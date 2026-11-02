// State
let exactData = [];
let similarData = [];
let activeCountdownId = null;
let countdownInterval = null;
let currentFocus = { rowIdx: -1, imgIdx: -1, tab: 'exact' };
let scanInProgress = false;
let pendingDeletion = null; // { type, tabName, rows, paths, timerId, committing }

let currentDirectory = '';

// DOM Elements
const tabs = document.querySelectorAll('.tab-btn');
const tabContents = document.querySelectorAll('.tab-content');
const browseBtn = document.getElementById('browse-btn');
const currentDirSpan = document.getElementById('current-dir');
const statusBar = document.getElementById('status-bar');
const statusText = document.getElementById('status-text');
const progressBar = document.getElementById('progress-bar');
const exactList = document.getElementById('exact-list');
const similarList = document.getElementById('similar-list');
const lightbox = document.getElementById('lightbox');
const lightboxViewport = document.getElementById('lightbox-viewport');
const lightboxImg = document.getElementById('lightbox-img');
const lightboxName = document.getElementById('lightbox-name');
const lightboxCapturedAt = document.getElementById('lightbox-captured-at');
const lightboxSize = document.getElementById('lightbox-size');
const scrollContainer = document.getElementById('scroll-container');

// Tab Switching
tabs.forEach(tab => {
    tab.addEventListener('click', async () => {
        const mode = tab.dataset.tab;
        tabs.forEach(t => t.classList.remove('active'));
        tabContents.forEach(c => c.classList.remove('active'));
        tab.classList.add('active');
        document.getElementById(`tab-${tab.dataset.tab}`).classList.add('active');
        focusFirstVisibleRow(mode);

        // Auto-scan if folder is chosen and this tab has no data yet
        const tabData = mode === 'exact' ? exactData : similarData;
        if (!currentDirectory || tabData.length > 0) return;
        // Finish a staged delete first, or the new results could still list
        // the files it is about to remove.
        await commitPendingDeletion();
        // The user may have switched tabs again while the delete was running.
        if (currentFocus.tab === mode) startScan(currentDirectory, mode);
    });
});

// Lightbox zoom, pan, and metadata
const ZOOM_SCALE = 2;
let isZoomed = false;
let lightboxPanX = 0;
let lightboxPanY = 0;
let activeLightboxPointerId = null;
let lightboxPointerStart = null;
let lightboxPanStart = null;
let pointerZoomHeld = false;
let spaceZoomHeld = false;
let lightboxInfoRequestId = 0;

function clamp(value, minimum, maximum) {
    return Math.min(Math.max(value, minimum), maximum);
}

function updateLightboxTransform() {
    if (!isZoomed) {
        lightboxImg.style.transform = '';
        return;
    }
    const viewportRect = lightboxViewport.getBoundingClientRect();
    const maxPanX = Math.max(0, (lightboxImg.clientWidth * ZOOM_SCALE - viewportRect.width) / 2);
    const maxPanY = Math.max(0, (lightboxImg.clientHeight * ZOOM_SCALE - viewportRect.height) / 2);
    lightboxPanX = clamp(lightboxPanX, -maxPanX, maxPanX);
    lightboxPanY = clamp(lightboxPanY, -maxPanY, maxPanY);
    lightboxImg.style.transform = `translate(${lightboxPanX}px, ${lightboxPanY}px) scale(${ZOOM_SCALE})`;
}

function resetLightboxPan() {
    lightboxPanX = 0;
    lightboxPanY = 0;
    updateLightboxTransform();
}

function setZoom(zoom) {
    if (zoom === isZoomed) {
        if (!zoom) resetLightboxPan();
        return;
    }
    isZoomed = zoom;
    lightbox.classList.toggle('zoomed', zoom);
    lightboxImg.classList.toggle('zoomed', zoom);
    if (!zoom) {
        resetLightboxPan();
    } else {
        updateLightboxTransform();
    }
}

function syncLightboxZoom({ resetPan = false } = {}) {
    const shouldZoom = pointerZoomHeld || spaceZoomHeld;
    setZoom(shouldZoom);
    if (resetPan && shouldZoom) resetLightboxPan();
}

