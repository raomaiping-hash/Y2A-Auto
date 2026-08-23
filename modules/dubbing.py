#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配音流水线：字幕→逐条 TTS→智能混合对齐→合成带配音的视频。

参考 pyVideoTrans 的 _stage_dubbing/_stage_align/_stage_assemble 设计，
适配 Fish Audio s2.1-pro-free + 本机 VAAPI 编码。

阶段：
  1. dub:   读取中文字幕，逐条合成语音（md5 缓存防重复）
  2. align: 智能混合对齐——优先用合成时 speed 参数贴合；残余误差用
            ffmpeg atempo 微调；缺口用静音填充
  3. assemble: 视频(烧中文字幕) + 配音音轨 + 可选 BGM，VAAPI 编码
"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from modules.ffmpeg_manager import get_ffmpeg_path, get_ffprobe_path
from providers.tts.base import BaseTTSProvider, TTSProviderError
from providers.tts.dub_cache import build_dub_cache_key, get_cached_dub_path, save_dub_cache

# 模块级兜底 logger：调用方可传自定义 logger，未传时使用标准 logging
_module_logger = logging.getLogger('dubbing')


def _log(logger, level, msg):
    (logger or _module_logger).log(getattr(logging, level, logging.INFO), msg)

#: 中文朗读速率估算（字/秒），用于"配音预计时长 > 字幕窗口"判断
ZH_CHARS_PER_SECOND = 4.5
#: 对齐阈值：预计配音时长超过字幕窗口该倍数时触发文案优化/变速
ALIGN_OVERFLOW_THRESHOLD = 1.1
#: 变速上限：超过则截断音频（避免语速失真）
MAX_SPEED_FACTOR = 1.25


@dataclass
class DubSegment:
    """一条字幕对应的配音片段。"""
    index: int
    text: str
    start_ms: int
    end_ms: int
    wav_path: str = ''
    duration_s: float = 0.0
    speed: float = 1.0
    voice: str = ''


def parse_srt_to_segments(srt_path: str) -> List[Dict[str, Any]]:
    """解析 SRT 为 [{'text','start_ms','end_ms'}]，跳过空行。"""
    cues: List[Dict[str, Any]] = []
    if not srt_path or not os.path.isfile(srt_path):
        return cues
    with open(srt_path, 'r', encoding='utf-8-sig', errors='replace') as fh:
        content = fh.read()
    blocks = [b.strip() for b in content.replace('\r\n', '\n').split('\n\n') if b.strip()]
    for block in blocks:
        lines = block.split('\n')
        # 跳过序号行，找时间行；时间行之前的序号行与之后的文本行分开
        time_idx = None
        for i, line in enumerate(lines):
            if '-->' in line:
                time_idx = i
                break
        if time_idx is None:
            continue
        time_line = lines[time_idx]
        # 序号行是时间行之前的第一个非空行（通常为纯数字）；文本为时间行之后所有非空行
        text_lines = [l.strip() for l in lines[time_idx + 1:] if l.strip()]
        if not text_lines:
            continue
        try:
            start_raw, end_raw = time_line.split('-->')
            start_ms = _ts_to_ms(start_raw.strip())
            end_ms = _ts_to_ms(end_raw.strip())
        except Exception:
            continue
        text = ' '.join(text_lines).strip()
        if not text or end_ms <= start_ms:
            continue
        cues.append({'text': text, 'start_ms': start_ms, 'end_ms': end_ms})
    return cues


def _ts_to_ms(ts: str) -> int:
    ts = ts.strip().replace(',', '.')
    h, m, s = ts.split(':')
    return int(h) * 3600000 + int(m) * 60000 + int(round(float(s) * 1000))


def _ms_to_ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms2 = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms2:03d}'


def _probe_wav_duration(wav_path: str, logger=None) -> float:
    """用 ffprobe 取音频时长（秒）。"""
    ffprobe = get_ffprobe_path()
    if not ffprobe:
        try:
            import wave
            with wave.open(wav_path, 'rb') as w:
                return w.getnframes() / float(w.getframerate())
        except Exception:
            return 0.0
    try:
        out = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', wav_path],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip())
    except Exception:
        return 0.0


