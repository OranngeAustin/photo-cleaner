import io
import os
import random
import sys
import threading
import time
import unittest.mock
import warnings
import pytest
from pathlib import Path
from PIL import Image, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
import backend.scanner as scanner_module
from backend.scanner import (
    Scanner,
    clear_thumbnail_cache,
    cluster_similar_hashes,
    get_file_hash,
    get_image_phash,
)

def create_image(path, mode="RGB", size=(100, 100), color="red"):
    img = Image.new(mode, size, color=color)
    img.save(path)

def test_get_file_hash(tmp_path):
    p = tmp_path / "test.txt"
    p.write_text("hello world")
    h = get_file_hash(str(p))
    assert len(h) == 64
    assert h == 'b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9'

    assert get_file_hash(str(tmp_path / "missing.txt")) == ''

    with unittest.mock.patch('builtins.open', side_effect=PermissionError):
        assert get_file_hash(str(p)) == ''

def test_get_image_phash(tmp_path):
    p = tmp_path / "img.jpg"
    create_image(p)
    h = get_image_phash(str(p))
    assert h != ''
    
    txt = tmp_path / "test.txt"
    txt.write_text("not image")
    assert get_image_phash(str(txt)) == ''
    
    assert get_image_phash(str(tmp_path / "missing.jpg")) == ''

def test_scanner_exact_mode(tmp_path):
    p1 = tmp_path / "img1.jpg"
    p2 = tmp_path / "img2.jpg"
    p3 = tmp_path / "img3.jpg"
    
    create_image(p1, color="red")
    create_image(p2, color="red")
    create_image(p3, color="blue")
    
    scanner = Scanner()
    results = []
    scanner.scan_directory(str(tmp_path), 'exact', lambda ev, data: results.append((ev, data)))
    
    assert len(results) >= 1
    assert results[-1][0] == 'done'
    final_res = results[-1][1]
    assert len(final_res.get('exact', [])) == 1
    
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    results = []
    scanner.scan_directory(str(empty_dir), 'exact', lambda ev, data: results.append((ev, data)))
    assert len(results[-1][1].get('exact', [])) == 0

    u1 = empty_dir / "u1.jpg"
    u2 = empty_dir / "u2.jpg"
    u3 = empty_dir / "u3.jpg"
    create_image(u1, color="red")
    create_image(u2, color="green")
    create_image(u3, color="blue")
    results = []
    scanner.scan_directory(str(empty_dir), 'exact', lambda ev, data: results.append((ev, data)))
    assert len(results[-1][1].get('exact', [])) == 0

def test_scanner_similar_mode(tmp_path):
    p1 = tmp_path / "img1.jpg"
    p2 = tmp_path / "img2.jpg"
    p3 = tmp_path / "img3.jpg"
    
    img = Image.new("RGB", (100,100), color="white")
    d = ImageDraw.Draw(img)
    d.rectangle([10,10,20,20], fill="black")
    img.save(p1)
    
    img2 = Image.new("RGB", (100,100), color="white")
    d2 = ImageDraw.Draw(img2)
    d2.rectangle([10,10,21,21], fill="black")
    img2.save(p2)
    
    create_image(p3, color="blue")
    
    scanner = Scanner()
    results = []
    scanner.scan_directory(str(tmp_path), 'similar', lambda ev, data: results.append((ev, data)))
    
    final_res = results[-1][1]
    assert len(final_res.get('similar', [])) == 1

def test_scanner_cancel(tmp_path):
    p1 = tmp_path / "img1.jpg"
    p2 = tmp_path / "img2.jpg"
    create_image(p1)
    create_image(p2)
    
    scanner = Scanner()
    results = []
    def cancel_callback(ev, data):
        results.append((ev, data))
        scanner.cancel()
        
    scanner.scan_directory(str(tmp_path), 'exact', cancel_callback)
    
    final_res = results[-1][1]
    assert final_res.get('cancelled') is True

