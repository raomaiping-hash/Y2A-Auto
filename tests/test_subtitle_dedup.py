"""字幕渐进式去重测试：覆盖自动字幕典型形态与必须保留的边界场景。"""

import unittest

from modules.srt_transform_engine import SrtTransformConfig, SrtTransformEngine


def _cue(start, end, text):
    return {'start': float(start), 'end': float(end), 'text': text}


class SubtitleDedupTests(unittest.TestCase):
    def setUp(self):
        self.engine = SrtTransformEngine(SrtTransformConfig())

    def _dedup(self, cues):
        return self.engine.deduplicate_progressive_overlaps(cues)

    def test_progressive_chain_merges_to_longest(self):
        cues = [
            _cue(0.0, 1.0, '黎明将至'),
            _cue(0.1, 1.1, '黎明将至，'),
            _cue(0.2, 1.3, '黎明将至，黑夜终将过去'),
        ]
        result = self._dedup(cues)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['text'], '黎明将至，黑夜终将过去')
        self.assertEqual(result[0]['end'], 1.3)

    def test_identical_text_same_window_merges(self):
        cues = [_cue(0.0, 1.0, '你好'), _cue(0.1, 1.0, '你好')]
        result = self._dedup(cues)
        self.assertEqual(len(result), 1)

    def test_legitimate_repetition_with_distinct_windows_not_merged(self):
        # "不不不" 式的正当连续重复：时间窗口不同，绝不能合并
        cues = [
            _cue(0.0, 0.5, '不'),
            _cue(0.7, 1.2, '不'),
            _cue(1.4, 1.9, '不'),
        ]
        result = self._dedup(cues)
        self.assertEqual(len(result), 3)

    def test_non_prefix_variant_merges_by_similarity(self):
        # 识别修正版：中间字符差异，非前缀
        cues = [_cue(0.0, 1.0, '我爱你们'), _cue(0.2, 1.2, '我爱你们啊')]
        result = self._dedup(cues)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['text'], '我爱你们啊')

    def test_dissimilar_overlapping_cues_not_merged(self):
        cues = [_cue(0.0, 1.0, '今天天气很好'), _cue(0.1, 1.1, '我们出去散步吧')]
        result = self._dedup(cues)
        self.assertEqual(len(result), 2)

    def test_merged_end_clamped_to_next_cue_start(self):
        cues = [
            _cue(0.0, 1.0, '黎明将至'),
            _cue(0.1, 1.1, '黎明将至，黑夜终将过去'),  # 合并 → end 1.1
            _cue(1.05, 2.0, '完全不同的下一句'),
        ]
        result = self._dedup(cues)
        self.assertEqual(len(result), 2)
        self.assertLessEqual(result[0]['end'], result[1]['start'] + 1e-9)

    def test_chain_cap_limits_runaway_merges(self):
        cues = [_cue(i * 0.1, i * 0.1 + 1.0, '重复文本') for i in range(12)]
        result = self._dedup(cues)
        # 最多合并成一条 max_chain=8 的链 + 剩余独立 cue
        self.assertGreaterEqual(len(result), 2)
        self.assertLessEqual(len(result), 12)

    def test_clean_srt_text_roundtrip(self):
        srt = (
            "1\n00:00:00,000 --> 00:00:01,000\n黎明将至\n\n"
            "2\n00:00:00,100 --> 00:00:01,100\n黎明将至，黑夜终将过去\n\n"
        )
        cleaned = self.engine.clean_srt_text(srt)
        self.assertIn('黎明将至，黑夜终将过去', cleaned)
        self.assertEqual(cleaned.count('-->'), 1)


if __name__ == '__main__':
    unittest.main()