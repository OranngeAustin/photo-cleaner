const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

class ClassList {
    constructor(initial = []) {
        this.values = new Set(initial);
    }

    add(...names) {
        names.forEach(name => this.values.add(name));
    }

    remove(...names) {
        names.forEach(name => this.values.delete(name));
    }

    contains(name) {
        return this.values.has(name);
    }

    toggle(name, force) {
        if (force === true) {
            this.values.add(name);
            return true;
        }
        if (force === false) {
            this.values.delete(name);
            return false;
        }
        if (this.values.has(name)) {
            this.values.delete(name);
            return false;
        }
        this.values.add(name);
        return true;
    }
}

function datasetKey(attributeName) {
    return attributeName.replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
}

function matchesSelector(element, selector) {
    const classNames = [...selector.matchAll(/\.([\w-]+)/g)].map(match => match[1]);
    if (classNames.length && !classNames.every(name => element.classList.contains(name))) {
        return false;
    }
    const dataMatch = selector.match(/\[data-([\w-]+)="([^"]*)"\]/);
    if (dataMatch) {
        return element.dataset[datasetKey(dataMatch[1])] === dataMatch[2];
    }
    return selector.startsWith('.') || classNames.length > 0;
}

class Element {
    constructor(document, tagName = 'div') {
        this.document = document;
        this.tagName = tagName.toUpperCase();
        this.children = [];
        this.parentNode = null;
        this.dataset = {};
        this.style = {};
        this.classList = new ClassList();
        this.listeners = new Map();
        this.disabled = false;
        this.src = '';
        this.textContent = '';
        this._id = '';
        this._innerHTML = '';
        this._className = '';
        this.clientWidth = 0;
        this.clientHeight = 0;
        this._rect = null;
        this.pointerCaptures = new Set();
    }

    set className(value) {
        this._className = value;
        this.classList = new ClassList(value.split(/\s+/).filter(Boolean));
    }

    get className() {
        return this._className;
    }

    set id(value) {
        this._id = value;
        this.document.elementsById.set(value, this);
    }

    get id() {
        return this._id;
    }

    set innerHTML(value) {
        this._innerHTML = value;
        this.children = [];
        if (value.includes('clean-btn')) {
            const button = this.document.createElement('button');
            button.classList.add('btn', 'danger', 'clean-btn');
            this.appendChild(button);
        }
    }

    get innerHTML() {
        return this._innerHTML;
    }

    appendChild(child) {
        if (child.parentNode) {
            child.parentNode.children = child.parentNode.children.filter(existing => existing !== child);
        }
        child.parentNode = this;
        this.children.push(child);
        return child;
    }

    remove() {
        if (this.parentNode) {
            this.parentNode.children = this.parentNode.children.filter(child => child !== this);
            this.parentNode = null;
        }
    }

    addEventListener(type, listener) {
        const listeners = this.listeners.get(type) || [];
        listeners.push(listener);
        this.listeners.set(type, listeners);
    }

    dispatch(type, event = {}) {
        const delivered = {
            preventDefault() {},
            stopPropagation() {},
            ...event,
        };
        (this.listeners.get(type) || []).forEach(listener => listener(delivered));
    }

    querySelectorAll(selector) {
        const results = [];
        const visit = element => {
            element.children.forEach(child => {
                if (matchesSelector(child, selector)) {
                    results.push(child);
                }
                visit(child);
            });
        };
        visit(this);
        return results;
    }

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }

    scrollIntoView() {}

    setPointerCapture(pointerId) {
        this.pointerCaptures.add(pointerId);
    }

    releasePointerCapture(pointerId) {
        this.pointerCaptures.delete(pointerId);
    }

    hasPointerCapture(pointerId) {
        return this.pointerCaptures.has(pointerId);
    }

    getBoundingClientRect() {
        return this._rect || { top: 0, left: 0, bottom: 100, right: 100, width: 100, height: 100 };
    }
}

