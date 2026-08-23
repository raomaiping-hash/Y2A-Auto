#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import tempfile
import unittest
from unittest.mock import patch


def _install_stubs():
    if "modules.utils" not in sys.modules:
        import types
        m = types.ModuleType("modules.utils")
        m.get_app_subdir = lambda subdir_name: os.path.join(os.getcwd(), "temp", "unit-tests", subdir_name)
        sys.modules["modules.utils"] = m
        # config_manager stub
    if "modules.config_manager" not in sys.modules:
        import types
        m = types.ModuleType("modules.config_manager")
        m.load_config = lambda: {}
        sys.modules["modules.config_manager"] = m
    if "modules.task_manager" not in sys.modules:
        import types
        m = types.ModuleType("modules.task_manager")
        m.add_task = lambda *a, **k: None
        sys.modules["modules.task_manager"] = m
    if "httplib2" not in sys.modules:
        import types
        m = types.ModuleType("httplib2")
        m.HttpLib2Error = type("HttpLib2Error", (Exception,), {})
        m.proxy_info_from_url = lambda url, method=None: {}
        sys.modules["httplib2"] = m
    if "apscheduler.schedulers.background" not in sys.modules:
        import types
        m = types.ModuleType("apscheduler.schedulers.background")
        class _S:
            def __init__(self, *a, **k): self.running = False
            def start(self): self.running = True
            def shutdown(self, *a, **k): self.running = False
        m.BackgroundScheduler = _S
        sys.modules["apscheduler"] = types.ModuleType("apscheduler")
        sys.modules["apscheduler.schedulers"] = types.ModuleType("apscheduler.schedulers")
        sys.modules["apscheduler.schedulers.background"] = m
    if "googleapiclient.discovery" not in sys.modules:
        import types
        d = types.ModuleType("googleapiclient.discovery")
        d.build = lambda *a, **k: object()
        sys.modules["googleapiclient"] = types.ModuleType("googleapiclient")
        sys.modules["googleapiclient.discovery"] = d
        e = types.ModuleType("googleapiclient.errors")
        e.HttpError = type("HttpError", (Exception,), {})
        sys.modules["googleapiclient.errors"] = e


try:
    from modules.youtube_monitor import YouTubeMonitor
except ModuleNotFoundError:
    _install_stubs()
    sys.modules.pop("modules.youtube_monitor", None)
    from modules.youtube_monitor import YouTubeMonitor


def _make_monitor(db_path):
    m = YouTubeMonitor.__new__(YouTubeMonitor)
    m.db_path = db_path
    m.api_key = None
    m.youtube = None
    m.youtube_http = None
    m._api_proxy_enabled = False
    m._last_api_init_error = None
    m._last_fetch_had_errors = False
    # 建表
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_configs (
            id INTEGER PRIMARY KEY,
            name TEXT, enabled BOOLEAN, monitor_type TEXT, channel_mode TEXT,
            video_types TEXT, historical_offset INTEGER DEFAULT 0,
            rate_limit_requests INTEGER DEFAULT 20, rate_limit_window INTEGER DEFAULT 60,
            max_results INTEGER DEFAULT 20, auto_add_to_tasks BOOLEAN
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS monitor_history (
            id INTEGER PRIMARY KEY, config_id INTEGER, video_id TEXT,
            added_to_tasks BOOLEAN
        )
        """)
        conn.commit()
    return m


def _seed_config(db_path, config_id=11, offset=0, auto_add=True, rate_limit=20, max_results=20):
    import sqlite3
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO monitor_configs (id, name, enabled, monitor_type, channel_mode, video_types, "
            "historical_offset, rate_limit_requests, max_results, auto_add_to_tasks) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (config_id, 'cfg', 1, 'channel_search', 'historical', 'video',
             offset, rate_limit, max_results, 1 if auto_add else 0)
        )
        conn.commit()


class YouTubeMonitorHistoricalOffsetTests(unittest.TestCase):
    def test_update_progress_advances_by_consumed_count(self):
        """offset 应由 consumed_count 推进，而不是 added_count。"""
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, 'youtube_monitor.db')
        monitor = _make_monitor(db)
        _seed_config(db, config_id=11, offset=0)

        # 267 个候选，本轮消费（含去重跳过）20 个
        all_filtered = [{'id': f'v{i}'} for i in range(267)]
        monitor._update_historical_progress(11, all_filtered, consumed_count=20)
        cfg = monitor.get_monitor_config(11)
        self.assertEqual(cfg['historical_offset'], 20)

    def test_update_progress_marks_done_when_offset_reaches_total(self):
        """完成判定：current_offset + consumed_count >= 候选总数。"""
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, 'youtube_monitor.db')
        monitor = _make_monitor(db)
        _seed_config(db, config_id=11, offset=247)

        all_filtered = [{'id': f'v{i}'} for i in range(267)]
        # 剩余 20 个，消费 20 个 -> offset 267 == total
        monitor._update_historical_progress(11, all_filtered, consumed_count=20)
        cfg = monitor.get_monitor_config(11)
        self.assertEqual(cfg['historical_offset'], 267)

    def test_update_progress_ignores_added_count_for_offset(self):
        """auto_add=False 时 added_count 恒为 0，但 offset 仍应推进（解耦）。"""
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, 'youtube_monitor.db')
        monitor = _make_monitor(db)
        # auto_add=False（added 恒为 0），但 consumed 仍应推进 offset
        _seed_config(db, config_id=11, offset=10, auto_add=False)

        all_filtered = [{'id': f'v{i}'} for i in range(100)]
        monitor._update_historical_progress(11, all_filtered, consumed_count=5)
        cfg = monitor.get_monitor_config(11)
        # offset 只按 consumed 推进，不受 added 影响
        self.assertEqual(cfg['historical_offset'], 15)

    def test_run_loop_counts_dedup_skipped_as_consumed(self):
        """被去重跳过的视频也应计入 consumed（否则 offset 漂移/重扫）。"""
        tmp = tempfile.mkdtemp()
        db = os.path.join(tmp, 'youtube_monitor.db')
        monitor = _make_monitor(db)
        _seed_config(db, config_id=11, offset=0, rate_limit=20, max_results=20)

        import sqlite3
        # 预先标记前 5 个视频已处理（去重会跳过它们）
        with sqlite3.connect(db) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO monitor_history (config_id, video_id, added_to_tasks) VALUES (?,?,?)",
                    (11, f'v{i}', 0)
                )
            conn.commit()

        # 候选 1..20（模拟已应用 offset 后），前 5 个去重跳过
        filtered_videos = [{'id': f'v{i}', 'title': f'v{i}'} for i in range(20)]

        consumed_count = 0
        added_count = 0
        processed_count = 0
        auto_add_enabled = True
        max_add_to_tasks = 20

        for video in filtered_videos:
            consumed_count += 1
            if monitor._is_video_processed(video['id'], 11):
                continue
            processed_count += 1
            added_count += 1
            if processed_count >= 20:
                break

        # 5 个去重跳过 + 15 个新处理 = 20 个消费
        self.assertEqual(consumed_count, 20)
        # added 只统计新入队的（15），与 consumed 不同
        self.assertEqual(added_count, 15)
        self.assertEqual(processed_count, 15)


if __name__ == "__main__":
    unittest.main()
