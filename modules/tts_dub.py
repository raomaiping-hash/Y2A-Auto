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
import shutil
import subprocess
import tempfile
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
# 变速软上限（参考 VideoLingo speed_factor.max=1.4）：超窗句由字幕对齐(合并/修剪)解决，
# 变速只做轻微适配，避免超快/急促。
_FIT_SPEED_MAX = 1.4
# 中文常态语速估算（秒/字），用于字幕-时长对齐预检（参考 VideoLingo estimate_duration）
_CN_DUR_PER_CHAR_S = 0.25
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


def estimate_duration(text: str) -> float:
    """估算文本朗读时长（秒）。中文按字数×0.25s/字，英文按词数×0.35s/词。

    用于配音前"字幕-时长对齐"预检：判断某句是否超出窗口可读范围，
    超窗句应由上层修剪文本而非依赖变速硬压（参考 VideoLingo estimate_duration）。
    """
    import re
    text = str(text or '').strip()
    if not text:
        return 0.0
    cn = len(re.findall(r'[\u4e00-\u9fff]', text))
    noncn_words = len(re.findall(r'[A-Za-z]+', text))
    return cn * _CN_DUR_PER_CHAR_S + noncn_words * 0.35


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
        # 复用连接池（httpx.Client 线程安全），避免并发合成时重复 HTTPS/TLS 握手
        self._client = httpx.Client(timeout=self.timeout_s)

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
                resp = self._client.post(url, json=body, headers=headers)
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


def build_duck_track(orig_wav: str, cue_windows: List[Tuple[float, float]], out_wav: str, ffmpeg: str, logger: logging.Logger, duck_level: float = 0.03) -> None:
    """压低模式：语音时间窗内原轨降低 duck_level 倍（默认 0.03≈-30dB），其余不变。

    压低幅度越大，原语音让位越多，合成配音越突出；非语音窗（背景音）保留原声。
    默认 0.03 使语音窗原声几乎静音，达到"替换人声、保留背景"的效果。
    """
    if not cue_windows:
        copy_file(orig_wav, out_wav)
        return
    filters = []
    for start_s, end_s in cue_windows:
        filters.append(
            f"volume={float(duck_level):.4g}:enable='between(t,{start_s:.3f},{end_s:.3f})'"
        )
    _run([
        ffmpeg, '-y', '-i', orig_wav, '-af', ','.join(filters),
        '-ar', '44100', '-ac', '2', '-c:a', 'pcm_s16le', out_wav,
    ], logger)


def copy_file(src: str, dst: str) -> None:
    shutil.copyfile(src, dst)


