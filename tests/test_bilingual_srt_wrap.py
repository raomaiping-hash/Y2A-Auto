#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import tempfile
import unittest

from modules.bilingual_subtitles import build_bilingual_srt, wrap_text_by_pixels


def _write_srt(path, cues):
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f"00:00:{start:02d},000 --> 00:00:{end:02d},000")
        lines.append(text)
        lines.append('')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines).strip() + '\n')


class BilingualSrtWrapTests(unittest.TestCase):
    """上传的双语 .srt 应与烧录共用同一折行实现，长字幕不溢出。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.src = os.path.join(self.tmp, 'src.srt')
        self.tr = os.path.join(self.tmp, 'tr.srt')
        self.out = os.path.join(self.tmp, 'bilingual.srt')
        self.long_cjk = '用各种不同的登机方式进入各个舱位这样就不需要排队我们就可以快速登机了'

    def test_long_line_wrapped_when_video_width_given(self):
        _write_srt(self.src, [(1, 5, 'Using a range of boarding methods to each cabin')])
        _write_srt(self.tr, [(1, 5, self.long_cjk)])
        build_bilingual_srt(self.src, self.tr, self.out, video_width=1920, zh_size=60, en_size=32)
        text = open(self.out, encoding='utf-8').read()
        # 中文长句应被折行（含 \\N / 多行），而非单行溢出
        self.assertIn('\\N', text, '上传的双语 SRT 中文长句应折行')

    def test_no_wrap_when_video_width_missing(self):
        _write_srt(self.src, [(1, 5, 'short english')])
        _write_srt(self.tr, [(1, 5, self.long_cjk)])
        build_bilingual_srt(self.src, self.tr, self.out)
        text = open(self.out, encoding='utf-8').read()
        # 未提供视频宽度时保持原样（单行），不做折行——向后兼容
        self.assertNotIn('\\N', text, '未提供宽时应保持单行')
        self.assertIn(self.long_cjk, text)

    def test_source_is_zh_single_language(self):
        # 源即中文：直接复制源字幕，不折行不加英文
        _write_srt(self.src, [(1, 5, '短句')])
        build_bilingual_srt(self.src, None, self.out, source_is_zh=True, video_width=1920)
        text = open(self.out, encoding='utf-8').read()
        self.assertIn('短句', text)


if __name__ == '__main__':
    unittest.main()
