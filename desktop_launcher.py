"""Desktop launcher for the DrawPPT Streamlit application."""

from __future__ import annotations

import datetime as dt
import html
import multiprocessing
import os
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import MutableMapping

APP_TITLE = "DrawPPT"
STARTUP_TIMEOUT_SECONDS = 60
LOCALHOST_NO_PROXY_HOSTS = ("127.0.0.1", "localhost")


def resource_path(*parts: str) -> Path:
    """Resolve a bundled or source-tree resource path."""
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path.joinpath(*parts)


def get_log_dir() -> Path:
    """Return the per-user DrawPPT log directory."""
    local_app_data = os.environ.get("LOCALAPPDATA")
    base_dir = Path(local_app_data) if local_app_data else Path.home() / "AppData" / "Local"
    return base_dir / APP_TITLE / "logs"


def timestamp() -> str:
    """Return an ISO-like local timestamp for log lines."""
    return dt.datetime.now().isoformat(timespec="seconds")


def append_log(log_path: Path, message: str) -> None:
    """Append a message to a log file, creating the directory when needed."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(f"[{timestamp()}] {message}\n")


def merge_no_proxy_value(existing_value: str | None) -> str:
    """Return a NO_PROXY/no_proxy value that includes localhost entries."""
    entries: list[str] = []
    seen: set[str] = set()
    for value in (existing_value or "").split(","):
        value = value.strip()
        if value and value.lower() not in seen:
            entries.append(value)
            seen.add(value.lower())
    for host in LOCALHOST_NO_PROXY_HOSTS:
        if host.lower() not in seen:
            entries.append(host)
            seen.add(host.lower())
    return ",".join(entries)


def ensure_localhost_no_proxy(env: MutableMapping[str, str] | None = None) -> None:
    """Ensure localhost requests bypass configured proxies for this process and children."""
    target_env = os.environ if env is None else env
    target_env["NO_PROXY"] = merge_no_proxy_value(target_env.get("NO_PROXY"))
    target_env["no_proxy"] = merge_no_proxy_value(target_env.get("no_proxy"))


def find_free_port() -> int:
    """Return an available localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def redirect_streamlit_output(streamlit_log_path: Path) -> None:
    """Redirect child stdout and stderr to the Streamlit log file."""
    streamlit_log_path.parent.mkdir(parents=True, exist_ok=True)
    log_handle = streamlit_log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = log_handle
    sys.stderr = log_handle


def run_streamlit(port: int, streamlit_log_path: str, launcher_log_path: str) -> None:
    """Run Streamlit on localhost for the desktop window."""
    streamlit_log = Path(streamlit_log_path)
    launcher_log = Path(launcher_log_path)
    redirect_streamlit_output(streamlit_log)
    try:
        append_log(streamlit_log, f"Starting Streamlit child process on port {port}.")
        os.environ["DRAWPPT_DESKTOP"] = "1"
        os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
        app_path = resource_path("app", "main.py").resolve()
        append_log(launcher_log, f"Bundled Streamlit app path: {app_path}")
        if not app_path.is_file():
            raise FileNotFoundError(f"Bundled Streamlit app file was not found: {app_path}")
        from app.services.bootstrap_service import initialize_desktop_database

        initialize_desktop_database()
        sys.argv = [
            "streamlit",
            "run",
            str(app_path),
            "--server.address=127.0.0.1",
            f"--server.port={port}",
            "--server.headless=true",
            "--browser.serverAddress=127.0.0.1",
            "--browser.gatherUsageStats=false",
            "--global.developmentMode=false",
            "--server.fileWatcherType=none",
        ]
        append_log(streamlit_log, "Invoking streamlit.web.cli.main().")
        from streamlit.web.cli import main as streamlit_main

        streamlit_main()
    except Exception:
        append_log(streamlit_log, "Unhandled exception in Streamlit child process:")
        traceback.print_exc(file=sys.stderr)
        raise


