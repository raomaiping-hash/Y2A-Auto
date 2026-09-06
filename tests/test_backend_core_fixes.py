# -*- coding: utf-8 -*-
"""后端核心修复（团队任务 t4）行为回归测试。

覆盖：
- recover_interrupted_tasks_to_pending：双平台仅部分成功恢复为 PENDING（可自动续传）
- _infer_completed_stages_from_task：按配置要求分别校验译名/译简介，不再用 "任一存在" 误判
- _get_effective_metadata_limits：限制值走 config_manager 可配置键（DEFAULT 兜底）
- update_task：用 db_connect 上下文 + BEGIN IMMEDIATE 原子读写
- reset_stuck_tasks：卡死看门狗超阈值强制重置并释放并发槽
- _sync_task_semaphore_capacity / _effective_max_concurrent_tasks：内存降并发真正生效
"""

import sqlite3
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from modules import task_manager as tm


class TempTaskDBTestCase(unittest.TestCase):
    """为每个用例准备独立临时 SQLite 库，并接管 tm.DB_PATH。"""

    MINIMAL_TASKS_SCHEMA = '''
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            youtube_url TEXT NOT NULL,
            upload_target TEXT DEFAULT 'acfun',
            status TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            video_title_original TEXT,
            video_title_translated TEXT,
            description_original TEXT,
            description_translated TEXT,
            pipeline_checkpoint TEXT,
            acfun_upload_response TEXT,
            bilibili_upload_response TEXT,
            error_message TEXT
        )
    '''

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self._tmp.close()
        self._db_path = self._tmp.name
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute(self.MINIMAL_TASKS_SCHEMA)
        conn.commit()
        conn.close()
        self._db_patcher = patch.object(tm, 'DB_PATH', self._db_path)
        self._db_patcher.start()

    def tearDown(self):
        self._db_patcher.stop()
        import os
        try:
            os.unlink(self._db_path)
        except OSError:
            pass

    def _insert_task(self, task_id, **fields):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        base = {'id': task_id, 'youtube_url': 'https://youtube.com/watch?v=test',
                'upload_target': 'acfun', 'status': 'processing'}
        base.update(fields)
        cols = list(base.keys())
        conn.execute(
            "INSERT INTO tasks ({}) VALUES ({})".format(
                ', '.join(cols), ', '.join(['?'] * len(cols))
            ),
            [base[c] for c in cols],
        )
        conn.commit()
        conn.close()

    def _set_task_stale(self, task_id, minutes=31):
        """用 SQLite 自身时间表达式把 updated_at 写旧，与查询里的 datetime('now') 对齐。"""
        conn = sqlite3.connect(self._db_path)
        conn.execute(
            "UPDATE tasks SET updated_at = datetime('now', ?) WHERE id = ?",
            (f'-{minutes} minutes', task_id),
        )
        conn.commit()
        conn.close()

    def _read_task_status(self, task_id):
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute('SELECT status FROM tasks WHERE id = ?', (task_id,)).fetchone()
        conn.close()
        return row['status'] if row else None


class RecoverInterruptedTasksTests(TempTaskDBTestCase):
    def test_partial_upload_both_recovers_to_pending(self):
        """双平台仅部分成功（如 acfun 已传、bili 未传）应恢复为 pending，而非 failed。

        pending 会被定时扫描器自动捡起，走 _has_partial_upload_success 失败点续传。
        """
        self._insert_task(
            'partial-both',
            upload_target='both',
            status='uploading',
            acfun_upload_response='{"video_id": 1}',
            bilibili_upload_response=None,
        )
        count = tm.recover_interrupted_tasks_to_pending()
        self.assertEqual(count, 1)
        self.assertEqual(self._read_task_status('partial-both'), tm.TASK_STATES['PENDING'])

    def test_full_upload_both_recovers_to_completed(self):
        self._insert_task(
            'full-both',
            upload_target='both',
            status='uploading',
            acfun_upload_response='{"video_id": 1}',
            bilibili_upload_response='{"bvid": "BV1"}',
        )
        tm.recover_interrupted_tasks_to_pending()
        self.assertEqual(self._read_task_status('full-both'), tm.TASK_STATES['COMPLETED'])

    def test_no_upload_recovers_to_pending(self):
        self._insert_task('no-up', upload_target='both', status='downloading')
        tm.recover_interrupted_tasks_to_pending()
        self.assertEqual(self._read_task_status('no-up'), tm.TASK_STATES['PENDING'])


