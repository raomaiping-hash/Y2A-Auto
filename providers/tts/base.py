#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""TTS Provider 抽象基类（参考 pyVideoTrans 的 tts/_base.py 设计）。

统一接口：`synthesize(text, voice, speed) -> bytes`。
新增语音合成渠道（Edge-TTS、OpenAI TTS 等）只需继承本类并实现 `_synthesize_impl`。

配音缓存由外层 dubbing 阶段处理（md5 key 防重复合成），provider 只负责"文本→音频"。
"""

from typing import Any, Dict, Optional


class TTSProviderError(Exception):
    """TTS 合成失败（网络/额度/参数错误等）。"""


class BaseTTSProvider:
    """TTS Provider 抽象基类。"""

    #: provider 名称（用于缓存 key 与配置选择）
    name: str = 'base'

    def __init__(self, config: Optional[Dict[str, Any]] = None, logger=None):
        self.config = dict(config or {})
        self.logger = logger

    def _log(self, level: str, msg: str):
        if self.logger:
            getattr(self.logger, level, self.logger.info)(msg)

    def synthesize(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        output_format: str = 'wav',
    ) -> bytes:
        """合成语音，返回音频字节（默认 WAV）。"""
        text = str(text or '').strip()
        if not text:
            raise TTSProviderError('合成文本为空')
        speed = max(0.5, min(2.0, float(speed or 1.0)))
        return self._synthesize_impl(text=text, voice=voice, speed=speed, output_format=output_format)

    def _synthesize_impl(self, text: str, voice: Optional[str], speed: float, output_format: str) -> bytes:
        raise NotImplementedError(f'{self.name} provider 未实现 _synthesize_impl')
