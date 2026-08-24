#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""配音文本规范化（数字→中文）测试。

用户反馈：字幕"10000"配音读成"一万"、字幕"11%"读成"百分之十一"、
字幕"25倍"读成"二十五倍"——字幕与配音不一致源于数字未汉字化。
修复：配音前把数字/百分比转成标准中文汉字，Fish 读得准且与字幕一致。
"""

import unittest

from modules.dubbing import _int_to_cn, _num_to_cn, _normalize_dub_text


class IntToCnTests(unittest.TestCase):
    def test_common_integers(self):
        cases = {
            0: '零', 1: '一', 10: '十', 11: '十一', 21: '二十一',
            25: '二十五', 100: '一百', 110: '一百一十',
            1000: '一千', 10000: '一万', 25: '二十五',
        }
        for n, expect in cases.items():
            self.assertEqual(_int_to_cn(n), expect, f'{n} -> {_int_to_cn(n)}')

    def test_no_leading_yi_for_teen(self):
        # 口语：10~19 不读"一十/一十一"
        self.assertEqual(_int_to_cn(11), '十一')
        self.assertEqual(_int_to_cn(15), '十五')
        self.assertEqual(_int_to_cn(19), '十九')


class NumToCnTests(unittest.TestCase):
    def test_wans(self):
        self.assertEqual(_normalize_dub_text('距今10000多年前'), '距今一万多年前')

    def test_percent(self):
        self.assertEqual(_normalize_dub_text('占11%'), '占百分之十一')

    def test_units(self):
        self.assertEqual(_normalize_dub_text('是二氧化碳的25倍'), '是二氧化碳的二十五倍')

    def test_plain_text_unchanged(self):
        self.assertEqual(_normalize_dub_text('全球一成一的农田'), '全球一成一的农田')

    def test_chemical_terms_preserved(self):
        self.assertEqual(_normalize_dub_text('打嗝排甲烷'), '打嗝排甲烷')
        self.assertEqual(_normalize_dub_text('举办宴会'), '举办宴会')


if __name__ == '__main__':
    unittest.main()
