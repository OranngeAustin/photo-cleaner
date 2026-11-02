import logging
import os
import stat
import sys
import threading
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Literal, List

import uvicorn
import webview
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import ExifTags, Image, UnidentifiedImageError
from pydantic import BaseModel
from send2trash import send2trash

from backend.scanner import Scanner, clear_thumbnail_cache


logger = logging.getLogger(__name__)
PROJECT_DIR = Path(__file__).resolve().parent


def _resource_dir() -> Path:
    """Return the source directory or PyInstaller's unpacked data directory."""
    return Path(getattr(sys, "_MEIPASS", PROJECT_DIR))


# The server only listens on 127.0.0.1, but a browser can still be steered at
# it.  DNS rebinding: a page on attacker.example re-points its own name at
# 127.0.0.1 and then calls this API as a same-origin page; its requests still
# carry "Host: attacker.example".  Any other site can also post straight to
# http://127.0.0.1:<port>; those requests carry that site's Origin.
TRUSTED_HOSTS = frozenset({"127.0.0.1", "localhost"})


def _host_name(host_header: str) -> str:
    """Return the lower-cased host name of a Host header, without the port."""
    host = host_header.strip().lower()
    if host.startswith("["):
        return host[1:host.find("]")] if "]" in host else host
    return host.split(":", 1)[0]


def _is_trusted_request(headers: dict[str, str]) -> bool:
    host = headers.get("host", "")
    if _host_name(host) not in TRUSTED_HOSTS:
        return False
    # Browsers send Origin on cross-origin requests and on same-origin POSTs;
    # the app's own page always sends exactly its own origin.
    origin = headers.get("origin")
    return origin is None or origin.strip().lower() == f"http://{host.strip().lower()}"


