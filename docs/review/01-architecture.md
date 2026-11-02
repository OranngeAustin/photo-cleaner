# 01 · 架构摸底

审查基准：`main` @ `c8a8e5c`。全仓库源码约 3.2k 行（不含文档）：

| 文件 | 行数 | 职责 |
|---|---|---|
| `main.py` | 299 | FastAPI 应用、全局扫描状态、路径授权（安全边界）、删除、pywebview 启动 |
| `backend/scanner.py` | 514 | 文件枚举、精确去重漏斗、pHash 相似聚类、缩略图缓存 |
| `web/script.js` | 814 | 无框架前端状态机：扫描轮询、渲染、键盘/鼠标、乐观删除 + 撤销、Lightbox |
| `web/index.html` / `web/style.css` | 72 / 373 | 静态页面与样式 |
| `tests/test_main.py` / `test_scanner.py` / `test_frontend.js` | 165 / 270 / 739 | 后端、扫描器、前端（vm + 手写假 DOM）测试 |

CLAUDE.md 没有列出需要忽略的目录；`.claude/agents/`、`docs/` 只含说明文档，不参与运行。

## 1. 模块划分

```
┌───────────── pywebview 原生窗口（Windows）──────────────┐
│  web/index.html + style.css + script.js（浏览器上下文）    │
│     │ fetch /api/*            │ window.pywebview.api       │
└─────┼─────────────────────────┼───────────────────────────┘
      ▼                         ▼
 main.py（FastAPI，127.0.0.1:随机端口，uvicorn 守护线程）
   ├─ Api.choose_directory      ← 原生文件夹对话框（js_api 桥）
   ├─ 全局状态：scan_state / active_scanner / allowed_scan_root /
   │           allowed_result_paths_by_mode，统一由 scan_lock 保护
   ├─ is_path_allowed / is_result_path_allowed（安全边界）
   ├─ /api/scan, /api/scan_status, /api/cancel_scan
   ├─ /api/thumbnail, /api/image, /api/photo_info（只读，受授权）
   ├─ /api/delete → send2trash（回收站）
   └─ StaticFiles("/") ← _resource_dir()/web（兼容 PyInstaller _MEIPASS）
      │
      ▼
 backend/scanner.py
   ├─ Scanner（每次扫描新建，一个守护线程跑 scan_directory）
   │    ├─ _enumerate_image_files：显式栈 + os.scandir，不跟随符号链接目录，
   │    │   realpath 去重，>259 字符路径跳过，exact 模式顺带收集 DirEntry.stat 大小
   │    ├─ _scan_exact：大小分组 → 64 KiB 前缀 SHA-256 → 大文件全量 SHA-256
   │    ├─ _scan_similar：并行 pHash → cluster_similar_hashes（六段索引 + 精确 Hamming，锚点语义）
   │    └─ _iter_parallel_results：ThreadPoolExecutor，在途任务 ≤ 2×worker，可快速取消
   └─ 缩略图：lru_cache(512) 以 (realpath, w, h, mtime_ns, size) 为键；透明图合成白底后编码 JPEG
```

## 2. 入口

| 入口 | 说明 |
|---|---|
| `python main.py` | 启动 uvicorn（`port=0`，仅回环地址）→ 等待就绪 ≤ 8 s → `webview.create_window(..., js_api=api)` |
| `pyinstaller -F -w --add-data "web;web" main.py` | 单文件 EXE；静态资源从 `sys._MEIPASS/web` 读取 |
| `Start_PhotoCleaner.bat` | 作者本机启动脚本（硬编码 conda Python 路径） |
| 测试 | `python -m pytest -q`；`node --test tests/test_frontend.js` |

## 3. 核心数据流

1. **选择目录**：`browse-btn` → `window.pywebview.api.choose_directory()` → 返回绝对路径（不经过 HTTP）。
2. **启动扫描**：`POST /api/scan {directory, mode}` → 校验是目录 → `realpath` 作为扫描根；若根变化则清空两种模式的结果白名单；
   `active_scanner` 非空时返回 409 → 新建 `Scanner`，守护线程执行 `scan_directory(root, mode, callback)`。
