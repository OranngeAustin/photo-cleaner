import asyncio
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from PIL import Image

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import main
from backend.scanner import Scanner


def _save_scan_state():
    return (
        main.allowed_scan_root,
        {mode: set(paths) for mode, paths in main.allowed_result_paths_by_mode.items()},
        main.active_scanner,
        dict(main.scan_state),
    )


def _restore_scan_state(saved_state):
    root, result_paths_by_mode, active_scanner, scan_state = saved_state
    with main.scan_lock:
        main.allowed_scan_root = root
        main.allowed_result_paths_by_mode = {
            mode: set(paths) for mode, paths in result_paths_by_mode.items()
        }
        main.active_scanner = active_scanner
        main.scan_state.clear()
        main.scan_state.update(scan_state)


def test_is_path_allowed(tmp_path):
    saved_state = _save_scan_state()
    try:
        image = tmp_path / "img.jpg"
        image.write_bytes(b"image")
        sibling = tmp_path.parent / f"{tmp_path.name}-sibling" / "img.jpg"

        main.allowed_scan_root = None
        assert main.is_path_allowed(str(image)) is False

        main.allowed_scan_root = str(tmp_path)
        assert main.is_path_allowed(str(image)) is True
        assert main.is_path_allowed(str(tmp_path / "nested" / "img.jpg")) is True
        assert main.is_path_allowed(str(sibling)) is False
    finally:
        _restore_scan_state(saved_state)


def test_only_scan_results_are_exposed_or_deletable(tmp_path, monkeypatch):
    saved_state = _save_scan_state()
    try:
        result_file = tmp_path / "result.jpg"
        other_file = tmp_path / "other.jpg"
        result_file.write_bytes(b"result")
        other_file.write_bytes(b"other")
        main.allowed_scan_root = str(tmp_path)
        main.allowed_result_paths_by_mode = {
            "exact": {main._path_key(str(result_file))},
            "similar": {main._path_key(str(result_file))},
        }

        assert main.is_result_path_allowed(str(result_file)) is True
        assert main.is_result_path_allowed(str(other_file)) is False

        sent_to_trash = []
        monkeypatch.setattr(main, "send2trash", lambda path: sent_to_trash.append(path))
        response = main.delete_files(main.DeleteRequest(files=[str(result_file), str(other_file), str(tmp_path)]))

        assert response["deleted"] == [str(result_file)]
        assert set(response["errors"]) == {str(other_file), str(tmp_path)}
        assert sent_to_trash == [main._resolve_path(str(result_file))]
        assert main.is_result_path_allowed(str(result_file)) is False
    finally:
        _restore_scan_state(saved_state)


def test_start_scan_rejects_a_second_active_job(tmp_path):
    saved_state = _save_scan_state()
    try:
        main.active_scanner = Scanner()
        response = main.start_scan(main.ScanRequest(directory=str(tmp_path), mode="exact"))
        assert response.status_code == 409
    finally:
        _restore_scan_state(saved_state)


