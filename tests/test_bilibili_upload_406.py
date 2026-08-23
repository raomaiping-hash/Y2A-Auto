"""Bilibili 上传 406 限流与指纹判定的单元测试。"""

import unittest

from modules import bilibili_uploader as bu


class FakeNetExc:
    def __init__(self, code, raw):
        self.code = code
        self.raw = raw


class Bilibili406DetectionTests(unittest.TestCase):
    def test_rate_limited_detected(self):
        """HTTP 406 + body code 601（上传过快）应判定为限流而非普通指纹风控。"""
        exc = FakeNetExc(406, {"code": 601, "message": "您上传视频过快，请您稍作休息后再继续"})
        self.assertTrue(bu._is_bilibili_rate_limited(exc))
        self.assertFalse(bu._is_bilibili_http_406(exc))

    def test_generic_fingerprint_detected(self):
        """HTTP 406 但无业务消息时，仍按普通风控处理。"""
        exc = FakeNetExc(406, {})
        self.assertFalse(bu._is_bilibili_rate_limited(exc))
        self.assertTrue(bu._is_bilibili_http_406(exc))

    def test_extract_body_message(self):
        exc = FakeNetExc(406, {"code": 601, "message": "您上传视频过快，请您稍作休息后再继续"})
        self.assertIn("上传视频过快", bu._extract_response_body_message(exc))

    def test_rate_limit_hint_mentions_cooldown(self):
        self.assertIn("冷却", bu._bilibili_rate_limit_hint())
        self.assertIn("重新上传", bu._bilibili_rate_limit_hint())


if __name__ == '__main__':
    unittest.main()
