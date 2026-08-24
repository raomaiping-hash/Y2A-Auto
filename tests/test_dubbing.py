#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import tempfile
import unittest
from unittest.mock import patch

from modules import dubbing


def _write_srt(path, cues):
    """cues: [(start_ms, end_ms, text)]"""
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines.append(str(i))
        lines.append(f'{dubbing._ms_to_ts(start)} --> {dubbing._ms_to_ts(end)}')
        lines.append(text)
        lines.append('')
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('\n'.join(lines).strip() + '\n')


class SrtParseTests(unittest.TestCase):
    def test_parse_basic(self):
        tmp = tempfile.mkdtemp()
        srt = os.path.join(tmp, 'a.srt')
        _write_srt(srt, [
            (0, 2000, '你好世界'),
            (2000, 4500, '第二句话'),
        ])
        cues = dubbing.parse_srt_to_segments(srt)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0]['text'], '你好世界')
        self.assertEqual(cues[0]['start_ms'], 0)
        self.assertEqual(cues[0]['end_ms'], 2000)
        self.assertEqual(cues[1]['text'], '第二句话')

    def test_parse_skips_empty_and_invalid(self):
        tmp = tempfile.mkdtemp()
        srt = os.path.join(tmp, 'b.srt')
        _write_srt(srt, [(0, 1000, '好'), (3000, 2000, '时间倒挂')])  # 时间倒挂应跳过
        cues = dubbing.parse_srt_to_segments(srt)
        self.assertEqual(len(cues), 1)

    def test_parse_missing_file(self):
        self.assertEqual(dubbing.parse_srt_to_segments('/nonexistent.srt'), [])


class DurationEstimateTests(unittest.TestCase):
    def test_chinese_estimate(self):
        # 9 个汉字 ≈ 2.0 秒
        dur = dubbing.estimate_speech_duration_s('这是一句九字的中文测试')
        self.assertAlmostEqual(dur, len('这是一句九字的中文测试') / 4.5, places=2)

    def test_empty(self):
        self.assertEqual(dubbing.estimate_speech_duration_s(''), 0.0)


class AlignTests(unittest.TestCase):
    def test_short_segment_kept(self):
        seg = dubbing.DubSegment(index=0, text='短', start_ms=0, end_ms=5000,
                                 wav_path='/tmp/fake.wav', duration_s=2.0)
        out = dubbing.align_segments_smart_mix([seg], None)
        self.assertEqual(out[0].speed, 1.0)
        self.assertEqual(out[0].wav_path, '/tmp/fake.wav')

    @patch('modules.dubbing._atempo_wav')
    @patch('modules.dubbing._probe_wav_duration')
    def test_long_segment_tempo(self, mock_dur, mock_atempo):
        mock_atempo.return_value = '/tmp/fake.tempo.wav'
        mock_dur.return_value = 4.8  # 加速后时长
        seg = dubbing.DubSegment(index=0, text='长', start_ms=0, end_ms=4000,
                                 wav_path='/tmp/fake.wav', duration_s=5.5)
        out = dubbing.align_segments_smart_mix([seg], None)
        self.assertGreater(out[0].speed, 1.0)
        self.assertEqual(out[0].wav_path, '/tmp/fake.tempo.wav')