def test_parallel_results_yield_each_file_once_and_failures_as_empty():
    scanner = Scanner(max_workers=3)
    filepaths = [f"photo-{index}.jpg" for index in range(200)]

    def worker(filepath, cancel_event):
        assert cancel_event is scanner._cancel_event
        if filepath.endswith("7.jpg"):
            raise RuntimeError("decoder failed")
        return filepath.upper()

    results = list(scanner._iter_parallel_results(filepaths, worker))

    assert sorted(results) == sorted(
        (filepath, "" if filepath.endswith("7.jpg") else filepath.upper()) for filepath in filepaths
    )
    assert list(scanner._iter_parallel_results([], worker)) == []


def test_parallel_results_bound_unconsumed_work_to_twice_the_workers():
    import threading
    import time

    scanner = Scanner(max_workers=2)
    started = 0
    lock = threading.Lock()

    def worker(filepath, _cancel_event):
        nonlocal started
        with lock:
            started += 1
        time.sleep(0.001)
        return filepath

    consumed = 0
    furthest_ahead = 0
    for _ in scanner._iter_parallel_results([str(index) for index in range(120)], worker):
        consumed += 1
        with lock:
            furthest_ahead = max(furthest_ahead, started - consumed)

    assert consumed == 120
    assert furthest_ahead <= 2 * 2


def test_parallel_results_stop_after_the_yield_that_observed_cancel():
    scanner = Scanner(max_workers=1)
    started = []

    def worker(filepath, _cancel_event):
        started.append(filepath)
        return filepath

    yielded = []
    for item in scanner._iter_parallel_results([str(index) for index in range(50)], worker):
        yielded.append(item)
        scanner.cancel()

    assert len(yielded) == 1
    assert len(started) <= 2


def test_parallel_results_cancelled_before_start_yield_nothing():
    scanner = Scanner(max_workers=2)
    scanner.cancel()
    assert list(scanner._iter_parallel_results(["a.jpg", "b.jpg", "c.jpg"], lambda path, _event: path)) == []


def test_scanner_generate_thumbnail(tmp_path):
    scanner = Scanner()
    
    p1 = tmp_path / "img1.jpg"
    create_image(p1, mode="RGB")
    assert len(scanner.generate_thumbnail(str(p1))) > 0
    
    p2 = tmp_path / "img2.png"
    create_image(p2, mode="RGBA")
    assert len(scanner.generate_thumbnail(str(p2))) > 0
    
    p3 = tmp_path / "test.txt"
    p3.write_text("hello")
    assert scanner.generate_thumbnail(str(p3)) == b''
    
    p4 = tmp_path / "img4.png"
    create_image(p4, mode="L")
    assert len(scanner.generate_thumbnail(str(p4))) > 0


def test_thumbnail_composites_palette_byte_transparency_without_warning(tmp_path):
    scanner = Scanner()
    image_path = tmp_path / "palette-transparency.png"
    palette_image = Image.new("P", (32, 32))
    palette_image.putpalette([255, 0, 0, 0, 0, 255] + [0] * (768 - 6))
    palette_image.paste(1, (16, 0, 32, 32))
    # A partial-alpha palette entry forces Pillow to preserve the tRNS byte table.
    palette_image.save(image_path, transparency=bytes([0, 128] + [255] * 254))
    clear_thumbnail_cache()

    with Image.open(image_path) as source:
        assert isinstance(source.info.get("transparency"), bytes)

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        thumbnail_bytes = scanner.generate_thumbnail(str(image_path))

    assert thumbnail_bytes
    assert not any(
        "Palette images with Transparency expressed in bytes" in str(warning.message)
        for warning in caught
    )
    with Image.open(io.BytesIO(thumbnail_bytes)) as thumbnail:
        assert thumbnail.mode == "RGB"
        assert all(channel > 235 for channel in thumbnail.getpixel((4, 4)))


