# 02 · 审查发现

审查基准：`main` @ `c8a8e5c`。按 [01-architecture.md](01-architecture.md) 的顺序审查：
`main.py` → `web/` → `backend/` → `tests/` → 根配置 → `docs/`、`.claude/`。

方法：用 `code-reviewer` 子代理按目录并行审查（main.py、web/、backend/+tests/ 各一个），
我再逐条核对代码，**高级别全部用脚本或测试复现过**。「把握」指对问题成立的把握，不是对触发概率的估计。

## 高

| 编号 | 位置 | 问题 | 原因 / 触发场景 | 修复建议 | 把握 |
|---|---|---|---|---|---|
| **H1** | `backend/scanner.py:389,403`；`main.py:211,215` | **删除一个指向照片的符号链接时，被送进回收站的是链接指向的原照片** | 枚举时 `entry.is_file()`、`entry.stat()` 默认跟随链接，目录做了 realpath 去重，文件却没有。于是 `b.jpg → a.jpg` 会和 `a.jpg` 被分进同一个精确组。用户保留 a、删除 b（「全部去重」默认就是这样）时，`delete_files` 会先做 `realpath(b) = a`，再 `send2trash(a)`，接口仍然返回 `deleted=[b]`。最后用户想保留的照片进了回收站，只剩一个悬空链接。**已用脚本复现**：`trashed == ['/tmp/…/a.jpg']` | 枚举时跳过 `entry.is_symlink()` 的文件，与「不跟随符号链接目录」保持一致；`delete_files` 再拒绝删除符号链接本身（纵深防御） | 高 |
| **H2** | `main.py:289` | **README 给出的发布方式（`pyinstaller -F -w`）打出的 EXE 启动即崩，且不显示任何提示** | windowed 模式下没有控制台，`sys.stdout` 和 `sys.stderr` 都是 `None`。`uvicorn.Config()` 在 `__init__` 里调用 `configure_logging()`，`ColourizedFormatter` 会执行 `sys.stdout.isatty()`。**已模拟复现**：`sys.stdout = sys.stderr = None` 时，`uvicorn.Config(...)` 抛出 `ValueError: Unable to configure formatter 'default'` | 创建 `Config` 之前，把为 `None` 的标准流重定向到 `os.devnull`。从源码运行时行为完全不变 | 高（Windows 真机 EXE 仍需人工验证） |
| **H3** | `web/script.js:547-551, 484` | **跨标签删除后，某组可能一张勾选都不剩，之后的清理会把这组全部删光，包括最后一份副本** | `removeDeletedPaths` 重新渲染时只恢复「仍然存在的已勾选路径」。触发：精确页某组 [P1, P2]，用户改为保留 P2 并删除 P1；相似页对应的组默认勾选的正好是 P1，P1 被删后，这组就没有任何勾选项。此时点「删除未勾选」或该组的 Clean，会把 P2 和组内其他照片全部移走。确认框只显示张数，用户很难察觉 | 如果某组原有的勾选项全部被删除，就默认勾选该组的第一张存活照片。用户自己取消全部勾选的组不受影响 | 高 |
| **H4** | `web/script.js:793-810` | **按 `Delete` 清理的不是焦点组，而是窗口坐标下第一个「可见」行，这一行可能被头部挡住、用户根本看不到** | README 写的是「`Delete`：一键清理当前组中未选中的照片」。实际代码用 `getBoundingClientRect()` 的窗口坐标判断，条件是 `top >= 0`，或 `bottom > 100`。但真正的滚动容器是 `main`，在约 146px 高的头部下方，所以已经滚到头部后面、被裁掉的行也会被选中。触发：用 `S` 把焦点移到屏幕中间的第 3 组，按 `Delete`，被清理的却是第 1 组（或者是看不见的上一组），删掉的是用户没有检查过的照片 | 焦点行存在且在滚动容器可视区内时，清理焦点行；否则退回到滚动容器内第一个可见行，用容器坐标判断，保留纯鼠标滚动时的原有行为 | 高（机制确定；意图依据 README 判断） |

