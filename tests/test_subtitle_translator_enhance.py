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
        self.assertEqual(cfg.cue_max_chars, 22)


class RemoveCjkSpacesTests(unittest.TestCase):
    def test_removes_spaces_between_cjk(self):
        from modules.subtitle_translator import SubtitleWriter
        self.assertEqual(SubtitleWriter._remove_cjk_spaces('经 过 延误'), '经过延误')
        self.assertEqual(SubtitleWriter._remove_cjk_spaces('数学家们 研究这个问题'), '数学家们研究这个问题')

    def test_keeps_latin_word_spaces(self):
        from modules.subtitle_translator import SubtitleWriter
        self.assertEqual(SubtitleWriter._remove_cjk_spaces('空客 A320 飞机'), '空客 A320 飞机')
        self.assertEqual(SubtitleWriter._remove_cjk_spaces('the size of space'), 'the size of space')


class SplitLongCueTests(unittest.TestCase):
    def test_short_text_unchanged(self):
        from modules.subtitle_translator import SubtitleWriter
        self.assertEqual(SubtitleWriter._split_long_cue('短字幕', 22), ['短字幕'])

    def test_long_text_splits_at_word_boundary(self):
        from modules.subtitle_translator import SubtitleWriter
        segs = SubtitleWriter._split_long_cue('经过数小时延误 你的红眼航班终于开始登机 期待已久的午睡眼看就要实现 可就在', 22)
        # 按空格拆成完整短句；<=3 字残片"可就在"丢弃，不并入不截断
        self.assertEqual(segs, [
            '经过数小时延误',
            '你的红眼航班终于开始登机',
            '期待已久的午睡眼看就要实现',
        ])

    def test_tiny_fragment_dropped(self):
        from modules.subtitle_translator import SubtitleWriter
        segs = SubtitleWriter._split_long_cue('这是一个很长的句子用来测试拆分会把最后一个很短的尾段并到前面去 好', 22)
        # 尾段"好"1字不是完整句，丢弃；无空格超长句均分硬切为两条
        self.assertEqual(len(segs), 2)
        self.assertTrue(all(len(s) > 3 for s in segs))
        self.assertEqual(''.join(segs), '这是一个很长的句子用来测试拆分会把最后一个很短的尾段并到前面去')

    def test_full_sentence_never_truncated(self):
        from modules.subtitle_translator import SubtitleWriter
        # 每个片段都是完整短句，绝不在句中断开
        segs = SubtitleWriter._split_long_cue('空客A320 每个人都带随身行李 后到前登机法需要多长时间', 22)
        self.assertEqual(segs, ['空客A320', '每个人都带随身行李', '后到前登机法需要多长时间'])


class PrepareCuesTests(unittest.TestCase):
    def test_time_allocated_by_char_ratio(self):
        from modules.subtitle_translator import SubtitleWriter, SubtitleItem
        items = [SubtitleItem(
            index=1,
            start_time='00:00:00,000',
            end_time='00:00:10,000',
            source_text='src',
            translated_text='一二三四五六七八九十 甲乙丙丁戊己庚辛壬癸',
        )]
        cues = SubtitleWriter._prepare_cues(items, translated=True, max_chars=12)
        # 20 字 > 12 → 拆成两条，各 10 字 → 时间各半
        self.assertEqual(len(cues), 2)
        t0 = SubtitleWriter._ts_to_seconds(cues[0]['start'])
        t1 = SubtitleWriter._ts_to_seconds(cues[0]['end'])
        t2 = SubtitleWriter._ts_to_seconds(cues[1]['start'])
        t3 = SubtitleWriter._ts_to_seconds(cues[1]['end'])
        self.assertAlmostEqual(t0, 0.0)
        self.assertAlmostEqual(t2, 5.0, delta=0.05)
        self.assertAlmostEqual(t3, 10.0, delta=0.05)
        self.assertAlmostEqual(t1, t2, delta=0.05)
        # 无 CJK 间空格
        self.assertNotIn(' ', cues[0]['text'])
        self.assertNotIn(' ', cues[1]['text'])

    def test_no_split_within_max_chars(self):
        from modules.subtitle_translator import SubtitleWriter, SubtitleItem
        items = [SubtitleItem(
            index=1,
            start_time='00:00:00,000',
            end_time='00:00:05,000',
            source_text='src',
            translated_text='这是一条 短字幕',
        )]
        cues = SubtitleWriter._prepare_cues(items, translated=True, max_chars=22)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]['text'], '这是一条短字幕')


if __name__ == "__main__":
    unittest.main()
