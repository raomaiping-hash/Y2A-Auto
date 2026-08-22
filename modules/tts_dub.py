#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TTS 配音模块：将翻译后字幕文本合成为语音，替换原声、保留背景音。

数据流（由 task_manager 在字幕阶段之后调用）：
  原视频 + 翻译后 SRT
    → 提取原音轨
    → 【分离】instrumental 伴奏轨（audio-separator/onnxruntime，CPU）或【压低】原轨
    → 逐条 cue：fish.audio TTS 合成（可零样本克隆原声）→ 时长拟合 → 定位放置
    → amix 合成新音轨 → 与视频流封装修复 → video_dubbed.mp4

任何一步失败都不阻断主流程：返回 (None, warnings)，由调用方降级保留原音频。
"""

import base64
import logging
import math
import os
import subprocess
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .ffmpeg_manager import get_ffmpeg_path, get_ffprobe_path
from .srt_transform_engine import SrtTransformConfig, SrtTransformEngine
from .utils import get_app_subdir

DEFAULT_BASE_URL = 'https://api.fish.audio'
DEFAULT_MODEL = 's2.1-pro-free'

# ffmpeg atempo 单级合法区间
_ATEMPO_MIN = 0.5
_ATEMPO_MAX = 2.0
# 语速拟合上限（双级 atempo 链覆盖）
_FIT_SPEED_MAX = 2.25
# 独立分离模型
_DEFAULT_SEPARATION_MODEL = 'UVR_MDXNET_KARA_2'
# 低于该时长的 cue 视为噪声，跳过
_MIN_CUE_DURATION_S = 0.5
# 参考音频采样时长（秒）
_REFERENCE_SAMPLE_SECONDS = 15.0
_REFERENCE_MAX_SECONDS = 30.0


class TtsDubError(Exception):
    """配音相关异常，message 为可读中文。"""


def build_atempo_chain(speed: float) -> List[float]:
    """把目标变速比拆解为合法的 atempo 参数链（每级 0.5~2.0）。

    >>> build_atempo_chain(1.0)
    [1.0]
    >>> len(build_atempo_chain(1.6)) == 1
    True
    >>> len(build_atempo_chain(3.0)) == 2
    True
    """
    speed = float(speed)
    if speed <= 0 or math.isnan(speed):
        raise ValueError('speed 必须为正数')
    chain: List[float] = []
    remaining = speed
    while remaining > _ATEMPO_MAX + 1e-6:
        stage = 2.0 if remaining >= _ATEMPO_MAX * 2 else math.sqrt(remaining)
        chain.append(stage)
        remaining = remaining / stage
    while remaining < _ATEMPO_MIN - 1e-6:
        stage = 0.5 if remaining <= _ATEMPO_MIN * 0.5 else math.sqrt(remaining)
        chain.append(stage)
        remaining = remaining / stage
    chain.append(remaining)
    return [round(c, 6) for c in chain]


def fit_cue_speed(tts_duration_s: float, window_duration_s: float) -> float:
    """计算把 TTS 时长压进 cue 窗口所需的变速比（>1 加速，<=1 不需加压）。"""
    if window_duration_s <= 0:
        return 1.0
    raw = tts_duration_s / window_duration_s
    if raw <= 1.0:
        return 1.0
    return min(raw, _FIT_SPEED_MAX)


class FishAudioTtsClient:
    """fish.audio TTS 客户端（JSON 传输，无额外运行时依赖）。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_BASE_URL,
        model: str = DEFAULT_MODEL,
        timeout_s: float = 60.0,
        max_retries: int = 3,
        retry_delay_s: float = 2.0,
        logger: Optional[logging.Logger] = None,
    ):
        self.api_key = str(api_key or '').strip()
        self.base_url = str(base_url or DEFAULT_BASE_URL).strip().rstrip('/')
        self.model = str(model or DEFAULT_MODEL).strip()
        self.timeout_s = float(timeout_s)
        self.max_retries = int(max_retries)
        self.retry_delay_s = float(retry_delay_s)
        self.logger = logger or logging.getLogger(__name__)

    def synthesize(
        self,
        text: str,
        *,
        reference_id: Optional[str] = None,
        reference_audio: Optional[bytes] = None,
        reference_text: str = '',
        speed: float = 1.0,
        audio_format: str = 'mp3',
    ) -> bytes:
        """合成一段语音，返回音频字节。失败抛 TtsDubError。"""
        if not self.api_key:
            raise TtsDubError('未配置 TTS_DUB_API_KEY')
        text = str(text or '').strip()
        if not text:
            raise TtsDubError('合成文本为空')

        body: Dict[str, Any] = {
            'text': text,
            'format': audio_format,
            'normalize': True,
            'prosody': {
                'speed': float(speed),
                'volume': 0,
                'normalize_loudness': True,
            },
        }
        if reference_id:
            body['reference_id'] = reference_id
        elif reference_audio:
            body['references'] = [{
                'audio': base64.b64encode(reference_audio).decode('ascii'),
                'text': str(reference_text or '').strip(),
            }]

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json',
            'model': self.model,
        }
        url = f'{self.base_url}/v1/tts'

        last_error = ''
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = httpx.post(url, json=body, headers=headers, timeout=self.timeout_s)
            except Exception as exc:  # 网络异常
                last_error = f'{type(exc).__name__}: {str(exc)[:160]}'
                self.logger.warning('fish.audio TTS 请求失败（第 %d/%d 次）: %s', attempt, self.max_retries, last_error)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay_s * (2 ** (attempt - 1)))
                continue

            if resp.status_code == 200 and resp.content:
                return resp.content
            if resp.status_code in (429, 402, 500, 503) and attempt < self.max_retries:
                last_error = f'HTTP {resp.status_code}: {resp.text[:160]}'
                self.logger.warning('fish.audio TTS 暂不可用（第 %d/%d 次）: %s', attempt, self.max_retries, last_error)
                time.sleep(self.retry_delay_s * (2 ** (attempt - 1)))
                continue
            last_error = f'HTTP {resp.status_code}: {resp.text[:220]}'
            break

        raise TtsDubError(f'语音合成失败：{last_error}')


