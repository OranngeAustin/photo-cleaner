import hashlib
import io
import logging
import os
import threading
from collections import defaultdict
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from functools import lru_cache
from typing import Callable, Dict, Iterator

import imagehash
from PIL import Image


logger = logging.getLogger(__name__)

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


def _was_cancelled(cancel_event: threading.Event | None) -> bool:
    return cancel_event is not None and cancel_event.is_set()


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


def get_file_prefix_hash(
    filepath: str,
    cancel_event: threading.Event | None = None,
    prefix_size: int = PREFIX_HASH_SIZE,
) -> str:
    """Hash only a file prefix for the exact-match prefilter."""
    try:
        if _was_cancelled(cancel_event):
            return ""
        with open(filepath, 'rb') as file_obj:
            prefix = file_obj.read(prefix_size)
        if _was_cancelled(cancel_event):
            return ""
        return hashlib.sha256(prefix).hexdigest()
    except OSError:
        logger.warning("Failed to hash file prefix: %s", filepath, exc_info=True)
        return ""


def get_image_phash(filepath: str, cancel_event: threading.Event | None = None) -> str:
    try:
        if _was_cancelled(cancel_event):
            return ""
        with Image.open(filepath) as img:
            result = str(imagehash.phash(img))
        return "" if _was_cancelled(cancel_event) else result
    except Exception:
        logger.warning("Failed to compute pHash: %s", filepath, exc_info=True)
        return ""


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
    try:
        with Image.open(image_path) as img:
            max_size = (max_width, max_height)
            if img.format == 'JPEG':
                img.draft('RGB', max_size)
                img.load()
            # JPEG has no alpha channel. Normalize PNG/GIF transparency first,
            # including palette images whose transparency is a byte table, then
            # composite it on a deterministic white background.
            if "transparency" in img.info:
                img = img.convert("RGBA")
            if img.mode in ("RGBA", "LA"):
                background = Image.new("RGB", img.size, "white")
                background.paste(img, mask=img.getchannel("A"))
                img = background
            elif img.mode != "RGB":
                img = img.convert("RGB")
            img.thumbnail(max_size)
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format='JPEG', quality=85)
            return img_byte_arr.getvalue()
    except Exception:
        logger.warning("Failed to generate thumbnail: %s", image_path, exc_info=True)
        return b""


def clear_thumbnail_cache() -> None:
    _generate_thumbnail_cached.cache_clear()


def generate_thumbnail(image_path: str, max_size: tuple[int, int] = (256, 256)) -> bytes:
    try:
        real_path = os.path.realpath(image_path)
        stat_result = os.stat(real_path)
        return _generate_thumbnail_cached(
            real_path,
            int(max_size[0]),
            int(max_size[1]),
            stat_result.st_mtime_ns,
            stat_result.st_size,
        )
    except OSError:
        logger.warning("Failed to stat thumbnail source: %s", image_path, exc_info=True)
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

    candidate_index: dict[tuple[int, int], list[int]] = defaultdict(list)
    for index, hash_value in enumerate(hash_values):
        for segment_index, (shift, width) in enumerate(PHASH_SEGMENTS):
            candidate_index[(segment_index, _segment_value(hash_value, shift, width))].append(index)

    visited_hashes: set[str] = set()
    similar_results: list[list[str]] = []
    use_index = threshold < len(PHASH_SEGMENTS)

    for index, hash_key in enumerate(hash_keys):
        if _was_cancelled(cancel_event):
            break
        if progress_callback and index % 100 == 0:
            progress_callback(index, total_keys)
        if hash_key in visited_hashes:
            continue

        group = list(phash_dict[hash_key])
        visited_hashes.add(hash_key)
        hash_value = hash_values[index]

        if use_index:
            candidate_indexes: set[int] = set()
            for segment_index, (shift, width) in enumerate(PHASH_SEGMENTS):
                candidate_indexes.update(
                    candidate_index[(segment_index, _segment_value(hash_value, shift, width))]
                )
            indexes_to_check = sorted(candidate_indexes)
        else:
            # The six segments are lossless only for thresholds below six.
            indexes_to_check = range(index + 1, total_keys)

        for other_index in indexes_to_check:
            if _was_cancelled(cancel_event):
                break
            if other_index <= index:
                continue
            other_key = hash_keys[other_index]
            if other_key in visited_hashes:
                continue
            if (hash_value ^ hash_values[other_index]).bit_count() <= threshold:
                group.extend(phash_dict[other_key])
                visited_hashes.add(other_key)

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
        worker: Callable[[str, threading.Event], str],
    ) -> Iterator[tuple[str, str]]:
        """Process a bounded number of futures so cancellation is prompt."""
        if not filepaths:
            return

        worker_count = self._worker_count()
        max_in_flight = worker_count * 2
        file_iterator = iter(filepaths)

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            pending: dict[object, str] = {}

            def submit_next() -> bool:
                try:
                    filepath = next(file_iterator)
                except StopIteration:
                    return False
                pending[executor.submit(worker, filepath, self._cancel_event)] = filepath
                return True

            for _ in range(min(max_in_flight, len(filepaths))):
                submit_next()

            while pending:
                if self.cancel_requested:
                    for future in pending:
                        future.cancel()
                    return

                completed, _ = wait(pending, return_when=FIRST_COMPLETED)
                for future in completed:
                    filepath = pending.pop(future)
                    try:
                        result = future.result()
                    except Exception:
                        logger.warning("Worker failed for file: %s", filepath, exc_info=True)
                        result = ""
                    yield filepath, result
                    if self.cancel_requested:
                        break
                    submit_next()

    def _finish(self, callback: Callable[[str, Dict], None], data: Dict) -> None:
        self.is_scanning = False
        callback('done', data)

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
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(entry.path)
                                continue
                            if not entry.is_file():
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
        for completed, (filepath, prefix_hash) in enumerate(
            self._iter_parallel_results(files_to_filter, get_file_prefix_hash), start=1
        ):
            if self.cancel_requested:
                return []
            if prefix_hash:
                prefix_groups[(file_sizes[filepath], prefix_hash)].append(filepath)
            if completed % 100 == 0:
                callback('progress', {'current': completed, 'total': len(files_to_filter), 'phase': 'prefix_filter'})

        exact_results: list[list[str]] = []
        files_to_hash: list[str] = []
        for (file_size, _), paths in prefix_groups.items():
            if len(paths) < 2:
                continue
            paths.sort(key=os.path.normcase)
            if file_size <= PREFIX_HASH_SIZE:
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
