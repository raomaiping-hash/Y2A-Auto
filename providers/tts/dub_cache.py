#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配音缓存层：md5(语言-文本-音色-语速-模型) 作为 key，防止重复合成。

参考 pyVideoTrans translator/_base.py 的 _get_key 设计。
同一句话 + 同一音色 + 同一语速永不重复调用 TTS（省免费额度）。
"""

import hashlib
import os
import time
from typing import Optional

from modules.utils import get_app_subdir


def get_dubbing_cache_dir() -> str:
    """配音缓存目录（跨任务复用）。"""
    cache_dir = os.path.join(get_app_subdir('caches'), 'dub')
    os.makedirs(cache_dir, exist_ok=True)
    return cache_dir


def build_dub_cache_key(
    text: str,
    voice: str,
    speed: float,
    model: str,
    language: str = '',
    provider: str = '',
    output_format: str = 'wav',
) -> str:
    """构造配音缓存 key：提供者/格式/配置组合 + 文本内容的 md5。

    加入 provider 与输出格式，避免未来新增 TTS 提供者或输出格式后 key 冲突
    （同一句话不同提供者/格式本应得到不同音频）。
    """
    raw = f'{provider}-{output_format}-{language}-{text}-{voice}-{speed}-{model}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def cleanup_dub_cache(max_age_days: float = 30.0, logger=None) -> int:
    """清理超过 max_age_days（按 mtime）未使用的配音缓存文件。

    长期运行会持续写入配音缓存，磁盘只增不减；该钩子在配音合成的入口处周期调用，
    删除陈旧音频文件（保留最近使用的），默认保留 30 天。返回删除的文件数。
    """
    cache_dir = get_dubbing_cache_dir()
    if not os.path.isdir(cache_dir):
        return 0
    cutoff = time.time() - max(max_age_days, 0.0) * 86400.0
    removed = 0
    for name in os.listdir(cache_dir):
        path = os.path.join(cache_dir, name)
        try:
            if os.path.isfile(path) and os.path.getmtime(path) < cutoff:
                os.remove(path)
                removed += 1
                if logger:
                    logger.info(f'配音缓存清理: 删除过期文件 {name}')
        except OSError:
            continue
    return removed


def get_cached_dub_path(cache_key: str, ext: str = 'wav') -> Optional[str]:
    """若缓存存在且非空，返回路径；否则 None。"""
    path = os.path.join(get_dubbing_cache_dir(), f'{cache_key}.{ext}')
    if os.path.isfile(path) and os.path.getsize(path) > 0:
        return path
    return None


def save_dub_cache(cache_key: str, audio_bytes: bytes, ext: str = 'wav') -> str:
    """写入配音缓存，返回缓存路径。"""
    path = os.path.join(get_dubbing_cache_dir(), f'{cache_key}.{ext}')
    tmp_path = path + '.tmp'
    with open(tmp_path, 'wb') as fh:
        fh.write(audio_bytes)
    os.replace(tmp_path, path)  # 原子落盘，避免并发写一半被读到
    return path