def test_thumbnail_cache_uses_source_metadata_for_invalidation(tmp_path):
    scanner = Scanner()
    image_path = tmp_path / "img.jpg"
    create_image(image_path, color="red")
    clear_thumbnail_cache()

    first = scanner.generate_thumbnail(str(image_path))
    second = scanner.generate_thumbnail(str(image_path))
    assert first == second
    assert scanner_module._generate_thumbnail_cached.cache_info().hits == 1

    create_image(image_path, color="blue")
    third = scanner.generate_thumbnail(str(image_path))
    assert third != b""
    assert scanner_module._generate_thumbnail_cached.cache_info().misses == 2

def test_exact_scan_only_full_hashes_prefix_collisions(tmp_path, monkeypatch):
    prefix = b"x" * (64 * 1024)
    duplicate = prefix + (b"d" * 4096)
    (tmp_path / "duplicate-a.jpg").write_bytes(duplicate)
    (tmp_path / "duplicate-b.jpg").write_bytes(duplicate)
    (tmp_path / "same-prefix-a.jpg").write_bytes(prefix + (b"a" * 4096))
    (tmp_path / "same-prefix-b.jpg").write_bytes(prefix + (b"b" * 4096))
    (tmp_path / "different-prefix.jpg").write_bytes((b"y" * (64 * 1024)) + (b"z" * 4096))

    full_hash_calls = []
    original_get_file_hash = scanner_module.get_file_hash

    def tracking_get_file_hash(filepath, cancel_event=None):
        full_hash_calls.append(Path(filepath).name)
        return original_get_file_hash(filepath, cancel_event)

    monkeypatch.setattr(scanner_module, "get_file_hash", tracking_get_file_hash)
    results = []
    Scanner(max_workers=1).scan_directory(
        str(tmp_path), "exact", lambda event, data: results.append((event, data))
    )

    exact_groups = results[-1][1]["exact"]
    assert len(exact_groups) == 1
    assert {Path(path).name for path in exact_groups[0]} == {"duplicate-a.jpg", "duplicate-b.jpg"}
    assert set(full_hash_calls) == {
        "duplicate-a.jpg",
        "duplicate-b.jpg",
        "same-prefix-a.jpg",
        "same-prefix-b.jpg",
    }

def test_exact_scan_reuses_enumeration_size_metadata(tmp_path, monkeypatch):
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    create_image(first, color="red")
    second.write_bytes(first.read_bytes())

    def fail_if_getsize_is_used(_path):
        raise AssertionError("exact scan must use DirEntry.stat() metadata, not os.path.getsize()")

    monkeypatch.setattr(scanner_module.os.path, "getsize", fail_if_getsize_is_used)
    results = []
    Scanner(max_workers=1).scan_directory(
        str(tmp_path), "exact", lambda event, data: results.append((event, data))
    )

    assert len(results[-1][1]["exact"]) == 1

def test_similar_cluster_is_lossless_for_five_bit_edge_and_keeps_anchor_semantics():
    anchor = 0
    # Five changes touch all four old 16-bit segments, so a four-bucket index
    # would miss this valid edge.  The sixth-segment index must retain it.
    edge = (1 << 0) | (1 << 16) | (1 << 32) | (1 << 48) | (1 << 49)
    chain = edge | (1 << 5)
    phash_dict = {
        f"{anchor:016x}": ["anchor.jpg"],
        f"{edge:016x}": ["edge.jpg"],
        f"{chain:016x}": ["chain.jpg"],
    }

    groups = cluster_similar_hashes(phash_dict)
    assert groups == [["anchor.jpg", "edge.jpg"]]

