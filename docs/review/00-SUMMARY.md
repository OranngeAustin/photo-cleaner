# 00 · 审查与优化总结

本文件记录三轮工作，逐步记录和决策都在 [PROGRESS.md](PROGRESS.md)。三轮的全部改动都已按用户要求合并进 `main`（`b077a6b`），见「合并状态」。

- **第三轮（最新）**：修复低风险问题 L1–L13，[PR #9](https://github.com/OranngeAustin/photo-cleaner/pull/9)。见「第三轮」一节。
- **第二轮**：修复中风险问题 M1–M11，[PR #8](https://github.com/OranngeAustin/photo-cleaner/pull/8)。
- **第一轮**：按 [RUNBOOK.md](RUNBOOK.md) 完成阶段 0–7，包括审查、H1–H4 修复（[PR #4](https://github.com/OranngeAustin/photo-cleaner/pull/4)）和 3 项性能优化（#5–#7），审查基准是 `main` @ `c8a8e5c`。见「一」到「五」。

三轮执行期间都没有推送 `main`、没有 force push、没有合并任何 PR、没有删除远端分支。所有合并都是之后按用户的明确要求进行的。

## 合并状态

| PR | 内容 | 合并到 | 合并 commit |
|---|---|---|---|
| [#5](https://github.com/OranngeAustin/photo-cleaner/pull/5)、[#6](https://github.com/OranngeAustin/photo-cleaner/pull/6)、[#7](https://github.com/OranngeAustin/photo-cleaner/pull/7) | 3 项性能优化 | `claude/review-fixes` | `a425b7b`、`7096e77`、`c10cdb5` |
| [#4](https://github.com/OranngeAustin/photo-cleaner/pull/4) | H1–H4、审查文档、基准脚本（已包含 #5–#7） | `main` | `cb46f1a` |
| [#8](https://github.com/OranngeAustin/photo-cleaner/pull/8) | M1–M11 | `main`（原目标为 `claude/review-fixes`，合并前改为 `main`） | `7b9faa9` |
| [#9](https://github.com/OranngeAustin/photo-cleaner/pull/9) | L1–L13 | `main`（原目标为 `claude/medium-fixes`，合并前改为 `main`） | `b077a6b` |

合并后的 `main` 与事先在本地模拟的合并结果完全相同（文件树一致）。在 `main` 上测试：Python 93 项通过、1 项跳过（Windows 联接点测试），Node 40 项通过。
所有远端分支的内容都已包含在 `main` 中，分支本身没有删除。

## 第三轮：修复低风险问题 L1–L13

本轮只遵守 RUNBOOK 的「工作规则」：
- 每个问题一个 commit。
- 能写测试的先写测试，并确认修复前失败。
- 每次修复后运行全部测试。
- 误报、纯风格偏好或修复风险过大的问题不改。

**测试**：Python 从 86 项通过、1 项跳过，变为 **93 项通过、1 项跳过**；Node 从 32 项增加到 **40 项**。
新增的 15 条测试都确认过修复前失败；没有修改或删除任何已有测试的断言。

| 编号 | 状态 | 问题 → 修复 |
|---|---|---|
| L1 | ✅ | 持有 `scan_lock` 时调用 `realpath` → 删除路径中的 `_path_key` 也移到锁外（扫描结束时的部分已在 M8 中处理） |
| L2 | ✅ | 生成失败的空缩略图被缓存 → 缓存函数不再吞掉异常，下次请求重新生成 |
| L3 | ✅ | `done` 回调失败后会再发一次 `done`，任务也不再释放，之后的扫描一律返回 409 → `done` 只发一次；扫描线程入口用 `finally` 兜底释放 |
| L4 | ✅ | 结果迭代器提前关闭时，要等排队中的任务全部跑完 → 在 `finally` 中取消排队任务 |
| L5 | ✅ 只改文档 | Windows 联接点会被遍历，与文档描述不符 → 在 CLAUDE.md 和代码注释中写明；是否跳过联接点，等 Q3 决定 |
| L6 | ✅ | 扫描结束提示的计时器会隐藏新扫描的进度栏 → 隐藏前检查是否有扫描在进行 |
| L7 | ✅ 部分 | 轮询失败一次就解锁界面 → 退避重试 4 次，放弃时请求后端取消扫描；**没有加取消按钮** |
| L8 | ✅ | 删除后焦点跳回顶部，缩略图缓存被清空 → 焦点留在原位，删除后不再清空缓存 |
| L9 | ✅ | 新的清理动作会静默撤销上一个 → 合并为一批，一次 Ctrl+Z 全部恢复 |
| L10 | ✅ | 提交中 Undo 按钮无效，失败提示不会消失 → 提交时隐藏 Undo，失败提示 5 秒后自动隐藏 |
| L11 | ✅ 部分不成立 | 删除无用变量、`pendingDeletion.type` 和无效 CSS，抽出公共函数 `stageDeletion`；`scrollContainer` 和 `.lightbox img.zoomed` 两项已不成立 |
| L12 | ⏭ 跳过 | 授权检查与删除之间的 TOCTOU：建议的复核只能缩小时间窗口；彻底修复需要 Windows 专用的按句柄删除，风险大于收益 |
| L13 | ✅ | 依赖没有锁定版本 → 新增可选的 `requirements.lock`（`pip install -r requirements.txt -c requirements.lock`），`requirements.txt` 不变 |

L14 已在第二轮随 M11 解决；L15 不在本轮范围内，没有处理。各项的 commit 见 02-findings「低风险修复状态」，决策见 PROGRESS R3-D1～R3-D5。

## 第二轮：修复中风险问题 M1–M11

| 阶段 | 结果 |
|---|---|
| 0 准备 | 从 `claude/review-fixes` @ `4db7895` 创建 `claude/medium-fixes`。基线：Python 56 项通过、1 项失败，Node 23 项通过 |
| 1 架构 | 复核后没有失效内容；本轮新增的防护补进了 01-architecture |
| 2 审查 | 11 项在当前代码上全部仍然存在，其中 M1、M2、M3、M8、M11 用脚本复现 |
| 3 安全 | M11 已复现（伪造 Host 和 Origin 的请求返回 200）；pip-audit 无已知漏洞 |
| 4 修复 | 11 项全部完成，每项 1 个 commit，附测试，且测试都确认过修复前失败、修复后通过 → [PR #8](https://github.com/OranngeAustin/photo-cleaner/pull/8) |
| 5 性能 | 新旧代码交错 A/B：只有 `exact` 有真实回归（+6.5%，来自 M1 新增的 `fstat`），其余都在噪声内 |
| 6 优化 | 消除这项回归：改为多读 1 个字节代替 `fstat`，最终只比修复前慢 1.6%，在噪声范围内（先单独提交了特征测试） |
| 7 总结 | 本节 |

**测试**：Python 从「56 项通过、1 项失败」变为「**86 项通过、1 项跳过、0 项失败**」，跳过的是 Windows 联接点测试；Node 从 23 项增加到 **32 项**，全部通过。
另外用真实 Chromium（WebView2 的内核）验证了 M11 的拦截效果，以及 M4–M6 的键盘和删除流程。

| 编号 | 问题 → 修复 |
|---|---|
| M1 | 文件在枚举后被写长时，可能被误判为重复 → 读前缀时检测大小变化，变化的组改走全量哈希 |
| M2 | 「拍摄时间」显示的其实是修改时间 → 先读 Exif 子 IFD |
| M3 | 竖拍照片的缩略图是横的 → 按 EXIF Orientation 只旋转已经缩小的缩略图 |
| M4 / M5 | 切换标签、暂存删除后键盘失效 → 焦点总有有效目标，撤销或删除失败后焦点复原 |
| M6 | 删除和扫描交错进行 → 切标签自动扫描、换目录之前，先等删除提交完成 |
| M7 | 大图并发解码可能 OOM → 解码像素预算（1.92 亿像素），缩略图先缩小再合成白底 |
| M8 | 扫描后被替换过的文件照样被删 → 扫描结束时记录 `(size, mtime_ns)`，删除前比对 |
| M9 | 符号链接环测试在非 Windows 上必然失败 → 非 Windows 上跳过，加强断言，并新增可移植的版本 |
| M10 | 高风险路径缺少测试 → 补 6 条，并做了变异检查 |
| M11 | DNS 重绑定 → `LocalRequestGuard` 校验 Host 和 Origin。**L14 一并解决**；L1 随 M8 得到缓解 |

**本轮的主要取舍**（详见 PROGRESS R2-D1～R2-D11）：
- PR 指向 `claude/review-fixes`，不指向 `main`。
- M6 选择「先提交」而不是「撤销」。
- M11 没有加会话令牌，也没有限制 `/api/scan` 可扫描的目录，因为这两项都要改前后端接口。
- M8 遇到缺少指纹的白名单路径时放行，这种情况只会出现在测试中。
- M9 修改了已有测试：只改了平台检查并新增断言，原有断言一条没改。
- 阶段 6 的回归修复直接提交在 PR #8 中，没有另开 perf 分支。

**本轮没有做的**：
- 低风险问题中，除了 L14（已解决）和 L1（已缓解），其余都没有处理（已在第三轮处理，见上文）。
- Q1 按用户的决定暂不处理。
- 端到端浏览器脚本没有提交到仓库（仓库没有 e2e 基础设施）。

## 一、完成了什么

| 阶段 | 产出 | 要点 |
|---|---|---|
| 0 准备 | `PROGRESS.md` | 测试基线：Python 18 项通过、1 项失败（这个失败是已有问题），Node 19 项全部通过；仓库原本没有基准测试 |
| 1 架构 | [01-architecture.md](01-architecture.md) | 梳理了模块、入口、数据流、外部依赖和高风险区域；审查顺序为 `main.py` → `web/` → `backend/` → `tests/` → 根目录配置 |
| 2 审查 | [02-findings.md](02-findings.md) | 3 个 `code-reviewer` 子代理按目录并行审查，主会话逐条核对；**所有「高」级别问题都用脚本或测试复现过** |
| 3 安全 | 02-findings.md「安全」一节 | DNS 重绑定（M11）；`cancel_scan` 存在 CSRF（L14）；`/docs` 未关闭（L15）。注入、反序列化、硬编码密钥均未发现问题；pip-audit 未发现已知漏洞 |
| 4 修复 | [PR #4](https://github.com/OranngeAustin/photo-cleaner/pull/4) → `main` | 修复 H1–H4，每个问题一个 commit，并附回归测试。每个回归测试都确认过修复前失败、修复后通过 |
| 5 性能 | [03-perf-plan.md](03-perf-plan.md)、`benchmarks/bench_scanner.py` | 7 项基准（5 次取中位数，并记录 tracemalloc 峰值内存）；用 cProfile 定位热点；按「收益高、风险低」选出前 3 项 |
| 6 优化 | PR #5、#6、#7 → `claude/review-fixes` | 每项都先提交特征测试，再提交优化；结果见下表 |
| 7 总结 | 本文件 | |

审查发现共计：**高 4、中 11、低 15、待人工确认 5**。

### 修复的高危问题（PR #4）

| 编号 | 问题 | 修复 |
|---|---|---|
| H1 | 精确去重时，「删除符号链接」实际会把链接指向的原照片（也就是用户要保留的那张）移进回收站 | 扫描时跳过文件符号链接；删除接口拒绝符号链接路径 |
| H2 | 按 README 的 `pyinstaller -F -w` 打出的 EXE，启动时 uvicorn 因 `sys.stdout is None` 崩溃 | 启动前把为 `None` 的标准流指向 `os.devnull` |
| H3 | 在一个标签页删除照片后，另一个标签页里的某组可能一张勾选都不剩，下一次清理就会删光这一组 | 某组的勾选项因删除全部丢失时，默认勾选第一张还存在的照片 |
| H4 | `Delete` 键清理的不是当前焦点组，而是窗口里第一个「可见」行，甚至可能是被页头挡住、实际看不见的行 | 优先清理焦点组；焦点组不在视野内时，退回到滚动容器内第一个可见行 |

### 性能优化（阶段 6）

| PR | 热点 | 优化前 → 优化后（5 次中位数） | 内存 | 是否达到 20% 目标 |
|---|---|---|---|---|
| [#5](https://github.com/OranngeAustin/photo-cleaner/pull/5) | `cluster_similar_hashes`（6 万个哈希） | 6136 → **1901 ms（−69%，3.2×）**；最坏的偏斜输入 1.46× | 11.9 → 9.8 MiB | ✅ |
| [#6](https://github.com/OranngeAustin/photo-cleaner/pull/6) | `_collect_result_path_keys`（2 万条路径） | 160.9 → **67.7 ms（−58%，2.4×）**；`scan_lock` 的持有时间同比缩短 | 不变 | ✅ |
| [#7](https://github.com/OranngeAustin/photo-cleaner/pull/7) | `_iter_parallel_results` | 调度 −9.4%，精确扫描 −9.1%，相似扫描 −1.0%（同进程交错 A/B 对比） | 不变 | ❌（试了 3 种方案，保留其中最好的正确版本） |

3 个 perf 分支在本地依次合并进 `claude/review-fixes`，均无冲突。合并后的测试结果：Python 56 项通过、1 项失败（已有问题），Node 23 项全部通过。

## 二、所有 PR

| PR | 分支 → 目标 | 内容 | 状态 |
|---|---|---|---|
| [#4](https://github.com/OranngeAustin/photo-cleaner/pull/4) | `claude/review-fixes` → `main` | 审查文档、H1–H4 修复、基准脚本，以及测试基线文档的更新 | 已合并（`cb46f1a`） |
| [#5](https://github.com/OranngeAustin/photo-cleaner/pull/5) | `claude/perf-cluster` → `claude/review-fixes` | 相似聚类提速 | 已合并（`a425b7b`） |
| [#6](https://github.com/OranngeAustin/photo-cleaner/pull/6) | `claude/perf-result-keys` → `claude/review-fixes` | 结果白名单按目录缓存 realpath | 已合并（`7096e77`） |
| [#7](https://github.com/OranngeAustin/photo-cleaner/pull/7) | `claude/perf-parallel` → `claude/review-fixes` | 并行调度改用完成队列（未达到目标，用户决定保留） | 已合并（`c10cdb5`） |
| [#8](https://github.com/OranngeAustin/photo-cleaner/pull/8) | `claude/medium-fixes` → `main`（原为 `claude/review-fixes`） | **第二轮**：M1–M11，附测试 | 已合并（`7b9faa9`） |
| [#9](https://github.com/OranngeAustin/photo-cleaner/pull/9) | `claude/low-fixes` → `main`（原为 `claude/medium-fixes`） | **第三轮**：L1–L13，附测试 | 已合并（`b077a6b`） |

## 三、跳过项及原因

RUNBOOK 中的阶段和子任务都没有跳过，但有以下几处是刻意没有做的：

| 项目 | 原因 |
|---|---|
| L12：授权与删除之间的 TOCTOU | 建议的 `lstat` 复核只能缩小窗口，无法关闭（`send2trash` 只接受路径字符串）；彻底修复要改成 Windows 专用的按句柄删除，改动大。利用前提苛刻，后果可以从回收站还原（PROGRESS R3-D3） |
| L7：取消扫描按钮 | 属于新增界面功能；重试和放弃时自动取消，已经解决了「结果被丢弃、再次扫描返回 409」（PROGRESS R3-D2） |
| L15：`/docs`、`/redoc`、`/openapi.json` 仍然开着 | 不在第三轮的范围（L1–L13）内。M11 之后外部网页已经访问不到，基本没有风险；改一行即可关闭 |
| Q1：在没有回收站的磁盘上可能被永久删除（建议定级为高） | 在 Linux 容器里无法验证 Windows 回收站的行为；修复需要 Windows 专用代码，或者新增 pywin32 依赖。用户决定暂不处理 |
| 既有失败测试 `test_scan_directory_symlink_cycle` | 第一轮按 RUNBOOK 只记录、不修；第二轮作为 M9 修复，在非 Windows 上改为跳过 |
| 性能第 4 项：pHash 用 JPEG `draft()` 缩小解码（单张约快 25×） | 会改变 pHash 数值，进而改变分组结果，无法用特征测试固定行为，属于产品决策 |
| 性能第 6–8 项（第 5 项已随 L8 落实） | 收益太小，或者无法在容器里可靠测量（见 03-perf-plan） |
| 阶段 6 第 3 项没有达到 20% | 3 种方案都没有达到，热缓存下的瓶颈是线程 / GIL 争用；保留了 −9% 的版本，未回退 |
| 端到端浏览器脚本 | 只在会话中用 Chromium 跑过，没有提交到仓库：仓库没有 e2e 测试的基础设施 |

## 四、待人工确认

**需要你做决定的：**

| 编号 | 问题 | 需要做什么 |
|---|---|---|
| **Q1** | 在 U 盘、SD 卡、网络共享上删除时，send2trash 2.1.0 在没有 pywin32 的情况下会走 legacy 路径。它使用的标志位 `FOF_ALLOWUNDO\|FOF_NOCONFIRMATION\|FOF_SILENT` 没有包含 `FOF_WANTNUKEWARNING`，文件**可能被静默永久删除**，这与 README 中「永远不会误删」的承诺相反 | 在 Windows 上用 U 盘实测。如果确认会永久删除，可以加依赖 `pywin32; sys_platform == "win32"`（modern 路径遇到无法回收的文件会返回 `E_FAIL`），或者在删除前拒绝不支持回收站的卷 |
| pHash 缩小解码 | 相似扫描每张约快 25 倍，但哈希值和分组结果会变 | 用一批真实照片对比分组差异，再决定是否采用 |
| M11 防护范围 | 只校验 Host 和 Origin，能挡住浏览器发起的攻击；没有会话令牌，也没有限制可扫描的目录，本机其他程序仍能调用接口 | 决定这个范围是否足够（加令牌要改前后端接口） |
| L12 | 见「三、跳过项」 | 接受现状，或以后专门做按句柄删除 |
| L7 | 没有取消扫描按钮 | 决定是否加 |
| L15 | 接口文档页面仍然开着 | 决定是否关闭（`FastAPI(docs_url=None, redoc_url=None, openapi_url=None)`） |
| Q2 | `Delete` 键本来的设计意图是「焦点组」还是「屏幕顶部的组」？H4 的修复按 README 的「当前组」理解为焦点组，并保留了滚动场景的退路 | 确认交互意图 |
| Q3 | 扫描根目录内有指向根目录外的 junction 时，外部的结果会显示出来，但所有接口都返回 403。L5 只在文档中写明了这一点 | 决定是跳过这类 junction，还是在界面上说明 |
| 交互改动 | M6：切标签或换目录时提前提交暂存的删除（而不是撤销）；L9：撤销窗口内连续清理会合并成一批，一次 Ctrl+Z 全部恢复；L8：删除后焦点留在原位 | 确认符合预期 |

**需要在 Windows 上实测的：**

| 编号 | 现状 | 需要做什么 |
|---|---|---|
| H2 | 修复在容器里是模拟验证的，没有在 Windows 上打包运行过 | 运行 `pyinstaller -F -w --name PhotoCleaner --add-data "web;web" main.py`，双击生成的 EXE，确认能正常启动 |
| M11 | 在 Chromium 中实测过：应用页面同源 POST 带的 `Origin` 与 `http://<Host>` 一致，所以能通过校验 | 在打包版（WebView2）中走一遍扫描和删除。如果出现 403，看日志中的 `Rejected request with Host … Origin …` |
| M3 | 用合成的 JPEG 和 HEIC 验证过 | 用手机竖拍的真实照片（JPEG 和 HEIC）看一下缩略图方向 |
| M7 | 预算 1.92 亿像素（约 0.8 GB）是估算值 | 扫描含全景图或大 TIFF 的目录，观察内存峰值和速度，必要时调整 `DECODE_PIXEL_BUDGET` |
| M8 | Linux 上每个文件约 1.35 µs；Windows 的 `os.stat` 慢得多 | 在结果很多（上万张）的目录上，看扫描结束阶段是否明显变慢。如果变慢，可以改用枚举阶段 `DirEntry.stat()` 的数据（见 03-perf-plan「第二轮」） |
| L10 | 提交中的 Undo 按钮通过 `style.display = 'none'` 隐藏 | 在 WebView2 中确认提交过程中 Undo 按钮会消失 |
| L13 | `requirements.lock` 是在 Linux、Python 3.13 上生成的 | 运行 `pip install -r requirements.txt -c requirements.lock`；如果 Python 版本较旧导致装不上，在 Windows 环境中重新生成 |
| Q5 | 焦点为 -1 时，Space 和 Enter 没有 `preventDefault`，可能触发按钮的默认点击 | 在 WebView2 上实测 |

**可以顺手处理的：**

| 编号 | 问题 | 需要做什么 |
|---|---|---|
| Q4 | 缩略图缓存失效测试依赖纯色 JPEG 的大小或 mtime 发生变化，可能偶发失败 | 换成内容不同、大小也不同的图片 |
| `Start_PhotoCleaner.bat` | 写死了作者本机的 conda 路径 | 只在作者电脑上可用，属于信息性问题 |

## 五、建议下一步（按优先级）

1. **在 Windows 上打包并启动 EXE**：验证 H2，顺便走一遍上面「需要在 Windows 上实测的」各项。
2. **Q1**：目前唯一可能造成不可恢复数据丢失的问题。先用 U 盘实测，再决定是加 pywin32，还是检查卷类型。
3. **做几个小决定**：L15（改一行）、L7 取消按钮、Q2、Q3、M11 是否加令牌；Q4 的测试可以顺手改掉。
4. **评估 pHash 缩小解码**：用一批真实照片对比 `draft()` 前后的分组差异。如果可以接受，相似扫描能提速一个数量级；必要时重新调整阈值。
5. **收尾**：`claude/review-fixes`、`claude/medium-fixes`、`claude/low-fixes`、三个 `claude/perf-*` 分支和 `claude/trusting-dijkstra-fpy2hd` 的内容都已进入 `main`，可以删除。本地仓库需要 `git pull` 才能拿到最新的 `main`。
