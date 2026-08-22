#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Y2A-Auto JSON API v1（供 Vue 3 SPA 使用）。

设计约定：
- 统一返回 {"success": bool, "message": str, ...} 结构；
- 会话认证沿用 Flask session（与旧页面一致）；
- 变更类请求需携带 X-CSRF-Token 请求头（token 由 /auth/session 或 /settings 下发）；
- 复用 app.py 中已存在的辅助函数（通过 _app() 动态引用），避免逻辑漂移。
"""

import base64
import json
import logging
import mimetypes
import os
import secrets
import subprocess
import tempfile
import threading
import time
import uuid

import httpx
from datetime import datetime, timedelta
from functools import wraps
from queue import Empty

from flask import (
    Blueprint,
    Response,
    jsonify,
    request,
    send_file,
    session,
    stream_with_context,
)

from .config_manager import load_config, update_config, reset_specific_config
from .notifications import (
    CHANNEL_LABELS,
    CHANNEL_MESSAGE_PUSHER,
    CHANNEL_SERVERCHAN,
    CHANNEL_WECOM,
    EVENT_LOGIN_LOCKED,
    EVENT_LOGIN_SUCCESS,
    get_global_notification_service,
)
from .cookiecloud import (
    CookieCloudError,
    sync_cookiecloud_to_youtube_file,
    test_cookiecloud_youtube_sync,
)
from .task_manager import (
    TASK_STATES,
    add_task,
    clear_all_tasks,
    delete_task,
    force_upload_task,
    get_db_connection,
    get_metadata_translation_retry_block_reason,
    get_task,
    get_tasks_by_status,
    get_tasks_paginated,
    is_metadata_translation_retryable,
    register_task_updates_listener,
    retry_failed_tasks,
    retry_metadata_translation_task,
    resolve_cookie_file_path,
    start_task,
    unregister_task_updates_listener,
    update_task,
)
from .utils import get_app_subdir
from .whisper_languages import WHISPER_LANGUAGE_LIST
from .youtube_monitor import youtube_monitor

logger = logging.getLogger('Y2A-Auto.api_v1')

api_bp = Blueprint('api_v1', __name__, url_prefix='/api/v1')

_APP_MODULE = None


def _app():
    """动态获取 app 模块（python app.py 时为 __main__，gunicorn/测试时为 app）。"""
    global _APP_MODULE
    if _APP_MODULE is None:
        import sys
        _APP_MODULE = sys.modules.get('app') or sys.modules.get('__main__')
    return _APP_MODULE


# ---------------------------------------------------------------- CSRF / 认证

def _issue_csrf_token() -> str:
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_hex(24)
        session['_csrf_token'] = token
    return token


def _csrf_token_valid(submitted: str) -> bool:
    expected = session.get('_csrf_token')
    return bool(expected and submitted and secrets.compare_digest(expected, submitted))


def _request_csrf_token() -> str:
    return request.headers.get('X-CSRF-Token', '') or request.headers.get('X-Csrf-Token', '')


def api_protected(f):
    """API 专用保护：会话认证 + 变更请求 CSRF 校验（登录端点豁免 CSRF）。"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        config = load_config()
        if config.get('password_protection_enabled') and 'logged_in' not in session:
            return jsonify({
                'success': False,
                'message': '请先登录',
                'code': 'unauthorized',
            }), 401

        if request.method in ('POST', 'PUT', 'PATCH', 'DELETE'):
            endpoint = request.endpoint or ''
            if not endpoint.endswith('.auth_login'):
                if not _csrf_token_valid(_request_csrf_token()):
                    return jsonify({
                        'success': False,
                        'message': '安全校验失败，请刷新页面后重试。',
                        'code': 'csrf',
                    }), 403
        return f(*args, **kwargs)

    return wrapper


def _error(message: str, status: int = 400, **extra):
    payload = {'success': False, 'message': message}
    payload.update(extra)
    return jsonify(payload), status


def _ok(message: str = '操作成功', **extra):
    payload = {'success': True, 'message': message}
    payload.update(extra)
    return jsonify(payload)


@api_bp.errorhandler(404)
def _not_found(_exc):
    return _error('接口不存在', 404)


# ---------------------------------------------------------------- 认证

@api_bp.get('/auth/session')
def auth_session():
    config = load_config()
    protected = bool(config.get('password_protection_enabled'))
    authenticated = (not protected) or ('logged_in' in session)

    sec = _app()._load_security_state()
    now = time.time()
    locked_until = None
    if sec.get('locked_until', 0) and now < sec['locked_until']:
        locked_until = sec['locked_until']

    remaining_attempts = None
    if protected:
        max_attempts = int(config.get('LOGIN_MAX_FAILED_ATTEMPTS', 5) or 5)
        failed = int(sec.get('failed_attempts', 0) or 0)
        remaining_attempts = max(0, max_attempts - failed)

    return jsonify({
        'success': True,
        'authenticated': authenticated,
        'password_protection_enabled': protected,
        'locked_until': locked_until,
        'remaining_attempts': remaining_attempts,
        'csrf_token': _issue_csrf_token(),
    })


@api_bp.post('/auth/login')
def auth_login():
    config = load_config()
    if not config.get('password_protection_enabled'):
        return jsonify({
            'success': True,
            'message': '未启用密码保护，无需登录',
            'authenticated': True,
            'csrf_token': _issue_csrf_token(),
        })

    if 'logged_in' in session:
        return jsonify({'success': True, 'message': '已登录', 'csrf_token': _issue_csrf_token()})

    sec = _app()._load_security_state()
    now_ts = time.time()
    if sec.get('locked_until', 0) and now_ts < sec['locked_until']:
        remaining = int(sec['locked_until'] - now_ts)
        return jsonify({
            'success': False,
            'message': f'登录已被临时锁定，请 {remaining // 60} 分 {remaining % 60} 秒后重试。',
            'locked_until': sec['locked_until'],
            'remaining_seconds': remaining,
        })

    payload = request.get_json(silent=True) or {}
    password = payload.get('password')
    stored_password = config.get('password')

    if not stored_password:
        return _error('系统尚未设置密码，无法登录。请在禁用密码保护的情况下，进入设置页面设置密码。')

    if password and password == stored_password:
        session['logged_in'] = True
        session.permanent = True
        sec.update({'failed_attempts': 0, 'locked_until': 0, 'last_attempt': now_ts})
        _app()._save_security_state(sec)
        _app()._emit_login_event(EVENT_LOGIN_SUCCESS, {
            'ip_address': _app()._get_request_ip_address(),
        })
        return jsonify({'success': True, 'message': '登录成功', 'csrf_token': _issue_csrf_token()})

    max_attempts = int(config.get('LOGIN_MAX_FAILED_ATTEMPTS', 5) or 5)
    lock_minutes = int(config.get('LOGIN_LOCKOUT_MINUTES', 15) or 15)
    failed = int(sec.get('failed_attempts', 0) or 0) + 1
    sec['failed_attempts'] = failed
    sec['last_attempt'] = now_ts
    locked_until = None
    if failed >= max_attempts:
        sec['locked_until'] = now_ts + lock_minutes * 60
        locked_until = sec['locked_until']
        _save_sec = True
        _app()._emit_login_event(EVENT_LOGIN_LOCKED, {
            'ip_address': _app()._get_request_ip_address(),
            'failed_attempts': failed,
            'max_attempts': max_attempts,
            'lock_minutes': lock_minutes,
        })
        message = f'密码错误次数过多（{failed}/{max_attempts}），已锁定 {lock_minutes} 分钟。'
    else:
        _save_sec = True
        remain = max_attempts - failed
        message = f'密码错误。还可尝试 {remain} 次后将被锁定。'
    _app()._save_security_state(sec)

    return jsonify({
        'success': False,
        'message': message,
        'remaining_attempts': max(0, max_attempts - failed),
        'locked_until': locked_until,
    })


