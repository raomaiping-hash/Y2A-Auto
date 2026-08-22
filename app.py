#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import json
import hashlib
import logging
import re
import secrets
import shutil
import time
import uuid
import threading

from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from flask import Flask, request, jsonify, redirect, send_from_directory, session
from functools import wraps
from flask_cors import CORS
from PIL import Image, UnidentifiedImageError
from werkzeug.security import safe_join
from modules.youtube_handler import extract_video_urls_from_playlist
from modules.utils import get_app_subdir
from modules.config_manager import load_config, update_config
from modules.task_manager import add_task, start_task, get_tasks_by_status, update_task, force_upload_task, TASK_STATES, resolve_cookie_file_path
from modules.acfun_auth import AcfunQrLoginSession
from modules.bilibili_auth import BilibiliQrLoginSession
from modules.youtube_monitor import youtube_monitor
from modules.speech_pipeline_settings import (
    SPEECH_PIPELINE_CHECKBOXES,
    SPEECH_PIPELINE_FLOAT_FIELDS,
    SPEECH_PIPELINE_INT_FIELDS,
)
from modules.notifications import (
    CHANNEL_LABELS,
    EVENT_QR_LOGIN_FAILED,
    EVENT_QR_LOGIN_SUCCESS,
    NotificationEvent,
    emit_notification_event,
    get_global_notification_service,
    iter_enabled_channel_ids,
    validate_channel_config_fields,
)
from apscheduler.schedulers.background import BackgroundScheduler

app = Flask(__name__)
app.secret_key = os.urandom(24)  # 用于会话签名

# JSON API v1（Vue 3 SPA 专用）
from modules.api_v1 import api_bp
app.register_blueprint(api_bp)

# 前端构建产物目录（frontend/dist）
FRONTEND_DIST_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'frontend', 'dist')

ALLOWED_COVER_EXTENSIONS = {
    '.jpg': 'image/jpeg',
    '.jpeg': 'image/jpeg',
    '.png': 'image/png',
    '.webp': 'image/webp',
}


def _get_security_state_path():
    try:
        db_dir = get_app_subdir('db')
    except Exception:
        # 回退到当前目录下的db
        db_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'db')
    os.makedirs(db_dir, exist_ok=True)
    return os.path.join(db_dir, 'security_state.json')

def _load_security_state():
    path = _get_security_state_path()
    try:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 兼容缺失字段
                if not isinstance(data, dict):
                    data = {}
        else:
            data = {}
    except Exception:
        data = {}
    # 默认值
    return {
        'failed_attempts': int(data.get('failed_attempts', 0) or 0),
        'locked_until': float(data.get('locked_until', 0) or 0.0),
        'last_attempt': float(data.get('last_attempt', 0) or 0.0),
    }

def _save_security_state(state):
    try:
        path = _get_security_state_path()
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False


# ---- 二维码登录会话存储 ----

_BILIBILI_QR_SESSIONS = {}
_BILIBILI_QR_SESSION_LOCK = threading.Lock()
_BILIBILI_QR_SESSION_TTL_SECONDS = 300

_ACFUN_QR_SESSIONS = {}
_ACFUN_QR_SESSION_LOCK = threading.Lock()
_ACFUN_QR_SESSION_TTL_SECONDS = 420


def _describe_youtube_api_status(status_code: str) -> str:
    messages = {
        'direct_ready': 'YouTube API 初始化成功，当前为直连模式',
        'proxy_ready': 'YouTube API 初始化成功，独立代理已启用',
        'missing_api_key': 'YouTube API 密钥未配置，请先在设置页完成接入。',
        'init_failed': 'YouTube监控 API 初始化失败，请检查 API 密钥、代理配置与网络连通性。',
    }
    return messages.get(status_code, 'YouTube监控 API 状态未知，请检查设置。')


def _build_startup_config_log_summary(config: dict | None) -> dict:
    normalized = dict(config or {})

    return {
        'feature_flags': {
            'AUTO_MODE_ENABLED': bool(normalized.get('AUTO_MODE_ENABLED', False)),
            'NOTIFY_ENABLED': bool(normalized.get('NOTIFY_ENABLED', False)),
            'password_protection_enabled': bool(normalized.get('password_protection_enabled', False)),
            'CONTENT_MODERATION_ENABLED': bool(normalized.get('CONTENT_MODERATION_ENABLED', False)),
            'YOUTUBE_PROXY_ENABLED': bool(normalized.get('YOUTUBE_PROXY_ENABLED', False)),
            'YOUTUBE_API_PROXY_ENABLED': bool(normalized.get('YOUTUBE_API_PROXY_ENABLED', False)),
            'COOKIECLOUD_ENABLED': bool(normalized.get('COOKIECLOUD_ENABLED', False)),
            'SUBTITLE_TRANSLATION_ENABLED': bool(normalized.get('SUBTITLE_TRANSLATION_ENABLED', False)),
            'SPEECH_RECOGNITION_ENABLED': bool(normalized.get('SPEECH_RECOGNITION_ENABLED', False)),
        },
        'config_keys_total': len(normalized),
    }


def _sync_notification_service(config: dict | None = None):
    effective_config = dict(config or load_config())
    try:
        get_global_notification_service(effective_config)
        logger.info("通知服务配置已同步")
    except Exception as e:
        logger.warning(f"同步通知服务配置失败: {e}")


def _append_notification_config_warnings(messages: list, config: dict | None):
    effective_config = dict(config or {})
    if not effective_config.get('NOTIFY_ENABLED'):
        return
    for channel_id in iter_enabled_channel_ids(effective_config):
        missing_fields = validate_channel_config_fields(channel_id, effective_config)
        if missing_fields:
            readable_fields = '、'.join(missing_fields)
            channel_label = CHANNEL_LABELS.get(channel_id, channel_id)
            _append_settings_message(
                messages,
                'warning',
                f'已启用 {channel_label} 通知，但缺少配置：{readable_fields}。该渠道会暂时跳过发送。'
            )


def _coerce_checkbox_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or '').strip().lower() in ('true', '1', 'on', 'yes', 'y')


def _merge_cookiecloud_runtime_settings(payload: dict | None, base_config: dict | None = None) -> dict:
    effective_config = dict(base_config or load_config())
    incoming = dict(payload) if isinstance(payload, dict) else {}

    bool_fields = {'COOKIECLOUD_ENABLED', 'COOKIECLOUD_ALLOW_PLAINTEXT_EXPORT'}
    text_fields = {
        'COOKIECLOUD_SERVER_URL',
        'COOKIECLOUD_UUID',
        'COOKIECLOUD_PASSWORD',
        'COOKIECLOUD_CRYPTO_TYPE',
        'YOUTUBE_COOKIES_PATH',
    }

    for key in bool_fields:
        if key in incoming:
            effective_config[key] = _coerce_checkbox_value(incoming.get(key))

    for key in text_fields:
        if key in incoming:
            value = str(incoming.get(key) or '').strip()
            if key == 'COOKIECLOUD_PASSWORD' and not value:
                continue
            effective_config[key] = value

    return effective_config


def _cookiecloud_operation_error_message(action: str, retry_later: bool = False) -> str:
    action_key = str(action or '').strip().lower()
    if action_key == 'test':
        return 'CookieCloud 连接测试失败，请稍后重试。' if retry_later else 'CookieCloud 连接测试失败，请检查配置后重试。'
    if action_key == 'sync':
        return 'CookieCloud 立即拉取失败，请稍后重试。' if retry_later else 'CookieCloud 立即拉取失败，请检查配置后重试。'
    return 'CookieCloud 操作失败，请稍后重试。' if retry_later else 'CookieCloud 操作失败，请检查配置后重试。'


def _remember_cookiecloud_sync_result(success: bool, message: str):
    status = 'success' if success else 'error'
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        update_config({
            'COOKIECLOUD_LAST_SYNC_AT': timestamp,
            'COOKIECLOUD_LAST_SYNC_STATUS': status,
            'COOKIECLOUD_LAST_SYNC_MESSAGE': str(message or '').strip(),
        })
    except Exception as e:
        logger.warning(f'记录 CookieCloud 最近同步状态失败: {e}')
    return timestamp


def _get_request_ip_address() -> str:
    forwarded_for = request.headers.get('X-Forwarded-For', '')
    if forwarded_for:
        return forwarded_for.split(',')[0].strip()
    return str(request.remote_addr or 'unknown').strip() or 'unknown'


def _emit_login_event(event_type: str, payload: dict):
    emit_notification_event(NotificationEvent(event_type=event_type, payload=payload))


def _cleanup_bilibili_qr_sessions():
    now_ts = time.time()
    with _BILIBILI_QR_SESSION_LOCK:
        stale_ids = []
        for sid, item in _BILIBILI_QR_SESSIONS.items():
            created_at = float(item.get('created_at', 0) or 0)
            if now_ts - created_at > _BILIBILI_QR_SESSION_TTL_SECONDS:
                stale_ids.append(sid)
        for sid in stale_ids:
            _BILIBILI_QR_SESSIONS.pop(sid, None)


def _create_bilibili_qr_session():
    _cleanup_bilibili_qr_sessions()
    session_id = str(uuid.uuid4())
    session_obj = BilibiliQrLoginSession()
    with _BILIBILI_QR_SESSION_LOCK:
        _BILIBILI_QR_SESSIONS[session_id] = {
            'created_at': time.time(),
            'session': session_obj,
            'success_notified': False,
            'failure_notified': False,
        }
    return session_id, session_obj


def _get_bilibili_qr_session(session_id: str):
    if not session_id:
        return None
    _cleanup_bilibili_qr_sessions()
    with _BILIBILI_QR_SESSION_LOCK:
        item = _BILIBILI_QR_SESSIONS.get(session_id)
    if not item:
        return None
    return item.get('session')


def _cleanup_acfun_qr_sessions():
    now_ts = time.time()
    with _ACFUN_QR_SESSION_LOCK:
        stale_ids = []
        for sid, item in _ACFUN_QR_SESSIONS.items():
            created_at = float(item.get('created_at', 0) or 0)
            if now_ts - created_at > _ACFUN_QR_SESSION_TTL_SECONDS:
                stale_ids.append(sid)
        for sid in stale_ids:
            _ACFUN_QR_SESSIONS.pop(sid, None)


def _create_acfun_qr_session():
    _cleanup_acfun_qr_sessions()
    session_id = str(uuid.uuid4())
    session_obj = AcfunQrLoginSession()
    with _ACFUN_QR_SESSION_LOCK:
        _ACFUN_QR_SESSIONS[session_id] = {
            'created_at': time.time(),
            'session': session_obj,
            'success_notified': False,
            'failure_notified': False,
        }
    return session_id, session_obj


def _get_acfun_qr_session(session_id: str):
    if not session_id:
        return None
    _cleanup_acfun_qr_sessions()
    with _ACFUN_QR_SESSION_LOCK:
        item = _ACFUN_QR_SESSIONS.get(session_id)
    if not item:
        return None
    return item.get('session')


def _mark_qr_notification_sent(session_store: dict, lock: threading.Lock, session_id: str, success: bool) -> bool:
    flag_name = 'success_notified' if success else 'failure_notified'
    with lock:
        item = session_store.get(session_id)
        if not item or item.get(flag_name):
            return False
        item[flag_name] = True
        return True


