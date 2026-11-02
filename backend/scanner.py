import hashlib
import io
import logging
import os
import queue
import threading
from bisect import bisect_right
from collections import defaultdict
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from functools import lru_cache
from typing import Callable, Dict, Iterator, TypeVar

import imagehash
from PIL import Image


logger = logging.getLogger(__name__)
ResultT = TypeVar("ResultT")

try:
    from pillow_heif import register_heif_opener
except ImportError:
    HEIC_AVAILABLE = False
else:
    register_heif_opener()
    HEIC_AVAILABLE = True

SUPPORTED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'}
if HEIC_AVAILABLE:
    SUPPORTED_EXTENSIONS.add('.heic')
HASH_CHUNK_SIZE = 256 * 1024
PREFIX_HASH_SIZE = 64 * 1024
SIMILARITY_THRESHOLD = 5

# Six segments are necessary for a Hamming threshold of five.  If at most five
# bits differ, the pigeonhole principle guarantees that at least one of these
# six segments is identical.  Four 16-bit segments would miss valid matches.
PHASH_SEGMENTS = ((0, 11), (11, 11), (22, 11), (33, 11), (44, 10), (54, 10))


# Decoding costs about 4 bytes per pixel here (an RGB decode plus pHash's
# greyscale copy).  Concurrent decodes share this budget, roughly 0.8 GB: about
# fifteen 12 MP photos at once, or one image at Pillow's 179 MP hard limit.
DECODE_PIXEL_BUDGET = 192_000_000