function finishLightboxPan(event) {
    if (event.pointerId !== activeLightboxPointerId) return;
    if (typeof lightboxViewport.releasePointerCapture === 'function' && lightboxViewport.hasPointerCapture?.(event.pointerId)) {
        lightboxViewport.releasePointerCapture(event.pointerId);
    }
    activeLightboxPointerId = null;
    lightboxPointerStart = null;
    lightboxPanStart = null;
    pointerZoomHeld = false;
    lightbox.classList.remove('panning');
    syncLightboxZoom({ resetPan: true });
}

lightboxViewport.addEventListener('pointerdown', (event) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    pointerZoomHeld = true;
    syncLightboxZoom();
    activeLightboxPointerId = event.pointerId;
    lightboxPointerStart = { x: event.clientX, y: event.clientY };
    lightboxPanStart = { x: lightboxPanX, y: lightboxPanY };
    lightbox.classList.add('panning');
    if (typeof lightboxViewport.setPointerCapture === 'function') {
        lightboxViewport.setPointerCapture(event.pointerId);
    }
});

lightboxViewport.addEventListener('pointermove', (event) => {
    if (event.pointerId !== activeLightboxPointerId || !lightboxPointerStart || !lightboxPanStart) return;
    const deltaX = event.clientX - lightboxPointerStart.x;
    const deltaY = event.clientY - lightboxPointerStart.y;
    if (Math.hypot(deltaX, deltaY) < 3) return;
    lightboxPanX = lightboxPanStart.x + deltaX;
    lightboxPanY = lightboxPanStart.y + deltaY;
    updateLightboxTransform();
});

lightboxViewport.addEventListener('pointerup', finishLightboxPan);
lightboxViewport.addEventListener('pointercancel', finishLightboxPan);
lightboxImg.addEventListener('load', () => updateLightboxTransform());

function displayFileName(path) {
    const segments = path.split(/[\\/]/);
    return segments[segments.length - 1] || path;
}

function formatFileSize(sizeBytes) {
    if (!Number.isFinite(sizeBytes) || sizeBytes < 0) return '未知';
    const units = ['B', 'KB', 'MB', 'GB', 'TB'];
    let value = sizeBytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024;
        unitIndex++;
    }
    const decimals = unitIndex === 0 ? 0 : (value >= 10 ? 1 : 2);
    return `${value.toFixed(decimals)} ${units[unitIndex]}`;
}

function updateLightboxInfo({ name = '—', capturedAt = '—', size = '—' }) {
    lightboxName.textContent = name;
    lightboxCapturedAt.textContent = capturedAt;
    lightboxSize.textContent = size;
}

function loadLightboxInfo(path) {
    const requestId = ++lightboxInfoRequestId;
    const fallbackName = displayFileName(path);
    updateLightboxInfo({ name: fallbackName, capturedAt: '加载中…', size: '加载中…' });
    fetch(`/api/photo_info?path=${encodeURIComponent(path)}`)
        .then(response => {
            if (!response.ok) throw new Error(`Photo metadata request failed: ${response.status}`);
            return response.json();
        })
        .then(info => {
            if (requestId !== lightboxInfoRequestId || lightbox.classList.contains('hidden')) return;
            updateLightboxInfo({
                name: info.name || fallbackName,
                capturedAt: info.captured_at || '未记录',
                size: formatFileSize(info.size_bytes),
            });
        })
        .catch(() => {
            if (requestId !== lightboxInfoRequestId || lightbox.classList.contains('hidden')) return;
            updateLightboxInfo({ name: fallbackName, capturedAt: '未能读取', size: '未能读取' });
        });
}

function closeLightbox() {
    lightbox.classList.add('hidden');
    lightbox.classList.remove('panning');
    activeLightboxPointerId = null;
    lightboxPointerStart = null;
    lightboxPanStart = null;
    pointerZoomHeld = false;
    spaceZoomHeld = false;
    lightboxInfoRequestId++;
    lightboxImg.src = '';
    updateLightboxInfo({});
    setZoom(false);
}

document.addEventListener('keyup', (e) => {
    if (e.key === ' ') {
        spaceZoomHeld = false;
        syncLightboxZoom();
    }
});