class InferCompletedStagesTests(unittest.TestCase):
    def _infer(self, task, cfg):
        with patch('modules.config_manager.load_config', return_value=cfg):
            return tm._infer_completed_stages_from_task(task)

    def test_translate_stage_requires_all_configured_fields(self):
        """标题已译但简介缺失（且配置要求译简介）时不得标翻译完成。"""
        task = {
            'video_title_original': 'Title',
            'video_title_translated': '译名',
            'description_original': 'Desc',
            'description_translated': None,
        }
        cfg = {'TRANSLATE_TITLE': True, 'TRANSLATE_DESCRIPTION': True}
        self.assertNotIn(tm.PIPELINE_STAGE_TRANSLATE_CONTENT, self._infer(task, cfg))

    def test_translate_stage_completed_when_all_present(self):
        task = {
            'video_title_original': 'Title',
            'video_title_translated': '译名',
            'description_original': 'Desc',
            'description_translated': '译介',
        }
        cfg = {'TRANSLATE_TITLE': True, 'TRANSLATE_DESCRIPTION': True}
        self.assertIn(tm.PIPELINE_STAGE_TRANSLATE_CONTENT, self._infer(task, cfg))

    def test_translate_disabled_stage_not_marked_completed(self):
        """翻译完全关闭时不应标翻译完成，避免今后开启翻译后跳过翻译阶段。"""
        task = {
            'video_title_original': 'Title',
            'description_original': 'Desc',
        }
        cfg = {'TRANSLATE_TITLE': False, 'TRANSLATE_DESCRIPTION': False}
        completed = self._infer(task, cfg)
        self.assertNotIn(tm.PIPELINE_STAGE_TRANSLATE_CONTENT, completed)


class EffectiveMetadataLimitsTests(unittest.TestCase):
    def test_limits_follow_configured_keys(self):
        with patch('modules.config_manager.get_config_default', side_effect=lambda key: {
            'METADATA_TITLE_LIMIT_BILIBILI': 80,
            'METADATA_DESCRIPTION_LIMIT_BILIBILI': 800,
            'METADATA_TITLE_LIMIT_ACFUN': 50,
            'METADATA_DESCRIPTION_LIMIT_ACFUN': 1000,
        }.get(key)):
            self.assertEqual(
                tm._get_effective_metadata_limits('bilibili'),
                {'title_limit': 80, 'description_limit': 800},
            )
            self.assertEqual(
                tm._get_effective_metadata_limits('acfun'),
                {'title_limit': 50, 'description_limit': 1000},
            )

    def test_limits_fall_back_to_literals_when_config_missing(self):
        with patch('modules.config_manager.get_config_default', return_value=None):
            self.assertEqual(
                tm._get_effective_metadata_limits('bilibili'),
                {'title_limit': 80, 'description_limit': 800},
            )


class UpdateTaskTests(TempTaskDBTestCase):
    @patch.object(tm, 'publish_task_event')
    @patch.object(tm, 'emit_notification_event')
    def test_update_task_uses_db_connect_and_commits(self, emit_mock, publish_mock):
        self._insert_task('upd-1', status='processing')
        ok = tm.update_task('upd-1', status='pending', silent=True)
        self.assertTrue(ok)
        self.assertEqual(self._read_task_status('upd-1'), 'pending')

    @patch.object(tm, 'publish_task_event')
    @patch.object(tm, 'emit_notification_event')
    def test_update_task_fires_completion_notification(self, emit_mock, publish_mock):
        self._insert_task('upd-2', status='processing')
        ok = tm.update_task('upd-2', status='completed')
        self.assertTrue(ok)
        self.assertEqual(self._read_task_status('upd-2'), 'completed')
        self.assertTrue(emit_mock.called)