def _was_cancelled(cancel_event: threading.Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


class _PixelBudget:
    """Caps the pixels that threads decode at the same time.

    Up to 32 scan workers (plus thumbnail requests) could otherwise each hold a
    full-size panorama or large TIFF in memory at once.  An image larger than
    the whole budget is still decoded, but alone.
    """

    def __init__(self, capacity: int):
        self.capacity = capacity
        self._in_use = 0
        self._condition = threading.Condition()

    @contextmanager
    def reserve(self, pixels: int, cancel_event: threading.Event | None = None) -> Iterator[bool]:
        """Hold ``pixels`` of the budget for the ``with`` body.

        Yields False, without holding anything, if ``cancel_event`` is set
        while waiting for room.
        """
        amount = min(max(int(pixels), 0), self.capacity)
        with self._condition:
            while self._in_use + amount > self.capacity and not _was_cancelled(cancel_event):
                # Time out now and then to notice a cancel nobody notifies.
                self._condition.wait(timeout=0.1)
            granted = self._in_use + amount <= self.capacity
            if granted:
                self._in_use += amount
        if not granted:
            yield False
            return
        try:
            yield True
        finally:
            with self._condition:
                self._in_use -= amount
                self._condition.notify_all()


_decode_budget = _PixelBudget(DECODE_PIXEL_BUDGET)


def get_file_hash(filepath: str, cancel_event: threading.Event | None = None) -> str:
    """Return a SHA-256 digest, stopping between blocks when cancelled."""
    try:
        with open(filepath, 'rb') as file_obj:
            if cancel_event is None:
                # Python 3.11+ uses a reusable 256 KiB buffer here.
                return hashlib.file_digest(file_obj, 'sha256').hexdigest()

            hasher = hashlib.sha256()
            buffer = bytearray(HASH_CHUNK_SIZE)
            view = memoryview(buffer)
            while not _was_cancelled(cancel_event):
                bytes_read = file_obj.readinto(buffer)
                if not bytes_read:
                    break
                hasher.update(view[:bytes_read])

            if _was_cancelled(cancel_event):
                return ""
            return hasher.hexdigest()
    except OSError:
        logger.warning("Failed to hash file: %s", filepath, exc_info=True)
        return ""


def get_file_prefix_hash_and_length(
    filepath: str,
    cancel_event: threading.Event | None = None,
    prefix_size: int = PREFIX_HASH_SIZE,
) -> tuple[str, int] | None:
    """Hash a file prefix and return it with the number of bytes read.

    One byte past the prefix is read, so the length is the file's size when
    the file fits in the prefix and ``prefix_size + 1`` when it does not.  A
    small file that grew or shrank since enumeration (a copy or sync still in
    progress) shows up as a length that differs from its enumerated size,
    without the cost of an extra ``fstat`` call.
    """
    try:
        if _was_cancelled(cancel_event):
            return None
        with open(filepath, 'rb') as file_obj:
            data = file_obj.read(prefix_size + 1)
        if _was_cancelled(cancel_event):
            return None
        return hashlib.sha256(memoryview(data)[:prefix_size]).hexdigest(), len(data)
    except OSError:
        logger.warning("Failed to hash file prefix: %s", filepath, exc_info=True)
        return None


def get_file_prefix_hash(
    filepath: str,
    cancel_event: threading.Event | None = None,
    prefix_size: int = PREFIX_HASH_SIZE,
) -> str:
    """Hash only a file prefix for the exact-match prefilter."""
    result = get_file_prefix_hash_and_length(filepath, cancel_event, prefix_size)
    return result[0] if result else ""


def get_image_phash(filepath: str, cancel_event: threading.Event | None = None) -> str:
    try:
        if _was_cancelled(cancel_event):
            return ""
        with Image.open(filepath) as img:
            # Opening reads only the header; phash() decodes the full image.
            with _decode_budget.reserve(img.width * img.height, cancel_event) as granted:
                if not granted:
                    return ""
                result = str(imagehash.phash(img))
        return "" if _was_cancelled(cancel_event) else result
    except Exception:
        logger.warning("Failed to compute pHash: %s", filepath, exc_info=True)
        return ""


EXIF_ORIENTATION_TAG = 274
# The same mapping as PIL.ImageOps.exif_transpose.
_ORIENTATION_TRANSPOSE = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
_SWAPS_AXES = {Image.Transpose.TRANSPOSE, Image.Transpose.TRANSVERSE, Image.Transpose.ROTATE_90, Image.Transpose.ROTATE_270}


def _orientation_transpose(img: Image.Image) -> Image.Transpose | None:
    """Return the transpose that displays ``img`` upright, if its EXIF needs one."""
    try:
        orientation = img.getexif().get(EXIF_ORIENTATION_TAG)
    except Exception:  # Malformed EXIF must not cost the whole thumbnail.
        logger.debug("Unreadable EXIF orientation: %s", getattr(img, "filename", ""), exc_info=True)
        return None
    return _ORIENTATION_TRANSPOSE.get(orientation) if isinstance(orientation, int) else None


@lru_cache(maxsize=512)
def _generate_thumbnail_cached(
    image_path: str,
    max_width: int,
    max_height: int,
    mtime_ns: int,
    file_size: int,
) -> bytes:
    """Render a thumbnail cached by path and source file identity metadata."""
    # mtime_ns and file_size intentionally participate in the cache key.
    del mtime_ns, file_size
    # Failures propagate on purpose: lru_cache keeps only returned values, so a
    # file briefly locked by another process is retried on the next request
    # instead of staying cached as an empty thumbnail.
    with Image.open(image_path) as img:
        # Read the orientation now: the conversions below drop metadata.
        # The bounding box applies to the upright image, and only the small
        # thumbnail is rotated, never the full-size decode.
        transpose = _orientation_transpose(img)
        if transpose in _SWAPS_AXES:
            max_width, max_height = max_height, max_width
        max_size = (max_width, max_height)
        if img.format == 'JPEG':
            # Decode at a reduced scale (down to 1/8); img.size reports it.
            img.draft('RGB', max_size)
        with _decode_budget.reserve(img.width * img.height):
            img.load()
            # JPEG has no alpha channel. Normalize PNG/GIF transparency first,
            # including palette images whose transparency is a byte table.
            if "transparency" in img.info:
                img = img.convert("RGBA")
            if img.mode not in ("RGB", "RGBA", "LA"):
                img = img.convert("RGB")
            img.thumbnail(max_size)
        # Composite on a deterministic white background only after
        # shrinking: a full-size background would double the memory.
        if img.mode in ("RGBA", "LA"):
            background = Image.new("RGB", img.size, "white")
            background.paste(img, mask=img.getchannel("A"))
            img = background
        if transpose is not None:
            img = img.transpose(transpose)
        img_byte_arr = io.BytesIO()
        img.save(img_byte_arr, format='JPEG', quality=85)
        return img_byte_arr.getvalue()


def clear_thumbnail_cache() -> None:
    _generate_thumbnail_cached.cache_clear()


def generate_thumbnail(image_path: str, max_size: tuple[int, int] = (256, 256)) -> bytes:
    try:
        real_path = os.path.realpath(image_path)
        stat_result = os.stat(real_path)
    except OSError:
        logger.warning("Failed to stat thumbnail source: %s", image_path, exc_info=True)
        return b""
    try:
        return _generate_thumbnail_cached(
            real_path,
            int(max_size[0]),
            int(max_size[1]),
            stat_result.st_mtime_ns,
            stat_result.st_size,
        )
    except Exception:
        logger.warning("Failed to generate thumbnail: %s", image_path, exc_info=True)
        return b""


def _segment_value(value: int, shift: int, width: int) -> int:
    return (value >> shift) & ((1 << width) - 1)


def cluster_similar_hashes(
    phash_dict: Dict[str, list[str]],
    threshold: int = SIMILARITY_THRESHOLD,
    cancel_event: threading.Event | None = None,
    progress_callback: Callable[[int, int], None] | None = None,
) -> list[list[str]]:
    """Cluster with the existing non-transitive anchor semantics efficiently.

    A group contains hashes within ``threshold`` of its first (anchor) hash.
    This deliberately avoids silently changing the product behaviour to a
    transitive chain/Union-Find cluster.  The six-segment index only removes
    impossible comparisons; every candidate is still verified exactly.
    """
    hash_keys = list(phash_dict)
    total_keys = len(hash_keys)
    hash_values = [int(hash_key, 16) for hash_key in hash_keys]
    # The six segments are lossless only for thresholds below six.
    use_index = threshold < len(PHASH_SEGMENTS)

    # One bucket map per segment.  Indexes are appended in ascending order, so
    # every bucket list is sorted and the candidates after an anchor start at
    # bisect_right(bucket, anchor); earlier hashes are never compared again.
    segment_buckets: list[dict[int, list[int]]] = [defaultdict(list) for _ in PHASH_SEGMENTS]
    if use_index:
        for index, hash_value in enumerate(hash_values):
            for buckets, (shift, width) in zip(segment_buckets, PHASH_SEGMENTS):
                buckets[_segment_value(hash_value, shift, width)].append(index)

    visited = [False] * total_keys
    similar_results: list[list[str]] = []

    for index, hash_key in enumerate(hash_keys):
        if _was_cancelled(cancel_event):
            break
        if progress_callback and index % 100 == 0:
            progress_callback(index, total_keys)
        if visited[index]:
            continue

        group = list(phash_dict[hash_key])
        visited[index] = True
        hash_value = hash_values[index]

        if _was_cancelled(cancel_event):
            # Keep only the anchor's own paths; the outer loop stops next.
            candidate_runs = []
        elif use_index:
            candidate_runs = []
            for buckets, (shift, width) in zip(segment_buckets, PHASH_SEGMENTS):
                bucket = buckets[_segment_value(hash_value, shift, width)]
                candidate_runs.append(bucket[bisect_right(bucket, index):])
        else:
            candidate_runs = [range(index + 1, total_keys)]

        matches: list[int] = []
        for candidates in candidate_runs:
            within_threshold = [
                other_index
                for other_index in candidates
                if (hash_value ^ hash_values[other_index]).bit_count() <= threshold
            ]
            # A hash can share several segments with the anchor; marking it
            # visited on its first match keeps it from being added twice.
            for other_index in within_threshold:
                if not visited[other_index]:
                    visited[other_index] = True
                    matches.append(other_index)
        # Preserve the original member order: ascending hash index.
        matches.sort()

        for other_index in matches:
            group.extend(phash_dict[hash_keys[other_index]])
        if len(group) > 1:
            similar_results.append(group)

    return similar_results


class Scanner:
    """One cancellable scan job.  Create a fresh instance for each request."""

    def __init__(self, max_workers: int | None = None):
        if max_workers is not None and max_workers < 1:
            raise ValueError("max_workers must be positive")
        self.max_workers = max_workers
        self._cancel_event = threading.Event()
        self.is_scanning = False
        self.scanned_files = 0
        self.total_files = 0

    @property
    def cancel_requested(self) -> bool:
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        self._cancel_event.set()

    def _worker_count(self) -> int:
        if self.max_workers is not None:
            return self.max_workers
        return min(32, (os.cpu_count() or 1) + 4)

    def _iter_parallel_results(
        self,
        filepaths: list[str],
        worker: Callable[[str, threading.Event], ResultT],
    ) -> Iterator[tuple[str, ResultT | str]]:
        """Process a bounded number of futures so cancellation is prompt.

        A worker that raises is logged and reported as ``""``, so callers
        skip any falsy result.
        """
        if not filepaths:
            return

        worker_count = self._worker_count()
        max_in_flight = worker_count * 2
        file_iterator = iter(filepaths)
        # Each future reports itself here when it finishes.  Waiting on one
        # queue is O(1) per file, whereas wait(FIRST_COMPLETED) re-arms a
        # waiter on every in-flight future after each completion.
        finished: queue.SimpleQueue[Future] = queue.SimpleQueue()

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            pending: dict[Future, str] = {}

            def submit_next() -> bool:
                try:
                    filepath = next(file_iterator)
                except StopIteration:
                    return False
                future = executor.submit(worker, filepath, self._cancel_event)
                pending[future] = filepath
                future.add_done_callback(finished.put)
                return True

            for _ in range(min(max_in_flight, len(filepaths))):
                submit_next()

            try:
                while pending:
                    if self.cancel_requested:
                        return

                    future = finished.get()
                    filepath = pending.pop(future)
                    try:
                        result = future.result()
                    except Exception:
                        logger.warning("Worker failed for file: %s", filepath, exc_info=True)
                        result = ""
                    yield filepath, result
                    if not self.cancel_requested:
                        submit_next()
            finally:
                # However the loop ends (cancel, an exception in the consumer,
                # or the consumer closing this generator early), drop queued
                # work so leaving the executor waits only for running workers.
                for future in pending:
                    future.cancel()

    def _finish(self, callback: Callable[[str, Dict], None], data: Dict) -> None:
        """Report done exactly once.

        A failing callback is logged here rather than reaching the scan's own
        error handler, which would report a second done.
        """
        self.is_scanning = False
        try:
            callback('done', data)
        except Exception:
            logger.exception("The scan completion callback failed")

    def scan_directory(self, root_dir: str, mode: str, callback: Callable[[str, Dict], None]) -> None:
        """Scan a directory for exact duplicates or visually similar photos."""
        self.is_scanning = True
        self.scanned_files = 0
        self.total_files = 0
        skipped_files = 0

        try:
            callback('status', {'message': 'Finding image files...'})
            all_files, file_sizes, skipped_files = self._enumerate_image_files(
                root_dir,
                collect_sizes=mode == 'exact',
            )
            self.total_files = len(all_files)
            if self.total_files == 0 or self.cancel_requested:
                self._finish(callback, {
                    'exact': [],
                    'similar': [],
                    'cancelled': self.cancel_requested,
                    'skipped_files': skipped_files,
                    'empty_scan': not self.cancel_requested and self.total_files == 0,
                })
                return

            if mode == 'exact':
                exact_results = self._scan_exact(all_files, file_sizes, callback)
                self._finish(callback, {
                    'exact': exact_results,
                    'similar': [],
                    'cancelled': self.cancel_requested,
                    'skipped_files': skipped_files,
                })
                return

            if mode == 'similar':
                similar_results = self._scan_similar(all_files, callback)
                self._finish(callback, {
                    'exact': [],
                    'similar': similar_results,
                    'cancelled': self.cancel_requested,
                    'skipped_files': skipped_files,
                })
                return

            raise ValueError(f"Unsupported scan mode: {mode}")
        except Exception:
            logger.exception("Scan failed for directory: %s", root_dir)
            self._finish(callback, {
                'exact': [],
                'similar': [],
                'cancelled': self.cancel_requested,
                'skipped_files': skipped_files,
                'error': 'Scan failed. Check the application log for details.',
            })

    def _enumerate_image_files(
        self,
        root_dir: str,
        *,
        collect_sizes: bool,
    ) -> tuple[list[str], dict[str, int], int]:
        """Enumerate supported images, reusing Windows directory metadata for size."""
        all_files: list[str] = []
        file_sizes: dict[str, int] = {}
        skipped_files = 0
        seen_realpaths: set[str] = set()
        stack = [root_dir]

        while stack and not self.cancel_requested:
            current_directory = stack.pop()
            try:
                real_dir = os.path.realpath(current_directory)
            except OSError:
                real_dir = os.path.abspath(current_directory)
            if real_dir in seen_realpaths:
                continue
            seen_realpaths.add(real_dir)

            try:
                with os.scandir(current_directory) as entries:
                    for entry in entries:
                        if self.cancel_requested:
                            break
                        try:
                            # Match os.walk(..., followlinks=False): traverse regular
                            # directories but do not descend into symlink directories.
                            # Windows junctions are not symlinks here, so they are
                            # followed; seen_realpaths stops junction loops.
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                                continue
                            # Do not follow file symlinks either. A link and its
                            # target would form a fake exact-duplicate pair, and
                            # deleting the link path resolves to (and trashes)
                            # the target the user chose to keep.
                            if entry.is_symlink() or not entry.is_file():
                                continue
                            extension = os.path.splitext(entry.name)[1].lower()
                            if extension not in SUPPORTED_EXTENSIONS:
                                continue
                            filepath = entry.path
                            if len(filepath) > 259:
                                logger.warning("Path exceeds MAX_PATH (260): %s", filepath)
                                skipped_files += 1
                                continue
                            if collect_sizes:
                                # On Windows, DirEntry.stat() reuses the directory
                                # enumeration data for ordinary files, unlike a later
                                # os.path.getsize(path) call.
                                file_sizes[filepath] = entry.stat().st_size
                            all_files.append(filepath)
                        except OSError:
                            logger.debug("Failed to inspect directory entry: %s", entry.path, exc_info=True)
            except OSError:
                logger.debug("Failed to scan directory: %s", current_directory, exc_info=True)

        all_files.sort(key=os.path.normcase)
        return all_files, file_sizes, skipped_files

    def _scan_exact(
        self,
        all_files: list[str],
        file_sizes: dict[str, int],
        callback: Callable[[str, Dict], None],
    ) -> list[list[str]]:
        callback('status', {'message': 'Grouping by size captured during file enumeration...'})
        size_groups: dict[int, list[str]] = defaultdict(list)
        for index, filepath in enumerate(all_files, start=1):
            if self.cancel_requested:
                return []
            file_size = file_sizes.get(filepath)
            if file_size is None:
                logger.debug("Missing cached file size: %s", filepath)
                continue
            size_groups[file_size].append(filepath)
            if index % 500 == 0:
                callback('progress', {'current': index, 'total': self.total_files, 'phase': 'size_grouping'})

        files_to_filter = [
            filepath
            for paths in size_groups.values()
            if len(paths) > 1
            for filepath in paths
        ]
        if not files_to_filter or self.cancel_requested:
            return []

        callback('status', {'message': f'Filtering {len(files_to_filter)} same-size files by prefix hash...'})
        prefix_groups: dict[tuple[int, str], list[str]] = defaultdict(list)
        # Files whose size changed after enumeration: a prefix match alone
        # proves nothing about them, even if they were small when listed.
        resized_files: set[str] = set()
        for completed, (filepath, prefix_result) in enumerate(
            self._iter_parallel_results(files_to_filter, get_file_prefix_hash_and_length), start=1
        ):
            if self.cancel_requested:
                return []
            if prefix_result:
                prefix_hash, bytes_read = prefix_result
                if bytes_read != min(file_sizes[filepath], PREFIX_HASH_SIZE + 1):
                    resized_files.add(filepath)
                prefix_groups[(file_sizes[filepath], prefix_hash)].append(filepath)
            if completed % 100 == 0:
                callback('progress', {'current': completed, 'total': len(files_to_filter), 'phase': 'prefix_filter'})

        exact_results: list[list[str]] = []
        files_to_hash: list[str] = []
        for (file_size, _), paths in prefix_groups.items():
            if len(paths) < 2:
                continue
            paths.sort(key=os.path.normcase)
            if file_size <= PREFIX_HASH_SIZE and resized_files.isdisjoint(paths):
                exact_results.append(paths)
            else:
                files_to_hash.extend(paths)

        if self.cancel_requested or not files_to_hash:
            return self._sorted_groups(exact_results)

        callback('status', {'message': f'Computing full exact hashes for {len(files_to_hash)} prefix candidates...'})
        full_hash_groups: dict[str, list[str]] = defaultdict(list)
        for completed, (filepath, file_hash) in enumerate(
            self._iter_parallel_results(files_to_hash, get_file_hash), start=1
        ):
            if self.cancel_requested:
                return self._sorted_groups(exact_results)
            if file_hash:
                full_hash_groups[file_hash].append(filepath)
            if completed % 100 == 0:
                callback('progress', {'current': completed, 'total': len(files_to_hash), 'phase': 'exact'})

        exact_results.extend(paths for paths in full_hash_groups.values() if len(paths) > 1)
        return self._sorted_groups(exact_results)

    def _scan_similar(self, all_files: list[str], callback: Callable[[str, Dict], None]) -> list[list[str]]:
        callback('status', {'message': 'Computing perceptual hashes for similar matches...'})
        phash_dict: dict[str, list[str]] = defaultdict(list)
        for completed, (filepath, phash) in enumerate(
            self._iter_parallel_results(all_files, get_image_phash), start=1
        ):
            if self.cancel_requested:
                return []
            if phash:
                phash_dict[phash].append(filepath)
            if completed % 100 == 0:
                callback('progress', {'current': completed, 'total': self.total_files, 'phase': 'similar'})

        callback('status', {'message': 'Clustering similar photos...'})
        ordered_phash_dict = {
            phash: sorted(paths, key=os.path.normcase)
            for phash, paths in sorted(phash_dict.items())
        }
        return cluster_similar_hashes(
            ordered_phash_dict,
            cancel_event=self._cancel_event,
            progress_callback=lambda current, total: callback(
                'progress', {'current': current, 'total': total, 'phase': 'clustering'}
            ),
        )

    @staticmethod
    def _sorted_groups(groups: list[list[str]]) -> list[list[str]]:
        normalized_groups = [sorted(group, key=os.path.normcase) for group in groups]
        return sorted(normalized_groups, key=lambda group: os.path.normcase(group[0]))

    def generate_thumbnail(self, image_path: str, max_size: tuple[int, int] = (256, 256)) -> bytes:
        return generate_thumbnail(image_path, max_size)