// Lightbox
document.querySelector('.lightbox-close').addEventListener('click', () => {
    closeLightbox();
});
lightbox.addEventListener('click', (e) => {
    if (e.target === lightbox) {
        closeLightbox();
    }
});
lightbox.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    closeLightbox();
});

// Disable global context menu
document.addEventListener('contextmenu', e => e.preventDefault());

// Auto Deduplicate
const autoDedupBtn = document.getElementById('auto-dedup-btn');
const similarAutoDedupBtn = document.getElementById('similar-auto-dedup-btn');

function setScanControls(isScanning) {
    scanInProgress = isScanning;
    browseBtn.disabled = isScanning;
    tabs.forEach(tab => {
        tab.disabled = isScanning;
    });
    if (autoDedupBtn) autoDedupBtn.disabled = isScanning;
    if (similarAutoDedupBtn) similarAutoDedupBtn.disabled = isScanning;
}

// A newer scan may have started by the time this fires; keep its progress visible.
function hideStatusBarLater() {
    setTimeout(() => {
        if (!scanInProgress) statusBar.classList.add('hidden');
    }, 5000);
}

function showScanError(message) {
    statusText.textContent = `⚠ ${message}`;
    progressBar.style.width = '0%';
    statusBar.classList.remove('hidden');
    hideStatusBarLater();
}

function stageBulkDeletion(tabName, rows, paths, toastMessage) {
    if (paths.length === 0) return false;

    if (pendingDeletion) undoPendingDeletion();

    rows.forEach(row => {
        row.style.display = 'none';
    });

    pendingDeletion = {
        type: 'global',
        tabName,
        rows,
        paths,
        timerId: setTimeout(() => commitPendingDeletion(), 3000),
        committing: false,
        focus: moveFocusOffHiddenRows(tabName)
    };
    showToast(toastMessage);
    return true;
}

if (autoDedupBtn) {
    autoDedupBtn.addEventListener('click', () => {
        if (scanInProgress || pendingDeletion?.committing) return;
        const rows = Array.from(document.querySelectorAll('#tab-exact .group-row')).filter(r => r.style.display !== 'none');
        if (rows.length === 0) return;
        
        const toDeleteAll = [];
        const rowsToHide = [];
        rows.forEach(row => {
            const items = Array.from(row.querySelectorAll('.image-item'));
            const pathsToDelete = items.slice(1).map(item => item.dataset.path);
            if (pathsToDelete.length > 0) {
                toDeleteAll.push(...pathsToDelete);
                rowsToHide.push(row);
            }
        });
        
        stageBulkDeletion(
            'exact',
            rowsToHide,
            toDeleteAll,
            `${toDeleteAll.length} exact duplicate photos marked; moving to Recycle Bin in 3 seconds.`
        );
    });
}

if (similarAutoDedupBtn) {
    similarAutoDedupBtn.addEventListener('click', () => {
        if (scanInProgress || pendingDeletion?.committing) return;
        const visibleRows = Array.from(document.querySelectorAll('#tab-similar .group-row'))
            .filter(row => row.style.display !== 'none');
        const pendingSimilarRows = pendingDeletion?.tabName === 'similar'
            ? pendingDeletion.rows
            : [];
        const rows = Array.from(new Set([...visibleRows, ...pendingSimilarRows]));
        const toDeleteAll = [];
        const rowsToHide = [];

        rows.forEach(row => {
            const pathsToDelete = Array.from(row.querySelectorAll('.image-item'))
                .filter(item => !item.classList.contains('selected'))
                .map(item => item.dataset.path);
            if (pathsToDelete.length > 0) {
                toDeleteAll.push(...pathsToDelete);
                rowsToHide.push(row);
            }
        });

        if (toDeleteAll.length === 0) return;
        const confirmed = window.confirm(
            `将删除 ${toDeleteAll.length} 张未勾选的高度相似照片。\n\n请确认您已浏览全部照片，并确认删除这些未勾选的照片？`
        );
        if (!confirmed) return;

        stageBulkDeletion(
            'similar',
            rowsToHide,
            toDeleteAll,
            `${toDeleteAll.length} similar photos marked; moving to Recycle Bin in 3 seconds.`
        );
    });
}

