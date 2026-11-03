# 05 · 交接：Windows 适配第一轮之后

写给接下来做审查或加功能的人，以及本地的 Claude Code。

[04-windows-handoff.md](04-windows-handoff.md) 列出了要在 Windows 上验证和决定的事。本轮在本机 Windows 上做了环境检查和实测，修了其中大部分问题。本文件记录：改了什么、怎么验证的、哪些还没验证、还剩什么问题，以及下一步计划（苹果照片格式支持）。

**基准版本**：分支 `claude/windows-fixes`，从 `main` @ `0886f3f` 开出，共 15 个修复和文档提交，本文件随后面的 docs 提交加入。写这份文档时，远端只推送到 `cd46d0e`，之后的提交只在本地；还没有合并进 `main`，也没有开 PR（本机没有安装 `gh`）。文中不写行号，只写函数名，因为行号很快就会过时。

**建议的接手顺序**

1. 读 `CLAUDE.md`（架构和约定）、本文件，需要背景时再看 04。
2. 按 §2 跑两套测试，确认基线：Python 107 项通过、3 项跳过；Node 51 项通过。
3. 先做 §4 中需要在窗口里实测的项目，尤其是本轮新加的界面行为。
4. 再从 §5 的遗留问题或 §6 的苹果格式计划里挑任务。每个问题一个 commit，能写测试的先写测试，并确认修复前失败（沿用 [RUNBOOK.md](RUNBOOK.md) 的工作规则）。

