import io
import os
import sys
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
    except subprocess.CalledProcessError:
        pytest.skip("Requires privileges to create junction")
        
    scanner = Scanner()
    results = []
    scanner.scan_directory(str(d1), 'exact', lambda ev, data: results.append((ev, data)))
    assert results[-1][0] == 'done'