## 中

| 编号 | 位置 | 问题 | 原因 / 触发场景 | 修复建议 | 把握 |
|---|---|---|---|---|---|
| M1 | `backend/scanner.py:449,459` | 「≤ 64 KiB 直接判定为重复」用的是**枚举时**记录的文件大小 | 文件在枚举后被写长到超过 64 KiB 时（比如正在复制或同步），前缀哈希只覆盖前 64 KiB。两个前缀相同、尾部不同的文件会被判成精确重复，「全部去重」就会误删 | 读前缀时对同一个句柄做 `fstat`，用实际大小判断；与枚举值不一致的文件改走全量哈希 | 机制高、概率低 |
| M2 | `main.py:110-115` | 照片信息里的「拍摄时间」读错了字段 | `getexif()` 只包含 IFD0，而 `DateTimeOriginal (36867)`、`DateTimeDigitized (36868)` 位于 Exif 子 IFD，所以总是退回到 `DateTime (306)`，也就是修改时间。**已复现**：子 IFD 中为 2024 年、IFD0 中为 2030 年时，显示的是 2030 年。现有测试把 36867 直接写进 IFD0，掩盖了这个问题 | 先读 `exif.get_ifd(ExifTags.IFD.Exif)`，再退回 IFD0；顺带捕获 `DecompressionBombError` | 高 |
| M3 | `backend/scanner.py:110-126` | 缩略图没有按 EXIF 方向旋转 | 不调用 `ImageOps.exif_transpose`，手机竖拍、靠 Orientation 标签记录方向的照片，缩略图是横的；Lightbox 由浏览器显示原图，方向是正的，两者不一致。**已复现**：400×200 且 Orientation=6 的图片，缩略图是 256×128 | 在 `thumbnail()` 之前做 `exif_transpose` | 高 |
| M4 | `web/script.js:37, 736` | 切换标签时沿用旧的 `rowIdx/imgIdx` | 精确页焦点在第 9 组，切到只有 3 组的相似页后按 `D`，`data[8].length` 抛出 TypeError，键盘操作失效 | 切换标签时重置焦点，或做边界检查 | 高 |
| M5 | `web/script.js:275-278, 671-674` | 暂存删除后焦点被置为 -1，撤销或删除失败后不恢复 | 这段时间 W/S/A/D/Space/Enter 全部无效，只能用鼠标点击恢复，而点击本身会切换勾选状态 | 暂存时把焦点移到下一个可见行，撤销或失败后恢复原焦点 | 高 |
| M6 | `web/script.js:41-47, 347-363` | 切标签自动扫描、选择新目录之前，都没有先结束 `pendingDeletion` | 在 3 秒撤销窗口内切到另一个标签，删除会在扫描中途提交。新结果里可能还有已删文件（缩略图 404），`main.py:176` 也会把它重新写进白名单。换目录时则会提示一个误导性的「无法删除」 | 扫描或换目录前先提交并等待完成，或者先撤销；`done` 时过滤掉已经删除的路径 | 中 |
| M7 | `backend/scanner.py:90, 118-123`；`_worker_count` | 超大图片的内存风险 | pHash 会对整张原图做 `convert('L')`，非 JPEG 缩略图会先生成全尺寸的 RGBA 图和白底。Pillow 在约 1.79 亿像素以下只告警，worker 数量最多 32 个，在途任务是它的 2 倍，处理全景图或大 TIFF 时可能 OOM | 设置更低的像素上限，或按像素量限制并发；先缩小再合成白底 | 中 |
| M8 | `main.py:209-215` | 删除前只核对路径，不核对文件是否还是扫描时的那一个 | 扫描之后，文件被同步软件或编辑器替换成了不同的内容，照样会被删 | `done` 时记录 `(size, mtime_ns)`，删除前比对 | 中（概率低） |
| M9 | `tests/test_scanner.py:251-270` | 符号链接环测试在非 Windows 系统上必然失败，而且断言太弱 | `cmd` 不存在时抛出的 `FileNotFoundError` 没有被捕获；测试只断言收到了 `done`，即使去掉 realpath 去重也照样通过 | 用 `skipif` 或 `os.symlink` 写一个跨平台版本，并断言每个文件只被枚举一次。（按 RUNBOOK 规定，已有的失败测试只记录、不修） | 高 |
| M10 | `tests/` | 高风险路径缺少测试 | 下面这些都没有测试：文件符号链接、65536/65537 字节边界、哈希中途取消、worker 抛异常、`done` 回调抛异常、「全部去重」的正向提交（只应提交 `items[1:]`）、3 秒计时到点后自动提交、提交进行中拦截新的清理动作、聚类结果与暴力锚点聚类的随机对照 | 优先补 H1–H4 的回归测试和聚类的特征测试（阶段 4、6 会补一部分） | 高 |