> **安全约定**
> - 测试只用仓库内的 `photo-test\`（已加入 `.gitignore`）。它根目录下原有的 122 张图片**不扫描、不删除、不移动、不重命名**。
> - 合成素材放在 `photo-test\fixtures\`，用 `docs\review\make_windows_fixtures.py` 生成；只有这些素材可以删除，而且必须走回收站。
> - 只在 `claude/windows-fixes`（或从它开出的分支）上提交，不推送 `main`；推送任何分支之前，先问用户。

---

## 1. 本轮改动

| commit | 编号 | 改动 | 测试 |
|---|---|---|---|
| `0a513a2` | — | `.gitignore` 加入 `photo-test/` | — |
| `291e86b` | Q4 | 缩略图缓存失效测试：第二次写入改用不同尺寸的图片，并把 mtime 推后 1 秒。原来两张纯色 JPEG 都是 825 字节，两次写入又落在同一个 NTFS 时间戳刻度内，测试在 Windows 上几乎每次都失败 | 只改测试 |
| `bf028d9` | Q3、L5 | 枚举时跳过 realpath 在扫描根之外的目录联接点（`DirEntry.is_junction()` 加 `_is_within`）。根内互指的联接点照旧遍历，由 realpath 去重防止循环 | 新增 1 条（Windows） |
| `b1d45d7` | W04、W19 | 哈希、pHash 读取或解码失败（且没有取消）时计入 `unreadable_files`，扫描结束提示「(N file(s) could not be read)」。超大图在相似模式下解码失败也走这条路径 | Python 2 条、Node 1 条 |
| `fa83193` | W02 | 文件名编码不成 UTF-8（含孤立代理字符）时跳过，并计入 `skipped_files`，不再让 `/api/scan_status` 返回 500 | 新增 1 条 |
| `57c5836` | W08 | `Start_PhotoCleaner.bat` 改用 `PYTHON_EXE` 变量，找不到解释器时提示并 `pause`；新增 `.gitattributes` 让 `.bat` 保持 CRLF | 实测 |
| `cd46d0e` | — | 按实测修正 CLAUDE.md 和 README | — |
| `092d561` | L15 | 关闭 `/docs`、`/redoc`、`/openapi.json` | 3 条（参数化） |
| `ea3a2da` | W20 | 扫描 `.tif`、`.jfif`，装了 pillow-heif 时再加 `.heif`。`.gif` 没有加 | 1 条 |
| `fe3d2b4` | W15 | 跳过 `$RECYCLE.BIN`、`RECYCLER`、`System Volume Information`（不区分大小写），以及 Windows 上同时带隐藏和系统属性的目录。只隐藏的目录照旧扫描 | 2 条 |
| `e8c9f79` | W11 | `_configure_logging()`：警告同时写到 stderr 和 `%LOCALAPPDATA%\PhotoCleaner\photo-cleaner.log`（满 1 MB 轮换，保留 2 份）；uvicorn 改用 `log_config=None`；服务 8 秒内没就绪时先记一条 error | 1 条（子进程） |
| `e1e8383` | W10、Q5 | `keyName(e)`：输入法报 `'Process'` 时改用 `e.code`；列表里长按 Space 只切换一次；没有照片拥有焦点时也拦截 Space/Enter；拦截 F5、Ctrl+R、Ctrl+Shift+R、Ctrl+F5、Alt+←/→、浏览器前进和后退键。测试替身改为按字符串比较 `dataset` | Node 4 条 |
| `aa6bbe7` | L7 | 进度栏加「Cancel scan」按钮，只在扫描中显示 | Node 1 条 |
| `e0e6fd8` | Q1 | 没有回收站时，要用户同意才永久删除（详见下面） | Python 5 条、Node 5 条 |
| `0af86fc` | — | 文档：上面各项的行为，测试基线 | — |

**Q1 的实现**（目前最需要审查的一处）

- `main._recycle_bin_available(path, size)`：非 Windows 一律返回 True。Windows 上依次检查：
  - `GetVolumePathNameW` 取卷根，`GetDriveTypeW` 必须是固定盘（`DRIVE_FIXED`）；
  - 组策略 `NoRecycleFiles`（HKCU、HKLM）没有打开；
  - 该卷的 `HKCU\...\Explorer\BitBucket\Volume\{GUID}` 下，`NukeOnDelete` 不为 1，`MaxCapacity`（MB）不小于文件大小。注册表只读。
- `/api/delete` 逐个文件判断：
  - 有回收站：照旧调用 `send2trash`。即使请求里带了 `permanent: true`，也不会绕过回收站。
  - 没有回收站、请求带 `permanent: true`：调用 `_delete_permanently`，即 `os.remove`；遇到只读文件时，先去掉只读属性再删。
  - 没有回收站、请求没带：拒绝，路径出现在 `errors` 中，同时列入 `no_recycle_bin`。这个键只在非空时出现，其他响应与以前完全一样。
- `/api/scan_status` 新增 `recycle_bin_available`，取自扫描根所在的卷。
- 前端：`recycleBinAvailable` 为 false 时，单组清理、`Delete` 键、「全部去重」在暂存前先弹 `confirmPermanentDeletion`；「删除未勾选」把这段说明并进原有的确认框，只弹一次。Toast 写明是永久删除，请求带上 `permanent`。服务器返回 `no_recycle_bin` 时（例如文件超过回收站容量），之后的清理也都先确认。
- `tests/test_main.py` 有一个 autouse fixture，把 `_recycle_bin_available` 固定为 True，让其他删除测试不依赖本机设置；要测真实实现时用 `REAL_RECYCLE_BIN_AVAILABLE`。

---

## 2. 环境与测试

### 2.1 本机环境（2026-11-02 检查）

| 项 | 值 |
|---|---|
| 系统 | Windows 11 Home China 10.0.26100；不是管理员，没开开发者模式 |
| Python | `D:\anaconda3\envs\py312-clean\python.exe`，3.12.13，64 位。PATH 上的 `python` 指向 Python 3.13，**不要用**（用户的全局规则） |
| Node / Git | v24.13.1 / 2.55.0 |
| pywebview 运行时 | pywebview 6.2.1、pythonnet 3.1.0、.NET Framework 4.8.1、WebView2 156.0.4314.58 |
| send2trash | 1.8.3，装了 pywin32 311，所以走 modern 实现。`requirements.txt` 没有 pywin32，新建的 venv 会走 legacy（见 §5） |
| pytest / pyinstaller | 9.1.1 / 6.21.0 |
| 磁盘 | C:、D: 都是 NTFS 固定盘，有回收站；`LongPathsEnabled=1`；用户目录没有 8.3 短名 |
| 依赖版本 | 比 `requirements.lock` 旧（例如 Pillow 12.2、Send2Trash 1.8.3），测试照样全部通过。`pip install --dry-run -r requirements.txt -c requirements.lock` 在 cp312-win_amd64 上能全部解析 |

### 2.2 怎么跑

```powershell
$env:PYTHONDONTWRITEBYTECODE = "1"
& "D:\anaconda3\envs\py312-clean\python.exe" -X utf8 -m pytest tests -p no:cacheprovider -q --basetemp=<临时目录>\pytest-tmp
node --test tests/test_frontend.js
```

- **必须写 `tests`**。不带路径时，pytest 会去收集 `photo-test\`，还会经由素材里的联接点循环；本轮出过一次，跑了 8 分钟，还有 2 个收集错误。本轮在素材里建过一个指向上级目录的联接点 `photo-test\fixtures\祖先联接点测试\回到上级`，如果还在，可以删掉。
- `--basetemp` 用来避开 W22（8.3 短路径误报）。`-p no:cacheprovider` 和 `PYTHONDONTWRITEBYTECODE` 让测试不往仓库里写缓存。
- 基线：Python 110 项，本机 107 项通过、3 项跳过（3 条符号链接测试，需要开发者模式）；非 Windows 平台跳过 5 条。Node 51 项全部通过。
- 从 Claude 的终端运行 `.bat` 时要写 `.\Start_PhotoCleaner.bat`：那里设置了 `NoDefaultCurrentDirectoryInExePath=1`，`cmd /c Start_PhotoCleaner.bat` 会找不到文件。
- Claude 桌面 app 是 MSIX 包。从 Claude 启动的程序，写到 AppData 下的文件可能落进包的副本，用户看不到。要看 W11 的日志文件，请用户自己双击启动应用。

---

## 3. 本轮在 Windows 上实测过的

**方法**

- 素材：用 `make_windows_fixtures.py` 生成到 `photo-test\fixtures\`。
- 接口：用 `fastapi.testclient.TestClient(main.app, base_url="http://127.0.0.1")` 调用真实接口（脚本当时放在会话的临时目录，没有提交）。
- 窗口：用户运行 `.bat`，在窗口里扫描了一次。

| 项 | 结果 |
|---|---|
| W01 中文、emoji、`#&%+` 文件名 | ✅ 分组正确，缩略图、`/api/photo_info` 都返回 200 |
| W03 超长路径 | ✅ 超过 259 个字符的文件跳过并计数 |
| 删除被占用的文件 | ✅ 正确失败：大约 1.1 秒后返回 HRESULT `0x80270027`，文件留在原处；关闭句柄后再删，进了回收站。CPython 的 `open()` 不带 `FILE_SHARE_DELETE`，所以应用自己正在读的文件也删不掉（概率很低） |
| 删除只读文件 | ✅ 进入回收站 |
| W02、W04、Q3 | 修复前实测都能复现，修复后：根外的结果为 0；读不了的文件计数正确；含代理字符的目录 `/api/scan_status` 返回 200；指向上级目录的联接点不再被枚举 |
| Q4 | 修复前在本机必失败，修复后通过 |
| W05 原子写入、W06 多进程 | 不适用：应用代码没有 `os.replace`、`rename` 或写文件，并发全是线程 |
| W08 `.bat` | ✅ 纯 ASCII、CRLF；能启动；关闭窗口后显示「Process exited.」 |
| W12 WebView2 的 Origin | ✅ 窗口里扫描时，控制台没有出现「Rejected request」 |
| 联接点环测试 | ✅ 云端从没跑过，本机首次运行就通过 |
| Q1 卷检测 | ✅ D:\、C:\ 判定为有回收站；200 GB 的文件超过 D: 的回收站容量（约 86 GB），判定为没有；网络路径和不存在的盘符判定为没有 |