def test_scan_directory_symlink_cycle(tmp_path):
    import subprocess
    d1 = tmp_path / "d1"
    d1.mkdir()
    d2 = d1 / "d2"
    d2.mkdir()
    
    p1 = d1 / "img1.jpg"
    create_image(p1)
    
    j_path = d2 / "j_d1"
    try:
        subprocess.run(["cmd", "/c", "mklink", "/J", str(j_path), str(d1)], check=True, stdout=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        # OSError: no cmd.exe (not Windows); CalledProcessError: no privilege.
        pytest.skip("Requires Windows and privileges to create a junction")
        
    scanner = Scanner()
    results = []
    scanner.scan_directory(str(d1), 'exact', lambda ev, data: results.append((ev, data)))
    assert results[-1][0] == 'done'
    # The junction leads back to d1; real-path de-duplication must stop the
    # loop, so the image is listed exactly once.
    assert Scanner()._enumerate_image_files(str(d1), collect_sizes=False)[0] == [str(p1)]


def _symlink_or_skip(link, target):
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks requires extra privileges on this platform")


def test_exact_scan_does_not_pair_a_file_symlink_with_its_target(tmp_path):
    target = tmp_path / "a.jpg"
    create_image(target)
    _symlink_or_skip(tmp_path / "b.jpg", target)

    scanner = Scanner(max_workers=1)
    files, _, _ = scanner._enumerate_image_files(str(tmp_path), collect_sizes=True)
    results = []
    scanner.scan_directory(str(tmp_path), "exact", lambda event, data: results.append((event, data)))

    assert files == [str(target)]
    assert results[-1][1]["exact"] == []


def _reference_anchor_clusters(phash_dict, threshold, cancel_at=None):
    """Brute-force O(K^2) statement of the anchor (non-transitive) semantics.

    ``cancel_at`` mirrors a cancellation observed at that anchor: earlier
    anchors complete, that anchor keeps only its own paths, and nothing follows.
    """
    keys = list(phash_dict)
    values = [int(key, 16) for key in keys]
    visited = set()
    groups = []
    for index, key in enumerate(keys):
        if cancel_at is not None and index > cancel_at:
            break
        if key in visited:
            continue
        visited.add(key)
        group = list(phash_dict[key])
        if cancel_at is None or index < cancel_at:
            for other_index in range(index + 1, len(keys)):
                other_key = keys[other_index]
                if other_key not in visited and (values[index] ^ values[other_index]).bit_count() <= threshold:
                    group.extend(phash_dict[other_key])
                    visited.add(other_key)
        if len(group) > 1:
            groups.append(group)
    return groups


def _random_clustered_phash_dict(seed, unique_hashes=600):
    rng = random.Random(seed)
    values = set()
    while len(values) < unique_hashes:
        if values and rng.random() < 0.6:
            value = rng.choice(sorted(values))
            for _ in range(rng.randint(1, 8)):
                value ^= 1 << rng.randrange(64)
        else:
            value = rng.getrandbits(64)
        values.add(value)
    ordered = sorted(f"{value:016x}" for value in values)
    return {
        key: [f"{index:04d}-{copy}.jpg" for copy in range(rng.choice((1, 1, 1, 2)))]
        for index, key in enumerate(ordered)
    }


@pytest.mark.parametrize("threshold", range(0, 9))
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_cluster_matches_brute_force_anchor_reference(seed, threshold):
    phash_dict = _random_clustered_phash_dict(seed)
    assert cluster_similar_hashes(phash_dict, threshold=threshold) == _reference_anchor_clusters(
        phash_dict, threshold
    )


def test_cluster_reports_progress_every_hundred_hashes():
    phash_dict = _random_clustered_phash_dict(4, unique_hashes=250)
    calls = []
    cluster_similar_hashes(phash_dict, progress_callback=lambda current, total: calls.append((current, total)))
    assert calls == [(0, 250), (100, 250), (200, 250)]


def test_cluster_returns_nothing_when_cancelled_before_start():
    cancel_event = threading.Event()
    cancel_event.set()
    assert cluster_similar_hashes(_random_clustered_phash_dict(5), cancel_event=cancel_event) == []


def test_cluster_cancelled_from_progress_keeps_only_completed_anchor_groups():
    phash_dict = _random_clustered_phash_dict(6, unique_hashes=300)
    cancel_event = threading.Event()

    def cancel_at_second_report(current, _total):
        if current == 100:
            cancel_event.set()

    result = cluster_similar_hashes(
        phash_dict, cancel_event=cancel_event, progress_callback=cancel_at_second_report
    )
    assert result == _reference_anchor_clusters(phash_dict, 5, cancel_at=100)


def test_exact_scan_full_hashes_small_files_that_grew_after_enumeration(tmp_path):
    # M1: sizes come from enumeration. A copy still being written can be past
    # 64 KiB by the time its prefix is read, and then the prefix no longer
    # covers the whole file, so it must not decide the match on its own.
    shared_prefix = os.urandom(scanner_module.PREFIX_HASH_SIZE + 4_000)
    first = tmp_path / "first.jpg"
    second = tmp_path / "second.jpg"
    copy = tmp_path / "copy.jpg"
    first.write_bytes(shared_prefix + b"first tail")
    second.write_bytes(shared_prefix + b"other tail")
    copy.write_bytes(shared_prefix + b"first tail")
    stale_sizes = {str(path): 1_000 for path in (first, second, copy)}

    groups = Scanner(max_workers=2)._scan_exact(sorted(stale_sizes), stale_sizes, lambda *_: None)

    assert groups == [[str(copy), str(first)]]


def test_thumbnail_follows_exif_orientation(tmp_path):
    # M3: phones store portrait shots as landscape pixels plus Orientation=6.
    image = Image.new("RGB", (400, 200), "red")
    image.paste((0, 0, 255), (200, 0, 400, 200))
    exif = Image.Exif()
    exif[274] = 6
    path = tmp_path / "portrait.jpg"
    image.save(path, exif=exif)
    clear_thumbnail_cache()

    thumbnail = Image.open(io.BytesIO(scanner_module.generate_thumbnail(str(path))))

    assert thumbnail.size == (128, 256)
    # Orientation 6 means "rotate 90 degrees clockwise to display", so the
    # red left half of the stored pixels ends up on top.
    top, bottom = thumbnail.getpixel((64, 32)), thumbnail.getpixel((64, 224))
    assert top[0] > 200 and top[2] < 60
    assert bottom[2] > 200 and bottom[0] < 60


def test_pixel_budget_makes_a_large_request_wait_for_room():
    budget = scanner_module._PixelBudget(100)
    events = []
    first_holding = threading.Event()
    release_first = threading.Event()

    def first():
        with budget.reserve(60) as granted:
            events.append(("first", granted))
            first_holding.set()
            release_first.wait(5)

    def second():
        first_holding.wait(5)
        with budget.reserve(60) as granted:
            events.append(("second", granted))

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    first_holding.wait(5)
    threading.Event().wait(0.2)
    assert events == [("first", True)]

    release_first.set()
    for thread in threads:
        thread.join(5)
    assert events == [("first", True), ("second", True)]


def test_pixel_budget_runs_an_oversized_image_alone_and_gives_up_on_cancel():
    budget = scanner_module._PixelBudget(100)
    cancel_event = threading.Event()
    with budget.reserve(500) as granted:
        assert granted
        cancel_event.set()
        with budget.reserve(1, cancel_event) as waiting_granted:
            assert waiting_granted is False
    with budget.reserve(100) as granted:
        assert granted


def test_similar_scan_keeps_concurrent_decodes_within_the_pixel_budget(tmp_path, monkeypatch):
    # M7: every worker used to decode a full-size image at the same time.
    paths = []
    for index in range(6):
        path = tmp_path / f"img{index}.png"
        create_image(path, size=(100, 100), color=(index * 40, 0, 0))
        paths.append(str(path))
    monkeypatch.setattr(scanner_module, "_decode_budget", scanner_module._PixelBudget(2 * 100 * 100))
    real_phash = scanner_module.imagehash.phash
    lock = threading.Lock()
    running = peak = 0

    def slow_phash(image):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        try:
            threading.Event().wait(0.05)
            return real_phash(image)
        finally:
            with lock:
                running -= 1

    monkeypatch.setattr(scanner_module.imagehash, "phash", slow_phash)
    results = list(Scanner(max_workers=6)._iter_parallel_results(paths, get_image_phash))

    assert peak == 2
    assert sorted(path for path, phash in results if phash) == paths


def test_thumbnail_reserves_the_reduced_jpeg_decode_and_composites_after_shrinking(tmp_path, monkeypatch):
    reserved = []
    real_budget = scanner_module._PixelBudget(10**9)

    class RecordingBudget:
        def reserve(self, pixels, cancel_event=None):
            reserved.append(pixels)
            return real_budget.reserve(pixels, cancel_event)

    monkeypatch.setattr(scanner_module, "_decode_budget", RecordingBudget())
    jpeg = tmp_path / "large.jpg"
    png = tmp_path / "large.png"
    create_image(jpeg, size=(1600, 1200))
    create_image(png, mode="RGBA", size=(1600, 1200), color=(0, 0, 255, 0))
    clear_thumbnail_cache()

    assert scanner_module.generate_thumbnail(str(jpeg))
    png_thumbnail = scanner_module.generate_thumbnail(str(png))

    # JPEG decodes at 1/4 scale for a 256 px box; PNG has no reduced decode.
    assert reserved == [400 * 300, 1600 * 1200]
    with Image.open(io.BytesIO(png_thumbnail)) as thumbnail:
        assert thumbnail.size == (256, 192)
        assert all(channel > 235 for channel in thumbnail.getpixel((128, 96)))


def test_scan_directory_does_not_loop_through_a_directory_symlink(tmp_path):
    # M9: a portable counterpart of the junction cycle test above.
    d1 = tmp_path / "d1"
    d2 = d1 / "d2"
    d2.mkdir(parents=True)
    image = d1 / "img1.jpg"
    create_image(image)
    _symlink_or_skip(d2 / "back_to_d1", d1)

    files, _, skipped = Scanner()._enumerate_image_files(str(d1), collect_sizes=False)
    results = []
    Scanner().scan_directory(str(d1), "exact", lambda event, data: results.append((event, data)))

    assert files == [str(image)]
    assert skipped == 0
    assert results[-1][0] == "done"


def test_exact_scan_decides_up_to_64_kib_by_prefix_and_full_hashes_larger_files(tmp_path, monkeypatch):
    # M10: the funnel boundary is "size <= PREFIX_HASH_SIZE".
    limit = scanner_module.PREFIX_HASH_SIZE
    payload = os.urandom(limit) + b"\x02"
    contents = {
        "at_limit_a.jpg": payload[:limit],
        "at_limit_b.jpg": payload[:limit],
        "over_same_a.jpg": payload,
        "over_same_b.jpg": payload,
        "over_diff_a.jpg": payload[:limit] + b"\x00",
        "over_diff_b.jpg": payload[:limit] + b"\x01",
    }
    for name, content in contents.items():
        (tmp_path / name).write_bytes(content)
    fully_hashed = []
    real_get_file_hash = scanner_module.get_file_hash

    def recording_get_file_hash(path, cancel_event=None):
        fully_hashed.append(os.path.basename(path))
        return real_get_file_hash(path, cancel_event)

    monkeypatch.setattr(scanner_module, "get_file_hash", recording_get_file_hash)
    events = []
    Scanner(max_workers=2).scan_directory(str(tmp_path), "exact", lambda event, data: events.append((event, data)))

    groups = [[os.path.basename(path) for path in group] for group in events[-1][1]["exact"]]
    assert groups == [["at_limit_a.jpg", "at_limit_b.jpg"], ["over_same_a.jpg", "over_same_b.jpg"]]
    assert sorted(fully_hashed) == ["over_diff_a.jpg", "over_diff_b.jpg", "over_same_a.jpg", "over_same_b.jpg"]


class _CancelAfter:
    """An Event stand-in that reports cancellation from the n-th check on."""

    def __init__(self, checks):
        self.remaining = checks

    def is_set(self):
        self.remaining -= 1
        return self.remaining < 0


def test_hashing_stops_and_returns_empty_when_cancelled_midway(tmp_path):
    big_file = tmp_path / "big.jpg"
    big_file.write_bytes(os.urandom(scanner_module.HASH_CHUNK_SIZE * 4))
    image = tmp_path / "image.png"
    create_image(image)

    cancelled_after_two_chunks = _CancelAfter(checks=2)
    assert get_file_hash(str(big_file), cancelled_after_two_chunks) == ""
    assert cancelled_after_two_chunks.remaining < 0
    assert get_file_hash(str(big_file), _CancelAfter(checks=10**6)) == get_file_hash(str(big_file))

    cancelled = threading.Event()
    cancelled.set()
    assert scanner_module.get_file_prefix_hash(str(big_file), cancelled) == ""
    assert get_image_phash(str(image), cancelled) == ""


def test_a_failing_done_callback_does_not_escape_the_scan_thread(tmp_path):
    create_image(tmp_path / "a.jpg")
    calls = []

    def callback(event, data):
        calls.append(event)
        if event == "done" and calls.count("done") == 1:
            raise RuntimeError("callback failed")

    scanner = Scanner()
    scanner.scan_directory(str(tmp_path), "exact", callback)

    assert "done" in calls
    assert scanner.is_scanning is False


@pytest.mark.parametrize("size", [1_000, 65_536, 70_000])
def test_prefix_hash_covers_exactly_the_first_64_kib(tmp_path, size):
    import hashlib

    data = os.urandom(size)
    path = tmp_path / "file.jpg"
    path.write_bytes(data)

    expected = hashlib.sha256(data[:scanner_module.PREFIX_HASH_SIZE]).hexdigest()
    assert scanner_module.get_file_prefix_hash(str(path)) == expected


@pytest.mark.parametrize(("size", "expected_length"), [(1_000, 1_000), (65_536, 65_536), (70_000, 65_537)])
def test_prefix_read_reports_the_file_length_up_to_one_byte_past_the_prefix(tmp_path, size, expected_length):
    path = tmp_path / "file.jpg"
    path.write_bytes(os.urandom(size))

    prefix_hash, bytes_read = scanner_module.get_file_prefix_hash_and_length(str(path))

    assert bytes_read == expected_length
    assert prefix_hash == scanner_module.get_file_prefix_hash(str(path))


def test_a_failed_thumbnail_is_retried_on_the_next_request(tmp_path, monkeypatch):
    """L2: a file briefly locked by another process (or a MemoryError) must not
    leave an empty thumbnail in the cache until the next scan or delete."""
    image = tmp_path / "a.jpg"
    create_image(image)
    clear_thumbnail_cache()
    real_open = scanner_module.Image.open
    opened = []

    def flaky_open(*args, **kwargs):
        opened.append(args[0])
        if len(opened) == 1:
            raise PermissionError("locked by another process")
        return real_open(*args, **kwargs)

    monkeypatch.setattr(scanner_module.Image, "open", flaky_open)

    assert scanner_module.generate_thumbnail(str(image)) == b""
    retried = scanner_module.generate_thumbnail(str(image))

    assert len(opened) == 2
    assert Image.open(io.BytesIO(retried)).format == "JPEG"


def test_done_is_reported_once_even_when_the_callback_keeps_failing(tmp_path):
    """L3: a failing done callback was caught by the scan's own error handler,
    which sent a second done; when that failed too, the exception escaped and
    ended the scan thread."""
    create_image(tmp_path / "a.jpg")
    events = []

    def callback(event, data):
        events.append(event)
        if event == "done":
            raise RuntimeError("callback failed")

    scanner = Scanner()
    scanner.scan_directory(str(tmp_path), "exact", callback)

    assert events.count("done") == 1
    assert scanner.is_scanning is False


def test_closing_the_result_iterator_early_drops_queued_work():
    """L4: when the consumer stops early for a reason other than cancel (an
    exception in its loop body, a break), queued files must not still be
    processed while the executor shuts down."""
    started = []

    def worker(path, cancel_event):
        started.append(path)
        if path != "a":
            time.sleep(0.3)
        return path

    scanner = Scanner(max_workers=2)
    results = scanner._iter_parallel_results(["a", "b", "c", "d", "e"], worker)
    assert next(results) == ("a", "a")

    results.close()

    assert "d" not in started
    assert "e" not in started