def _emit_qr_login_event_once(
    session_store: dict,
    lock: threading.Lock,
    session_id: str,
    platform: str,
    status_data: dict,
):
    status = str((status_data or {}).get('status') or '').strip().lower()
    if status not in ('done', 'failed'):
        return
    is_success = status == 'done'
    if not _mark_qr_notification_sent(session_store, lock, session_id, is_success):
        return
    _emit_login_event(
        EVENT_QR_LOGIN_SUCCESS if is_success else EVENT_QR_LOGIN_FAILED,
        {
            'platform': platform,
            'message': str((status_data or {}).get('message') or ('Cookies 已保存' if is_success else '登录失败')).strip(),
        }
    )


_SETTINGS_SAVE_OPERATIONS = {}
_SETTINGS_SAVE_LOCK = threading.Lock()
_SETTINGS_SAVE_TTL_SECONDS = 600
_MONITOR_RUN_OPERATIONS = {}
_MONITOR_RUN_LOCK = threading.Lock()
_MONITOR_RUN_TTL_SECONDS = 600


def _new_settings_save_state(operation_id: str) -> dict:
    now_ts = time.time()
    return {
        'operation_id': operation_id,
        'stage': 'saving_config',
        'message': '正在准备保存设置',
        'detail': '正在提交保存任务，请稍候。',
        'percent': None,
        'downloaded_bytes': None,
        'total_bytes': None,
        'done': False,
        'level': 'info',
        'success': None,
        'messages': [],
        'created_at': now_ts,
        'updated_at': now_ts,
        'expires_at': None,
    }


def _cleanup_settings_save_operations():
    now_ts = time.time()
    with _SETTINGS_SAVE_LOCK:
        stale_ids = []
        for operation_id, state in _SETTINGS_SAVE_OPERATIONS.items():
            expires_at = state.get('expires_at')
            if expires_at and now_ts >= float(expires_at):
                stale_ids.append(operation_id)
        for operation_id in stale_ids:
            _SETTINGS_SAVE_OPERATIONS.pop(operation_id, None)


def _update_settings_save_progress(operation_id: str, **fields) -> dict:
    _cleanup_settings_save_operations()
    with _SETTINGS_SAVE_LOCK:
        state = dict(_SETTINGS_SAVE_OPERATIONS.get(operation_id) or _new_settings_save_state(operation_id))
        state.update(fields)
        state['updated_at'] = time.time()
        if state.get('done'):
            state['expires_at'] = state['updated_at'] + _SETTINGS_SAVE_TTL_SECONDS
        _SETTINGS_SAVE_OPERATIONS[operation_id] = state
        return dict(state)


def _get_settings_save_progress(operation_id: str):
    _cleanup_settings_save_operations()
    with _SETTINGS_SAVE_LOCK:
        state = _SETTINGS_SAVE_OPERATIONS.get(operation_id)
        return dict(state) if state else None


def _new_monitor_run_state(operation_id: str, config_id: int) -> dict:
    now_ts = time.time()
    return {
        'operation_id': operation_id,
        'config_id': config_id,
        'message': '监控任务已创建',
        'detail': '正在后台执行 YouTube 监控，请稍候。',
        'done': False,
        'level': 'info',
        'success': None,
        'created_at': now_ts,
        'updated_at': now_ts,
        'expires_at': None,
    }


def _cleanup_monitor_run_operations():
    now_ts = time.time()
    with _MONITOR_RUN_LOCK:
        stale_ids = []
        for operation_id, state in _MONITOR_RUN_OPERATIONS.items():
            expires_at = state.get('expires_at')
            if expires_at and now_ts >= float(expires_at):
                stale_ids.append(operation_id)
        for operation_id in stale_ids:
            _MONITOR_RUN_OPERATIONS.pop(operation_id, None)


def _update_monitor_run_progress(operation_id: str, config_id: int, **fields) -> dict:
    _cleanup_monitor_run_operations()
    with _MONITOR_RUN_LOCK:
        state = dict(_MONITOR_RUN_OPERATIONS.get(operation_id) or _new_monitor_run_state(operation_id, config_id))
        state.update(fields)
        state['config_id'] = config_id
        state['updated_at'] = time.time()
        if state.get('done'):
            state['expires_at'] = state['updated_at'] + _MONITOR_RUN_TTL_SECONDS
        _MONITOR_RUN_OPERATIONS[operation_id] = state
        return dict(state)


def _get_monitor_run_progress(operation_id: str):
    _cleanup_monitor_run_operations()
    with _MONITOR_RUN_LOCK:
        state = _MONITOR_RUN_OPERATIONS.get(operation_id)
        return dict(state) if state else None


def _finalize_monitor_run_operation(operation_id: str, config_id: int, success: bool, message: str, detail: str = ''):
    _update_monitor_run_progress(
        operation_id,
        config_id,
        message=message,
        detail=detail or message,
        done=True,
        level='success' if success else 'error',
        success=success,
    )


def _run_monitor_operation(operation_id: str, config_id: int):
    try:
        success, message = youtube_monitor.run_monitor(config_id)
    except Exception as exc:
        logger.exception("后台执行 YouTube 监控失败，配置ID: %s", config_id)
        success = False
        message = f"监控失败: {exc}"

    detail = '监控记录已更新，可刷新页面查看最新结果。' if success else message
    _finalize_monitor_run_operation(operation_id, config_id, success, message, detail)


def _start_monitor_run_operation(config_id: int):
    config = youtube_monitor.get_monitor_config(config_id)
    if not config:
        return None, None, "监控配置不存在"

    operation_id = str(uuid.uuid4())
    _update_monitor_run_progress(
        operation_id,
        config_id,
        message=f"已启动监控任务：{config['name']}",
        detail='正在后台执行 YouTube 监控，请稍候。',
        done=False,
        level='info',
        success=None,
    )

    monitor_thread = threading.Thread(
        target=_run_monitor_operation,
        args=(operation_id, config_id),
        daemon=True,
        name=f'youtube-monitor-run-{config_id}-{operation_id[:8]}'
    )
    monitor_thread.start()
    return operation_id, config, None


def _append_settings_message(messages: list, category: str, text: str):
    clean_text = str(text or '').strip()
    if not clean_text:
        return
    messages.append({'category': category, 'text': clean_text})


def _get_task_dir_real(task_id: str) -> str:
    downloads_dir_real = os.path.realpath(get_app_subdir('downloads'))
    try:
        normalized_task_id = str(uuid.UUID(str(task_id or '').strip()))
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('非法任务目录') from exc

    safe_task_dir = safe_join(downloads_dir_real, normalized_task_id)
    if not safe_task_dir:
        raise ValueError('非法任务目录')
    task_dir_real = os.path.realpath(safe_task_dir)
    if os.path.commonpath([downloads_dir_real, task_dir_real]) != downloads_dir_real:
        raise ValueError('非法任务目录')
    return task_dir_real


def _safe_join_task_dir(task_dir_real: str, *parts: str) -> str | None:
    try:
        safe_path = safe_join(task_dir_real, *[str(part) for part in parts])
        if not safe_path:
            return None
        file_real = os.path.realpath(safe_path)
        if os.path.commonpath([task_dir_real, file_real]) != task_dir_real:
            return None
        return file_real
    except (ValueError, OSError):
        return None


def _get_cover_file_info(path: str):
    ext = os.path.splitext(str(path or ''))[1].lower()
    return ext, ALLOWED_COVER_EXTENSIONS.get(ext)


def _validate_cover_upload(file_storage):
    if not file_storage or not getattr(file_storage, 'filename', ''):
        raise ValueError('请选择要上传的封面图片')

    ext, _ = _get_cover_file_info(file_storage.filename)
    if ext not in ALLOWED_COVER_EXTENSIONS:
        raise ValueError('仅支持 JPG、JPEG、PNG、WEBP 格式的封面图片')

    current_pos = file_storage.stream.tell()
    try:
        with Image.open(file_storage.stream) as img:
            img.verify()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError(f'上传文件不是有效图片: {exc}') from exc
    finally:
        file_storage.stream.seek(current_pos)

    return ext


def _find_original_cover_backup(task_dir_real: str):
    for ext in ALLOWED_COVER_EXTENSIONS:
        candidate = _safe_join_task_dir(task_dir_real, f'original_cover{ext}')
        if candidate and os.path.exists(candidate):
            return candidate
    return None


def _get_current_cover_path(task: dict, task_dir_real: str):
    cover_path = str(task.get('cover_path_local') or '').strip()
    if cover_path:
        candidate = _safe_join_task_dir(task_dir_real, os.path.basename(cover_path))
        if candidate and os.path.exists(candidate):
            return candidate

    for name in ('cover.jpg', 'cover.png', 'cover.webp', 'thumbnail.jpg', 'thumbnail.png', 'thumbnail.webp'):
        candidate = _safe_join_task_dir(task_dir_real, name)
        if candidate and os.path.exists(candidate):
            return candidate

    if os.path.isdir(task_dir_real):
        with os.scandir(task_dir_real) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                if entry.name.lower().endswith(tuple(ALLOWED_COVER_EXTENSIONS.keys())):
                    candidate = _safe_join_task_dir(task_dir_real, entry.name)
                    if candidate and os.path.exists(candidate):
                        return candidate

    return ''


def _replace_task_cover(task: dict, uploaded_file):
    task_id = str(task.get('id') or '').strip()
    if not task_id:
        raise ValueError('任务不存在')

    task_dir_real = _get_task_dir_real(task_id)
    os.makedirs(task_dir_real, exist_ok=True)

    current_cover_path = _get_current_cover_path(task, task_dir_real)

    ext = _validate_cover_upload(uploaded_file)
    original_backup = _find_original_cover_backup(task_dir_real)

    if not original_backup and current_cover_path:
        current_ext, _ = _get_cover_file_info(current_cover_path)
        if current_ext not in ALLOWED_COVER_EXTENSIONS:
            raise ValueError('当前原始封面格式不受支持，无法创建恢复备份')
        original_backup = _safe_join_task_dir(task_dir_real, f'original_cover{current_ext}')
        if not original_backup:
            raise ValueError('无法创建原始封面备份路径')
        shutil.copy2(current_cover_path, original_backup)

    for existing_ext in ALLOWED_COVER_EXTENSIONS:
        custom_candidate = _safe_join_task_dir(task_dir_real, f'custom_cover{existing_ext}')
        if custom_candidate and os.path.exists(custom_candidate):
            os.remove(custom_candidate)

    new_cover_path = _safe_join_task_dir(task_dir_real, f'custom_cover{ext}')
    if not new_cover_path:
        raise ValueError('无法创建封面保存路径')
    uploaded_file.save(new_cover_path)
    update_task(task_id, cover_path_local=new_cover_path, silent=True)
    return new_cover_path


def _restore_task_cover(task: dict):
    task_id = str(task.get('id') or '').strip()
    if not task_id:
        raise ValueError('任务不存在')

    task_dir_real = _get_task_dir_real(task_id)
    if not os.path.isdir(task_dir_real):
        raise ValueError('任务目录不存在，无法恢复原封面')

    original_backup = _find_original_cover_backup(task_dir_real)
    if not original_backup:
        raise ValueError('未找到原始封面备份，无法恢复')

    update_task(task_id, cover_path_local=original_backup, silent=True)
    return original_backup