class DocumentMock {
    constructor() {
        this.elementsById = new Map();
        this.listeners = new Map();
        this.body = new Element(this, 'body');
    }

    createElement(tagName) {
        return new Element(this, tagName);
    }

    getElementById(id) {
        return this.elementsById.get(id) || null;
    }

    querySelectorAll(selector) {
        const descendantMatch = selector.match(/^#([\w-]+)\s+(.+)$/);
        if (descendantMatch) {
            const ancestor = this.getElementById(descendantMatch[1]);
            return ancestor ? ancestor.querySelectorAll(descendantMatch[2]) : [];
        }
        return this.body.querySelectorAll(selector);
    }

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }

    addEventListener(type, listener) {
        const listeners = this.listeners.get(type) || [];
        listeners.push(listener);
        this.listeners.set(type, listeners);
    }

    dispatch(type, event = {}) {
        const delivered = {
            preventDefault() {},
            stopPropagation() {},
            ...event,
        };
        (this.listeners.get(type) || []).forEach(listener => listener(delivered));
    }
}

function createRuntime(fetchImpl, confirmImpl = () => true) {
    const document = new DocumentMock();
    const add = (id, classNames = []) => {
        const element = document.createElement('div');
        element.id = id;
        element.classList.add(...classNames);
        document.body.appendChild(element);
        return element;
    };
    const elements = {
        browseBtn: add('browse-btn'),
        currentDir: add('current-dir'),
        statusBar: add('status-bar', ['hidden']),
        statusText: add('status-text'),
        progressBar: add('progress-bar'),
        exactList: add('exact-list'),
        similarList: add('similar-list'),
        similarAutoDedupBtn: add('similar-auto-dedup-btn'),
        lightbox: add('lightbox', ['hidden']),
        lightboxViewport: add('lightbox-viewport'),
        lightboxImg: add('lightbox-img'),
        lightboxInfo: add('lightbox-info'),
        lightboxName: add('lightbox-name'),
        lightboxCapturedAt: add('lightbox-captured-at'),
        lightboxSize: add('lightbox-size'),
        scrollContainer: add('scroll-container'),
        autoDedupBtn: add('auto-dedup-btn'),
        toastContainer: add('toast-container'),
        toastMessage: add('toast-msg'),
        toastUndo: add('toast-undo-btn'),
    };
    const close = document.createElement('button');
    close.classList.add('lightbox-close');
    elements.lightbox.appendChild(close);
    elements.lightbox.appendChild(elements.lightboxViewport);
    elements.lightboxViewport.appendChild(elements.lightboxImg);
    elements.lightbox.appendChild(elements.lightboxInfo);
    elements.lightboxInfo.appendChild(elements.lightboxName);
    elements.lightboxInfo.appendChild(elements.lightboxCapturedAt);
    elements.lightboxInfo.appendChild(elements.lightboxSize);
    ['exact', 'similar'].forEach(tabName => {
        const tab = document.createElement('button');
        tab.classList.add('tab-btn');
        tab.dataset.tab = tabName;
        document.body.appendChild(tab);
        const content = document.createElement('div');
        content.id = `tab-${tabName}`;
        content.classList.add('tab-content');
        document.body.appendChild(content);
    });
    document.getElementById('tab-exact').appendChild(elements.exactList);
    document.getElementById('tab-similar').appendChild(elements.similarList);

    const scheduledDelays = [];
    const window = {
        addEventListener() {},
        confirm: confirmImpl,
    };
    const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'script.js'), 'utf8');
    const context = vm.createContext({
        Array,
        JSON,
        Set,
        console,
        document,
        encodeURIComponent,
        fetch: fetchImpl,
        globalThis: {},
        setTimeout: (_, delay) => {
            scheduledDelays.push(delay);
            return { mocked: true };
        },
        clearTimeout() {},
        window,
    });
    vm.runInContext(`${source}
globalThis.__frontendTest = {
    commitPendingDeletion,
    renderList,
    showLightbox,
    setZoom,
    undoPendingDeletion,
    getLightboxState: () => ({ isZoomed, panX: lightboxPanX, panY: lightboxPanY }),
    getPendingDeletion: () => pendingDeletion,
    setPendingDeletion: value => { pendingDeletion = value; },
    setExactData: value => { exactData = value; },
    setSimilarData: value => { similarData = value; },
    snapshot: () => JSON.parse(JSON.stringify({ exactData, similarData })),
};`, context, { filename: 'script.js' });
    return { api: context.globalThis.__frontendTest, document, elements, scheduledDelays };
}