3. **进度**：扫描线程回调 `status/progress/done` → 在 `scan_lock` 内写 `scan_state`；只接受当前 `active_scanner` 的事件。
   前端每 500 ms 轮询 `GET /api/scan_status`，直到 `done=true`。
4. **结果授权**：`done` 时把该模式所有结果路径（`normcase(realpath)`）写入 `allowed_result_paths_by_mode[mode]`。
   之后 `/api/thumbnail`、`/api/image`、`/api/photo_info`、`/api/delete` 都必须通过 `is_result_path_allowed`：
   路径在扫描根内 **且** 在任一模式的结果集中。
5. **渲染**：`renderList` 为每组建 DOM 行，`<img loading=lazy src=/api/thumbnail?path=…>`；默认选中每组第 1 张。
6. **删除**：单行 `Delete`/「Clean Unselected」或「全部去重」/「删除未勾选」→ 先隐藏行、3 秒 Toast 可 `Ctrl+Z` 撤销 →
   `commitPendingDeletion` 发 `POST /api/delete {files}` → 后端逐个授权校验、`send2trash`、从两个白名单移除、清缩略图缓存 →
   前端只把服务器确认的 `deleted` 从两个标签的缓存中移除，其余恢复（按路径恢复选择）。
7. **预览**：Lightbox 加载 `/api/image`（`FileResponse` 原图）与 `/api/photo_info`（EXIF 拍摄时间、大小）；请求序号防竞态。

## 4. 外部依赖

| 依赖 | 用途 | 备注 |
|---|---|---|
| fastapi / starlette / pydantic | HTTP API、请求校验、静态文件 | `requirements.txt` **未锁版本** |
| uvicorn | ASGI 服务器（回环地址、随机端口） | 未锁版本 |
| pywebview | 原生窗口 + `js_api` 桥 | 测试也需要（`main` 顶层 import） |
| Pillow / pillow-heif | 解码、EXIF、缩略图、HEIC | 解码不可信图片文件 → 解码器漏洞面 |
| ImageHash（→ numpy、scipy、PyWavelets） | pHash | |
| Send2Trash | 移入回收站 | 删除的唯一通道 |
| Node 内置 `node:test` / `vm` | 前端测试 | 无 npm 依赖 |

本地运行环境实测版本：fastapi 0.162.0、starlette 1.7.0、uvicorn 0.54.0、Pillow 12.3.0、pillow-heif 1.8.1、
ImageHash 4.3.2、Send2Trash 2.1.0、pywebview 6.2.1。

## 5. 高风险区域

| 风险 | 位置 | 为什么高 |
|---|---|---|
| **数据丢失** | `main.py::delete_files`、`web/script.js` 删除状态机（`triggerClean`、`stageBulkDeletion`、`commitPendingDeletion`、`removeDeletedPaths`） | 发给后端的路径集合错了就会删错文件；虽进回收站，但用户难以察觉 |
| **精确去重的正确性** | `backend/scanner.py::_scan_exact` | 「全部去重」会无条件删除每个精确组除第 1 张外的所有文件；组里混入非重复文件即误删 |
| **路径授权（越权读/删）** | `main.py::is_path_allowed`、`is_result_path_allowed`、各文件端点 | 本地 HTTP 服务无鉴权，授权仅依赖扫描根 + 结果白名单；还需考虑 Host 头/DNS 重绑定 |
| **并发与生命周期** | `main.py` 全局状态 + 扫描线程回调；`Scanner` 取消；前端扫描轮询 | 竞态可能造成状态错乱或白名单与界面不一致 |
| **前端索引与 DOM 一致性** | `web/script.js` 键盘导航、焦点、行 id | 隐藏行/重渲染后索引错位可能把操作作用到错误的组 |
| **不可信文件解码** | `scanner.py` 中 `Image.open`、`imagehash.phash`、缩略图；`main.py::_read_capture_time` | 超大/畸形图片可能导致内存/CPU 消耗或解码异常 |
| **性能热点** | 文件枚举、哈希漏斗、pHash（CPU 密集）、聚类、缩略图 | 万级照片库的扫描时长；见阶段 5 |

