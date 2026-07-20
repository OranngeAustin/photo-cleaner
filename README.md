# Photo Cleaner

A high-performance local Windows tool for finding and safely cleaning exact duplicate and visually similar photos. It combines a FastAPI backend with a desktop WebView interface for fast review of large photo libraries and long screenshots.

## Download

A packaged Windows build is prepared for GitHub Releases. Download the executable from the repository's **Releases** page when available.

## Features

### Exact and Similar Matching

- **Exact duplicates:** groups files by SHA-256 content rather than file name.
- **Similar photos:** uses perceptual hashing (pHash) to identify visually similar images such as bursts and crops.
- **Efficient candidate selection:** exact matching narrows work by file size and a 64 KiB prefix hash before calculating a full hash. Similar matching uses a six-segment candidate index and confirms matches by Hamming distance.
- **Lazy thumbnails:** the interface loads thumbnail images on demand.

### Review Workflow

- Switch between **Exact Matches** and **Similar Matches**.
- Use `W` and `S` to move between groups, `A` and `D` or the arrow keys to move between images, and `Space` or left-click to select an image.
- Press `Enter`, right-click, or double-click to open the original image preview.
- Hold the left mouse button or `Space` in the preview to zoom and drag across the image.
- The preview shows the file name, capture date when available, and file size.

### Safe Cleanup

- A clean action first enters a three-second undo window. Press `Ctrl+Z` or use **Undo** to cancel it.
- **Deduplicate All** keeps the first item in each exact-match group and queues the rest for cleanup.
- Similar-photo cleanup only deletes unselected photos and asks for confirmation first.
- Confirmed files are moved through `Send2Trash` to the Windows Recycle Bin. A failed or partial deletion leaves unaffected photos visible for retry.

## Implementation Notes

- A bounded worker pool performs hashing and responds to scan cancellation between blocks.
- Thumbnail cache keys include the source path, file modification time in nanoseconds, and file size.
- Every preview and deletion request is checked against the active scan root and the cached scan results, preventing arbitrary path reads or deletions.
- The static `web/` directory is automatically located from the project directory during development and from the PyInstaller bundle when packaged.

## Run from Source

Requirements: Python 3.12 or later on Windows.

```powershell
python -m pip install -r requirements.txt
python main.py
```

### WebView2 Runtime

The Windows build uses the Microsoft Edge WebView2 Runtime. It is included with most current Windows installations; if the application window does not open, install the WebView2 Runtime and try again.

## Build a Windows Executable

```powershell
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --onefile --name PhotoCleaner --add-data web;web main.py
```

The `--add-data web;web` option embeds the HTML, CSS, and JavaScript interface in the executable.

## Tests

```powershell
python -m pytest -q
node --test tests/test_frontend.js
```

The automated coverage includes scanning, cancellation, cache invalidation, transparent image thumbnails, path authorization, preview metadata, safe deletion behavior, undo flows, and keyboard and mouse preview interactions.
