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
    def test_returns_no_write_subs_when_subtitles_disabled(self):
        build_args = _load_function("_build_subtitle_download_args")

        args = build_args({}, include_subtitles=False)

        self.assertEqual(args, ["--no-write-subs"])

    def test_returns_no_write_subs_when_auto_gen_disabled(self):
        """YOUTUBE_AUTO_GENERATED_SUBTITLES_ENABLED 默认 False，不下载字幕"""
        build_args = _load_function("_build_subtitle_download_args")

        args = build_args({}, include_subtitles=True)

        self.assertEqual(args, ["--no-write-subs"])

    def test_includes_target_language_sub_langs_when_enabled(self):
        """启用自动字幕时只下载目标语言（en/zh），避免全量下载触发 429 限流"""
        build_args = _load_function("_build_subtitle_download_args")

        args = build_args(
            {"YOUTUBE_AUTO_GENERATED_SUBTITLES_ENABLED": True},
            include_subtitles=True,
        )

        self.assertIn("--write-auto-subs", args)
        self.assertEqual(
            args,
            ["--write-subs", "--sub-langs", "en.*,zh.*", "--convert-subs", "srt", "--write-auto-subs"],
        )
        self.assertNotIn("--all-subs", args)

    def test_includes_explicit_source_language_in_sub_langs(self):
        build_args = _load_function("_build_subtitle_download_args")

        args = build_args(
            {
                "YOUTUBE_AUTO_GENERATED_SUBTITLES_ENABLED": True,
                "SUBTITLE_SOURCE_LANGUAGE": "ja",
            },
            include_subtitles=True,
        )

        lang_index = args.index("--sub-langs")
        self.assertEqual(args[lang_index + 1], "ja.*,en.*,zh.*")


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