@api_bp.post('/auth/logout')
@api_protected
def auth_logout():
    session.pop('logged_in', None)
    session.pop('_csrf_token', None)
    return _ok('已退出登录')


# ---------------------------------------------------------------- 仪表盘

@api_bp.get('/dashboard')
@api_protected
def dashboard():
    stats = {
        'total_tasks': 0, 'awaiting_review': 0, 'failed_total': 0,
        'pending_total': 0, 'ready_total': 0, 'in_progress': 0,
        'completed_today': 0, 'failed_today': 0, 'created_today': 0,
    }
    recent_tasks = []
    try:
        conn = get_db_connection()
        cur = conn.cursor()

        now_local = datetime.now()
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        fmt = '%Y-%m-%d %H:%M:%S'
        start_str = today_start.strftime(fmt)
        end_str = tomorrow_start.strftime(fmt)

        cur.execute('SELECT COUNT(*) FROM tasks')
        stats['total_tasks'] = cur.fetchone()[0] or 0
        cur.execute('SELECT COUNT(*) FROM tasks WHERE status = ?', (TASK_STATES['AWAITING_REVIEW'],))
        stats['awaiting_review'] = cur.fetchone()[0] or 0
        cur.execute('SELECT COUNT(*) FROM tasks WHERE status = ?', (TASK_STATES['FAILED'],))
        stats['failed_total'] = cur.fetchone()[0] or 0
        cur.execute('SELECT COUNT(*) FROM tasks WHERE status = ?', (TASK_STATES['PENDING'],))
        stats['pending_total'] = cur.fetchone()[0] or 0
        cur.execute('SELECT COUNT(*) FROM tasks WHERE status = ?', (TASK_STATES['READY_FOR_UPLOAD'],))
        stats['ready_total'] = cur.fetchone()[0] or 0

        processing_states = (
            'fetching_info', 'info_fetched',
            TASK_STATES['TRANSLATING'], TASK_STATES['TAGGING'], TASK_STATES['PARTITIONING'],
            TASK_STATES['MODERATING'], TASK_STATES['DOWNLOADING'], TASK_STATES['DOWNLOADED'],
            TASK_STATES['ASR_TRANSCRIBING'], TASK_STATES['TRANSLATING_SUBTITLE'],
            TASK_STATES['ENCODING_VIDEO'], TASK_STATES['UPLOADING'],
        )
        placeholders = ','.join(['?'] * len(processing_states))
        cur.execute(
            f'SELECT COUNT(*) FROM tasks WHERE status IN ({placeholders})',
            processing_states,
        )
        stats['in_progress'] = cur.fetchone()[0] or 0

        cur.execute(
            'SELECT COUNT(*) FROM tasks WHERE status = ? AND updated_at >= ? AND updated_at < ?',
            (TASK_STATES['COMPLETED'], start_str, end_str),
        )
        stats['completed_today'] = cur.fetchone()[0] or 0
        cur.execute(
            'SELECT COUNT(*) FROM tasks WHERE status = ? AND updated_at >= ? AND updated_at < ?',
            (TASK_STATES['FAILED'], start_str, end_str),
        )
        stats['failed_today'] = cur.fetchone()[0] or 0
        cur.execute(
            'SELECT COUNT(*) FROM tasks WHERE created_at >= ? AND created_at < ?',
            (start_str, end_str),
        )
        stats['created_today'] = cur.fetchone()[0] or 0

        cur.execute(
            'SELECT id, video_title_translated, video_title_original, status, updated_at, '
            'upload_target, acfun_upload_response, bilibili_upload_response '
            'FROM tasks ORDER BY updated_at DESC LIMIT 10'
        )
        for r in cur.fetchall():
            upload_id = None
            upload_target = (r[5] or 'acfun').lower()
            try:
                if upload_target == 'both':
                    resp_b = json.loads(r[7]) if r[7] else None
                    resp_a = json.loads(r[6]) if r[6] else None
                    bv = resp_b.get('bvid') if isinstance(resp_b, dict) else None
                    ac = resp_a.get('ac_number') if isinstance(resp_a, dict) else None
                    if bv and ac:
                        upload_id = f'{bv} / AC{ac}'
                    elif bv:
                        upload_id = bv
                    elif ac:
                        upload_id = f'AC{ac}'
                elif upload_target == 'bilibili':
                    resp = json.loads(r[7]) if r[7] else None
                    if isinstance(resp, dict):
                        upload_id = resp.get('bvid') or resp.get('aid')
                else:
                    resp = json.loads(r[6]) if r[6] else None
                    if isinstance(resp, dict):
                        upload_id = resp.get('ac_number')
            except Exception:
                upload_id = None
            recent_tasks.append({
                'id': r[0],
                'title': r[1] or r[2] or '未获取标题',
                'status': r[3],
                'updated_at': r[4],
                'upload_target': upload_target,
                'upload_id': upload_id,
            })
        conn.close()
    except Exception as e:
        logger.warning('仪表盘统计失败: %s', e)

    return jsonify({'success': True, 'stats': stats, 'recent_tasks': recent_tasks})


# ---------------------------------------------------------------- 任务

@api_bp.get('/tasks')
@api_protected
def tasks_list():
    page = max(1, request.args.get('page', 1, type=int))
    per_page = max(1, min(request.args.get('per_page', 20, type=int), 100))
    status_filter = (request.args.get('status') or '').strip() or None
    search = (request.args.get('q') or '').strip() or None

    data = get_tasks_paginated(page=page, per_page=per_page, status=status_filter, search=search)
    for task in data.get('tasks', []):
        task['can_retry_translation'] = is_metadata_translation_retryable(task)
    return jsonify(data)


@api_bp.get('/tasks/<task_id>')
@api_protected
def task_detail(task_id):
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)

    task['can_retry_translation'] = is_metadata_translation_retryable(task)
    task['missing_partitions'] = _app()._missing_upload_partition_labels(task, load_config())

    try:
        task_dir_real = _app()._get_task_dir_real(task_id)
        active_cover = _app()._get_current_cover_path(task, task_dir_real) if os.path.isdir(task_dir_real) else ''
        task['cover_preview'] = bool(active_cover)
        task['cover_filename'] = os.path.basename(active_cover) if active_cover else ''
        task['has_original_cover_backup'] = bool(
            os.path.isdir(task_dir_real) and _app()._find_original_cover_backup(task_dir_real)
        )
        task['is_custom_cover_active'] = task['cover_filename'].startswith('custom_cover.')
    except Exception:
        task['cover_preview'] = bool(task.get('cover_path_local'))
        task['cover_filename'] = os.path.basename(str(task.get('cover_path_local') or ''))
        task['has_original_cover_backup'] = False
        task['is_custom_cover_active'] = False

    # 标签以列表形式返回，方便前端编辑
    tags_list = []
    if task.get('tags_generated'):
        try:
            tags_list = json.loads(task['tags_generated'])
        except Exception:
            tags_list = []
    task['tags_list'] = tags_list

    # 本地成品视频预览信息
    task['preview_available'] = False
    task['preview_kind'] = 'none'
    try:
        task_dir_real = _app()._get_task_dir_real(task_id)
        embedded = _app()._safe_join_task_dir(task_dir_real, 'video_dubbed.mp4')
        if not (embedded and os.path.isfile(embedded)):
            embedded = _app()._safe_join_task_dir(task_dir_real, 'video_with_subtitle.mp4')
        original = _app()._safe_join_task_dir(task_dir_real, 'video.mp4')
        if embedded and os.path.isfile(embedded):
            task['preview_available'] = True
            task['preview_kind'] = 'dubbed' if os.path.basename(embedded) == 'video_dubbed.mp4' else 'embedded'
        elif original and os.path.isfile(original):
            task['preview_available'] = True
            task['preview_kind'] = 'original'
    except (ValueError, OSError):
        task['preview_available'] = False
        task['preview_kind'] = 'none'

    return jsonify({
        'success': True,
        'task': task,
        'acfun_partition_mapping': _app()._load_acfun_partition_mapping(),
        'bilibili_partition_mapping': _app()._build_bilibili_partition_mapping(),
    })