---

## 4. 还没有验证的

编号指 04 §5 的手动测试项。

| 项 | 需要做什么 |
|---|---|
| 本轮新加的界面行为 | 在窗口里看：Cancel scan 按钮的位置和效果；永久删除的确认框；中文输入法下的 W/A/S/D；长按 Space；F5、Ctrl+R、Alt+← 在 WebView2 里是否真的被拦住（T24–T27）。前端测试只用假 DOM 验证过逻辑 |
| Q1 在真实介质上的表现 | 没有 U 盘，只用 mock 测过。要做：扫描 U 盘或存储卡上的副本，确认会弹确认框、文件被永久删除；不同意时，文件不动（T18）。回收站容量不足的情况（T19）只测了判定函数 |
| T02 窗口版 EXE（H2、W11、W23） | 用 `pyinstaller -F -w` 打包，双击运行；确认日志写进 `%LOCALAPPDATA%\PhotoCleaner\photo-cleaner.log`；关闭后没有残留进程和 `_MEI*` 目录 |
| T07 真实手机照片的方向（M3） | 需要真实的竖拍 JPEG 和 HEIC |
| T09、T10 CMYK 和超大图的内存（M7、W18） | 未测 |
| T28 高 DPI | 未测 |
| T30、T31 一万个文件的耗时，以及杀毒软件的影响（M8） | 未测；Windows 的 `os.stat` 比 Linux 慢 |
| T32、T33 网络共享、OneDrive 占位符（W13、W14） | 未测 |
| 符号链接测试（H1） | 打开开发者模式后重跑 pytest，3 条跳过的测试就会运行 |
| 原图预览：TIF 和 HEIC | 见 §5 第一条 |

---

## 5. 遗留问题

