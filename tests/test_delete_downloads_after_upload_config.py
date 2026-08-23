import pathlib
import unittest

from modules.config_manager import DEFAULT_CONFIG, _infer_config_field_types


ROOT = pathlib.Path(__file__).resolve().parents[1]


class DeleteDownloadsAfterUploadConfigTests(unittest.TestCase):
    def test_option_is_registered_and_disabled_by_default(self):
        self.assertIn('DELETE_DOWNLOAD_FILES_AFTER_UPLOAD', DEFAULT_CONFIG)
        self.assertFalse(DEFAULT_CONFIG['DELETE_DOWNLOAD_FILES_AFTER_UPLOAD'])

    def test_settings_page_exposes_option_and_save_handler_tracks_checkbox(self):
        view = (ROOT / 'frontend' / 'src' / 'views' / 'SettingsView.vue').read_text(encoding='utf-8')

        # 新版 SPA 设置页的字段列表中暴露该选项
        self.assertIn('DELETE_DOWNLOAD_FILES_AFTER_UPLOAD', view)
        self.assertIn('上传后删除下载文件', view)
        # 后端设置保存处理器的复选框类型单一来源：该字段是 DEFAULT_CONFIG 中的 bool
        # 由 _infer_config_field_types 推导为 checkbox（而非硬编码字段表），行为保留。
        checkbox_keys, _, _ = _infer_config_field_types()
        self.assertIn('DELETE_DOWNLOAD_FILES_AFTER_UPLOAD', checkbox_keys)

    def test_upload_cleanup_is_guarded_by_option_for_both_platform_handlers(self):
        source = (ROOT / 'modules' / 'task_manager.py').read_text(encoding='utf-8')
        option_guard = "self.config.get('DELETE_DOWNLOAD_FILES_AFTER_UPLOAD', False)"

        self.assertEqual(source.count(option_guard), 2)
        self.assertIn('and _get_task_upload_target(task) == UPLOAD_TARGET_ACFUN', source)
        self.assertIn('and _get_task_upload_target(task) != UPLOAD_TARGET_ACFUN', source)


if __name__ == '__main__':
    unittest.main()
