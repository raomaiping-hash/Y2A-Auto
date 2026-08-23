#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中英双语字幕生成（参考 VideoLingo 的 src_trans/trans_src 双字幕方案）。

输入：原始（源语言）字幕 srt + 翻译（目标语言）字幕 srt。
做法：以“翻译字幕”的较细时间片为锚（每片通常是可读的单行），
     按时间覆盖比例从“源字幕”中切出对应英文片段，
     每片输出两行（中英/英中按配置排序），生成双字幕 srt，供烧录。
"""

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .srt_transform_engine import SrtTransformConfig, SrtTransformEngine


def _fmt_ts(seconds: float) -> str:
    """秒 → 规范 SRT 时间戳 HH:MM:SS,mmm。"""
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def _parse_srt(path: str) -> List[Dict[str, Any]]:
    if not path or not os.path.isfile(path):
        return []
    try:
        engine = SrtTransformEngine(SrtTransformConfig())
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            cues = engine.parse_srt(fh.read())
        return [
            {'start': float(c['start']), 'end': float(c['end']), 'text': str(c.get('text') or '').strip()}
            for c in cues if str(c.get('text') or '').strip()
        ]
    except Exception:
        return []


def _normalize_words(text: str) -> List[str]:
    """把英文切成词，中文切成单字（去标点/空白，但保留词内撇号如 can't）。"""
    # 不在 ' 处切分，保留 can't / it's 等词内撇号
    return [w for w in re.split(r'[\s,.;:!?，。！？；：“”()\[\]]+', text)
            if w and w.strip("'\u2019")]


def _slice_source_text(src_text: str, src_start: float, src_end: float, sub_start: float, sub_end: float) -> str:
    """按 [sub_start, sub_end] 在源字幕 [src_start, src_end] 内的时长占比，切出对应文本片段。"""
    src_text = str(src_text or '').strip()
    if not src_text:
        return ''
    src_dur = max(0.01, src_end - src_start)
    # 取子窗口相对源窗口的起止比例（限制在 [0,1]）
    r0 = max(0.0, (sub_start - src_start) / src_dur)
    r1 = min(1.0, (sub_end - src_start) / src_dur)
    words = _normalize_words(src_text)
    if not words:
        return src_text
    i0 = int(round(r0 * len(words)))
    i1 = max(i0 + 1, int(round(r1 * len(words))))
    i0 = max(0, i0)
    i1 = min(len(words), i1)
    return ' '.join(words[i0:i1]).strip()


def _find_source_for(src_cues: List[Dict[str, Any]], t0: float, t1: float) -> Optional[Dict[str, Any]]:
    """找到覆盖/最重叠给定窗口的源字幕 cue。"""
    best: Optional[Dict[str, Any]] = None
    best_overlap = -1.0
    for sc in src_cues:
        overlap = min(sc['end'], t1) - max(sc['start'], t0)
        if overlap > best_overlap:
            best_overlap = overlap
            best = sc
    return best if best_overlap > 0 else None


def build_bilingual_srt(
    source_path: str,
    translated_path: str,
    out_path: str,
    order: str = 'trans_src',
    source_is_zh: bool = False,
) -> Optional[str]:
    """生成中英双语字幕 srt。

    order: 'trans_src'=中文在上/英文在下；'src_trans'=英文在上/中文在下。
    source_is_zh: 源语言本就是中文时，直接把源字幕复制，不拼双语。
    返回输出路径；无有效内容返回 None。
    """
    order = str(order or 'trans_src').strip().lower()
    if source_is_zh:
        # 源即中文：直接用源字幕（无英文可对照）
        src_cues = _parse_srt(source_path)
        if not src_cues:
            return None
        lines: List[str] = []
        for i, c in enumerate(src_cues, 1):
            lines.append(str(i))
            lines.append(f"{_fmt_ts(c['start'])} --> {_fmt_ts(c['end'])}")
            lines.append(c['text'])
            lines.append('')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines).strip() + '\n')
        return out_path

    src_cues = _parse_srt(source_path)
    tr_cues = _parse_srt(translated_path)
    if not tr_cues:
        return None
    if not src_cues:
        # 无源可对照：退化为单语翻译字幕
        lines: List[str] = []
        for i, c in enumerate(tr_cues, 1):
            lines.append(str(i))
            lines.append(f"{_fmt_ts(c['start'])} --> {_fmt_ts(c['end'])}")
            lines.append(c['text'])
            lines.append('')
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines).strip() + '\n')
        return out_path

    out_lines: List[str] = []
    idx = 1
    for tc in tr_cues:
        t0, t1 = tc['start'], tc['end']
        sc = _find_source_for(src_cues, t0, t1)
        en = _slice_source_text(sc['text'], sc['start'], sc['end'], t0, t1) if sc else ''
        zh = tc['text']
        if order == 'src_trans':
            body = '\n'.join(x for x in (en, zh) if x)
        else:
            body = '\n'.join(x for x in (zh, en) if x)
        out_lines.append(str(idx))
        out_lines.append(f"{_fmt_ts(t0)} --> {_fmt_ts(t1)}")
        out_lines.append(body)
        out_lines.append('')
        idx += 1

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(out_lines).strip() + '\n')
    return out_path
