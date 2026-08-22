"""modules/api_v1.py JSON API 层专项测试（数据层全部 patch，不落真实 DB）。"""

import json
import unittest
from unittest.mock import Mock, patch

import app as web_app
from modules import api_v1 as av


def _csrf(client):
    """走真实会话流程获取 CSRF token（同时种下 cookie）。"""
    resp = client.get('/api/v1/auth/session')
    return resp.get_json()['csrf_token']


class ApiV1AuthAndCsrfTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config['TESTING'] = True
        self.client = web_app.app.test_client()

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False})
    @patch.object(web_app, '_load_security_state', return_value={})
    def test_session_issues_csrf_token(self, *mocks):
        resp = self.client.get('/api/v1/auth/session')
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data['success'])
        self.assertTrue(data['authenticated'])
        self.assertGreater(len(data['csrf_token']), 16)

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False})
    def test_mutating_request_without_csrf_is_rejected(self, *mocks):
        resp = self.client.post('/api/v1/tasks', json={'url': 'https://www.youtube.com/watch?v=abc'})
        self.assertEqual(resp.status_code, 403)
        self.assertIn('安全校验失败', resp.get_json().get('message', ''))

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False})
    @patch.object(av, 'get_tasks_paginated',
                  return_value={'tasks': [], 'total': 0, 'total_pages': 0, 'page': 1, 'per_page': 20})
    def test_tasks_list_with_csrf_allowed(self, *mocks):
        token = _csrf(self.client)
        resp = self.client.get('/api/v1/tasks')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('tasks', resp.get_json())

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False})
    @patch.object(av, 'get_tasks_paginated',
                  return_value={'tasks': [], 'total': 0, 'total_pages': 0, 'page': 1, 'per_page': 20})
    def test_tasks_search_query_propagates_as_search(self, pag_mock, *mocks):
        token = _csrf(self.client)
        resp = self.client.get('/api/v1/tasks?q=dQw4w9WgXcQ')
        self.assertEqual(resp.status_code, 200)
        pag_mock.assert_called_once()
        kwargs = pag_mock.call_args
        self.assertEqual(kwargs.kwargs['search'], 'dQw4w9WgXcQ')
        # get_tasks_paginated 的搜索条件含 youtube_url（按链接检索）
        import inspect
        src = inspect.getsource(__import__('modules.task_manager', fromlist=['get_tasks_paginated']).get_tasks_paginated)
        self.assertIn('youtube_url LIKE ?', src)


class ApiV1TaskApiTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config['TESTING'] = True
        self.client = web_app.app.test_client()

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False})
    @patch.object(av, 'add_task', return_value={'id': 'new-task-1'})
    def test_task_create_flow(self, add_mock, *mocks):
        token = _csrf(self.client)
        resp = self.client.post(
            '/api/v1/tasks',
            json={'youtube_url': 'https://www.youtube.com/watch?v=abc'},
            headers={'X-CSRF-Token': token},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()['success'])
        add_mock.assert_called_once()

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False})
    @patch.object(av, 'get_task', return_value={'id': 't1', 'status': av.TASK_STATES['PENDING']})
    @patch.object(av, 'start_task', return_value=True)
    def test_task_start(self, start_mock, *mocks):
        token = _csrf(self.client)
        resp = self.client.post('/api/v1/tasks/t1/start', headers={'X-CSRF-Token': token})
        self.assertEqual(resp.status_code, 200)
        start_mock.assert_called_once_with('t1', {'password_protection_enabled': False})


class ApiV1SettingsFlowTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config['TESTING'] = True
        self.client = web_app.app.test_client()

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False})
    @patch.object(av, '_app')
    def test_settings_save_starts_async_operation(self, app_mock, *mocks):
        app = app_mock.return_value
        app._load_security_state.return_value = {}
        app._extract_settings_uploads.return_value = {}
        app._update_settings_save_progress.return_value = None
        token = _csrf(self.client)
        resp = self.client.post(
            '/api/v1/settings',
            data={'OPENAI_API_KEY': 'sk-test'},
            headers={'X-CSRF-Token': token},
        )
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(data['success'])
        self.assertIn('operation_id', data)
        # 线程已启动（daemon 线程正常创建，不 join 直接返回）
        app._run_settings_save_operation.assert_called_once()