@api_bp.post('/tasks')
@api_protected
def tasks_add():
    payload = request.get_json(silent=True) or {}
    youtube_url = str(payload.get('youtube_url') or '').strip()
    upload_target = str(payload.get('upload_target') or '').strip().lower()

    if not youtube_url:
        return _error('YouTube URL不能为空')

    config = load_config()
    if not upload_target:
        upload_target = config.get('UPLOAD_TARGET_DEFAULT', 'acfun')
    if upload_target not in ('acfun', 'bilibili', 'both'):
        return _error('无效的投稿平台参数')

    try:
        is_playlist = 'youtube.com/playlist' in youtube_url or 'youtu.be/playlist' in youtube_url
        if is_playlist:
            from .youtube_handler import extract_video_urls_from_playlist
            cookies_path = config.get('YOUTUBE_COOKIES_PATH')
            video_urls = extract_video_urls_from_playlist(youtube_url, cookies_path)
            if not video_urls:
                return _error('未能提取到播放列表中的视频')
            added_count = 0
            task_ids = []
            for url in video_urls:
                task_id = add_task(url, upload_target=upload_target)
                if task_id:
                    added_count += 1
                    task_ids.append(task_id)
                    if config.get('AUTO_MODE_ENABLED', False):
                        start_task(task_id, config)
            return jsonify({
                'success': True,
                'message': f'已批量添加 {added_count} 个视频任务（来自播放列表）',
                'task_ids': task_ids,
                'count': added_count,
            })
        else:
            task_id = add_task(youtube_url, upload_target=upload_target)
            if not task_id:
                return _error('添加任务失败', 500)
            started = False
            if config.get('AUTO_MODE_ENABLED', False):
                start_task(task_id, config)
                started = True
            return jsonify({
                'success': True,
                'message': '任务已添加并开始处理' if started else '任务已添加',
                'task_id': task_id,
            })
    except Exception as e:
        logger.error('添加任务失败: %s', e)
        return _error('服务器内部错误，请稍后重试', 500)


@api_bp.post('/tasks/<task_id>/start')
@api_protected
def task_start(task_id):
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)
    if task['status'] not in [TASK_STATES['PENDING'], TASK_STATES['FAILED']]:
        return _error('当前任务状态不能启动', 409)
    config = load_config()
    success = start_task(task_id, config)
    if success:
        return _ok('任务处理已启动')
    return _error('启动任务处理失败', 500)


@api_bp.post('/tasks/<task_id>/delete')
@api_protected
def task_delete(task_id):
    payload = request.get_json(silent=True) or {}
    delete_files = bool(payload.get('delete_files', True))
    success = delete_task(task_id, delete_files)
    if success:
        return _ok('任务已删除')
    return _error('删除任务失败', 500)


@api_bp.post('/tasks/clear_all')
@api_protected
def tasks_clear_all():
    payload = request.get_json(silent=True) or {}
    delete_files = bool(payload.get('delete_files', True))
    try:
        success = clear_all_tasks(delete_files=delete_files)
        if success:
            return _ok('所有任务已清空')
        return _error('清空任务失败，请查看日志', 500)
    except Exception as e:
        logger.error('清空所有任务失败: %s', e)
        return _error(f'清空任务失败: {e}', 500)


@api_bp.post('/tasks/retry_failed')
@api_protected
def tasks_retry_failed():
    try:
        cfg = load_config()
        result = retry_failed_tasks(cfg)
        if isinstance(result, dict):
            scheduled = result.get('scheduled', 0)
            total = result.get('total', 0)
            return _ok(f'已重新调度 {scheduled}/{total} 个失败任务')
        return _error('重新调度失败，请查看日志', 500)
    except Exception as e:
        logger.error('重试失败任务失败: %s', e)
        return _error(f'重试失败任务失败: {e}', 500)


@api_bp.post('/tasks/<task_id>/reprocess')
@api_protected
def task_reprocess(task_id):
    """重新处理任务：重置断点并置待处理，重跑字幕翻译与配音等后续阶段。"""
    from .task_manager import reprocess_task
    try:
        if not reprocess_task(task_id):
            return _error('任务不存在，无法重新处理', 404)
        return _ok('已重新调度：将按断点跳过已完成阶段并补跑字幕翻译/配音')
    except Exception as e:
        logger.error('重新处理任务 %s 失败: %s', task_id, e)
        return _error('重新处理失败', 500)


@api_bp.post('/tasks/<task_id>/dub')
@api_protected
def task_dub(task_id):
    """用现有视频+字幕文件一次性生成配音（后台线程执行，无需整条管线重跑）。"""
    from .task_manager import setup_task_logger

    config = load_config()
    api_key = str(config.get('TTS_DUB_API_KEY') or '').strip()
    if not api_key:
        return _error('未配置 TTS_DUB_API_KEY（语音配音分组）', 400)
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)
    video_path = str(task.get('video_path_local') or '').strip()
    if not video_path or not os.path.isfile(video_path):
        return _error('本地视频文件不存在，请先完成下载/处理', 400)

    has_srt = False
    try:
        task_dir = os.path.dirname(video_path)
        has_srt = any(str(f).lower().endswith('.srt') for f in os.listdir(task_dir))
    except OSError:
        pass
    if not (str(task.get('subtitle_path_translated') or '').strip()
            or str(task.get('subtitle_path_original') or '').strip() or has_srt):
        return _error('任务没有可用字幕文件，无法生成配音', 400)

    logger = setup_task_logger(task_id)
    update_task(task_id, status='dubbing_audio')

    from .task_manager import get_global_task_processor
    processor = get_global_task_processor(config)

    threading.Thread(
        target=processor._maybe_dub_audio,
        args=(task_id, logger),
        daemon=True,
        name=f'task-dub-{task_id[:8]}',
    ).start()
    return _ok('配音生成已启动，可稍后在详情页预览成品·配音')


@api_bp.post('/tasks/reset_stuck')
@api_protected
def tasks_reset_stuck():
    from .task_manager import reset_stuck_tasks
    try:
        reset_count = reset_stuck_tasks()
        if reset_count > 0:
            return _ok(f'已重置 {reset_count} 个卡住的任务')
        return _ok('没有发现卡住的任务')
    except Exception as e:
        logger.error('重置卡住任务失败: %s', e)
        return _error('重置卡住任务失败', 500)


@api_bp.post('/tasks/<task_id>/retry_translation')
@api_protected
def task_retry_translation(task_id):
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)
    if not is_metadata_translation_retryable(task):
        return _error('当前任务不是可重试的自动翻译失败任务')
    config = load_config()
    block_reason = get_metadata_translation_retry_block_reason(task, config)
    if block_reason:
        return _error(block_reason)
    try:
        if retry_metadata_translation_task(task_id, config):
            return _ok('已重新启动自动翻译，任务将在后台继续处理')
        return _error('重新启动自动翻译失败，请稍后重试', 500)
    except Exception as exc:
        logger.error('重试任务 %s 的自动翻译失败: %s', task_id, exc)
        return _error('重新启动自动翻译失败，请查看日志', 500)