class StuckWatchdogTests(TempTaskDBTestCase):
    @patch.object(tm, '_is_task_active', return_value=True)
    @patch.object(tm, '_force_release_task_slot')
    @patch.object(tm, '_mark_task_inactive')
    def test_stuck_watchdog_force_resets_after_cancel_threshold(
        self, mark_inactive, release_slot, is_active
    ):
        # 构造一个"卡死"任务：状态为处理中、updated_at 超过 30 分钟。
        self._insert_task('stuck-1', status='downloading')
        self._set_task_stale('stuck-1', minutes=31)
        # 模拟上一次扫描已下发取消请求且超过阈值仍未响应。
        with tm._STUCK_WATCHDOG_CANCEL_LOCK:
            tm._STUCK_WATCHDOG_CANCEL_ISSUED_AT['stuck-1'] = time.time() - 61

        reset_count = tm.reset_stuck_tasks(skip_active=True, cancel_active=True)
        self.assertEqual(reset_count, 1)
        self.assertEqual(self._read_task_status('stuck-1'), tm.TASK_STATES['FAILED'])
        mark_inactive.assert_called_once_with('stuck-1')
        release_slot.assert_called_once_with('stuck-1')


class ConcurrencySemaphoreTests(unittest.TestCase):
    def test_effective_max_reduces_when_memory_high(self):
        tp = tm.TaskProcessor.__new__(tm.TaskProcessor)
        tp.config = {'MAX_CONCURRENT_TASKS': 4}
        with patch.object(tm, '_should_reduce_concurrency', return_value=True):
            self.assertEqual(tp._effective_max_concurrent_tasks(), 2)
        with patch.object(tm, '_should_reduce_concurrency', return_value=False):
            self.assertEqual(tp._effective_max_concurrent_tasks(), 4)

    def test_sync_semaphore_rebuilds_capacity(self):
        tm.init_task_semaphore(2)
        tp = tm.TaskProcessor.__new__(tm.TaskProcessor)
        tp.config = {'MAX_CONCURRENT_TASKS': 2}
        tp._current_max_concurrent_tasks = 2
        tp._sync_task_semaphore_capacity(1)
        self.assertEqual(tm._TASK_SEMAPHORE_CURRENT_MAX, 1)
        # 恢复容量后应同步扩展回配置值。
        tm.init_task_semaphore(1)
        tp._current_max_concurrent_tasks = 1
        tp._sync_task_semaphore_capacity(2)
        self.assertEqual(tm._TASK_SEMAPHORE_CURRENT_MAX, 2)


class DibSegmentSignatureTests(unittest.TestCase):
    """dub.wav 二次拼接去冗余：签名比较决定是否需重拼接。"""

    @staticmethod
    def _seg(wav_path, duration_s):
        return type('Seg', (), {'wav_path': wav_path, 'duration_s': duration_s})()

    def test_signature_filters_invalid_and_orders_stable(self):
        segs = [
            self._seg('a.wav', 1.5),
            self._seg(None, 0.0),       # 无效：无路径
            self._seg('b.wav', 0.0),    # 无效：时长为 0
            self._seg('c.wav', 2.0),
        ]
        self.assertEqual(
            tm._dub_segments_signature(segs),
            (('a.wav', 1.5), ('c.wav', 2.0)),
        )

    def test_signature_detects_alignment_change(self):
        before = [self._seg('seg.wav', 3.0)]
        after = [self._seg('seg.wav.tempo.wav', 2.0)]  # atempo 变速后路径/时长变化
        self.assertNotEqual(
            tm._dub_segments_signature(before),
            tm._dub_segments_signature(after),
        )

    def test_signature_no_change_skips_reconcat(self):
        before = [self._seg('seg.wav', 1.0)]
        after = [self._seg('seg.wav', 1.0)]  # 对齐未改动片段
        self.assertEqual(
            tm._dub_segments_signature(before),
            tm._dub_segments_signature(after),
        )


if __name__ == '__main__':
    unittest.main()
