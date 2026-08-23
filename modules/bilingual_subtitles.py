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


def _parse_bool_cfg(value: Any, default: bool = True) -> bool:
    """把配置值稳健转换为布尔（兼容 bool/int/str），用于字幕开关类配置。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    s = str(value).strip().lower()
    if s in ('', 'auto'):
        return default
    return s in ('1', 'true', 'yes', 'on', 'y')


def wrap_text_by_pixels(text: str, font_size: int, video_width: int, margin_lr: int = 60, max_lines: int = 3) -> str:
    """双语/单语字幕统一的按像素宽度折行入口（规范实现）。

    以可用像素宽度与字号估算每行字符预算，把过长字幕安全折行，
    避免溢出画面。此函数是双语与单语烧录路径共同复用的折行规范，
    保证同一段长字幕无论走哪条烧录路径都不会溢出。

    Args:
        text: 原始字幕文本
        font_size: 显示字号（px）
        video_width: 视频画面宽度（px）
        margin_lr: 左右安全边距（px）
        max_lines: 最多显示行数，超出截断加省略号

    Returns:
        折行后的文本，多行用 ``\\N`` 连接（ASS 换行符）。
    """
    return _wrap_text_by_pixels(text, font_size, video_width, margin_lr, max_lines)


def _wrap_text_by_pixels(text: str, font_size: int, video_width: int, margin_lr: int = 60, max_lines: int = 3) -> str:
    """把过长的字幕文本按可用宽度折行，避免溢出画面。

    估算每行可容纳字符数（CJK 全宽≈font_size，其余≈font_size*0.5），
    在标点/空格处断行；仍放不下则硬切到该行上限。用 \\N 连接显示行。
    含空格的拉丁文本按"词"折行，CJK 文本按字符折行。
    """
    text = str(text or '').strip()
    if not text:
        return text
    available = max(font_size, (video_width - 2 * margin_lr) * 0.90)  # 留 10% 余量防止贴边溢出
    # 每行最大字符数（宽字符按全宽 1，窄字符按 0.55）
    budget = max(2, int(available / font_size))
    max_lines = max(1, int(max_lines or 3))

    # 分词：拉丁/数字按空格，CJK 逐字符
    tokens: List[str] = []
    if any(ch.isspace() for ch in text) and not _is_all_cjk(text):
        tokens = text.split(' ')
    else:
        # CJK 逐字符，但保留非 CJK 连续串（数字/符号）作为整体
        cur = ''
        for ch in text:
            if _is_cjk_char(ch):
                if cur:
                    tokens.append(cur)
                    cur = ''
                tokens.append(ch)
            else:
                cur += ch
        if cur:
            tokens.append(cur)

    lines: List[str] = []
    cur_line = ''
    cur_w = 0.0
    for token in tokens:
        if not token:
            continue
        # 判断是否为纯 CJK token（逐字符拆出的，或不含空格的连续中文字串）
        is_cjk_token = all(_is_cjk_char(ch) for ch in token) if token else False
        sep = '' if is_cjk_token else ' '
        sep_w = 0.0 if is_cjk_token else 0.5
        tok_w = _token_width(token)
        # CJK 字符与前面 token 直接拼接；拉丁 token 之间需加空格
        add_w = sep_w + tok_w if cur_line else tok_w
        if cur_line and cur_w + add_w > budget:
            lines.append(cur_line)
            cur_line = token
            cur_w = tok_w
            if len(lines) >= max_lines:
                break
        else:
            cur_line = cur_line + sep + token if (cur_line and sep) else cur_line + token
            cur_w += add_w
    if cur_line:
        lines.append(cur_line)

    # 超出最大行数则截断加省略号
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][: max(1, budget - 1)].rstrip() + '…'
    return '\\N'.join(lines)


def _token_width(token: str) -> float:
    return sum(1.0 if _is_cjk_char(ch) else 0.5 for ch in token)


def _is_all_cjk(text: str) -> bool:
    cjk = sum(1 for ch in text if _is_cjk_char(ch))
    return cjk >= len(text) * 0.5


def _is_cjk_char(ch: str) -> bool:
    """判断字符是否为 CJK 全宽字符（中文/日文/韩文）。"""
    code = ord(ch)
    return (
        0x2E80 <= code <= 0x9FFF      # CJK 部首/汉字
        or 0xF900 <= code <= 0xFAFF   # CJK 兼容表意文字
        or 0xFF00 <= code <= 0xFFEF   # 全角符号
        or 0x20000 <= code <= 0x2FA1F  # CJK 扩展 B+
    )


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
    bold = _parse_bool_cfg(cfg.get('SUBTITLE_BOLD', 1), default=True)  # 默认加粗，提升可读性
    bold_flag = -1 if bold else 0  # ASS：-1=加粗，0=不加粗
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
        f'{bold_flag},0,0,0,100,100,0,0,' + f'{border_style},{outline},{shadow},{align},60,60,{margin_v},1\n'
        f'Style: En,{font_family},{en_size},{en_color},{en_color},{outline_color},{back_color},'
        f'{bold_flag},0,0,0,100,100,0,0,' + f'{border_style},{outline},{shadow},{align},60,60,{en_margin},1\n\n'
        '[Events]\n'
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    )

    lines: List[str] = []
    if mode == 'en_only':
        for tc in tr_cues:
            sc = _find_source_for(src_cues, tc['start'], tc['end'])
            en = _slice_source_text(sc['text'], sc['start'], sc['end'], tc['start'], tc['end']) if sc else ''
            if en:
                wrapped = _wrap_text_by_pixels(en, en_size, video_width, 60)
                lines.append(f"Dialogue: 0,{_seconds_to_ass(tc['start'])},{_seconds_to_ass(tc['end'])},"
                             f"En,,0,0,0,,{{\\rEn}}{wrapped}")
    elif mode == 'zh_only':
        for tc in tr_cues:
            if tc['text']:
                wrapped = _wrap_text_by_pixels(tc['text'], zh_size, video_width, 60)
                lines.append(f"Dialogue: 0,{_seconds_to_ass(tc['start'])},{_seconds_to_ass(tc['end'])},"
                             f"Zh,,0,0,0,,{{\\rZh}}{wrapped}")
    else:  # bilingual
        for tc in tr_cues:
            sc = _find_source_for(src_cues, tc['start'], tc['end'])
            en = _slice_source_text(sc['text'], sc['start'], sc['end'], tc['start'], tc['end']) if sc else ''
            st, en_ts = _seconds_to_ass(tc['start']), _seconds_to_ass(tc['end'])
            # 中文大行在上（自动按画面宽度折行，避免溢出）
            if tc['text']:
                wrapped_zh = _wrap_text_by_pixels(tc['text'], zh_size, video_width, 60)
                lines.append(f"Dialogue: 0,{st},{en_ts},Zh,,0,0,0,,{{\\rZh}}{wrapped_zh}")
            # 英文小行在下
            if en:
                wrapped_en = _wrap_text_by_pixels(en, en_size, video_width, 60)
                lines.append(f"Dialogue: 0,{st},{en_ts},En,,0,0,0,,{{\\rEn}}{wrapped_en}")

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
    video_width: Optional[int] = None,
    zh_size: int = 60,
    en_size: int = 32,
) -> Optional[str]:
    """生成中英双语字幕 srt。

    order: 'trans_src'=中文在上/英文在下；'src_trans'=英文在上/中文在下。
    source_is_zh: 源语言本就是中文时，直接把源字幕复制，不拼双语。
    video_width/zh_size/en_size: 可选，提供后对每行按画面宽度折行（与烧录共用
        ``wrap_text_by_pixels`` 规范实现），避免上传的字幕文件与烧录画面不一致/溢出。
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
        # 若提供视频宽度，则对每条字幕按画面宽度折行，与烧录共用 wrap_text_by_pixels 规范实现。
        if video_width:
            zh = _wrap_text_by_pixels(zh, zh_size, video_width, 60, max_lines=3)
            if en:
                en = _wrap_text_by_pixels(en, en_size, video_width, 60, max_lines=3)
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