def mix_tracks(base_wav: str, overlay_wavs: List[str], out_wav: str, ffmpeg: str, logger: logging.Logger, cue_gain: float = 2.0) -> None:
    """叠加多条已定位轨道到基底上。

    注意：amix 必须用 normalize=0（求和模式）——默认的 normalize=1 会把
    每条输入除以输入总数，几百条 cue 叠加后整体趋近静音。
    求和后用 alimiter 防止偶发重叠导致的削波。

    cue_gain：对合成配音轨道统一提升倍率（fish.audio 输出音量偏低，
    默认 2.0≈+6dB 使其相较压低后的原声更突出、清晰）。
    """
    if not overlay_wavs:
        copy_file(base_wav, out_wav)
        return
    gain = max(0.1, float(cue_gain or 2.0))
    cmd = [ffmpeg, '-y']
    inputs = ['-i', base_wav]
    for w in overlay_wavs:
        inputs += ['-i', w]
    cmd += inputs
    # 并行链用 ; 分隔：base 打标签 + 每个合成轨道加增益打标签，再 amix 求和
    n = len(overlay_wavs)
    parts = ['[0:a]anull[base]'] + [
        f'[{i + 1}:a]volume={gain:.4g}[o{i + 1}]' for i in range(n)
    ]
    amix_in = '[base]' + ''.join(f'[o{i + 1}]' for i in range(n))
    filter_complex = (
        ';'.join(parts)
        + f';{amix_in}amix=inputs={n + 1}:duration=longest:normalize=0,'
          f'alimiter=limit=0.95:level=0[aout]'
    )
    cmd += [
        '-filter_complex', filter_complex,
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

# 全局分离互斥锁：MDX 分离是 CPU 密集型（N100 4 核），并发会互相拖慢数倍。
# 同一时刻只允许一个分离；其他请求排队等待（默认最多等 60 分钟，超时降级压低模式）。
_SEPARATION_LOCK = threading.Lock()
_SEPARATION_WAIT_SECONDS = 3600


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

    if not _SEPARATION_LOCK.acquire(timeout=_SEPARATION_WAIT_SECONDS):
        logger.warning('等待分离锁超时（有其他分离任务占满 CPU），降级为压低模式')
        return None
    try:
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
        # 优先取 instrumental 轨（文件名含 instrumental）
        for name in files:
            if 'instrumental' in str(name).lower():
                return os.path.join(out_dir, name)
        # 兜底：非 vocals 的 stem（模型名可能含 kara 干扰匹配）
        non_vocals = [name for name in files if 'vocals' not in str(name).lower()]
        if non_vocals:
            return os.path.join(out_dir, non_vocals[0])
        return os.path.join(out_dir, files[0])
    finally:
        _SEPARATION_LOCK.release()


def _split_narration_into_cues(text: str, max_chars: int = 20) -> List[str]:
    """把一段连续旁白按标点/长度切成短句块（供字幕分屏显示，避免整段堆叠超框）。

    优先在中文标点（。！？；，）处断句；单块超过 max_chars 则强制在最近标点前切，
    无标点则按长度硬切。返回按语言顺序排列的短句列表。
    """
    import re
    text = str(text or '').strip()
    if not text:
        return []
    # 归一化常见分隔，切出“句”级候选
    parts = re.split(r'(?<=[。！？；，、])', text)
    parts = [p.strip() for p in parts if p and p.strip()]
    chunks: List[str] = []
    for part in parts:
        # 单句仍超长：继续按长度+标点切
        while len(part) > max_chars:
            window = part[:max_chars]
            # 在窗口内找最后一个标点，尽量在标点处切
            cut = -1
            for idx in range(len(window) - 1, 0, -1):
                if window[idx] in '，。；、！？':
                    cut = idx
                    break
            if cut <= 0 or cut >= len(part) - 1:
                cut = max_chars
            chunks.append(part[:cut].strip())
            part = part[cut:].strip()
        if part:
            chunks.append(part)
    return [c for c in chunks if c]


def separate_instrumental_via_api(
    audio_wav: str,
    out_dir: str,
    api_url: str,
    api_key: str,
    model: str,
    ffmpeg: str,
    logger: logging.Logger,
) -> Optional[str]:
    """调用云端音频分离 API（free.ai /v1/music/separate）把原声去掉，取 instrumental 纯背景。

    返回纯背景 wav 路径；失败返回 None（由调用方降级）。
    上传前把原声编码为 128k 立体声 mp3（小于 50MB 限制、更快）；分离结果下载到 out_dir。
    """
    import requests
    from urllib.parse import urlparse

    if not api_key:
        logger.warning('云端分离未配置 API Key，跳过')
        return None
    if not api_url:
        logger.warning('云端分离未配置 API 地址，跳过')
        return None

    try:
        mp3_path = os.path.join(out_dir, 'orig_for_separation.mp3')
        _run([
            ffmpeg, '-y', '-i', audio_wav,
            '-ac', '2', '-ar', '44100', '-c:a', 'libmp3lame', '-b:a', '128k',
            mp3_path,
        ], logger)
        if not os.path.isfile(mp3_path) or os.path.getsize(mp3_path) <= 0:
            logger.warning('云端分离源音频编码失败')
            return None

        with open(mp3_path, 'rb') as fh:
            files = {'file': ('audio.mp3', fh, 'audio/mpeg')}
            resp = requests.post(
                api_url,
                headers={'Authorization': f'Bearer {api_key}'},
                files=files,
                data={'model': str(model or 'demucs')},
                timeout=600,
            )
        if resp.status_code != 200:
            logger.warning('云端分离请求失败 HTTP %s: %s', resp.status_code, resp.text[:160])
            return None
        data = resp.json() or {}
        stems = data.get('stems') or {}
        stem_url = stems.get('instrumental') or stems.get('no_vocals')
        if not stem_url:
            logger.warning('云端分离未返回 instrumental stem')
            return None

        # stem_url 可能是相对路径（/static/outputs/...），补齐主机
        if not str(stem_url).startswith('http'):
            parsed = urlparse(str(api_url))
            stem_url = f'{parsed.scheme}://{parsed.netloc}{stem_url}'

        # 下载（分离结果可能稍后才就绪，做短重试）
        out_wav = os.path.join(out_dir, 'instrumental.wav')
        last_err = ''
        for attempt in range(1, 6):
            try:
                dl = requests.get(stem_url, headers={'Authorization': f'Bearer {api_key}'}, timeout=120)
            except Exception as exc:
                last_err = f'{type(exc).__name__}: {str(exc)[:100]}'
                dl = None
            if dl is not None and dl.status_code == 200 and dl.content:
                with open(out_wav, 'wb') as fh:
                    fh.write(dl.content)
                logger.info('云端分离 instrumental 已就绪（第 %d 次）', attempt)
                return out_wav
            last_err = f'HTTP {dl.status_code if dl is not None else "?"}' if dl is not None else last_err
            if attempt < 5:
                time.sleep(3 * attempt)
        logger.warning('云端分离结果下载失败: %s', last_err)
        return None
    except Exception as exc:
        logger.warning('云端分离异常: %s', str(exc)[:180])
        return None


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


def ensure_reference_model(
    api_key: str,
    base_url: str,
    sample_path: str,
    logger: logging.Logger,
    title: str = 'Y2A-Auto 配音克隆',
) -> Optional[str]:
    """把参考音频上传为私有克隆模型，返回 reference_id；带 md5 缓存避免重复建库。"""
    import hashlib
    import requests

    with open(sample_path, 'rb') as fh:
        sample_bytes = fh.read()
    digest = hashlib.md5(sample_bytes).hexdigest()

    cache_path = os.path.join(get_app_subdir('models'), 'tts_voice_models.json')
    try:
        with open(cache_path, 'r', encoding='utf-8') as fh:
            cache = json.load(fh)
        if digest in cache:
            logger.info('复用已缓存的克隆声音模型 %s', cache[digest])
            return cache[digest]
    except Exception:
        cache = {}

    resp = None
    last_err = ''
    for attempt in range(1, 4):  # 网络/SSL 波动重试，成功才克隆，避免音色丢失
        try:
            resp = requests.post(
                f'{base_url.rstrip("/")}/model',
                headers={'Authorization': f'Bearer {api_key}'},
                data={
                    'type': 'tts',
                    'title': f'{title} {time.strftime("%m%d%H%M")}',
                    'train_mode': 'fast',
                    'visibility': 'private',
                },
                files={'voices': ('reference.mp3', sample_bytes, 'audio/mpeg')},
                timeout=120,
            )
            break
        except Exception as exc:
            last_err = f'{type(exc).__name__}: {str(exc)[:100]}'
            logger.warning('克隆声音模型请求失败(第%d/3次): %s', attempt, last_err)
            if attempt < 3:
                time.sleep(2)
    if resp is None:
        logger.warning('克隆声音模型多次失败，使用默认音色: %s', last_err)
        return None
    if resp.status_code != 201:
        logger.warning('创建克隆声音模型失败 HTTP %s: %s', resp.status_code, resp.text[:160])
        return None
    model_id = str((resp.json() or {}).get('_id') or '').strip()
    if not model_id:
        logger.warning('创建克隆声音模型未返回 id')
        return None
    try:
        cache[digest] = model_id
        os.makedirs(os.path.dirname(cache_path), exist_ok=True)
        with open(cache_path, 'w', encoding='utf-8') as fh:
            json.dump(cache, fh, ensure_ascii=False, indent=1)
    except Exception:
        pass
    logger.info('克隆声音模型已创建：%s', model_id)
    return model_id


# ---------------------------------------------------------------- 主流程

# ---------------------------------------------------------------- 新管线：整段文案 + STT 反推时间戳
# ---------------------------------------------------------------

def _rewrite_script(texts: List[str], config: Dict[str, Any], logger: logging.Logger) -> Optional[str]:
    """用 LLM 把逐条字幕重写为一段通顺、连贯的中文旁白（整段，非逐句碎片）。"""
    import openai
    api_key = str(config.get('OPENAI_API_KEY') or '').strip()
    base_url = str(config.get('OPENAI_BASE_URL') or 'https://api.openai.com/v1').strip()
    model = str(config.get('OPENAI_MODEL_NAME') or 'gpt-3.5-turbo').strip()
    if not api_key:
        logger.warning('重写文案缺少 OPENAI_API_KEY')
        return None
    src = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(texts) if str(t or '').strip())
    if not src:
        return None
    client = openai.OpenAI(api_key=api_key, base_url=base_url)
    sysp = (
        "你是专业视频文案润色。把下面逐条字幕重写为一段通顺、连贯、口语化的中文旁白，"
        "保持原意和顺序，消除逐条的机械感。用句号标句（每句末尾用句号），句与句之间自然停顿，"
        "可适当合并重复语义、连缀成自然语流。只输出润色后的整段旁白文本，不要编号、不要解释、不要JSON。"
    )
    try:
        r = client.chat.completions.create(
            model=model,
            messages=[{'role': 'system', 'content': sysp}, {'role': 'user', 'content': src}],
            max_tokens=4096,
        )
        script = (r.choices[0].message.content or '').strip()
        if script:
            logger.info('重写整段文案 %d 字', len(script))
        return script or None
    except Exception as exc:
        logger.warning('重写整段文案失败: %s', str(exc)[:160])
        return None