def estimate_speech_duration_s(text: str) -> float:
    """估算中文配音时长：字数 / 4.5 字每秒（含标点折半）。"""
    text = str(text or '')
    cjk = sum(1 for ch in text if '\u2e80' <= ch <= '\u9fff')
    other = len(text) - cjk
    return cjk / ZH_CHARS_PER_SECOND + other / (ZH_CHARS_PER_SECOND * 2)


def dub_srt_to_audio(
    srt_path: str,
    config: Dict[str, Any],
    task_id: str,
    logger,
    voice: Optional[str] = None,
    output_wav: Optional[str] = None,
    speed: float = 1.0,
    progress_callback=None,
) -> Tuple[Optional[str], List[DubSegment]]:
    """把中文字幕逐条合成为一段完整配音 wav。

    返回 (wav路径或None, 片段列表)。缓存命中直接复用，不重复调用 TTS。
    """
    logger = logger or _module_logger
    from providers.tts.fish_audio import create_tts_provider

    provider: BaseTTSProvider = create_tts_provider(config, logger=logger)
    model = str(config.get('FISH_TTS_MODEL') or 's2.1-pro-free')
    language = str(config.get('SUBTITLE_TARGET_LANGUAGE') or 'zh')

    cues = parse_srt_to_segments(srt_path)
    if not cues:
        logger.warning('配音：字幕为空，跳过')
        return None, []

    segments: List[DubSegment] = []
    temp_dir = tempfile.mkdtemp(prefix=f'dub_{task_id[:8]}_')

    total = len(cues)
    for idx, cue in enumerate(cues):
        text = cue['text']
        seg = DubSegment(
            index=idx,
            text=text,
            start_ms=cue['start_ms'],
            end_ms=cue['end_ms'],
            voice=voice or '',
        )
        # 缓存优先
        cache_key = build_dub_cache_key(text, voice or '', speed, model, language)
        cached = get_cached_dub_path(cache_key)
        if cached:
            seg.wav_path = os.path.join(temp_dir, f'seg_{idx}.wav')
            shutil.copy2(cached, seg.wav_path)
            seg.duration_s = _probe_wav_duration(seg.wav_path, logger)
            logger.debug(f'配音缓存命中 [{idx+1}/{total}]: {text[:20]}...')
        else:
            try:
                audio = provider.synthesize(text, voice=voice, speed=speed)
            except TTSProviderError as e:
                logger.warning(f'配音合成失败 [{idx+1}/{total}]: {text[:30]}... {e}')
                segments.append(seg)
                continue
            seg.wav_path = os.path.join(temp_dir, f'seg_{idx}.wav')
            with open(seg.wav_path, 'wb') as fh:
                fh.write(audio)
            save_dub_cache(cache_key, audio)
            seg.duration_s = _probe_wav_duration(seg.wav_path, logger)
            logger.info(f'配音合成 [{idx+1}/{total}]: {text[:24]}... ({seg.duration_s:.1f}s)')
        segments.append(seg)
        if progress_callback:
            progress_callback((idx + 1) / total, idx + 1, total)

    # 无有效片段则失败
    valid = [s for s in segments if s.wav_path and s.duration_s > 0]
    if not valid:
        logger.error('配音：无有效合成片段')
        return None, segments

    # 合并为完整 wav
    if output_wav is None:
        output_wav = os.path.join(tempfile.gettempdir(), f'dub_{task_id[:8]}.wav')
    _concat_wav_segments(valid, output_wav, logger)
    return output_wav, segments