@api_bp.post('/tasks/<task_id>/force_upload')
@api_protected
def task_force_upload(task_id):
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)
    config = load_config()
    upload_target = str(task.get('upload_target') or 'acfun').lower()
    platform_name = '双平台' if upload_target == 'both' else ('bilibili' if upload_target == 'bilibili' else 'AcFun')
    missing_partitions = _app()._missing_upload_partition_labels(task, config)
    if missing_partitions:
        return _error(f'请先选择{"、".join(missing_partitions)}，或开启分区推荐后再继续上传。')
    _app()._start_background_force_upload(task_id, config, platform_name)
    return _ok(f'已启动强制上传到{platform_name}，正在后台处理...')


@api_bp.post('/tasks/<task_id>/abandon')
@api_protected
def task_abandon(task_id):
    payload = request.get_json(silent=True) or {}
    delete_files = bool(payload.get('delete_files', True))
    update_task(task_id, status=TASK_STATES['FAILED'], error_message='用户主动放弃任务')
    if delete_files:
        from .task_manager import delete_task_files
        delete_task_files(task_id)
    return _ok('任务已废弃')


@api_bp.patch('/tasks/<task_id>')
@api_protected
def task_update(task_id):
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)

    payload = request.get_json(silent=True) or {}
    upload_target = str(task.get('upload_target') or 'acfun').lower()

    legacy_partition_id = str(payload.get('selected_partition_id') or '')
    partition_id_acfun = str(payload.get('selected_partition_id_acfun') or '')
    partition_id_bilibili = str(payload.get('selected_partition_id_bilibili') or '')

    if upload_target == 'both':
        partition_id_acfun = partition_id_acfun or legacy_partition_id
        partition_id_bilibili = partition_id_bilibili or legacy_partition_id
    elif upload_target == 'bilibili':
        partition_id_bilibili = partition_id_bilibili or legacy_partition_id
    else:
        partition_id_acfun = partition_id_acfun or legacy_partition_id

    tags = payload.get('tags')
    if isinstance(tags, (list, tuple)):
        tags_json = json.dumps(
            [str(t).strip() for t in tags if str(t).strip()], ensure_ascii=False
        )
    else:
        tags_json = json.dumps(
            [t.strip() for t in str(tags or '').replace('，', ',').split(',') if t.strip()],
            ensure_ascii=False,
        )

    update_data = {
        'video_title_translated': str(payload.get('video_title_translated') or ''),
        'description_translated': str(payload.get('description_translated') or ''),
        'selected_partition_id_acfun': partition_id_acfun,
        'selected_partition_id_bilibili': partition_id_bilibili,
        'tags_generated': tags_json,
        'error_message': None,
        'error_category': None,
    }

    safe_states_to_make_uploadable = [
        TASK_STATES['DOWNLOADED'],
        TASK_STATES['MODERATING'],
        TASK_STATES['AWAITING_REVIEW'],
        TASK_STATES['FAILED'],
        TASK_STATES['UPLOADING'],
    ]
    if task['status'] in safe_states_to_make_uploadable:
        update_data['status'] = TASK_STATES['READY_FOR_UPLOAD']

    try:
        update_task(task_id, **update_data)
    except Exception as e:
        logger.warning('update_task调用失败: %s', e)

    updated_task = get_task(task_id) or task
    message = '任务已保存。'

    if payload.get('force_upload'):
        config = load_config()
        target = str(updated_task.get('upload_target') or 'acfun').lower()
        platform_name = '双平台' if target == 'both' else ('bilibili' if target == 'bilibili' else 'AcFun')
        missing = _app()._missing_upload_partition_labels(updated_task, config)
        if missing:
            return _error(f'请先选择{"、".join(missing)}，或开启分区推荐后再继续上传。')
        _app()._start_background_force_upload(task_id, config, platform_name)
        message = f'已保存当前修改，并启动强制上传到{platform_name}，正在后台处理...'
    elif updated_task.get('status') == TASK_STATES['READY_FOR_UPLOAD']:
        message = '任务已保存，当前可单独执行上传。'

    updated_task = get_task(task_id) or updated_task
    updated_task['can_retry_translation'] = is_metadata_translation_retryable(updated_task)
    return jsonify({'success': True, 'message': message, 'task': updated_task})


@api_bp.get('/tasks/<task_id>/cover')
@api_protected
def task_cover(task_id):
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)
    try:
        task_dir_real = _app()._get_task_dir_real(task_id)
    except (ValueError, OSError):
        return _error('任务目录无效', 404)
    cover_path = _app()._get_current_cover_path(task, task_dir_real)
    if cover_path and os.path.exists(cover_path):
        mime_type, _ = mimetypes.guess_type(cover_path)
        response = send_file(cover_path, mimetype=mime_type)
        response.headers['Cache-Control'] = 'no-store'
        return response
    return _error('暂无封面', 404)


@api_bp.get('/tasks/<task_id>/preview')
@api_protected
def task_video_preview(task_id):
    """流式返回任务本地成品视频（支持 Range 拖动进度条）。

    优先返回烧录翻译字幕的成品（video_with_subtitle.mp4），
    否则返回原片（video.mp4），均严格限定在任务目录内。
    """
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)
    try:
        task_dir_real = _app()._get_task_dir_real(task_id)
    except (ValueError, OSError):
        return _error('任务目录无效', 404)

    candidates = [
        _app()._safe_join_task_dir(task_dir_real, 'video_dubbed.mp4'),
        _app()._safe_join_task_dir(task_dir_real, 'video_with_subtitle.mp4'),
        _app()._safe_join_task_dir(task_dir_real, 'video.mp4'),
    ]
    # 兜底：数据库记录的路径若仍在任务目录内也允许
    stored_video = str(task.get('video_path_local') or '').strip()
    if stored_video:
        candidates.append(_app()._safe_join_task_dir(task_dir_real, os.path.basename(stored_video)))

    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            mime_type, _ = mimetypes.guess_type(candidate)
            response = send_file(candidate, mimetype=mime_type or 'video/mp4', conditional=True)
            response.headers['Cache-Control'] = 'no-store'
            return response
    return _error('视频文件不存在', 404)


@api_bp.post('/tasks/<task_id>/cover')
@api_protected
def task_cover_upload(task_id):
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)
    cover_file = request.files.get('cover_file')
    try:
        _app()._replace_task_cover(task, cover_file)
        return _ok('任务封面已更新。')
    except Exception as e:
        logger.warning('替换任务 %s 封面失败: %s', task_id, e)
        return _error(f'更换封面失败: {e}', 500)


@api_bp.post('/tasks/<task_id>/cover/restore')
@api_protected
def task_cover_restore(task_id):
    task = get_task(task_id)
    if not task:
        return _error('任务不存在', 404)
    try:
        _app()._restore_task_cover(task)
        return _ok('已恢复原始封面。')
    except Exception as e:
        logger.warning('恢复任务 %s 原始封面失败: %s', task_id, e)
        return _error(f'恢复原封面失败: {e}', 500)


@api_bp.get('/tasks/<task_id>/log')
@api_protected
def task_log(task_id):
    log_path = os.path.join(get_app_subdir('logs'), f'task_{task_id}.log')
    if not os.path.exists(log_path):
        return jsonify({'success': True, 'content': ''})
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            # 只返回尾部，避免超大日志拖垮前端
            f.seek(0, os.SEEK_END)
            size = f.tell()
            read_size = min(size, 256 * 1024)
            f.seek(max(0, size - read_size))
            content = f.read()
        return jsonify({'success': True, 'content': content})
    except Exception as e:
        logger.warning('读取任务 %s 日志失败: %s', task_id, e)
        return _error('读取任务日志失败', 500)


