"""重新烧录字幕（reburn_subtitle）相关单元测试。"""

import os
import tempfile
import unittest
from unittest.mock import patch

from modules.task_manager import TaskProcessor


class ReburnResolverTests(unittest.TestCase):
    def _make_processor(self, config=None):
        return TaskProcessor(config or {})

    def test_resolve_original_video_prefers_video_mp4(self):
        """存在 video.mp4 时优先使用它，而不是带字幕产物。"""
        with tempfile.TemporaryDirectory() as tmp:
            video_mp4 = os.path.join(tmp, 'video.mp4')
            burned = os.path.join(tmp, 'video_with_subtitle.mp4')
            for p in (video_mp4, burned):
                with open(p, 'wb') as fh:
                    fh.write(b'x')
            proc = self._make_processor()
            task = {'video_path_local': burned}
            self.assertEqual(proc._resolve_original_video('t', task, tmp), video_mp4)

    def test_resolve_original_video_derives_from_burned(self):
        """无 video.mp4 时，从 video_with_subtitle.mp4 反推原始文件名。"""
        with tempfile.TemporaryDirectory() as tmp:
            video_mp4 = os.path.join(tmp, 'video.mp4')
            burned = os.path.join(tmp, 'video_with_subtitle.mp4')
            with open(video_mp4, 'wb') as fh:
                fh.write(b'x')
            with open(burned, 'wb') as fh:
                fh.write(b'x')
            proc = self._make_processor()
            task = {'video_path_local': burned}
            self.assertEqual(proc._resolve_original_video('t', task, tmp), video_mp4)

    def test_resolve_original_video_falls_back_to_raw_input(self):
        """未烧录时，video_path_local 本身即为原始视频。"""
        with tempfile.TemporaryDirectory() as tmp:
            raw = os.path.join(tmp, 'clip.mp4')
            with open(raw, 'wb') as fh:
                fh.write(b'x')
            proc = self._make_processor()
            task = {'video_path_local': raw}
            self.assertEqual(proc._resolve_original_video('t', task, tmp), raw)

    def test_resolve_original_video_rejects_burned_as_source(self):
        """仅剩带字幕产物时不应把它当作原始视频（避免二次叠加）。"""
        with tempfile.TemporaryDirectory() as tmp:
            burned = os.path.join(tmp, 'clip_with_subtitle.mp4')
            with open(burned, 'wb') as fh:
                fh.write(b'x')
            proc = self._make_processor()
            task = {'video_path_local': burned}
            self.assertEqual(proc._resolve_original_video('t', task, tmp), '')

    def test_rebuild_burn_subtitle_detects_translated_srt(self):
        """在任务目录中发现 asr_*.srt 与 translated_*.srt，且翻译关闭时降级为翻译字幕。"""
        with tempfile.TemporaryDirectory() as tmp:
            asr = os.path.join(tmp, 'asr_t.srt')
            tr = os.path.join(tmp, 'translated_t.srt')
            with open(asr, 'w', encoding='utf-8') as fh:
                fh.write('1\n00:00:00,000 --> 00:00:02,000\nHello\n')
            with open(tr, 'w', encoding='utf-8') as fh:
                fh.write('1\n00:00:00,000 --> 00:00:02,000\n你好\n')
            cfg = {'SUBTITLE_TRANSLATION_ENABLED': False}
            proc = self._make_processor(cfg)
            origin = os.path.join(tmp, 'video.mp4')
            with open(origin, 'wb') as fh:
                fh.write(b'x')
            with patch.object(proc, '_detect_subtitle_language', return_value='en'):
                burn, src, tsl, lang = proc._rebuild_burn_subtitle('t', tmp, {}, origin, None)
            self.assertEqual(burn, tr)
            self.assertEqual(src, asr)
            self.assertEqual(tsl, tr)
            self.assertEqual(lang, 'en')


if __name__ == '__main__':
    unittest.main()
