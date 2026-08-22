#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试 VideoLingo 风格字幕翻译增强（上下文感知 / 术语表 / 两阶段开关）。

覆盖：
- _to_bool 布尔值安全转换
- get_glossary_prompt 术语表 prompt 生成（目标语言注入）
- LLMRequester._parse_glossary_json 容错解析（含字典/JSON 文本/脏数据）
- LLMRequester._build_structured_user_prompt 上下文与术语注入
"""

import json
import unittest

from modules.subtitle_translator import (
    LLMRequester,
    TranslationConfig,
    SubtitleTranslator,
    _to_bool,
)
from modules.prompt_manager import get_glossary_prompt


class ToBoolTests(unittest.TestCase):
    def test_bool_identity(self):
        self.assertTrue(_to_bool(True))
        self.assertFalse(_to_bool(False))

    def test_str_true_variants(self):
        for v in ("true", "1", "on", "yes", "True", " ON "):
            self.assertTrue(_to_bool(v))

    def test_str_false_and_none(self):
        for v in ("", "false", "0", "off", "no", None):
            self.assertFalse(_to_bool(v))

    def test_numeric(self):
        self.assertTrue(_to_bool(1))
        self.assertFalse(_to_bool(0))


class GlossaryPromptTests(unittest.TestCase):
    def test_prompt_includes_target_language(self):
        for lang in ("zh", "en"):
            p = get_glossary_prompt(lang)
            self.assertIn(lang, p)

    def test_prompt_has_summary_and_terms_json(self):
        p = get_glossary_prompt("zh")
        self.assertIn("summary", p)
        self.assertIn("terms", p)
        self.assertIn('"src"', p)
        self.assertIn('"tgt"', p)
        self.assertIn('"note"', p)

    def test_prompt_contains_less_than_fifteen(self):
        p = get_glossary_prompt("zh")
        self.assertIn("15", p)


class ParseGlossaryJsonTests(unittest.TestCase):
    def _requester(self):
        return LLMRequester({"OPENAI_API_KEY": "test"}, "glossary-test")

    def test_valid_dict(self):
        raw = {"summary": "主题", "terms": [{"src": "CNN", "tgt": "卷积神经网络", "note": "注"}]}
        out = self._requester()._parse_glossary_json(raw)
        self.assertEqual(out["summary"], "主题")
        self.assertEqual(len(out["terms"]), 1)
        self.assertEqual(out["terms"][0]["src"], "CNN")

    def test_valid_json_text(self):
        raw = '{"summary":"s","terms":[{"src":"a","tgt":"b","note":"c"}]}'
        out = self._requester()._parse_glossary_json(raw)
        self.assertEqual(out["summary"], "s")
        self.assertEqual(out["terms"][0]["tgt"], "b")

    def test_filters_empty_terms(self):
        raw = {
            "summary": "s",
            "terms": [{"src": "a", "tgt": "b"}, {"src": "", "tgt": ""}, {"src": "x", "tgt": ""}],
        }
        out = self._requester()._parse_glossary_json(raw)
        self.assertEqual(len(out["terms"]), 1)
        self.assertEqual(out["terms"][0]["src"], "a")

    def test_invalid_returns_empty(self):
        self.assertEqual(self._requester()._parse_glossary_json(None), {})
        self.assertEqual(self._requester()._parse_glossary_json("not json"), {})
        self.assertEqual(self._requester()._parse_glossary_json([]), {})

    def test_terms_not_list_returns_empty_terms(self):
        out = self._requester()._parse_glossary_json({"summary": "s", "terms": "bad"})
        self.assertEqual(out["terms"], [])


class BuildUserPromptTests(unittest.TestCase):
    def _requester(self):
        return LLMRequester({"OPENAI_API_KEY": "test"}, "prompt-test")

    def test_basic_no_context(self):
        p = self._requester()._build_structured_user_prompt(["hello", "world"])
        data = json.loads(p)
        self.assertEqual(data["texts"], ["hello", "world"])
        self.assertNotIn("previous_context", data)
        self.assertNotIn("terminology", data)

    def test_context_and_terms_injected(self):
        p = self._requester()._build_structured_user_prompt(
            ["hi"],
            previous_text=["prev1", "prev2"],
            after_text=["next1"],
            summary="主题摘要",
            terms=[{"src": "CNN", "tgt": "卷积神经网络", "note": "n"}],
        )
        data = json.loads(p)
        self.assertEqual(data["previous_context"], ["prev1", "prev2"])
        self.assertEqual(data["subsequent_context"], ["next1"])
        self.assertEqual(data["summary"], "主题摘要")
        self.assertEqual(data["terminology"][0]["src"], "CNN")
        self.assertEqual(data["requires" if "requires" in data else "requirements"]["no_cross_item_carryover"], True)

    def test_reflect_pass_renames_task(self):
        p = self._requester()._build_structured_user_prompt(
            ["hi"], is_reflect_pass=True
        )
        data = json.loads(p)
        self.assertEqual(data["task"], "subtitle_refinement")


class TranslationConfigTests(unittest.TestCase):
    def test_defaults_are_false(self):
        cfg = TranslationConfig()
        self.assertFalse(cfg.context_enabled)
        self.assertFalse(cfg.glossary_enabled)
        self.assertFalse(cfg.reflect_translate)


if __name__ == "__main__":
    unittest.main()