function preparePendingExactDeletion(runtime, paths) {
    runtime.api.setExactData([['keep.jpg', ...paths]]);
    runtime.api.renderList([['keep.jpg', ...paths]], runtime.elements.exactList, 'exact');
    const row = runtime.elements.exactList.children[0];
    row.style.display = 'none';
    runtime.api.setPendingDeletion({
        type: 'single',
        tabName: 'exact',
        rows: [row],
        paths,
        timerId: null,
        committing: false,
    });
    return row;
}

test('a rejected delete request restores the pending group', async () => {
    const runtime = createRuntime(async () => {
        throw new Error('offline');
    });
    const row = preparePendingExactDeletion(runtime, ['delete.jpg']);

    await runtime.api.commitPendingDeletion();

    assert.deepEqual(runtime.api.snapshot().exactData, [['keep.jpg', 'delete.jpg']]);
    assert.equal(row.style.display, 'flex');
    assert.equal(runtime.api.getPendingDeletion(), null);
});

test('a fully failed delete response keeps every photo visible', async () => {
    const runtime = createRuntime(async () => ({
        ok: true,
        json: async () => ({ deleted: [], errors: ['delete.jpg'] }),
    }));
    const row = preparePendingExactDeletion(runtime, ['delete.jpg']);

    await runtime.api.commitPendingDeletion();

    assert.deepEqual(runtime.api.snapshot().exactData, [['keep.jpg', 'delete.jpg']]);
    assert.equal(row.style.display, 'flex');
    assert.equal(runtime.api.getPendingDeletion(), null);
});

test('a partial delete response removes only files confirmed by the server', async () => {
    const runtime = createRuntime(async () => ({
        ok: true,
        json: async () => ({ deleted: ['deleted.jpg'], errors: ['failed.jpg'] }),
    }));
    preparePendingExactDeletion(runtime, ['deleted.jpg', 'failed.jpg']);

    await runtime.api.commitPendingDeletion();

    assert.deepEqual(runtime.api.snapshot().exactData, [['keep.jpg', 'failed.jpg']]);
    assert.equal(runtime.elements.exactList.querySelectorAll('.image-item').length, 2);
    assert.equal(runtime.api.getPendingDeletion(), null);
});

test('partial deletion preserves the user-selected surviving photo', async () => {
    const runtime = createRuntime(async () => ({
        ok: true,
        json: async () => ({ deleted: ['a.jpg'], errors: ['b.jpg'] }),
    }));
    runtime.api.setExactData([['a.jpg', 'b.jpg', 'c.jpg']]);
    runtime.api.renderList([['a.jpg', 'b.jpg', 'c.jpg']], runtime.elements.exactList, 'exact');
    const row = runtime.elements.exactList.children[0];
    const items = row.querySelectorAll('.image-item');
    items[0].dispatch('click');
    items[2].dispatch('click');
    row.style.display = 'none';
    runtime.api.setPendingDeletion({
        type: 'single',
        tabName: 'exact',
        rows: [row],
        paths: ['a.jpg', 'b.jpg'],
        timerId: null,
        committing: false,
    });

    await runtime.api.commitPendingDeletion();

    assert.deepEqual(runtime.api.snapshot().exactData, [['b.jpg', 'c.jpg']]);
    assert.deepEqual(
        runtime.elements.exactList.querySelectorAll('.image-item')
            .map(item => item.classList.contains('selected')),
        [false, true]
    );
});

