"""TTS 配音模块单元测试（时长拟合、请求构造、错误处理）。"""

import base64
import unittest
from unittest.mock import Mock, patch

from modules import tts_dub
from modules.tts_dub import FishAudioTtsClient, TtsDubError, build_atempo_chain, fit_cue_speed


class AtempoChainTests(unittest.TestCase):
    def test_speed_1_single_stage(self):
        self.assertEqual(build_atempo_chain(1.0), [1.0])

    def test_speed_within_single_stage_range(self):
        self.assertEqual(len(build_atempo_chain(1.6)), 1)
        self.assertAlmostEqual(build_atempo_chain(1.6)[0], 1.6, places=4)

    def test_speed_3_splits_into_two_stages(self):
        chain = build_atempo_chain(3.0)
        self.assertEqual(len(chain), 2)
        total = 1.0
        for c in chain:
            self.assertGreaterEqual(c, 0.5)
            self.assertLessEqual(c, 2.0)
            total *= c
        self.assertAlmostEqual(total, 3.0, places=3)

    def test_speed_below_half_splits(self):
        chain = build_atempo_chain(0.25)
        total = 1.0
        for c in chain:
            self.assertLessEqual(c, 2.0)
            total *= c
        self.assertAlmostEqual(total, 0.25, places=3)

    def test_invalid_speed_raises(self):
        with self.assertRaises(ValueError):
            build_atempo_chain(0)


class FitCueSpeedTests(unittest.TestCase):
    def test_shorter_tts_needs_no_speedup(self):
        self.assertEqual(fit_cue_speed(3.0, 10.0), 1.0)

    def test_longer_tts_speed_up_to_fit(self):
        # 8s 语音放进 4s 窗口 → 2x
        self.assertAlmostEqual(fit_cue_speed(8.0, 4.0), 2.0, places=3)

    def test_caps_at_max_fit_speed(self):
        self.assertAlmostEqual(fit_cue_speed(20.0, 4.0), 2.25, places=3)

    def test_zero_window_returns_1(self):
        self.assertEqual(fit_cue_speed(5.0, 0.0), 1.0)


class FishAudioClientTests(unittest.TestCase):
    def setUp(self):
        self.client = FishAudioTtsClient(api_key='test-key', base_url='https://api.fish.audio', model='s2.1-pro-free')

    def test_missing_api_key_raises(self):
        with self.assertRaises(TtsDubError):
            FishAudioTtsClient(api_key='').synthesize('你好')

    def test_payload_contains_model_header_and_text(self):
        resp = Mock()
        resp.status_code = 200
        resp.content = b'audio-bytes'
        with patch.object(tts_dub.httpx, 'post', return_value=resp) as post_mock:
            audio = self.client.synthesize('测试文本')
        self.assertEqual(audio, b'audio-bytes')
        kwargs = post_mock.call_args.kwargs
        self.assertEqual(kwargs['json']['text'], '测试文本')
        self.assertEqual(kwargs['headers']['model'], 's2.1-pro-free')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer test-key')

    def test_reference_audio_encoded_base64(self):
        resp = Mock()
        resp.status_code = 200
        resp.content = b'audio-bytes'
        with patch.object(tts_dub.httpx, 'post', return_value=resp) as post_mock:
            self.client.synthesize('文本', reference_audio=b'\x00\x01', reference_text='样本')
        body = post_mock.call_args.kwargs['json']
        self.assertEqual(body['references'][0]['audio'], base64.b64encode(b'\x00\x01').decode())
        self.assertEqual(body['references'][0]['text'], '样本')
        self.assertNotIn('reference_id', body)

    def test_reference_id_preferred_over_audio(self):
        resp = Mock()
        resp.status_code = 200
        resp.content = b'audio'
        with patch.object(tts_dub.httpx, 'post', return_value=resp) as post_mock:
            self.client.synthesize('文本', reference_id='model-id', reference_audio=b'\x00')
        body = post_mock.call_args.kwargs['json']
        self.assertEqual(body['reference_id'], 'model-id')
        self.assertNotIn('references', body)

    def test_retries_on_429_then_success(self):
        fail = Mock()
        fail.status_code = 429
        fail.text = 'rate limited'
        ok = Mock()
        ok.status_code = 200
        ok.content = b'audio'
        with patch.object(tts_dub.httpx, 'post', side_effect=[fail, ok]) as post_mock:
            audio = self.client.synthesize('文本')
        self.assertEqual(audio, b'audio')
        self.assertEqual(post_mock.call_count, 2)

    def test_http_error_raises_tts_error(self):
        fail = Mock()
        fail.status_code = 401
        fail.text = 'unauthorized'
        with patch.object(tts_dub.httpx, 'post', return_value=fail):
            with self.assertRaises(TtsDubError):
                self.client.synthesize('文本')


if __name__ == '__main__':
    unittest.main()