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


def _seconds_to_ass(seconds: float) -> str:
    """秒 → ASS 时间戳 H:MM:SS.cc（libass 兼容）。"""
    if seconds < 0:
        seconds = 0.0
    cs = int(round(seconds * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f'{h}:{m:02d}:{s:02d}.{cs:02d}'


def _hex_to_ass(hex_color: Any, default: int = 0xFFFFFF) -> str:
    """#RRGGBB → ASS 颜色 &HAABBGGRR（A=00 不透明）。"""
    h = str(hex_color or '').strip().lstrip('#')
    if len(h) == 6:
        try:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        except ValueError:
            r = g = b = default
    else:
        r = g = b = default
    return f'&H00{b:02X}{g:02X}{r:02X}'


def build_bilingual_ass(
    source_path: str,
    translated_path: str,
    out_ass: str,
    cfg: Optional[Dict[str, Any]] = None,
    font_family: str = 'Noto Sans CJK SC',
    video_width: int = 1920,
    video_height: int = 1080,
) -> Optional[str]:
    """生成带样式的双语 ASS（参考 VideoLingo：中文字幕大、英文字幕小）。

    mode: zh_only=只中文 / bilingual=中英双语（中文大英文小） / en_only=只英文。
    样式与位置由 cfg 控制（字号/颜色/描边/位置/背景框）。
    返回输出路径；无有效内容返回 None。
    """
    cfg = cfg or {}
    mode = str(cfg.get('SUBTITLE_MODE') or 'bilingual').strip().lower()
    # 容错：'builtin' 等非法值统一视为双语
    if mode not in ('en_only', 'zh_only', 'bilingual'):
        mode = 'bilingual'
    zh_size = int(cfg.get('SUBTITLE_ZH_SIZE') or 60)
    en_size = int(cfg.get('SUBTITLE_EN_SIZE') or 32)
    zh_color = _hex_to_ass(cfg.get('SUBTITLE_ZH_COLOR') or '#FFFFFF')
    en_color = _hex_to_ass(cfg.get('SUBTITLE_EN_COLOR') or '#FFFFFF')
    outline_color = _hex_to_ass(cfg.get('SUBTITLE_OUTLINE_COLOR') or '#000000')
    outline = int(cfg.get('SUBTITLE_OUTLINE_WIDTH') or 3)
    shadow = int(cfg.get('SUBTITLE_SHADOW') or 0)
    boxed = bool(cfg.get('SUBTITLE_BOXED', True))
    border_style = 4 if boxed else 1
    back_color = _hex_to_ass(cfg.get('SUBTITLE_BOX_COLOR') or '#000000')
    # 半透明背景框：&HxxBBGGRR，xx=alpha。默认 &H96000000≈59% 黑（保证复杂背景可读）
    if boxed:
        back_color = '&H' + hex(int(cfg.get('SUBTITLE_BOX_ALPHA') or 0x96))[2:].zfill(2) + back_color[4:]
    bold = int(cfg.get('SUBTITLE_BOLD', 1) or 1)  # 默认加粗，提升可读性
    align_map = {'bottom': 2, 'center': 5, 'top': 8}
    align = align_map.get(str(cfg.get('SUBTITLE_ALIGN') or 'bottom').strip().lower(), 2)
    margin_v = int(cfg.get('SUBTITLE_MARGIN_V') or 90)
    # 英文行在其下方，留出清晰间距（按中文字号动态计算）
    gap = int(cfg.get('SUBTITLE_LINE_GAP') or max(12, int(zh_size * 0.28)))
    en_margin = max(4, margin_v - int(zh_size * 0.72) - gap)

    src_cues = _parse_srt(source_path)
    tr_cues = _parse_srt(translated_path)
    if not tr_cues:
        return None

    header = (
        '[Script Info]\n'
        'Title: Bilingual Subtitle\n'
        'ScriptType: v4.00+\n'
        f'PlayResX: {int(video_width)}\n'
        f'PlayResY: {int(video_height)}\n'
        'WrapStyle: 0\n'
        'ScaledBorderAndShadow: yes\n'
        'Collisions: Normal\n\n'
        '[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, '
        'Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
        'Alignment, MarginL, MarginR, MarginV, Encoding\n'
        f'Style: Zh,{font_family},{zh_size},{zh_color},{zh_color},{outline_color},{back_color},'
        f'-{bold},0,0,0,100,100,0,0,' + f'{border_style},{outline},{shadow},{align},60,60,{margin_v},1\n'
        f'Style: En,{font_family},{en_size},{en_color},{en_color},{outline_color},{back_color},'
        f'-{bold},0,0,0,100,100,0,0,' + f'{border_style},{outline},{shadow},{align},60,60,{en_margin},1\n\n'
        '[Events]\n'
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    )

    lines: List[str] = []
    if mode == 'en_only':
        for tc in tr_cues:
            sc = _find_source_for(src_cues, tc['start'], tc['end'])
            en = _slice_source_text(sc['text'], sc['start'], sc['end'], tc['start'], tc['end']) if sc else ''
            if en:
                lines.append(f"Dialogue: 0,{_seconds_to_ass(tc['start'])},{_seconds_to_ass(tc['end'])},"
                             f"En,,0,0,0,,{{\\rEn}}{en}")
    elif mode == 'zh_only':
        for tc in tr_cues:
            if tc['text']:
                lines.append(f"Dialogue: 0,{_seconds_to_ass(tc['start'])},{_seconds_to_ass(tc['end'])},"
                             f"Zh,,0,0,0,,{{\\rZh}}{tc['text']}")
    else:  # bilingual
        for tc in tr_cues:
            sc = _find_source_for(src_cues, tc['start'], tc['end'])
            en = _slice_source_text(sc['text'], sc['start'], sc['end'], tc['start'], tc['end']) if sc else ''
            st, en_ts = _seconds_to_ass(tc['start']), _seconds_to_ass(tc['end'])
            # 中文大行在上
            if tc['text']:
                lines.append(f"Dialogue: 0,{st},{en_ts},Zh,,0,0,0,,{{\\rZh}}{tc['text']}")
            # 英文小行在下
            if en:
                lines.append(f"Dialogue: 0,{st},{en_ts},En,,0,0,0,,{{\\rEn}}{en}")

    if not lines:
        return None
    os.makedirs(os.path.dirname(out_ass), exist_ok=True)
    with open(out_ass, 'w', encoding='utf-8') as fh:
        fh.write(header + '\n'.join(lines) + '\n')
    return out_ass


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