class ApiV1HealthTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config['TESTING'] = True
        self.client = web_app.app.test_client()

    @patch('modules.ffmpeg_manager.get_ffmpeg_path', return_value='/opt/ffmpeg')
    @patch('modules.ffmpeg_manager.is_ffmpeg_usable', return_value=True)
    @patch('modules.ffmpeg_manager.get_ffprobe_path', return_value='/opt/ffprobe')
    def test_system_health_includes_runtime_tools(self, *mocks):
        resp = self.client.get('/system_health')
        data = resp.get_json()
        tools = data['runtime_tools']
        self.assertEqual(tools['ffmpeg']['status'], 'ok')
        self.assertEqual(tools['ffmpeg']['path'], '/opt/ffmpeg')
        self.assertEqual(tools['ffprobe']['status'], 'ok')
        self.assertIn('asr', tools)
        self.assertIn('tts', tools)
        self.assertIn('vad', tools)
        self.assertIn('disk', tools)


class ApiV1TtsTestEndpointTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config['TESTING'] = True
        self.client = web_app.app.test_client()

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False, 'TTS_DUB_API_KEY': ''})
    def test_tts_test_without_key_returns_400(self, *mocks):
        token = _csrf(self.client)
        resp = self.client.post(
            '/api/v1/settings/tts/test',
            json={'text': '测试'},
            headers={'X-CSRF-Token': token},
        )
        self.assertEqual(resp.status_code, 400)
        self.assertIn('TTS_DUB_API_KEY', resp.get_json()['message'])

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False, 'TTS_DUB_API_KEY': 'k'})
    def test_voices_endpoint_normalizes_and_skips_missing_id(self, *mocks):
        fake = Mock()
        fake.status_code = 200
        fake.json.return_value = {
            'total': 2,
            'has_more': True,
            'items': [
                {'_id': 'abc123', 'title': 'Voice A', 'languages': ['zh'], 'tags': ['female'], 'state': 'trained'},
                {'title': 'No ID skip me'},
            ],
        }
        token = _csrf(self.client)
        with patch.object(av.httpx, 'get', return_value=fake) as get_mock:
            resp = self.client.get('/api/v1/settings/tts/voices?page_size=10', headers={'X-CSRF-Token': token})
        data = resp.get_json()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['id'], 'abc123')
        self.assertEqual(data['items'][0]['title'], 'Voice A')
        self.assertTrue(data['has_more'])
        # 代理请求带鉴权头与分页参数
        headers = get_mock.call_args.kwargs['headers']
        self.assertEqual(headers['Authorization'], 'Bearer k')
        self.assertEqual(get_mock.call_args.kwargs['params']['page_size'], 10)

    def test_voices_without_key_returns_400(self):
        with patch.object(av, 'load_config', return_value={'password_protection_enabled': False, 'TTS_DUB_API_KEY': ''}):
            token = _csrf(self.client)
            resp = self.client.get('/api/v1/settings/tts/voices', headers={'X-CSRF-Token': token})
        self.assertEqual(resp.status_code, 400)


class ApiV1DubEndpointTests(unittest.TestCase):
    def setUp(self):
        web_app.app.config['TESTING'] = True
        self.client = web_app.app.test_client()

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False, 'TTS_DUB_API_KEY': ''})
    @patch.object(av, 'get_task', return_value={'id': 't1', 'status': 'ready_for_upload', 'video_path_local': '/tmp/x.mp4'})
    @patch.object(av.os.path, 'isfile', return_value=True)
    @patch.object(av.os, 'listdir', return_value=['video.zh.srt'])
    @patch.object(av.os.path, 'dirname', return_value='/tmp')
    def test_dub_without_key_returns_400(self, *mocks):
        token = _csrf(self.client)
        resp = self.client.post('/api/v1/tasks/t1/dub', headers={'X-CSRF-Token': token})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('TTS_DUB_API_KEY', resp.get_json()['message'])

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False, 'TTS_DUB_API_KEY': 'k'})
    @patch.object(av, 'get_task', return_value={'id': 't1', 'status': 'ready_for_upload', 'video_path_local': ''})
    def test_dub_without_video_returns_400(self, *mocks):
        token = _csrf(self.client)
        resp = self.client.post('/api/v1/tasks/t1/dub', headers={'X-CSRF-Token': token})
        self.assertEqual(resp.status_code, 400)

    @patch.object(av, 'load_config', return_value={'password_protection_enabled': False, 'TTS_DUB_API_KEY': 'k'})
    @patch.object(av, 'get_task', return_value={'id': 't1', 'status': 'dubbing_audio', 'video_path_local': '/tmp/x.mp4'})
    @patch.object(av.os.path, 'isfile', return_value=True)
    def test_dub_while_dubbing_returns_409(self, *mocks):
        token = _csrf(self.client)
        resp = self.client.post('/api/v1/tasks/t1/dub', headers={'X-CSRF-Token': token})
        self.assertEqual(resp.status_code, 409)


if __name__ == '__main__':
    unittest.main()