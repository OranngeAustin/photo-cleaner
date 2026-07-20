import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Literal, List

import uvicorn
import webview
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel
from send2trash import send2trash

from backend.scanner import Scanner, clear_thumbnail_cache


logger = logging.getLogger(__name__)
PROJECT_DIR = Path(__file__).resolve().parent


def _resource_dir() -> Path:
    """Return the source directory or PyInstaller's unpacked data directory."""
    return Path(getattr(sys, "_MEIPASS", PROJECT_DIR))


app = FastAPI()
thumbnail_scanner = Scanner()
scan_lock = threading.Lock()
active_scanner: Scanner | None = None
allowed_scan_root: str | None = None
allowed_result_paths_by_mode: dict[str, set[str]] = {
    "exact": set(),
    "similar": set(),
}

# In-memory storage for scan results to stream to the frontend.
scan_state = {
    "status": "idle",
    "message": "",
    "progress": {},
    "done": False,
    "cancelled": False,
    "results": {"exact": [], "similar": []},
}


class ScanRequest(BaseModel):
    directory: str
    mode: Literal["exact", "similar"]


class DeleteRequest(BaseModel):
    files: List[str]


class Api:
    def choose_directory(self):
        if webview.windows:
            result = webview.windows[0].create_file_dialog(webview.FileDialog.FOLDER)
            if result:
                return result[0]
        return None


api = Api()


def _resolve_path(path: str) -> str:
    return os.path.realpath(os.path.abspath(path))


def _path_key(path: str) -> str:
    return os.path.normcase(_resolve_path(path))


def is_path_allowed(path: str) -> bool:
    """Check whether a path stays inside the selected scan root."""
    with scan_lock:
        root = allowed_scan_root
    if not root:
        return False
    try:
        real_path = _resolve_path(path)
        return os.path.normcase(os.path.commonpath([real_path, root])) == os.path.normcase(root)
    except (TypeError, ValueError, OSError):
        return False


def is_result_path_allowed(path: str) -> bool:
    """Only expose files returned by an active scan result for the selected root."""
    if not is_path_allowed(path):
        return False
    try:
        path_key = _path_key(path)
    except (TypeError, ValueError, OSError):
        return False
    with scan_lock:
        return any(path_key in paths for paths in allowed_result_paths_by_mode.values())


