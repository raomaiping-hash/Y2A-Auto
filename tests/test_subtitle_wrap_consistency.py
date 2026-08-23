#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from modules.bilingual_subtitles import wrap_text_by_pixels, _wrap_text_by_pixels


class SubtitleWrapConsistencyTests(unittest.TestCase):
    """锁定双语/单语烧录同一折行契约：超长字幕必须被限定在有限行数内，不溢出画面。"""

    LONG_CJK = '用各种不同的登机方式进入各个舱位这样就不需要排队我们就能更快地登机并且能节省大量时间'
    LONG_LATIN = (
        'Using a range of different boarding methods to enter each cabin '
        'so that we do not need to queue and can board the aircraft faster'
    )

    def test_public_entry_matches_private_impl(self):
        """公开入口 wrap_text_by_pixels 应等价于内部 _wrap_text_by_pixels。"""
        self.assertEqual(
            wrap_text_by_pixels(self.LONG_CJK, 60, 1920, 60),
            _wrap_text_by_pixels(self.LONG_CJK, 60, 1920, 60),
        )

    def test_long_cjk_is_wrapped_to_bounded_lines(self):
        # 1920 宽、60 号字：45+ 字应折成多行，且行数有上限
        result = _wrap_text_by_pixels(self.LONG_CJK, 60, 1920, 60)
        lines = result.split(r'\N')
        self.assertGreater(len(lines), 1, '长中文应被折行，不应单行溢出')
        self.assertLessEqual(len(lines), 3, '折行行数不得超过上限')

    def test_long_latin_is_wrapped_to_bounded_lines(self):
        result = _wrap_text_by_pixels(self.LONG_LATIN, 60, 1920, 60)
        lines = result.split(r'\N')
        self.assertGreater(len(lines), 1, '长英文应按词折行')
        self.assertLessEqual(len(lines), 3)

    def test_short_text_not_wrapped(self):
        self.assertEqual(_wrap_text_by_pixels('你好世界', 60, 1920, 60), '你好世界')

    def test_portrait_narrow_width_forces_wrap(self):
        # 竖屏窄画面：同一段文字更容易溢出，应折行
        result = _wrap_text_by_pixels(self.LONG_CJK, 60, 720, 60)
        lines = result.split(r'\N')
        self.assertGreater(len(lines), 1)
        self.assertLessEqual(len(lines), 3)

    def test_empty_or_whitespace_passthrough(self):
        self.assertEqual(_wrap_text_by_pixels('', 60, 1920, 60), '')
        # 纯空白会被 trim 掉（.strip()），仅含空白应返回空串
        self.assertEqual(_wrap_text_by_pixels('   ', 60, 1920, 60), '')

    def test_no_single_line_exceeds_budget_heuristic(self):
        """任何一行都不应超过按可用宽度估算的单行预算（防止溢出）。"""
        for tex in (self.LONG_CJK, self.LONG_LATIN):
            for width in (1280, 1920):
                result = _wrap_text_by_pixels(tex, 60, width, 60)
                budget = max(2, int(((width - 2 * 60) * 0.90) / 60))
                for line in result.split(r'\N'):
                    # 估算宽度单位（CJK 全宽 1，拉丁 0.5），允许少量舍入容差
                    units = sum(1.0 if 0x2E80 <= ord(ch) <= 0x9FFF else 0.5 for ch in line)
                    self.assertLessEqual(units, budget + 1.5, f'行宽超出预算: {line!r} (units={units}, budget={budget})')


if __name__ == '__main__':
    unittest.main()
