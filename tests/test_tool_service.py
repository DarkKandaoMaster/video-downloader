import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from video_downloader.core.constants import LEGACY_ALL_SUBTITLE_LANGS, RECOMMENDED_SUBTITLE_LANGS
from video_downloader.services.tools import ToolService


class FakeAppState:
    def __init__(self):
        self.updates = []

    def update_config(self, values):
        self.updates.append(values)


def create_service(tool_dir, build_subtitle_command=None, app_state=None, log=None):
    return ToolService(
        tool_dir=tool_dir,
        exe_suffix=".exe",
        app_state=app_state or FakeAppState(),
        save_config=lambda: None,
        log=log or (lambda message, level="info": None),
        build_subtitle_command=build_subtitle_command,
    )


class ImmediateThread:
    def __init__(self, target, daemon=False):
        self._target = target

    def start(self):
        self._target()


class CompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class ToolServiceTests(unittest.TestCase):
    def test_check_deps_reports_all_tools(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            (tool_dir / "ffmpeg.exe").touch()
            service = create_service(tool_dir)
            self.assertEqual(service.check_deps(), {
                "yt-dlp": True,
                "ffmpeg": True,
                "ffprobe": False,
                "fantiadl": False,
                "withny_dl": False,
                "nicochannel_plugin": False,
            })

    def test_read_urls_file_filters_blank_and_comment_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "urls.txt").write_text(
                "# ignored\n\nhttps://example.com/one\n https://example.com/two \n",
                encoding="utf-8",
            )
            service = create_service(tool_dir)
            self.assertEqual(service.read_urls_file(), ([
                "https://example.com/one",
                "https://example.com/two",
            ], None))

    def test_clean_temp_only_removes_known_extensions(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            nested = tool_dir / "nested"
            nested.mkdir()
            (nested / "video.part").touch()
            (nested / "state.ytdl").touch()
            kept = tool_dir / "video.mp4"
            kept.touch()
            result = create_service(tool_dir).clean_temp()
            self.assertEqual(result, {"ok": True, "count": 2})
            self.assertTrue(kept.exists())
            self.assertFalse((nested / "video.part").exists())

    def test_templates_do_not_overwrite_existing_files(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            urls_file = tool_dir / "urls.txt"
            cookie_file = tool_dir / "cookies.txt"
            urls_file.write_text("existing urls", encoding="utf-8")
            cookie_file.write_text("existing cookies", encoding="utf-8")
            service = create_service(tool_dir)
            self.assertTrue(service.gen_url_template()["existed"])
            self.assertTrue(service.gen_cookie_template()["existed"])
            self.assertEqual(urls_file.read_text(encoding="utf-8"), "existing urls")
            self.assertEqual(cookie_file.read_text(encoding="utf-8"), "existing cookies")

    def test_handle_tool_action_routes_every_explicit_action(self):
        with tempfile.TemporaryDirectory() as directory:
            service = create_service(Path(directory))
            method_names = [
                "gen_url_template",
                "gen_cookie_template",
                "update_ytdlp",
                "clean_temp",
            ]
            actions = [
                "gen-template",
                "gen-cookie-template",
                "update-ytdlp",
                "clean-temp",
            ]
            for method_name, action in zip(method_names, actions):
                with self.subTest(action=action), patch.object(service, method_name, return_value={"action": action}):
                    self.assertEqual(service.handle_tool_action(action), {"action": action})

    def test_handle_tool_action_routes_folder_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            service = create_service(tool_dir)
            with patch.object(service, "open_folder", side_effect=lambda path: {"path": path}):
                self.assertEqual(service.handle_tool_action("open-downloads"), {"path": tool_dir})
                self.assertEqual(service.handle_tool_action("open-logs"), {"path": tool_dir / "logs"})

    def test_download_subtitles_requires_ytdlp(self):
        with tempfile.TemporaryDirectory() as directory:
            service = create_service(Path(directory), build_subtitle_command=lambda **kwargs: [])
            self.assertEqual(
                service.download_subtitles(["https://youtube.com/watch?v=abc"], "all", "all,-live_chat"),
                {"error": "未找到yt-dlp.exe"},
            )

    def test_download_subtitles_validates_type_and_language_length(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            service = create_service(tool_dir, build_subtitle_command=lambda **kwargs: [])

            self.assertEqual(
                service.download_subtitles(["https://youtube.com/watch?v=abc"], "bad", "all,-live_chat"),
                {"error": "字幕类型无效"},
            )
            self.assertEqual(
                service.download_subtitles(["https://youtube.com/watch?v=abc"], "all", "x" * 201),
                {"error": "字幕语言设置长度不能超过 200 字符"},
            )

    def test_download_subtitles_runs_subtitle_command_without_updating_config(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            app_state = FakeAppState()
            build_calls = []
            logs = []

            def build_subtitle_command(url, *, subtitle_type, subtitle_langs):
                build_calls.append((url, subtitle_type, subtitle_langs))
                return [str(tool_dir / "yt-dlp.exe"), "--skip-download", url]

            service = create_service(
                tool_dir,
                build_subtitle_command=build_subtitle_command,
                app_state=app_state,
                log=lambda message, level="info": logs.append((message, level)),
            )
            with patch("video_downloader.services.tools.threading.Thread", ImmediateThread), \
                 patch("video_downloader.services.tools.subprocess.run", return_value=CompletedProcess(
                     stdout="[info] Writing video subtitles to: subtitles/video.zh.vtt",
                 )) as run:
                result = service.download_subtitles([
                    " `https://youtube.com/watch?v=abc` ",
                    "",
                ], "manual", "zh.*")

            self.assertEqual(result, {"ok": True, "total": 1})
            self.assertEqual(build_calls, [("https://youtube.com/watch?v=abc", "manual", "zh.*")])
            self.assertEqual(run.call_args.args[0], [str(tool_dir / "yt-dlp.exe"), "--skip-download", "https://youtube.com/watch?v=abc"])
            self.assertEqual(app_state.updates, [])
            self.assertTrue(any(level == "success" for _, level in logs))

    def test_download_subtitles_counts_success_when_stdout_writes_with_stderr_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            logs = []

            def build_subtitle_command(url, *, subtitle_type, subtitle_langs):
                return [str(tool_dir / "yt-dlp.exe"), "--skip-download", url]

            service = create_service(
                tool_dir,
                build_subtitle_command=build_subtitle_command,
                log=lambda message, level="info": logs.append((message, level)),
            )
            with patch("video_downloader.services.tools.threading.Thread", ImmediateThread), \
                 patch("video_downloader.services.tools.subprocess.run", return_value=CompletedProcess(
                     returncode=0,
                     stdout="[info] Writing video subtitles to: subtitles/video.ja.vtt",
                     stderr="WARNING: subtitles are only available when logged in",
                 )):
                result = service.download_subtitles(["https://youtube.com/watch?v=abc"], "manual", "ja.*")

            self.assertEqual(result, {"ok": True, "total": 1})
            self.assertTrue(any("字幕处理完成" in message for message, _ in logs))
            self.assertTrue(any("成功1 未找到0 失败0" in message for message, _ in logs))

    def test_download_subtitles_counts_zero_return_without_written_file_as_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            logs = []

            def build_subtitle_command(url, *, subtitle_type, subtitle_langs):
                return [str(tool_dir / "yt-dlp.exe"), "--skip-download", url]

            service = create_service(
                tool_dir,
                build_subtitle_command=build_subtitle_command,
                log=lambda message, level="info": logs.append((message, level)),
            )
            with patch("video_downloader.services.tools.threading.Thread", ImmediateThread), \
                 patch("video_downloader.services.tools.subprocess.run", return_value=CompletedProcess(
                     returncode=0,
                     stdout="[info] There are no subtitles for the requested languages",
                 )):
                result = service.download_subtitles(["https://youtube.com/watch?v=abc"], "manual", "ja.*")

            self.assertEqual(result, {"ok": True, "total": 1})
            self.assertTrue(any("未找到匹配字幕" in message for message, _ in logs))
            self.assertTrue(any("成功0 未找到1 失败0" in message for message, _ in logs))

    def test_download_subtitles_retries_recommended_languages_after_legacy_all_rate_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            tool_dir = Path(directory)
            (tool_dir / "yt-dlp.exe").touch()
            build_calls = []
            logs = []

            def build_subtitle_command(url, *, subtitle_type, subtitle_langs):
                build_calls.append((url, subtitle_type, subtitle_langs))
                return [str(tool_dir / "yt-dlp.exe"), "--sub-langs", subtitle_langs, "--skip-download", url]

            service = create_service(
                tool_dir,
                build_subtitle_command=build_subtitle_command,
                log=lambda message, level="info": logs.append((message, level)),
            )
            with patch("video_downloader.services.tools.threading.Thread", ImmediateThread), \
                 patch("video_downloader.services.tools.subprocess.run", side_effect=[
                     CompletedProcess(
                         returncode=1,
                         stderr="ERROR: Unable to download video subtitles for 'ab': HTTP Error 429: Too Many Requests",
                     ),
                     CompletedProcess(
                         returncode=0,
                         stdout="[info] Writing video subtitles to: subtitles/video.ja.vtt",
                     ),
                 ]) as run:
                result = service.download_subtitles(
                    ["https://youtube.com/watch?v=abc"],
                    "all",
                    LEGACY_ALL_SUBTITLE_LANGS,
                )

            self.assertEqual(result, {"ok": True, "total": 1})
            self.assertEqual(build_calls, [
                ("https://youtube.com/watch?v=abc", "all", LEGACY_ALL_SUBTITLE_LANGS),
                ("https://youtube.com/watch?v=abc", "all", RECOMMENDED_SUBTITLE_LANGS),
            ])
            self.assertEqual(run.call_count, 2)
            self.assertTrue(any("改用常用字幕重试" in message for message, _ in logs))
            self.assertTrue(any(level == "success" for _, level in logs))

    def test_handle_tool_action_rejects_unknown_action(self):
        with tempfile.TemporaryDirectory() as directory:
            service = create_service(Path(directory))
            self.assertEqual(
                service.handle_tool_action("missing"),
                {"error": "未知工具操作: missing"},
            )


if __name__ == "__main__":
    unittest.main()