### 中风险修复状态（第二轮，分支 `claude/medium-fixes`）

| 编号 | 状态 | commit | 说明 |
|---|---|---|---|
| M1 | ✅ 已修复 | `e64cb8e` | 读前缀后在同一句柄上 `fstat`，大小与枚举时不一致的组改走全量哈希 |
| M2 | ✅ 已修复 | `62ad778` | 先读 Exif 子 IFD 的 36867/36868，再退回 IFD0；`DecompressionBombError` 返回「未记录」 |
| M3 | ✅ 已修复 | `2d65a24` | 按 Orientation 只旋转已经缩小的缩略图 |
| M4 | ✅ 已修复 | `6e32f29` | 切换标签时焦点移到新标签的第一个可见组，并加越界检查 |
| M5 | ✅ 已修复 | `acec284` | 暂存删除时焦点移到相邻组；撤销或删除失败后恢复 |
| M6 | ✅ 已修复 | `f54fadd` | 切标签自动扫描、换目录之前，先等暂存的删除提交完成 |
| M7 | ✅ 已修复 | `aa46c62` | 解码像素预算 `DECODE_PIXEL_BUDGET`（1.92 亿像素）；缩略图先缩小再合成白底；`MAX_IMAGE_PIXELS` 未改 |
| M8 | ✅ 已修复 | `7473547` | 扫描结束时记录 `(size, mtime_ns)`，删除前比对；指纹在获取锁之前算好（顺带缓解 L1） |
| M9 | ✅ 已修复 | `2125ded` | 平台检查补上 `OSError`，在非 Windows 上跳过；新增「每个文件只枚举一次」的断言，以及可移植的目录符号链接环测试 |
| M10 | ✅ 已补齐 | `2d48fea` | 64 KiB 边界、哈希中途取消、`done` 回调异常、全部去重正向提交、计时器自动提交、提交进行中拦截 |
| M11 | ✅ 已修复 | `97c7200` | `LocalRequestGuard` 校验 Host（127.0.0.1/localhost）和 Origin（必须与 Host 同源）；**L14 同时解决**。未采用会话令牌（见 PROGRESS R2-D6） |

## 低

