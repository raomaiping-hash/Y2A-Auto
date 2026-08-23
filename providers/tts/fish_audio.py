#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Fish Audio TTS Provider（s2.1-pro-free / s2.1-pro）。

API: POST https://api.fish.audio/v1/tts
- Authorization: Bearer <FISH_API_KEY>
- model 请求头: s2.1-pro-free（免费，fair-use 限额）
- 请求体: {"text": "...", "reference_id": "<音色ID>", "format": "wav",
           "prosody": {"speed": 1.0}}
返回二进制音频（format 决定容器）。
"""

import time
from typing import Any, Dict, Optional

import requests

from .base import BaseTTSProvider, TTSProviderError


FISH_TTS_ENDPOINT = 'https://api.fish.audio/v1/tts'
#: 默认模型：免费开发模型，与 s2.1-pro 同质量（无 TTFA/DPA 保证）
FISH_TTS_MODEL_DEFAULT = 's2.1-pro-free'
#: 请求间隔（秒），防止免费模型 fair-use 限流
FISH_REQUEST_INTERVAL_SECONDS = 0.35


class FishAudioProvider(BaseTTSProvider):
    """Fish Audio 语音合成。"""

    name = 'fish_audio'

    def __init__(self, config: Optional[Dict[str, Any]] = None, logger=None):
        super().__init__(config, logger)
        self.api_key = str(self.config.get('FISH_API_KEY') or '').strip()
        self.model = str(self.config.get('FISH_TTS_MODEL') or FISH_TTS_MODEL_DEFAULT).strip() or FISH_TTS_MODEL_DEFAULT
        self.timeout_seconds = float(self.config.get('FISH_TTS_TIMEOUT_SECONDS') or 90)
        self.request_interval = float(self.config.get('FISH_REQUEST_INTERVAL_SECONDS') or FISH_REQUEST_INTERVAL_SECONDS)
        self._last_request_at = 0.0

    def _rate_limit_wait(self):
        """串行调用限速：距上次请求不足间隔则等待。"""
        now = time.time()
        wait = self._last_request_at + self.request_interval - now
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.time()

    def _synthesize_impl(self, text: str, voice: Optional[str], speed: float, output_format: str) -> bytes:
        if not self.api_key:
            raise TTSProviderError('Fish Audio API Key 未配置（FISH_API_KEY）')

        payload: Dict[str, Any] = {
            'text': text,
            'format': output_format,
            'prosody': {'speed': speed},
        }
        if voice:
            payload['reference_id'] = str(voice).strip()

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'model': self.model,
        }

        last_error: Optional[str] = None
        for attempt in range(1, 4):
            try:
                self._rate_limit_wait()
                resp = requests.post(
                    FISH_TTS_ENDPOINT,
                    json=payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
                if resp.status_code == 200:
                    audio = resp.content
                    if not audio:
                        raise TTSProviderError('Fish Audio 返回空音频')
                    self._log('debug', f'Fish TTS 合成成功: {len(audio)} bytes (attempt={attempt})')
                    return audio

                # 402=额度不足；4xx 参数/认证错误一般不重试
                if resp.status_code in (402, 401, 403, 404):
                    detail = ''
                    try:
                        detail = resp.json().get('message', '')
                    except Exception:
                        detail = resp.text[:200]
                    raise TTSProviderError(f'Fish Audio HTTP {resp.status_code}: {detail}')

                last_error = f'HTTP {resp.status_code}: {resp.text[:200]}'
                self._log('warning', f'Fish TTS 第 {attempt} 次失败: {last_error}')
            except TTSProviderError:
                raise
            except Exception as e:
                last_error = str(e)
                self._log('warning', f'Fish TTS 第 {attempt} 次请求异常: {e}')

            if attempt < 3:
                time.sleep(1.0 * attempt)

        raise TTSProviderError(f'Fish Audio 合成失败（重试3次）: {last_error}')


def create_tts_provider(config: Optional[Dict[str, Any]] = None, logger=None) -> BaseTTSProvider:
    """按配置创建 TTS provider（当前仅 fish_audio）。"""
    cfg = dict(config or {})
    provider_name = str(cfg.get('TTS_PROVIDER') or 'fish_audio').strip().lower()
    if provider_name == 'fish_audio':
        return FishAudioProvider(cfg, logger=logger)
    # 未知 provider 一律回退 fish_audio（唯一实现）
    return FishAudioProvider(cfg, logger=logger)
