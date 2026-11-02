"""Micro/meso benchmarks for the scan engine and the result-path whitelist.

Run from the repository root:

    python benchmarks/bench_scanner.py                 # every benchmark, 5 runs each
    python benchmarks/bench_scanner.py cluster exact   # only selected benchmarks
    python benchmarks/bench_scanner.py --runs 7 --json out.json

Each benchmark builds its own deterministic synthetic input (fixed random seed)
in a temporary directory, runs the measured function ``--runs`` times and
reports the median wall time plus the peak traced Python memory of one extra
run.  Cloud timings are noisy, so only compare relative changes measured on the
same machine in the same session.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from PIL import Image  # noqa: E402

import backend.scanner as scanner_module  # noqa: E402
from backend.scanner import Scanner, cluster_similar_hashes  # noqa: E402


# ---------------------------------------------------------------------------
# Synthetic inputs
# ---------------------------------------------------------------------------

def make_phash_dict(unique_hashes: int, seed: int = 1234) -> dict[str, list[str]]:
    """Build a pHash -> paths mapping that resembles a real photo library.

    Real pHashes are not uniformly random: bursts of photos produce families
    of hashes a few bits apart, and many unrelated photos share low-frequency
    structure, which makes some index buckets much larger than average.
    """
    rng = random.Random(seed)
    hashes: set[int] = set()
    # A handful of "styles" (shared high bits) skews the bucket sizes.
    styles = [rng.getrandbits(64) for _ in range(32)]
    while len(hashes) < unique_hashes:
        roll = rng.random()
        if roll < 0.55:
            value = rng.getrandbits(64)
        elif roll < 0.80:
            # Shares the upper 33 bits with a style -> crowded buckets.
            style = rng.choice(styles)
            value = (style & ~((1 << 31) - 1)) | rng.getrandbits(31)
        else:
            # Burst member: up to 7 bits away from an existing hash.
            base = rng.choice(tuple(hashes)) if hashes else rng.getrandbits(64)
            value = base
            for _ in range(rng.randint(0, 7)):
                value ^= 1 << rng.randrange(64)
        hashes.add(value & ((1 << 64) - 1))
    ordered = sorted(f"{value:016x}" for value in hashes)
    return {key: [f"/photos/{index:07d}.jpg"] for index, key in enumerate(ordered)}


def make_file_tree(root: Path, files: int, seed: int = 99) -> None:
    """Create a nested directory tree of small image-named files.

    About a third of the files are duplicates of another file and a further
    slice shares the 64 KiB prefix but differs later, so every exact-mode
    funnel stage has work to do.
    """
    rng = random.Random(seed)
    extensions = [".jpg", ".JPG", ".jpeg", ".png", ".txt", ".json", ".heic"]
    payloads: list[bytes] = []
    for index in range(files):
        directory = root / f"y{index % 7}" / f"m{index % 12:02d}" / f"d{index % 5}"
        directory.mkdir(parents=True, exist_ok=True)
        extension = extensions[index % len(extensions)]
        roll = rng.random()
        if payloads and roll < 0.33:
            payload = rng.choice(payloads)
        elif payloads and roll < 0.40:
            base = rng.choice(payloads)
            payload = base[:-1] + bytes([(base[-1] + 1) % 256])
        else:
            size = rng.choice((900, 4_000, 30_000, 70_000, 140_000))
            payload = rng.randbytes(size)
            payloads.append(payload)
        (directory / f"IMG_{index:06d}{extension}").write_bytes(payload)


def make_jpegs(root: Path, count: int, size: tuple[int, int], seed: int = 7) -> list[str]:
    rng = random.Random(seed)
    paths = []
    for index in range(count):
        image = Image.new("RGB", size, (rng.randrange(256), rng.randrange(256), rng.randrange(256)))
        for _ in range(12):
            x0, y0 = rng.randrange(size[0]), rng.randrange(size[1])
            x1, y1 = x0 + rng.randrange(size[0] // 2), y0 + rng.randrange(size[1] // 2)
            image.paste((rng.randrange(256), rng.randrange(256), rng.randrange(256)), (x0, y0, x1, y1))
        path = root / f"photo_{index:04d}.jpg"
        image.save(path, quality=90)
        paths.append(str(path))
    return paths


# ---------------------------------------------------------------------------
# Benchmarks: each returns (setup -> callable, teardown)
# ---------------------------------------------------------------------------

def _noop_callback(_event: str, _data: dict) -> None:
    return None


def bench_cluster(size: int) -> tuple[Callable[[], object], Callable[[], None]]:
    phash_dict = make_phash_dict(size)
    return (lambda: cluster_similar_hashes(phash_dict)), (lambda: None)


def bench_enumerate(files: int) -> tuple[Callable[[], object], Callable[[], None]]:
    root = Path(tempfile.mkdtemp(prefix="bench-enum-"))
    make_file_tree(root, files)
    scanner = Scanner()

    def run():
        return scanner._enumerate_image_files(str(root), collect_sizes=True)

    return run, (lambda: shutil.rmtree(root, ignore_errors=True))


def bench_exact(files: int) -> tuple[Callable[[], object], Callable[[], None]]:
    root = Path(tempfile.mkdtemp(prefix="bench-exact-"))
    make_file_tree(root, files)

    def run():
        results = []
        Scanner().scan_directory(str(root), "exact", lambda event, data: results.append((event, data)))
        return results[-1][1]["exact"]

    return run, (lambda: shutil.rmtree(root, ignore_errors=True))


def bench_phash(count: int) -> tuple[Callable[[], object], Callable[[], None]]:
    root = Path(tempfile.mkdtemp(prefix="bench-phash-"))
    make_jpegs(root, count, (1600, 1200))

    def run():
        results = []
        Scanner().scan_directory(str(root), "similar", lambda event, data: results.append((event, data)))
        return results[-1][1]["similar"]

    return run, (lambda: shutil.rmtree(root, ignore_errors=True))


def bench_thumbnail(count: int) -> tuple[Callable[[], object], Callable[[], None]]:
    root = Path(tempfile.mkdtemp(prefix="bench-thumb-"))
    paths = make_jpegs(root, count, (1600, 1200), seed=11)

    def run():
        scanner_module.clear_thumbnail_cache()
        return [len(scanner_module.generate_thumbnail(path)) for path in paths]

    return run, (lambda: shutil.rmtree(root, ignore_errors=True))


def bench_parallel(items: int) -> tuple[Callable[[], object], Callable[[], None]]:
    """Pure scheduling overhead of Scanner._iter_parallel_results (no-op worker)."""
    filepaths = [f"/photos/{index:07d}.jpg" for index in range(items)]
    scanner = Scanner()

    def worker(filepath: str, _cancel_event) -> str:
        return filepath

    return (lambda: list(scanner._iter_parallel_results(filepaths, worker))), (lambda: None)


def _make_result_groups(paths_count: int) -> tuple[Path, dict[str, list[list[str]]]]:
    root = Path(tempfile.mkdtemp(prefix="bench-keys-"))
    groups: list[list[str]] = []
    for index in range(0, paths_count, 2):
        directory = root / f"d{index % 50}"
        directory.mkdir(exist_ok=True)
        pair = []
        for offset in (0, 1):
            path = directory / f"p{index + offset}.jpg"
            path.write_bytes(b"x")
            pair.append(str(path))
        groups.append(pair)
    return root, {"exact": groups, "similar": []}


def bench_result_keys(paths_count: int) -> tuple[Callable[[], object], Callable[[], None]]:
    root, results = _make_result_groups(paths_count)
    import main  # noqa: PLC0415 - imported lazily because it pulls in pywebview

    return (lambda: main._collect_result_path_keys(results, "exact")), (
        lambda: shutil.rmtree(root, ignore_errors=True)
    )


def bench_result_fingerprints(paths_count: int) -> tuple[Callable[[], object], Callable[[], None]]:
    """What a finished scan now does: whitelist keys plus one stat per result."""
    root, results = _make_result_groups(paths_count)
    import main  # noqa: PLC0415 - imported lazily because it pulls in pywebview

    return (lambda: main._collect_result_fingerprints(results, "exact")), (
        lambda: shutil.rmtree(root, ignore_errors=True)
    )


BENCHMARKS: dict[str, tuple[Callable[[int], tuple[Callable[[], object], Callable[[], None]]], int, str]] = {
    "cluster": (bench_cluster, 60_000, "cluster_similar_hashes, 60k unique pHashes"),
    "enumerate": (bench_enumerate, 20_000, "_enumerate_image_files, 20k files / 420 dirs (warm cache)"),
    "exact": (bench_exact, 6_000, "exact scan end-to-end, 6k files (warm cache)"),
    "phash": (bench_phash, 120, "similar scan end-to-end, 120 JPEG 1600x1200"),
    "thumbnail": (bench_thumbnail, 60, "generate_thumbnail cold cache, 60 JPEG 1600x1200"),
    "parallel": (bench_parallel, 20_000, "_iter_parallel_results scheduling, 20k no-op items"),
    "result_keys": (bench_result_keys, 20_000, "main._collect_result_path_keys, 20k result paths"),
    "result_fingerprints": (
        bench_result_fingerprints, 20_000, "main._collect_result_fingerprints, 20k result paths"
    ),
}


def measure(name: str, runs: int, size: int | None = None) -> dict:
    factory, default_size, description = BENCHMARKS[name]
    run, teardown = factory(size or default_size)
    try:
        run()  # warm-up (fills OS page cache, imports, lazy init)
        timings = []
        for _ in range(runs):
            start = time.perf_counter()
            run()
            timings.append(time.perf_counter() - start)
        tracemalloc.start()
        run()
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
    finally:
        teardown()
    return {
        "name": name,
        "description": description,
        "runs": runs,
        "median_s": statistics.median(timings),
        "min_s": min(timings),
        "max_s": max(timings),
        "peak_py_mem_mb": peak / (1024 * 1024),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("names", nargs="*", help=f"benchmarks to run (default: all): {', '.join(BENCHMARKS)}")
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--size", type=int, default=None, help="override the input size of the selected benchmarks")
    parser.add_argument("--json", type=Path, default=None, help="also write results to this JSON file")
    args = parser.parse_args(argv)

    names = args.names or list(BENCHMARKS)
    unknown = [name for name in names if name not in BENCHMARKS]
    if unknown:
        parser.error(f"unknown benchmark(s): {', '.join(unknown)}")
    results = []
    print(f"{'benchmark':<12} {'median':>10} {'min':>10} {'max':>10} {'peak MiB':>9}  description")
    for name in names:
        result = measure(name, args.runs, args.size)
        results.append(result)
        print(
            f"{name:<12} {result['median_s']*1000:>8.1f}ms {result['min_s']*1000:>8.1f}ms "
            f"{result['max_s']*1000:>8.1f}ms {result['peak_py_mem_mb']:>9.1f}  {result['description']}",
            flush=True,
        )
    if args.json:
        args.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