// Scan Logic
browseBtn.addEventListener('click', async () => {
    if (window.pywebview && window.pywebview.api) {
        const folder = await window.pywebview.api.choose_directory();
        if (folder) {
            // Finish a staged delete while its folder is still the authorized
            // scan root; the scan below replaces that root.
            await commitPendingDeletion();
            currentDirectory = folder;
            currentDirSpan.textContent = folder;
            // Clear old data
            exactData = [];
            similarData = [];
            exactList.innerHTML = '';
            similarList.innerHTML = '';
            
            // Auto start scan for current tab
            startScan(currentDirectory, currentFocus.tab);
        }
    }
});

async function startScan(directory, mode) {
    if (!directory || scanInProgress) return false;
    
    statusBar.classList.remove('hidden');
    setScanControls(true);

    try {
        const response = await fetch('/api/scan', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({directory, mode})
        });
        const responseData = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(responseData.error || `Scan request failed (${response.status})`);
        }
        pollStatus(mode);
        return true;
    } catch (error) {
        setScanControls(false);
        showScanError(error.message || 'Unable to start scan.');
        return false;
    }
}

// One failed status poll does not mean the scan stopped, so retry with backoff.
// Giving up abandons the results: cancel the backend scan as well, or the next
// scan is refused while it keeps running.
const STATUS_POLL_RETRY_DELAYS = [500, 1000, 2000, 4000];

function retryOrAbandonScan(mode, failures, error) {
    if (failures < STATUS_POLL_RETRY_DELAYS.length) {
        setTimeout(() => pollStatus(mode, failures + 1), STATUS_POLL_RETRY_DELAYS[failures]);
        return;
    }
    Promise.resolve()
        .then(() => fetch('/api/cancel_scan', { method: 'POST' }))
        .catch(() => {});
    setScanControls(false);
    showScanError(error.message || 'Lost connection while scanning.');
}

async function pollStatus(mode, failures = 0) {
    if (!scanInProgress) return;
    let data;
    try {
        const res = await fetch('/api/scan_status');
        if (!res.ok) throw new Error(`Status request failed (${res.status})`);
        data = await res.json();
    } catch (error) {
        retryOrAbandonScan(mode, failures, error);
        return;
    }
    try {
    statusText.textContent = data.message;
    if (data.progress && data.progress.total) {
        const pct = (data.progress.current / data.progress.total) * 100;
        progressBar.style.width = `${pct}%`;
    }
    
    if (data.done) {
        setScanControls(false);
        statusBar.classList.add('hidden');
        if (mode === 'exact') {
            exactData = data.results.exact || [];
            renderList(exactData, exactList, 'exact');
            if (exactData.length > 0) {
                currentFocus = { rowIdx: 0, imgIdx: 0, tab: 'exact' };
                updateFocusUI();
            }
        } else {
            similarData = data.results.similar || [];
            renderList(similarData, similarList, 'similar');
            if (similarData.length > 0) {
                currentFocus = { rowIdx: 0, imgIdx: 0, tab: 'similar' };
                updateFocusUI();
            }
        }
        // Show contextual post-scan messages
        let postMsg = '';
        if (data.results.error) {
            postMsg = `⚠ ${data.results.error}`;
        } else if (data.cancelled) {
            postMsg = '\u26A0 Scan cancelled \u2014 results may be incomplete.';
        } else if (data.results.empty_scan) {
            postMsg = 'No supported images found in the selected directory.';
        } else {
            const resultCount = (mode === 'exact')
                ? (data.results.exact || []).length
                : (data.results.similar || []).length;
            if (resultCount === 0) {
                postMsg = `\u2705 No ${mode === 'exact' ? 'duplicate' : 'similar'} photos found.`;
            }
        }
        const skipped = data.results.skipped_files || 0;
        if (skipped > 0) {
            postMsg += (postMsg ? ' ' : '') + `(${skipped} file(s) skipped due to path length)`;
        }
        if (postMsg) {
            statusText.textContent = postMsg;
            progressBar.style.width = '0%';
            statusBar.classList.remove('hidden');
            hideStatusBarLater();
        }
    } else {
        setTimeout(() => pollStatus(mode), 500);
    }
    } catch (error) {
        setScanControls(false);
        showScanError(error.message || 'Lost connection while scanning.');
    }
}

