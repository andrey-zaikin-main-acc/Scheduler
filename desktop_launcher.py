"""Desktop launcher for the DrawPPT Streamlit application."""

from __future__ import annotations

import multiprocessing
import os
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

APP_TITLE = "DrawPPT"
STARTUP_TIMEOUT_SECONDS = 60


def resource_path(*parts: str) -> Path:
    """Resolve a bundled or source-tree resource path."""
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path.joinpath(*parts)


def find_free_port() -> int:
    """Return an available localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def run_streamlit(port: int) -> None:
    """Run Streamlit on localhost for the desktop window."""
    os.environ["DRAWPPT_DESKTOP"] = "1"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"
    app_path = resource_path("app", "main.py")
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
    from streamlit.web.cli import main as streamlit_main

    streamlit_main()


def wait_for_server(url: str, process: multiprocessing.Process) -> None:
    """Wait until the Streamlit server responds or raise a useful error."""
    deadline = time.monotonic() + STARTUP_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if not process.is_alive():
            raise RuntimeError("Streamlit server process exited before the application window could open.")
        try:
            with urllib.request.urlopen(url, timeout=1.0) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
        time.sleep(0.25)
    raise RuntimeError(f"Streamlit server did not become ready at {url}: {last_error}")


def stop_process(process: multiprocessing.Process) -> None:
    """Terminate the Streamlit process and ensure no child process remains."""
    if not process.is_alive():
        return
    process.terminate()
    process.join(timeout=10)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)


def show_error(message: str) -> None:
    """Show a clear startup error to the user."""
    try:
        import webview

        webview.create_window(f"{APP_TITLE} — startup error", html=f"<pre>{message}</pre>", width=900, height=500)
        webview.start()
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    """Start the local Streamlit server and host it in a native window."""
    multiprocessing.freeze_support()
    port = find_free_port()
    url = f"http://127.0.0.1:{port}"
    server_process = multiprocessing.Process(target=run_streamlit, args=(port,), name="DrawPPTStreamlit")
    server_process.start()
    try:
        wait_for_server(url, server_process)
        import webview

        webview.create_window(APP_TITLE, url=url, width=1400, height=900)
        webview.start()
        return 0
    except Exception:
        show_error(traceback.format_exc())
        return 1
    finally:
        stop_process(server_process)


if __name__ == "__main__":
    raise SystemExit(main())