test('auto dedup does not hide a group with no deletable duplicate', () => {
    const runtime = createRuntime(async () => ({ ok: true, json: async () => ({}) }));
    runtime.api.setExactData([['only.jpg']]);
    runtime.api.renderList([['only.jpg']], runtime.elements.exactList, 'exact');
    const row = runtime.elements.exactList.children[0];

    runtime.elements.autoDedupBtn.dispatch('click');

    assert.notEqual(row.style.display, 'none');
    assert.equal(runtime.api.getPendingDeletion(), null);
});

test('similar bulk deletion asks for confirmation and leaves every photo visible when cancelled', () => {
    const confirmations = [];
    const runtime = createRuntime(
        async () => ({ ok: true, json: async () => ({}) }),
        message => {
            confirmations.push(message);
            return false;
        }
    );
    runtime.api.setSimilarData([['keep.jpg', 'discard.jpg']]);
    runtime.api.renderList([['keep.jpg', 'discard.jpg']], runtime.elements.similarList, 'similar');
    const row = runtime.elements.similarList.children[0];

    runtime.elements.similarAutoDedupBtn.dispatch('click');

    assert.equal(confirmations.length, 1);
    assert.match(confirmations[0], /reviewed all photos/);
    assert.notEqual(row.style.display, 'none');
    assert.equal(runtime.api.getPendingDeletion(), null);
});

test('confirmed similar bulk deletion stages only unchecked photos with a three-second undo window', () => {
    const runtime = createRuntime(async () => ({ ok: true, json: async () => ({}) }));
    runtime.api.setSimilarData([
        ['keep-one.jpg', 'discard-one.jpg'],
        ['keep-two.jpg', 'keep-three.jpg'],
    ]);
    runtime.api.renderList(runtime.api.snapshot().similarData, runtime.elements.similarList, 'similar');
    const [firstRow, secondRow] = runtime.elements.similarList.children;
    secondRow.querySelectorAll('.image-item')[1].dispatch('click');

    runtime.elements.similarAutoDedupBtn.dispatch('click');

    const deletion = runtime.api.getPendingDeletion();
    assert.equal(deletion.tabName, 'similar');
    assert.deepEqual([...deletion.paths], ['discard-one.jpg']);
    assert.equal(firstRow.style.display, 'none');
    assert.notEqual(secondRow.style.display, 'none');
    assert.equal(runtime.scheduledDelays.includes(3000), true);

    runtime.api.undoPendingDeletion();
    assert.equal(runtime.api.getPendingDeletion(), null);
    assert.equal(firstRow.style.display, 'flex');
});

test('confirmed similar bulk deletion includes rows already in a similar undo window', () => {
    const runtime = createRuntime(async () => ({ ok: true, json: async () => ({}) }));
    runtime.api.setSimilarData([
        ['keep-one.jpg', 'discard-one.jpg'],
        ['keep-two.jpg', 'discard-two.jpg'],
    ]);
    runtime.api.renderList(runtime.api.snapshot().similarData, runtime.elements.similarList, 'similar');
    const [firstRow, secondRow] = runtime.elements.similarList.children;
    firstRow.style.display = 'none';
    runtime.api.setPendingDeletion({
        type: 'single',
        tabName: 'similar',
        rows: [firstRow],
        paths: ['discard-one.jpg'],
        timerId: { mocked: true },
        committing: false,
    });

    runtime.elements.similarAutoDedupBtn.dispatch('click');

    const deletion = runtime.api.getPendingDeletion();
    assert.equal(deletion.tabName, 'similar');
    assert.deepEqual([...deletion.paths].sort(), ['discard-one.jpg', 'discard-two.jpg']);
    assert.equal(firstRow.style.display, 'none');
    assert.equal(secondRow.style.display, 'none');
});