def _concat_wav_segments(segments: List[DubSegment], output_wav: str, logger) -> None:
    """按时间顺序把片段拼接为完整 wav（片段间按字幕时间插入静音）。"""
    if len(segments) == 1:
        shutil.copy2(segments[0].wav_path, output_wav)
        return
    ffmpeg = get_ffmpeg_path(logger=logger)
    if not ffmpeg:
        raise RuntimeError('FFmpeg 不可用，无法合并配音')

    # 用 filter_complex 精确控制每段时间
    inputs = []
    for s in segments:
        inputs += ['-i', s.wav_path]
    # 计算每段的开始偏移：按字幕时间线放置
    filter_parts = []
    first_start_ms = segments[0].start_ms
    for i, s in enumerate(segments):
        offset_ms = s.start_ms - first_start_ms
        filter_parts.append(f'[{i}:a]adelay={offset_ms}|{offset_ms}[a{i}]')
    n = len(segments)
    mix = ''.join(f'[a{i}]' for i in range(n)) + f'amix=inputs={n}:duration=longest:normalize=0[out]'
    cmd = [ffmpeg, '-y'] + inputs + [
        '-filter_complex', ';'.join(filter_parts) + ';' + mix,
        '-map', '[out]', '-ac', '2', '-ar', '44100', output_wav,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        raise RuntimeError(f'合并配音失败: {result.stderr[-300:]}')


def align_segments_smart_mix(
    segments: List[DubSegment],
    logger,
) -> List[DubSegment]:
    """智能混合对齐：把每个片段时长贴合其字幕窗口。

    策略（按优先级）：
      1. 已贴近（≤阈值）→ 不动
      2. 过长 → ffmpeg atempo 加速（上限 MAX_SPEED_FACTOR，防失真）
      3. 过短 → 尾部补静音
    """
    logger = logger or _module_logger
    aligned = []
    for s in segments:
        if not s.wav_path or s.duration_s <= 0:
            continue
        window_s = (s.end_ms - s.start_ms) / 1000.0
        if window_s <= 0:
            aligned.append(s)
            continue
        ratio = s.duration_s / window_s
        if ratio <= ALIGN_OVERFLOW_THRESHOLD:
            # 过短：补静音（用 ffmpeg 或直接记录 gap，拼接时已按字幕时间放置）
            s.speed = 1.0
            aligned.append(s)
            continue
        # 过长：atempo 加速，上限 1.25x
        speed = min(ratio, MAX_SPEED_FACTOR)
        try:
            new_path = _atempo_wav(s.wav_path, speed, logger)
            if new_path:
                s.wav_path = new_path
                s.duration_s = _probe_wav_duration(new_path, logger)
                s.speed = speed
                logger.info(f'配音对齐: 片段[{s.index}] 加速 {speed:.2f}x '
                            f'({s.duration_s:.1f}s → 目标 {window_s:.1f}s)')
        except Exception as e:
            logger.warning(f'配音对齐失败[{s.index}]: {e}')
        aligned.append(s)
    return aligned


def _atempo_wav(wav_path: str, factor: float, logger) -> Optional[str]:
    """ffmpeg atempo 变速（factor 1~2 可一步，支持链式）。"""
    ffmpeg = get_ffmpeg_path(logger=logger)
    if not ffmpeg:
        return None
    out = wav_path + '.tempo.wav'
    # atempo 单次范围 0.5~2.0，此处 factor ∈ (1.1, 1.25] 一步即可
    cmd = [ffmpeg, '-y', '-i', wav_path,
           '-filter:a', f'atempo={factor:.4f}',
           '-ac', '2', '-ar', '44100', out]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f'atempo 失败: {result.stderr[-200:]}')
    return out


