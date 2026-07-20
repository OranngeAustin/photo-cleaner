import sys
from pathlib import Path

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