def test_resource_dir_uses_pyinstaller_unpack_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(main.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert main._resource_dir() == tmp_path


def test_photo_info_returns_exif_capture_time_and_file_details(tmp_path):
    saved_state = _save_scan_state()
    try:
        photo = tmp_path / "summer trip.jpg"
        exif = Image.Exif()
        exif[36867] = "2024:05:06 07:08:09"
        Image.new("RGB", (2, 2), "white").save(photo, exif=exif)
        main.allowed_scan_root = str(tmp_path)
        main.allowed_result_paths_by_mode = {
            "exact": {main._path_key(str(photo))},
            "similar": set(),
        }

        response = main.get_photo_info(str(photo))

        assert response == {
            "name": "summer trip.jpg",
            "captured_at": "2024-05-06 07:08:09",
            "size_bytes": photo.stat().st_size,
        }
    finally:
        _restore_scan_state(saved_state)


def test_photo_info_hides_unavailable_metadata_and_rejects_non_results(tmp_path):
    saved_state = _save_scan_state()
    try:
        photo = tmp_path / "without-exif.jpg"
        other_photo = tmp_path / "not-a-result.jpg"
        Image.new("RGB", (2, 2), "white").save(photo)
        Image.new("RGB", (2, 2), "white").save(other_photo)
        main.allowed_scan_root = str(tmp_path)
        main.allowed_result_paths_by_mode = {
            "exact": {main._path_key(str(photo))},
            "similar": set(),
        }

        response = main.get_photo_info(str(photo))
        rejected_response = main.get_photo_info(str(other_photo))

        assert response["captured_at"] is None
        assert rejected_response.status_code == 403
    finally:
        _restore_scan_state(saved_state)


def test_result_from_other_cached_mode_remains_previewable_after_empty_rescan(tmp_path):
    saved_state = _save_scan_state()
    try:
        photo = tmp_path / "similar-result.jpg"
        Image.new("RGB", (32, 16), "white").save(photo)
        main.allowed_scan_root = str(tmp_path)
        main.allowed_result_paths_by_mode = {
            "exact": set(),
            "similar": {main._path_key(str(photo))},
        }

        # This mirrors an empty exact-mode rescan after the similar tab was cached.
        main.allowed_result_paths_by_mode["exact"] = main._collect_result_path_keys(
            {"exact": []}, "exact"
        )

        thumbnail_response = main.get_thumbnail(str(photo))
        image_response = main.get_image(str(photo))
        info_response = main.get_photo_info(str(photo))

        assert thumbnail_response.status_code == 200
        assert image_response.status_code == 200
        assert info_response["name"] == "similar-result.jpg"
    finally:
        _restore_scan_state(saved_state)


def test_delete_refuses_a_symlink_that_resolves_to_a_result_file(tmp_path, monkeypatch):
    saved_state = _save_scan_state()
    try:
        target = tmp_path / "a.jpg"
        target.write_bytes(b"photo")
        link = tmp_path / "b.jpg"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            pytest.skip("Creating symlinks requires extra privileges on this platform")
        main.allowed_scan_root = str(tmp_path)
        main.allowed_result_paths_by_mode = {
            "exact": {main._path_key(str(target))},
            "similar": set(),
        }

        sent_to_trash = []
        monkeypatch.setattr(main, "send2trash", lambda path: sent_to_trash.append(path))
        response = main.delete_files(main.DeleteRequest(files=[str(link)]))

        assert response == {"deleted": [], "errors": [str(link)]}
        assert sent_to_trash == []
        assert main.is_result_path_allowed(str(target)) is True
    finally:
        _restore_scan_state(saved_state)


def test_server_config_starts_without_console_streams():
    """pyinstaller -w / pythonw run with sys.stdout and sys.stderr set to None."""
    script = textwrap.dedent(
        """
        import sys
        sys.stdout = None
        sys.stderr = None
        import uvicorn
        import main
        main._ensure_std_streams()
        uvicorn.Config(main.app, host="127.0.0.1", port=0, log_level="error")
        sys.stdout.write("ok")
        """
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr


def _original_result_path_keys(results, mode):
    """The pre-optimisation definition, kept as the characterisation oracle."""
    return {main._path_key(path) for group in results.get(mode, []) for path in group}


def _try_symlink(link, target):
    try:
        os.symlink(target, link, target_is_directory=os.path.isdir(target))
    except (OSError, NotImplementedError):
        return False
    return True


def test_result_path_keys_match_per_file_realpath(tmp_path, monkeypatch):
    real_dir = tmp_path / "Real Photos" / "2024"
    real_dir.mkdir(parents=True)
    paths = []
    for index in range(6):
        photo = real_dir / f"IMG_{index}.JPG"
        photo.write_bytes(b"x")
        paths.append(str(photo))
    groups = [paths[:3], paths[3:]]

    linked_dir = tmp_path / "linked-dir"
    if _try_symlink(linked_dir, real_dir):
        groups.append([str(linked_dir / "IMG_0.JPG"), str(linked_dir / "IMG_1.JPG")])
    target_file = tmp_path / "target.jpg"
    target_file.write_bytes(b"t")
    if _try_symlink(tmp_path / "link.jpg", target_file):
        groups.append([str(tmp_path / "link.jpg"), str(target_file)])

    # Paths that disappeared after the scan, and relative paths.
    groups.append([str(real_dir / "gone.jpg"), str(tmp_path / "gone-dir" / "x.jpg")])
    monkeypatch.chdir(tmp_path)
    groups.append([os.path.join("Real Photos", "2024", "IMG_2.JPG"), os.path.join(".", "target.jpg")])

    results = {"exact": groups, "similar": [[paths[0], paths[5]]]}

    for mode in ("exact", "similar", "missing-mode"):
        assert main._collect_result_path_keys(results, mode) == _original_result_path_keys(results, mode)


def test_capture_time_prefers_the_exif_sub_ifd_over_the_modification_time(tmp_path):
    # M2: DateTimeOriginal lives in the Exif sub-IFD. IFD0's DateTime (306) is
    # the last-modified time and must only be a fallback.
    photo = tmp_path / "photo.jpg"
    exif = Image.Exif()
    exif[306] = "2030:01:01 00:00:00"
    exif.get_ifd(0x8769)[36867] = "2024:05:06 07:08:09"
    Image.new("RGB", (8, 8)).save(photo, exif=exif)

    assert main._read_capture_time(str(photo)) == "2024-05-06 07:08:09"


def test_capture_time_is_unknown_for_a_decompression_bomb(tmp_path, monkeypatch):
    photo = tmp_path / "huge.png"
    Image.new("RGB", (64, 64)).save(photo)
    # Pillow refuses to open images above twice this many pixels.
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)

    assert main._read_capture_time(str(photo)) is None


def test_delete_refuses_a_file_changed_since_the_scan(tmp_path, monkeypatch):
    # M8: a sync tool or editor can replace a result after the scan finished.
    saved_state = _save_scan_state()
    saved_fingerprints = {mode: dict(prints) for mode, prints in main.result_fingerprints_by_mode.items()}
    try:
        unchanged = tmp_path / "unchanged.jpg"
        resized = tmp_path / "resized.jpg"
        touched = tmp_path / "touched.jpg"
        for path in (unchanged, resized, touched):
            path.write_bytes(b"original")
        results = {"exact": [[str(unchanged), str(resized), str(touched)]], "similar": []}
        fingerprints = main._collect_result_fingerprints(results, "exact")
        main.allowed_scan_root = str(tmp_path)
        main.allowed_result_paths_by_mode = {"exact": set(fingerprints), "similar": set()}
        main.result_fingerprints_by_mode = {"exact": fingerprints, "similar": {}}

        resized.write_bytes(b"replaced with different content")
        stat_result = touched.stat()
        touched.write_bytes(b"ORIGINAL")  # same size, new content and mtime
        os.utime(touched, ns=(stat_result.st_atime_ns, stat_result.st_mtime_ns + 5_000_000_000))
        sent_to_trash = []
        monkeypatch.setattr(main, "send2trash", sent_to_trash.append)

        response = main.delete_files(main.DeleteRequest(files=[str(unchanged), str(resized), str(touched)]))

        assert response == {"deleted": [str(unchanged)], "errors": [str(resized), str(touched)]}
        assert sent_to_trash == [main._resolve_path(str(unchanged))]
    finally:
        _restore_scan_state(saved_state)
        main.result_fingerprints_by_mode = saved_fingerprints


def test_a_finished_scan_records_the_fingerprints_that_delete_checks(tmp_path, monkeypatch):
    saved_state = _save_scan_state()
    saved_fingerprints = {mode: dict(prints) for mode, prints in main.result_fingerprints_by_mode.items()}
    try:
        first = tmp_path / "a.jpg"
        second = tmp_path / "b.jpg"
        first.write_bytes(b"duplicate")
        second.write_bytes(b"duplicate")
        main.active_scanner = None
        assert main.start_scan(main.ScanRequest(directory=str(tmp_path), mode="exact")) == {"status": "started"}
        deadline = time.monotonic() + 10
        while not main.scan_state["done"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert main.scan_state["results"]["exact"] == [[str(first), str(second)]]

        second.write_bytes(b"edited after the scan")
        sent_to_trash = []
        monkeypatch.setattr(main, "send2trash", sent_to_trash.append)
        response = main.delete_files(main.DeleteRequest(files=[str(first), str(second)]))

        assert response == {"deleted": [str(first)], "errors": [str(second)]}
    finally:
        _restore_scan_state(saved_state)
        main.result_fingerprints_by_mode = saved_fingerprints


def _asgi_status(method, path, headers):
    """Send one request through the full ASGI stack and return its status."""
    sent = []
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": method, "scheme": "http", "path": path, "raw_path": path.encode(),
        "query_string": b"", "root_path": "",
        "headers": [(name.encode(), value.encode()) for name, value in headers.items()],
        "client": ("127.0.0.1", 50000), "server": ("127.0.0.1", 8000),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    asyncio.run(main.app(scope, receive, send))
    return sent[0]["status"]


@pytest.mark.parametrize(
    ("method", "path", "headers"),
    [
        # DNS rebinding: the attacker's name now resolves to 127.0.0.1.
        ("POST", "/api/cancel_scan", {"host": "attacker.example:8000", "origin": "http://attacker.example:8000"}),
        ("GET", "/api/scan_status", {"host": "attacker.example:8000"}),
        ("GET", "/", {"host": "attacker.example:8000"}),
        # Another site posting straight to the loopback port (L14).
        ("POST", "/api/cancel_scan", {"host": "127.0.0.1:8000", "origin": "http://evil.example"}),
        ("POST", "/api/cancel_scan", {"host": "127.0.0.1:8000", "origin": "null"}),
        ("POST", "/api/cancel_scan", {"host": "127.0.0.1:8000", "origin": "http://localhost:8000"}),
        ("GET", "/api/scan_status", {}),
    ],
)
def test_requests_from_other_hosts_or_origins_are_rejected(method, path, headers):
    # M11
    saved_state = _save_scan_state()
    try:
        main.active_scanner = None
        assert _asgi_status(method, path, headers) == 403
    finally:
        _restore_scan_state(saved_state)


@pytest.mark.parametrize(
    "headers",
    [
        {"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"},
        {"host": "127.0.0.1:8000"},
        {"host": "localhost:8000", "origin": "http://localhost:8000"},
    ],
)
def test_requests_from_the_app_page_are_accepted(headers):
    saved_state = _save_scan_state()
    try:
        main.active_scanner = None
        assert _asgi_status("POST", "/api/cancel_scan", headers) == 200
        assert _asgi_status("GET", "/api/scan_status", {"host": headers["host"]}) == 200
    finally:
        _restore_scan_state(saved_state)


def test_result_paths_are_resolved_outside_the_scan_lock(tmp_path, monkeypatch):
    """L1: realpath can block on a slow or network drive. While it runs under
    scan_lock, /api/scan_status and every file endpoint wait behind it."""
    saved_state = _save_scan_state()
    saved_fingerprints = {mode: dict(prints) for mode, prints in main.result_fingerprints_by_mode.items()}
    try:
        first = tmp_path / "a.jpg"
        second = tmp_path / "b.jpg"
        first.write_bytes(b"duplicate")
        second.write_bytes(b"duplicate")
        resolved_while_locked = []
        real_realpath = os.path.realpath

        def recording_realpath(path, *args, **kwargs):
            resolved_while_locked.append(main.scan_lock.locked())
            return real_realpath(path, *args, **kwargs)

        monkeypatch.setattr(main.os.path, "realpath", recording_realpath)
        main.active_scanner = None
        assert main.start_scan(main.ScanRequest(directory=str(tmp_path), mode="exact")) == {"status": "started"}
        deadline = time.monotonic() + 10
        while not main.scan_state["done"] and time.monotonic() < deadline:
            time.sleep(0.01)
        assert main.scan_state["results"]["exact"] == [[str(first), str(second)]]

        monkeypatch.setattr(main, "send2trash", lambda path: None)
        response = main.delete_files(main.DeleteRequest(files=[str(second)]))

        assert response == {"deleted": [str(second)], "errors": []}
        assert resolved_while_locked and not any(resolved_while_locked)
    finally:
        _restore_scan_state(saved_state)
        main.result_fingerprints_by_mode = saved_fingerprints


def test_a_scan_whose_completion_handling_fails_does_not_block_later_scans(tmp_path, monkeypatch):
    """L3: if handling the done event fails, the job must still be released;
    otherwise every later scan is refused with 409 until the app restarts."""
    saved_state = _save_scan_state()
    saved_fingerprints = {mode: dict(prints) for mode, prints in main.result_fingerprints_by_mode.items()}
    try:
        (tmp_path / "a.jpg").write_bytes(b"photo")

        def failing_fingerprints(results, mode):
            raise RuntimeError("cannot record fingerprints")

        monkeypatch.setattr(main, "_collect_result_fingerprints", failing_fingerprints)
        main.active_scanner = None
        assert main.start_scan(main.ScanRequest(directory=str(tmp_path), mode="exact")) == {"status": "started"}
        deadline = time.monotonic() + 5
        while not main.scan_state["done"] and time.monotonic() < deadline:
            time.sleep(0.01)

        assert main.scan_state["done"] is True
        assert main.active_scanner is None
        assert main.scan_state["status"] == "idle"
        assert main.scan_state["results"]["error"]
    finally:
        _restore_scan_state(saved_state)
        main.result_fingerprints_by_mode = saved_fingerprints


def test_deleting_a_file_keeps_the_other_cached_thumbnails(tmp_path, monkeypatch):
    """L8: the thumbnail cache key already includes each file's size and mtime,
    so a delete need not make every visible thumbnail render again."""
    from backend import scanner as scanner_module

    saved_state = _save_scan_state()
    try:
        kept = tmp_path / "kept.jpg"
        removed = tmp_path / "removed.jpg"
        Image.new("RGB", (64, 64), "red").save(kept)
        Image.new("RGB", (64, 64), "blue").save(removed)
        with main.scan_lock:
            main.allowed_scan_root = main._resolve_path(str(tmp_path))
            main.allowed_result_paths_by_mode = {
                "exact": {main._path_key(str(kept)), main._path_key(str(removed))},
                "similar": set(),
            }
        scanner_module.clear_thumbnail_cache()
        assert main.get_thumbnail(str(kept)).status_code == 200

        monkeypatch.setattr(main, "send2trash", lambda path: None)
        assert main.delete_files(main.DeleteRequest(files=[str(removed)]))["deleted"] == [str(removed)]
        assert main.get_thumbnail(str(kept)).status_code == 200

        assert scanner_module._generate_thumbnail_cached.cache_info().hits == 1
    finally:
        _restore_scan_state(saved_state)
