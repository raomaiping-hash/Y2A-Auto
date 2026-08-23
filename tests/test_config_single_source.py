#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from modules import config_manager as cm
from modules.config_manager import (
    DEFAULT_CONFIG,
    _infer_config_field_types,
    get_config_default,
)


class ConfigSingleSourceTests(unittest.TestCase):
    """验证配置默认值单一来源：DEFAULT_CONFIG 为权威，无互相矛盾的硬编码回退值。"""

    def test_conflicting_keys_match_documented_defaults(self):
        """这些键此前在多个模块里有互相矛盾的默认值，现在应与 DEFAULT_CONFIG 一致。"""
        self.assertEqual(DEFAULT_CONFIG['SUBTITLE_MAX_LINE_LENGTH'], 42)
        self.assertEqual(DEFAULT_CONFIG['SUBTITLE_MAX_LINES'], 2)
        self.assertEqual(DEFAULT_CONFIG['SUBTITLE_BATCH_SIZE'], 3)
        self.assertEqual(DEFAULT_CONFIG['SUBTITLE_RETRY_DELAY'], 2)
        self.assertEqual(DEFAULT_CONFIG['LOG_CLEANUP_HOURS'], 72)
        self.assertEqual(DEFAULT_CONFIG['SUBTITLE_QC_THRESHOLD'], 0.60)

    def test_speech_pipeline_defaults_do_not_conflict(self):
        """speech_pipeline_settings 注入的值不得与 DEFAULT_CONFIG 冲突。"""
        from modules import speech_pipeline_settings as sps
        for key, value in sps.SPEECH_PIPELINE_DEFAULTS.items():
            if key in DEFAULT_CONFIG and isinstance(DEFAULT_CONFIG[key], type(value)):
                self.assertEqual(
                    DEFAULT_CONFIG[key], value,
                    f"SPEECH_PIPELINE_DEFAULTS[{key}] 与 DEFAULT_CONFIG 冲突",
                )

    def test_infer_field_types_classifies_correctly(self):
        checkbox, ints, floats = _infer_config_field_types()
        self.assertIn('TRANSLATE_TITLE', checkbox)
        self.assertIn('AUTO_MODE_ENABLED', checkbox)
        self.assertIn('password_protection_enabled', checkbox)
        self.assertIn('MAX_CONCURRENT_TASKS', ints)
        self.assertIn('LOGIN_SESSION_TIMEOUT_MINUTES', ints)
        self.assertIn('SUBTITLE_TIME_OFFSET_S', floats)
        self.assertIn('SUBTITLE_QC_THRESHOLD', floats)

    def test_no_type_mixing(self):
        checkbox, ints, floats = _infer_config_field_types()
        self.assertEqual(set(checkbox) & set(ints), set())
        self.assertEqual(set(checkbox) & set(floats), set())
        self.assertEqual(set(ints) & set(floats), set())

    def test_get_config_default_returns_authoritative_value(self):
        """转换失败时的回退默认值应取自 DEFAULT_CONFIG。"""
        self.assertEqual(get_config_default('SUBTITLE_BATCH_SIZE'), 3)
        self.assertEqual(get_config_default('SUBTITLE_RETRY_DELAY'), 2)
        self.assertEqual(get_config_default('LOG_CLEANUP_HOURS'), 72)
        self.assertEqual(get_config_default('SUBTITLE_QC_THRESHOLD'), 0.60)
        self.assertIsNone(get_config_default('__not_a_real_key__'))


if __name__ == '__main__':
    unittest.main()