class AssemblyCmdTests(unittest.TestCase):
    """验证合成命令结构（不实际跑 ffmpeg）。"""

    def test_concat_uses_absolute_timeline_and_trims(self):
        """回归：拼接用绝对时间轴 + atrim 窗口钳制，短不叠加、不从 0 也要补静音。"""
        captured = {}

        def fake_run(cmd, **kwargs):
            captured['cmd'] = cmd
            return _FakeProc()

        seg1 = dubbing.DubSegment(index=0, text='首句', start_ms=3000, end_ms=5000,
                                  wav_path='/tmp/a.wav', duration_s=3.0)
        seg2 = dubbing.DubSegment(index=1, text='次句', start_ms=5000, end_ms=8000,
                                  wav_path='/tmp/b.wav', duration_s=3.0)
        with patch('modules.dubbing.subprocess.run', side_effect=fake_run), \
             patch('modules.dubbing.get_ffmpeg_path', return_value='ffmpeg'):
            dubbing._concat_wav_segments([seg1, seg2], '/tmp/out.wav', None)

        fc = ' '.join(captured['cmd'])
        # 每段都 atrim 到其窗口时长（seg1 窗口 2s, seg2 窗口 3s）
        self.assertIn('atrim=0:2.000', fc)
        self.assertIn('atrim=0:3.000', fc)
        # 绝对时间轴 adelay
        self.assertIn('adelay=3000|3000', fc)
        self.assertIn('adelay=5000|5000', fc)

    def test_concat_trims_overlong_segment(self):
        """回归：超窗片段（加速后仍长于窗口）必须被截断，防侵入下一句叠加。"""
        captured = {}

        def fake_run(cmd, **kwargs):
            captured['cmd'] = cmd
            return _FakeProc()

        # seg1 实际 5s 但窗口只有 2s（模拟加速后仍超窗）——atrim 需截断到 2s
        seg1 = dubbing.DubSegment(index=0, text='long', start_ms=3000, end_ms=5000,
                                  wav_path='/tmp/a.wav', duration_s=5.0)
        with patch('modules.dubbing.subprocess.run', side_effect=fake_run), \
             patch('modules.dubbing.get_ffmpeg_path', return_value='ffmpeg'):
            dubbing._concat_wav_segments([seg1], '/tmp/out.wav', None)
        fc = ' '.join(captured['cmd'])
        self.assertIn('atrim=0:2.000', fc)

    def test_concat_single_segment_pads_leading_silence(self):
        """单片段且起始时间非 0：也要补前导静音保证绝对时间轴。"""
        captured = {}

        def fake_run(cmd, **kwargs):
            captured['cmd'] = cmd
            return _FakeProc()

        seg = dubbing.DubSegment(index=0, text='首句', start_ms=4000, end_ms=6000,
                                 wav_path='/tmp/a.wav', duration_s=2.0)
        with patch('modules.dubbing.subprocess.run', side_effect=fake_run), \
             patch('modules.dubbing.get_ffmpeg_path', return_value='ffmpeg'):
            dubbing._concat_wav_segments([seg], '/tmp/out.wav', None)
        fc = ' '.join(captured['cmd'])
        self.assertIn('atrim=0:2.000', fc)
        self.assertIn('adelay=4000|4000', fc)

    def test_assemble_cmd_no_bgm_no_subtitle(self):
        cfg = {'VIDEO_ENCODER': 'cpu', 'VIDEO_CPU_PRESET': 'fast'}
        cmd = self._capture_cmd(cfg, bgm=None, sub=None)
        self.assertEqual(cmd[0:2], ['ffmpeg', '-y'])
        self.assertIn('-i', cmd)
        self.assertIn('-map', cmd)
        self.assertIn('[a_out]', ' '.join(cmd))
        self.assertNotIn('subtitles', ' '.join(cmd))

    @staticmethod
    def _capture_cmd(cfg, bgm, sub):
        captured = {}

        def fake_popen(cmd, **kwargs):
            captured['cmd'] = cmd
            # 模拟 ffmpeg 产出输出文件
            out_arg = None
            for i, part in enumerate(cmd):
                if part == '/tmp/out.mp4':
                    out_arg = part
            if out_arg:
                with open(out_arg, 'wb') as fh:
                    fh.write(b'fake-mp4')
            return _FakeProc()

        with patch('modules.dubbing.subprocess.Popen', side_effect=fake_popen), \
             patch('modules.dubbing.get_ffmpeg_path', return_value='ffmpeg'), \
             patch('modules.dubbing.os.makedirs'):
            dubbing.assemble_dubbed_video(
                '/tmp/v.mp4', '/tmp/dub.wav', sub, '/tmp/out.mp4', cfg, None,
                bgm_path=bgm,
            )
        return captured['cmd']


class _FakeProc:
    def __init__(self):
        self.returncode = 0
        self.stdout = []

    def wait(self, timeout=None):
        return 0


if __name__ == '__main__':
    unittest.main()