@api_bp.get('/tasks/stream')
@api_protected
def tasks_stream():
    """Server-Sent Events 实时任务更新流。"""
    def generate():
        listener = register_task_updates_listener()
        try:
            yield 'data: {"type":"welcome"}\n\n'
            while True:
                try:
                    event = listener.get(timeout=10)
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except Empty:
                    yield 'data: {"type":"heartbeat"}\n\n'
        except GeneratorExit:
            pass
        finally:
            unregister_task_updates_listener(listener)

    response = Response(stream_with_context(generate()), mimetype='text/event-stream')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Connection'] = 'keep-alive'
    response.headers['Transfer-Encoding'] = 'chunked'
    return response


# ---------------------------------------------------------------- 设置

@api_bp.get('/settings')
@api_protected
def settings_get():
    config = load_config()
    # 敏感值不回传明文，前端只关心“是否已设置”
    safe_config = dict(config)
    password_set = bool(safe_config.get('password'))
    safe_config.pop('password', None)
    safe_config['password_set'] = password_set

    try:
        from .prompt_manager import get_builtin_prompt_previews
        builtin_prompts = get_builtin_prompt_previews()
    except Exception as exc:
        logger.debug('获取内置 Prompt 预览失败: %s', exc)
        builtin_prompts = {}

    return jsonify({
        'success': True,
        'config': safe_config,
        'whisper_languages': WHISPER_LANGUAGE_LIST,
        'acfun_partition_mapping': _app()._load_acfun_partition_mapping(),
        'bilibili_partition_mapping': _app()._build_bilibili_partition_mapping(),
        'builtin_prompts': builtin_prompts,
        'tgbot_token_state': _app()._tgbot_api_token_state(config),
        'csrf_token': _issue_csrf_token(),
    })


@api_bp.post('/settings')
@api_protected
def settings_save():
    form_data = request.form.to_dict()
    uploads = _app()._extract_settings_uploads(request.files)
    operation_id = str(form_data.get('save_operation_id') or uuid.uuid4())
    enable_password_protection = str(form_data.get('password_protection_enabled', '')).lower() in ['true', '1', 'on']
    submitted_new_password = str(form_data.get('new_password') or '')
    submitted_confirm_password = str(form_data.get('confirm_password') or '')
    config = load_config()
    has_effective_password = (
        (submitted_new_password and submitted_new_password == submitted_confirm_password)
        or bool(config.get('password'))
    )

    # 与旧设置页一致：启用保护且存在有效密码时，立即把当前会话标记为已登录
    if enable_password_protection and has_effective_password:
        session['logged_in'] = True
        session.permanent = True

    _app()._update_settings_save_progress(
        operation_id,
        stage='saving_config',
        message='正在准备保存设置',
        detail='保存任务已创建，正在后台执行。',
        percent=None,
        done=False,
        level='info',
        success=None,
        messages=[],
    )
    save_thread = threading.Thread(
        target=_app()._run_settings_save_operation,
        args=(operation_id, form_data, uploads),
        daemon=True,
        name=f'settings-save-{operation_id[:8]}',
    )
    save_thread.start()
    return jsonify({
        'success': True,
        'message': '设置保存已启动',
        'operation_id': operation_id,
        'csrf_token': _issue_csrf_token(),
    })


@api_bp.get('/settings/save-progress/<operation_id>')
@api_protected
def settings_save_progress(operation_id):
    progress = _app()._get_settings_save_progress(operation_id)
    if not progress:
        return jsonify({
            'found': False, 'stage': None, 'message': '', 'detail': '',
            'percent': None, 'downloaded_bytes': None, 'total_bytes': None,
            'done': True, 'level': 'error', 'success': False, 'messages': [],
        })
    return jsonify({
        'found': True,
        'stage': progress.get('stage'),
        'message': progress.get('message'),
        'detail': progress.get('detail'),
        'percent': progress.get('percent'),
        'downloaded_bytes': progress.get('downloaded_bytes'),
        'total_bytes': progress.get('total_bytes'),
        'done': progress.get('done', False),
        'level': progress.get('level', 'info'),
        'success': progress.get('success'),
        'messages': progress.get('messages', []),
    })


@api_bp.post('/settings/reset')
@api_protected
def settings_reset():
    payload = request.get_json(silent=True) or {}
    keys = payload.get('keys') or []
    if not keys:
        return _error('未指定要重置的配置项')
    try:
        reset_specific_config(keys)
        return _ok('当前页面的设置已重置为默认值。')
    except Exception as e:
        logger.error('重置设置失败: %s', e)
        return _error('重置设置失败，请稍后重试', 500)


@api_bp.post('/settings/tgbot-token')
@api_protected
def settings_tgbot_token():
    payload = request.get_json(silent=True) or {}
    action = str(payload.get('action') or '').strip().lower()
    if action in ('generate', 'reset'):
        token = _app()._generate_tgbot_api_token()
        updated_config = update_config({
            'TG_BOT_API_TOKEN_HASH': _app()._hash_tgbot_api_token(token),
            'TG_BOT_API_TOKEN_CREATED_AT': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'TG_BOT_API_TOKEN_LAST4': token[-4:],
        })
        return jsonify({
            'success': True,
            'message': 'Telegram Bot API Token 已生成，旧 Token 已失效。请立即复制保存。',
            'token': token,
            'state': _app()._tgbot_api_token_state(updated_config),
        })
    if action == 'revoke':
        updated_config = update_config({
            'TG_BOT_API_TOKEN_HASH': '',
            'TG_BOT_API_TOKEN_CREATED_AT': '',
            'TG_BOT_API_TOKEN_LAST4': '',
        })
        return jsonify({
            'success': True,
            'message': 'Telegram Bot API Token 已撤销。',
            'state': _app()._tgbot_api_token_state(updated_config),
        })
    return _error('未知的 Token 操作。')


@api_bp.post('/settings/tts/test')
@api_protected
def settings_test_tts():
    """合成一小段语音验证 fish.audio 配置（真实调用，返回时长）。"""
    payload = request.get_json(silent=True) or {}
    text = str(payload.get('text') or '').strip() or '这是一段语音合成测试。'
    config = load_config()
    api_key = str(config.get('TTS_DUB_API_KEY') or '').strip()
    if not api_key:
        return _error('未配置 TTS_DUB_API_KEY（语音配音分组）', 400)
    try:
        from .tts_dub import FishAudioTtsClient
        client = FishAudioTtsClient(
            api_key=api_key,
            base_url=str(config.get('TTS_DUB_BASE_URL') or 'https://api.fish.audio'),
            model=str(config.get('TTS_DUB_MODEL') or 's2.1-pro-free'),
            max_retries=int(config.get('TTS_DUB_MAX_RETRIES') or 1),
            retry_delay_s=0,
        )
        audio = client.synthesize(text, speed=float(config.get('TTS_DUB_SPEED') or 1.0))
        duration_ms = 0
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp:
            tmp.write(audio)
            tmp_path = tmp.name
        try:
            from .ffmpeg_manager import get_ffprobe_path, get_ffmpeg_path
            ffmpeg = get_ffmpeg_path()
            if ffmpeg and os.path.exists(ffmpeg):
                ffprobe = get_ffprobe_path(ffmpeg_path=ffmpeg)
                if ffprobe:
                    out = subprocess.run(
                        [ffprobe, '-v', 'error', '-show_entries', 'format=duration',
                         '-of', 'default=noprint_wrappers=1:nokey=1', tmp_path],
                        capture_output=True, text=True, timeout=60,
                    )
                    duration_ms = int(float(str(out.stdout or '').strip() or 0) * 1000)
        finally:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return jsonify({
            'success': True,
            'message': f'合成成功（{duration_ms}ms）',
            'duration_ms': duration_ms,
            'model': str(config.get('TTS_DUB_MODEL') or ''),
        })
    except Exception as exc:
        return _error(f'合成测试失败: {str(exc)[:200]}', 502)