def create_localhost_healthcheck_opener() -> urllib.request.OpenerDirector:
    """Return an opener that ignores system proxies for localhost health checks."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def wait_for_server(health_url: str, process: multiprocessing.Process, launcher_log_path: Path) -> None:
    """Wait until the Streamlit health endpoint responds or raise a useful error."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None
    opener = create_localhost_healthcheck_opener()
    append_log(launcher_log_path, f"Waiting for Streamlit readiness at {health_url}.")
    while time.monotonic() < deadline:
        if not process.is_alive():
            exit_code = process.exitcode
            append_log(launcher_log_path, f"Streamlit process exited before readiness; exit_code={exit_code}.")
            raise RuntimeError("Streamlit server process exited before the application window could open.")
        try:
            with opener.open(health_url, timeout=1.0) as response:
                append_log(launcher_log_path, f"Readiness check returned HTTP {response.status}.")
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            append_log(launcher_log_path, f"Readiness check failed: {exc!r}.")
        time.sleep(0.25)
    raise RuntimeError(f"Streamlit server did not become ready at {health_url}: {last_error}")


def stop_process(process: multiprocessing.Process, launcher_log_path: Path) -> None:
    """Terminate the Streamlit process and ensure no child process remains."""
    if not process.is_alive():
        append_log(launcher_log_path, f"Streamlit process already stopped; exit_code={process.exitcode}.")
        return
    append_log(launcher_log_path, "Terminating Streamlit process.")
    process.terminate()
    process.join(timeout=10)
    if process.is_alive():
        append_log(launcher_log_path, "Killing Streamlit process after graceful termination timed out.")
        process.kill()
        process.join(timeout=5)
    append_log(launcher_log_path, f"Streamlit process final exit_code={process.exitcode}.")


def show_error(message: str) -> None:
    """Show a clear startup error to the user."""
    try:
        import webview

        safe_message = html.escape(message)
        webview.create_window(f"{APP_TITLE} — startup error", html=f"<pre>{safe_message}</pre>", width=900, height=500)
        webview.start()
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    """Start the local Streamlit server and host it in a native window."""
    multiprocessing.freeze_support()
    log_dir = get_log_dir()
    launcher_log_path = log_dir / "launcher.log"
    streamlit_log_path = log_dir / "streamlit.log"
    append_log(launcher_log_path, "Starting DrawPPT desktop launcher.")
    ensure_localhost_no_proxy()
    append_log(launcher_log_path, f"NO_PROXY={os.environ.get('NO_PROXY', '')}")
    append_log(launcher_log_path, f"no_proxy={os.environ.get('no_proxy', '')}")
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    health_url = f"{url}/_stcore/health"
    append_log(launcher_log_path, f"Selected port={port}; url={url}; health_url={health_url}.")
    server_process = multiprocessing.Process(
        target=run_streamlit,
        args=(port, str(streamlit_log_path), str(launcher_log_path)),
        name="DrawPPTStreamlit",
    )
    server_process.start()
    append_log(launcher_log_path, f"Started Streamlit process pid={server_process.pid}.")
    try:
        wait_for_server(health_url, server_process, launcher_log_path)
        append_log(launcher_log_path, f"Opening webview window at {url}.")
        import webview

        webview.create_window(APP_TITLE, url=url, width=1400, height=900)
        webview.start()
        append_log(launcher_log_path, "Webview window closed.")
        return 0
    except Exception as exc:
        append_log(launcher_log_path, "Launcher startup failed:")
        append_log(launcher_log_path, traceback.format_exc())
        show_error(
            f"DrawPPT не удалось запустить локальный сервер.\n\n"
            f"Причина: {exc}\n\n"
            f"Подробные логи:\n{log_dir}"
        )
        return 1
    finally:
        stop_process(server_process, launcher_log_path)


if __name__ == "__main__":
    raise SystemExit(main())
