# 04 · Windows 适配交接

给在本地 Windows 上接手的人，以及本地的 Claude Code。

云端的三轮修复（高 H、中 M、低 L）已经全部合并进 `main`。本文件列出在 Windows 上还需要验证和决定的事。

**基准版本**：本文件提交在 `claude/low-fixes`。提交前，该分支已经快进到 `main` @ `032876c`，所以代码与 `main` 完全相同，只多了本文件和素材脚本 `docs/review/make_windows_fixtures.py`。文中的「文件:行号」都以这个版本为准。

**建议的接手顺序**

1. 读 `CLAUDE.md`（架构和约定）和本文件。
2. 按 §4 跑自动测试，把结果填进 §7。
3. 用素材脚本生成测试素材，按 §5 做手动测试，结果也填进 §7。
4. 根据测试结果和 §8 的决定开分支修复。`main` 受保护，不能直接推送，改动要走 PR。

> **安全约定：所有手动测试都只用副本**，也就是脚本生成的合成图片，或者从相册复制出来的照片。不要对真实相册目录点「全部去重」或「删除未勾选」。应用的删除都会走回收站，但 Q1（某些磁盘上可能被永久删除）还没有排除。

---

## 1. 三轮修改总览

| 轮次 | PR | 内容 |
|---|---|---|
| 第一轮 | [#4](https://github.com/OranngeAustin/photo-cleaner/pull/4) | 审查文档、H1–H4 修复、基准脚本 |
| 第一轮 | [#5](https://github.com/OranngeAustin/photo-cleaner/pull/5)、[#6](https://github.com/OranngeAustin/photo-cleaner/pull/6)、[#7](https://github.com/OranngeAustin/photo-cleaner/pull/7) | 性能：相似聚类、结果白名单、并行调度。三个 PR 先合并进 `claude/review-fixes`，再随 #4 进入 `main` |
| 第二轮 | [#8](https://github.com/OranngeAustin/photo-cleaner/pull/8) | M1–M11，同时解决了 L14 |
| 第三轮 | [#9](https://github.com/OranngeAustin/photo-cleaner/pull/9) | L1–L13，其中 L12 跳过 |
| 收尾 | [#10](https://github.com/OranngeAustin/photo-cleaner/pull/10) | 文档：合并状态、第三轮总结 |

发现编号的完整说明见 [02-findings.md](02-findings.md)，逐项的取舍见 [PROGRESS.md](PROGRESS.md)。

### `main.py`：HTTP 接口与安全边界

| 改动 | 位置 | 发现 | PR |
|---|---|---|---|
| `LocalRequestGuard`：`Host` 只接受 `127.0.0.1` 或 `localhost`；`Origin` 存在时必须与 `Host` 同源；否则返回 403 | `main.py:36-81` | M11、L14 | #8 |
| 删除接口拒绝符号链接路径 | `main.py:364` | H1 | #4 |
| 扫描结束时记录每个结果的 `(size, mtime_ns)`；删除前比对，不一致就拒绝 | `main.py:230-262`、`:371-373` | M8 | #8 |
| 删除时在 `scan_lock` 之外解析路径 | `main.py:378` | L1 | #9 |
| 删除后不再清空缩略图缓存 | `main.py:387-389` | L8 | #9 |
| 结果白名单按目录缓存 `realpath` | `main.py:198-228` | 性能 6.2 | #6 |
| 扫描线程入口 `run_scan` 用 `finally` 兜底释放任务 | `main.py:319-336` | L3 | #9 |
| 拍摄时间先读 Exif 子 IFD；遇到超大图返回「未记录」 | `main.py:164-195` | M2 | #8 |
| 没有控制台时，把标准流指向 `os.devnull`（否则打包的 EXE 启动即崩） | `main.py:437-446` | H2 | #4 |

### `backend/scanner.py`：扫描引擎

| 改动 | 位置 | 发现 | PR |
|---|---|---|---|
| 枚举时跳过文件符号链接 | `scanner.py:538` | H1 | #4 |
| 注释写明 Windows 联接点会被遍历 | `scanner.py:528-531` | L5 | #9 |
| 读前缀时多读 1 个字节，检测文件是否变长；变长的组改走全量哈希 | `scanner.py:119-143`、`:594-614` | M1 | #8 |
| 缩略图按 EXIF 方向旋转 | `scanner.py:185-193`、`:209-236` | M3 | #8 |
| 解码像素预算；缩略图先缩小，再合成白底 | `scanner.py:45`、`:52-91`、`:155-168`、`:219-233` | M7 | #8 |
| 生成缩略图失败时，结果不进缓存 | `scanner.py:196-260` | L2 | #9 |
| 相似聚类提速 | `scanner.py:270` 起 | 性能 6.1 | #5 |
| 并行调度改用完成队列；提前结束时取消排队中的任务 | `scanner.py:372-429` | 性能 6.3、L4 | #7、#9 |
| `done` 回调只发一次，回调异常只记日志 | `scanner.py:431-441` | L3 | #9 |

### `web/script.js`：界面状态机

| 改动 | 位置 | 发现 | PR |
|---|---|---|---|
| 跨标签删除后，保证每组至少还有一张勾选 | `script.js:607-647`（`lostSelections`） | H3 | #4 |
| `Delete` 清理焦点组；焦点不在可视区时，清理滚动容器内第一个可见组 | `script.js:807-826` | H4 | #4 |
| 切换标签、暂存删除后焦点仍然有效；撤销或删除失败后焦点复原 | `script.js:575-600`、`:790-805` | M4、M5 | #8 |
| 切标签自动扫描、换目录之前，先等暂存的删除提交完成 | `script.js:29-47`、`:357-376`、`:660-670` | M6 | #8 |
| 撤销窗口内的多次清理合并为一批；所有清理动作共用 `stageDeletion` | `script.js:261-300` | L9、L11 | #9 |
| 扫描结束提示不会隐藏新扫描的进度栏 | `script.js:247-251` | L6 | #9 |
| 状态轮询失败后退避重试；放弃时请求后端取消扫描 | `script.js:406-418` | L7 | #9 |
| 提交删除后，焦点留在原来的组 | `script.js:607-647` | L8 | #9 |
| 提交过程中隐藏 Undo；失败提示 5 秒后自动隐藏 | `script.js:660-711`、`:735-752` | L10 | #9 |
| 删除无用变量和 `pendingDeletion.type` | — | L11 | #9 |

### 其他文件

| 文件 | 改动 | 发现 | PR |
|---|---|---|---|
| `web/style.css` | 删除无效规则 `.group-row.focused` | L11 | #9 |
| `tests/` | Python 测试从 19 项（18 项通过、1 项失败）增加到 94 项（Linux 上 93 项通过、1 项跳过）；Node 测试从 19 项增加到 40 项。每项修复都带回归测试 | M9、M10 及各项修复 | 各 PR |
| `benchmarks/bench_scanner.py` | 阶段 5 新增的基准脚本；第二轮加了 `result_fingerprints` | — | #4、#8 |
| `requirements.lock` | 可选的约束文件，记录测试通过时的精确版本 | L13 | #9 |
| `README.md`、`CLAUDE.md` | 测试基线、行为说明 | — | 各 PR |
| `docs/review/` | 审查文档 | — | #4、#10 |

---

## 2. 云端没能验证的内容

云端是 Linux 容器，没有 Windows 桌面、WebView2 和回收站。下面这些都**只在代码层面或 Linux 上验证过**：

| 类别 | 内容 | 为什么没验证 | 在哪里验证 |
|---|---|---|---|
| 跳过的测试 | `test_scan_directory_symlink_cycle`（`tests/test_scanner.py:321-345`）：用 `mklink /J` 造一个联接点环，断言每个文件只枚举一次 | 只能在 Windows 上运行，三轮中**从未实际运行过** | §4 A3 |
| Windows 上可能跳过的测试 | 3 条符号链接测试：`tests/test_scanner.py:354`、`:587`，`tests/test_main.py:174`。另外 `tests/test_main.py:238` 里的符号链接分支，没有权限时不执行 | Windows 上创建符号链接需要开发者模式或管理员权限；没有权限时自动跳过（见 `tests/test_scanner.py:347-351`） | §4 A3、A4 |
| GUI | pywebview 窗口、文件夹对话框（`main.py:118-124`）、WebView2 渲染、中文字体 | 云端没有桌面 | T01–T05 |
| 浏览器内核 | 前端单元测试用的是假 DOM；真实浏览器验证（M4–M6、M11）只在 Linux 的 Chromium 上做过 | WebView2 只在 Windows 上 | T05、T24–T29 |
| 输入设备与显示 | 按键（含中文输入法）、长按、预览的按住放大和拖动、触控板和触摸屏、125%/150%/200% 缩放 | 同上 | T24–T29 |
| 打包 | `pyinstaller -F -w` 打出的 EXE 能否启动。H2 只用 `sys.stdout = None` 模拟过 | 同上 | T02 |
| 启动脚本 | `Start_PhotoCleaner.bat` | 需要 cmd.exe 和作者本机的 conda 环境 | T03 |
| 回收站 | send2trash 在 Windows 上走哪一套实现；没有回收站的卷、回收站容量不足、只读文件、被占用的文件 | Linux 上 send2trash 用的是 freedesktop 回收站，代码完全不同 | T11–T20 |
| 真实照片 | 手机竖拍 JPEG 和 HEIC 的方向（M3）、CMYK、超大图的内存占用（M7） | 只用合成图片验证过 | T06–T10 |
| 性能 | Windows 上 `os.stat` 的开销（M8）、NTFS 枚举、杀毒软件、网络盘、OneDrive | 基准只在 Linux 容器里跑过 | T30–T33 |
| 依赖 | `requirements.lock` 在 Windows 上能否安装（L13）。pywebview 在 Windows 上还依赖 pythonnet，锁文件里没有 | 锁文件是在 Linux、Python 3.13 上生成的 | §4 A1 |
| 日志 | 窗口版 EXE 会丢弃全部日志（`main.py:437-446`） | — | W11、T02 |

---

## 3. Windows 风险清单

每条都对应本项目的具体代码。「验证」一栏指向 §4 的自动步骤（A 开头）或 §5 的手动测试（T 开头）。标「推断」的结论是读代码得出的，没有在 Windows 上实测过。

| 编号 | 风险 | 代码位置 | 说明 | 验证 |
|---|---|---|---|---|
| W01 | 路径与中文文件名的编码 | 枚举：`backend/scanner.py:513-557`；授权：`main.py:130-160`；拼 URL：`web/script.js:175`、`:529`、`:566`；回传文件名：`main.py:427` | Python 3 在 Windows 上使用宽字符 API，中文、空格、emoji 原则上没问题。需要验证两点：一是含 `#`、`&`、`%`、`+` 的文件名经 URL 编码往返后不变；二是 `realpath` 会展开 8.3 短文件名、改写大小写，之后前端和后端的路径仍能对应上 | T04、T05 |
| W02 | 文件名里有不成对的 UTF-16 代理字符（极少见） | `main.py:340-343`（`/api/scan_status` 返回 JSON） | NTFS 允许这种文件名，Python 会保留为 `'\udc80'` 这样的字符。Starlette 编码 JSON 时会抛出 `UnicodeEncodeError`（已在 Linux 上用 `JSONResponse` 复现），整个扫描结果返回 500，前端重试 4 次后放弃（L7） | 可选，见 T05 的附加步骤 |
| W03 | 超长路径 | `backend/scanner.py:544-547`（完整路径超过 259 个字符的文件跳过并计数）；`web/script.js:474`（提示跳过数量） | 只按文件的完整路径长度判断。send2trash 的 legacy 实现（`SHFileOperationW`）不支持超过 MAX_PATH 的路径，259 以内的应能正常预览和删除。目录本身超过 260 个字符时能否枚举，取决于系统的长路径设置和程序清单：`python.exe` 声明了 `longPathAware`，PyInstaller 的引导程序未确认 | T06 |
| W04 | 文件被占用 | 删除：`main.py:375`、`:384-386`；前端提示：`web/script.js:695-711`；扫描时读取：`backend/scanner.py:97`、`:114`、`:135`、`:140`；原图预览：`main.py:413` | 其他程序以不共享的方式打开文件时，删除会失败；界面应提示「could not be deleted」，并保留该组。扫描时如果文件被独占，哈希读取失败，这个文件会**悄悄从结果中消失**，也不计入跳过数量（推断）。应用自己的文件句柄都在 `with` 中及时关闭，只有预览原图时，`FileResponse` 在传输期间会持有句柄 | T16、T17 |
| W05 | `os.replace` 原子写入 | 不适用 | 已用 grep 确认：应用代码没有 `os.replace`、`os.rename`、`shutil`，也没有以写模式调用 `open`；唯一改动文件系统的操作是 `send2trash`（`main.py:375`），应用也不重命名文件。以后如果要写配置或缓存文件：Windows 上目标文件可能被杀毒软件或索引服务短暂占用，`os.replace` 会抛出 `PermissionError`，需要加重试 | 无需验证 |
| W06 | 多进程 spawn | 不适用；线程池：`backend/scanner.py:367-370`、`:372-429`；入口：`main.py:462-475` | 应用不使用 multiprocessing 或 subprocess（只有测试里用 subprocess 创建联接点、模拟无控制台启动）。并发全部是线程，worker 数为 `min(32, CPU 数 + 4)`；uvicorn 也在线程中运行。PyInstaller `-F` 打出的 EXE 运行时会出现两个进程（解包引导进程和应用进程），这是正常的。如果以后改用 `ProcessPoolExecutor`，必须在 `main.py:462` 之后调用 `multiprocessing.freeze_support()`；而且 `main.py` 在模块顶层创建 FastAPI 应用，`scanner.py` 在顶层注册 HEIC 解码器，spawn 出来的子进程会重复执行这些代码 | T02（关闭窗口后不应残留进程） |
| W07 | 删除方式：回收站（Q1） | `main.py:17`、`:375`；`requirements.txt`（没有 pywin32） | 应用只调用 send2trash，从不直接删除文件。send2trash 2.1.0 在 Windows 上按是否装了 pywin32 选择实现：<br>• 装了 pywin32：用 modern 实现（`IFileOperation`，带 `FOFX_RECYCLEONDELETE` 和 `FOFX_EARLYFAILURE`），文件无法回收时报错。<br>• 没装：用 legacy 实现（`SHFileOperationW`，标志位 `FOF_ALLOWUNDO\|FOF_NOCONFIRMATION\|FOF_NOERRORUI\|FOF_SILENT`）。其中 `FOF_NOCONFIRMATION` 会自动对 Shell 的「无法放入回收站，是否永久删除」回答「是」。所以在没有回收站的卷（U 盘、SD 卡、网络共享）上，或者文件超过回收站容量时，**文件可能被静默永久删除**。<br>conda 环境常常自带 pywin32，所以源码运行和打包的 EXE 可能走不同的实现 | A2（确认实现），T18、T19 |
| W08 | `.bat` 的编码与路径 | `Start_PhotoCleaner.bat:9`（`cd /d "%~dp0"`）、`:12`（写死 `D:\anaconda3\envs\py312-clean\python.exe`） | 文件是纯 ASCII，目前没有编码问题。仓库没有 `.gitattributes`，换行符取决于 Git 的 `core.autocrlf`；脚本里没有标签和 `goto`，LF 换行也能运行。以后如果要在 `.bat` 里写中文：用 ANSI（GBK）保存，或者用不带 BOM 的 UTF-8 并在开头加 `chcp 65001 >nul`。带 BOM 会让第一行变成无法识别的命令。`%~dp0` 加了引号，项目放在中文或带空格的目录里也能正常切换 | T03 |
| W09 | 高 DPI 缩放 | 窗口尺寸：`main.py:474`（1200×800）；缩略图最大 256 像素：`backend/scanner.py:246`；缩略图显示为 150×150 CSS 像素：`web/style.css:188-207`；预览缩放拖动：`web/script.js:65-145` | 前端坐标都是 CSS 像素，与缩放比例无关。缩放到 200% 时，150 CSS 像素对应 300 物理像素，大于 256 像素的缩略图，看起来会略虚；150% 及以下没有这个问题。窗口尺寸按逻辑像素还是物理像素计算，取决于 pywebview 的 DPI 感知设置，没有验证过 | T28 |
| W10 | 按键事件 | 按下：`web/script.js:828-935`；松开：`web/script.js:208-213` | (a) 中文输入法处于中文模式时，字母键的 `e.key` 可能变成 `Process`，W/A/S/D 失效，方向键通常不受影响；代码没有处理 `isComposing`（推断）。<br>(b) 列表中长按 Space 时，代码没有检查 `e.repeat`（`:910-916`），按键自动重复会反复切换勾选，松开时的状态不确定。<br>(c) 焦点为 -1 时提前返回（`:859`），不会调用 `preventDefault`，Space/Enter 会触发当前拥有 DOM 焦点的按钮（Q5）。<br>(d) 没有拦截 WebView2 自带的快捷键：F5、Ctrl+R 刷新会丢掉扫描结果；另外还有 Ctrl+F、Ctrl+P、Ctrl+滚轮缩放、Alt+← 后退。<br>(e) Ctrl+Z 只在有待删除项时生效（`:830-835`） | T24–T27 |
| W11 | 窗口版 EXE 没有日志 | `main.py:437-446`（无控制台时 stdout/stderr 指向 devnull）；`main.py:465`（uvicorn 日志级别为 error） | 在 `-w` 打包的 EXE 里，应用所有的 `logger.warning` 都会被丢弃，例如：M11 的「Rejected request…」（`main.py:70`）、删除失败（`main.py:385`）、缩略图和 pHash 失败。服务 8 秒内没起来时抛出的 `RuntimeError`（`main.py:470-472`）也不会有任何提示，表现就是窗口不出现。排查问题要用源码运行（`python main.py`，日志输出在控制台），或者打一个不带 `-w` 的控制台版 | T02 |
| W12 | Host/Origin 校验与 WebView2（M11） | `main.py:36-81`；窗口地址：`main.py:456-457`（取自监听套接字，形如 `http://127.0.0.1:<端口>`） | 在 Linux Chromium 中，应用页面的同源 POST 带 `Origin: http://127.0.0.1:<端口>`，能通过校验。如果 WebView2 发出的 `Origin` 或 `Host` 形式不同，所有请求都会返回 403，表现为扫描无法开始、缩略图全部空白 | T05、T29 |
| W13 | 联接点、映射盘、网络路径 | 按 realpath 去重：`backend/scanner.py:513-519`；遍历联接点：`backend/scanner.py:528-531`；授权：`main.py:130-160` | 扫描根内指向根外的联接点：结果能看到，但预览和删除都返回 403（Q3）。映射网络盘（如 `Z:`）和 `subst` 盘：`realpath` 可能解析成 UNC 路径或真实路径；授权的两边都用 `realpath`，理论上能对上，但没有实测 | T21、T32 |
| W14 | OneDrive 等云文件占位符 | 哈希读取整个文件：`backend/scanner.py:94-117`、`:119-143`；pHash 解码整张图：`backend/scanner.py:155-168` | 「仅在线可用」的文件不是符号链接，会被正常枚举，读取时 Windows 会自动下载。扫描 OneDrive 下的「图片」文件夹，可能把整个相册下载下来 | T33 |
| W15 | 驱动器根目录与系统目录 | `backend/scanner.py:498-560`（没有跳过隐藏和系统目录） | 扫描 `D:\` 这样的根目录时，会进入 `$RECYCLE.BIN`：回收站里已删除的照片会出现在结果中，甚至和原图配成一组。`System Volume Information` 会因拒绝访问被静默跳过（`backend/scanner.py:556-557`） | T23 |
| W16 | NTFS 目录项里的文件大小可能滞后 | 大小来自目录枚举：`backend/scanner.py:548-552`；M1 的长度复核：`backend/scanner.py:594-614` | 正在写入的文件，目录项中的大小可能还没更新。M1 的「多读 1 个字节」复核会把长度不一致的组送去全量哈希，偏差是偏安全的 | 低优先级：一边复制大量照片，一边扫描同一个目录 |
| W17 | 文件指纹与外部修改（M8） | `main.py:230-262`、`:371-373` | 在资源管理器里修改照片属性（评级、标记），或者照片应用写入元数据，都会改变 mtime，之后删除会被拒绝，这是设计上的行为。FAT32 的 mtime 精度只有 2 秒：2 秒内被换成大小相同的文件时，指纹仍会匹配 | T15 |
| W18 | CMYK 与色彩配置文件 | `backend/scanner.py:224-227`（非 RGB 图片直接 `convert("RGB")`，不处理 ICC 配置文件） | CMYK JPEG 的缩略图颜色可能和照片查看器显示的不同。原图预览由 WebView2 解码，颜色以浏览器为准。分组不受影响，因为 pHash 用的是灰度图 | T09 |
| W19 | 超大图片 | 像素预算：`backend/scanner.py:45`、`:52-91`；拍摄时间：`main.py:184`；Pillow 默认的 `MAX_IMAGE_PIXELS`（项目没有修改：约 8900 万像素时告警，约 1.79 亿像素时报错） | 超过 1.79 亿像素的图片在相似模式下解码失败，会**悄悄**不出现在结果里，缩略图返回 500。精确模式只读字节，不受影响 | T10 |
| W20 | 支持的扩展名 | `backend/scanner.py:29-31`（`.jpg .jpeg .png .bmp .webp .tiff`；装了 pillow-heif 时再加 `.heic`） | Windows 上常见的 `.tif`、`.jfif`、`.heif`、`.gif` 都不会被扫描。这不是 bug，但用户可能会以为扫描漏了文件 | T08 |
| W21 | 依赖与运行时 | `requirements.txt`；`requirements.lock:1-10`（文件头说明） | pywebview 在 Windows 上依赖两样东西：<br>• pythonnet：需要与 Python 版本匹配的安装包，以及 .NET Framework 4.7.2 以上。<br>• WebView2 Runtime：Windows 11 自带，Windows 10 可能需要另外安装。<br>锁文件是在 Linux、Python 3.13 上生成的，个别固定版本在较旧的 Python 上可能没有安装包 | A1、A2 |
| W22 | 8.3 短路径导致测试误报 | 扫描根做 realpath：`main.py:274`；测试中把扫描结果与 `str(tmp_path / …)` 直接比较：`tests/test_main.py:333`、`:432` | 用户名较长或含中文时，`%TEMP%` 里可能出现 8.3 短文件名（如 `C:\Users\ZHANGS~1\...`）。`realpath` 会把它展开成长文件名，扫描结果里的路径就和测试期望的字符串对不上，测试失败，但应用本身没有问题 | A3（用 `--basetemp` 规避） |
| W23 | PyInstaller 单文件 EXE | 资源目录：`main.py:26-29`（`_MEIPASS`）；打包参数 `--add-data "web;web"`；服务就绪等待：`main.py:449-459`、`:468-472` | 单文件 EXE 每次启动都要解包到 `%TEMP%\_MEIxxxx`。杀毒软件可能误报，或者拖慢启动；进程被强制结束时，解包目录会残留。服务就绪最多等 8 秒，超时后什么提示都没有（见 W11） | T02 |

---

## 4. 本地自动测试步骤（Windows PowerShell）

**前置条件**
- Git。
- 64 位 Python 3.12 或 3.13。作者的 `.bat` 用的是 3.12，锁文件是在 3.13 上生成的。
- Node.js 18 或以上。前端测试使用 Node 自带的 `node:test`。

### A0 取代码

```powershell
cd D:\code                               # 任意工作目录
git clone https://github.com/OranngeAustin/photo-cleaner.git   # 已有仓库就跳过这一行
cd photo-cleaner
git fetch origin
git switch claude/low-fixes              # 代码与 main 相同，多了本文件和素材脚本
git pull
```

### A1 创建虚拟环境、安装依赖

```powershell
py -3.13 -m venv .venv                   # 或 py -3.12；没有 py 启动器就用 python -m venv .venv
# 如果激活时提示「禁止运行脚本」，先执行下一行，只对当前窗口生效：
# Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -c requirements.lock pytest pyinstaller
```

如果因为某个固定版本没有对应的安装包而失败，把报错记进 §7，然后改用不带锁文件的安装：

```powershell
python -m pip install -r requirements.txt pytest pyinstaller
```

### A2 记录环境（填进 §7 的环境表）

```powershell
python --version
node --version
python -m pip freeze > "$env:USERPROFILE\Desktop\pc-pip-freeze.txt"
# 打印 send2trash.win.modern（装了 pywin32）或 send2trash.win.legacy（见 W07）
python -c "from send2trash.win import send2trash as f; print(f.__module__)"
python -c "import webview, PIL, pillow_heif; print('import ok', PIL.__version__, pillow_heif.__version__)"
# WebView2 Runtime 版本。没有输出的话，到「设置 → 应用」里找 Microsoft Edge WebView2 Runtime
(Get-ItemProperty 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction SilentlyContinue).pv
```

### A3 Python 测试

用 `--basetemp` 指定一个路径里没有 8.3 短文件名的临时目录（见 W22）。**pytest 每次运行都会清空这个目录**，不要指向放有用文件的地方。

```powershell
python -m pytest -q -rs --basetemp="$env:USERPROFILE\pc-pytest-tmp"
```

预期结果（按代码推断，没有在 Windows 上实测过）：
- 没开开发者模式：`91 passed, 3 skipped`。跳过的 3 条都是符号链接测试，原因是 `Creating symlinks requires extra privileges on this platform`。
- 开了开发者模式（A4）：`94 passed`。
- `test_scan_directory_symlink_cycle` 会第一次真正运行（`mklink /J` 不需要管理员权限）。如果它失败，把完整输出记下来：这就是要修的第一个 Windows 问题。
- 失败信息里如果出现 `~1` 这类路径不一致，说明 `--basetemp` 没有生效，或者指向的目录本身带短文件名。

### A4 开启开发者模式后重跑（可选，让符号链接测试也运行）

路径：设置 → 系统 → 开发者选项 → 开发人员模式。开启后重新打开 PowerShell，激活虚拟环境，再执行一次 A3。

### A5 前端测试

```powershell
node --test tests/test_frontend.js
```

预期结果：`# pass 40`，`# fail 0`。

### A6 基准测试（可选）

```powershell
python benchmarks/bench_scanner.py --json "$env:USERPROFILE\Desktop\pc-bench-windows.json"
```

和 [03-perf-plan.md](03-perf-plan.md) 中的 Linux 数据只比较量级。重点看 `result_fingerprints`（M8 新增的 stat 开销，Linux 上约 1.35 µs/文件）。

### A7 打包

```powershell
pyinstaller -F -w --name PhotoCleaner --add-data "web;web" main.py          # 窗口版：dist\PhotoCleaner.exe
pyinstaller -F --name PhotoCleanerConsole --add-data "web;web" main.py      # 控制台版，用来看日志（W11）
```

### A8 生成手动测试素材

**输出目录必须是新的空目录**：素材里有只读文件，重复运行时无法覆盖。

```powershell
python docs\review\make_windows_fixtures.py D:\pc-test --many 10000 --huge
```

- `--many 10000` 会额外生成 5000 组小图，用于 T30 的性能测试。
- `--huge` 会生成一张约 2 亿像素的灰度 PNG，用于 T10。生成时大约需要 1 GB 内存，不需要可以去掉。

---

## 5. 手动测试清单

### 5.1 准备素材

**全部使用副本。** 下表中「脚本」指 A8 的素材脚本，输出在 `D:\pc-test`，扫描根是 `D:\pc-test\扫描根`。

每组默认勾选排在最前面的文件。脚本生成的「X - 副本」排在「X」前面，所以默认**保留「- 副本」**，删除不带「副本」的那张。

| 素材 | 位置（相对 `D:\pc-test`） | 来源 | 用于 |
|---|---|---|---|
| S01 中文路径 | `扫描根\中文路径\春节 2024（副本）\` | 脚本 | T04、T05、T11 |
| S02 特殊字符文件名（emoji、`#`、`&`、`%`） | `扫描根\特殊字符\` | 脚本 | T05、T15 |
| S03 超长路径（完整路径 255 个和 263 个字符，外加一个短名） | `扫描根\超长路径\…` | 脚本 | T06 |
| S04 竖拍（EXIF 方向 6 和 8） | `扫描根\竖拍\` | 脚本 | T07 |
| S05 真实手机照片：竖拍 JPEG 和 HEIC 各几张，每张再复制一份 | `扫描根\真实照片\` | **手动复制** | T07、T19 |
| S06 CMYK JPEG，以及同一张图的 RGB 版本 | `扫描根\CMYK\` | 脚本 | T08、T09 |
| S07 带透明色的调色板 PNG | `扫描根\透明\` | 脚本 | T09 |
| S08 大图：4800 万像素 JPEG，可选约 2 亿像素 PNG | `扫描根\大图\` | 脚本（`--huge`） | T10 |
| S09 只读文件：`readonly.jpg` 已设只读属性，默认会被删除 | `扫描根\只读\` | 脚本 | T14 |
| S10 被占用的文件（`locked.jpg`，默认会被删除） | `扫描根\被占用\` | 脚本，再用 PowerShell 独占（见下） | T16、T17 |
| S11 相似：同一张图，缩小后低质量重存 | `扫描根\相似\` | 脚本 | T08 |
| S12 不支持的扩展名：`.tif`、`.jfif`、`.gif` | `扫描根\不支持的扩展名\` | 脚本 | T08 |
| S13 截断的 JPEG | `扫描根\损坏\` | 脚本 | T08 |
| S14 约 5 MB 的随机噪声图 | `扫描根\回收站容量\` | 脚本 | T19 |
| S15 指向根外的联接点 | `扫描根\联接点（指向根外）` → `外部目录` | 脚本（`mklink /J`） | T21 |
| S16 文件符号链接 `b-指向a的符号链接.jpg` → `a.jpg` | `扫描根\符号链接\` | 脚本（需要开发者模式，否则不创建） | T22 |
| S17 大量文件 | `扫描根\大量文件\` | 脚本（`--many`） | T30 |
| S18 U 盘或 SD 卡（exFAT/FAT32）上的副本 | U 盘根目录下新建 `pc-usb\`，把 S01 的两张复制进去 | 手动 | T18 |
| S19 驱动器根目录（含回收站） | 一个内容很少的分区，或者用「磁盘管理」新建的小型 VHD | 手动 | T23 |

独占一个文件（S10）的方法：

```powershell
$f = [System.IO.File]::Open("D:\pc-test\扫描根\被占用\locked.jpg", 'Open', 'Read', 'None')
# ……测试……
$f.Close()
```

### 5.2 测试项

第 1–10 项不会删除文件。从第 11 项开始会删除素材，素材不够时重新生成到一个新目录，或者从回收站还原。

**启动**

| 编号 | 项目 | 操作步骤 | 预期结果 | 关联 |
|---|---|---|---|---|
| T01 | 源码启动 | 激活虚拟环境，执行 `python main.py` | 几秒内出现「Photo Cleaner UI」窗口；没有防火墙弹窗；控制台没有报错 | W21 |
| T02 | 窗口版 EXE | 双击 `dist\PhotoCleaner.exe`；做一次会失败的删除（T16 的场景）；关闭窗口 | 窗口正常出现（H2）。删除失败时界面有提示，但没有任何日志可看（W11）。关闭后，任务管理器里没有残留的 `PhotoCleaner.exe`（W06），`%TEMP%` 下没有残留的 `_MEI*` 目录（W23） | H2、W06、W11、W23 |
| T03 | 启动脚本 | 把 `Start_PhotoCleaner.bat` 第 12 行改成本机的 Python，例如 `.venv\Scripts\python.exe` 的完整路径；把项目复制到 `D:\测试 目录\photo-cleaner`，双击这个 `.bat` | 控制台显示标题后弹出窗口；关闭窗口后显示「Process exited.」并等待按键 | W08 |
| T04 | 选择中文目录 | 点「Choose Folder to Scan...」，选 `D:\pc-test\扫描根` | 顶部显示**完整**路径（不是只有一个字符）；自动开始精确扫描，进度条能走完 | W01 |

**扫描与显示**

| 编号 | 项目 | 操作步骤 | 预期结果 | 关联 |
|---|---|---|---|---|
| T05 | 结果与预览 | 精确页里找到 S01、S02 两组；双击缩略图；看信息浮层；按 Esc 关闭 | 缩略图都能显示；原图能打开；文件名正确显示中文和 emoji；大小正确；没有空白缩略图（空白说明可能被 403）。附加步骤（可选，W02）：把 S01 中的一张复制成文件名带孤立代理字符的两份，然后重新扫描，记录界面表现。复制命令：`python -c "import shutil; src=r'D:\pc-test\扫描根\中文路径\春节 2024（副本）\一号 照片.jpg'; [shutil.copy(src, 'D:/pc-test/扫描根/bad%d\udc80.jpg' % i) for i in (1, 2)]"` | W01、W02、W12 |
| T06 | 超长路径 | 精确扫描完成后看状态栏，再看「超长路径」组 | 状态栏出现「(1 file(s) skipped due to path length)」；组里只有 `a.jpg` 和 `…-255.jpg` 两张，都能预览；`…-263.jpg` 不出现 | W03 |
| T07 | 照片方向 | 看「竖拍」两组和真实照片的缩略图；双击打开原图 | 缩略图都是竖的，方向与原图一致（M3）；HEIC 不会被旋转两次 | M3 |
| T08 | 相似页与边界素材 | 切到「高度相似」页（会自动扫描）；再回到精确页对照 | 相似页：S11 的两张为一组；S06 的 CMYK 与 RGB 版本为一组；截断的 JPEG 不出现。精确页：截断的 JPEG 作为重复出现，缩略图空白。两页都不出现 `.tif`、`.jfif`、`.gif`（W20） | W19、W20 |
| T09 | CMYK 与透明 | 把 CMYK 的缩略图与系统「照片」应用中的颜色对比；看透明 PNG 的缩略图 | CMYK 颜色接近，有明显偏色时记录下来（W18）；透明区域显示为白底 | W18 |
| T10 | 大图内存 | 打开任务管理器，在「详细信息」页观察进程内存；重新扫描（换个目录再换回来）后切到相似页 | 扫描能完成，界面不卡死；记录内存峰值，解码预算约 0.8 GB（M7）。2 亿像素的 PNG 不出现在相似页，但在精确页正常出现（W19） | M7、W19 |

**删除与回收站**

| 编号 | 项目 | 操作步骤 | 预期结果 | 关联 |
|---|---|---|---|---|
| T11 | 单组清理与撤销 | 在 S01 组点「Clean Unselected」，3 秒内按 Ctrl+Z；然后再点一次，等 3 秒 | 第一次：组恢复，提示消失，回收站里没有新文件。第二次：提示变成「Moving 1 photo(s) to the Recycle Bin…」，并且没有 Undo 按钮（L10）；随后组消失，未勾选的那张出现在回收站，可以还原。焦点停在附近的组，列表不会跳回顶部（L8） | L8、L10、W07 |
| T12 | 用键盘连续清理 | 用 S 键把焦点移到某一组，按 Delete；3 秒内再按一次 Delete；然后按 Ctrl+Z | 提示显示「2 photos marked」；按 Ctrl+Z 后两组都恢复，焦点回到第一次按 Delete 之前的组（L9） | L9 |
| T13 | 切标签前先提交 | 清理一组后，3 秒内切到「高度相似」页 | 先提交删除，再开始相似扫描（M6）；相似页结果里没有刚删除的文件 | M6 |
| T14 | 删除只读文件 | 清理「只读」组（默认删除的就是只读的 `readonly.jpg`） | 文件进入回收站，没有确认弹窗；从回收站还原后仍是只读 | W07 |
| T15 | 扫描后被修改（M8） | 扫描完成后，用「画图」打开 S02 组中未勾选的那张（不带「副本」），画一笔并保存；然后清理这一组 | 提示「⚠ 1 file(s) could not be deleted. They remain visible.」，文件留在原处；提示没有 Undo 按钮，5 秒后自动消失（L10） | M8、L10、W17 |
| T16 | 删除被占用的文件 | 用 PowerShell 独占 `locked.jpg`，清理「被占用」组；然后执行 `$f.Close()`，再清理一次 | 第一次：提示无法删除，组保持可见。第二次：文件成功进入回收站 | W04 |
| T17 | 扫描时文件被独占 | 先独占 `locked.jpg`，再重新扫描 | 记录实际表现。按代码推断：`locked.jpg` 不出现在结果中，也没有任何提示（W04） | W04 |
| T18 | U 盘上删除（Q1） | 扫描 U 盘上的 `pc-usb`，清理那一组 | README 的承诺是文件进入回收站，或者明确报错。**记录实际情况**：U 盘没有回收站时，文件是否被静默永久删除。同时记下 A2 打印的 send2trash 实现（modern 或 legacy） | Q1、W07 |
| T19 | 回收站容量不足（Q1） | 在回收站属性里，把测试所在磁盘的「自定义大小」设为允许的最小值（测试后改回）；清理「回收站容量」组（约 5 MB）或真实照片组 | **记录实际情况**：文件是进了回收站，还是被永久删除，还是报错 | Q1、W07 |
| T20 | 全部去重 | 在精确页点「全部去重」，等 3 秒 | 每组除第一张以外的照片都进入回收站，界面只剩无法删除的组。**这一步会删掉大部分素材，放在删除测试的最后** | M10 |

**链接与特殊目录**

| 编号 | 项目 | 操作步骤 | 预期结果 | 关联 |
|---|---|---|---|---|
| T21 | 指向根外的联接点（Q3） | 精确扫描 `D:\pc-test\扫描根` | 「根外的照片」那一组会出现（经由联接点路径）；缩略图空白（403），清理时提示无法删除。记录下来，用于决定 Q3 | Q3、L5、W13 |
| T22 | 文件符号链接（H1） | 开发者模式下生成素材后，精确扫描 | `a.jpg` 与 `b-指向a的符号链接.jpg` 不在同一组 | H1 |
| T23 | 驱动器根目录（W15，可选） | 在 S19 分区的根目录放两张相同的照片副本，用资源管理器把其中一张删到回收站，然后在应用中扫描这个分区的根目录 | 记录结果中是否出现 `$RECYCLE.BIN` 下的路径 | W15 |

**键盘与显示**

| 编号 | 项目 | 操作步骤 | 预期结果 | 关联 |
|---|---|---|---|---|
| T24 | 键盘（英文输入） | 把输入法切到英文；依次按 W/A/S/D、方向键、Space、Enter（打开预览）；在预览中按 A/D/Esc；再按 Delete、Ctrl+Z；打开 Caps Lock 后重复一遍 | 都按 README 的说明工作；Caps Lock 没有影响 | W10 |
| T25 | 键盘（中文输入法） | 切到微软拼音的中文模式，重复 T24 | 记录哪些键失效。按代码推断，字母键可能失效，方向键正常（W10a） | W10 |
| T26 | 长按 Space | 列表中焦点在某张照片上时，按住 Space 2 秒再松开；在预览中按住 Space | 列表中：按代码推断，勾选会反复切换（W10b），记录松开后的状态。预览中：按住时放大，松开后还原 | W10 |
| T27 | 没有焦点时的按键与浏览器快捷键 | (a) 选一个没有任何重复的新目录（例如只放一张图片），用鼠标点一下「全部去重」，再按 Space 和 Enter。<br>(b) 有结果时，依次按 F5、Ctrl+R、Ctrl+F、Ctrl+P、Ctrl+滚轮、Alt+←。<br>(c) 在 3 秒撤销窗口内按 F5 | (a) 记录按钮是否被再次触发（Q5）。<br>(b) 记录每个快捷键的表现；刷新后结果会清空，需要重新扫描（W10d）。<br>(c) 刷新后文件没有进回收站：待删除项随页面一起丢弃 | Q5、W10 |
| T28 | 高 DPI | 在「设置 → 显示」中把缩放分别设为 100%、125%、150%、200%；有多台显示器时，把窗口拖到缩放比例不同的屏幕上 | 窗口大小合适，文字清晰；200% 时缩略图可能略虚（W09）；预览中按住放大和拖动都跟手 | W09 |
| T29 | EXE 完整流程（M11） | 用窗口版 EXE 走一遍：选目录、扫描、预览、切标签、删除；可以的话也用触控板、触摸屏或笔操作预览 | 全程正常。如果出现缩略图全部空白或扫描无法开始，用 `PhotoCleanerConsole.exe` 重现，并记录控制台里的「Rejected request with Host … and Origin …」 | M11、W12 |

**性能与环境**

| 编号 | 项目 | 操作步骤 | 预期结果 | 关联 |
|---|---|---|---|---|
| T30 | 大量文件（M8） | 精确扫描和相似扫描 `扫描根\大量文件`（1 万个文件） | 记录从开始扫描到显示结果的总时间，以及进度条走完到结果出现之间的停顿（M8 的 stat 开销）；和 Linux 基准比较量级 | M8、W16 |
| T31 | 杀毒软件 | 在 Windows 安全中心的实时保护开启和关闭时，各做一次 T30（如果允许关闭） | 记录两次耗时的差别 | — |
| T32 | 映射盘或网络共享（可选） | 把 S01 复制到网络共享，映射为 `Z:`，扫描其中的目录 | 预览和删除都正常（不出现 403）；记录删除后文件是否进了回收站（网络共享通常没有回收站，见 Q1） | W13、Q1 |
| T33 | OneDrive（可选） | 在 OneDrive 文件夹里放几张设为「仅在线可用」的照片副本，然后扫描 | 记录扫描是否触发下载（W14） | W14 |

---

## 6. 已知问题

### 6.1 三轮中标为跳过、未完成或待确认的

| 编号 | 状态 | 原因 | 详见 |
|---|---|---|---|
| Q1 | 暂不处理（用户决定） | 在没有回收站的磁盘上，删除可能是永久的（见 W07）；无法在 Linux 上验证，修复需要 Windows 专用代码或新增 pywin32 依赖 | 02-findings「待人工确认」 |
| L12 | ⏭ 跳过 | 授权检查与删除之间存在 TOCTOU。建议的 `lstat` 复核只能缩小时间窗口，无法消除（send2trash 只接受路径字符串）；彻底修复需要 Windows 专用的按句柄删除，风险大于收益。利用前提苛刻，后果可以从回收站还原 | PROGRESS R3-D3 |
| L7 | 部分修复 | 轮询失败后的重试和自动取消已完成；**没有加取消扫描按钮**，因为这属于新增界面功能 | PROGRESS R3-D2 |
| L5 | 只改了文档 | 联接点会被遍历这一点已写入 CLAUDE.md；扫描行为等 Q3 决定 | CLAUDE.md |
| L11（其中两项） | 不成立，没有改 | `scrollContainer` 在 H4 修复后已经被使用；`.lightbox img.zoomed` 是有效规则 | PROGRESS R3-D4 |
| L15 | 未处理 | 不在第三轮的范围（L1–L13）内。`/docs`、`/redoc`、`/openapi.json` 仍然开着；M11 之后外部网页已经访问不到 | 02-findings「安全」 |
| Q2 | 待确认 | `Delete` 键清理的是焦点组还是屏幕顶部的组 | 02-findings |
| Q3 | 待确认 | 指向根外的联接点要不要跳过（见 T21） | 02-findings |
| Q4 | 未修 | 缩略图缓存失效的测试用纯色 JPEG，可能偶发失败 | 02-findings |
| Q5 | 待实测 | 焦点为 -1 时，Space/Enter 可能触发按钮（见 T27） | 02-findings |
| 性能第 4 项 | 未采用 | pHash 用 JPEG `draft()` 缩小解码，单张约快 25 倍，但会改变分组结果，属于产品决策 | 03-perf-plan |
| 性能第 6–8 项 | 未做 | 收益太小，或者无法可靠测量。第 5 项已随 L8 落实 | 03-perf-plan |
| PR #7 | 未达目标、保留 | 并行调度只快了约 9%，没有达到 20% 的目标；用户决定保留 | PROGRESS D11 |
| M11 的范围 | 取舍 | 没有加会话令牌，也没有限制可扫描的目录；本机其他程序仍能调用接口 | PROGRESS R2-D6 |
| M8 缺少指纹时放行 | 取舍 | 只有直接写白名单的测试会遇到这种情况；扫描结束时 stat 失败的文件一律拒绝删除 | PROGRESS 第二轮 |
| 端到端浏览器脚本 | 未提交 | 只在会话中跑过，仓库没有 e2e 测试的基础设施 | 00-SUMMARY |

### 6.2 本次交接时新发现、尚未处理的

都来自 §3，是读代码得出的，需要先在 Windows 上实测确认：

| 编号 | 问题 |
|---|---|
| W02 | 文件名含孤立代理字符时，`/api/scan_status` 返回 500，整个扫描结果无法显示 |
| W04 | 扫描时被独占的文件，会悄悄从结果中消失，不计入跳过数量 |
| W10 | 中文输入法下字母键可能失效；长按 Space 会反复切换勾选；F5 等浏览器快捷键没有拦截 |
| W11 | 窗口版 EXE 没有任何日志，启动失败时也没有提示 |
| W14 | 扫描 OneDrive 文件夹可能触发全量下载 |
| W15 | 扫描驱动器根目录时会进入 `$RECYCLE.BIN` |
| W19 | 超过约 1.79 亿像素的图片在相似模式下被悄悄跳过 |
| W20 | 不支持 `.tif`、`.jfif`、`.heif`、`.gif` |
| W22 | 测试结果在 8.3 短路径下会误报（只影响测试，不影响应用） |

---

## 7. 结果记录模板

把下面两张表复制到 issue 或新文件里填写。结果一栏填：✅ 通过、❌ 失败、⚠ 部分通过或与预期不同、⏭ 未测。

**环境**

| 项目 | 值 |
|---|---|
| 测试日期 | |
| Windows 版本（`winver`） | |
| Python 版本 / 安装方式（python.org、conda） | |
| Node 版本 | |
| WebView2 Runtime 版本 | |
| send2trash 实现（A2：modern / legacy） | |
| 显示缩放比例 / 显示器数量 | |
| 是否开启开发者模式 | |
| 安装依赖时是否用了 `-c requirements.lock` | |
| 测试的提交（`git rev-parse --short HEAD`） | |

**结果**

| 编号 | 项目 | 结果 | 报错信息 / 实际表现 | 备注 |
|---|---|---|---|---|
| A1 | 安装依赖 | | | |
| A2 | 记录环境 | | | |
| A3 | Python 测试（passed / skipped / failed 数量） | | | |
| A4 | 开发者模式下重跑 | | | |
| A5 | 前端测试 | | | |
| A6 | 基准测试 | | | |
| A7 | 打包 | | | |
| A8 | 生成素材 | | | |
| T01 | 源码启动 | | | |
| T02 | 窗口版 EXE | | | |
| T03 | 启动脚本 | | | |
| T04 | 选择中文目录 | | | |
| T05 | 结果与预览 | | | |
| T06 | 超长路径 | | | |
| T07 | 照片方向 | | | |
| T08 | 相似页与边界素材 | | | |
| T09 | CMYK 与透明 | | | |
| T10 | 大图内存 | | | |
| T11 | 单组清理与撤销 | | | |
| T12 | 用键盘连续清理 | | | |
| T13 | 切标签前先提交 | | | |
| T14 | 删除只读文件 | | | |
| T15 | 扫描后被修改 | | | |
| T16 | 删除被占用的文件 | | | |
| T17 | 扫描时文件被独占 | | | |
| T18 | U 盘上删除（Q1） | | | |
| T19 | 回收站容量不足（Q1） | | | |
| T20 | 全部去重 | | | |
| T21 | 指向根外的联接点 | | | |
| T22 | 文件符号链接 | | | |
| T23 | 驱动器根目录 | | | |
| T24 | 键盘（英文输入） | | | |
| T25 | 键盘（中文输入法） | | | |
| T26 | 长按 Space | | | |
| T27 | 没有焦点时的按键与浏览器快捷键 | | | |
| T28 | 高 DPI | | | |
| T29 | EXE 完整流程 | | | |
| T30 | 大量文件 | | | |
| T31 | 杀毒软件 | | | |
| T32 | 映射盘或网络共享 | | | |
| T33 | OneDrive | | | |

---

## 8. 需要你决定的

先看相关测试的结果再决定。「建议」一栏是我的倾向，仅供参考。

| 编号 | 问题 | 可选做法 | 建议 | 先看 |
|---|---|---|---|---|
| Q1 | 没有回收站的磁盘上，删除可能是永久的 | A：加依赖 `pywin32; sys_platform == "win32"`，并确认 PyInstaller 会把它打包进去。<br>B：删除前检查磁盘是否支持回收站，不支持就拒绝删除。<br>C：A 和 B 都做 | 如果 T18 或 T19 确认会永久删除，至少做 A（改动最小）；B 作为第二道防线 | T18、T19、A2 |
| Q3 | 指向根外的联接点要不要扫描 | 跳过 / 在界面上说明 / 保持现状 | 跳过：这些结果既不能预览，也不能删除 | T21 |
| Q2 | `Delete` 键的设计意图 | 焦点组（现状）/ 屏幕顶部的组 | 保持现状 | T12 |
| Q5、W10 | 键盘兼容性 | 用 `e.code` 判断字母键，兼容中文输入法；列表中忽略 `e.repeat` 的 Space；焦点为 -1 时也拦截 Space/Enter | 三项都做，改动都很小 | T25–T27 |
| W10d | 浏览器快捷键 | 拦截 F5、Ctrl+R、Ctrl+P 等 / 保持现状 | 至少拦截刷新，避免误按丢掉结果 | T27 |
| W11 | 窗口版 EXE 的日志 | 写日志文件，例如 `%LOCALAPPDATA%\PhotoCleaner\photo-cleaner.log`，带大小滚动 / 保持现状 | 加日志文件，否则用户遇到问题时无从排查 | T02 |
| W15 | 系统目录 | 跳过 `$RECYCLE.BIN`、`System Volume Information`，以及带隐藏或系统属性的目录 / 保持现状 | 跳过 | T23 |
| W14 | OneDrive 占位符 | 跳过「仅在线可用」的文件（带 `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` 属性）/ 在界面上提示 / 保持现状 | 先看 T33 的结果 | T33 |
| W04、W19 | 被悄悄跳过的文件 | 把读取失败、解码失败的文件计数，在扫描结束时提示 / 保持现状 | 计数并提示 | T10、T17 |
| W20 | 支持的扩展名 | 增加 `.tif`、`.jfif`、`.heif`（需要 pillow-heif） | 增加 | T08 |
| W02 | 孤立代理字符 | 返回 JSON 前替换或跳过这类路径 / 保持现状 | 跳过并计数，概率很低 | T05 附加步骤 |
| L15 | 接口文档页面 | 改为 `FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` / 保持现状 | 关掉，改一行 | — |
| L7 | 取消扫描按钮 | 加 / 不加 | 扫描大目录时有用，可以加 | T30 |
| L12 | 删除的 TOCTOU | 保持跳过 / 改成按句柄删除 | 保持跳过 | — |
| M11 | 会话令牌 | 加（要改前后端接口）/ 不加 | 不加；Host/Origin 校验已经挡住了浏览器发起的攻击 | T29 |
| 性能第 4 项 | pHash 缩小解码 | 采用（分组结果会变）/ 不采用 | 先用真实照片对比分组差异 | — |
| 交互改动 | M6：先提交而不是撤销；L8：焦点留在原位；L9：合并为一批撤销 | 确认 / 调整 | 确认 | T11–T13 |
| `Start_PhotoCleaner.bat` | 写死了作者本机的 conda 路径 | 优先用项目里的 `.venv\Scripts\python.exe`，找不到再用 PATH 中的 `python` / 保持现状 | 改成相对路径 | T03 |
| `requirements.lock` | 锁文件在 Linux 上生成 | 在 Windows 上重新生成 / 保持现状 | 如果 A1 失败，就在 Windows 上重新生成 | A1 |
| Q4 | 可能偶发失败的测试 | 换成内容和大小都不同的图片 / 保持现状 | 换，改动很小 | A3 |
| 远端分支 | review-fixes、medium-fixes、low-fixes、3 个 perf 分支，以及 `claude/trusting-dijkstra-fpy2hd` | 内容都已进入 `main`，可以删除 / 保留 | Windows 适配期间保留 `claude/low-fixes`，其余可以删除 | — |