class LocalRequestGuard:
    """Reject HTTP requests that did not come from the app's own page."""

    def __init__(self, asgi_app):
        self.app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {
                name.decode("latin-1").lower(): value.decode("latin-1")
                for name, value in scope["headers"]
            }
            if not _is_trusted_request(headers):
                logger.warning(
                    "Rejected request with Host %r and Origin %r",
                    headers.get("host"),
                    headers.get("origin"),
                )
                await PlainTextResponse("Forbidden", status_code=403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


# The app's own page never uses the generated API docs (L15).
app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(LocalRequestGuard)
thumbnail_scanner = Scanner()
scan_lock = threading.Lock()
SCAN_FAILED_MESSAGE = "Scan failed. Check the application log for details."
active_scanner: Scanner | None = None
allowed_scan_root: str | None = None
allowed_result_paths_by_mode: dict[str, set[str]] = {
    "exact": set(),
    "similar": set(),
}
# (size, mtime_ns) of each result path when its scan finished, keyed like
# allowed_result_paths_by_mode; None if the file could not be read then.
result_fingerprints_by_mode: dict[str, dict[str, tuple[int, int] | None]] = {
    "exact": {},
    "similar": {},
}

# In-memory storage for scan results to stream to the frontend.
scan_state = {
    "status": "idle",
    "message": "",
    "progress": {},
    "done": False,
    "cancelled": False,
    "results": {"exact": [], "similar": []},
    "recycle_bin_available": True,
}


class ScanRequest(BaseModel):
    directory: str
    mode: Literal["exact", "similar"]


class DeleteRequest(BaseModel):
    files: List[str]
    # The user agreed to delete files that cannot go to the Recycle Bin.
    permanent: bool = False


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


# DateTimeOriginal and DateTimeDigitized, then IFD0's DateTime (last modified).
_CAPTURE_TIME_TAGS = (36867, 36868)
_MODIFIED_TIME_TAG = 306


def _read_capture_time(path: str) -> str | None:
    """Read a displayable capture time from EXIF without decoding pixel data."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            # The capture tags belong in the Exif sub-IFD; getexif() itself
            # only holds IFD0, where DateTime is the last-modified time.
            try:
                exif_ifd = exif.get_ifd(ExifTags.IFD.Exif)
            except Exception:  # A malformed sub-IFD must not hide IFD0.
                logger.debug("Unreadable Exif sub-IFD: %s", path, exc_info=True)
                exif_ifd = {}
            candidates = [exif_ifd.get(tag) for tag in _CAPTURE_TIME_TAGS]
            # Some writers put the capture tags in IFD0 instead.
            candidates += [exif.get(tag) for tag in (*_CAPTURE_TIME_TAGS, _MODIFIED_TIME_TAG)]
            raw_value = next((value for value in candidates if value), None)
    except (OSError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError):
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


def _iter_result_path_keys(results: dict, mode: str):
    """Yield ``(absolute_path, _path_key(path))`` for every result path.

    Each directory is resolved once; see ``_collect_result_path_keys``.
    """
    # Maps a directory to its resolved path, ending in a separator.
    resolved_prefixes: dict[str, str] = {}
    for group in results.get(mode, []):
        for path in group:
            absolute_path = os.path.abspath(path)
            directory, name = os.path.split(absolute_path)
            if not name or os.path.islink(absolute_path):
                yield absolute_path, _path_key(path)
                continue
            prefix = resolved_prefixes.get(directory)
            if prefix is None:
                prefix = os.path.join(os.path.realpath(directory), "")
                resolved_prefixes[directory] = prefix
            yield absolute_path, os.path.normcase(prefix + name)


def _collect_result_path_keys(results: dict, mode: str) -> set[str]:
    """Return ``_path_key`` for every result path, resolving each directory once.

    For a path whose last component is not a symlink,
    ``realpath(dir/name) == realpath(dir)/name``.  Results share a small set of
    directories, so caching the directory resolution replaces one realpath per
    file (several lstat calls, or a handle open on Windows) with one per folder.
    """
    return {path_key for _, path_key in _iter_result_path_keys(results, mode)}


def _file_fingerprint(path: str) -> tuple[int, int] | None:
    try:
        stat_result = os.stat(path)
    except OSError:
        return None
    return stat_result.st_size, stat_result.st_mtime_ns


def _collect_result_fingerprints(results: dict, mode: str) -> dict[str, tuple[int, int] | None]:
    """Map each result's ``_path_key`` to its current ``(size, mtime_ns)``."""
    return {
        path_key: _file_fingerprint(absolute_path)
        for absolute_path, path_key in _iter_result_path_keys(results, mode)
    }


def _matches_scan_fingerprint(path: str) -> bool:
    """Whether ``path`` still has the size and mtime it had when its scan finished.

    A sync tool or editor may have replaced the file with different content
    since then; deleting it would remove something the user never reviewed.
    """
    path_key = _path_key(path)
    with scan_lock:
        recorded = [
            fingerprints[path_key]
            for fingerprints in result_fingerprints_by_mode.values()
            if path_key in fingerprints
        ]
    if not recorded:
        # Every scan result gets a fingerprint when its scan finishes, so only
        # a whitelist filled in some other way (as tests do) lacks one.
        return True
    current = _file_fingerprint(path)
    return current is not None and current in recorded


# Windows has no Recycle Bin on removable drives, network shares or RAM disks,
# the user can turn it off, and a file larger than the bin does not fit.  In
# each case send2trash deletes the file permanently without saying so (Q1).
_DRIVE_FIXED = 3
_RECYCLE_BIN_VOLUMES_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\BitBucket\Volume"
_EXPLORER_POLICIES_KEY = r"Software\Microsoft\Windows\CurrentVersion\Policies\Explorer"

if os.name == "nt":
    import ctypes
    import winreg
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetVolumePathNameW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    _kernel32.GetVolumePathNameW.restype = wintypes.BOOL
    _kernel32.GetVolumeNameForVolumeMountPointW.argtypes = (wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD)
    _kernel32.GetVolumeNameForVolumeMountPointW.restype = wintypes.BOOL
    _kernel32.GetDriveTypeW.argtypes = (wintypes.LPCWSTR,)
    _kernel32.GetDriveTypeW.restype = wintypes.UINT


def _volume_root(path: str) -> str | None:
    """Return the root of the volume holding ``path``, e.g. ``D:\\``."""
    buffer = ctypes.create_unicode_buffer(32768)
    if not _kernel32.GetVolumePathNameW(path, buffer, len(buffer)):
        return None
    return buffer.value


def _drive_type(volume_root: str) -> int:
    return _kernel32.GetDriveTypeW(volume_root)


def _registry_number(root_key, sub_key: str, name: str) -> int | None:
    try:
        with winreg.OpenKey(root_key, sub_key) as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return None
    return value if isinstance(value, int) else None


def _recycle_bin_settings(volume_root: str) -> tuple[bool, int | None]:
    """Return whether the bin is turned off, and its size limit in bytes."""
    for root_key in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        if _registry_number(root_key, _EXPLORER_POLICIES_KEY, "NoRecycleFiles"):
            return True, None
    buffer = ctypes.create_unicode_buffer(64)
    if not _kernel32.GetVolumeNameForVolumeMountPointW(volume_root, buffer, len(buffer)):
        return False, None
    # "\\?\Volume{GUID}\" keeps its settings under "...\Volume\{GUID}"; a
    # drive whose settings were never changed has no key and uses defaults.
    guid_start = buffer.value.find("{")
    if guid_start < 0:
        return False, None
    volume_key = _RECYCLE_BIN_VOLUMES_KEY + "\\" + buffer.value[guid_start:].rstrip("\\")
    turned_off = _registry_number(winreg.HKEY_CURRENT_USER, volume_key, "NukeOnDelete")
    capacity_mb = _registry_number(winreg.HKEY_CURRENT_USER, volume_key, "MaxCapacity")
    return bool(turned_off), capacity_mb * 1024 * 1024 if capacity_mb else None


def _recycle_bin_available(path: str, size: int = 0) -> bool:
    """Whether send2trash would put a file of ``size`` bytes at ``path`` in the Recycle Bin."""
    if os.name != "nt":
        return True
    volume_root = _volume_root(path)
    if volume_root is None or _drive_type(volume_root) != _DRIVE_FIXED:
        return False
    turned_off, capacity = _recycle_bin_settings(volume_root)
    return not turned_off and (capacity is None or size <= capacity)


def _delete_permanently(path: str) -> None:
    try:
        os.remove(path)
    except PermissionError:
        # Windows will not delete a read-only file; the Recycle Bin path
        # takes such files, so this one does too.
        if os.access(path, os.W_OK):
            raise
        os.chmod(path, stat.S_IWRITE)
        os.remove(path)


@app.post("/api/scan")
def start_scan(req: ScanRequest):
    global active_scanner, allowed_scan_root

    if not os.path.isdir(req.directory):
        return JSONResponse({"error": "Invalid directory"}, status_code=400)

    scan_root = _resolve_path(req.directory)
    recycle_bin_available = _recycle_bin_available(scan_root)
    scan_job = Scanner()
    with scan_lock:
        if active_scanner is not None:
            return JSONResponse({"error": "A scan is already running"}, status_code=409)

        active_scanner = scan_job
        if allowed_scan_root is None or os.path.normcase(allowed_scan_root) != os.path.normcase(scan_root):
            for paths in allowed_result_paths_by_mode.values():
                paths.clear()
            for fingerprints in result_fingerprints_by_mode.values():
                fingerprints.clear()
        allowed_scan_root = scan_root
        scan_state["status"] = "scanning"
        scan_state["message"] = f"Initializing {req.mode} scan..."
        scan_state["progress"] = {}
        scan_state["done"] = False
        scan_state["cancelled"] = False
        scan_state["results"] = {"exact": [], "similar": []}
        # The page asks before staging a delete that cannot be undone.
        scan_state["recycle_bin_available"] = recycle_bin_available
    clear_thumbnail_cache()

    def callback(event_type: str, data: dict) -> None:
        global active_scanner
        fingerprints: dict[str, tuple[int, int] | None] = {}
        if event_type == 'done':
            # Resolving and stat-ing every result is file-system work; finish
            # it before taking scan_lock so status polls never wait on it.
            fingerprints = _collect_result_fingerprints(data, req.mode)
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
                allowed_result_paths_by_mode[req.mode] = set(fingerprints)
                result_fingerprints_by_mode[req.mode] = fingerprints
                scan_state["status"] = "idle"
                active_scanner = None
                scan_state["done"] = True  # Frontend treats this as an atomic completion marker.

    def run_scan() -> None:
        global active_scanner
        try:
            scan_job.scan_directory(scan_root, req.mode, callback)
        finally:
            # The scanner always reports done, but if handling that report
            # failed, release the job here: otherwise every later scan is
            # refused with 409 until the app restarts.
            with scan_lock:
                if active_scanner is scan_job:
                    active_scanner = None
                    scan_state["results"] = {"exact": [], "similar": [], "error": SCAN_FAILED_MESSAGE}
                    scan_state["message"] = SCAN_FAILED_MESSAGE
                    scan_state["cancelled"] = False
                    scan_state["status"] = "idle"
                    scan_state["done"] = True

    threading.Thread(target=run_scan, daemon=True).start()
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
    # Refused because they cannot go to the Recycle Bin and the request did
    # not say the user agreed to delete them permanently.
    no_recycle_bin: list[str] = []
    for requested_path in req.files:
        try:
            # Trashing a symlink would resolve to, and remove, a different file
            # than the one the user selected.
            if os.path.islink(os.path.abspath(requested_path)):
                errors.append(requested_path)
                continue
            real_path = _resolve_path(requested_path)
            if not is_result_path_allowed(real_path) or not os.path.isfile(real_path):
                errors.append(requested_path)
                continue
            if not _matches_scan_fingerprint(real_path):
                logger.warning("File changed since the scan, not deleting: %s", requested_path)
                errors.append(requested_path)
                continue
            if _recycle_bin_available(real_path, os.path.getsize(real_path)):
                send2trash(real_path)
            elif req.permanent:
                _delete_permanently(real_path)
            else:
                logger.warning("No Recycle Bin for this file, not deleting it without consent: %s", requested_path)
                errors.append(requested_path)
                no_recycle_bin.append(requested_path)
                continue
            success.append(requested_path)
            # Resolve before taking the lock: realpath touches the file system.
            path_key = _path_key(real_path)
            with scan_lock:
                for paths in allowed_result_paths_by_mode.values():
                    paths.discard(path_key)
                for fingerprints in result_fingerprints_by_mode.values():
                    fingerprints.pop(path_key, None)
        except Exception:
            logger.warning("Failed to delete file: %s", requested_path, exc_info=True)
            errors.append(requested_path)

    # The thumbnail cache is not cleared here: its key includes each file's
    # size and mtime, and deleted paths are no longer allowed anyway.
    response = {"deleted": success, "errors": errors}
    if no_recycle_bin:
        response["no_recycle_bin"] = no_recycle_bin
    return response


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


def _ensure_std_streams() -> None:
    """Give console-less builds (pythonw, ``pyinstaller -w``) writable std streams.

    Without a console, ``sys.stdout`` and ``sys.stderr`` are ``None``, and
    uvicorn's default logging config calls ``sys.stdout.isatty()`` while it
    builds its formatter, which aborts start-up before the window can open.
    """
    for stream_name in ("stdout", "stderr"):
        if getattr(sys, stream_name) is None:
            setattr(sys, stream_name, open(os.devnull, "w", encoding="utf-8"))


LOG_FILE_NAME = "photo-cleaner.log"


def _default_log_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    return Path(local_app_data) / "PhotoCleaner" if local_app_data else Path.home() / ".photo-cleaner"


def _configure_logging(log_dir: str | os.PathLike | None = None) -> Path | None:
    """Send warnings to the console and to a small rotating log file.

    A windowed build has no console, so without the file every warning
    (rejected requests, failed deletes, a server that never started) is lost.
    Returns the log file's path, or None if it could not be created.
    """
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formatter)
    root.addHandler(console)

    log_path = Path(log_dir or _default_log_dir()) / LOG_FILE_NAME
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    except OSError:
        logger.warning("Cannot write the log file %s", log_path, exc_info=True)
        return None
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    return log_path


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
    _ensure_std_streams()
    _configure_logging()
    # Port zero asks the operating system for an unused loopback port.  With
    # log_config=None uvicorn's own errors reach the handlers set up above.
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error", log_config=None))
    server_thread = threading.Thread(target=server.run, daemon=True)
    server_thread.start()

    server_url = _server_url_when_ready(server)
    if server_url is None:
        server.should_exit = True
        logger.error("Photo Cleaner server did not become ready within 8 seconds")
        raise RuntimeError("Photo Cleaner server did not become ready within 8 seconds")

    webview.create_window('Photo Cleaner UI', server_url, width=1200, height=800, js_api=api)
    webview.start()
