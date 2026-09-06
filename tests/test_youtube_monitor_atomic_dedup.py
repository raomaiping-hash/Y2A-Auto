import os
import shutil
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


def _install_stubs():
    if "modules.utils" not in sys.modules:
        modules_utils = types.ModuleType("modules.utils")
        modules_utils.get_app_subdir = lambda subdir_name: os.path.join(os.getcwd(), "temp", "unit-tests", subdir_name)
        sys.modules["modules.utils"] = modules_utils

    if "modules.config_manager" not in sys.modules:
        modules_config_manager = types.ModuleType("modules.config_manager")
        modules_config_manager.load_config = lambda: {}
        sys.modules["modules.config_manager"] = modules_config_manager

    if "modules.task_manager" not in sys.modules:
        modules_task_manager = types.ModuleType("modules.task_manager")
        modules_task_manager.add_task = lambda *args, **kwargs: None
        sys.modules["modules.task_manager"] = modules_task_manager

    if "httplib2" not in sys.modules:
        httplib2_module = types.ModuleType("httplib2")

        class _StubHttpLib2Error(Exception):
            pass

        class _StubHttp:
            def __init__(self, timeout=None, proxy_info=None):
                self.timeout = timeout
                self.proxy_info = proxy_info

        httplib2_module.Http = _StubHttp
        httplib2_module.HttpLib2Error = _StubHttpLib2Error
        httplib2_module.proxy_info_from_url = lambda url, method=None: {"url": url, "method": method}
        sys.modules["httplib2"] = httplib2_module

    if "apscheduler.schedulers.background" not in sys.modules:
        apscheduler_module = types.ModuleType("apscheduler")
        apscheduler_schedulers_module = types.ModuleType("apscheduler.schedulers")
        apscheduler_background_module = types.ModuleType("apscheduler.schedulers.background")

        class _StubBackgroundScheduler:
            def __init__(self, *args, **kwargs):
                self.running = False
                self._jobs = {}

            def add_job(self, func=None, trigger=None, minutes=None, id=None, args=None, replace_existing=False):
                if id is not None:
                    self._jobs[id] = {"func": func, "trigger": trigger, "minutes": minutes, "args": args or []}

            def get_job(self, job_id):
                return self._jobs.get(job_id)

            def remove_job(self, job_id):
                self._jobs.pop(job_id, None)

            def start(self):
                self.running = True

            def shutdown(self, *args, **kwargs):
                self.running = False

        apscheduler_background_module.BackgroundScheduler = _StubBackgroundScheduler
        sys.modules["apscheduler"] = apscheduler_module
        sys.modules["apscheduler.schedulers"] = apscheduler_schedulers_module
        sys.modules["apscheduler.schedulers.background"] = apscheduler_background_module

    if "googleapiclient.discovery" not in sys.modules:
        googleapiclient_module = types.ModuleType("googleapiclient")
        discovery_module = types.ModuleType("googleapiclient.discovery")
        errors_module = types.ModuleType("googleapiclient.errors")
        http_module = types.ModuleType("googleapiclient.http")

        class _StubHttpError(Exception):
            pass

        discovery_module.build = lambda *args, **kwargs: object()
        errors_module.HttpError = _StubHttpError
        http_module.DEFAULT_HTTP_TIMEOUT_SEC = 120

        sys.modules["googleapiclient"] = googleapiclient_module
        sys.modules["googleapiclient.discovery"] = discovery_module
        sys.modules["googleapiclient.errors"] = errors_module
        sys.modules["googleapiclient.http"] = http_module


try:
    from modules.youtube_monitor import API_INIT_STATUS_MISSING_API_KEY, YouTubeMonitor
    from modules.task_manager import add_task
except ModuleNotFoundError:
    _install_stubs()
    sys.modules.pop("modules.youtube_monitor", None)
    from modules.youtube_monitor import API_INIT_STATUS_MISSING_API_KEY, YouTubeMonitor
    from modules.task_manager import add_task


def _iso(dt_str):
    return f"{dt_str}T00:00:00Z"


def _make_video_dict(vid, published_at):
    return {
        "id": vid,
        "snippet": {
            "title": f"Video {vid}",
            "channelTitle": "TestChannel",
            "channelId": "UCtest",
            "publishedAt": published_at,
            "liveBroadcastContent": "none",
        },
        "contentDetails": {"duration": "PT5M"},
        "statistics": {"viewCount": "100", "likeCount": "10", "commentCount": "1"},
    }


