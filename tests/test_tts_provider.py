#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from providers.tts.base import BaseTTSProvider, TTSProviderError
from providers.tts.fish_audio import FishAudioProvider, create_tts_provider, FISH_TTS_MODEL_DEFAULT
from providers.tts.dub_cache import build_dub_cache_key, get_cached_dub_path, save_dub_cache


class _StubProvider(BaseTTSProvider):
    name = 'stub'

    def _synthesize_impl(self, text, voice, speed, output_format):
        return (f'{text}|{voice}|{speed}|{output_format}').encode()


class TTSProviderBaseTests(unittest.TestCase):
    def test_synthesize_rejects_empty_text(self):
        p = _StubProvider({})
        with self.assertRaises(TTSProviderError):
            p.synthesize('   ')

    def test_synthesize_clamps_speed(self):
        p = _StubProvider({})
        out = p.synthesize('你好', speed=9.9)
        self.assertEqual(out.decode(), '你好|None|2.0|wav')

    def test_synthesize_passes_through(self):
        p = _StubProvider({})
        out = p.synthesize('你好', voice='v1', speed=1.2)
        self.assertEqual(out.decode(), '你好|v1|1.2|wav')


class FishAudioProviderTests(unittest.TestCase):
    def test_missing_api_key_raises(self):
        p = FishAudioProvider({'FISH_API_KEY': ''})
        with self.assertRaises(TTSProviderError):
            p.synthesize('你好')

    @patch('providers.tts.fish_audio.requests.post')
    def test_success_returns_audio_bytes(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = b'RIFF-test-audio'
        mock_post.return_value = mock_resp

        p = FishAudioProvider({'FISH_API_KEY': 'sk-test'})
        audio = p.synthesize('你好', voice='v1', speed=1.0)
        self.assertEqual(audio, b'RIFF-test-audio')
        # 验证 payload 与 headers
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs['json']['text'], '你好')
        self.assertEqual(kwargs['json']['reference_id'], 'v1')
        self.assertEqual(kwargs['headers']['model'], FISH_TTS_MODEL_DEFAULT)
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer sk-test')

    @patch('providers.tts.fish_audio.requests.post')
    def test_402_credit_error_raises_without_retry(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 402
        mock_resp.json.return_value = {'message': 'Insufficient API credit'}
        mock_resp.text = ''
        mock_post.return_value = mock_resp

        p = FishAudioProvider({'FISH_API_KEY': 'sk-test'})
        with self.assertRaises(TTSProviderError) as ctx:
            p.synthesize('你好')
        self.assertIn('402', str(ctx.exception))
        # 不重试（402 属于无需重试）
        self.assertEqual(mock_post.call_count, 1)

    @patch('providers.tts.fish_audio.requests.post')
    def test_5xx_retries_then_raises(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = 'internal error'
        mock_post.return_value = mock_resp

        p = FishAudioProvider({'FISH_API_KEY': 'sk-test'})
        with self.assertRaises(TTSProviderError):
            p.synthesize('你好')
        self.assertEqual(mock_post.call_count, 3)

    def test_create_tts_provider_defaults_to_fish(self):
        p = create_tts_provider({'TTS_PROVIDER': 'unknown'})
        self.assertIsInstance(p, FishAudioProvider)


class DubCacheTests(unittest.TestCase):
    def test_cache_key_stable_and_distinct(self):
        k1 = build_dub_cache_key('你好', 'v1', 1.0, 's2.1-pro-free')
        k2 = build_dub_cache_key('你好', 'v1', 1.0, 's2.1-pro-free')
        k3 = build_dub_cache_key('你好', 'v1', 1.2, 's2.1-pro-free')
        self.assertEqual(k1, k2)
        self.assertNotEqual(k1, k3)

    def test_save_and_get_cache(self):
        # 用临时目录替换缓存目录，避免污染真实 caches/
        import providers.tts.dub_cache as dc
        tmp = tempfile.mkdtemp()
        with patch.object(dc, 'get_dubbing_cache_dir', return_value=tmp):
            key = build_dub_cache_key('测试', 'v1', 1.0, 'm')
            self.assertIsNone(get_cached_dub_path(key))
            path = save_dub_cache(key, b'RIFF-abc')
            self.assertTrue(os.path.isfile(path))
            self.assertEqual(get_cached_dub_path(key), path)


if __name__ == '__main__':
    unittest.main()