def _transcribe_segments(audio_wav: str, config: Dict[str, Any], logger: logging.Logger, out_dir: str) -> List[Dict[str, Any]]:
    """用项目 grok-stt + VAD 把合成语音反推为带时间戳的段落（语音自身时间轴）。"""
    try:
        from .speech_recognition import create_speech_recognizer_from_config
        rec = create_speech_recognizer_from_config(config, 'dub')
        if rec is None:
            logger.warning('无法创建语音识别器，STT 反推失败')
            return []
        out_srt = os.path.join(out_dir, 'asr_reverse.srt')
        res = rec.transcribe_video_to_subtitles(audio_wav, out_srt)
        if not res or not os.path.isfile(out_srt):
            logger.warning('STT 反推未产出字幕')
            return []
        from .srt_transform_engine import SrtTransformConfig, SrtTransformEngine
        eng = SrtTransformEngine(SrtTransformConfig(), logger=logger)
        cues = eng.parse_srt(open(out_srt, encoding='utf-8', errors='replace').read())
        segs = [
            {'start': float(c['start']), 'end': float(c['end']), 'text': str(c.get('text') or '').strip()}
            for c in cues if str(c.get('text') or '').strip()
        ]
        logger.info('STT 反推段落 %d 个', len(segs))
        return segs
    except Exception as exc:
        logger.warning('STT 反推失败: %s', str(exc)[:160])
        return []


