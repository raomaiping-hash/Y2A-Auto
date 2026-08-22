import ast
import pathlib
import unittest
from unittest import mock


def _load_function(name):
    module_path = pathlib.Path(__file__).resolve().parents[1] / "modules" / "youtube_handler.py"
    source = module_path.read_text(encoding="utf-8")
    module_ast = ast.parse(source, filename=str(module_path))
    selected = [
        node for node in module_ast.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    isolated_module = ast.Module(body=selected, type_ignores=[])
    namespace = {"Any": object}
    exec(compile(isolated_module, str(module_path), "exec"), namespace)
    return namespace[name]


class YouTubeSubtitleDownloadOptionsTests(unittest.TestCase):
    def test_download_command_always_disables_subtitle_download(self):
        """自动字幕已彻底移除：下载命令恒为 --no-write-subs，字幕统一走 ASR。

        源码级回归测试：防止 --write-auto-subs / --write-subs 逻辑被重新引入。
        """
        module_path = pathlib.Path(__file__).resolve().parents[1] / "modules" / "youtube_handler.py"
        source = module_path.read_text(encoding="utf-8")

        self.assertIn("--no-write-subs", source)
        self.assertNotIn("--write-auto-subs", source)
        self.assertNotIn("--write-subs", source)
        self.assertNotIn("YOUTUBE_AUTO_GENERATED_SUBTITLES_ENABLED", source)
        self.assertNotIn("_build_subtitle_download_args", source)
        self.assertNotIn("_require_ffmpeg_for_subtitles", source)

    def test_config_no_longer_exposes_auto_generated_toggle(self):
        """配置中心不再有自动字幕开关；旧配置键由 prune 自动清理。"""
        module_path = pathlib.Path(__file__).resolve().parents[1] / "modules" / "config_manager.py"
        source = module_path.read_text(encoding="utf-8")
        self.assertNotIn("YOUTUBE_AUTO_GENERATED_SUBTITLES_ENABLED", source)


class YtDlpErrorSummaryAndFfmpegPreflightTests(unittest.TestCase):
    def test_summary_prefers_error_line_over_download_progress(self):
        """复现实测回归：stderr 含 ffmpeg ERROR + 末尾 [download] 100% 进度行时，
        摘要必须返回真正的 ERROR 行而不是进度行。"""
        summarize = _load_function("_summarize_yt_dlp_error")

        summary = summarize(
            "[download] 100% of  304.75MiB\n",
            "ERROR: ffmpeg not found. Please install or provide the path using --ffmpeg-location\n",
        )

        self.assertIn("ffmpeg not found", summary)
        self.assertNotIn("304.75MiB", summary)

    def test_summary_returns_last_error_line(self):
        summarize = _load_function("_summarize_yt_dlp_error")

        summary = summarize(
            "[youtube] abc: Downloading webpage\n",
            "WARNING: something\nERROR: first failure\nERROR: final failure\n",
        )

        self.assertEqual(summary, "ERROR: final failure")

    def test_summary_falls_back_to_progress_when_no_error_lines(self):
        summarize = _load_function("_summarize_yt_dlp_error")

        summary = summarize("[download] 42.0% of 1.00GiB\n", "")

        self.assertIn("42.0%", summary)


class YouTubeJsRuntimeOptionsTests(unittest.TestCase):
    def test_prefers_deno_and_keeps_node_as_fallback(self):
        detect_args = _load_function("_detect_js_runtime_args")
        detect_args.__globals__["_which"] = mock.Mock(
            side_effect=lambda runtime: f"/{runtime}" if runtime in {"deno", "node"} else None
        )

        self.assertEqual(
            detect_args(),
            ["--js-runtimes", "deno", "--js-runtimes", "node"],
        )

    def test_uses_deno_when_node_is_unavailable(self):
        detect_args = _load_function("_detect_js_runtime_args")
        detect_args.__globals__["_which"] = mock.Mock(
            side_effect=lambda runtime: "/deno" if runtime == "deno" else None
        )

        self.assertEqual(detect_args(), ["--js-runtimes", "deno"])

    def test_uses_node_when_deno_is_unavailable(self):
        detect_args = _load_function("_detect_js_runtime_args")
        detect_args.__globals__["_which"] = mock.Mock(
            side_effect=lambda runtime: "/node" if runtime == "node" else None
        )

        self.assertEqual(detect_args(), ["--js-runtimes", "node"])

    def test_returns_no_args_without_a_runtime(self):
        detect_args = _load_function("_detect_js_runtime_args")
        detect_args.__globals__["_which"] = mock.Mock(return_value=None)

        self.assertEqual(detect_args(), [])


if __name__ == "__main__":
    unittest.main()