// Render List (Using simple Chunking + Lazy Loading images)
function renderList(groups, container, tabName, selectedPaths = null) {
    container.innerHTML = '';
    // To implement extreme virtual list we would use IO, but for now 
    // rendering DOM nodes with <img loading="lazy"> is very fast up to ~5000 rows.
    // For simplicity, we just create the rows.
    groups.forEach((group, rIdx) => {
        const row = document.createElement('div');
        row.className = 'group-row';
        row.dataset.rowIdx = rIdx;
        row.dataset.tab = tabName;
        row.id = `row-${tabName}-${rIdx}`;
        
        const header = document.createElement('div');
        header.className = 'group-header';
        header.innerHTML = `
            <span>Group ${rIdx + 1} (${group.length} items)</span>
            <button class="btn danger clean-btn">Clean Unselected</button>
        `;
        
        const imgsContainer = document.createElement('div');
        imgsContainer.className = 'group-images';
        
        group.forEach((path, iIdx) => {
            const item = document.createElement('div');
            item.className = 'image-item';
            // A fresh scan selects the first item by default. A re-render after a
            // partial delete restores the user's surviving selections by path.
            if (selectedPaths ? selectedPaths.has(path) : iIdx === 0) {
                item.classList.add('selected');
            }
            
            item.dataset.path = path;
            item.dataset.rIdx = rIdx;
            item.dataset.iIdx = iIdx;
            
            const img = document.createElement('img');
            img.loading = 'lazy';
            img.src = `/api/thumbnail?path=${encodeURIComponent(path)}`;
            item.appendChild(img);
            
            // Mouse Interaction
            item.addEventListener('click', () => {
                item.classList.toggle('selected');
                setFocus(tabName, rIdx, iIdx);
            });
            item.addEventListener('contextmenu', (e) => {
                e.preventDefault();
                showLightbox(path);
                setFocus(tabName, rIdx, iIdx);
            });
            item.addEventListener('dblclick', (e) => {
                e.preventDefault();
                showLightbox(path);
                setFocus(tabName, rIdx, iIdx);
            });
            
            imgsContainer.appendChild(item);
        });
        
        const cleanBtn = header.querySelector('.clean-btn');
        cleanBtn.addEventListener('click', () => {
            triggerClean(tabName, rIdx);
        });
        
        row.appendChild(header);
        row.appendChild(imgsContainer);
        container.appendChild(row);
    });
}

function showLightbox(path) {
    pointerZoomHeld = false;
    spaceZoomHeld = false;
    setZoom(false);
    lightboxImg.src = `/api/image?path=${encodeURIComponent(path)}`;
    lightbox.classList.remove('hidden');
    loadLightboxInfo(path);
}

// Undo & Clean Logic

// Hiding the focused group must not leave the keyboard without a target: move
// to the nearest visible group and remember where focus was, for undo.
function moveFocusOffHiddenRows(tabName) {
    if (currentFocus.tab !== tabName || currentFocus.rowIdx < 0) return null;
    const focusedRow = document.getElementById(`row-${tabName}-${currentFocus.rowIdx}`);
    if (focusedRow && focusedRow.style.display !== 'none') return null;

    const previous = { ...currentFocus };
    const rows = visibleRows(tabName);
    const target = rows.find(row => Number(row.dataset.rowIdx) > previous.rowIdx)
        || rows.reverse().find(row => Number(row.dataset.rowIdx) < previous.rowIdx);
    currentFocus = target
        ? { rowIdx: Number(target.dataset.rowIdx), imgIdx: 0, tab: tabName }
        : { rowIdx: -1, imgIdx: -1, tab: tabName };
    updateFocusUI();
    return { previous, staged: { ...currentFocus } };
}

// Undo (or a failed delete) returns focus to the restored group, unless the
// user has already moved it somewhere else.
function restoreFocusAfterUndo(deletion) {
    const saved = deletion.focus;
    if (!saved || currentFocus.tab !== saved.previous.tab) return;
    if (currentFocus.rowIdx !== saved.staged.rowIdx || currentFocus.imgIdx !== saved.staged.imgIdx) return;
    currentFocus = { ...saved.previous };
    updateFocusUI();
}

