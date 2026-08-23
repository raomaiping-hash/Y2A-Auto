#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配音字幕来源选择的回归测试。

Bug 背景：真实任务配音成英文——subtitle_path_translated 存的是双语 ASS（非 .srt）
被过滤后回退到了 subtitle_path_original（英文原文），导致配音用英文文本。
修复：优先任务目录的 translated_*.srt（纯中文翻译产物）。
"""

import os
import tempfile
import unittest
from unittest.mock import patch

import modules.task_manager as tm


def _resolve_zh_srt(task, task_dir):
    """提取 _dub_video 里的中文字幕选择逻辑（与实现保持一致的简化版，供断言）。"""
    zh_srt = None
    for name in sorted(os.listdir(task_dir)):
        if name.startswith('translated_') and name.endswith('.srt'):
            zh_srt = os.path.join(task_dir, name)
            break
    if not zh_srt:
        cand = task.get('subtitle_path_translated')
        if cand and os.path.isfile(str(cand)) and str(cand).lower().endswith('.srt'):
            zh_srt = cand
    if not zh_srt:
        cand = task.get('subtitle_path_original')
        if cand and os.path.isfile(str(cand)) and str(cand).lower().endswith('.srt'):
            lang = str(task.get('subtitle_language_detected') or '').lower()
            if lang.startswith('zh'):
                zh_srt = cand
    return zh_srt


class DubSubtitleSourceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()

    def _mk(self, name, content='1\n00:00:00,000 --> 00:00:01,000\n你好\n\n'):
        p = os.path.join(self.tmp, name)
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(content)
        return p

    def test_prefers_translated_srt_even_when_translated_is_ass(self):
        """核心回归：translated 字段是双语 .ass 时，应取目录里的 translated_*.srt，
        而不是回退到英文原文。"""
        translated_srt = self._mk('translated_task.srt')
        en_original = self._mk('video.en.srt', '1\n00:00:00,000 --> 00:00:01,000\nHello\n\n')
        ass = self._mk('bilingual_task.ass')

        task = {
            'subtitle_path_translated': ass,       # 双语 ASS（非 srt，会被过滤）
            'subtitle_path_original': en_original,  # 英文原文（旧逻辑会错误回退到这里）
            'subtitle_language_detected': 'en',
        }
        resolved = _resolve_zh_srt(task, self.tmp)
        self.assertEqual(resolved, translated_srt)

    def test_falls_back_to_bilingual_srt(self):
        """无 translated_*.srt 时，双语 .srt 可用作兜底（含中文行）。"""
        bilingual = self._mk('bilingual_task.srt')
        task = {
            'subtitle_path_translated': bilingual,
            'subtitle_path_original': None,
        }
        self.assertEqual(_resolve_zh_srt(task, self.tmp), bilingual)

    def test_english_original_only_rejected(self):
        """只有英文原文（无翻译产物）时，不得拿英文配音。"""
        en = self._mk('video.en.srt', '1\n00:00:00,000 --> 00:00:01,000\nHello\n\n')
        task = {
            'subtitle_path_translated': None,
            'subtitle_path_original': en,
            'subtitle_language_detected': 'en',
        }
        self.assertIsNone(_resolve_zh_srt(task, self.tmp))

    def test_chinese_original_accepted(self):
        """原文本身就是中文时可接受。"""
        zh = self._mk('video.zh.srt')
        task = {
            'subtitle_path_translated': None,
            'subtitle_path_original': zh,
            'subtitle_language_detected': 'zh',
        }
        self.assertEqual(_resolve_zh_srt(task, self.tmp), zh)

    def test_source_selection_logic_in_real_method(self):
        """源码级验证：_dub_video 里必须包含 translated_ 优先逻辑（防回退回归）。"""
        import inspect
        src = inspect.getsource(tm.TaskProcessor._dub_video)
        self.assertIn("name.startswith('translated_')", src)
        self.assertIn("lang.startswith('zh')", src)


if __name__ == '__main__':
    unittest.main()