test('cancelling similar bulk confirmation preserves an existing undo window', () => {
    const runtime = createRuntime(
        async () => ({ ok: true, json: async () => ({}) }),
        () => false
    );
    runtime.api.setSimilarData([['keep.jpg', 'discard.jpg']]);
    runtime.api.renderList(runtime.api.snapshot().similarData, runtime.elements.similarList, 'similar');
    const row = runtime.elements.similarList.children[0];
    row.style.display = 'none';
    const existingDeletion = {
        type: 'single',
        tabName: 'similar',
        rows: [row],
        paths: ['discard.jpg'],
        timerId: { mocked: true },
        committing: false,
    };
    runtime.api.setPendingDeletion(existingDeletion);

    runtime.elements.similarAutoDedupBtn.dispatch('click');

    assert.equal(runtime.api.getPendingDeletion(), existingDeletion);
    assert.equal(row.style.display, 'none');
});

test('confirmed similar bulk deletion commits only unchecked photos', async () => {
    let request;
    const runtime = createRuntime(async (_, options) => {
        request = options;
        return { ok: true, json: async () => ({ deleted: ['discard.jpg'] }) };
    });
    runtime.api.setSimilarData([
        ['keep.jpg', 'discard.jpg'],
        ['remain-one.jpg', 'remain-two.jpg'],
    ]);
    runtime.api.renderList(runtime.api.snapshot().similarData, runtime.elements.similarList, 'similar');
    runtime.elements.similarList.children[1].querySelectorAll('.image-item')[1].dispatch('click');

    runtime.elements.similarAutoDedupBtn.dispatch('click');
    await runtime.api.commitPendingDeletion();

    assert.deepEqual(JSON.parse(request.body).files, ['discard.jpg']);
    assert.deepEqual(runtime.api.snapshot().similarData, [['remain-one.jpg', 'remain-two.jpg']]);
});

test('successful similar bulk deletion removes confirmed paths from both cached result tabs', async () => {
    const runtime = createRuntime(async () => ({
        ok: true,
        json: async () => ({ deleted: ['discard.jpg'] }),
    }));
    runtime.api.setExactData([['exact-keep.jpg', 'discard.jpg']]);
    runtime.api.setSimilarData([['similar-keep.jpg', 'discard.jpg']]);
    runtime.api.renderList(runtime.api.snapshot().exactData, runtime.elements.exactList, 'exact');
    runtime.api.renderList(runtime.api.snapshot().similarData, runtime.elements.similarList, 'similar');

    runtime.elements.similarAutoDedupBtn.dispatch('click');
    await runtime.api.commitPendingDeletion();

    assert.deepEqual(runtime.api.snapshot().exactData, []);
    assert.deepEqual(runtime.api.snapshot().similarData, []);
    assert.equal(runtime.elements.exactList.children.length, 0);
    assert.equal(runtime.elements.similarList.children.length, 0);
});

test('failed paths remain in both cached tabs after a partially successful similar bulk deletion', async () => {
    const runtime = createRuntime(async () => ({
        ok: true,
        json: async () => ({ deleted: ['deleted.jpg'] }),
    }));
    runtime.api.setExactData([['exact-keep.jpg', 'deleted.jpg', 'failed.jpg']]);
    runtime.api.setSimilarData([['similar-keep.jpg', 'deleted.jpg', 'failed.jpg']]);
    runtime.api.renderList(runtime.api.snapshot().exactData, runtime.elements.exactList, 'exact');
    runtime.api.renderList(runtime.api.snapshot().similarData, runtime.elements.similarList, 'similar');

    runtime.elements.similarAutoDedupBtn.dispatch('click');
    await runtime.api.commitPendingDeletion();

    assert.deepEqual(runtime.api.snapshot().exactData, [['exact-keep.jpg', 'failed.jpg']]);
    assert.deepEqual(runtime.api.snapshot().similarData, [['similar-keep.jpg', 'failed.jpg']]);
});