| 编号 | 位置 | 问题 | 原因 / 触发场景 | 修复建议 | 把握 |
|---|---|---|---|---|---|
| L1 | `main.py:176` | 持有 `scan_lock` 时逐个调用 `realpath` | 结果很多或扫描网络盘时，`/api/scan_status` 和所有文件端点都会被阻塞 | 在锁外先算好集合，再在锁内赋值 | 高 |
| L2 | `backend/scanner.py:130-132` | 失败结果 `b""` 也会被 `lru_cache` 缓存 | 文件只是暂时被占用（或出现 MemoryError）时，之后会一直返回 500，直到下次扫描或删除 | 在缓存函数内抛出异常，由外层捕获 | 高 |
| L3 | `backend/scanner.py:298, 345-353`；`main.py:181` | `_finish` 放在 `try` 里面 | `done` 回调抛异常会被 `except` 捕获，再发一次带 error 的 `done`；如果第二次也抛异常，线程直接退出，`active_scanner` 永远不会复位，之后的扫描一律返回 409 | 在 `try` 外只发一次 `done`；main 的线程入口用 `finally` 兜底复位 | 中 |
| L4 | `backend/scanner.py:263-294` | 生成器因为取消以外的原因提前关闭时，排队中的任务不会被取消 | `with` 退出时调用 `shutdown(wait=True)`，要等最多 2×worker 个任务跑完。取消路径没有这个问题，因为 worker 会先检查 event | 在 `finally` 里对 `pending` 中的 future 调用 `cancel()` | 中 |
| L5 | `backend/scanner.py:386` | 会跟随 Windows 联接点（junction），与 CLAUDE.md 中「Symlinked directories are not followed」的描述不一致 | 这与 `os.walk(followlinks=False)` 的行为相同，realpath 去重也能防住环。但如果联接点指向扫描根之外，对应结果在界面上能看到，所有接口却都返回 403 | 在 CLAUDE.md 中写明，或用 `is_junction()` 跳过根外目标。见待人工确认 Q3 | 中 |
| L6 | `web/script.js:445` | 扫描结束提示的 5 秒隐藏计时器不检查 `scanInProgress` | 5 秒内开始的新扫描（例如切换标签触发的自动扫描），进度栏会被藏起来 | 与 `showScanError` 一样，先检查 `scanInProgress` | 高 |
| L7 | `web/script.js:450-453` | 轮询失败一次就解锁界面 | 后端扫描仍在运行，结果被丢弃；再次扫描返回 409；前端没有调用 `/api/cancel_scan` 的入口 | 有限次重试并退避；提供取消按钮 | 高 |
| L8 | `web/script.js:563-568`；`main.py:225-226` | 每次提交删除后，焦点都重置到第 0 组并 `scrollIntoView`，列表跳回顶部；整表重新渲染，后端又清空了缩略图缓存，所有可见缩略图都要重新生成 | 体验和性能问题（见阶段 5） | 焦点保持在原位置附近；删除后不必清空缩略图缓存，因为缓存键已经包含 mtime 和 size | 高 |
| L9 | `web/script.js:260, 657` | 新的清理动作会静默撤销上一个待删除项（精确页不会合并） | 连续按 `Delete` 时，前一行会重新出现。偏保守，不会造成误删，但容易让人困惑 | 在提示中说明，或像相似页那样合并 | 中 |
| L10 | `web/script.js:585, 625, 633` | Toast 状态不对 | 提交进行中，Undo 按钮还在，但点击无效；失败提示永远不会自动消失，上面的 Undo 按钮也一直无效 | 提交时修改提示文案、禁用按钮；失败提示定时隐藏 | 高 |
| L11 | `web/script.js:4-5, 28, 266/663`；`web/style.css:156-159, 323-326` | 可维护性 | 有未使用的变量：`activeCountdownId`、`countdownInterval`、`scrollContainer`；`pendingDeletion.type` 从不读取；`triggerClean` 与 `stageBulkDeletion` 重复构造 `pendingDeletion`；`.group-row.focused` 和 `.lightbox img.zoomed` 是无效规则（元素上不会出现这两个 class 组合） | 清理并抽出公共函数 | 高 |
| L12 | `main.py:96-103, 211-215` | 授权与删除之间存在 TOCTOU | 检查和使用分两次进行，删除时用的是路径字符串。如果其间父目录被换成联接点，删除就可能越出扫描根。前提是攻击者对扫描目录有写权限，属于理论风险 | 删除前用 `lstat` 复核 | 中 |
| L13 | `requirements.txt` | 依赖没有锁定版本 | 无法复现构建；测试依赖合成图的 pHash 数值，ImageHash 和 scipy 升级后可能出现差异 | 提供 `requirements.lock`，或至少锁定主版本 | 高 |

## 待人工确认

