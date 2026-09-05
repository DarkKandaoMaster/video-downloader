import json
import queue
import secrets
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from typing import Any, Callable, Protocol, TypeAlias, cast
from urllib.parse import parse_qs, urlparse

from video_downloader.core.constants import RECOMMENDED_SUBTITLE_LANGS

JsonDict: TypeAlias = dict[str, Any]
HttpResult: TypeAlias = JsonDict
MaybeBytesResponse: TypeAlias = tuple[bytes | None, str | None]
ExpectedFieldType: TypeAlias = type[Any] | tuple[type[Any], ...]


class AppStateLike(Protocol):
    config_lock: Any
    log_history: list[Any]
    progress_data: JsonDict
    batch_stats: JsonDict

    def config_snapshot(self) -> JsonDict: ...
    def replace_config(self, values: JsonDict) -> None: ...
    def add_sse_client(self, client: queue.Queue[Any], ready_factory: Callable[[], JsonDict]) -> None: ...
    def remove_sse_client(self, client: queue.Queue[Any]) -> bool: ...


class DownloadManagerLike(Protocol):
    def snapshot(self) -> JsonDict: ...


class UpdaterLike(Protocol):
    def is_checking(self) -> bool: ...
    def start_check_thread(self, silent: bool) -> None: ...
    def snapshot(self) -> JsonDict: ...
    def do_update(self) -> HttpResult: ...


class StoppableServer(Protocol):
    stop_event: threading.Event


class StartDownloadFn(Protocol):
    def __call__(self, url: str, *, bili_parts: Any = None, tc_password: str | None = None) -> HttpResult: ...


class BatchTxtDownloadFn(Protocol):
    def __call__(self, *, bili_parts_map: Any = None) -> HttpResult: ...


@dataclass(frozen=True)
class HttpHandlerDependencies:
    session_token: str
    version: str
    default_config: JsonDict
    app_state: AppStateLike
    download_manager: DownloadManagerLike
    updater: UpdaterLike
    render_html_page: Callable[[str], bytes]
    serve_static_file: Callable[[str], MaybeBytesResponse]
    check_deps: Callable[[], HttpResult]
    load_presets: Callable[[], dict[str, Any]]
    load_history: Callable[[], list[Any]]
    cancel_idle_timer: Callable[[], Any]
    start_idle_timer: Callable[[], Any]
    start_download: StartDownloadFn
    start_withny_archive: Callable[[], HttpResult]
    start_withny_live: Callable[[], HttpResult]
    batch_txt_download: BatchTxtDownloadFn
    start_urls_download: Callable[[list[str]], HttpResult]
    stop_download: Callable[[], HttpResult]
    submit_password: Callable[[str, str], HttpResult]
    fetch_bili_playlist: Callable[[str], HttpResult]
    save_preset: Callable[[str], HttpResult]
    load_preset: Callable[[str], HttpResult]
    delete_preset: Callable[[str], HttpResult]
    clear_history: Callable[[], HttpResult]
    find_cover: Callable[[str], MaybeBytesResponse]
    validate_config: Callable[[JsonDict, JsonDict], tuple[JsonDict, list[str]]]
    save_config: Callable[[], Any]
    handle_tool_action: Callable[[str], HttpResult]
    browse_folder: Callable[[], HttpResult]
    update_ytdlp: Callable[[], HttpResult]
    clean_temp: Callable[[], HttpResult]
    gen_url_template: Callable[[], HttpResult]
    wav_to_mp3: Callable[[str, bool, int, bool], HttpResult]
    audio_loudnorm: Callable[[str, bool, str, int | float, int | float, int | float, str, str], HttpResult]
    audio_volume: Callable[[str, bool, int | float, bool, str, str], HttpResult]
    download_subtitles: Callable[[list[str], str, str], HttpResult]
    request_exit: Callable[[], Any]