# ---------------------------------------------------------------- 音视频工具

def _ffmpeg_path(logger: logging.Logger) -> str:
    path = get_ffmpeg_path(logger=logger)
    if not path or not os.path.exists(path):
        raise TtsDubError('缺少 ffmpeg，无法执行配音（请将二进制放入项目 ffmpeg/ 目录）')
    return path


def _ffprobe_path(ffmpeg: str, logger: logging.Logger) -> str:
    path = get_ffprobe_path(ffmpeg_path=ffmpeg, logger=logger)
    if not path or not os.path.exists(path):
        raise TtsDubError('缺少 ffprobe，无法执行配音')
    return path


def _run(cmd: List[str], logger: logging.Logger, timeout: int = 1800) -> None:
    logger.info('执行: %s', ' '.join(cmd)[:400])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise TtsDubError(f'ffmpeg 执行失败: {(proc.stderr or proc.stdout or "")[-300:]}')


def probe_duration(path: str, ffprobe: str, logger: logging.Logger) -> float:
    try:
        out = subprocess.run(
            [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', path],
            capture_output=True, text=True, timeout=60,
        )
        return float(str(out.stdout or '').strip())
    except Exception:
        return 0.0


def extract_audio(video_path: str, out_wav: str, ffmpeg: str, logger: logging.Logger) -> None:
    _run([
        ffmpeg, '-y', '-i', video_path, '-vn',
        '-ac', '2', '-ar', '44100', '-c:a', 'pcm_s16le', out_wav,
    ], logger)


def cut_audio_range(src_wav: str, start_s: float, duration_s: float, out_wav: str, ffmpeg: str, logger: logging.Logger) -> None:
    _run([
        ffmpeg, '-y', '-ss', f'{max(0.0, start_s):.3f}', '-t', f'{max(0.0, duration_s):.3f}',
        '-i', src_wav, '-ac', '2', '-ar', '44100', '-c:a', 'pcm_s16le', out_wav,
    ], logger)


def fit_audio_speed(src: str, target_speed: float, out: str, ffmpeg: str, logger: logging.Logger) -> None:
    chain = build_atempo_chain(target_speed)
    if len(chain) == 1:
        _run([ffmpeg, '-y', '-i', src, '-filter:a', f'atempo={chain[0]}', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', out], logger)
        return
    # 多级链：级联滤镜，避免中间文件
    filters = ','.join([f'atempo={c}' for c in chain])
    _run([ffmpeg, '-y', '-i', src, '-filter:a', filters, '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', out], logger)


def place_audio_at(src: str, start_s: float, out_wav: str, ffmpeg: str, logger: logging.Logger) -> None:
    """把音频放到指定时间点（前导静音）。"""
    ms = int(max(0.0, start_s) * 1000)
    _run([
        ffmpeg, '-y', '-i', src, '-af', f'adelay={ms}:all=1',
        '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', out_wav,
    ], logger)


def build_duck_track(orig_wav: str, cue_windows: List[Tuple[float, float]], out_wav: str, ffmpeg: str, logger: logging.Logger) -> None:
    """压低模式：语音时间窗内原轨降 18dB，其余不变。"""
    if not cue_windows:
        shutil_copy(orig_wav, out_wav)
        return
    filters = []
    for start_s, end_s in cue_windows:
        filters.append(
            f"volume=0.125:enable='between(t,{start_s:.3f},{end_s:.3f})'"
        )
    _run([
        ffmpeg, '-y', '-i', orig_wav, '-af', ','.join(filters),
        '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', out_wav,
    ], logger)


def shutil_copy(src: str, dst: str) -> None:
    import shutil
    shutil.copyfile(src, dst)


def mix_tracks(base_wav: str, overlay_wavs: List[str], out_wav: str, ffmpeg: str, logger: logging.Logger) -> None:
    """叠加多条已定位轨道到基底上（amix，归一化 + 动态响度）。"""
    if not overlay_wavs:
        shutil_copy(base_wav, out_wav)
        return
    cmd = [ffmpeg, '-y']
    inputs = ['-i', base_wav]
    for w in overlay_wavs:
        inputs += ['-i', w]
    cmd += inputs
    filter_complex = ';'.join(
        [f'[{i}:a]volume=1.0[a{i}]' for i in range(len(overlay_wavs))]
    )
    # 所有 overlay 与 base 混合
    mix_inputs = ''.join(f'[a{i}]' for i in range(len(overlay_wavs)))
    cmd += [
        '-filter_complex',
        f'{filter_complex};[0:a]{mix_inputs}amix=inputs={len(overlay_wavs) + 1}:duration=longest:normalize=1[aout]',
        '-map', '[aout]', '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', out_wav,
    ]
    _run(cmd, logger)


def mux_dubbed_video(video_path: str, dubbed_audio_wav: str, out_mp4: str, ffmpeg: str, logger: logging.Logger) -> str:
    """用合成音轨替换视频音轨（视频流 copy，保留烧录字幕画面）。"""
    _run([
        ffmpeg, '-y', '-i', video_path, '-i', dubbed_audio_wav,
        '-map', '0:v:0', '-map', '1:a:0',
        '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
        '-shortest', '-movflags', '+faststart', out_mp4,
    ], logger)
    return out_mp4


# ---------------------------------------------------------------- 分离

def separate_instrumental(
    audio_wav: str,
    out_dir: str,
    model_name: str,
    logger: logging.Logger,
) -> Optional[str]:
    """用 audio-separator（onnxruntime CPU）分离伴奏轨；失败返回 None（由调用方降级）。"""
    try:
        from audio_separator.separator import Separator  # 懒加载：避免缺依赖时导入失败
    except Exception as exc:
        logger.warning('audio-separator 未安装（%s），降级为压低模式', exc)
        return None

    model_dir = os.path.join(get_app_subdir('models'), 'audio_separator')
    os.makedirs(model_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)
    model_name = str(model_name or _DEFAULT_SEPARATION_MODEL)

    # audio-separator 需要系统 ffmpeg（探测 + 内部 IO）：调用期间把项目内置 ffmpeg 目录前置到 PATH
    ffmpeg_checked = get_ffmpeg_path(logger=logger)
    app_ffmpeg_dir = os.path.dirname(ffmpeg_checked) if ffmpeg_checked else None
    old_path = os.environ.get('PATH', '')
    if app_ffmpeg_dir:
        os.environ['PATH'] = app_ffmpeg_dir + os.pathsep + old_path
    try:
        separator = Separator(
            output_dir=str(out_dir),
            model_file_dir=str(model_dir),
            output_format='WAV',
            use_soundfile=True,
        )
        try:
            # 0.44+ API：模型按文件名加载
            separator.load_model(model_filename=model_name)
        except TypeError:
            # 旧版 API：model_name 直接传入构造器
            separator.load_model(model_name=model_name)
        files = separator.separate(audio_wav)
    except Exception as exc:
        logger.warning('音频分离失败（%s），降级为压低模式', str(exc)[:200])
        return None
    finally:
        os.environ['PATH'] = old_path
    if not files:
        logger.warning('音频分离未产生输出，降级为压低模式')
        return None
    # 优先取 instrumental（非 vocals 且文件名含 instrumental/“伴奏”标识）
    for name in files:
        lower = str(name).lower()
        if 'instrumental' in lower or 'kara' in lower:
            return os.path.join(out_dir, name)
    return os.path.join(out_dir, files[0])


# ---------------------------------------------------------------- cue 参考样本

def extract_reference_sample(
    audio_wav: str,
    duration_s: float,
    original_cues: List[Dict[str, Any]],
    ffmpeg: str,
    logger: logging.Logger,
) -> Optional[bytes]:
    """截取 10~30s 干净人声样本（优先第一条>10s 的话语 cue，否则从 0 开始）。"""
    window: Optional[Tuple[float, float]] = None
    for cue in original_cues:
        start_s = float(cue.get('start', 0) or 0)
        end_s = float(cue.get('end', 0) or 0)
        if end_s - start_s >= 10.0:
            window = (start_s, min(end_s, start_s + _REFERENCE_MAX_SECONDS))
            break
    if window is None and duration_s > 10:
        window = (0.0, min(10.0 + _REFERENCE_SAMPLE_SECONDS, duration_s))

    if window is None:
        return None
    with tempfile.TemporaryDirectory(prefix='tts_ref_') as tmp:
        sample = os.path.join(tmp, 'ref.wav')
        try:
            cut_audio_range(audio_wav, window[0], window[1] - window[0], sample, ffmpeg, logger)
            with open(sample, 'rb') as fh:
                return fh.read()
        except Exception as exc:
            logger.warning('参考音频截取失败: %s', exc)
            return None


def _cue_texts_in_window(cues: List[Dict[str, Any]], start_s: float, end_s: float) -> str:
    parts = []
    for cue in cues:
        cue_start = float(cue.get('start', 0) or 0)
        cue_end = float(cue.get('end', 0) or 0)
        if cue_start >= start_s - 0.5 and cue_start < end_s:
            text = str(cue.get('text') or '').strip()
            if text:
                parts.append(text)
    return ' '.join(parts)


# ---------------------------------------------------------------- 主流程

def build_dubbed_audio(
    task_dir: str,
    video_path: str,
    translated_srt_path: str,
    original_srt_path: Optional[str],
    config: Dict[str, Any],
    logger: logging.Logger,
) -> Tuple[Optional[str], List[str]]:
    """执行配音全流程，返回 (合成音轨 wav 路径 | None, 警告列表)。"""
    warnings: List[str] = []
    enabled = bool(config.get('TTS_DUB_ENABLED', False))
    api_key = str(config.get('TTS_DUB_API_KEY') or '').strip()
    if not enabled or not api_key:
        warnings.append('TTS 配音未启用或未配置 API Key，跳过')
        return None, warnings

    try:
        ffmpeg = _ffmpeg_path(logger)
        ffprobe = _ffprobe_path(ffmpeg, logger)
    except TtsDubError as exc:
        warnings.append(str(exc))
        return None, warnings

    if not os.path.isfile(translated_srt_path) or not os.path.isfile(video_path):
        warnings.append('翻译字幕或视频文件缺失，跳过配音')
        return None, warnings

    try:
        engine = SrtTransformEngine(SrtTransformConfig(), logger=logger)
        with open(translated_srt_path, 'r', encoding='utf-8', errors='replace') as fh:
            cues = engine.parse_srt(fh.read())
    except Exception as exc:
        warnings.append(f'解析翻译字幕失败: {exc}')
        return None, warnings

    usable_cues = [c for c in cues if len(str(c.get('text') or '').strip()) >= 2]
    if not usable_cues:
        warnings.append('翻译字幕无可用 cue，跳过配音')
        return None, warnings

    original_cues: List[Dict[str, Any]] = []
    if original_srt_path and os.path.isfile(original_srt_path):
        try:
            with open(original_srt_path, 'r', encoding='utf-8', errors='replace') as fh:
                original_cues = engine.parse_srt(fh.read())
        except Exception:
            original_cues = []

    logger.info('TTS 配音开始：%d 条 cue', len(usable_cues))
    tmp_dir = os.path.join(task_dir, '_dub_tmp')
    os.makedirs(tmp_dir, exist_ok=True)

    try:
        # 1. 提取原音轨
        orig_wav = os.path.join(tmp_dir, 'orig.wav')
        extract_audio(video_path, orig_wav, ffmpeg, logger)
        total_duration = probe_duration(video_path, ffprobe, logger)

        # 2. 背景处理
        bg_mode = str(config.get('TTS_DUB_BACKGROUND_MODE') or 'separate').strip().lower()
        max_minutes = float(config.get('TTS_DUB_MAX_DURATION_MINUTES', 20) or 20)
        if bg_mode == 'separate' and total_duration > max_minutes * 60:
            logger.info('视频时长 %.1f 分钟超过 %.0f 分钟上限，转为压低模式', total_duration / 60, max_minutes)
            bg_mode = 'duck'

        base_track: Optional[str] = None
        if bg_mode == 'separate':
            instrumental = separate_instrumental(
                orig_wav, tmp_dir, str(config.get('TTS_DUB_SEPARATION_MODEL') or _DEFAULT_SEPARATION_MODEL), logger,
            )
            if instrumental and os.path.isfile(instrumental):
                base_track = instrumental
                logger.info('背景处理：分离模式（instrumental）')
            else:
                bg_mode = 'duck'

        cue_windows = [(float(c['start']), float(c['end'])) for c in usable_cues]
        if base_track is None:
            build_duck_track(orig_wav, cue_windows, os.path.join(tmp_dir, 'base_duck.wav'), ffmpeg, logger)
            base_track = os.path.join(tmp_dir, 'base_duck.wav')
            logger.info('背景处理：压低模式（原轨语音窗降 18dB）')

        # 3. 参考音色
        reference_mode = str(config.get('TTS_DUB_REFERENCE_MODE') or 'auto').strip().lower()
        reference_id = str(config.get('TTS_DUB_VOICE_ID') or '').strip() or None
        reference_audio: Optional[bytes] = None
        reference_text = ''
        if reference_id:
            pass  # 使用固定声音 ID
        elif reference_mode == 'auto':
            reference_audio = extract_reference_sample(orig_wav, total_duration, original_cues, ffmpeg, logger)
            if reference_audio:
                first_cue = original_cues[0] if original_cues else None
                if first_cue:
                    reference_text = ' '.join(str(c.get('text') or '') for c in original_cues[:3])[:300]
                logger.info('参考音色：零样本克隆（%.2fKB）', len(reference_audio) / 1024)
            else:
                logger.info('参考音色：未获得采样，使用默认音色')

        # 4. 逐 cue 合成 + 拟合 + 定位
        client = FishAudioTtsClient(
            api_key=api_key,
            base_url=str(config.get('TTS_DUB_BASE_URL') or DEFAULT_BASE_URL),
            model=str(config.get('TTS_DUB_MODEL') or DEFAULT_MODEL),
            max_retries=int(config.get('TTS_DUB_MAX_RETRIES') or 3),
            retry_delay_s=float(config.get('TTS_DUB_RETRY_DELAY') or 2),
            logger=logger,
        )
        base_speed = float(config.get('TTS_DUB_SPEED') or 1.0)

        overlays: List[str] = []
        placed_count = 0
        for idx, cue in enumerate(usable_cues, 1):
            start_s = float(cue['start'])
            window_s = max(float(cue['end']) - start_s, _MIN_CUE_DURATION_S)
            text = str(cue.get('text') or '').strip()
            if not text:
                continue
            try:
                raw = client.synthesize(
                    text,
                    reference_id=reference_id,
                    reference_audio=reference_audio,
                    reference_text=reference_text,
                    speed=base_speed,
                )
                raw_path = os.path.join(tmp_dir, f'cue_{idx:04d}_raw.mp3')
                with open(raw_path, 'wb') as fh:
                    fh.write(raw)
                tts_duration = probe_duration(raw_path, ffprobe, logger)
                fit_speed = fit_cue_speed(tts_duration, window_s)
                if fit_speed > 1.0:
                    fitted_path = os.path.join(tmp_dir, f'cue_{idx:04d}_fitted.wav')
                    fit_audio_speed(raw_path, fit_speed, fitted_path, ffmpeg, logger)
                else:
                    fitted_path = raw_path
                placed_path = os.path.join(tmp_dir, f'cue_{idx:04d}_placed.wav')
                place_audio_at(fitted_path, start_s, placed_path, ffmpeg, logger)
                overlays.append(placed_path)
                placed_count += 1
            except Exception as exc:
                warnings.append(f'cue #{idx} 合成失败: {str(exc)[:120]}')
                logger.warning('cue #%d/%d 合成失败: %s', idx, len(usable_cues), exc)

        if not overlays:
            warnings.append('全部 cue 合成失败，保留原音频')
            return None, warnings

        # 5. 混合
        logger.info('混合 %d 条配音轨道（共 %d 条 cue）', placed_count, len(usable_cues))
        mixed_wav = os.path.join(tmp_dir, 'dubbed.wav')
        mix_tracks(base_track, overlays, mixed_wav, ffmpeg, logger)
        return mixed_wav, warnings
    except TtsDubError as exc:
        warnings.append(str(exc))
        return None, warnings
    except Exception as exc:  # noqa: BLE001 - 兜底不阻塞主流程
        warnings.append(f'配音流程异常: {str(exc)[:200]}')
        return None, warnings
    finally:
        # 保留 tmp_dub 目录里的最终产物，供上层做 mux；清理可由任务文件删除逻辑兜底
        pass