function restorePendingDeletion(deletion) {
    deletion.rows.forEach(row => {
        row.style.display = 'flex';
    });
}

function removeDeletedPaths(tabName, deletedPaths) {
    const currentData = tabName === 'exact' ? exactData : similarData;
    const container = tabName === 'exact' ? exactList : similarList;
    const previouslySelected = Array.from(container.querySelectorAll('.image-item.selected'))
        .map(item => item.dataset.path);
    const selectedPaths = new Set(previouslySelected.filter(path => !deletedPaths.has(path)));
    const lostSelections = new Set(previouslySelected.filter(path => deletedPaths.has(path)));
    const survivingGroups = currentData.map(group => group.filter(path => !deletedPaths.has(path)));
    const updatedData = survivingGroups.filter(group => group.length > 1);

    // A kept photo can be deleted from the other tab. Never leave such a group
    // with nothing selected, or the next clean would remove every remaining copy.
    currentData.forEach(group => {
        if (!group.some(path => lostSelections.has(path))) return;
        const survivors = group.filter(path => !deletedPaths.has(path));
        if (survivors.length > 1 && !survivors.some(path => selectedPaths.has(path))) {
            selectedPaths.add(survivors[0]);
        }
    });

    if (tabName === 'exact') {
        exactData = updatedData;
    } else {
        similarData = updatedData;
    }
    renderList(updatedData, container, tabName, selectedPaths);

    if (currentFocus.tab === tabName) {
        // Stay on the focused photo's group, or the next group still listed,
        // instead of jumping back to the top of the list.
        const focusedPath = currentData[currentFocus.rowIdx]?.[currentFocus.imgIdx];
        const groupsBefore = survivingGroups
            .slice(0, Math.max(currentFocus.rowIdx, 0))
            .filter(group => group.length > 1).length;
        const rowIdx = Math.min(groupsBefore, updatedData.length - 1);
        currentFocus = rowIdx >= 0
            ? { rowIdx, imgIdx: Math.max(updatedData[rowIdx].indexOf(focusedPath), 0), tab: tabName }
            : { rowIdx: -1, imgIdx: -1, tab: tabName };
        updateFocusUI();
    }
}

function removeDeletedPathsFromCachedResults(deletedPaths) {
    ['exact', 'similar'].forEach(tabName => {
        const data = tabName === 'exact' ? exactData : similarData;
        if (data.some(group => group.some(path => deletedPaths.has(path)))) {
            removeDeletedPaths(tabName, deletedPaths);
        }
    });
}

// Returns the in-flight request, so callers can wait for a delete that the
// undo timer (or another caller) has already started.
function commitPendingDeletion() {
    const deletion = pendingDeletion;
    if (!deletion) return Promise.resolve();
    if (!deletion.committing) {
        clearTimeout(deletion.timerId);
        deletion.committing = true;
        deletion.request = sendPendingDeletion(deletion);
    }
    return deletion.request || Promise.resolve();
}

async function sendPendingDeletion(deletion) {
    try {
        const response = await fetch('/api/delete', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({files: deletion.paths})
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.error || `Delete request failed (${response.status})`);
        }

        const requestedPaths = new Set(deletion.paths);
        const deletedPaths = new Set(
            (Array.isArray(data.deleted) ? data.deleted : [])
                .filter(path => requestedPaths.has(path))
        );
        if (deletedPaths.size > 0) {
            removeDeletedPathsFromCachedResults(deletedPaths);
        }
        restorePendingDeletion(deletion);
        // A re-render (above) already reset focus; otherwise the rows are back as they were.
        if (deletedPaths.size === 0) restoreFocusAfterUndo(deletion);

        const failedCount = deletion.paths.filter(path => !deletedPaths.has(path)).length;
        if (failedCount > 0) {
            showToast(`\u26A0 ${failedCount} file(s) could not be deleted. They remain visible.`);
        } else {
            hideToast();
        }
    } catch (error) {
        restorePendingDeletion(deletion);
        restoreFocusAfterUndo(deletion);
        showToast('\u26A0 Delete failed. The photos remain visible and can be retried.');
    } finally {
        if (pendingDeletion === deletion) {
            pendingDeletion = null;
        }
    }
}