def _extract_settings_uploads(files_storage) -> dict:
    uploads = {}
    for field_name in ('youtube_cookies_file', 'acfun_cookies_file', 'bilibili_cookies_file'):
        file_storage = files_storage.get(field_name)
        if not file_storage or not getattr(file_storage, 'filename', ''):
            continue
        uploads[field_name] = {
            'filename': file_storage.filename,
            'content': file_storage.read()
        }
    return uploads


def _persist_settings_uploads(form_data: dict, uploads: dict):
    cookies_dir = get_app_subdir('cookies')
    os.makedirs(cookies_dir, exist_ok=True)

    file_specs = {
        'youtube_cookies_file': ('yt_cookies.txt', 'YOUTUBE_COOKIES_PATH', 'cookies/yt_cookies.txt', 'YouTube'),
        'acfun_cookies_file': ('ac_cookies.json', 'ACFUN_COOKIES_PATH', 'cookies/ac_cookies.json', 'AcFun'),
        'bilibili_cookies_file': ('bili_cookies.json', 'BILIBILI_COOKIES_PATH', 'cookies/bili_cookies.json', 'Bilibili'),
    }

    for field_name, payload in uploads.items():
        spec = file_specs.get(field_name)
        if not spec or not payload.get('filename'):
            continue
        save_name, config_key, relative_path, service_name = spec
        target_path = os.path.join(cookies_dir, save_name)
        with open(target_path, 'wb') as target_file:
            target_file.write(payload.get('content') or b'')
        form_data[config_key] = relative_path
        logger.info(f"{service_name} cookies文件已上传并保存到: {target_path}")


def _build_settings_progress_reporter(operation_id: str | None):
    if not operation_id:
        return None

    def _report(payload: dict):
        _update_settings_save_progress(
            operation_id,
            stage=payload.get('stage', 'saving_config'),
            message=payload.get('message', ''),
            detail=payload.get('detail', ''),
            percent=payload.get('percent'),
            downloaded_bytes=payload.get('downloaded_bytes'),
            total_bytes=payload.get('total_bytes'),
            level=payload.get('level', 'info')
        )

    return _report


def _perform_settings_save(form_data: dict, uploads: dict, operation_id: str | None = None) -> dict:
    form_data = dict(form_data or {})
    uploads = uploads or {}
    messages = []
    progress_reporter = _build_settings_progress_reporter(operation_id)

    def report(stage: str, message: str, detail: str = '', percent=None, level: str = 'info', downloaded_bytes=None, total_bytes=None):
        if not progress_reporter:
            return
        progress_reporter({
            'stage': stage,
            'message': message,
            'detail': detail,
            'percent': percent,
            'downloaded_bytes': downloaded_bytes,
            'total_bytes': total_bytes,
            'level': level,
        })

    try:
        report('saving_config', '正在保存配置', '正在校验并写入设置。')
        form_data.pop('save_operation_id', None)

        new_password = form_data.get('new_password')
        confirm_password = form_data.get('confirm_password')
        if new_password:
            if new_password == confirm_password:
                form_data['password'] = new_password
            else:
                _append_settings_message(messages, 'danger', '新密码两次输入不一致，密码未更新。')

        form_data.pop('new_password', None)
        form_data.pop('confirm_password', None)

        checkboxes = [
            'AUTO_MODE_ENABLED', 'TRANSLATE_TITLE', 'TRANSLATE_DESCRIPTION',
            'UPLOAD_APPEND_REPOST_NOTICE', 'DELETE_DOWNLOAD_FILES_AFTER_UPLOAD',
            'GENERATE_TAGS', 'YOUTUBE_UPLOADER_AS_FIRST_TAG', 'RECOMMEND_PARTITION',
            'RECOMMEND_PARTITION_WITH_COVER', 'CONTENT_MODERATION_ENABLED',
            'OPENAI_THINKING_ENABLED', 'SUBTITLE_OPENAI_THINKING_ENABLED', 'SUBTITLE_QC_THINKING_ENABLED',
            'LOG_CLEANUP_ENABLED', 'SUBTITLE_TRANSLATION_ENABLED', 'SUBTITLE_EMBED_IN_VIDEO',
            'SUBTITLE_KEEP_ORIGINAL',
            'YOUTUBE_PROXY_ENABLED', 'YOUTUBE_API_PROXY_ENABLED', 'password_protection_enabled',
            'SPEECH_RECOGNITION_ENABLED',
            'VAD_ENABLED',
            'SUBTITLE_NORMALIZE_PUNCTUATION', 'SUBTITLE_FILTER_FILLER_WORDS',
            'SUBTITLE_TIME_OFFSET_ENABLED', 'SUBTITLE_MIN_CUE_DURATION_ENABLED',
            'SUBTITLE_MERGE_GAP_ENABLED', 'SUBTITLE_MIN_TEXT_LENGTH_ENABLED',
            'SUBTITLE_MAX_LINE_LENGTH_ENABLED', 'SUBTITLE_MAX_LINES_ENABLED',
            'SUBTITLE_QC_ENABLED',
            'FFMPEG_AUTO_DOWNLOAD', 'WHISPER_TRANSLATE',
            'VIDEO_CUSTOM_PARAMS_ENABLED',
            'VOXTRAL_DIARIZE',
            'NOTIFY_ENABLED',
            'NOTIFY_EVENT_TASK_ADDED',
            'NOTIFY_EVENT_TASK_COMPLETED',
            'NOTIFY_EVENT_TASK_FAILED',
            'NOTIFY_EVENT_LOGIN_SUCCESS',
            'NOTIFY_EVENT_LOGIN_LOCKED',
            'NOTIFY_EVENT_QR_LOGIN_SUCCESS',
            'NOTIFY_EVENT_QR_LOGIN_FAILED',
            'NOTIFY_WECOM_ENABLED',
            'NOTIFY_SERVERCHAN_ENABLED',
            'NOTIFY_MESSAGE_PUSHER_ENABLED',
            'COOKIECLOUD_ENABLED',
            'COOKIECLOUD_ALLOW_PLAINTEXT_EXPORT',
        ]
        for checkbox in SPEECH_PIPELINE_CHECKBOXES:
            if checkbox not in checkboxes:
                checkboxes.append(checkbox)
        for checkbox in checkboxes:
            if checkbox not in form_data:
                form_data[checkbox] = 'off'

        numeric_fields = [
            'MAX_CONCURRENT_TASKS', 'MAX_CONCURRENT_UPLOADS', 'LOG_CLEANUP_HOURS',
            'LOG_CLEANUP_INTERVAL', 'SUBTITLE_BATCH_SIZE', 'SUBTITLE_MAX_RETRIES',
            'SUBTITLE_RETRY_DELAY', 'SUBTITLE_MAX_WORKERS', 'YOUTUBE_DOWNLOAD_THREADS',
            'YOUTUBE_DOWNLOAD_MAX_HEIGHT',
            'LOGIN_MAX_FAILED_ATTEMPTS', 'LOGIN_LOCKOUT_MINUTES', 'LOGIN_SESSION_TIMEOUT_MINUTES',
            'VAD_SILERO_MIN_SPEECH_MS',
            'VAD_SILERO_MIN_SILENCE_MS', 'VAD_SILERO_MAX_SPEECH_S',
            'VAD_SILERO_SPEECH_PAD_MS', 'VAD_MAX_SEGMENT_S',
            'SUBTITLE_QC_SAMPLE_MAX_ITEMS', 'SUBTITLE_QC_MAX_CHARS',
            'SUBTITLE_MIN_TEXT_LENGTH',
            'WHISPER_MAX_WORKERS', 'WHISPER_MAX_RETRIES'
        ]
        for field in SPEECH_PIPELINE_INT_FIELDS:
            if field not in numeric_fields:
                numeric_fields.append(field)
        for field in numeric_fields:
            if field in form_data:
                try:
                    original_value = form_data[field]
                    normalized_value = int(original_value)
                    if field == 'LOGIN_SESSION_TIMEOUT_MINUTES':
                        normalized_value = max(1, normalized_value)
                    form_data[field] = str(normalized_value)
                except (ValueError, TypeError) as e:
                    logger.debug(f"整数转换失败 - field: {field}, value: {form_data[field]}, error: {e}")
                    defaults = {
                        'MAX_CONCURRENT_TASKS': 2,
                        'MAX_CONCURRENT_UPLOADS': 1,
                        'LOG_CLEANUP_HOURS': 168,
                        'LOG_CLEANUP_INTERVAL': 12,
                        'SUBTITLE_BATCH_SIZE': 5,
                        'SUBTITLE_MAX_RETRIES': 3,
                        'SUBTITLE_RETRY_DELAY': 5,
                        'SUBTITLE_MAX_WORKERS': 2,
                        'YOUTUBE_DOWNLOAD_THREADS': 4,
                        'YOUTUBE_DOWNLOAD_MAX_HEIGHT': 1080,
                        'LOGIN_MAX_FAILED_ATTEMPTS': 5,
                        'LOGIN_LOCKOUT_MINUTES': 15,
                        'LOGIN_SESSION_TIMEOUT_MINUTES': 30,
                        'VAD_SILERO_MIN_SPEECH_MS': 300,
                        'VAD_SILERO_MIN_SILENCE_MS': 320,
                        'VAD_SILERO_MAX_SPEECH_S': 120,
                        'VAD_SILERO_SPEECH_PAD_MS': 120,
                        'VAD_MAX_SEGMENT_S': 15,
                        'SUBTITLE_QC_SAMPLE_MAX_ITEMS': 80,
                        'SUBTITLE_QC_MAX_CHARS': 9000
                    }
                    defaults.update(SPEECH_PIPELINE_INT_FIELDS)
                    form_data[field] = str(defaults.get(field, 1))
                    logger.debug(f"整数字段使用默认值 - field: {field}, value: {form_data[field]}")

        float_fields = [
            'VAD_SILERO_THRESHOLD',
            'SUBTITLE_TIME_OFFSET_S', 'SUBTITLE_MIN_CUE_DURATION_S', 'SUBTITLE_MERGE_GAP_S',
            'SUBTITLE_QC_THRESHOLD',
            'WHISPER_RETRY_DELAY_S', 'AUDIO_CHUNK_WINDOW_S', 'AUDIO_CHUNK_OVERLAP_S',
            'VAD_MERGE_GAP_S', 'VAD_MIN_SEGMENT_S', 'VAD_MAX_SEGMENT_S_FOR_SPLIT'
        ]
        for field in SPEECH_PIPELINE_FLOAT_FIELDS:
            if field not in float_fields:
                float_fields.append(field)
        for field in float_fields:
            if field in form_data:
                try:
                    original_value = form_data[field]
                    if str(original_value).strip() == '':
                        raise ValueError('empty string')
                    form_data[field] = str(float(original_value))
                except (ValueError, TypeError) as e:
                    logger.debug(f"浮点数转换失败 - field: {field}, value: {form_data[field]}, error: {e}")
                    float_defaults = {
                        'VAD_SILERO_THRESHOLD': 0.55,
                        'SUBTITLE_TIME_OFFSET_S': 0.0,
                        'SUBTITLE_MIN_CUE_DURATION_S': 0.6,
                        'SUBTITLE_MERGE_GAP_S': 0.3,
                        'SUBTITLE_QC_THRESHOLD': 0.35,
                        'WHISPER_RETRY_DELAY_S': 2.0,
                        'AUDIO_CHUNK_WINDOW_S': 15.0,
                        'AUDIO_CHUNK_OVERLAP_S': 0.4,
                        'VAD_MERGE_GAP_S': 0.35,
                        'VAD_MIN_SEGMENT_S': 0.8,
                        'VAD_MAX_SEGMENT_S_FOR_SPLIT': 15.0,
                    }
                    float_defaults.update(SPEECH_PIPELINE_FLOAT_FIELDS)
                    form_data[field] = str(float_defaults.get(field, 0.0))
                    logger.debug(f"浮点字段使用默认值 - field: {field}, value: {form_data[field]}")

        if 'SUBTITLE_FONT_NAME' in form_data:
            form_data['SUBTITLE_FONT_NAME'] = str(form_data['SUBTITLE_FONT_NAME']).strip()

        _persist_settings_uploads(form_data, uploads)
        updated_config = update_config(form_data)

        try:
            from modules.task_manager import get_global_task_processor
            configure_app(app, updated_config)
            get_global_task_processor(updated_config)
            logger.info("配置已更新并同步到任务处理器")
        except Exception as e:
            logger.warning(f"同步任务处理器配置失败: {e}")

        _sync_notification_service(updated_config)
        _append_notification_config_warnings(messages, updated_config)

        try:
            need_ffmpeg = False
            if str(updated_config.get('SPEECH_RECOGNITION_ENABLED', False)).lower() in ['true', '1', 'on']:
                need_ffmpeg = True
            if str(updated_config.get('SUBTITLE_EMBED_IN_VIDEO', False)).lower() in ['true', '1', 'on']:
                need_ffmpeg = True

            if need_ffmpeg:
                from modules.ffmpeg_manager import get_windows_ffmpeg_manual_setup_message
                from modules.youtube_handler import get_ffmpeg_path
                report('checking_ffmpeg', '正在检查 FFmpeg', '已启用依赖 FFmpeg 的功能，正在检查本地环境。')
                ff_path = get_ffmpeg_path(
                    logger=logger,
                    force_refresh=True,
                    progress_callback=progress_reporter
                )
                if ff_path and os.path.exists(ff_path):
                    logger.info(f"FFmpeg 已就绪: {ff_path}")
                    report('completed', 'FFmpeg 已就绪', ff_path, percent=100.0, level='success')
                else:
                    warning_msg = get_windows_ffmpeg_manual_setup_message()
                    logger.warning(warning_msg)
                    _append_settings_message(messages, 'warning', warning_msg)
                    report('warning', 'FFmpeg 未就绪', warning_msg, level='warning')
            else:
                report('completed', '配置已保存', '当前设置不需要额外下载 FFmpeg。', percent=100.0, level='success')
        except Exception as e:
            from modules.ffmpeg_manager import get_windows_ffmpeg_manual_setup_message
            warning_msg = f'检查内置 FFmpeg 状态失败，请查看服务日志。{get_windows_ffmpeg_manual_setup_message()}'
            logger.warning("检查内置 FFmpeg 状态失败: %s", e)
            _append_settings_message(messages, 'warning', warning_msg)
            report('warning', 'FFmpeg 检查失败', warning_msg, level='warning')

        api_key = str(updated_config.get('YOUTUBE_API_KEY') or '').strip()
        api_ready, api_status = youtube_monitor.reload_api_client(updated_config)
        if api_key:
            if api_ready:
                youtube_monitor.start_all_schedules()
                if api_status == 'proxy_ready':
                    logger.info("YouTube监控 API 已重建并同步到监控系统，独立代理已启用")
                else:
                    logger.info("YouTube监控 API 已重建并同步到监控系统，当前为直连模式")
            else:
                youtube_monitor.stop_all_schedules()
                if api_status == 'missing_api_key':
                    warning_msg = 'YouTube API 密钥未配置，请先在设置页完成接入。'
                else:
                    warning_msg = 'YouTube监控 API 初始化失败，请检查 API 密钥、代理配置与网络连通性。'
                logger.warning(warning_msg)
                _append_settings_message(messages, 'warning', warning_msg)
        else:
            youtube_monitor.stop_all_schedules()
            logger.info("YouTube API密钥未配置，已跳过监控系统初始化")

        # Issue 101: 非阻断提示——CookieCloud 已启用时，逐项检查服务地址/UUID/密码是否缺失
        if str(updated_config.get('COOKIECLOUD_ENABLED', False)).lower() in ('true', '1', 'on'):
            _cookiecloud_missing = []
            if not str(updated_config.get('COOKIECLOUD_SERVER_URL', '') or '').strip():
                _cookiecloud_missing.append('服务地址')
            if not str(updated_config.get('COOKIECLOUD_UUID', '') or '').strip():
                _cookiecloud_missing.append('UUID')
            if not str(updated_config.get('COOKIECLOUD_PASSWORD', '') or '').strip():
                _cookiecloud_missing.append('密码')
            if _cookiecloud_missing:
                _append_settings_message(
                    messages, 'warning',
                    f'CookieCloud 已启用，但以下必填项为空：{"、".join(_cookiecloud_missing)}。'
                    'CookieCloud 需要服务地址、UUID、密码三者均非空才能正常同步，'
                    '请补全后保存，或暂时关闭 CookieCloud。'
                )

        _append_settings_message(messages, 'success', '配置已成功保存')
        final_level = 'warning' if any(msg['category'] in ('warning', 'danger') for msg in messages) else 'success'
        final_stage = 'warning' if final_level == 'warning' else 'completed'
        final_message = '配置已保存，但有提醒需要处理。' if final_level == 'warning' else '配置已成功保存'
        final_detail = next((msg['text'] for msg in messages if msg['category'] in ('warning', 'danger')), '设置已生效。')
        return {
            'success': True,
            'messages': messages,
            'updated_config': updated_config,
            'final_stage': final_stage,
            'final_message': final_message,
            'final_detail': final_detail,
            'final_level': final_level,
        }
    except Exception as e:
        logger.exception("保存设置失败: %s", e)
        public_message = '保存设置失败，请查看服务日志。'
        _append_settings_message(messages, 'danger', public_message)
        return {
            'success': False,
            'messages': messages,
            'updated_config': None,
            'final_stage': 'failed',
            'final_message': '保存设置失败',
            'final_detail': public_message,
            'final_level': 'error',
        }