| 编号 | 位置 | 问题 | 为什么不确定 | 建议 |
|---|---|---|---|---|
| Q1 | `main.py:215` + `requirements.txt` | **在没有回收站的盘上（U 盘 / SD 卡 / 网络共享）删除，可能被静默永久删除**（建议定级：高） | requirements 里没有 pywin32，send2trash 2.1.0 在 Windows 上会退回 `win/legacy.py:174`，标志是 `FOF_ALLOWUNDO\|FOF_NOCONFIRMATION\|FOF_NOERRORUI\|FOF_SILENT`，没有 `FOF_WANTNUKEWARNING`。按 Win32 文档，卷不支持回收站时会直接永久删除，也不会弹窗。安装 pywin32 后，`win/modern.py` 用 `FOFX_RECYCLEONDELETE`，进度回调遇到无法回收的情况会返回 `E_FAIL`，相当于安全地失败。容器里没有 Windows，无法验证 | 在 Windows 上用 U 盘实测。如果确认存在：加 `pywin32; sys_platform == "win32"`，并确认 PyInstaller 能把它打包进去；或者删除前用 `GetDriveTypeW` / `SHQueryRecycleBinW` 拒绝不支持回收站的卷 |
| Q2 | `web/script.js:793-810` | `Delete` 的设计意图究竟是「焦点组」还是「屏幕顶部的组」 | README 写的是「当前组」。H4 的修复优先使用焦点组；焦点不在可视区时，仍沿用「容器内第一个可见行」 | 请确认交互意图 |
| Q3 | `backend/scanner.py:386` | 扫描根内指向根外的联接点（junction）是否应该被扫描 | 现在会扫描进来，但这些结果无法预览、无法删除 | 确认后，要么跳过，要么在界面上说明 |
| Q4 | `tests/test_scanner.py:182` | `test_thumbnail_cache_uses_source_metadata_for_invalidation` 可能偶发失败 | 测试依赖重写文件后 `(size, mtime_ns)` 发生变化；纯色图片的 JPEG 大小可能相同，NTFS 的时间戳粒度又比较粗 | 改成内容不同、大小也不同的图片 |
| Q5 | `web/script.js:777-792` | 焦点为 -1 时，Space/Enter 没有被 `preventDefault` | 如果某个按钮此时保有 DOM 焦点，按键可能触发按钮的默认点击（例如再次弹出批量删除确认框），具体取决于 WebView2 的行为 | 在 WebView2 上实测 |

## 已核实没有问题（避免重复审查）

