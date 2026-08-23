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
        # 8s 语音放进 4s 窗口 → 2x 但被软上限 1.35 截断（超窗句应修剪文本而非硬压）
        self.assertAlmostEqual(fit_cue_speed(8.0, 4.0), 1.4, places=3)

    def test_caps_at_max_fit_speed(self):
        self.assertAlmostEqual(fit_cue_speed(20.0, 4.0), 1.4, places=3)

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
        with patch.object(tts_dub.httpx.Client, "post", return_value=resp) as post_mock:
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
        with patch.object(tts_dub.httpx.Client, "post", return_value=resp) as post_mock:
            self.client.synthesize('文本', reference_audio=b'\x00\x01', reference_text='样本')
        body = post_mock.call_args.kwargs['json']
        self.assertEqual(body['references'][0]['audio'], base64.b64encode(b'\x00\x01').decode())
        self.assertEqual(body['references'][0]['text'], '样本')
        self.assertNotIn('reference_id', body)

    def test_reference_id_preferred_over_audio(self):
        resp = Mock()
        resp.status_code = 200
        resp.content = b'audio'
        with patch.object(tts_dub.httpx.Client, "post", return_value=resp) as post_mock:
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
        with patch.object(tts_dub.httpx.Client, 'post', side_effect=[fail, ok]) as post_mock:
            audio = self.client.synthesize('文本')
        self.assertEqual(audio, b'audio')
        self.assertEqual(post_mock.call_count, 2)

    def test_http_error_raises_tts_error(self):
        fail = Mock()
        fail.status_code = 401
        fail.text = 'unauthorized'
        with patch.object(tts_dub.httpx.Client, 'post', return_value=fail):
            with self.assertRaises(TtsDubError):
                self.client.synthesize('文本')


class AlignedSubtitleTests(unittest.TestCase):
    def test_fmt_srt_ts_standard(self):
        from modules.tts_dub import _fmt_srt_ts
        self.assertEqual(_fmt_srt_ts(0.0), '00:00:00,000')
        self.assertEqual(_fmt_srt_ts(14.8), '00:00:14,800')
        self.assertEqual(_fmt_srt_ts(350.8), '00:05:50,800')
        self.assertEqual(_fmt_srt_ts(3661.5), '01:01:01,500')

    def test_fmt_srt_ts_never_negative(self):
        from modules.tts_dub import _fmt_srt_ts
        self.assertEqual(_fmt_srt_ts(-3.2), '00:00:00,000')

    def test_write_aligned_dub_subtitle_writes_mapped(self):
        import os
        import tempfile
        from modules.tts_dub import write_aligned_dub_subtitle

        mapped = [
            {'video_start': 0.0, 'video_end': 14.8, 'text': '第一段旁白。'},
            {'video_start': 14.81, 'video_end': 29.4, 'text': '第二段旁白。'},
            {'video_start': 0.0, 'video_end': 1.0, 'text': ''},  # 空文本段应被丢弃
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, 'aligned.srt')
            result = write_aligned_dub_subtitle(mapped, out)
            self.assertEqual(result, out)
            with open(out, encoding='utf-8') as fh:
                content = fh.read()
            self.assertIn('00:00:00,000 --> 00:00:14,800', content)
            self.assertIn('00:00:14,810 --> 00:00:29,400', content)
            self.assertIn('第一段旁白。', content)
            self.assertNotIn('空文本段', content)
            # 应恰好 2 段（空文本被丢弃）
            self.assertEqual(content.count('-->'), 2)

    def test_write_aligned_dub_subtitle_empty_returns_none(self):
        from modules.tts_dub import write_aligned_dub_subtitle
        self.assertIsNone(write_aligned_dub_subtitle([], '/tmp/nonexist/out.srt'))
        self.assertIsNone(
            write_aligned_dub_subtitle(
                [{'video_start': 0, 'video_end': 1, 'text': '  '}], '/tmp/nonexist/out.srt',
            )
        )


if __name__ == '__main__':
    unittest.main()