@api_bp.get('/settings/tts/voices')
@api_protected
def settings_tts_voices():
    """浏览 fish.audio 公开说话人库（Voice Library）。"""
    config = load_config()
    api_key = str(config.get('TTS_DUB_API_KEY') or '').strip()
    if not api_key:
        return _error('未配置 TTS_DUB_API_KEY（语音配音分组）', 400)

    page = int(request.args.get('page') or 1)
    page_size = min(int(request.args.get('page_size') or 30), 50)
    query = str(request.args.get('q') or '').strip()[:80]

    params = {'page_size': page_size, 'page_number': max(1, page)}
    if query:
        params['title'] = query
    try:
        resp = httpx.get(
            'https://api.fish.audio/model',
            params=params,
            headers={'Authorization': f'Bearer {api_key}'},
            timeout=20,
        )
    except Exception as exc:
        return _error(f'获取说话人列表失败: {str(exc)[:150]}', 502)
    if resp.status_code != 200:
        return _error(f'Fish Audio 返回 {resp.status_code}: {resp.text[:150]}', 502)

    data = resp.json() or {}
    items = []
    for model in (data.get('items') or []):
        if not isinstance(model, dict):
            continue
        voice_id = str(model.get('_id') or model.get('id') or '').strip()
        if not voice_id:
            continue
        items.append({
            'id': voice_id,
            'title': str(model.get('title') or '').strip(),
            'state': str(model.get('state') or ''),
            'languages': [str(x) for x in (model.get('languages') or [])],
            'tags': [str(x) for x in (model.get('tags') or [])],
            'description': str(model.get('description') or '')[:200],
        })
    return jsonify({
        'success': True,
        'total': int(data.get('total') or len(items)),
        'has_more': bool(data.get('has_more', False)),
        'items': items,
    })


@api_bp.post('/settings/tts/preview')
@api_protected
def settings_tts_preview():
    """按指定说话人合成试听音频（约 1-2 秒文本，返回 base64 mp3）。"""
    payload = request.get_json(silent=True) or {}
    voice_id = str(payload.get('voice_id') or '').strip()
    if not voice_id:
        return _error('缺少 voice_id', 400)
    config = load_config()
    api_key = str(config.get('TTS_DUB_API_KEY') or '').strip()
    if not api_key:
        return _error('未配置 TTS_DUB_API_KEY（语音配音分组）', 400)
    try:
        from .tts_dub import FishAudioTtsClient
        client = FishAudioTtsClient(
            api_key=api_key,
            model=str(config.get('TTS_DUB_MODEL') or 's2.1-pro-free'),
            max_retries=int(config.get('TTS_DUB_MAX_RETRIES') or 1),
            retry_delay_s=0,
        )
        audio = client.synthesize('你好，这是 Y2A-Auto 配音功能的试听语音。', reference_id=voice_id)
        return jsonify({
            'success': True,
            'audio_base64': base64.encodebytes(audio).decode('ascii'),
            'mime': 'audio/mpeg',
            'voice_id': voice_id,
        })
    except Exception as exc:
        return _error(f'试听合成失败: {str(exc)[:200]}', 502)


@api_bp.post('/settings/notifications/test')
@api_protected
def settings_test_notification():
    payload = request.get_json(silent=True) or {}
    channel = str(payload.get('channel') or '').strip()
    if channel not in (CHANNEL_WECOM, CHANNEL_SERVERCHAN, CHANNEL_MESSAGE_PUSHER):
        return _error('不支持的通知渠道')
    try:
        config = load_config()
        _app()._sync_notification_service(config)
        service = get_global_notification_service(config)
        service.send_test_message(channel)
        return _ok(f'{CHANNEL_LABELS.get(channel, channel)} 测试消息已发送')
    except ValueError:
        logger.warning('测试通知发送失败，渠道=%s', channel, exc_info=True)
        return _error(f'{CHANNEL_LABELS.get(channel, channel)} 配置不完整，请检查后重试')
    except Exception:
        logger.exception('测试通知发送失败，渠道=%s', channel)
        return _error('测试通知发送失败，请稍后重试', 500)


@api_bp.post('/settings/cookiecloud/test')
@api_protected
def settings_test_cookiecloud():
    payload = request.get_json(silent=True) or {}
    effective_config = _app()._merge_cookiecloud_runtime_settings(payload)
    try:
        result = test_cookiecloud_youtube_sync(effective_config)
        message = (
            f"CookieCloud 连接成功，已解析 {result['cookie_count']} 条 YouTube/Google Cookies，"
            f"当前使用 {result['crypto_type_used']} 算法。"
        )
        updated_at = _app()._remember_cookiecloud_sync_result(True, message)
        return jsonify({
            'success': True, 'message': message,
            'cookie_count': result['cookie_count'],
            'crypto_type_used': result['crypto_type_used'],
            'updated_at': updated_at, 'status': 'success',
        })
    except CookieCloudError as exc:
        message = _app()._cookiecloud_operation_error_message('test')
        updated_at = _app()._remember_cookiecloud_sync_result(False, message)
        logger.warning('CookieCloud 连接测试失败（%s）: %s', type(exc).__name__, exc)
        return jsonify({
            'success': False, 'message': message,
            'updated_at': updated_at, 'status': 'error',
        }), 400
    except Exception:
        message = _app()._cookiecloud_operation_error_message('test', retry_later=True)
        updated_at = _app()._remember_cookiecloud_sync_result(False, message)
        logger.exception('CookieCloud 连接测试失败')
        return jsonify({
            'success': False, 'message': message,
            'updated_at': updated_at, 'status': 'error',
        }), 500


@api_bp.post('/settings/cookiecloud/sync')
@api_protected
def settings_sync_cookiecloud():
    payload = request.get_json(silent=True) or {}
    effective_config = _app()._merge_cookiecloud_runtime_settings(payload)
    try:
        result = sync_cookiecloud_to_youtube_file(effective_config)
        message = (
            f"CookieCloud 已成功写入 {result['cookie_count']} 条 YouTube/Google Cookies 到 "
            f"{result['output_path_display']}。"
        )
        updated_at = _app()._remember_cookiecloud_sync_result(True, message)
        return jsonify({
            'success': True, 'message': message,
            'cookie_count': result['cookie_count'],
            'crypto_type_used': result['crypto_type_used'],
            'output_path_display': result['output_path_display'],
            'updated_at': updated_at, 'status': 'success',
        })
    except CookieCloudError as exc:
        message = _app()._cookiecloud_operation_error_message('sync')
        updated_at = _app()._remember_cookiecloud_sync_result(False, message)
        logger.warning('CookieCloud 立即拉取失败（%s）: %s', type(exc).__name__, exc)
        return jsonify({
            'success': False, 'message': message,
            'updated_at': updated_at, 'status': 'error',
        }), 400
    except Exception:
        message = _app()._cookiecloud_operation_error_message('sync', retry_later=True)
        updated_at = _app()._remember_cookiecloud_sync_result(False, message)
        logger.exception('CookieCloud 立即拉取失败')
        return jsonify({
            'success': False, 'message': message,
            'updated_at': updated_at, 'status': 'error',
        }), 500