def _finalize_settings_save_operation(operation_id: str, result: dict):
    current_state = _get_settings_save_progress(operation_id) or _new_settings_save_state(operation_id)
    percent = current_state.get('percent')
    if result.get('success') and percent is None:
        percent = 100.0

    _update_settings_save_progress(
        operation_id,
        stage=result.get('final_stage', 'completed'),
        message=result.get('final_message', ''),
        detail=result.get('final_detail', ''),
        percent=percent,
        done=True,
        level=result.get('final_level', 'success'),
        success=result.get('success'),
        messages=result.get('messages', []),
    )


def _run_settings_save_operation(operation_id: str, form_data: dict, uploads: dict):
    result = _perform_settings_save(form_data, uploads, operation_id=operation_id)
    _finalize_settings_save_operation(operation_id, result)


TG_BOT_API_TOKEN_PREFIX = 'y2a_tgbot_v1_'
TG_BOT_API_TOKEN_HASH_PREFIX = 'pbkdf2_sha256:'
TG_BOT_API_TOKEN_HASH_ITERATIONS = 260000
_TG_BOT_API_TOKEN_RANDOM_RE = re.compile(r'^[A-Za-z0-9_-]{32,}$')
_TG_BOT_UPLOAD_RATE_LIMIT_WINDOW_SECONDS = 60
_TG_BOT_UPLOAD_RATE_LIMIT_MAX_REQUESTS = 60
_TG_BOT_UPLOAD_RATE_LIMIT_MAX_BUCKETS = 10000
_TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS = {}
_TG_BOT_UPLOAD_RATE_LIMIT_LOCK = threading.Lock()


def _generate_tgbot_api_token() -> str:
    return f'{TG_BOT_API_TOKEN_PREFIX}{secrets.token_urlsafe(32)}'


def _is_valid_tgbot_api_token_format(token: str | None) -> bool:
    token = str(token or '').strip()
    if not token.startswith(TG_BOT_API_TOKEN_PREFIX):
        return False
    random_part = token[len(TG_BOT_API_TOKEN_PREFIX):]
    return bool(_TG_BOT_API_TOKEN_RANDOM_RE.fullmatch(random_part))


def _hash_tgbot_api_token(token: str) -> str:
    salt = secrets.token_urlsafe(16)
    digest = hashlib.pbkdf2_hmac(
        'sha256',
        token.encode('utf-8'),
        salt.encode('utf-8'),
        TG_BOT_API_TOKEN_HASH_ITERATIONS,
    ).hex()
    return f'{TG_BOT_API_TOKEN_HASH_PREFIX}{TG_BOT_API_TOKEN_HASH_ITERATIONS}${salt}${digest}'


def _verify_tgbot_api_token_hash(token: str, stored_hash: str) -> bool:
    if not stored_hash.startswith(TG_BOT_API_TOKEN_HASH_PREFIX):
        return False
    payload = stored_hash[len(TG_BOT_API_TOKEN_HASH_PREFIX):]
    try:
        iterations_text, salt, expected_digest = payload.split('$', 2)
        iterations = int(iterations_text)
    except (TypeError, ValueError):
        return False
    if iterations < 1 or not salt or not expected_digest:
        return False
    actual_digest = hashlib.pbkdf2_hmac(
        'sha256',
        token.encode('utf-8'),
        salt.encode('utf-8'),
        iterations,
    ).hex()
    return secrets.compare_digest(expected_digest, actual_digest)


def _extract_bearer_token() -> str:
    auth_header = request.headers.get('Authorization') or ''
    scheme, _, value = auth_header.partition(' ')
    if scheme.lower() != 'bearer' or not value.strip():
        return ''
    return value.strip()


def _verify_tgbot_api_token(token: str, config: dict | None = None) -> bool:
    if not _is_valid_tgbot_api_token_format(token):
        return False
    effective_config = config if isinstance(config, dict) else load_config()
    stored_hash = str(effective_config.get('TG_BOT_API_TOKEN_HASH') or '').strip()
    return _verify_tgbot_api_token_hash(token, stored_hash)


def _tgbot_api_token_state(config: dict | None = None) -> dict:
    effective_config = config if isinstance(config, dict) else load_config()
    token_hash = str(effective_config.get('TG_BOT_API_TOKEN_HASH') or '').strip()
    return {
        'configured': bool(token_hash),
        'created_at': str(effective_config.get('TG_BOT_API_TOKEN_CREATED_AT') or ''),
        'last4': str(effective_config.get('TG_BOT_API_TOKEN_LAST4') or ''),
    }


def _ensure_tgbot_token_csrf_token() -> str:
    token = session.get('tgbot_token_csrf')
    if not isinstance(token, str) or not token:
        token = secrets.token_urlsafe(32)
        session['tgbot_token_csrf'] = token
    return token