def _map_segments_to_video(
    segs: List[Dict[str, Any]],
    script_dur: float,
    original_cues: List[Dict[str, Any]],
    total_duration: float,
    logger: logging.Logger,
) -> List[Dict[str, Any]]:
    """把语音段按"段在语音中的相对位置"线性映射到"视频说话时间轴"（比例位置，不拉伸音频）。"""
    if not segs or script_dur <= 0:
        return []
    # 视频说话范围 = 源 ASR 首句start ~ 末句end
    sp = [float(c['start']) for c in original_cues if str(c.get('text') or '').strip()]
    ep = [float(c['end']) for c in original_cues if str(c.get('text') or '').strip()]
    if sp and ep:
        v0, v1 = min(sp), max(ep)
    else:
        v0, v1 = 0.0, float(total_duration)
    if v1 - v0 <= 0:
        v1 = v0 + 1.0
    out: List[Dict[str, Any]] = []
    for seg in segs:
        t0, t1 = float(seg['start']), float(seg['end'])
        m0 = v0 + (t0 / script_dur) * (v1 - v0)
        m1 = v0 + (t1 / script_dur) * (v1 - v0)
        if m1 - m0 < _MIN_CUE_DURATION_S:
            m1 = m0 + _MIN_CUE_DURATION_S
        out.append({
            'src_start': t0, 'src_end': t1,
            'video_start': m0, 'video_end': m1,
            'text': seg.get('text', ''),
        })
    logger.info('语音段映射到视频时间轴: %d 段 (范围 %.1f-%.1fs)', len(out), v0, v1)
    return out


def _fmt_srt_ts(seconds: float) -> str:
    """把秒数格式化为规范 SRT 时间戳 HH:MM:SS,mmm（避免浮点时间戳导致 libass 无法烧录）。"""
    if seconds < 0:
        seconds = 0.0
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


_SUBTITLE_MAX_CHARS = 20  # 单条字幕块最大字数（避免整段堆叠/超框），配合 ASS 折行渲染