test('double-clicking an image opens its original-size preview', () => {
    const runtime = createRuntime(async () => ({ ok: true, json: async () => ({}) }));
    runtime.api.setExactData([['photo one.jpg']]);
    runtime.api.renderList([['photo one.jpg']], runtime.elements.exactList, 'exact');

    runtime.elements.exactList.querySelector('.image-item').dispatch('dblclick');

    assert.equal(runtime.elements.lightbox.classList.contains('hidden'), false);
    assert.equal(runtime.elements.lightboxImg.src, '/api/image?path=photo%20one.jpg');
});

test('the preview zooms and pans only while the left mouse button is held', () => {
    const runtime = createRuntime(async () => ({ ok: true, json: async () => ({}) }));
    runtime.elements.lightboxViewport._rect = {
        top: 0, left: 0, bottom: 600, right: 1000, width: 1000, height: 600,
    };
    runtime.elements.lightboxImg.clientWidth = 800;
    runtime.elements.lightboxImg.clientHeight = 500;
    runtime.api.showLightbox('wide-photo.jpg');

    runtime.elements.lightboxViewport.dispatch('pointerdown', {
        button: 0, pointerId: 1, clientX: 500, clientY: 300,
    });
    runtime.elements.lightboxViewport.dispatch('pointermove', {
        pointerId: 1, clientX: 650, clientY: 200,
    });
    const zoomedState = runtime.api.getLightboxState();
    assert.equal(zoomedState.isZoomed, true);
    assert.equal(zoomedState.panX, 150);
    assert.equal(zoomedState.panY, -100);
    assert.equal(
        runtime.elements.lightboxImg.style.transform,
        'translate(150px, -100px) scale(2)'
    );

    runtime.elements.lightboxViewport.dispatch('pointerup', { pointerId: 1 });
    const restoredState = runtime.api.getLightboxState();
    assert.equal(restoredState.isZoomed, false);
    assert.equal(restoredState.panX, 0);
    assert.equal(restoredState.panY, 0);
    assert.equal(runtime.elements.lightboxImg.style.transform, '');
});

test('overlapping mouse and Space holds keep zoom active until both inputs release', () => {
    const runtime = createRuntime(async () => ({ ok: true, json: async () => ({}) }));
    runtime.elements.lightboxViewport._rect = {
        top: 0, left: 0, bottom: 600, right: 1000, width: 1000, height: 600,
    };
    runtime.elements.lightboxImg.clientWidth = 800;
    runtime.elements.lightboxImg.clientHeight = 500;
    runtime.api.showLightbox('wide-photo.jpg');

    runtime.elements.lightboxViewport.dispatch('pointerdown', {
        button: 0, pointerId: 1, clientX: 500, clientY: 300,
    });
    runtime.elements.lightboxViewport.dispatch('pointermove', {
        pointerId: 1, clientX: 650, clientY: 200,
    });
    runtime.document.dispatch('keydown', { key: ' ', repeat: false });
    runtime.elements.lightboxViewport.dispatch('pointerup', { pointerId: 1 });

    assert.equal(runtime.api.getLightboxState().isZoomed, true);
    assert.equal(runtime.api.getLightboxState().panX, 0);
    assert.equal(runtime.api.getLightboxState().panY, 0);

    runtime.document.dispatch('keyup', { key: ' ' });
    assert.equal(runtime.api.getLightboxState().isZoomed, false);

    runtime.document.dispatch('keydown', { key: ' ', repeat: false });
    runtime.elements.lightboxViewport.dispatch('pointerdown', {
        button: 0, pointerId: 2, clientX: 500, clientY: 300,
    });
    runtime.document.dispatch('keyup', { key: ' ' });

    assert.equal(runtime.api.getLightboxState().isZoomed, true);
    runtime.elements.lightboxViewport.dispatch('pointercancel', { pointerId: 2 });
    assert.equal(runtime.api.getLightboxState().isZoomed, false);
    assert.equal(runtime.api.getLightboxState().panX, 0);
    assert.equal(runtime.api.getLightboxState().panY, 0);
});

