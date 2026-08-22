"""delete_task_files 相关文件清理测试（downloads 目录 + 任务日志文件）。"""

import pathlib
import tempfile
import unittest
from unittest import mock

from modules import task_manager as tm


class DeleteTaskFilesTests(unittest.TestCase):
    def _patch_dirs(self, root):
        logs_dir = pathlib.Path(root) / 'logs'
        downloads_dir = pathlib.Path(root) / 'downloads'
        logs_dir.mkdir(parents=True, exist_ok=True)
        downloads_dir.mkdir(parents=True, exist_ok=True)
        return (
            mock.patch.object(tm, 'LOGS_DIR', logs_dir),
            mock.patch.object(tm, 'DOWNLOADS_DIR', downloads_dir),
            logs_dir,
            downloads_dir,
        )

    def test_removes_download_dir_and_task_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs, downloads, logs_dir, downloads_dir = self._patch_dirs(tmp)
            with logs, downloads:
                task_dir = downloads_dir / 'abc12345-1234-5678-1234-567812345678'
                task_dir.mkdir()
                (task_dir / 'video.mp4').write_bytes(b'x' * 8)
                log_path = logs_dir / 'task_abc12345-1234-5678-1234-567812345678.log'
                log_path.write_text('log content')

                self.assertTrue(tm.delete_task_files('abc12345-1234-5678-1234-567812345678'))

                self.assertFalse(task_dir.exists(), '下载目录应被删除')
                self.assertFalse(log_path.exists(), '任务日志应被删除')

    def test_leaves_other_task_logs_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs, downloads, logs_dir, downloads_dir = self._patch_dirs(tmp)
            with logs, downloads:
                (downloads_dir / '11111111-1111-1111-1111-111111111111').mkdir()
                (logs_dir / 'task_11111111-1111-1111-1111-111111111111.log').write_text('keep me')
                (logs_dir / 'task_abc12345-1234-5678-1234-567812345678.log').write_text('remove me')

                self.assertTrue(tm.delete_task_files('abc12345-1234-5678-1234-567812345678'))

                self.assertFalse((logs_dir / 'task_abc12345-1234-5678-1234-567812345678.log').exists())
                self.assertTrue((logs_dir / 'task_11111111-1111-1111-1111-111111111111.log').exists(), '其他任务日志不受影响')

    def test_rejects_path_traversal_task_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            logs, downloads, _, _ = self._patch_dirs(tmp)
            with logs, downloads:
                self.assertFalse(tm.delete_task_files('../../etc/passwd'))


if __name__ == '__main__':
    unittest.main()