function undoPendingDeletion() {
    if (!pendingDeletion || pendingDeletion.committing) return;

    const deletion = pendingDeletion;
    clearTimeout(deletion.timerId);
    restorePendingDeletion(deletion);
    pendingDeletion = null;
    restoreFocusAfterUndo(deletion);
    hideToast();
}

function showToast(message) {
    document.getElementById('toast-msg').textContent = message;
    document.getElementById('toast-container').classList.add('show');
}

function hideToast() {
    document.getElementById('toast-container').classList.remove('show');
}

document.getElementById('toast-undo-btn').addEventListener('click', undoPendingDeletion);

function triggerClean(tabName, rIdx) {
    if (scanInProgress || pendingDeletion?.committing) return;
    const rowId = `row-${tabName}-${rIdx}`;
    const row = document.getElementById(rowId);
    if (!row) return;

    // Gather unselected items
    const items = Array.from(row.querySelectorAll('.image-item'));
    const toDelete = items.filter(item => !item.classList.contains('selected')).map(item => item.dataset.path);
    
    if (toDelete.length === 0) return;

    // Undo previous pending deletion to preserve its undo window
    if (pendingDeletion) undoPendingDeletion();

    // Hide row immediately
    row.style.display = 'none';

    pendingDeletion = {
        type: 'single',
        tabName,
        rows: [row],
        paths: toDelete,
        timerId: setTimeout(() => commitPendingDeletion(), 3000),
        committing: false,
        focus: moveFocusOffHiddenRows(tabName)
    };
    showToast(`${toDelete.length} photos marked; moving to Recycle Bin in 3 seconds.`);
}

// Keyboard Control
function setFocus(tab, rIdx, iIdx) {
    currentFocus = { tab, rowIdx: rIdx, imgIdx: iIdx };
    updateFocusUI();
}

function updateFocusUI() {
    document.querySelectorAll('.image-item.focused').forEach(el => el.classList.remove('focused'));
    if (currentFocus.rowIdx === -1) return;
    
    const row = document.getElementById(`row-${currentFocus.tab}-${currentFocus.rowIdx}`);
    if (row) {
        const item = row.querySelector(`.image-item[data-i-idx="${currentFocus.imgIdx}"]`);
        if (item) {
            item.classList.add('focused');
            // Ensure visible in container
            item.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        }
    }
}

function visibleRows(tabName) {
    return Array.from(document.querySelectorAll(`#tab-${tabName} .group-row`))
        .filter(row => row.style.display !== 'none');
}

// Row indexes belong to one tab, so a focus carried over from the other tab
// (or from before a re-render) can point past this tab's groups.
function focusFirstVisibleRow(tabName) {
    const [row] = visibleRows(tabName);
    currentFocus = row
        ? { rowIdx: Number(row.dataset.rowIdx), imgIdx: 0, tab: tabName }
        : { rowIdx: -1, imgIdx: -1, tab: tabName };
    updateFocusUI();
}

// Rows scroll inside #scroll-container, below the fixed header, so visibility
// must be judged against the container rather than the window.
function isRowInScrollView(row) {
    if (!row || row.style.display === 'none') return false;
    const viewRect = scrollContainer.getBoundingClientRect();
    const rect = row.getBoundingClientRect();
    return rect.bottom > viewRect.top && rect.top < viewRect.bottom;
}

// Delete cleans the focused group. If focus was scrolled out of view with the
// mouse, fall back to the first group that is actually visible in the list.
function findDeleteTargetRow(tabName, focusedRowIdx) {
    const focusedRow = document.getElementById(`row-${tabName}-${focusedRowIdx}`);
    if (isRowInScrollView(focusedRow)) return focusedRow;

    const viewRect = scrollContainer.getBoundingClientRect();
    return Array.from(document.querySelectorAll(`#tab-${tabName} .group-row`)).find(row => {
        if (!isRowInScrollView(row)) return false;
        const rect = row.getBoundingClientRect();
        return rect.top >= viewRect.top || rect.bottom > viewRect.top + 100;
    }) || null;
}