test('a non-left pointer button does not activate preview zoom', () => {
    const runtime = createRuntime(async () => ({ ok: true, json: async () => ({}) }));
    runtime.api.showLightbox('photo.jpg');

    runtime.elements.lightboxViewport.dispatch('pointerdown', {
        button: 2, pointerId: 1, clientX: 50, clientY: 50,
    });

    assert.equal(runtime.api.getLightboxState().isZoomed, false);
});

test('the lightbox shows the returned file metadata in its information panel', async () => {
    const runtime = createRuntime(async () => ({
        ok: true,
        json: async () => ({
            name: 'holiday photo.jpg',
            captured_at: '2024-05-06 07:08:09',
            size_bytes: 1536,
        }),
    }));

    runtime.api.showLightbox('C:\\photos\\holiday photo.jpg');
    await new Promise(resolve => setImmediate(resolve));

    assert.equal(runtime.elements.lightboxName.textContent, 'holiday photo.jpg');
    assert.equal(runtime.elements.lightboxCapturedAt.textContent, '2024-05-06 07:08:09');
    assert.equal(runtime.elements.lightboxSize.textContent, '1.50 KB');
});

test('lightbox navigation does not reload metadata when it reaches either end of a photo row', async () => {
    const requests = [];
    const runtime = createRuntime(async url => {
        requests.push(url);
        const photoName = url.includes('first.jpg') ? 'first.jpg' : 'last.jpg';
        return {
            ok: true,
            json: async () => ({ name: photoName, captured_at: null, size_bytes: 1024 }),
        };
    });
    runtime.api.setExactData([['first.jpg', 'last.jpg']]);
    runtime.api.renderList(runtime.api.snapshot().exactData, runtime.elements.exactList, 'exact');
    const items = runtime.elements.exactList.querySelectorAll('.image-item');

    items[0].dispatch('dblclick');
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 1);
    assert.equal(runtime.elements.lightboxName.textContent, 'first.jpg');

    runtime.document.dispatch('keydown', { key: 'ArrowLeft' });
    assert.equal(requests.length, 1);
    assert.equal(runtime.elements.lightboxName.textContent, 'first.jpg');

    runtime.document.dispatch('keydown', { key: 'ArrowRight' });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(requests.length, 2);
    assert.equal(runtime.elements.lightboxName.textContent, 'last.jpg');

    runtime.document.dispatch('keydown', { key: 'ArrowRight' });
    assert.equal(requests.length, 2);
    assert.equal(runtime.elements.lightboxName.textContent, 'last.jpg');
});

test('a delayed metadata response cannot overwrite the currently previewed photo', async () => {
    let resolveFirstResponse;
    let requestCount = 0;
    const runtime = createRuntime(() => {
        requestCount++;
        if (requestCount === 1) {
            return new Promise(resolve => {
                resolveFirstResponse = resolve;
            });
        }
        return Promise.resolve({
            ok: true,
            json: async () => ({ name: 'new.jpg', captured_at: null, size_bytes: 2048 }),
        });
    });

    runtime.api.showLightbox('old.jpg');
    runtime.api.showLightbox('new.jpg');
    await new Promise(resolve => setImmediate(resolve));
    resolveFirstResponse({
        ok: true,
        json: async () => ({ name: 'old.jpg', captured_at: null, size_bytes: 1024 }),
    });
    await new Promise(resolve => setImmediate(resolve));

    assert.equal(runtime.elements.lightboxName.textContent, 'new.jpg');
    assert.equal(runtime.elements.lightboxSize.textContent, '2.00 KB');
});