@api_bp.post('/settings/acfun/qrcode/start')
@api_protected
def acfun_qrcode_start():
    config = load_config()
    cookie_path = resolve_cookie_file_path(
        path_value=config.get('ACFUN_COOKIES_PATH', 'cookies/ac_cookies.json'),
        default_relative_path='cookies/ac_cookies.json',
        service_name='AcFun',
        logger_obj=logger,
        allow_json_txt_fallback=True,
    )
    try:
        session_id, qr_session = _app()._create_acfun_qr_session()
        qr_data = qr_session.generate()
        return jsonify({
            'success': True,
            'session_id': session_id,
            'image_base64': qr_data.get('image_base64', ''),
            'mime_type': qr_data.get('mime_type', 'image/png'),
            'expires_in': _app()._ACFUN_QR_SESSION_TTL_SECONDS,
            'qr_expires_in_ms': qr_data.get('expires_in_ms', 120000),
            'cookie_path': cookie_path,
        })
    except Exception as e:
        logger.error('发起 AcFun 二维码登录失败: %s', e)
        return _error('二维码登录失败，请稍后重试', 500)


@api_bp.get('/settings/acfun/qrcode/status/<session_id>')
@api_protected
def acfun_qrcode_status(session_id):
    qr_session = _app()._get_acfun_qr_session(session_id)
    if not qr_session:
        return _error('二维码会话不存在或已过期', 404)
    config = load_config()
    cookie_path = resolve_cookie_file_path(
        path_value=config.get('ACFUN_COOKIES_PATH', 'cookies/ac_cookies.json'),
        default_relative_path='cookies/ac_cookies.json',
        service_name='AcFun',
        logger_obj=logger,
        allow_json_txt_fallback=True,
    )
    try:
        status_data = qr_session.check_status(cookie_file=cookie_path)
        _app()._emit_qr_login_event_once(
            _app()._ACFUN_QR_SESSIONS,
            _app()._ACFUN_QR_SESSION_LOCK,
            session_id,
            'AcFun',
            status_data,
        )
        status = status_data.get('status')
        if status == 'timeout':
            with _app()._ACFUN_QR_SESSION_LOCK:
                _app()._ACFUN_QR_SESSIONS.pop(session_id, None)
        return jsonify({'success': True, **status_data})
    except Exception as e:
        logger.error('查询 AcFun 二维码登录状态失败: %s', e)
        return _error('查询登录状态失败，请稍后重试', 500)


@api_bp.post('/settings/bilibili/qrcode/start')
@api_protected
def bilibili_qrcode_start():
    config = load_config()
    cookie_path = resolve_cookie_file_path(
        path_value=config.get('BILIBILI_COOKIES_PATH', 'cookies/bili_cookies.json'),
        default_relative_path='cookies/bili_cookies.json',
        service_name='Bilibili',
        logger_obj=logger,
        allow_json_txt_fallback=False,
    )
    try:
        session_id, qr_session = _app()._create_bilibili_qr_session()
        qr_data = qr_session.generate()
        return jsonify({
            'success': True,
            'session_id': session_id,
            'image_base64': qr_data.get('image_base64', ''),
            'mime_type': qr_data.get('mime_type', 'image/png'),
            'expires_in': _app()._BILIBILI_QR_SESSION_TTL_SECONDS,
            'cookie_path': cookie_path,
        })
    except Exception as e:
        logger.error('发起 bilibili 二维码登录失败: %s', e)
        return _error('二维码登录失败，请稍后重试', 500)


@api_bp.get('/settings/bilibili/qrcode/status/<session_id>')
@api_protected
def bilibili_qrcode_status(session_id):
    qr_session = _app()._get_bilibili_qr_session(session_id)
    if not qr_session:
        return _error('二维码会话不存在或已过期', 404)
    config = load_config()
    cookie_path = resolve_cookie_file_path(
        path_value=config.get('BILIBILI_COOKIES_PATH', 'cookies/bili_cookies.json'),
        default_relative_path='cookies/bili_cookies.json',
        service_name='Bilibili',
        logger_obj=logger,
        allow_json_txt_fallback=False,
    )
    try:
        status_data = qr_session.check_status(cookie_file=cookie_path)
        _app()._emit_qr_login_event_once(
            _app()._BILIBILI_QR_SESSIONS,
            _app()._BILIBILI_QR_SESSION_LOCK,
            session_id,
            'bilibili',
            status_data,
        )
        status = status_data.get('status')
        if status in ('done', 'timeout', 'failed'):
            with _app()._BILIBILI_QR_SESSION_LOCK:
                _app()._BILIBILI_QR_SESSIONS.pop(session_id, None)
        return jsonify({'success': True, **status_data})
    except Exception as e:
        logger.error('查询 bilibili 二维码登录状态失败: %s', e)
        return _error('查询登录状态失败，请稍后重试', 500)


# ---------------------------------------------------------------- 维护

@api_bp.post('/maintenance/clear_logs')
@api_protected
def maintenance_clear_logs():
    payload = request.get_json(silent=True) or {}
    if payload.get('all'):
        result = _app().clear_specific_logs()
        if result.get('success'):
            processed = '、'.join(result.get('processed_files', []))
            return jsonify({
                'success': True,
                'message': f"日志清理成功，已处理 {result.get('files_processed', 0)} 个文件（{processed}），释放了 {result.get('bytes_freed_readable', '0B')} 空间",
                **result,
            })
        return jsonify({'success': False, 'message': f"日志清理失败: {result.get('error', '未知错误')}", **result})
    try:
        config = load_config()
        hours = int(payload.get('hours') or config.get('LOG_CLEANUP_HOURS', 168))
    except (TypeError, ValueError):
        return _error('清理时长参数无效')
    result = _app().cleanup_logs(hours)
    if result.get('success'):
        return jsonify({
            'success': True,
            'message': f"日志清理成功，删除了 {result.get('files_removed', 0)} 个文件，释放了 {result.get('bytes_freed_readable', '0B')} 空间",
            **result,
        })
    return jsonify({'success': False, 'message': f"日志清理失败: {result.get('error', '未知错误')}", **result})


@api_bp.post('/maintenance/cleanup_downloads')
@api_protected
def maintenance_cleanup_downloads():
    payload = request.get_json(silent=True) or {}
    try:
        config = load_config()
        hours = int(payload.get('hours') or config.get('DOWNLOAD_CLEANUP_HOURS', 72))
    except (TypeError, ValueError):
        return _error('清理时长参数无效')
    result = _app().cleanup_downloads(hours)
    if result.get('success'):
        return jsonify({
            'success': True,
            'message': f"下载内容清理成功，删除了 {result.get('dirs_removed', 0)} 个目录、{result.get('files_removed', 0)} 个文件，释放了 {result.get('bytes_freed_readable', '0B')} 空间",
            **result,
        })
    return jsonify({'success': False, 'message': f"下载内容清理失败: {result.get('error', '未知错误')}", **result})


# ---------------------------------------------------------------- 系统健康

@api_bp.get('/system_health')
def system_health():
    """复用旧 /system_health 路由的完整实现（返回 JSON）。"""
    return _app().system_health()


# ---------------------------------------------------------------- YouTube 监控

