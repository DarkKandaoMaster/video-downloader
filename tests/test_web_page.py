import os
import unittest

from video_downloader.web.rendering import (
    SESSION_TOKEN_PLACEHOLDER,
    render_html_page,
    serve_static_file,
)


def _skip_if_frozen():
    import sys

    if getattr(sys, "frozen", False):
        raise unittest.SkipTest("PyInstaller frozen mode")


class WebPageTests(unittest.TestCase):
    def test_render_replaces_session_token(self):
        token = "test-session-token"
        rendered = render_html_page(token)
        self.assertIsInstance(rendered, bytes)
        text = rendered.decode("utf-8")
        # Token is injected via window.SESSION_TOKEN inline script
        self.assertIn(f'window.SESSION_TOKEN = "{token}";', text)
        self.assertNotIn(SESSION_TOKEN_PLACEHOLDER, text)

    def test_template_keeps_expected_structure(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(base, "resource", "templates", "index.html")
        self.assertTrue(
            os.path.isfile(template_path), f"Template missing: {template_path}"
        )
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()
        self.assertTrue(html.startswith("<!DOCTYPE html>"))
        self.assertIn("</html>", html)
        # HTML 结构检查
        self.assertIn("page-download", html)
        self.assertIn("page-settings", html)
        self.assertIn("page-history", html)
        self.assertIn("page-tools", html)
        self.assertIn("page-help", html)
        self.assertIn("page-about", html)
        self.assertIn('class="app-shell"', html)
        self.assertIn('class="app-sidebar"', html)
        self.assertIn('class="app-content"', html)
        self.assertIn('aria-label="主导航"', html)
        self.assertIn("ErgouTree", html)
        self.assertIn("@ergou10086", html)
        self.assertIn("https://github.com/ergou10086", html)
        self.assertIn("DarkKandaoMaster", html)
        self.assertIn("强壮的砍刀", html)
        self.assertIn("https://github.com/DarkKandaoMaster", html)
        self.assertIn("https://github.com/maomaoyexi", html)
        # 引用了外部 CSS/JS（重构为自建深色设计系统，不再依赖 Tabler）
        self.assertIn("/static/css/core.css", html)
        self.assertIn("/static/css/theme.css", html)
        self.assertIn("/static/js/app.js", html)
        self.assertNotIn("tabler.min.css", html)
        self.assertNotIn("tabler.min.js", html)
        # Token 占位符
        self.assertIn("__SESSION_TOKEN__", html)
        self.assertIn('id="btnWithnyLive"', html)
        self.assertIn('id="nicochannelHint"', html)
        self.assertIn('id="sw_subtitles"', html)
        self.assertIn('id="s_subtitle_type"', html)
        self.assertIn('id="s_subtitle_lang_preset"', html)
        self.assertIn('id="s_subtitle_langs"', html)
        self.assertIn('id="subtitleDownloadDialog"', html)
        self.assertIn('id="subtitleUrlInput"', html)
        self.assertIn('id="tool_subtitle_type"', html)
        self.assertIn('id="tool_subtitle_lang_preset"', html)
        self.assertIn('id="tool_subtitle_langs"', html)

    def test_reset_config_uses_post(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # reset-config 使用 POST 在 JS 中
        self.assertIn("api('/api/reset-config', {method:'POST'})", js)
        self.assertIn("api('/api/start-withny-live'", js)

    def test_subtitle_controls_are_in_settings_page_only(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(base, "resource", "templates", "index.html")
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        download_start = html.index('id="page-download"')
        settings_start = html.index('id="page-settings"')
        history_start = html.index('id="page-history"')
        download_html = html[download_start:settings_start]
        settings_html = html[settings_start:history_start]

        self.assertNotIn('id="subtitleOptions"', download_html)
        self.assertNotIn('id="sw_subtitles"', download_html)
        self.assertNotIn('id="s_subtitle_type"', download_html)
        self.assertNotIn('id="s_subtitle_lang_preset"', download_html)
        self.assertNotIn('id="s_subtitle_langs"', download_html)
        self.assertIn('id="subtitleOptions"', settings_html)
        self.assertIn('id="sw_subtitles"', settings_html)
        self.assertIn('id="s_subtitle_type"', settings_html)
        self.assertIn('id="s_subtitle_lang_preset"', settings_html)
        self.assertIn('id="s_subtitle_langs"', settings_html)
        self.assertIn("字幕下载", settings_html)
        self.assertIn("影响单链接、多行链接和 TXT 批量下载", settings_html)
        self.assertLess(
            settings_html.index("画质与输出"),
            settings_html.index('id="subtitleOptions"'),
        )
        self.assertLess(
            settings_html.index('id="subtitleOptions"'),
            settings_html.index("网络与代理"),
        )

    def test_subtitle_download_tool_is_in_tools_page(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        template_path = os.path.join(base, "resource", "templates", "index.html")
        with open(template_path, "r", encoding="utf-8") as f:
            html = f.read()

        tools_start = html.index('id="page-tools"')
        help_start = html.index('id="page-help"')
        tools_html = html[tools_start:help_start]

        self.assertIn("单独下载字幕", tools_html)
        self.assertIn('onclick="showSubtitleDownloader()"', tools_html)
        self.assertIn('id="subtitleDownloadDialog"', tools_html)
        self.assertIn('id="subtitleUrlInput"', tools_html)
        self.assertIn('id="tool_subtitle_type"', tools_html)
        self.assertIn('id="tool_subtitle_lang_preset"', tools_html)
        self.assertIn('id="tool_subtitle_langs"', tools_html)
        self.assertIn("不会下载视频", tools_html)

    def test_normal_palette_toggle_is_available(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(
            os.path.join(base, "resource", "templates", "index.html"),
            "r",
            encoding="utf-8",
        ) as f:
            html = f.read()
        with open(
            os.path.join(base, "resource", "static", "js", "theme.js"),
            "r",
            encoding="utf-8",
        ) as f:
            js = f.read()
        with open(
            os.path.join(base, "resource", "static", "css", "theme.css"),
            "r",
            encoding="utf-8",
        ) as f:
            css = f.read()
        self.assertIn('id="paletteToggle"', html)
        self.assertIn('id="paletteToggleMobile"', html)
        self.assertIn("video-dl-palette", js)
        self.assertIn("togglePalette", js)
        self.assertIn('[data-palette="normal"]', css)
        self.assertIn('[data-theme="light"][data-palette="normal"]', css)

    def test_app_js_has_api_endpoints(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        # 关键 API 端点仍在 JS 中
        self.assertIn("/api/events?token=", js)
        self.assertIn("/api/start", js)
        self.assertIn("/api/start-withny-archive", js)
        self.assertIn('{name:"Withny",color:"#22C55E"}', js)
        self.assertIn("/api/do-update", js)
        self.assertIn("/api/download-subtitles", js)
        self.assertIn("DOWNLOAD_SUBTITLES: isOn('sw_subtitles')?1:0", js)
        self.assertIn("SUBTITLE_TYPE: $('s_subtitle_type').value", js)
        self.assertIn("SUBTITLE_LANGS: getSubtitleLangsValue()", js)
        self.assertIn("function applySubtitleLangsValue(value)", js)
        self.assertIn("function onSubtitleLangPresetChange()", js)
        self.assertIn("function showSubtitleDownloader()", js)
        self.assertIn("function startSubtitleDownload()", js)
        self.assertIn(
            "fillSelect('tool_subtitle_lang_preset', SUBTITLE_LANG_PRESETS)", js
        )
        self.assertIn("fillSelect('s_subtitle_lang_preset', SUBTITLE_LANG_PRESETS)", js)
        self.assertIn("const LEGACY_ALL_SUBTITLE_LANGS = 'all,-live_chat';", js)
        self.assertIn("const DEFAULT_SUBTITLE_LANGS = 'ja.*,zh.*,zh-Hans,zh-Hant,en.*,ko.*';", js)
        self.assertIn("[DEFAULT_SUBTITLE_LANGS, '常用字幕（推荐）']", js)
        self.assertIn("function normalizeSubtitleLangsValue(value)", js)
        self.assertIn("['zh.*,zh-Hans,zh-Hant', '中文']", js)
        self.assertIn("['zh.*,zh-Hans,zh-Hant,en.*', '中文 + 英文']", js)
        self.assertIn("['custom', '自定义']", js)
        self.assertNotIn("['all,-live_chat', '全部可用字幕（推荐）']", js)

    def test_bilibili_part_title_uses_safe_dom_properties(self):
        _skip_if_frozen()
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        js_path = os.path.join(base, "resource", "static", "js", "app.js")
        with open(js_path, "r", encoding="utf-8") as f:
            js = f.read()
        self.assertIn("title.title = String(p.title ?? '');", js)
        self.assertIn("title.textContent = String(p.title ?? '');", js)
        self.assertNotIn("list.innerHTML = parts.map", js)

    def test_serve_static_file_css(self):
        content, mime = serve_static_file("/static/css/theme.css")
        self.assertIsNotNone(content)
        self.assertIn("text/css", mime)
        self.assertIn(b":root", content)

    def test_serve_static_file_js(self):
        content, mime = serve_static_file("/static/js/app.js")
        self.assertIsNotNone(content)
        self.assertIn("javascript", mime)

    def test_serve_static_file_not_found(self):
        content, mime = serve_static_file("/static/nonexistent.file")
        self.assertIsNone(content)
        self.assertIsNone(mime)

    def test_serve_static_file_path_traversal_blocked(self):
        content, mime = serve_static_file("/static/../../../etc/passwd")
        self.assertIsNone(content)
        self.assertIsNone(mime)

    def test_serve_static_file_non_static_prefix_blocked(self):
        content, mime = serve_static_file("/api/config")
        self.assertIsNone(content)
        self.assertIsNone(mime)

    def test_fallback_html(self):
        from video_downloader.web.rendering import _fallback_html

        html = _fallback_html("fallback-token")
        self.assertIsInstance(html, bytes)
        text = html.decode("utf-8")
        self.assertIn("fallback-token", text)


if __name__ == "__main__":
    unittest.main()