## 6. 审查顺序（按风险从高到低，精确到目录/文件）

1. **根目录 `main.py`**：删除端点、路径授权、全局状态与扫描回调、静态资源挂载、启动流程。
2. **`web/`**：`script.js` 的删除状态机 → 扫描轮询 → 键盘/焦点/索引 → Lightbox；随后 `index.html`、`style.css`。
3. **`backend/`**：`scanner.py` 精确去重漏斗 → 文件枚举 → 并行执行与取消 → 相似聚类 → 缩略图缓存。
4. **`tests/`**：测试是否真正覆盖上述高风险路径、是否有平台相关或脆弱的测试。
5. **根目录配置与打包**：`requirements.txt`（版本锁定）、`Start_PhotoCleaner.bat`、`.gitignore`。
6. **`docs/`、`.claude/`**：只读文档，仅检查是否与代码不一致。

## 第二轮（M1–M11 修复后）新增的防护

| 位置 | 机制 | 对应发现 |
|---|---|---|
| `main.py` `LocalRequestGuard` | 中间件栈的最外层：`Host` 必须是 `127.0.0.1` 或 `localhost`；如果带 `Origin`，必须等于 `http://<Host>`；否则返回 403。作用于所有 HTTP 请求，包括静态文件 | M11、L14 |
| `main.py` `result_fingerprints_by_mode` | 扫描结束时记录每个结果的 `(size, mtime_ns)`，`/api/delete` 删除前比对，不一致就拒绝；换根目录时清空，删除成功后移除 | M8 |
| `backend/scanner.py` `_decode_budget` | 所有线程同时解码的像素总量上限（pHash、非 JPEG 缩略图、按 draft 缩小后的 JPEG）；超大图独占预算；扫描任务在等待中会响应取消 | M7 |
| `backend/scanner.py` `get_file_prefix_hash_and_length` | 读前缀时多读 1 个字节，返回实际读到的长度；长度与枚举时的大小不一致的组，不能只凭前缀判定（最初用 `fstat`，因为造成 +6.5% 的回归，改成了现在的做法） | M1 |
| `web/script.js` `commitPendingDeletion` | 返回进行中的请求；切标签自动扫描和换目录之前都会等它完成 | M6 |
| `web/script.js` `moveFocusOffHiddenRows` / `restoreFocusAfterUndo` / `focusFirstVisibleRow` | 键盘焦点在暂存、撤销、失败、切换标签之后始终有效 | M4、M5 |

## 第三轮（L1–L13 修复后）的变化

| 位置 | 机制 | 对应发现 |
|---|---|---|
| `main.py` `start_scan` 中的 `run_scan` | 扫描线程入口用 `finally` 兜底：如果处理 `done` 失败、任务仍是 `active_scanner`，就释放它，并把状态设为带错误信息的 `done`，避免之后的扫描一律返回 409 | L3 |
| `main.py` `delete_files` | 删除后不再清空缩略图缓存；`_path_key` 在 `scan_lock` 之外计算 | L8、L1 |
| `backend/scanner.py` `_finish` | 回调异常只记录日志，`done` 只发一次 | L3 |
| `backend/scanner.py` `_iter_parallel_results` | 无论循环以哪种方式结束，都在 `finally` 中取消排队中的任务 | L4 |
| `backend/scanner.py` `generate_thumbnail` | 生成失败的异常不进入 `lru_cache`，由外层返回空结果 | L2 |
| `web/script.js` `retryOrAbandonScan` | 状态轮询按 0.5/1/2/4 秒退避重试；放弃时请求 `/api/cancel_scan` | L7 |
| `web/script.js` `stageDeletion` | 所有清理动作的唯一入口；撤销窗口内的新动作并入同一批 | L9、L11 |
| `web/script.js` `showToast({ undoable })` / `hideToastLater` | 提交中和结果提示不显示 Undo；结果提示 5 秒后自动隐藏，不会隐藏更新的提示 | L10 |
| `requirements.lock` | 可选的 constraints 文件，记录测试通过时的确切版本；`requirements.txt` 不变 | L13 |