def assemble_dubbed_video(
    video_path: str,
    dub_wav_path: str,
    subtitle_ass_path: Optional[str],
    output_path: str,
    config: Dict[str, Any],
    logger,
    bgm_path: Optional[str] = None,
    bgm_volume: float = 0.3,
    burn_subtitle: bool = True,
    progress_callback=None,
) -> Optional[str]:
    """合成：视频(可选烧中文字幕) + 配音 + 可选 BGM（垫底）。

    原视频音轨完全丢弃（用户需求：完全去掉原声，可选 BGM 代替背景）。
    视频编码优先 VAAPI（本机 N100 核显），失败降级 CPU。
    """
    logger = logger or _module_logger
    ffmpeg = get_ffmpeg_path(logger=logger)
    if not ffmpeg:
        _log(logger, 'ERROR', 'FFmpeg 不可用，无法合成')
        return None

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    has_bgm = bool(bgm_path and os.path.isfile(bgm_path))

    # --- 输入与音频混音图 ---
    cmd = [ffmpeg, '-y', '-i', video_path, '-i', dub_wav_path]
    if has_bgm:
        cmd += ['-i', bgm_path]

    audio_filters = ['[1:a]anull[a_dub]']
    if has_bgm:
        # BGM 循环 + 音量压低垫底，时长截到与配音一致
        audio_filters.append(f'[2:a]volume={bgm_volume:.2f},aloop=loop=-1:size=2e9[b_bgm]')
        audio_filters.append(
            '[a_dub][b_bgm]amix=inputs=2:duration=first:normalize=0,'
            'alimiter=limit=0.95[a_out]'
        )
    else:
        audio_filters.append('[a_dub]anull[a_out]')

    # --- 视频流 ---
    if burn_subtitle and subtitle_ass_path and os.path.isfile(subtitle_ass_path):
        # 只烧中文字幕：直接用 ASS（已在字幕阶段生成 zh_only ASS）
        # 绝对路径转义，避免 cwd/相对路径问题（fontsdir 沿用系统字体+项目 fonts）
        ass_abs = os.path.abspath(subtitle_ass_path)
        escaped = ass_abs.replace('\\', '\\\\').replace(':', '\\:').replace("'", "\\'")
        vf = f"subtitles='{escaped}':fontsdir={os.path.abspath('fonts')}:charenc=UTF-8"
    else:
        vf = None

    # VAAPI 参数（复用现有策略：vaapi 时 HEVC，否则 libx264）
    encoder = str(config.get('VIDEO_ENCODER') or 'auto').lower()
    use_vaapi = (encoder == 'vaapi') and os.path.exists('/dev/dri/renderD128')
    if use_vaapi:
        cmd += ['-vaapi_device', '/dev/dri/renderD128']
    cmd += ['-filter_complex', ';'.join(audio_filters)]
    if vf:
        # VAAPI 编码必须上传到硬件 surface；无字幕时也要转换格式
        if use_vaapi:
            vf = f'{vf},format=nv12,hwupload'
        cmd += ['-vf', vf]
    elif use_vaapi:
        cmd += ['-vf', 'format=nv12,hwupload']
    # 视频编码
    if use_vaapi:
        cmd += ['-c:v', 'hevc_vaapi', '-qp', str(int(config.get('VAAPI_QP') or 26)),
                '-vsync', 'cfr', '-profile:v', 'main']
    else:
        cmd += ['-c:v', 'libx264', '-preset', str(config.get('VIDEO_CPU_PRESET') or 'medium'),
                '-crf', str(int(config.get('VIDEO_CRF') or 23)), '-pix_fmt', 'yuv420p']
    cmd += ['-map', '0:v:0', '-map', '[a_out]', '-c:a', 'aac', '-b:a', '192k']
    cmd += ['-movflags', '+faststart', '-shortest', output_path]

    logger.info(f'合成配音视频: {" ".join(cmd[:10])}...')
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, errors='replace',
    )
    stderr_tail = ''
    for line in proc.stdout or []:
        stderr_tail = line[-300:]
        if logger and 'time=' in line:
            logger.debug(f'合成进度: {line.strip()[-80:]}')
    proc.wait(timeout=3600 * 4)
    if proc.returncode != 0:
        logger.error(f'合成失败: {stderr_tail}')
        return None
    if not os.path.isfile(output_path) or os.path.getsize(output_path) == 0:
        logger.error('合成产物为空')
        return None
    logger.info(f'合成完成: {output_path} ({os.path.getsize(output_path)} bytes)')
    return output_path