| 编号 | 状态 | 说明 | 建议 |
|---|---|---|---|
| 新 | **待确认，可能是 bug** | `/api/image` 用 `FileResponse` 把原文件直接交给 WebView2，而 WebView2 通常不能解码 TIFF 和 HEIC，所以这两种格式的全屏预览可能是空白（按代码推断）。HEIC 以前就有这个问题；`.tif` 是本轮 W20 加进来的，所以本轮把它带进了更多文件。缩略图由后端转成 JPEG，不受影响 | 先在窗口里实测；确认后，对浏览器不能显示的格式在后端转成 JPEG（见 §6 阶段 1 第 1 项） |
| Q1 残留 | 取舍 | (1) 注册表里没有该卷的键时，按默认设置处理，不检查容量。(2) 前端的标志 `recycleBinAvailable` 只按扫描根所在的卷计算；同一次扫描里个别文件（例如超过容量的）由后端逐个拒绝，用户再清理一次就会弹确认框。(3) 后端每删一个文件都要读几次注册表，大批量删除的耗时没有测 | 可以再加一道防线：依赖 `pywin32; sys_platform == "win32"`，让 send2trash 始终走 modern 实现（无法回收时报错，而不是静默删除），并确认 PyInstaller 会把它打包进去 |
| Q2 | 保持现状 | `Delete` 键清理焦点组；焦点不在可视区时，清理容器内第一个可见组 | 用户没有提出异议 |
| W10 取舍 | 设计如此 | 没有照片拥有焦点时也会拦截 Space/Enter，所以用 Tab 选中按钮的键盘用户，不能用这两个键触发按钮（有焦点时本来就是这样）。Ctrl+F、Ctrl+P、Ctrl+滚轮缩放没有拦截 | — |
| W14 | 未处理 | 扫描 OneDrive、iCloud 文件夹时，「仅在线可用」的文件会被逐个下载 | 枚举时检查 `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` 和 `FILE_ATTRIBUTE_OFFLINE`，跳过并计数（§6 决定 E） |
| W19 | 部分解决 | 超过约 1.79 亿像素的图片在相似模式下仍然解码失败，但现在会计入「could not be read」；缩略图返回 500 | 需要时再调整 `MAX_IMAGE_PIXELS` 和解码预算 |
| W18 | 未处理 | CMYK 图片转 RGB 时不处理 ICC 配置文件，缩略图可能偏色 | 先看 T09 |
| W20 余项 | 没有做 | `.gif` 不扫描（动图的去重语义不明确） | 有需要再加 |
| W09、W13、W16、W17、W23 | 未实测 | 见 04 §3 | — |
| W22 | 只影响测试 | 8.3 短路径会导致测试误报；用 `--basetemp` 规避 | — |
| L12 | 保持跳过 | 授权检查和删除之间的 TOCTOU；`send2trash` 只接受路径字符串。本轮新增的 `os.remove` 分支同样存在这个问题 | 除非改成按句柄删除 |
| M11 范围 | 取舍 | 只校验 Host 和 Origin，没有会话令牌；本机其他程序仍能调用接口 | 不变 |
| 性能第 4 项 | 未采用 | pHash 用 JPEG `draft()` 缩小解码，单张约快 25 倍，但分组结果会变 | 用真实照片对比分组差异后再决定 |
| 端到端测试 | 没有 | 仓库没有 e2e 测试基础设施；窗口里的行为只能手测 | 以后可以考虑用 Playwright 驱动 Chromium，加载本地服务的页面 |

---

## 6. 下一步：苹果照片格式支持（计划，尚未开始）

**现状**：装了 pillow-heif（锁定版本 1.8.1）时，会扫描 `.heic`、`.heif`；扩展名不区分大小写，`.HEIC` 也能识别。精确模式按字节比较，不受格式影响；相似模式和缩略图都会用 pillow-heif 解码整张图，方向由 pillow-heif 自动转正。拍摄时间用 `Image.open` 加 `getexif()` 读取，理论上支持 HEIC，但没有用真实的 iPhone 照片验证过。

**阶段 0：素材（需要用户提供）**