def _validate_tgbot_token_csrf(submitted_token: str | None) -> bool:
    expected = session.get('tgbot_token_csrf')
    if not isinstance(expected, str) or not expected:
        return False
    if not secrets.compare_digest(expected, str(submitted_token or '')):
        return False
    session.pop('tgbot_token_csrf', None)
    return True


def _is_tgbot_upload_rate_limited() -> bool:
    client_id = request.remote_addr or 'unknown'
    now = time.time()
    window_start = now - _TG_BOT_UPLOAD_RATE_LIMIT_WINDOW_SECONDS
    with _TG_BOT_UPLOAD_RATE_LIMIT_LOCK:
        for key in list(_TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS.keys()):
            _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS[key] = [
                timestamp for timestamp in _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS[key]
                if timestamp >= window_start
            ]
            if not _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS[key]:
                del _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS[key]

        if len(_TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS) > _TG_BOT_UPLOAD_RATE_LIMIT_MAX_BUCKETS:
            newest_buckets = sorted(
                _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS.items(),
                key=lambda item: item[1][-1] if item[1] else 0,
                reverse=True,
            )[:_TG_BOT_UPLOAD_RATE_LIMIT_MAX_BUCKETS]
            _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS.clear()
            _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS.update(newest_buckets)

        bucket = _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS.setdefault(client_id, [])
        if len(bucket) >= _TG_BOT_UPLOAD_RATE_LIMIT_MAX_REQUESTS:
            return True
        bucket.append(now)
        if len(_TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS) > _TG_BOT_UPLOAD_RATE_LIMIT_MAX_BUCKETS:
            newest_buckets = sorted(
                _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS.items(),
                key=lambda item: item[1][-1] if item[1] else 0,
                reverse=True,
            )[:_TG_BOT_UPLOAD_RATE_LIMIT_MAX_BUCKETS]
            _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS.clear()
            _TG_BOT_UPLOAD_RATE_LIMIT_BUCKETS.update(newest_buckets)
        return False


def tgbot_upload_token_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if request.method == 'OPTIONS':
            return f(*args, **kwargs)

        if _is_tgbot_upload_rate_limited():
            return jsonify({'success': False, 'message': '请求过于频繁，请稍后再试。'}), 429

        config = load_config()
        if not config.get('TG_BOT_API_TOKEN_HASH'):
            return jsonify({
                'success': False,
                'message': 'Telegram Bot API Token 未配置，请先在设置页生成专用 Token。'
            }), 403

        token = _extract_bearer_token()
        if not _verify_tgbot_api_token(token, config):
            return jsonify({'success': False, 'message': 'Telegram Bot API Token 无效或缺失。'}), 401

        return f(*args, **kwargs)
    return decorated_function


# 登录验证装饰器
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        config = load_config()
        if config.get('password_protection_enabled'):
            if 'logged_in' not in session:
                # API 请求（浏览器扩展 Cookie 同步等）返回 401 JSON，其余重定向到新版控制台登录页
                if request.path.startswith('/api/'):
                    return jsonify({'error': '请先登录', 'code': 'unauthorized'}), 401
                return redirect('/ui/login')
        return f(*args, **kwargs)
    return decorated_function