def write_aligned_dub_subtitle(mapped: List[Dict[str, Any]], out_srt: str) -> Optional[str]:
    """把映射到视频时间轴上的旁白段写成"画面字幕 = 旁白"的 srt。

    每段旁白被切成若干短块（≤_SUBTITLE_MAX_CHARS 字，优先在标点处断），
    并按字数比例把该段被映射/拉伸后的完整时长（video_start ~ video_end）
    分配给各块，使字幕连续、逐块跟随语速（音频已拉伸填满该窗口，无空档）。
    返回输出路径；无有效段时返回 None。
    """
    segs = [m for m in mapped if str(m.get('text') or '').strip()]
    if not segs:
        return None
    lines: List[str] = []
    idx = 1
    for ms in segs:
        start = float(ms['video_start'])
        end = float(ms['video_end'])
        if end - start <= 0:
            end = start + max(0.5, float(ms.get('src_end', start)) - float(ms.get('src_start', start)))
        chunks = _split_narration_into_cues(str(ms['text']), _SUBTITLE_MAX_CHARS)
        total_chars = sum(len(c) for c in chunks) or 1
        cursor = start
        for chunk in chunks:
            dur = (end - start) * (len(chunk) / total_chars)
            sub_end = min(end, cursor + max(0.4, dur))
            lines.append(str(idx))
            lines.append(f"{_fmt_srt_ts(cursor)} --> {_fmt_srt_ts(sub_end)}")
            lines.append(chunk)
            lines.append('')
            cursor = sub_end
            idx += 1
    content = '\n'.join(lines).strip() + '\n'
    os.makedirs(os.path.dirname(out_srt), exist_ok=True)
    with open(out_srt, 'w', encoding='utf-8') as fh:
        fh.write(content)
    return out_srt