- `is_path_allowed`：`commonpath` 跨盘符或 UNC 时抛出的 `ValueError` 已被捕获；大小写由 `realpath` 加 `normcase` 统一；根为盘符根目录（`C:\`）时也正确。
- `scan_state` 的嵌套值都是整体替换、不会原地修改，`dict(scan_state)` 浅拷贝是安全的。
- 六段 pHash 索引在阈值 ≤ 5 时不会漏检（11×4 + 10×2 = 64 位，抽屉原理）；锚点（非传递）语义的实现与 CLAUDE.md 一致。
- 只要回调本身不抛异常，`scan_directory` 的每条路径都会发出 `done`。
- 前端没有 XSS：`innerHTML` 只插入数字，路径都经过 `encodeURIComponent` 或 `textContent`。

## 安全（阶段 3）

范围：全仓库（`main.py`、`backend/`、`web/`、`tests/`、`requirements.txt`、`Start_PhotoCleaner.bat`）。
编号与上文接续。威胁模型：本地桌面应用，HTTP 服务只绑定 `127.0.0.1` 的随机端口，没有鉴权；
攻击面是「用户机器上同时打开的恶意网页」和「被扫描目录中的不可信文件」。

| 编号 | 类别 | 位置 | 问题 | 证据 / 触发场景 | 修复建议 | 把握 |
|---|---|---|---|---|---|---|
| **M11** | 鉴权 / 越权 | `main.py:31, 137-271` | **没有校验 Host 和 Origin，也没有会话令牌，存在 DNS 重绑定风险** | 攻击者网页把自己的域名重绑定到 `127.0.0.1:<端口>` 后，就和应用同源了，可以：① `POST /api/scan` 扫描任意目录；② 用 `/api/scan_status` 读到结果路径；③ 用 `/api/image` 读出照片原图；④ 用 `/api/delete` 把重复照片移进回收站。结果白名单约束不了攻击者，因为扫描本身就是攻击者发起的。**已验证**：带 `Host: attacker.example`、`Origin: http://attacker.example` 的 `POST /api/scan` 会被正常处理。缓解因素：端口每次随机，攻击者需要先探测端口 | 加 `TrustedHostMiddleware(allowed_hosts=["127.0.0.1", "localhost"])`；启动时生成随机令牌，通过 `js_api` 交给前端，每个 `/api/*` 请求都校验；`/api/scan` 只接受 `choose_directory` 返回过的目录 | 机制高，可利用性中 |
| L14 | CSRF | `main.py:195` | `POST /api/cancel_scan` 不带请求体，属于「简单请求」 | 任何网页都能用 `fetch(…, {method:'POST', mode:'no-cors'})` 取消正在进行的扫描（已验证返回 200）。影响很小，只是取消扫描。其余写接口都需要 JSON：`text/plain` 会被 FastAPI 的 strict content-type 拒绝（422，已验证）；`application/json` 跨源请求要先过预检，而 OPTIONS 返回 405（已验证），浏览器会拦下 | 和 M11 的令牌方案一起解决 | 高 |
| L15 | 信息暴露 | `main.py:31` | `/docs`、`/redoc`、`/openapi.json` 默认开着（均返回 200） | 对本地应用影响很小，但会给 M11 的攻击者提供现成的接口清单 | `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` | 高 |
| (H1) | 越权 | `main.py:211, 215` | 授权检查的是 `realpath`，但用户选中的是链接路径 | 见 H1：删除链接时，实际被删的是另一个文件（链接目标），超出了用户的选择 | 见 H1 | 高 |

逐项检查，结论如下：

- **注入**
  - SQL：项目没有数据库。
  - 命令：应用代码里没有 `subprocess`、`os.system` 或 `shell=True`；只有一个测试用固定参数调用了 `cmd`。
  - 模板：没有服务端模板。
  - 前端：`innerHTML` 只拼接数字。查询参数全部经过 `encodeURIComponent`，文本全部用 `textContent`。
  - 结论：**未发现问题**。
- **鉴权与越权**：见 M11、L14、H1。另外：
  - 文件端点统一经过 `is_result_path_allowed`，即同时要求「路径在扫描根内」和「路径在结果白名单中」，大小写、`..`、跨盘符的处理都正确。
  - `js_api` 只暴露了 `choose_directory`。
  - `StaticFiles` 由 Starlette 防护路径穿越。
- **敏感信息**
  - 没有硬编码的密钥、令牌或密码（已 grep）。
  - 日志只在 WARNING 级别把文件路径输出到 stderr，不写日志文件，没有凭据。
  - `Start_PhotoCleaner.bat` 暴露了作者本机的 conda 路径，属于信息性问题。
- **不安全的反序列化**
  - 没有 `pickle`、`yaml.load`、`eval` 或 `exec`；请求体都经过 pydantic 校验。
  - 唯一不可信的输入是图片文件，解码由 Pillow / pillow-heif 完成，依赖默认的 `MAX_IMAGE_PIXELS` 防护（参见 M7）。
- **依赖中已知的高危版本**
  - 用 `pip-audit 2.10.1 -r requirements.txt` 按当前最新版本解析，结果是 `No known vulnerabilities found`。本地实测版本见 `01-architecture.md` §4。
  - 依赖没有锁定版本（L13），所以「当前没有已知漏洞」只代表审计时刻的状态。建议锁定版本后，在 CI 里定期运行 pip-audit。
  - Node 端没有 npm 依赖。