def _read_capture_time(path: str) -> str | None:
    """Read a displayable capture time from EXIF without decoding pixel data."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            raw_value = next(
                (exif.get(tag) for tag in (36867, 36868, 306) if exif.get(tag)),
                None,
            )
    except (OSError, SyntaxError, UnidentifiedImageError):
        return None

    if raw_value is None:
        return None
    value = str(raw_value).strip()
    for source_format in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(value, source_format).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return value or None


def _collect_result_path_keys(results: dict, mode: str) -> set[str]:
    return {
        _path_key(path)
        for group in results.get(mode, [])
        for path in group
    }


@app.post("/api/scan")
def start_scan(req: ScanRequest):
    global active_scanner, allowed_scan_root

    if not os.path.isdir(req.directory):
        return JSONResponse({"error": "Invalid directory"}, status_code=400)

    scan_root = _resolve_path(req.directory)
    scan_job = Scanner()
    with scan_lock:
        if active_scanner is not None:
            return JSONResponse({"error": "A scan is already running"}, status_code=409)

        active_scanner = scan_job
        if allowed_scan_root is None or os.path.normcase(allowed_scan_root) != os.path.normcase(scan_root):
            for paths in allowed_result_paths_by_mode.values():
                paths.clear()
        allowed_scan_root = scan_root
        scan_state["status"] = "scanning"
        scan_state["message"] = f"Initializing {req.mode} scan..."
        scan_state["progress"] = {}
        scan_state["done"] = False
        scan_state["cancelled"] = False
        scan_state["results"] = {"exact": [], "similar": []}
    clear_thumbnail_cache()

    def callback(event_type: str, data: dict) -> None:
        global active_scanner
        with scan_lock:
            if active_scanner is not scan_job:
                return
            if event_type == 'status':
                scan_state["message"] = data["message"]
            elif event_type == 'progress':
                scan_state["progress"] = data
            elif event_type == 'done':
                scan_state["results"] = data
                scan_state["cancelled"] = data.get("cancelled", False)
                scan_state["message"] = data.get("error", scan_state["message"])
                allowed_result_paths_by_mode[req.mode] = _collect_result_path_keys(data, req.mode)
                scan_state["status"] = "idle"
                active_scanner = None
                scan_state["done"] = True  # Frontend treats this as an atomic completion marker.

    threading.Thread(
        target=scan_job.scan_directory,
        args=(scan_root, req.mode, callback),
        daemon=True,
    ).start()
    return {"status": "started"}


@app.get("/api/scan_status")
def get_scan_status():
    with scan_lock:
        return dict(scan_state)


@app.post("/api/cancel_scan")
def cancel_scan():
    with scan_lock:
        scan_job = active_scanner
    if scan_job is None:
        return {"status": "idle"}
    scan_job.cancel()
    return {"status": "cancelling"}


@app.post("/api/delete")
def delete_files(req: DeleteRequest):
    success: list[str] = []
    errors: list[str] = []
    for requested_path in req.files:
        try:
            real_path = _resolve_path(requested_path)
            if not is_result_path_allowed(real_path) or not os.path.isfile(real_path):
                errors.append(requested_path)
                continue
            send2trash(real_path)
            success.append(requested_path)
            with scan_lock:
                path_key = _path_key(real_path)
                for paths in allowed_result_paths_by_mode.values():
                    paths.discard(path_key)
        except Exception:
            logger.warning("Failed to delete file: %s", requested_path, exc_info=True)
            errors.append(requested_path)

    if success:
        clear_thumbnail_cache()
    return {"deleted": success, "errors": errors}


@app.get("/api/thumbnail")
def get_thumbnail(path: str):
    if not is_result_path_allowed(path):
        return Response(status_code=403)
    real_path = _resolve_path(path)
    if not os.path.isfile(real_path):
        return Response(status_code=404)
    image_bytes = thumbnail_scanner.generate_thumbnail(real_path)
    if not image_bytes:
        return Response(status_code=500)
    return Response(content=image_bytes, media_type="image/jpeg")


@app.get("/api/image")
def get_image(path: str):
    if not is_result_path_allowed(path):
        return Response(status_code=403)
    real_path = _resolve_path(path)
    if not os.path.isfile(real_path):
        return Response(status_code=404)
    return FileResponse(real_path)


@app.get("/api/photo_info")
def get_photo_info(path: str):
    """Return lightweight metadata only for a photo from the current scan results."""
    if not is_result_path_allowed(path):
        return Response(status_code=403)
    real_path = _resolve_path(path)
    try:
        size_bytes = os.stat(real_path).st_size
    except OSError:
        return Response(status_code=404)
    return {
        "name": Path(real_path).name,
        "captured_at": _read_capture_time(real_path),
        "size_bytes": size_bytes,
    }


# Resolve static assets from this file, not the caller's current working directory.
app.mount("/", StaticFiles(directory=str(_resource_dir() / "web"), html=True), name="web")


def _server_url_when_ready(server: uvicorn.Server, timeout_seconds: float = 8.0) -> str | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if server.started:
            for instance in getattr(server, "servers", []):
                sockets = getattr(instance, "sockets", None) or []
                if sockets:
                    host, port = sockets[0].getsockname()[:2]
                    return f"http://{host}:{port}"
        time.sleep(0.05)
    return None


if __name__ == '__main__':
    # Port zero asks the operating system for an unused loopback port.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    server_url = _server_url_when_ready(server)
    if server_url is None:
        server.should_exit = True
        raise RuntimeError("Photo Cleaner server did not become ready within 8 seconds")

    webview.create_window('Photo Cleaner UI', server_url, width=1200, height=800, js_api=api)
    webview.start()