class _FakeYouTube:
    """模拟 YouTube playlistItems / videos / channels 分页数据。"""

    def __init__(self, pages, published_after):
        # pages: list of {"items": [...], "nextPageToken": str|None}
        self._pages = pages
        self._published_after = published_after
        self.playlist_requests = 0

    def channels(self):
        class _Ch:
            def list(self, **kw):
                return _Resp({"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UPLOAD"}}}]})

        return _Ch()

    def playlistItems(self):
        class _P:
            def __init__(self, fake):
                self._fake = fake

            def list(self, **kw):
                self._fake.playlist_requests += 1
                # 第一页无 pageToken
                token = kw.get("pageToken")
                if token is None:
                    idx = 0
                else:
                    idx = int(token.replace("p", ""))
                if idx >= len(self._fake._pages):
                    return _Resp({"items": []})
                page = self._fake._pages[idx]
                next_token = page.get("nextPageToken")
                return _Resp({"items": page["items"], "nextPageToken": next_token})

        return _P(self)

    def videos(self):
        class _V:
            def __init__(self, fake):
                self._fake = fake

            def list(self, **kw):
                ids = str(kw.get("id", "")).split(",")
                items = []
                for vid in ids:
                    for page in self._fake._pages:
                        for it in page["items"]:
                            if it["snippet"]["resourceId"]["videoId"] == vid:
                                items.append(_make_video_dict(vid, it["snippet"]["publishedAt"]))
                                break
                return _Resp({"items": items})

        return _V(self)


class _Resp:
    def __init__(self, data):
        self._data = data

    def execute(self):
        return self._data


class AtomicDedupTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.get_app_subdir_patcher = patch(
            "modules.youtube_monitor.get_app_subdir",
            side_effect=self._get_app_subdir,
        )
        self.init_api_patcher = patch.object(
            YouTubeMonitor,
            "_init_youtube_api",
            return_value=(False, API_INIT_STATUS_MISSING_API_KEY),
        )
        self.get_app_subdir_patcher.start()
        self.init_api_patcher.start()
        self.monitor = YouTubeMonitor()
        self.monitor.youtube = object()

    def tearDown(self):
        try:
            scheduler = getattr(self.monitor, "scheduler", None)
            if scheduler and getattr(scheduler, "running", False):
                scheduler.shutdown(wait=False)
        finally:
            self.get_app_subdir_patcher.stop()
            self.init_api_patcher.stop()
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _get_app_subdir(self, subdir_name):
        path = os.path.join(self.tmpdir, subdir_name)
        os.makedirs(path, exist_ok=True)
        return path

    def test_history_table_has_unique_index(self):
        import sqlite3
        with sqlite3.connect(self.monitor.db_path) as conn:
            rows = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_monitor_history_config_video'"
            ).fetchall()
        self.assertEqual(len(rows), 1)

    def test_atomic_insert_returns_is_new_semantics(self):
        config_id = self.monitor.create_monitor_config({"name": "atomic"})
        info = {
            "id": "v1", "title": "V1", "channel_title": "TestChannel",
            "channel_id": "UCtest", "published_at": _iso("2024-01-01"),
            "duration": "PT5M", "view_count": 100, "like_count": 10,
            "comment_count": 1, "video_type": "video",
        }

        first = self.monitor._save_video_history(info, config_id, auto_add_to_tasks=False)
        self.assertTrue(first, "首次插入应为新记录")

        # 同一 (config_id, video_id) 再次插入应被唯一约束忽略，视为已存在
        second = self.monitor._save_video_history(info, config_id, auto_add_to_tasks=False)
        self.assertFalse(second, "重复插入应返回已存在")

        import sqlite3
        with sqlite3.connect(self.monitor.db_path) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM monitor_history WHERE config_id=? AND video_id=?",
                (config_id, "v1"),
            ).fetchone()[0]
        self.assertEqual(count, 1, "唯一约束应保证同配置同视频不重复入库")

    def test_enqueue_failed_leaves_added_zero_then_retries(self):
        """入队失败时 added_to_tasks 保持 0，下次运行再重试入队。"""
        config_id = self.monitor.create_monitor_config({
            "name": "retry-enqueue",
            "keywords": "test",
            "max_results": 10,
            "auto_add_to_tasks": True,
            "rate_limit_requests": 10,
            "schedule_type": "manual",
        })

        # 首次入队失败（返回 None），第二次运行才成功
        add_results = [None]
        original = self.monitor._add_video_to_tasks

        def fake_add(video_info, auto_start=True, config_id=None):
            call = add_results.pop(0) if add_results else None
            if call is None:
                return None
            return call

        candidate = _make_video_dict("v1", _iso("2024-01-01"))
        filtered_videos = [{
            "id": "v1", "title": "V1", "channel_title": "TestChannel",
            "channel_id": "UCtest", "published_at": _iso("2024-01-01"),
            "duration": "PT5M", "view_count": 100, "like_count": 10,
            "comment_count": 1, "video_type": "video",
        }]

        with patch.object(YouTubeMonitor, "_fetch_videos", return_value=[candidate]), \
                patch.object(YouTubeMonitor, "_meets_criteria", return_value=True), \
                patch.object(YouTubeMonitor, "_detect_video_type", return_value="video"), \
                patch.object(YouTubeMonitor, "_add_video_to_tasks", side_effect=fake_add):
            # 第一次运行：首候选插库后入队失败（返回 None）
            ok, msg = self.monitor.run_monitor(config_id)
            self.assertTrue(ok, f"第一轮应成功: {msg}")

        import sqlite3
        with sqlite3.connect(self.monitor.db_path) as conn:
            row = conn.execute(
                "SELECT added_to_tasks FROM monitor_history WHERE config_id=? AND video_id=?",
                (config_id, "v1"),
            ).fetchone()
        self.assertEqual(row[0], 0, "入队失败后 added_to_tasks 应保持 0")

        # 第二次运行：add_queue 仍成功（本次返回 task-id），应补标记为已添加
        add_results = ["task-id-456"]
        filtered_videos2 = [{
            "id": "v1", "title": "V1", "channel_title": "TestChannel",
            "channel_id": "UCtest", "published_at": _iso("2024-01-01"),
            "duration": "PT5M", "view_count": 100, "like_count": 10,
            "comment_count": 1, "video_type": "video",
        }]
        with patch.object(YouTubeMonitor, "_fetch_videos", return_value=[candidate]), \
                patch.object(YouTubeMonitor, "_meets_criteria", return_value=True), \
                patch.object(YouTubeMonitor, "_detect_video_type", return_value="video"), \
                patch.object(YouTubeMonitor, "_add_video_to_tasks", side_effect=fake_add):
            ok, msg = self.monitor.run_monitor(config_id)
            self.assertTrue(ok, f"第二轮应成功: {msg}")

        with sqlite3.connect(self.monitor.db_path) as conn:
            row = conn.execute(
                "SELECT added_to_tasks FROM monitor_history WHERE config_id=? AND video_id=?",
                (config_id, "v1"),
            ).fetchone()
        self.assertEqual(row[0], 1, "重试成功入队后 added_to_tasks 应置 1")

    def test_cross_config_task_dedup_skips_add_task(self):
        """跨配置重复建任务去重：_find_existing_task_for_url 命中时不再调用 add_task。"""
        config_id = self.monitor.create_monitor_config({
            "name": "cross-dedup", "auto_add_to_tasks": True,
        })
        info = {
            "id": "v1", "title": "V1", "channel_title": "TestChannel",
            "channel_id": "UCtest", "published_at": _iso("2024-01-01"),
            "duration": "PT5M", "view_count": 100, "like_count": 10,
            "comment_count": 1, "video_type": "video",
        }

        with patch.object(YouTubeMonitor, "_find_existing_task_for_url", return_value="existing-task-777"), \
                patch("modules.youtube_monitor.add_task", return_value="new-task-xxx") as mock_add:
            result = self.monitor._add_video_to_tasks(info, auto_start=True, config_id=config_id)

        self.assertEqual(result, "existing-task-777")
        mock_add.assert_not_called()


class PaginationBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.get_app_subdir_patcher = patch(
            "modules.youtube_monitor.get_app_subdir",
            side_effect=self._get_app_subdir,
        )
        self.init_api_patcher = patch.object(
            YouTubeMonitor,
            "_init_youtube_api",
            return_value=(False, API_INIT_STATUS_MISSING_API_KEY),
        )
        self.get_app_subdir_patcher.start()
        self.init_api_patcher.start()
        self.monitor = YouTubeMonitor()
        self.monitor.youtube = object()

    def tearDown(self):
        try:
            scheduler = getattr(self.monitor, "scheduler", None)
            if scheduler and getattr(scheduler, "running", False):
                scheduler.shutdown(wait=False)
        finally:
            self.get_app_subdir_patcher.stop()
            self.init_api_patcher.stop()
            shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _get_app_subdir(self, subdir_name):
        path = os.path.join(self.tmpdir, subdir_name)
        os.makedirs(path, exist_ok=True)
        return path

    def _make_playlist_item(self, vid, published_at):
        return {
            "snippet": {
                "publishedAt": published_at,
                "resourceId": {"videoId": vid},
                "title": f"V{vid}",
                "channelTitle": "TestChannel",
                "channelId": "UCtest",
            }
        }

    def test_historical_pagination_covers_beyond_500_and_stops_at_boundary(self):
        """历史模式不应再受固定 500 上限限制，且应翻页直到按时间窗口边界停止。"""
        # 构造 12 页 x 50 = 600 条，模拟新的在前：前 11 页在窗口内，最后一页到达边界
        pages = []
        for page_idx in range(12):
            items = []
            for j in range(50):
                vid = f"h{page_idx * 50 + j}"
                # 前 11 页：从很新到接近边界；第 12 页：明显早于 published_after
                if page_idx < 11:
                    published_at = _iso(f"2024-{12 - page_idx:02d}-{30 - j:02d}")
                else:
                    published_at = _iso("2023-12-01")
                items.append(self._make_playlist_item(vid, published_at))
            next_token = f"p{page_idx + 1}" if page_idx < 11 else None
            pages.append({"items": items, "nextPageToken": next_token})

        published_after = "2024-01-01T00:00:00Z"
        self.monitor.youtube = _FakeYouTube(pages, published_after)
        config = {"channel_ids": "UCtest", "channel_mode": "historical", "max_results": 20}

        videos = self.monitor._fetch_channel_playlist_videos("UCtest", config, published_after, None)

        self.assertGreater(len(videos), 500, f"历史模式不应被固定 500 截断, 实际 {len(videos)}")
        # 应到达时间窗口边界
        self.assertTrue(self.monitor._last_channel_reached_boundary)

    def test_latest_pagination_covers_beyond_latest_max_results(self):
        """latest 模式翻页直到覆盖 last_run_time，不应只取 latest_max_results 条。"""
        pages = []
        # 第一页 20 条（latest_max_results=20），第二页 15 条到达边界
        for idx, count in enumerate((20, 15)):
            items = []
            for j in range(count):
                vid = f"l{idx*20+j}"
                if idx == 0:
                    published_at = _iso(f"2024-06-{30 - j:02d}")
                else:
                    published_at = _iso("2024-01-01")
                items.append(self._make_playlist_item(vid, published_at))
            next_token = "p1" if idx == 0 else None
            pages.append({"items": items, "nextPageToken": next_token})

        published_after = "2024-05-01T00:00:00Z"
        self.monitor.youtube = _FakeYouTube(pages, published_after)
        config = {"channel_ids": "UCtest", "channel_mode": "latest", "latest_max_results": 20, "max_results": 20}

        videos = self.monitor._fetch_channel_playlist_videos("UCtest", config, published_after, None)

        # 第一页 20 条都在窗口内（>2024-05-01），第二页 15 条到达边界（2024-01-01）
        # 应覆盖到 20 条之外的视频，证明已翻页而非固定 latest_max_results
        self.assertGreater(
            self.monitor.youtube.playlist_requests, 1,
            "latest 模式应翻页直到覆盖 last_run_time, 而非仅取固定条数",
        )


class ProxyConstructionTests(unittest.TestCase):
    def _monitor(self):
        m = YouTubeMonitor.__new__(YouTubeMonitor)
        m.api_key = None
        m.youtube = None
        m.youtube_http = None
        m._api_proxy_enabled = False
        m._last_api_init_error = None
        return m

    def test_proxy_enabled_constructs_independent_proxy_info(self):
        m = self._monitor()
        http = m._build_youtube_http({
            "YOUTUBE_API_PROXY_ENABLED": True,
            "YOUTUBE_API_PROXY_URL": "http://my-proxy.example.com:7890",
        })
        self.assertTrue(m._api_proxy_enabled)
        # 独立代理启用时 httplib2 只能通过这部分 proxy_info 走代理，host 为配置的独立代理
        self.assertIsNotNone(http.proxy_info)
        self.assertTrue(callable(http.proxy_info))

    def test_proxy_disabled_returns_direct_http(self):
        m = self._monitor()
        http = m._build_youtube_http({"YOUTUBE_API_PROXY_ENABLED": False})
        self.assertFalse(m._api_proxy_enabled)
        # 直连时 proxy_info 为 None，httplib2 不会命中任何环境代理，避免与环境代理串扰
        self.assertIsNone(http.proxy_info)


if __name__ == "__main__":
    unittest.main()