请用户把真实的 iPhone 照片复制到新的子目录 `photo-test\iphone\`：横拍、竖拍、Live Photo（`.HEIC` 和同名 `.MOV`）、编辑过的照片（`IMG_E….HEIC` 和 `.AAE`）、HDR、人像模式、ProRAW `.DNG`（如果有），再加同一张照片导出的 JPG。自动测试用 pillow-heif 编码合成的 HEIC；要先确认安装的 wheel 带有 HEIC 编码器。

**阶段 1：基础（不需要决定）**

1. **原图预览转码**：`/api/image` 对 `.heic`、`.heif`、`.tif`、`.tiff` 在后端解码，按 EXIF 方向转正，长边缩到 4096 像素以内，在 `_decode_budget` 的预算下编码成 JPEG（质量 90）。其他格式照旧用 `FileResponse`。这一项同时修掉 §5 的第一条。
2. **拍摄时间和方向**：用真实照片核对，有问题就修。
3. **速度**：HEIC 的缩略图优先用文件里内嵌的缩略图（尺寸够用时）。pHash 仍然解码整张图，保证数值不变。
4. **打包**：PyInstaller 加 `--collect-all pillow_heif`；确认打出来的 EXE 能解码 HEIC；更新 README 的打包命令。

**阶段 2：需要用户决定（第一项是我的建议）**

| 编号 | 问题 | 可选做法 |
|---|---|---|
| A | Live Photo：删掉 HEIC 以后，同名的 `.MOV` 会留下来 | **显示 Live 标记，删除时连同 `.MOV` 一起删**（`.MOV` 也要进白名单和指纹，确认框和提示里要算上它） / 只显示提示 / 不处理 |
| B | 编辑过的照片：`IMG_1234` 和 `IMG_E1234` 会被分到同一个相似组 | **默认勾选（保留）编辑后的版本**，删除原片时连同 `.AAE` 一起删 / 保持现状（保留第一张） |
| C | 同一张照片的 HEIC 和 JPG：精确模式匹配不上，相似模式能匹配上 | **拍摄时间和尺寸都相同时，标记为「同一张照片的不同格式」，默认保留 HEIC** / 默认保留 JPG（兼容性更好） |
| D | ProRAW `.DNG` | **先只参与精确模式，缩略图显示占位图**；以后再试 DNG 内嵌的预览图（未验证）；最后才考虑 `rawpy`（LibRaw，约 20 MB） |
| E | iCloud、OneDrive 中没下载的文件 | **枚举时识别，跳过并提示「N file(s) not downloaded」** / 照常读取（会触发下载） |

每项一个 commit，提交到 `claude/windows-fixes` 或从它开出的分支；每项都带测试，并用真实照片核对。

---

## 7. 给后续审查的提示

- **风险最集中的地方**：
  - `main.delete_files`：现在有三条分支（回收站、经同意的永久删除、拒绝），还要经过符号链接、白名单、指纹三道检查。
  - `_recycle_bin_settings`：ctypes 加注册表，只在 Windows 上运行。
  - `web/script.js` 的 `stageDeletion` 和 keydown 处理函数。
  
  改这几处时，先读 CLAUDE.md 里对应的段落。
- **测试的盲区**：真实的 WebView2、打包后的 EXE、真实的无回收站介质。前端测试的假 DOM 不解析 `innerHTML`，也不会把 `dataset` 值转成字符串（本轮已在选择器匹配里补上）；`script.js` 在加载时用到新的元素 ID 时，要在 `createRuntime` 里补上。
- **约定**：每个发现一个 commit，提交信息引用编号；先写会失败的测试；不为了通过测试而改已有测试的断言（Q4 那样测试本身有缺陷的除外，并在提交信息里说明）。提交信息用中文，结尾带 `Co-Authored-By` 行。
- **工具**：仓库自带只读的审查子代理 `.claude/agents/code-reviewer.md`；扫描引擎的基准测试是 `python benchmarks/bench_scanner.py`。
- **编号**：H、M、L、Q 的含义见 02-findings；W 见 04 §3。新发现建议从 W24、Q6 接着编。

## 8. 文档索引

| 文件 | 内容 |
|---|---|
| [00-SUMMARY.md](00-SUMMARY.md) | 云端三轮（H、M、L）的总结和 PR 链接 |
| [01-architecture.md](01-architecture.md) | 架构摸底 |
| [02-findings.md](02-findings.md) | 全部发现，包括「待人工确认」和「已核实没有问题」 |
| [03-perf-plan.md](03-perf-plan.md) | 性能分析和基准结果 |
| [04-windows-handoff.md](04-windows-handoff.md) | Windows 风险清单 W01–W23、手动测试 T01–T33、结果记录模板 |
| 05-handoff.md（本文件） | 本轮改动、实测结果、遗留问题、苹果格式计划 |
| [PROGRESS.md](PROGRESS.md)、[RUNBOOK.md](RUNBOOK.md) | 云端各轮的逐步记录、决策，以及工作规则 |
| [make_windows_fixtures.py](make_windows_fixtures.py) | 生成 Windows 手动测试素材 |
