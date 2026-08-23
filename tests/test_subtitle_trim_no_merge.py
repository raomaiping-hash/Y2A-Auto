#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""字幕-时长对齐（trim）回归测试：配音场景不得合并短句成大段长字幕。"""

import unittest
import logging

from modules.subtitle_translator import SubtitleTranslator


def _mk_translator(min_subtitle_duration=0.0):
    t = SubtitleTranslator.__new__(SubtitleTranslator)
    t.min_subtitle_duration = min_subtitle_duration
    t.config = type('Cfg', (), {'min_subtitle_duration': min_subtitle_duration})()
    t.logger = logging.getLogger('test_subtitle_trim')
    return t


class TrimOverlongCuesTests(unittest.TestCase):
    def _cues(self, pairs):
        return [
            {'start': f'00:00:{int(s):02d},000', 'end': f'00:00:{int(e):02d},000', 'text': t}
            for s, e, t in pairs
        ]

    def test_dubbing_mode_does_not_merge_short_cues(self):
        """配音场景（min=0）：短句不合并，逐条保留，不产生大段长字幕。"""
        t = _mk_translator(0.0)
        cues = self._cues([
            (0, 2.2, '全球每年吃的大米比所有人还重'),
            (2.2, 4.4, '这种作物提供大量能量'),
            (4.4, 6.6, '韩式拌饭很受欢迎'),
        ])
        out = t._trim_overlong_cues(cues, min_subtitle_duration=0.0)
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]['text'], '全球每年吃的大米比所有人还重')

    def test_reading_mode_merges_short_cues(self):
        """纯字幕阅读场景（min=2.5）：过短句合并到相邻。"""
        t = _mk_translator(2.5)
        cues = self._cues([
            (0, 2.0, '短句A'),
            (2.0, 4.0, '短句B'),
            (4.0, 6.0, '短句C'),
        ])
        out = t._trim_overlong_cues(cues, min_subtitle_duration=2.5)
        # A(2.0<2.5) 与 B 紧邻合并；B 并入后 A 窗口变 0-4.0
        self.assertLess(len(out), 3)

    def test_dubbing_mode_overlong_uses_trim_not_merge(self):
        """配音场景超窗句：LLM 修剪当前句，而非拼接后续句成大段。"""
        t = _mk_translator(0.0)
        # 单句 20 字，窗口只有 2 秒（预计朗读 20*0.21=4.2s > 2*1.2=2.4s，超窗）
        cues = self._cues([
            (0, 2.0, '这是一句非常非常长的字幕文本超过了窗口能容纳的长度上限'),
            (2.0, 4.0, '第二句'),
        ])
        # 打桩 _llm_trim_text 返回短文本，避免真实 LLM 调用
        t._llm_trim_text = lambda text, win: '修剪后的短句'
        out = t._trim_overlong_cues(cues, min_subtitle_duration=0.0)
        self.assertEqual(len(out), 2)  # 不合并，仍是两句
        self.assertEqual(out[0]['text'], '修剪后的短句')
        self.assertEqual(out[1]['text'], '第二句')


if __name__ == '__main__':
    unittest.main()