document.addEventListener('keydown', (e) => {
    // Check for Ctrl+Z undo
    if ((e.ctrlKey || e.metaKey) && (e.key === 'z' || e.key === 'Z')) {
        if (pendingDeletion) {
            undoPendingDeletion();
            e.preventDefault();
        }
        return;
    }

    const isLightboxOpen = !lightbox.classList.contains('hidden');

    if (isLightboxOpen) {
        if (e.key === 'Escape' || e.key === 'Enter') {
            closeLightbox();
            e.preventDefault();
            return;
        }
        if (e.key === ' ') {
            spaceZoomHeld = true;
            syncLightboxZoom();
            e.preventDefault();
            return;
        }
        if (!['ArrowRight', 'ArrowLeft', 'd', 'D', 'a', 'A'].includes(e.key)) {
            return; 
        }
    }
    
    const tabName = currentFocus.tab;
    const data = tabName === 'exact' ? exactData : similarData;
    if (data.length === 0 || currentFocus.rowIdx < 0) return;
    if (!data[currentFocus.rowIdx]) {
        focusFirstVisibleRow(tabName);
        return;
    }

    let { rowIdx, imgIdx } = currentFocus;
    const k = e.key.toLowerCase();

    if (e.key === 'ArrowRight' || k === 'd') {
        const maxImgs = data[rowIdx].length;
        const nextImgIdx = Math.min(imgIdx + 1, maxImgs - 1);
        if (nextImgIdx !== imgIdx) {
            setFocus(tabName, rowIdx, nextImgIdx);
            if (isLightboxOpen) showLightbox(data[rowIdx][nextImgIdx]);
        }
        e.preventDefault();
    } 
    else if (e.key === 'ArrowLeft' || k === 'a') {
        const nextImgIdx = Math.max(imgIdx - 1, 0);
        if (nextImgIdx !== imgIdx) {
            setFocus(tabName, rowIdx, nextImgIdx);
            if (isLightboxOpen) showLightbox(data[rowIdx][nextImgIdx]);
        }
        e.preventDefault();
    }
    else if (!isLightboxOpen) {
        if (e.key === 'ArrowDown' || k === 's') {
            rowIdx++;
            while (rowIdx < data.length) {
                const candidate = document.getElementById(`row-${tabName}-${rowIdx}`);
                if (candidate && candidate.style.display !== 'none') break;
                rowIdx++; // skip deleted rows
            }
            if (rowIdx >= data.length) rowIdx = currentFocus.rowIdx;
            imgIdx = 0;
            setFocus(tabName, rowIdx, imgIdx);
            e.preventDefault();
        }
        else if (e.key === 'ArrowUp' || k === 'w') {
            rowIdx--;
            while (rowIdx >= 0) {
                const candidate = document.getElementById(`row-${tabName}-${rowIdx}`);
                if (candidate && candidate.style.display !== 'none') break;
                rowIdx--;
            }
            if (rowIdx < 0) rowIdx = currentFocus.rowIdx;
            imgIdx = 0;
            setFocus(tabName, rowIdx, imgIdx);
            e.preventDefault();
        }
        else if (e.key === ' ') { // Space
            const row = document.getElementById(`row-${tabName}-${rowIdx}`);
            if (row) {
                const item = row.querySelector(`.image-item[data-i-idx="${imgIdx}"]`);
                if (item) item.classList.toggle('selected');
            }
            e.preventDefault();
        }
        else if (e.key === 'Enter') {
            const row = document.getElementById(`row-${tabName}-${rowIdx}`);
            if (row) {
                const item = row.querySelector(`.image-item[data-i-idx="${imgIdx}"]`);
                if (item) showLightbox(item.dataset.path);
            }
            e.preventDefault();
        }
        else if (e.key === 'Delete') {
            const targetRow = findDeleteTargetRow(tabName, rowIdx);
            if (targetRow) {
                const rIdx = Number(targetRow.dataset.rowIdx);
                if (Number.isInteger(rIdx)) triggerClean(tabName, rIdx);
            }
            e.preventDefault();
        }
    }
});