# 配置CORS，允许来自YouTube的跨域请求
CORS(app, resources={
    r"/tasks/add_via_extension": {
        "origins": [r"https?://www\.youtube\.com", r"https?://youtube\.com"],
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# 确保日志目录存在
log_dir = get_app_subdir('logs')
os.makedirs(log_dir, exist_ok=True)

# 配置日志
log_file = os.path.join(log_dir, 'app.log')
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# 文件处理器
file_handler = RotatingFileHandler(log_file, maxBytes=10485760, backupCount=10, encoding='utf-8')
file_handler.setFormatter(log_formatter)
file_handler.setLevel(logging.WARNING)

# 控制台处理器
console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.WARNING)
# 确保Windows控制台编码正确
if os.name == 'nt':
    import sys
    import codecs
    # 检查Python版本和reconfigure方法可用性
    python_version = sys.version_info
    
    # 强制设置stdout和stderr为UTF-8编码
    if hasattr(sys.stdout, 'reconfigure'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')  # type: ignore
        except Exception:
            pass
        
    if hasattr(sys.stderr, 'reconfigure'):
        try:
            sys.stderr.reconfigure(encoding='utf-8')  # type: ignore
        except Exception:
            pass
    
    # 设置环境变量
    os.environ["PYTHONIOENCODING"] = "utf-8"
    # 为控制台处理器设置编码
    try:
        console_handler.setStream(codecs.getwriter('utf-8')(sys.stdout.buffer))  # type: ignore
    except Exception:
        pass

# 配置根日志记录器
root_logger = logging.getLogger()
root_logger.setLevel(logging.WARNING)
root_logger.addHandler(file_handler)
root_logger.addHandler(console_handler)

# 强制设置所有日志记录器的默认编码为UTF-8
try:
    logging.getLogger().handlers[0].encoding = 'utf-8'  # type: ignore
except Exception:
    pass

try:
    if len(logging.getLogger().handlers) > 1:
        logging.getLogger().handlers[1].encoding = 'utf-8'  # type: ignore
except Exception:
    pass

# 配置应用日志记录器
logger = logging.getLogger('Y2A-Auto')
logger.setLevel(logging.WARNING)

def init_id_mapping():
    """
    初始化AcFun分区ID映射.
    id_mapping.json 文件现在应该由 acfunid/ 目录直接提供，并包含在Docker镜像中。
    此函数仅记录一条信息，不再执行文件生成或检查逻辑。
    """
    logger.info("AcFun分区ID映射 (id_mapping.json) 应由 'acfunid/' 目录提供。")

# 模板辅助函数


def _get_bilibili_zone_data():
    from modules.bilibili_zones import get_zone_list_sub
    return get_zone_list_sub()


def _load_acfun_partition_mapping():
    id_mapping_path = os.path.join(get_app_subdir('acfunid'), 'id_mapping.json')
    try:
        with open(id_mapping_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"读取AcFun分区映射失败: {e}")
        return []


def _build_bilibili_partition_mapping():
    id_mapping = []
    zone_data = _get_bilibili_zone_data()
    for parent in zone_data:
        if not isinstance(parent, dict):
            continue
        parent_tid = parent.get('tid')
        parent_name = parent.get('name')
        if parent_tid in (None, 0, '0') or not parent_name:
            continue
        id_mapping.append({
            'category': parent_name,
            'partitions': [{
                'id': str(parent_tid),
                'name': parent_name,
                'sub_partitions': [
                    {
                        'id': str(sub.get('tid')),
                        'name': sub.get('name'),
                    }
                    for sub in (parent.get('sub') or [])
                    if isinstance(sub, dict) and sub.get('tid') not in (None, 0, '0') and sub.get('name')
                ]
            }]
        })
    return id_mapping


@app.route('/')
def index():
    """根路径跳转到新版 SPA 控制台。旧版页面路由保留，便于过渡。"""
    return redirect('/ui/')

@app.route('/ui', defaults={'path': ''})
@app.route('/ui/', defaults={'path': ''})
@app.route('/ui/<path:path>')
def spa_console(path):
    """托管 Vue 3 SPA 构建产物，非静态资源回退到 index.html（History 路由）。"""
    if not os.path.isdir(FRONTEND_DIST_DIR):
        return (
            '前端尚未构建：请在 frontend/ 目录执行 npm install && npm run build 后重试。',
            503,
        )
    if path:
        full_path = safe_join(FRONTEND_DIST_DIR, path)
        if full_path and os.path.isfile(full_path):
            return send_from_directory(FRONTEND_DIST_DIR, path)
    response = send_from_directory(FRONTEND_DIST_DIR, 'index.html')
    response.headers['Cache-Control'] = 'no-cache'
    return response


def _missing_upload_partition_labels(task, config):
    upload_target = str(task.get('upload_target') or 'acfun').lower()
    recommend_enabled = str(config.get('RECOMMEND_PARTITION', False)).strip().lower() in ('true', '1', 'on', 'yes')
    missing = []

    if upload_target in ('acfun', 'both'):
        fixed_acfun_pid = str(config.get('FIXED_PARTITION_ID', '') or '').strip()
        acfun_partition = str(
            task.get('selected_partition_id_acfun')
            or task.get('recommended_partition_id_acfun')
            or task.get('selected_partition_id')
            or task.get('recommended_partition_id')
            or ''
        ).strip()
        if not fixed_acfun_pid and not acfun_partition and not recommend_enabled:
            missing.append('AcFun 分区')

    if upload_target in ('bilibili', 'both'):
        fixed_bili_pid = str(config.get('FIXED_PARTITION_ID_BILIBILI', '') or '').strip()
        bili_partition = str(
            task.get('selected_partition_id_bilibili')
            or task.get('recommended_partition_id_bilibili')
            or task.get('selected_partition_id')
            or task.get('recommended_partition_id')
            or ''
        ).strip()
        if not fixed_bili_pid and not bili_partition and not recommend_enabled:
            missing.append('bilibili 分区')

    return missing


def _start_background_force_upload(task_id, config, platform_name):
    logger.info(f"开始后台强制上传任务 {task_id} 到{platform_name}")

    def background_force_upload():
        try:
            success = force_upload_task(task_id, config)
            if success:
                logger.info(f"任务 {task_id} 后台强制上传成功")
            else:
                logger.error(f"任务 {task_id} 后台强制上传失败")
        except Exception as e:
            logger.error(f"任务 {task_id} 后台强制上传出错: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())

    upload_thread = threading.Thread(target=background_force_upload, daemon=True)
    upload_thread.start()
    

@app.route('/tasks/add_via_extension', methods=['POST', 'OPTIONS'])
@tgbot_upload_token_required
def add_task_via_extension():
    """
    通过浏览器扩展或API添加任务 (JSON格式)
    支持Telegram Bot、浏览器扩展等外部服务调用
    """
    # 处理CORS预检请求
    if request.method == 'OPTIONS':
        return '', 200
    
    try:
        # 优先从JSON获取，兼容form表单
        if request.is_json:
            data = request.get_json()
            youtube_url = data.get('youtube_url') if data else None
            upload_target = data.get('upload_target') if data else None
        else:
            youtube_url = request.form.get('youtube_url')
            upload_target = request.form.get('upload_target')

        if not youtube_url:
            return jsonify({'success': False, 'message': 'YouTube URL不能为空'}), 400

        config = load_config()
        if not upload_target:
            upload_target = config.get('UPLOAD_TARGET_DEFAULT', 'acfun')
        else:
            upload_target = str(upload_target).strip().lower()

        if upload_target not in ('acfun', 'bilibili', 'both'):
            return jsonify({'success': False, 'message': '无效的投稿平台参数'}), 400
        
        # 判断是否为播放列表URL
        if 'youtube.com/playlist' in youtube_url or 'youtu.be/playlist' in youtube_url:
            # 提取所有视频URL
            cookies_path = config.get('YOUTUBE_COOKIES_PATH')
            video_urls = extract_video_urls_from_playlist(youtube_url, cookies_path)
            if not video_urls:
                return jsonify({'success': False, 'message': '未能提取到播放列表中的视频'}), 400
            
            added_count = 0
            task_ids = []
            for url in video_urls:
                task_id = add_task(url, upload_target=upload_target)
                if task_id:
                    added_count += 1
                    task_ids.append(task_id)
                    # 自动模式下启动任务
                    if config.get('AUTO_MODE_ENABLED', False):
                        start_task(task_id, config)
            
            return jsonify({
                'success': True,
                'message': f'已批量添加 {added_count} 个视频任务（来自播放列表）',
                'task_ids': task_ids,
                'count': added_count
            }), 200
        else:
            # 单个视频
            task_id = add_task(youtube_url, upload_target=upload_target)
            if task_id:
                if config.get('AUTO_MODE_ENABLED', False):
                    logger.info(f"自动模式已启用，立即开始处理任务 {task_id}")
                    start_task(task_id, config)
                    return jsonify({
                        'success': True,
                        'message': f'任务已添加并开始处理',
                        'task_id': task_id
                    }), 200
                else:
                    return jsonify({
                        'success': True,
                        'message': '任务已添加',
                        'task_id': task_id
                    }), 200
            else:
                return jsonify({'success': False, 'message': '添加任务失败'}), 500
                
    except Exception as e:
        logger.error(f"通过扩展添加任务失败: {str(e)}")
        return jsonify({'success': False, 'message': '服务器内部错误，请稍后重试'}), 500


def check_docker_volumes():
    """检查Docker挂载卷状态"""
    volumes = {}
    app_root = os.path.dirname(os.path.abspath(__file__))
    
    volume_paths = [
        ('config', 'config'),
        ('db', 'db'),
        ('downloads', 'downloads'),
        ('logs', 'logs'),
        ('cookies', 'cookies'),
        ('temp', 'temp')
    ]
    
    for name, path in volume_paths:
        full_path = os.path.join(app_root, path)
        volumes[name] = {
            'path': full_path,
            'exists': os.path.exists(full_path),
            'is_mount': os.path.ismount(full_path),
            'writable': os.access(full_path, os.W_OK) if os.path.exists(full_path) else False,
            'size_mb': get_directory_size(full_path) if os.path.exists(full_path) else 0
        }
    
    return volumes

def get_directory_size(path):
    """获取目录大小(MB)"""
    try:
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                if os.path.exists(fp):
                    total_size += os.path.getsize(fp)
        return round(total_size / 1024 / 1024, 2)
    except Exception as e:
        logger.warning(f"获取目录大小失败 {path}: {e}")
        return 0

def _public_health_check_error_message(component: str = '检查项') -> str:
    return f'{component}检查失败，请查看服务日志。'

def get_database_info():
    """获取数据库文件信息"""
    try:
        from modules.task_manager import get_db_path
        db_path = get_db_path()
        
        if os.path.exists(db_path):
            stat_info = os.stat(db_path)
            return {
                'path': db_path,
                'size': stat_info.st_size,
                'writable': os.access(db_path, os.W_OK),
                'last_modified': stat_info.st_mtime
            }
        else:
            return {
                'path': db_path,
                'size': 0,
                'writable': False,
                'last_modified': None
            }
    except Exception as e:
        logger.warning("获取数据库文件信息失败: %s", e)
        return {
            'path': 'unknown',
            'size': 0,
            'writable': False,
            'error': _public_health_check_error_message('数据库')
        }

def get_database_debug_info():
    """获取数据库调试信息"""
    try:
        from modules.task_manager import get_db_path
        db_path = get_db_path()
        
        debug_info = {
            'db_path': db_path,
            'db_exists': os.path.exists(db_path),
            'db_dir': os.path.dirname(db_path),
            'db_dir_exists': os.path.exists(os.path.dirname(db_path)),
            'db_dir_writable': os.access(os.path.dirname(db_path), os.W_OK) if os.path.exists(os.path.dirname(db_path)) else False,
            'current_user': os.environ.get('USER', 'unknown'),
            'current_uid': os.getuid() if hasattr(os, 'getuid') else 'unknown',  # type: ignore
            'current_gid': os.getgid() if hasattr(os, 'getgid') else 'unknown'   # type: ignore
        }
        
        if os.path.exists(db_path):
            stat_info = os.stat(db_path)
            debug_info.update({
                'db_size': stat_info.st_size,
                'db_mode': oct(stat_info.st_mode)[-3:],
                'db_uid': stat_info.st_uid,
                'db_gid': stat_info.st_gid
            })
        
        return debug_info
    except Exception as e:
        logger.warning("获取数据库调试信息失败: %s", e)
        return {'error': _public_health_check_error_message('数据库')}

def get_file_info(file_path):
    """获取文件详细信息"""
    try:
        info = {
            'exists': os.path.exists(file_path),
            'size': 0,
            'readable': False,
            'last_modified': None
        }
        
        if info['exists']:
            stat_info = os.stat(file_path)
            info.update({
                'size': stat_info.st_size,
                'readable': os.access(file_path, os.R_OK),
                'last_modified': stat_info.st_mtime
            })
        
        return info
    except Exception as e:
        logger.warning("获取文件信息失败: %s", e)
        return {
            'exists': False,
            'size': 0,
            'readable': False,
            'last_modified': None,
            'error': _public_health_check_error_message('文件')
        }

def get_path_debug_info(file_path):
    """获取路径调试信息"""
    try:
        debug_info = {
            'path': file_path,
            'dirname': os.path.dirname(file_path),
            'basename': os.path.basename(file_path),
            'dirname_exists': os.path.exists(os.path.dirname(file_path)),
            'dirname_readable': os.access(os.path.dirname(file_path), os.R_OK) if os.path.exists(os.path.dirname(file_path)) else False,
            'dirname_writable': os.access(os.path.dirname(file_path), os.W_OK) if os.path.exists(os.path.dirname(file_path)) else False
        }
        
        # 列出目录内容
        if debug_info['dirname_exists'] and debug_info['dirname_readable']:
            try:
                debug_info['directory_contents'] = os.listdir(os.path.dirname(file_path))
            except:
                debug_info['directory_contents'] = 'permission_denied'
        
        return debug_info
    except Exception as e:
        logger.warning("获取路径调试信息失败: %s", e)
        return {'error': _public_health_check_error_message('路径')}

@app.route('/system_health')
def system_health():
    """系统健康检查 - 增强Docker环境兼容性"""
    from modules.task_manager import get_db_connection, validate_cookies, resolve_cookie_file_path
    import sqlite3
    import os
    import platform
    import sys
    
    # 检测运行环境
    is_docker = os.path.exists('/.dockerenv') or os.environ.get('CONTAINER') == 'docker'
    
    health_status = {
        'environment': {
            'platform': platform.system(),
            'python_version': sys.version.split()[0],
            'is_docker': is_docker,
            'user': os.environ.get('USER', 'unknown'),
            'working_directory': os.getcwd()
        },
        'database': {'status': 'unknown', 'message': ''},
        'youtube_cookies': {'status': 'unknown', 'message': ''},
        'acfun_cookies': {'status': 'unknown', 'message': ''},
        'bilibili_cookies': {'status': 'unknown', 'message': ''},
        'stuck_tasks': {'count': 0, 'tasks': []},
        'recent_errors': [],
        'runtime_tools': {
            'ffmpeg': {'status': 'unknown', 'path': None},
            'ffprobe': {'status': 'unknown', 'path': None},
            'vad': {'status': 'unknown', 'message': ''},
            'asr': {'status': 'unknown', 'message': ''},
            'tts': {'status': 'unknown', 'message': ''},
            'disk': {'status': 'unknown', 'free_gb': None},
        },
        'docker_volumes': {}
    }
    
    # 运行时依赖体检（ffmpeg/ffprobe/ASR/VAD/磁盘）
    try:
        from modules.ffmpeg_manager import get_ffmpeg_path, get_ffprobe_path, is_ffmpeg_usable
        ffmpeg_path = get_ffmpeg_path()
        health_status['runtime_tools']['ffmpeg'] = {
            'status': 'ok' if (ffmpeg_path and is_ffmpeg_usable(ffmpeg_path)) else 'missing',
            'path': ffmpeg_path or None,
        }
        ffprobe_path = get_ffprobe_path(ffmpeg_path=ffmpeg_path)
        health_status['runtime_tools']['ffprobe'] = {
            'status': 'ok' if ffprobe_path else 'missing',
            'path': ffprobe_path or None,
        }
    except Exception:
        health_status['runtime_tools']['ffmpeg'] = {'status': 'error', 'path': None}
        health_status['runtime_tools']['ffprobe'] = {'status': 'error', 'path': None}

    try:
        import importlib.util
        torch_ok = importlib.util.find_spec('torch') is not None
        silero_ok = importlib.util.find_spec('silero_vad') is not None
        if torch_ok and silero_ok:
            health_status['runtime_tools']['vad'] = {'status': 'ok', 'message': 'silero-vad 可用'}
        elif torch_ok:
            health_status['runtime_tools']['vad'] = {'status': 'missing', 'message': 'silero-vad 未安装（torch 已装）'}
        else:
            health_status['runtime_tools']['vad'] = {'status': 'missing', 'message': 'silero-vad/torch 未安装，VAD 将走整段兜底'}
    except Exception:
        health_status['runtime_tools']['vad'] = {'status': 'error', 'message': ''}

    try:
        _health_config = load_config()
        asr_key = bool(str(_health_config.get('WHISPER_API_KEY') or '').strip())
        asr_base = str(_health_config.get('WHISPER_BASE_URL') or '').strip()
        asr_model = str(_health_config.get('WHISPER_MODEL_NAME') or '').strip()
        if asr_key and asr_base:
            health_status['runtime_tools']['asr'] = {
                'status': 'ok' if asr_model else 'warn',
                'message': f'{asr_model or "默认"} @ {asr_base}',
            }
        elif asr_base:
            health_status['runtime_tools']['asr'] = {'status': 'warn', 'message': '已配置端点但缺少 API Key'}
        else:
            health_status['runtime_tools']['asr'] = {'status': 'disabled', 'message': '未配置语音识别'}

        tts_enabled = bool(_health_config.get('TTS_DUB_ENABLED', False))
        tts_key = bool(str(_health_config.get('TTS_DUB_API_KEY') or '').strip())
        tts_model = str(_health_config.get('TTS_DUB_MODEL') or '').strip()
        if tts_enabled and tts_key:
            health_status['runtime_tools']['tts'] = {
                'status': 'ok',
                'message': f'{tts_model} @ {str(_health_config.get("TTS_DUB_BASE_URL") or "")[:40]}',
            }
        elif tts_enabled and not tts_key:
            health_status['runtime_tools']['tts'] = {'status': 'warn', 'message': '已启用配音但缺少 API Key'}
        else:
            health_status['runtime_tools']['tts'] = {'status': 'disabled', 'message': '未启用配音'}
    except Exception:
        health_status['runtime_tools']['asr'] = {'status': 'error', 'message': ''}
        health_status['runtime_tools']['tts'] = {'status': 'error', 'message': ''}

    try:
        import shutil
        disk_usage = shutil.disk_usage(os.path.abspath(os.curdir))
        free_gb = round(disk_usage.free / (1024 ** 3), 1)
        health_status['runtime_tools']['disk'] = {
            'status': 'ok' if free_gb >= 5 else 'warn',
            'free_gb': free_gb,
        }
    except Exception:
        health_status['runtime_tools']['disk'] = {'status': 'error', 'free_gb': None}
    
    # Docker环境特殊检查
    if is_docker:
        health_status['docker_volumes'] = check_docker_volumes()
    
    # 检查数据库
    try:
        logger.info("开始数据库健康检查...")
        conn = get_db_connection()
        
        # 测试基本连接
        cursor = conn.execute('SELECT COUNT(*) FROM tasks')
        task_count = cursor.fetchone()[0]
        
        # 检查数据库文件权限和位置
        db_info = get_database_info()
        
        health_status['database'] = {
            'status': 'ok',
            'message': f'数据库正常，共有 {task_count} 个任务',
            'location': db_info['path'],
            'size_mb': round(db_info['size'] / 1024 / 1024, 2),
            'writable': db_info['writable']
        }
        
        # 检查卡住的任务
        stuck_cursor = conn.execute('''
            SELECT id, status, created_at, updated_at, error_message
            FROM tasks 
            WHERE status IN ('processing', 'downloading', 'uploading', 'fetching_info', 'translating')
            AND datetime(updated_at) < datetime('now', '-30 minutes')
        ''')
        stuck_tasks = stuck_cursor.fetchall()
        health_status['stuck_tasks'] = {
            'count': len(stuck_tasks),
            'tasks': [{'id': t[0][:8] + '...', 'status': t[1], 'updated': t[3]} for t in stuck_tasks]
        }
        
        # 检查最近的错误
        error_cursor = conn.execute('''
            SELECT id, error_message, updated_at
            FROM tasks 
            WHERE status = 'failed' AND error_message IS NOT NULL
            ORDER BY updated_at DESC
            LIMIT 5
        ''')
        error_tasks = error_cursor.fetchall()
        health_status['recent_errors'] = [
            {'id': t[0][:8] + '...', 'error': t[1][:100] + '...' if len(t[1]) > 100 else t[1], 'time': t[2]}
            for t in error_tasks
        ]
        
        conn.close()
        logger.info("数据库健康检查完成")
    except Exception:
        logger.exception("数据库健康检查失败")
        health_status['database'] = {
            'status': 'error',
            'message': _public_health_check_error_message('数据库'),
            'details': get_database_debug_info()
        }
    

    # 检查cookies - 使用更健壮的路径处理
    try:
        logger.info("开始cookies健康检查...")
        config = load_config()
        
        # YouTube cookies
        yt_cookies_path = config.get('YOUTUBE_COOKIES_PATH', 'cookies/yt_cookies.txt')
        if yt_cookies_path:
            # 如果是相对路径，转换为绝对路径
            yt_cookies_path = resolve_cookie_file_path(
                path_value=yt_cookies_path,
                default_relative_path='cookies/yt_cookies.txt',
                service_name='YouTube',
                logger_obj=logger,
                allow_json_txt_fallback=False
            )
            
            try:
                logger.debug(f"检查YouTube cookies文件: {yt_cookies_path}")
                is_valid, message = validate_cookies(yt_cookies_path, "YouTube")
                
                # 获取文件详细信息
                file_info = get_file_info(yt_cookies_path)
                
                health_status['youtube_cookies'] = {
                    'status': 'ok' if is_valid else 'error',
                    'message': message,
                    'path': yt_cookies_path,
                    'exists': file_info['exists'],
                    'size': file_info['size'],
                    'readable': file_info['readable'],
                    'last_modified': file_info['last_modified']
                }
            except Exception:
                logger.exception("YouTube cookies检查异常")
                health_status['youtube_cookies'] = {
                    'status': 'error',
                    'message': _public_health_check_error_message('YouTube Cookies'),
                    'path': yt_cookies_path,
                    'debug_info': get_path_debug_info(yt_cookies_path)
                }
        else:
            health_status['youtube_cookies'] = {
                'status': 'warning',
                'message': '未配置YouTube cookies路径'
            }
        
        # AcFun cookies
        ac_cookies_path = resolve_cookie_file_path(
            path_value=config.get('ACFUN_COOKIES_PATH', 'cookies/ac_cookies.json'),
            default_relative_path='cookies/ac_cookies.json',
            service_name='AcFun',
            logger_obj=logger,
            allow_json_txt_fallback=True
        )
        if ac_cookies_path:
            try:
                logger.debug(f"检查AcFun cookies文件: {ac_cookies_path}")
                is_valid, message = validate_cookies(ac_cookies_path, "AcFun")
                
                # 获取文件详细信息
                file_info = get_file_info(ac_cookies_path)
                
                health_status['acfun_cookies'] = {
                    'status': 'ok' if is_valid else 'error',
                    'message': message,
                    'path': ac_cookies_path,
                    'exists': file_info['exists'],
                    'size': file_info['size'],
                    'readable': file_info['readable'],
                    'last_modified': file_info['last_modified']
                }
            except Exception:
                logger.exception("AcFun cookies检查异常")
                health_status['acfun_cookies'] = {
                    'status': 'error',
                    'message': _public_health_check_error_message('AcFun Cookies'),
                    'path': ac_cookies_path,
                    'debug_info': get_path_debug_info(ac_cookies_path)
                }
        else:
            health_status['acfun_cookies'] = {
                'status': 'warning',
                'message': '未配置AcFun cookies路径'
            }

        # Bilibili cookies
        bili_cookies_path = config.get('BILIBILI_COOKIES_PATH', 'cookies/bili_cookies.json')
        if bili_cookies_path:
            bili_cookies_path = resolve_cookie_file_path(
                path_value=bili_cookies_path,
                default_relative_path='cookies/bili_cookies.json',
                service_name='Bilibili',
                logger_obj=logger,
                allow_json_txt_fallback=False
            )

            try:
                logger.debug(f"检查Bilibili cookies文件: {bili_cookies_path}")
                is_valid, message = validate_cookies(bili_cookies_path, "Bilibili")
                file_info = get_file_info(bili_cookies_path)
                health_status['bilibili_cookies'] = {
                    'status': 'ok' if is_valid else 'error',
                    'message': message,
                    'path': bili_cookies_path,
                    'exists': file_info['exists'],
                    'size': file_info['size'],
                    'readable': file_info['readable'],
                    'last_modified': file_info['last_modified']
                }
            except Exception:
                logger.exception("Bilibili cookies检查异常")
                health_status['bilibili_cookies'] = {
                    'status': 'error',
                    'message': _public_health_check_error_message('Bilibili Cookies'),
                    'path': bili_cookies_path,
                    'debug_info': get_path_debug_info(bili_cookies_path)
                }
        else:
            health_status['bilibili_cookies'] = {
                'status': 'warning',
                'message': '未配置Bilibili cookies路径'
            }
        
        logger.info("cookies健康检查完成")
            
    except Exception:
        logger.exception("检查cookies时发生错误")
        health_status['youtube_cookies'] = {
            'status': 'error',
            'message': _public_health_check_error_message('YouTube Cookies'),
            'debug_info': _public_health_check_error_message('Cookies')
        }
        health_status['acfun_cookies'] = {
            'status': 'error',
            'message': _public_health_check_error_message('AcFun Cookies'),
            'debug_info': _public_health_check_error_message('Cookies')
        }
        health_status['bilibili_cookies'] = {
            'status': 'error',
            'message': _public_health_check_error_message('Bilibili Cookies'),
            'debug_info': _public_health_check_error_message('Cookies')
        }
    
    return jsonify(health_status)


def _human_readable_size(num_bytes: float) -> str:
    # Simple helper for human readable file sizes
    if num_bytes is None:
        return '0B'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f}{unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f}PB"


def cleanup_logs(hours: int):
    """删除logs目录下指定小时之前的日志文件（不包括当前运行日志）"""
    try:
        logs_dir = get_app_subdir('logs')
        if not os.path.exists(logs_dir):
            return {'success': True, 'files_removed': 0, 'bytes_freed': 0, 'bytes_freed_readable': '0B'}

        cutoff = time.time() - float(hours) * 3600
        files_removed = 0
        bytes_freed = 0

        for filename in os.listdir(logs_dir):
            path = os.path.join(logs_dir, filename)
            # skip current top-level app and manager logs when present
            if filename in ('app.log', 'task_manager.log'):
                continue
            try:
                stat = os.stat(path)
                if stat.st_mtime < cutoff:
                    bytes_freed += stat.st_size if stat.st_size else 0
                    if os.path.isfile(path):
                        os.remove(path)
                        files_removed += 1
                    elif os.path.isdir(path):
                        # 统计目录内实际文件数和大小
                        for dirpath, dirnames, dir_filenames in os.walk(path):
                            for df in dir_filenames:
                                try:
                                    bytes_freed += os.path.getsize(os.path.join(dirpath, df))
                                except Exception:
                                    pass
                                files_removed += 1
                        shutil.rmtree(path)
            except Exception:
                continue

        return {'success': True, 'files_removed': files_removed, 'bytes_freed': bytes_freed, 'bytes_freed_readable': _human_readable_size(bytes_freed)}
    except Exception as e:
        logger.warning(f"日志清理失败: {e}")
        return {'success': False, 'error': str(e)}


def clear_specific_logs():
    """清空特定日志文件并删除 task_xxx.log 文件"""
    try:
        logs_dir = get_app_subdir('logs')
        processed_files = []
        bytes_freed = 0

        # 清空 app.log 和 task_manager.log
        for fname in ('app.log', 'task_manager.log'):
            fpath = os.path.join(logs_dir, fname)
            if os.path.exists(fpath):
                try:
                    bytes_freed += os.path.getsize(fpath)
                    open(fpath, 'w', encoding='utf-8').close()
                    processed_files.append(fname)
                except Exception:
                    pass

        # 删除所有task_xxx.log文件
        for filename in os.listdir(logs_dir):
            if filename.startswith('task_') and filename.endswith('.log'):
                path = os.path.join(logs_dir, filename)
                try:
                    bytes_freed += os.path.getsize(path) if os.path.exists(path) else 0
                    os.remove(path)
                    processed_files.append(filename)
                except Exception:
                    pass

        return {'success': True, 'files_processed': len(processed_files), 'processed_files': processed_files, 'bytes_freed': bytes_freed, 'bytes_freed_readable': _human_readable_size(bytes_freed)}
    except Exception as e:
        logger.warning(f"清空日志失败: {e}")
        return {'success': False, 'error': str(e)}


def cleanup_downloads(hours: int):
    """清理下载目录中指定hours之前的任务目录"""
    try:
        downloads_dir = get_app_subdir('downloads')
        if not os.path.exists(downloads_dir):
            return {'success': True, 'dirs_removed': 0, 'files_removed': 0, 'bytes_freed': 0, 'bytes_freed_readable': '0B'}

        cutoff = time.time() - float(hours) * 3600
        dirs_removed = 0
        files_removed = 0
        bytes_freed = 0

        for entry in os.listdir(downloads_dir):
            path = os.path.join(downloads_dir, entry)
            try:
                if os.path.isdir(path):
                    # check last modification
                    mtime = os.path.getmtime(path)
                    if mtime < cutoff:
                        # accumulate size
                        for root, dirs, files in os.walk(path):
                            for f in files:
                                fp = os.path.join(root, f)
                                if os.path.exists(fp):
                                    bytes_freed += os.path.getsize(fp)
                                    files_removed += 1
                        shutil.rmtree(path)
                        dirs_removed += 1
            except Exception:
                continue

        return {'success': True, 'dirs_removed': dirs_removed, 'files_removed': files_removed, 'bytes_freed': bytes_freed, 'bytes_freed_readable': _human_readable_size(bytes_freed)}
    except Exception as e:
        logger.warning(f"下载内容清理失败: {e}")
        return {'success': False, 'error': str(e)}


def configure_app(app, config):
    """为Flask app应用一些基础配置值（如 secret_key、上传限制等）"""
    try:
        # 使用配置中的SECRET_KEY提高会话安全，首次运行时自动生成并持久化
        secret = config.get('SECRET_KEY') if isinstance(config, dict) else None
        if secret:
            app.secret_key = secret
        elif isinstance(config, dict):
            # 若新配置中无 SECRET_KEY 但 app 已有，则复用，避免 session 全部失效
            if app.secret_key:
                config['SECRET_KEY'] = app.secret_key
            else:
                import secrets
                new_secret = secrets.token_hex(32)
                config['SECRET_KEY'] = new_secret
                app.secret_key = new_secret
                try:
                    update_config({'SECRET_KEY': new_secret})
                    logger.info("已自动生成并保存SECRET_KEY")
                except Exception as e:
                    logger.warning(f"保存自动生成的SECRET_KEY失败: {e}")

        max_content = config.get('MAX_CONTENT_LENGTH_MB', None) if isinstance(config, dict) else None
        if max_content:
            try:
                app.config['MAX_CONTENT_LENGTH'] = int(max_content) * 1024 * 1024
            except Exception:
                pass

        timeout_minutes = 30
        if isinstance(config, dict):
            timeout_value = config.get('LOGIN_SESSION_TIMEOUT_MINUTES', 30)
            try:
                timeout_minutes = int(timeout_value)
            except (TypeError, ValueError):
                timeout_minutes = 30
        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=max(1, timeout_minutes))
        app.config['SESSION_REFRESH_EACH_REQUEST'] = True

        # 允许覆盖的内容
        app.config['Y2A_SETTINGS'] = config
    except Exception as e:
        logger.warning(f"应用配置失败: {e}")


def auto_start_pending_tasks(config):
    """在启动时尝试自动启动pending状态的任务"""
    try:
        from modules.task_manager import get_global_task_processor, get_tasks_by_status, TASK_STATES
        processor = get_global_task_processor(config)
        if not processor:
            return

        # 循环尝试启动下一个pending任务，直到并发数或没有更多pending
        # 我们设置一个上限避免无限循环
        attempts = 0
        while attempts < 200:
            attempts += 1
            try:
                processor._check_and_start_next_pending_task()
            except Exception:
                break
            # 如果没有pending则退出
            pending = get_tasks_by_status(TASK_STATES['PENDING'])
            if not pending:
                break
            time.sleep(0.05)
    except Exception as e:
        logger.warning(f"自动启动pending任务失败: {e}")


def schedule_log_cleanup():
    """为日志清理创建并启动一个BackgroundScheduler, 返回调度器对象"""
    try:
        config = load_config()
        interval_hours = int(config.get('LOG_CLEANUP_INTERVAL', 12))
        if not config.get('LOG_CLEANUP_ENABLED', False):
            return None

        scheduler = BackgroundScheduler()
        def _job():
            cleanup_logs(int(config.get('LOG_CLEANUP_HOURS', 168)))
        scheduler.add_job(_job, 'interval', hours=interval_hours, id='log_cleanup', replace_existing=True)
        scheduler.start()
        return scheduler
    except Exception as e:
        logger.warning(f"启动日志清理定时任务失败: {e}")
        return None


def schedule_download_cleanup():
    try:
        config = load_config()
        interval_hours = int(config.get('DOWNLOAD_CLEANUP_INTERVAL', 24))
        if not config.get('DOWNLOAD_CLEANUP_ENABLED', False):
            return None

        scheduler = BackgroundScheduler()
        def _job():
            cleanup_downloads(int(config.get('DOWNLOAD_CLEANUP_HOURS', 72)))
        scheduler.add_job(_job, 'interval', hours=interval_hours, id='download_cleanup', replace_existing=True)
        scheduler.start()
        return scheduler
    except Exception as e:
        logger.warning(f"启动下载内容清理定时任务失败: {e}")
        return None


# YouTube监控系统路由


@app.route('/api/cookies/sync', methods=['POST'])
@login_required
def sync_cookies():
    """
    接收从浏览器扩展同步过来的Cookie
    """
    try:
        if not request.is_json:
            return jsonify({'error': '请求必须是JSON格式'}), 400
        
        data = request.get_json()
        
        # 验证必要字段
        required_fields = ['source', 'timestamp', 'cookies', 'cookieCount']
        for field in required_fields:
            if field not in data:
                return jsonify({'error': f'缺少必要字段: {field}'}), 400
        
        # 验证来源
        if data['source'] not in ['userscript', 'extension']:
            return jsonify({'error': '不支持的cookie来源'}), 400
        
        # 验证cookie数据
        cookies_content = data['cookies']
        if not cookies_content or not isinstance(cookies_content, str):
            return jsonify({'error': 'cookie数据无效'}), 400
        
        # 保存cookie到文件
        cookies_dir = get_app_subdir('cookies')
        os.makedirs(cookies_dir, exist_ok=True)
        
        youtube_cookies_path = os.path.join(cookies_dir, 'yt_cookies.txt')
        
        # 写入新的cookie文件
        try:
            with open(youtube_cookies_path, 'w', encoding='utf-8') as f:
                f.write(cookies_content)
            
            # 记录同步信息
            sync_info = {
                'timestamp': data['timestamp'],
                'sync_time': time.time(),
                'cookie_count': data['cookieCount'],
                'user_agent': data.get('userAgent', ''),
                'source_url': data.get('url', ''),
                'file_size': len(cookies_content)
            }
            
            source_name = '浏览器扩展' if data['source'] == 'extension' else '油猴脚本'
            logger.info(f"Cookie同步成功 - 来源: {source_name}, 数量: {data['cookieCount']}, 大小: {len(cookies_content)} bytes")

            return jsonify({
                'success': True,
                'message': 'Cookie同步成功',
                'sync_info': sync_info
            }), 200
            
        except Exception as e:
            logger.error(f"写入cookie文件失败: {str(e)}")
            return jsonify({'error': '保存cookie失败，请稍后重试'}), 500

    except Exception as e:
        logger.error(f"Cookie同步API异常: {str(e)}")
        return jsonify({'error': '服务器内部错误，请稍后重试'}), 500

@app.route('/api/cookies/status', methods=['GET'])
@login_required
def get_cookie_status():
    """
    提供Cookie状态给浏览器扩展
    """
    try:
        cookies_dir = get_app_subdir('cookies')
        youtube_cookies_path = os.path.join(cookies_dir, 'yt_cookies.txt')
        
        status = {
            'youtube_cookies_exists': os.path.exists(youtube_cookies_path),
            'last_modified': None,
            'file_size': 0,
            'line_count': 0
        }
        
        if status['youtube_cookies_exists']:
            stat_info = os.stat(youtube_cookies_path)
            status['last_modified'] = stat_info.st_mtime
            status['file_size'] = stat_info.st_size
            
            # 统计行数
            try:
                with open(youtube_cookies_path, 'r', encoding='utf-8') as f:
                    status['line_count'] = sum(1 for line in f if line.strip() and not line.startswith('#'))
            except Exception as e:
                logger.warning(f"读取cookie文件失败: {str(e)}")
                status['line_count'] = -1
        
        return jsonify(status), 200
        
    except Exception as e:
        logger.error(f"获取cookie状态失败: {str(e)}")
        return jsonify({'error': '获取状态失败，请稍后重试'}), 500

@app.route('/api/cookies/refresh-needed', methods=['POST'])
@login_required
def cookie_refresh_needed():
    """
    接收浏览器扩展的通知，标记某个网站的Cookie需要刷新
    """
    try:
        data = request.get_json()
        reason = data.get('reason', 'unknown')
        video_url = data.get('video_url', '')
        
        logger.warning(f"收到Cookie刷新需求 - 原因: {reason}, 视频: {video_url}")
        
        # 这里可以实现通知机制，比如：
        # 1. 发送到浏览器扩展
        # 2. 在Web界面显示提示
        # 3. 发送邮件通知等
        
        return jsonify({
            'success': True,
            'message': 'Cookie刷新需求已记录',
            'suggestion': '请使用浏览器扩展重新同步Cookie'
        }), 200
        
    except Exception as e:
        logger.error(f"处理Cookie刷新需求失败: {str(e)}")
        return jsonify({'error': '处理失败，请稍后重试'}), 500

if __name__ == '__main__':
    logger.info("Y2A-Auto 启动中...")

    # 初始化AcFun分区ID映射
    init_id_mapping()

    # 加载配置
    config = load_config()
    app.config['Y2A_SETTINGS'] = config
    logger.info(
        "配置已加载（摘要）: %s",
        json.dumps(_build_startup_config_log_summary(config), ensure_ascii=False)
    )
    _sync_notification_service(config)

    # 初始化全局任务处理器，确保并发控制生效
    from modules.task_manager import get_global_task_processor, shutdown_global_task_processor
    get_global_task_processor(config)
    logger.info("全局任务处理器已初始化")

    # 自动启动所有pending任务（如果启用了自动模式）
    if config.get('AUTO_MODE_ENABLED', False):
        logger.info("自动模式已启用，正在启动所有pending任务...")
        auto_start_pending_tasks(config)

    # 初始化YouTube监控API
    if config.get('YOUTUBE_API_KEY'):
        api_ready, api_status = youtube_monitor.reload_api_client(config)
        if api_ready:
            youtube_monitor.start_all_schedules()
            if api_status == 'proxy_ready':
                logger.info("YouTube监控系统已初始化，独立代理已启用")
            else:
                logger.info("YouTube监控系统已初始化，当前为直连模式")
        else:
            if api_status == 'missing_api_key':
                logger.warning('YouTube API 密钥未配置，请先在设置页完成接入。')
            else:
                logger.warning('YouTube监控 API 初始化失败，请检查 API 密钥、代理配置与网络连通性。')

    # 配置应用
    configure_app(app, config)

    # 设置日志清理定时任务
    log_cleanup_scheduler = schedule_log_cleanup()

    # 设置下载内容清理定时任务
    download_cleanup_scheduler = schedule_download_cleanup()

    try:
        port = int(os.environ.get('PORT', 5000))
        logger.info(f"服务启动，监听地址: http://127.0.0.1:{port}")
        # 使用标准Flask运行
        app.run(host='0.0.0.0', port=port, debug=False)
    except KeyboardInterrupt:
        logger.info("接收到退出信号，服务正在关闭...")
    except Exception as e:
        logger.error(f"服务启动失败: {str(e)}")
    finally:
        # 关闭全局任务处理器
        shutdown_global_task_processor()

        if log_cleanup_scheduler:
            log_cleanup_scheduler.shutdown()
        if download_cleanup_scheduler:
            download_cleanup_scheduler.shutdown()
        logger.info("服务已关闭")
