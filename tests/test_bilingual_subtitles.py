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


if __name__ == '__main__':
    unittest.main()