def _monitor_config_from_payload(payload: dict) -> dict:
    def safe_int(value, default=0):
        if value is None or str(value).strip() == '':
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default

    video_types = payload.get('video_types')
    if isinstance(video_types, (list, tuple)):
        vt = ','.join(str(v) for v in video_types if str(v) in ('video', 'short', 'live'))
        if not vt:
            vt = 'video,short,live'
    else:
        vt = str(video_types or '') or 'video,short,live'

    return {
        'name': str(payload.get('name') or '').strip(),
        'enabled': bool(payload.get('enabled')),
        'monitor_type': payload.get('monitor_type') or 'youtube_search',
        'channel_mode': payload.get('channel_mode') or 'latest',
        'region_code': payload.get('region_code') or 'US',
        'category_id': payload.get('category_id') or '0',
        'time_period': safe_int(payload.get('time_period'), 7),
        'max_results': safe_int(payload.get('max_results'), 10),
        'min_view_count': safe_int(payload.get('min_view_count'), 0),
        'min_like_count': safe_int(payload.get('min_like_count'), 0),
        'min_comment_count': safe_int(payload.get('min_comment_count'), 0),
        'keywords': payload.get('keywords') or '',
        'exclude_keywords': payload.get('exclude_keywords') or '',
        'channel_ids': payload.get('channel_ids') or '',
        'channel_keywords': payload.get('channel_keywords') or '',
        'exclude_channel_ids': payload.get('exclude_channel_ids') or '',
        'min_duration': safe_int(payload.get('min_duration'), 0),
        'max_duration': safe_int(payload.get('max_duration'), 0),
        'schedule_type': payload.get('schedule_type') or 'manual',
        'schedule_interval': safe_int(payload.get('schedule_interval'), 120),
        'order_by': payload.get('order_by') or 'viewCount',
        'start_date': payload.get('start_date') or '',
        'end_date': payload.get('end_date') or '',
        'latest_days': safe_int(payload.get('latest_days'), 7),
        'latest_max_results': safe_int(payload.get('latest_max_results'), 20),
        'rate_limit_requests': safe_int(payload.get('rate_limit_requests'), 20),
        'rate_limit_window': safe_int(payload.get('rate_limit_window'), 60),
        'auto_add_to_tasks': bool(payload.get('auto_add_to_tasks')),
        'video_types': vt,
    }


@api_bp.get('/monitor')
@api_protected
def monitor_index():
    configs = youtube_monitor.get_monitor_configs()
    history = youtube_monitor.get_monitor_history(limit=50)
    return jsonify({'success': True, 'configs': configs, 'history': history})


@api_bp.get('/monitor/configs')
@api_protected
def monitor_configs():
    configs = youtube_monitor.get_monitor_configs()
    return jsonify({'success': True, 'configs': configs})


@api_bp.get('/monitor/configs/<int:config_id>')
@api_protected
def monitor_config_get(config_id):
    config = youtube_monitor.get_monitor_config(config_id)
    if not config:
        return _error('监控配置不存在', 404)
    return jsonify({'success': True, 'config': config})


@api_bp.post('/monitor/configs')
@api_protected
def monitor_config_create():
    payload = request.get_json(silent=True) or {}
    config_data = _monitor_config_from_payload(payload)
    if not config_data['name']:
        return _error('配置名称不能为空')
    try:
        config_id = youtube_monitor.create_monitor_config(config_data)
        return jsonify({
            'success': True,
            'message': f'监控配置 "{config_data["name"]}" 创建成功！',
            'config_id': config_id,
        })
    except Exception as e:
        logger.error('创建监控配置失败: %s', e)
        return _error(f'创建监控配置失败: {e}', 500)


@api_bp.patch('/monitor/configs/<int:config_id>')
@api_protected
def monitor_config_update(config_id):
    config = youtube_monitor.get_monitor_config(config_id)
    if not config:
        return _error('监控配置不存在', 404)
    payload = request.get_json(silent=True) or {}
    config_data = _monitor_config_from_payload(payload)
    if not config_data['name']:
        return _error('配置名称不能为空')
    try:
        youtube_monitor.update_monitor_config(config_id, config_data)
        return _ok('监控配置更新成功！')
    except Exception as e:
        logger.error('更新监控配置失败: %s', e)
        return _error(f'更新监控配置失败: {e}', 500)


@api_bp.delete('/monitor/configs/<int:config_id>')
@api_protected
def monitor_config_delete(config_id):
    try:
        config = youtube_monitor.get_monitor_config(config_id)
        if config:
            youtube_monitor.delete_monitor_config(config_id)
            return _ok(f'监控配置 "{config["name"]}" 删除成功！')
        return _error('监控配置不存在', 404)
    except Exception as e:
        logger.error('删除监控配置失败: %s', e)
        return _error(f'删除监控配置失败: {e}', 500)


@api_bp.post('/monitor/configs/<int:config_id>/run')
@api_protected
def monitor_run(config_id):
    operation_id, config, error_message = _app()._start_monitor_run_operation(config_id)
    if error_message:
        return _error(error_message, 404)
    if not config:
        return _error('监控配置不存在', 404)
    return jsonify({
        'success': True,
        'message': f"监控已在后台开始执行：{config['name']}",
        'operation_id': operation_id,
        'config_id': config_id,
    })


@api_bp.get('/monitor/run-status/<operation_id>')
@api_protected
def monitor_run_status(operation_id):
    progress = _app()._get_monitor_run_progress(operation_id)
    if not progress:
        return jsonify({
            'found': False, 'config_id': None, 'message': '', 'detail': '',
            'done': True, 'level': 'error', 'success': False,
        })
    return jsonify({
        'found': True,
        'config_id': progress.get('config_id'),
        'message': progress.get('message', ''),
        'detail': progress.get('detail', ''),
        'done': progress.get('done', False),
        'level': progress.get('level', 'info'),
        'success': progress.get('success'),
    })


@api_bp.get('/monitor/configs/<int:config_id>/history')
@api_protected
def monitor_history(config_id):
    config = youtube_monitor.get_monitor_config(config_id)
    if not config:
        return _error('监控配置不存在', 404)
    history = youtube_monitor.get_monitor_history(config_id, limit=200)

    stats = {'total_records': len(history), 'added_to_tasks': 0, 'avg_views': 0, 'avg_likes': 0}
    if history:
        total_views = 0
        total_likes = 0
        for record in history:
            if record.get('added_to_tasks'):
                stats['added_to_tasks'] += 1
            total_views += record.get('view_count', 0)
            total_likes += record.get('like_count', 0)
        stats['avg_views'] = int(total_views / len(history))
        stats['avg_likes'] = int(total_likes / len(history))

    return jsonify({'success': True, 'history': history, 'config': config, 'stats': stats})


@api_bp.post('/monitor/add_to_tasks')
@api_protected
def monitor_add_to_tasks():
    payload = request.get_json(silent=True) or {}
    video_id = payload.get('video_id')
    config_id = payload.get('config_id')
    if not video_id or not config_id:
        return _error('参数不完整')
    try:
        config_id_int = int(config_id)
    except (TypeError, ValueError):
        return _error('config_id 无效')
    success, message = youtube_monitor.add_video_to_tasks_manually(video_id, config_id_int)
    if success:
        return _ok(message)
    return _error(message)


@api_bp.post('/monitor/configs/<int:config_id>/history/clear')
@api_protected
def monitor_clear_history(config_id):
    youtube_monitor.clear_monitor_history(config_id)
    return _ok('历史记录已清空')


@api_bp.post('/monitor/history/clear_all')
@api_protected
def monitor_clear_all_history():
    youtube_monitor.clear_all_monitor_history()
    return _ok('所有历史记录已清空')


@api_bp.post('/monitor/restore_configs')
@api_protected
def monitor_restore_configs():
    youtube_monitor.restore_configs_from_files_manually()
    return _ok('已恢复默认监控配置')


@api_bp.post('/monitor/configs/<int:config_id>/reset_offset')
@api_protected
def monitor_reset_offset(config_id):
    youtube_monitor.reset_historical_offset(config_id)
    return _ok('已重置频道监控的视频偏移量')
