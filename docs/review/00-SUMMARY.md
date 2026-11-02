# 00 · 审查与优化总结

本文件记录两轮工作，逐步记录和决策都在 [PROGRESS.md](PROGRESS.md)：

- **第二轮（最新）**：修复中风险问题 M1–M11。代码在 `claude/medium-fixes`，[PR #8](https://github.com/OranngeAustin/photo-cleaner/pull/8) → `claude/review-fixes`（未合并）。见下一节。
- **第一轮**：按 [RUNBOOK.md](RUNBOOK.md) 完成阶段 0–7，包括审查、H1–H4 修复和 3 项性能优化，审查基准是 `main` @ `c8a8e5c`。见「一」到「五」。

两轮执行期间都没有推送 `main`、没有 force push、没有合并任何 PR、没有删除远端分支。第一轮结束后，#5–#7 是按用户的明确要求合并的。

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
- 低风险问题中，除了 L14（已解决）和 L1（已缓解），其余都没有处理。
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

| PR | 分支 → 目标 | 内容 |
|---|---|---|
| [#4](https://github.com/OranngeAustin/photo-cleaner/pull/4) | `claude/review-fixes` → `main` | 审查文档、H1–H4 修复、基准脚本，以及测试基线文档的更新 |
| [#5](https://github.com/OranngeAustin/photo-cleaner/pull/5) | `claude/perf-cluster` → `claude/review-fixes` | 相似聚类提速 |
| [#6](https://github.com/OranngeAustin/photo-cleaner/pull/6) | `claude/perf-result-keys` → `claude/review-fixes` | 结果白名单按目录缓存 realpath |
| [#7](https://github.com/OranngeAustin/photo-cleaner/pull/7) | `claude/perf-parallel` → `claude/review-fixes` | 并行调度改用完成队列（未达到目标；用户决定保留，已合并） |
| [#8](https://github.com/OranngeAustin/photo-cleaner/pull/8) | `claude/medium-fixes` → `claude/review-fixes` | **第二轮**：修复 M1–M11，附测试；未合并 |

**更新**：按用户要求，#5、#6、#7 已合并进 `claude/review-fixes`；Q1 暂不处理。#4 现在已经包含这三项优化，仍处于打开状态，等待审阅后合并到 `main`。

## 三、跳过项及原因

RUNBOOK 中的阶段和子任务都没有跳过，但有以下几处是刻意没有做的：

| 项目 | 原因 |
|---|---|
| 中、低级别问题（M1–M11、L1–L15） | 第一轮阶段 4 按规则只修「高」级别。**M1–M11 已在第二轮修复（PR #8）**；低级别问题中，L14 已解决，L1 已缓解，其余仍未处理 |
| Q1：在没有回收站的磁盘上可能被永久删除（建议定级为高） | 在 Linux 容器里无法验证 Windows 回收站的行为；修复需要 Windows 专用代码，或者新增 pywin32 依赖 |
| 既有失败测试 `test_scan_directory_symlink_cycle` | 第一轮按 RUNBOOK 只记录、不修；第二轮作为 M9 修复，在非 Windows 上改为跳过 |
| 性能第 4 项：pHash 用 JPEG `draft()` 缩小解码（单张约快 25×） | 会改变 pHash 数值，进而改变分组结果，无法用特征测试固定行为，属于产品决策 |
| 性能第 5–8 项 | 收益不确定、收益太小，或者无法在容器里可靠测量（见 03-perf-plan） |
| 阶段 6 第 3 项没有达到 20% | 3 种方案都没有达到，热缓存下的瓶颈是线程 / GIL 争用；保留了 −9% 的版本，未回退 |

## 四、待人工确认

| 编号 | 问题 | 需要做什么 |
|---|---|---|
| **Q1** | 在 U 盘、SD 卡、网络共享上删除时，send2trash 2.1.0 在没有 pywin32 的情况下会走 legacy 路径。它使用的标志位 `FOF_ALLOWUNDO\|FOF_NOCONFIRMATION\|FOF_SILENT` 没有包含 `FOF_WANTNUKEWARNING`，文件**可能被静默永久删除**，这与 README 中「永远不会误删」的承诺相反 | 在 Windows 上用 U 盘实测。如果确认会永久删除，可以加依赖 `pywin32; sys_platform == "win32"`（modern 路径遇到无法回收的文件会返回 `E_FAIL`），或者在删除前拒绝不支持回收站的卷 |
| H2 验证 | 修复在容器里是模拟验证的，没有在 Windows 上打包运行过 | 运行 `pyinstaller -F -w --name PhotoCleaner --add-data "web;web" main.py`，双击生成的 EXE，确认能正常启动 |
| Q2 | `Delete` 键本来的设计意图是「焦点组」还是「屏幕顶部的组」？H4 的修复按 README 的「当前组」理解为焦点组，并保留了滚动场景的退路 | 确认交互意图 |
| Q3 | 扫描根目录内有指向根目录外的 junction 时，外部的结果会显示出来，但所有接口都返回 403 | 决定是跳过这类 junction，还是在界面上说明 |
| Q4 | 缩略图缓存失效测试依赖纯色 JPEG 的大小或 mtime 发生变化，可能偶发失败 | 换成内容不同、大小也不同的图片 |
| Q5 | 焦点为 -1 时，Space 和 Enter 没有 `preventDefault`，可能触发按钮的默认点击 | 在 WebView2 上实测 |
| PR #7 | 收益约 9%，未达到目标 | 用户决定保留，已合并 |
| 第二轮 · M11 | 在 Chromium 中实测过：应用页面同源 POST 带的 `Origin` 与 `http://<Host>` 一致，所以能通过校验 | 在 Windows 打包版（WebView2）中走一遍扫描和删除。如果出现 403，看日志中的 `Rejected request with Host … Origin …` |
| 第二轮 · M3 | 用合成的 JPEG 和 HEIC 验证过 | 用手机竖拍的真实照片（JPEG 和 HEIC）看一下缩略图方向 |
| 第二轮 · M7 | 预算 1.92 亿像素（约 0.8 GB）是估算值 | 扫描含全景图或大 TIFF 的目录，观察内存峰值和速度，必要时调整 `DECODE_PIXEL_BUDGET` |
| 第二轮 · M8 | Linux 上每个文件约 1.35 µs；Windows 的 `os.stat` 慢得多 | 在结果很多（上万张）的目录上，看扫描结束阶段是否明显变慢。如果变慢，可以改用枚举阶段 `DirEntry.stat()` 的数据（见 03-perf-plan「第二轮」） |
| 第二轮 · M6 | 切标签或换目录时，会提前提交暂存的删除 | 确认这个交互符合预期（另一个选择是撤销） |

## 五、建议下一步（按优先级）

1. **审阅 [PR #8](https://github.com/OranngeAustin/photo-cleaner/pull/8)，合并到 `claude/review-fixes`；然后审阅 [PR #4](https://github.com/OranngeAustin/photo-cleaner/pull/4)，合并到 `main`。**
   #4 会自动带上 #5–#8 的全部内容。
2. **在 Windows 上打包，启动 EXE**：验证 H2；顺便手动走一遍「待人工确认」里第二轮的 5 项（M11、M3、M7、M8、M6）。
3. **Q1（用户决定暂不处理）**：这是目前唯一可能造成不可恢复数据丢失的问题。以后处理时，再决定是加 pywin32，还是检查卷类型。
4. **低风险问题中值得顺手修的几项**：
   - L3：`done` 回调第二次抛异常时，`active_scanner` 不会复位，之后所有扫描都返回 409。
   - L6：进度栏的隐藏计时器。
   - L7：轮询失败一次就解锁界面。
   - L10：Toast 的状态不对。
   - L2：失败的缩略图也会被缓存。

   每项都只是几行代码加一条测试。L15（关闭 `/docs`）在 M11 之后已经没有实际风险，可以顺手做。
5. **评估 pHash 缩小解码**：用一批真实照片对比 `draft()` 前后的分组差异。如果可以接受，相似扫描能提速一个数量级；必要时重新调整阈值。
6. **工程化**：
   - 锁定依赖版本（L13）；
   - 加 CI，跑 pytest、node 测试和 pip-audit；
   - 如果需要，把 scratchpad 里的 Chromium 端到端脚本整理进仓库，作为可选测试。
