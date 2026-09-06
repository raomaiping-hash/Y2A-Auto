"""AcFun 上传链路修复与 B 站限流/eTag 判定的补充单元测试。

覆盖：
- AcFun 请求会话本机直连（trust_env=False），与 B 站/YouTube 出口语义一致；
- AcFun 上传层保留单一重试源（不再叠加 HTTPAdapter 自动重试）；
- complete_upload 失败显式返回并让上传流程感知（不再静默生成残缺投稿）；
- B 站限流优先按 body 业务码（601/6022）判定，文案变体（太快/过频）不再误判为 406；
- B 站分块 ETag 大小写兼容读取并回填到 complete 请求。
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import types
import unittest
from unittest import mock

from modules import bilibili_uploader as bu
from modules.acfun_uploader import AcfunUploader, make_acfun_session
from modules.acfun_auth import AcfunQrLoginSession
from modules.bili_sdk.video_uploader import VideoUploader, _pick_etag
from modules.bili_sdk.utils.AsyncEvent import AsyncEvent


class FakeNetExc:
    def __init__(self, code, raw):
        self.code = code
        self.raw = raw


class _FakeResponse:
    def __init__(self, code=200, text="MULTIPART_PUT_SUCCESS", headers=None):
        self.code = code
        self.status_code = code
        self._text = text
        self.headers = headers or {}

    def utf8_text(self):
        return self._text

    def json(self):
        return json.loads(self._text)


class AcfunProxyConsistencyTests(unittest.TestCase):
    def test_make_acfun_session_disables_trust_env(self):
        session = make_acfun_session()
        self.assertFalse(session.trust_env)

    def test_acfun_uploader_session_disables_trust_env(self):
        uploader = AcfunUploader()
        self.assertFalse(uploader.session.trust_env)

    def test_acfun_qr_login_session_disables_trust_env(self):
        session = AcfunQrLoginSession()
        self.assertFalse(session.session.trust_env)

    def test_upload_chunk_uses_direct_session_and_single_retry(self):
        # 分块上传：只应由显式 for 循环负责重试（单层），且使用本机直连会话。
        uploader = AcfunUploader()
        uploader.logger = mock.Mock()
        post_counts = {"n": 0}

        def fake_post(*args, **kwargs):
            post_counts["n"] += 1
            if post_counts["n"] < 2:
                return _FakeResponse(503)
            response = _FakeResponse(200)
            response.json = mock.Mock(return_value={"result": 1})
            return response

        fake_session = mock.Mock()
        fake_session.post = fake_post
        fake_session.trust_env = False

        with mock.patch(
            "modules.acfun_uploader.make_acfun_session",
            return_value=fake_session,
        ), mock.patch(
            "modules.acfun_uploader.time.sleep",
        ):
            ok = uploader.upload_chunk(b"data", 0, "token")

        self.assertTrue(ok)
        # 仅手动层重试（1 次失败 + 1 次成功），不应有 HTTPAdapter 叠加。
        self.assertEqual(post_counts["n"], 2)


class AcfunCompleteUploadTests(unittest.TestCase):
    def _uploader(self):
        return AcfunUploader()

    def test_complete_upload_returns_true_on_success(self):
        uploader = self._uploader()
        fake_post = mock.Mock()
        fake_response = _FakeResponse(200)
        fake_response.json = mock.Mock(return_value={"result": 1})
        fake_post.return_value = fake_response

        with mock.patch(
            "modules.acfun_uploader.make_acfun_session",
            return_value=mock.Mock(post=fake_post),
        ):
            result = uploader.complete_upload(3, "token")

        self.assertTrue(result)

    def test_complete_upload_returns_false_on_business_failure(self):
        uploader = self._uploader()
        fake_post = mock.Mock()
        fake_response = _FakeResponse(200)
        fake_response.json = mock.Mock(return_value={"result": 2, "message": "failed"})
        fake_post.return_value = fake_response

        with mock.patch(
            "modules.acfun_uploader.make_acfun_session",
            return_value=mock.Mock(post=fake_post),
        ):
            result = uploader.complete_upload(3, "token")

        self.assertFalse(result)

    def test_create_douga_fails_when_complete_upload_fails(self):
        uploader = self._uploader()
        uploader.logger = mock.Mock()

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = os.path.join(temp_dir, "video.mp4")
            cover_path = os.path.join(temp_dir, "cover.jpg")
            with open(video_path, "wb") as f:
                f.write(b"abcdefgh")

            with mock.patch.object(
                uploader, "get_token", return_value=("1", "tok", 100)
            ), mock.patch.object(
                uploader, "upload_chunk", return_value=True
            ), mock.patch.object(
                uploader, "complete_upload", return_value=False
            ):
                ok, result = uploader.create_douga(
                    video_path, "标题", 1, cover_path, desc="简介"
                )

        self.assertFalse(ok)
        self.assertIn("上传完成确认失败", result)


class BilibiliRateLimitBodyCodeTests(unittest.TestCase):
    def test_rate_limited_when_body_code_601_with_variant_text(self):
        # body 里有业务码 601，文案是“太快”变体：应判限流而非指纹 406。
        exc = FakeNetExc(406, {"code": 601, "message": "您上传太快了，请稍后再试"})
        self.assertTrue(bu._is_bilibili_rate_limited(exc))
        self.assertFalse(bu._is_bilibili_http_406(exc))

    def test_rate_limited_when_body_code_6022(self):
        exc = FakeNetExc(406, {"code": 6022, "message": "提交过于频繁"})
        self.assertTrue(bu._is_bilibili_rate_limited(exc))
        self.assertFalse(bu._is_bilibili_http_406(exc))

    def test_rate_limited_by_text_marker_frequency(self):
        # 无业务码时，文案仍可兜底识别（“过于频繁”）。
        exc = FakeNetExc(406, {"message": "您的操作过于频繁，请稍作休息"})
        self.assertTrue(bu._is_bilibili_rate_limited(exc))
        self.assertFalse(bu._is_bilibili_http_406(exc))

    def test_generic_406_without_signal_is_fingerprint(self):
        exc = FakeNetExc(406, {})
        self.assertFalse(bu._is_bilibili_rate_limited(exc))
        self.assertTrue(bu._is_bilibili_http_406(exc))


class BilibiliRuntimeHotReloadTests(unittest.TestCase):
    def test_config_reapplies_on_each_call(self):
        import modules.bilibili_runtime as runtime

        runtime = importlib.reload(runtime)
        calls = []
        fake_settings = types.SimpleNamespace(
            set=lambda key, value: calls.append((key, value))
        )
        fake_bili_sdk = types.SimpleNamespace(request_settings=fake_settings)

        # 默认直连：设置 impersonate 与 trust_env=False
        with mock.patch.dict(sys.modules, {"modules.bili_sdk": fake_bili_sdk}):
            self.assertTrue(runtime.configure_bilibili_runtime())
        self.assertIn(("impersonate", "chrome131"), calls)
        self.assertIn(("trust_env", False), calls)

        # 关闭直连后再次调用：应刷新 trust_env 回到 True（热更新生效）。
        with mock.patch.dict(sys.modules, {"modules.bili_sdk": fake_bili_sdk}), mock.patch.dict(
            os.environ, {"BILIBILI_DIRECT_CONNECT": "0"}
        ):
            self.assertTrue(runtime.configure_bilibili_runtime())
        self.assertIn(("trust_env", True), calls)

    def test_direct_connect_disabled_does_not_set_trust_env_false(self):
        import modules.bilibili_runtime as runtime

        runtime = importlib.reload(runtime)
        calls = []
        fake_settings = types.SimpleNamespace(
            set=lambda key, value: calls.append((key, value))
        )
        fake_bili_sdk = types.SimpleNamespace(request_settings=fake_settings)

        with mock.patch.dict(sys.modules, {"modules.bili_sdk": fake_bili_sdk}), mock.patch.dict(
            os.environ, {"BILIBILI_DIRECT_CONNECT": "0"}
        ):
            self.assertTrue(runtime.configure_bilibili_runtime())

        self.assertNotIn(("trust_env", False), calls)
        self.assertIn(("impersonate", "chrome131"), calls)


class BilibiliEtagTests(unittest.TestCase):
    def test_pick_etag_case_insensitive(self):
        self.assertEqual(_pick_etag({"etag": "a"}), "a")
        self.assertEqual(_pick_etag({"ETag": "b"}), "b")
        self.assertEqual(_pick_etag({"Etag": "c"}), "c")
        self.assertEqual(_pick_etag({}), "")
        self.assertEqual(_pick_etag(None), "")

    def _run_complete_page(self, chunks, etags):
        uploader = object.__new__(VideoUploader)
        AsyncEvent.__init__(uploader)
        uploader.line = None
        page = mock.Mock()
        page.path = "/tmp/video.mp4"

        body_capture = {}

        async def _request(**kwargs):
            body_capture["body"] = kwargs.get("data")
            return _FakeResponse(200, text='{"OK":1,"key":"/video.mp4"}')

        session = mock.Mock()
        session.request = _request
        preupload = {
            "endpoint": "//upload.example.com",
            "biz_id": 1,
            "auth": "auth",
            "upos_uri": "upos://bucket/video.mp4",
        }

        with mock.patch(
            "modules.bili_sdk.video_uploader.get_client",
            return_value=session,
        ):
            result = asyncio.run(
                uploader._complete_page(page, chunks, preupload, "u", etags)
            )
        return result, json.loads(body_capture["body"])["parts"]

    def test_complete_page_builds_parts_with_real_etag(self):
        result, parts = self._run_complete_page(3, ["etc1", "etc2", "etc3"])
        self.assertEqual(result["cid"], 1)
        self.assertEqual([p["eTag"] for p in parts], ["etc1", "etc2", "etc3"])

    def test_complete_page_falls_back_to_etag_when_missing(self):
        result, parts = self._run_complete_page(2, ["real1", ""])
        self.assertEqual(parts[0]["eTag"], "real1")
        self.assertEqual(parts[1]["eTag"], "etag")


if __name__ == "__main__":
    unittest.main()