def create_handler(dependencies: HttpHandlerDependencies):
    class RequestHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _is_local_request(self) -> bool:
            host = self.headers.get("Host", "").split(":", 1)[0].lower()
            if host not in ("127.0.0.1", "localhost"):
                return False
            origin = self.headers.get("Origin")
            return not origin or origin == f"http://{self.headers.get('Host', '')}"

        def _is_authorized(self, parsed: Any = None) -> bool:
            if not self._is_local_request():
                return False
            token = self.headers.get("X-Session-Token", "")
            if not token and parsed is not None:
                token = parse_qs(parsed.query).get("token", [""])[0]
            return secrets.compare_digest(token, dependencies.session_token)

        def _forbidden(self) -> None:
            self.send_error(403, "Forbidden")

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if path == "/" or path == "/index.html":
                if not self._is_local_request():
                    self._forbidden()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(
                    dependencies.render_html_page(dependencies.session_token)
                )
            elif path.startswith("/api/") and not self._is_authorized(parsed):
                self._forbidden()
            elif path == "/api/config":
                self._json(
                    {
                        "version": dependencies.version,
                        "config": dependencies.app_state.config_snapshot(),
                    }
                )
            elif path == "/api/deps":
                self._json(dependencies.check_deps())
            elif path == "/api/presets":
                self._json({"presets": list(dependencies.load_presets().keys())})
            elif path == "/api/history":
                self._json({"history": dependencies.load_history()[:100]})
            elif path == "/api/cover":
                filepath = parse_qs(parsed.query).get("path", [""])[0]
                content, content_type = dependencies.find_cover(filepath)
                if content is None:
                    self.send_error(404)
                    return
                if content_type is None:
                    content_type = "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(content)
            elif path == "/api/events":
                self._serve_events()
            elif path == "/api/check-update":
                if not dependencies.updater.is_checking():
                    dependencies.updater.start_check_thread(silent=True)
                self._json({"checking": True})
            elif path == "/api/update-status":
                self._json(dependencies.updater.snapshot())
            elif path.startswith("/static/"):
                if not self._is_local_request():
                    self._forbidden()
                    return
                content, content_type = dependencies.serve_static_file(path)
                if content is None:
                    self.send_error(404)
                    return
                if content_type is None:
                    content_type = "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                # 静态资源缓存1小时（版本号变更时URL可加?v=参数强制刷新）
                self.send_header("Cache-Control", "public, max-age=3600")
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404)

        def _serve_events(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.end_headers()

            def ready_event() -> JsonDict:
                download_snapshot = dependencies.download_manager.snapshot()
                return {
                    "type": "ready",
                    "data": {
                        "logs": dependencies.app_state.log_history[-50:],
                        "running": download_snapshot["running"],
                        "phase": download_snapshot["phase"],
                        "generation": download_snapshot["generation"],
                        "progress": dict(dependencies.app_state.progress_data),
                        "stats": dict(dependencies.app_state.batch_stats),
                        "update": dependencies.updater.snapshot(),
                    },
                }

            # 每个 SSE 连接使用有界队列；慢连接的丢旧保新策略由 AppState 统一执行。
            client_queue: queue.Queue[JsonDict] = queue.Queue(maxsize=256)
            dependencies.app_state.add_sse_client(client_queue, ready_event)
            dependencies.cancel_idle_timer()
            last_keepalive = time.monotonic()
            server = cast(StoppableServer, self.server)
            try:
                while not server.stop_event.is_set():
                    try:
                        event = client_queue.get(timeout=1)
                        data = json.dumps(event, ensure_ascii=False)
                        self.wfile.write(f"data: {data}\n\n".encode("utf-8"))
                        self.wfile.flush()
                        if event.get("type") == "exit":
                            break
                    except queue.Empty:
                        if time.monotonic() - last_keepalive >= 15:
                            self.wfile.write(b": keepalive\n\n")
                            self.wfile.flush()
                            last_keepalive = time.monotonic()
            except Exception:
                pass
            finally:
                no_clients = dependencies.app_state.remove_sse_client(client_queue)
                if (
                    no_clients
                    and not dependencies.download_manager.snapshot()["running"]
                    and not server.stop_event.is_set()
                ):
                    dependencies.start_idle_timer()

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path
            if not self._is_authorized(parsed):
                self._forbidden()
                return
            if self.headers.get_content_type() != "application/json":
                self._json(
                    {"error": "Content-Type 必须为 application/json"}, status=415
                )
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                self._json({"error": "无效的 Content-Length"}, status=400)
                return
            if length < 0:
                self._json({"error": "无效的 Content-Length"}, status=400)
                return
            if length > 65536:
                self.send_error(413, "Request body too large")
                return
            try:
                body = self.rfile.read(length).decode("utf-8") if length else "{}"
                data = json.loads(body) if body else {}
            except (UnicodeDecodeError, json.JSONDecodeError):
                self._json({"error": "请求体不是有效的 JSON"}, status=400)
                return
            if not isinstance(data, dict):
                self._json({"error": "JSON 请求体必须是对象"}, status=400)
                return
            data = cast(JsonDict, data)
            if path == "/api/start":
                url = self._field(data, "url", str, "")
                if url is None:
                    return
                bili_parts = data.get("bili_parts") or None
                tc_password = data.get("tc_password")
                if tc_password is not None and not isinstance(tc_password, str):
                    self._json({"error": "字段 tc_password 类型错误"}, status=400)
                    return
                tc_password = tc_password or None
                self._json(
                    dependencies.start_download(
                        url, bili_parts=bili_parts, tc_password=tc_password
                    )
                )
            elif path == "/api/start-withny-archive":
                self._json(dependencies.start_withny_archive())
            elif path == "/api/start-withny-live":
                self._json(dependencies.start_withny_live())
            elif path == "/api/submit-password":
                url = self._field(data, "url", str, "")
                if url is None:
                    return
                password = self._field(data, "password", str, "")
                if password is None:
                    return
                if not password.strip():
                    self._json({"error": "密码不能为空"}, status=400)
                    return
                self._json(dependencies.submit_password(url, password))
            elif path == "/api/start-urls":
                urls = self._field(data, "urls", list, [])
                if urls is None:
                    return
                if not all(isinstance(u, str) for u in urls):
                    self._json({"error": "字段 urls 必须是字符串数组"}, status=400)
                    return
                self._json(dependencies.start_urls_download(urls))
            elif path == "/api/batch-txt":
                bili_parts_map = data.get("bili_parts_map") or None
                self._json(
                    dependencies.batch_txt_download(bili_parts_map=bili_parts_map)
                )
            elif path == "/api/download-subtitles":
                urls = self._field(data, "urls", list, [])
                if urls is None:
                    return
                if not all(isinstance(u, str) for u in urls):
                    self._json({"error": "字段 urls 必须是字符串数组"}, status=400)
                    return
                subtitle_type = self._field(data, "subtitle_type", str, "all")
                if subtitle_type is None:
                    return
                subtitle_langs = self._field(
                    data, "subtitle_langs", str, RECOMMENDED_SUBTITLE_LANGS
                )
                if subtitle_langs is None:
                    return
                self._json(
                    dependencies.download_subtitles(urls, subtitle_type, subtitle_langs)
                )
            elif path == "/api/bili-playlist":
                url = self._field(data, "url", str, "")
                if url is None:
                    return
                self._json(dependencies.fetch_bili_playlist(url))
            elif path == "/api/stop":
                self._json(dependencies.stop_download())
            elif path == "/api/save-preset":
                name = self._field(data, "name", str, "")
                if name is not None:
                    self._json(dependencies.save_preset(name))
            elif path == "/api/load-preset":
                name = self._field(data, "name", str, "")
                if name is not None:
                    self._json(dependencies.load_preset(name))
            elif path == "/api/delete-preset":
                name = self._field(data, "name", str, "")
                if name is not None:
                    self._json(dependencies.delete_preset(name))
            elif path == "/api/clear-history":
                self._json(dependencies.clear_history())
            elif path == "/api/save-config":
                with dependencies.app_state.config_lock:
                    previous = dependencies.app_state.config_snapshot()
                    validated, errors = dependencies.validate_config(data, previous)
                    if errors:
                        self._json(
                            {"error": f"无效设置: {', '.join(errors)}"}, status=400
                        )
                        return
                    dependencies.app_state.replace_config(validated)
                    try:
                        dependencies.save_config()
                    except Exception as exc:
                        dependencies.app_state.replace_config(previous)
                        self._json({"error": f"保存设置失败: {exc}"}, status=500)
                        return
                self._json({"ok": True})
            elif path == "/api/reset-config":
                with dependencies.app_state.config_lock:
                    previous = dependencies.app_state.config_snapshot()
                    dependencies.app_state.replace_config(dependencies.default_config)
                    try:
                        dependencies.save_config()
                    except Exception as exc:
                        dependencies.app_state.replace_config(previous)
                        self._json({"error": f"重置设置失败: {exc}"}, status=500)
                        return
                self._json({"ok": True})
            elif path == "/api/tool":
                action = self._field(data, "action", str, "")
                if action is not None:
                    self._json(dependencies.handle_tool_action(action))
            elif path == "/api/browse-folder":
                self._json(dependencies.browse_folder())
            elif path == "/api/update-ytdlp":
                self._json(dependencies.update_ytdlp())
            elif path == "/api/clean-temp":
                self._json(dependencies.clean_temp())
            elif path == "/api/gen-template":
                self._json(dependencies.gen_url_template())
            elif path == "/api/wav2mp3":
                directory = self._field(data, "dir", str, "")
                if directory is None:
                    return
                recursive = self._field(data, "recursive", bool, False)
                if recursive is None:
                    return
                bitrate = self._field(data, "bitrate", int, 320)
                if bitrate is None:
                    return
                del_src = self._field(data, "del_src", bool, False)
                if del_src is None:
                    return
                self._json(
                    dependencies.wav_to_mp3(directory, recursive, bitrate, del_src)
                )
            elif path == "/api/audio-loudnorm":
                directory = self._field(data, "dir", str, "")
                if directory is None:
                    return
                recursive = self._field(data, "recursive", bool, False)
                if recursive is None:
                    return
                mode = self._field(data, "mode", str, "single")
                if mode is None:
                    return
                i_target = self._field(data, "i_target", (int, float), -24)
                if i_target is None:
                    return
                lra_target = self._field(data, "lra_target", (int, float), 7)
                if lra_target is None:
                    return
                tp_target = self._field(data, "tp_target", (int, float), -2)
                if tp_target is None:
                    return
                output_dir = self._field(data, "output_dir", str, "")
                if output_dir is None:
                    return
                output_format = self._field(data, "output_format", str, "")
                if output_format is None:
                    return
                self._json(
                    dependencies.audio_loudnorm(
                        directory,
                        recursive,
                        mode,
                        i_target,
                        lra_target,
                        tp_target,
                        output_dir,
                        output_format,
                    )
                )
            elif path == "/api/audio-volume":
                directory = self._field(data, "dir", str, "")
                if directory is None:
                    return
                recursive = self._field(data, "recursive", bool, False)
                if recursive is None:
                    return
                gain_db = self._field(data, "gain_db", (int, float), 0)
                if gain_db is None:
                    return
                limiter_enabled = self._field(data, "limiter_enabled", bool, True)
                if limiter_enabled is None:
                    return
                output_dir = self._field(data, "output_dir", str, "")
                if output_dir is None:
                    return
                output_format = self._field(data, "output_format", str, "")
                if output_format is None:
                    return
                self._json(
                    dependencies.audio_volume(
                        directory,
                        recursive,
                        gain_db,
                        limiter_enabled,
                        output_dir,
                        output_format,
                    )
                )
            elif path == "/api/do-update":
                self._json(dependencies.updater.do_update())
            elif path == "/api/exit":
                self._json({"ok": True})
                threading.Thread(target=self._request_exit, daemon=True).start()
            else:
                self.send_error(404)

        def _field(self, data: JsonDict, name: str, expected_type: ExpectedFieldType, default: Any) -> Any:
            value = data.get(name, default)
            # bool is a subclass of int — reject it for numeric types
            if isinstance(value, bool):
                expected_types = expected_type if isinstance(expected_type, tuple) else (expected_type,)
                if int in expected_types or float in expected_types:
                    self._json({"error": f"字段 {name} 类型错误"}, status=400)
                    return None
            if not isinstance(value, expected_type):
                self._json({"error": f"字段 {name} 类型错误"}, status=400)
                return None
            return value

        def _request_exit(self) -> None:
            time.sleep(0.5)
            dependencies.request_exit()

        def _json(self, obj: Any, status: int = 200) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(json.dumps(obj, ensure_ascii=False).encode("utf-8"))

    return RequestHandler


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    block_on_close = False
    allow_reuse_address = True

    def __init__(self, *args: Any, **kwargs: Any):
        self.stop_event = threading.Event()
        super().__init__(*args, **kwargs)


class HttpService:
    def __init__(self, handler_factory: Callable[[], type[BaseHTTPRequestHandler]], host: str = "127.0.0.1", port: int = 0):
        self._handler_factory = handler_factory
        self._host = host
        self._requested_port = port
        self._server: ThreadedHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int | None:
        if self._server is None:
            return None
        return self._server.server_address[1]

    @property
    def url(self) -> str | None:
        if self.port is None:
            return None
        return f"http://{self._host}:{self.port}"

    def start(self) -> str | None:
        if self._server is not None:
            return self.url
        self._server = ThreadedHTTPServer(
            (self._host, self._requested_port),
            self._handler_factory(),
        )
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self.url

    def stop(self) -> None:
        if self._server is None:
            return
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        # 先通知 SSE 循环退出，再关闭监听并等待服务线程，避免长连接拖住停机。
        server.stop_event.set()
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join()
