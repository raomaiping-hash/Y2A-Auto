"""中英双语字幕生成模块单元测试。"""

import os
import tempfile
import unittest

from modules import bilingual_subtitles as bs


def _write_srt(path, entries):
    """entries: list of (start, end, text)."""
    lines = []
    for i, (s, e, t) in enumerate(entries, 1):
        lines.append(str(i))
        lines.append(f"{bs._fmt_ts(s)} --> {bs._fmt_ts(e)}")
        lines.append(t)
        lines.append('')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines).strip() + '\n')


class BilingualSubtitleTests(unittest.TestCase):
    def test_wrap_text_by_pixels_wraps_long_cjk(self):
        """超长中文应按画面宽度折行，且不破坏内容。"""
        text = '在这视野毫无遮挡的高塔上卡珊德拉目睹了一切的发展度过了漫长而痛苦的岁月'
        wrapped = bs._wrap_text_by_pixels(text, 64, 1920, 60)
        lines = wrapped.split('\\N')
        self.assertGreater(len(lines), 1)
        # 去折行符后内容应与原文一致（无数字token，纯CJK不应插空格）
        self.assertEqual(''.join(lines).replace('…', ''), text)
        self.assertNotIn(' ', wrapped)  # 纯 CJK 折行不插入空格

    def test_wrap_text_by_pixels_caps_lines(self):
        """极长文本应被限制为最多3行并加省略号，绝不无限折行。"""
        text = '啊' * 200
        wrapped = bs._wrap_text_by_pixels(text, 64, 1920, 60)
        lines = wrapped.split('\\N')
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[-1].endswith('…'))

    def test_wrap_text_by_pixels_short_text_untouched(self):
        """短字幕不被折行。"""
        self.assertEqual(bs._wrap_text_by_pixels('你好世界', 64, 1920, 60), '你好世界')

    def test_trans_src_order(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.srt')
            tr = os.path.join(tmp, 'tr.srt')
            out = os.path.join(tmp, 'out.srt')
            _write_srt(src, [(0.0, 5.0, 'After hours of delay your flight is boarding')])
            _write_srt(tr, [(0.0, 2.0, '经过数小时延误'), (2.0, 5.0, '你的航班开始登机')])
            result = bs.build_bilingual_srt(src, tr, out, order='trans_src')
            self.assertTrue(result)
            with open(out, encoding='utf-8') as fh:
                content = fh.read()
            self.assertIn('00:00:00,000 --> 00:00:02,000', content)
            self.assertIn('经过数小时延误', content)
            # 英文按时间比例切成片段，中文在上（trans_src）
            self.assertIn('After hours of', content)
            self.assertLess(content.index('经过数小时延误'), content.index('After hours of'))

    def test_src_trans_order_swaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.srt')
            tr = os.path.join(tmp, 'tr.srt')
            out = os.path.join(tmp, 'out.srt')
            _write_srt(src, [(0.0, 5.0, 'After hours of delay')])
            _write_srt(tr, [(0.0, 5.0, '经过数小时延误')])
            bs.build_bilingual_srt(src, tr, out, order='src_trans')
            with open(out, encoding='utf-8') as fh:
                content = fh.read()
            # 英文在上（src_trans）
            self.assertLess(content.index('After hours of delay'), content.index('经过数小时延误'))

    def test_source_zh_copies_single(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.srt')
            out = os.path.join(tmp, 'out.srt')
            _write_srt(src, [(0.0, 5.0, '这是中文源字幕')])
            bs.build_bilingual_srt(src, src, out, order='trans_src', source_is_zh=True)
            with open(out, encoding='utf-8') as fh:
                self.assertIn('这是中文源字幕', fh.read())

    def test_no_source_falls_back_to_translation(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'missing.srt')
            tr = os.path.join(tmp, 'tr.srt')
            out = os.path.join(tmp, 'out.srt')
            _write_srt(tr, [(0.0, 5.0, '只有翻译')])
            result = bs.build_bilingual_srt(src, tr, out)
            self.assertTrue(result)
            with open(out, encoding='utf-8') as fh:
                self.assertIn('只有翻译', fh.read())

    def test_slice_source_text_proportional(self):
        text = 'After hours of delay your flight is boarding now'
        # 中间 50% 窗口应切出中间一半左右的词
        sliced = bs._slice_source_text(text, 0.0, 10.0, 2.5, 7.5)
        self.assertTrue(sliced)
        self.assertLess(len(sliced.split()), len(text.split()))
        self.assertGreater(len(sliced.split()), 0)

    def test_build_bilingual_ass_bold_string_robustness(self):
        """SUBTITLE_BOLD 可能是 'on'/'off' 等字符串（设置页 toggle 存法），不应导致构建失败。"""
        import tempfile
        from modules.bilingual_subtitles import build_bilingual_ass
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.srt')
            tr = os.path.join(tmp, 'tr.srt')
            out = os.path.join(tmp, 'out.ass')
            _write_srt(src, [(0.0, 5.0, 'After hours of delay')])
            _write_srt(tr, [(0.0, 5.0, '经过数小时延误')])
            for bold_val, expect in (('on', '-1'), ('off', '0'), (1, '-1'), (0, '0')):
                cfg = {
                    'SUBTITLE_MODE': 'bilingual',
                    'SUBTITLE_ZH_SIZE': 60,
                    'SUBTITLE_EN_SIZE': 32,
                    'SUBTITLE_BOLD': bold_val,
                }
                res = build_bilingual_ass(src, tr, out, cfg, 'Noto Sans CJK SC', 1920, 1080)
                self.assertTrue(res, f'bold={bold_val!r} 构建失败')
                with open(out, encoding='utf-8') as fh:
                    zh_style = next(l for l in fh if l.startswith('Style: Zh,'))
                self.assertIn(f'Noto Sans CJK SC,60,&H00FFFFFF,&H00FFFFFF,&H00000000,&H96000000,{expect},',
                              zh_style, f'bold={bold_val!r} 期望 {expect}')

    def test_build_bilingual_ass_styles(self):
        """中文大(60)+英文小(32)，两个样式；双语生成两行，zh_only 只中文。"""
        import tempfile
        from modules.bilingual_subtitles import build_bilingual_ass
        from modules.srt_transform_engine import SrtTransformConfig, SrtTransformEngine
        eng = SrtTransformEngine(SrtTransformConfig())
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.srt')
            tr = os.path.join(tmp, 'tr.srt')
            out = os.path.join(tmp, 'out.ass')
            _write_srt(src, [(0.0, 5.0, 'After hours of delay your flight is boarding')])
            _write_srt(tr, [(0.0, 5.0, '经过数小时延误后你的航班开始登机')])
            cfg = {
                'SUBTITLE_MODE': 'bilingual',
                'SUBTITLE_ZH_SIZE': 60,
                'SUBTITLE_EN_SIZE': 32,
                'SUBTITLE_ZH_COLOR': '#FFFFFF',
                'SUBTITLE_EN_COLOR': '#DCDCDC',
                'SUBTITLE_ALIGN': 'bottom',
                'SUBTITLE_MARGIN_V': 90,
                'SUBTITLE_BOXED': True,
            }
            res = build_bilingual_ass(src, tr, out, cfg, 'Noto Sans CJK SC', 1920, 1080)
            self.assertTrue(res)
            with open(out, encoding='utf-8') as fh:
                content = fh.read()
            # 两个样式 Zh/En，中文字号比英文大
            self.assertIn('Style: Zh,Noto Sans CJK SC,60', content)
            self.assertIn('Style: En,Noto Sans CJK SC,32', content)
            # 默认加粗（Bold=-1）且描边为黑色，保证复杂背景下可读性
            self.assertIn(',&H00000000,&H96000000,-1,0,0,0', content)
            # 双语有两行（一条 Zh + 一条 En dialogue）
            self.assertIn('{\\rZh}经过', content)
            self.assertIn('{\\rEn}After hours of delay', content)

            # zh_only 只保留中文行
            res2 = build_bilingual_ass(src, tr, os.path.join(tmp, 'out2.ass'), {**cfg, 'SUBTITLE_MODE': 'zh_only'}, 'Noto Sans CJK SC', 1920, 1080)
            self.assertTrue(res2)
            with open(os.path.join(tmp, 'out2.ass'), encoding='utf-8') as fh:
                content2 = fh.read()
            self.assertIn('{\\rZh}经过', content2)
            self.assertNotIn('{\\rEn}', content2)


if __name__ == '__main__':
    unittest.main()