def build_dubbed_audio(
    task_dir: str,
    video_path: str,
    translated_srt_path: str,
    original_srt_path: Optional[str],
    config: Dict[str, Any],
    logger: logging.Logger,
) -> Tuple[Optional[str], List[str], Optional[str]]:
    """执行配音全流程，返回 (合成音轨 wav 路径 | None, 警告列表, 对齐旁白字幕 srt 路径 | None)。"""
    warnings: List[str] = []
    enabled = bool(config.get('TTS_DUB_ENABLED', False))
    api_key = str(config.get('TTS_DUB_API_KEY') or '').strip()
    if not enabled or not api_key:
        warnings.append('TTS 配音未启用或未配置 API Key，跳过')
        return None, warnings, None

    try:
        ffmpeg = _ffmpeg_path(logger)
        ffprobe = _ffprobe_path(ffmpeg, logger)
    except TtsDubError as exc:
        warnings.append(str(exc))
        return None, warnings, None

    if not os.path.isfile(translated_srt_path) or not os.path.isfile(video_path):
        warnings.append('翻译字幕或视频文件缺失，跳过配音')
        return None, warnings, None

    try:
        engine = SrtTransformEngine(SrtTransformConfig(), logger=logger)
        with open(translated_srt_path, 'r', encoding='utf-8', errors='replace') as fh:
            cues = engine.parse_srt(fh.read())
    except Exception as exc:
        warnings.append(f'解析翻译字幕失败: {exc}')
        return None, warnings, None

    usable_cues = [c for c in cues if len(str(c.get('text') or '').strip()) >= 2]
    if not usable_cues:
        warnings.append('翻译字幕无可用 cue，跳过配音')
        return None, warnings, None

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
        # 云端/本地分离对 CPU 无压力，只有本地分离才受时长保护上限（避免 OOM/卡死）
        if bg_mode == 'separate':
            max_minutes = float(config.get('TTS_DUB_MAX_DURATION_MINUTES', 20) or 20)
            if total_duration > max_minutes * 60:
                logger.info('视频时长 %.1f 分钟超过 %.0f 分钟上限，转为压低模式', total_duration / 60, max_minutes)
                bg_mode = 'duck'

        base_track: Optional[str] = None
        # 复用上次尝试已分离的伴奏（重跑不重复推理/不重复付费）
        cached = [
            os.path.join(tmp_dir, f)
            for f in sorted(os.listdir(tmp_dir))
            if 'instrumental' in f.lower() and f.lower().endswith('.wav')
            and os.path.getsize(os.path.join(tmp_dir, f)) > 1024
        ]
        if cached and bg_mode in ('separate', 'separate_api'):
            base_track = cached[0]
            logger.info('背景处理：复用上次分离结果 %s', os.path.basename(base_track))

        if base_track is None and bg_mode == 'separate_api':
            instrumental = separate_instrumental_via_api(
                orig_wav, tmp_dir,
                str(config.get('TTS_DUB_SEPARATION_API_URL') or ''),
                str(config.get('TTS_DUB_SEPARATION_API_KEY') or ''),
                str(config.get('TTS_DUB_SEPARATION_API_MODEL') or 'demucs'),
                ffmpeg, logger,
            )
            if instrumental and os.path.isfile(instrumental):
                base_track = instrumental
                logger.info('背景处理：云端分离模式（instrumental，去原声）')
            else:
                logger.warning('云端分离失败，回退本地分离')
                bg_mode = 'separate'

        if base_track is None and bg_mode == 'separate':
            instrumental = separate_instrumental(
                orig_wav, tmp_dir, str(config.get('TTS_DUB_SEPARATION_MODEL') or _DEFAULT_SEPARATION_MODEL), logger,
            )
            if instrumental and os.path.isfile(instrumental):
                base_track = instrumental
                logger.info('背景处理：本地分离模式（instrumental）')
            else:
                bg_mode = 'duck'

        cue_windows = [(float(c['start']), float(c['end'])) for c in usable_cues]
        if base_track is None:
            duck_level = max(0.0001, float(config.get('TTS_DUB_DUCK_LEVEL') or 0.03))
            build_duck_track(
                orig_wav, cue_windows, os.path.join(tmp_dir, 'base_duck.wav'), ffmpeg, logger,
                duck_level,
            )
            base_track = os.path.join(tmp_dir, 'base_duck.wav')
            logger.info('背景处理：压低模式（原轨语音窗降 %.0f dB）', -20.0 * math.log10(duck_level))

        # 3. 参考音色
        reference_mode = str(config.get('TTS_DUB_REFERENCE_MODE') or 'auto').strip().lower()
        reference_id = str(config.get('TTS_DUB_VOICE_ID') or '').strip() or None
        reference_audio: Optional[bytes] = None
        reference_text = ''
        base_url = str(config.get('TTS_DUB_BASE_URL') or DEFAULT_BASE_URL)
        if reference_id:
            pass  # 使用固定声音 ID
        elif reference_mode == 'auto':
            # 零样本 references 在部分端点会被拒（400 invalid），
            # 改为官方推荐路径：把参考音频上传为私有克隆模型，全部 cue 用 reference_id
            sample_path: Optional[str] = None
            try:
                sample_window = None
                duration_for_sample = total_duration
                for cue in original_cues:
                    s0, e0 = float(cue.get('start', 0) or 0), float(cue.get('end', 0) or 0)
                    if e0 - s0 >= 10.0:
                        sample_window = (s0, min(e0, s0 + 30.0))
                        break
                if sample_window is None and total_duration > 10:
                    sample_window = (0.0, min(25.0, total_duration))
                if sample_window:
                    sample_path = os.path.join(tmp_dir, 'reference_sample.mp3')
                    _run([
                        ffmpeg, '-y',
                        '-ss', f'{sample_window[0]:.3f}', '-t', f'{sample_window[1] - sample_window[0]:.3f}',
                        '-i', orig_wav, '-ac', '1', '-ar', '44100', '-c:a', 'libmp3lame', '-b:a', '128k',
                        sample_path,
                    ], logger)
            except Exception as exc:
                logger.warning('参考采样截取失败: %s', exc)
            if sample_path and os.path.isfile(sample_path):
                try:
                    reference_id = ensure_reference_model(api_key, base_url, sample_path, logger)
                except Exception as exc:
                    logger.warning('克隆参考音色失败，使用默认音色: %s', type(exc).__name__)
                    reference_id = None
                if reference_id:
                    logger.info('参考音色：克隆模型已就绪 %s', reference_id)
            if not reference_id:
                logger.info('参考音色：克隆不可用，使用默认音色')
        else:
            logger.info('参考音色：默认音色')

        # 4. 新管线：LLM 重写整段文案 → 一次合成 → STT 反推时间戳 → 映射视频时间轴
        client = FishAudioTtsClient(
            api_key=api_key,
            base_url=str(config.get('TTS_DUB_BASE_URL') or DEFAULT_BASE_URL),
            model=str(config.get('TTS_DUB_MODEL') or DEFAULT_MODEL),
            max_retries=int(config.get('TTS_DUB_MAX_RETRIES') or 3),
            retry_delay_s=float(config.get('TTS_DUB_RETRY_DELAY') or 2),
            logger=logger,
        )
        base_speed = float(config.get('TTS_DUB_SPEED') or 1.0)

        # 4a. LLM 重写整段通顺文案
        script = _rewrite_script([str(c.get('text') or '') for c in usable_cues], config, logger)
        if not script:
            warnings.append('LLM 重写整段文案失败，保留原音频')
            return None, warnings, None
        # 4b. 一次合成整段语音
        raw = client.synthesize(
            script, reference_id=reference_id, reference_audio=reference_audio,
            reference_text=reference_text, speed=base_speed, audio_format='wav',
        )
        script_wav = os.path.join(tmp_dir, 'script.wav')
        with open(script_wav, 'wb') as fh:
            fh.write(raw)
        script_dur = probe_duration(script_wav, ffprobe, logger)
        logger.info('整段合成完成：%d 字，%.1f 秒', len(script), script_dur)
        # 4c. STT 反推段落时间戳（语音自身时间轴）
        segs = _transcribe_segments(script_wav, config, logger, tmp_dir)
        if not segs:
            warnings.append('STT 反推无段落，保留原音频')
            return None, warnings, None
        # 4d. 映射到视频时间轴
        mapped = _map_segments_to_video(segs, script_dur, original_cues, total_duration, logger)
        # 4d2. 把映射结果写成"画面字幕=旁白"的对齐字幕 srt（供上层烧录，保证字幕对得上语音）
        aligned_srt = None
        try:
            aligned_srt = write_aligned_dub_subtitle(
                mapped, os.path.join(task_dir, 'video.zh-Hans.dub-aligned.srt'),
            )
            if aligned_srt:
                logger.info('对齐旁白字幕已生成: %s', aligned_srt)
        except Exception as exc:
            logger.warning('对齐旁白字幕生成失败: %s', str(exc)[:160])
        if not mapped:
            warnings.append('语音段映射无结果，保留原音频')
            return None, warnings, None
        # 4e. 逐段切出并定位（拉伸填满映射窗口，消除音画空档、保证连续对得上）
        overlays: List[str] = []
        placed_count = 0
        for i, ms in enumerate(mapped, 1):
            src_len = ms['src_end'] - ms['src_start']
            if src_len <= 0:
                continue
            seg_audio = os.path.join(tmp_dir, f'seg_{i:03d}.wav')
            cut_audio_range(script_wav, ms['src_start'], src_len, seg_audio, ffmpeg, logger)
            # 把该段拉伸/减速到填满 [video_start, video_end]，使旁白连续覆盖视频时间轴
            window_dur = ms['video_end'] - ms['video_start']
            speed = (src_len / window_dur) if window_dur > 0 else 1.0
            fitted_path = os.path.join(tmp_dir, f'seg_{i:03d}_fitted.wav')
            fit_audio_speed(seg_audio, speed, fitted_path, ffmpeg, logger)
            placed_path = os.path.join(tmp_dir, f'seg_{i:03d}_placed.wav')
            place_audio_at(fitted_path, ms['video_start'], placed_path, ffmpeg, logger)
            overlays.append(placed_path)
            placed_count += 1

        if not overlays:
            warnings.append('全部语音段放置失败，保留原音频')
            return None, warnings, None

        # 5. 混合
        logger.info('混合 %d 段整段旁白（共 %d 段）', placed_count, len(mapped))
        mixed_wav = os.path.join(tmp_dir, 'dubbed.wav')
        mix_tracks(
            base_track, overlays, mixed_wav, ffmpeg, logger,
            float(config.get('TTS_DUB_CUE_GAIN') or 2.0),
        )
        return mixed_wav, warnings, aligned_srt
    except TtsDubError as exc:
        warnings.append(str(exc))
        return None, warnings, None
    except Exception as exc:  # noqa: BLE001 - 兜底不阻塞主流程
        warnings.append(f'配音流程异常: {str(exc)[:200]}')
        return None, warnings, None
    finally:
        # 保留 tmp_dub 目录里的最终产物，供上层做 mux；清理可由任务文件删除逻辑兜底
        pass
