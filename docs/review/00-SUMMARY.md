# 00 · 审查与优化总结

按 [RUNBOOK.md](RUNBOOK.md) 执行了阶段 0 到阶段 7，全部完成，没有跳过任何阶段。审查基准是 `main` @ `c8a8e5c`。
逐步记录和决策见 [PROGRESS.md](PROGRESS.md)。全程没有推送 `main`，没有 force push，没有合并任何 PR，也没有删除远端分支。

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
| [#7](https://github.com/OranngeAustin/photo-cleaner/pull/7) | `claude/perf-parallel` → `claude/review-fixes` | 并行调度改用完成队列（未达到目标，可以直接关闭） |

建议的合并顺序：先在 `claude/review-fixes` 上审阅并合并 #5、#6，再决定 #7 是否合并；最后合并 #4。#4 会自动带上已经合进 `claude/review-fixes` 的内容。

## 三、跳过项及原因

RUNBOOK 中的阶段和子任务都没有跳过，但有以下几处是刻意没有做的：

| 项目 | 原因 |
|---|---|
| 中、低级别问题（M1–M11、L1–L15） | 阶段 4 按规则只修「高」级别且有把握的问题 |
| Q1：在没有回收站的磁盘上可能被永久删除（建议定级为高） | 在 Linux 容器里无法验证 Windows 回收站的行为；修复需要 Windows 专用代码，或者新增 pywin32 依赖 |
| 既有失败测试 `test_scan_directory_symlink_cycle` | RUNBOOK 规定「已有的失败测试只记录、不修」 |
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
| PR #7 | 收益约 9%，未达到目标 | 决定合并还是关闭 |

## 五、建议下一步（按优先级）

1. **先确认 Q1**：这是剩下唯一可能造成不可恢复数据丢失的问题。确认后再决定是加 pywin32，还是检查卷类型。
2. **在 Windows 上打包并启动 EXE**，验证 H2；顺便手工走一遍 H3、H4 的场景。
3. **审阅并合并 PR #5、#6，决定 #7 的去留，最后合并 #4**。
4. **修复 M11（DNS 重绑定）**：加 `TrustedHostMiddleware(["127.0.0.1", "localhost"])`；启动时生成随机令牌，通过 `js_api` 交给前端，后端校验每个请求；同时关闭 `/docs`（L15）。改动小，收益明确。
5. **快速修复几个功能问题**：M2（EXIF 拍摄时间要读 Exif 子 IFD）、M3（缩略图按 EXIF 方向旋转）、M4 和 M5（切换标签或删除后键盘焦点失效）、L6（进度栏的隐藏计时器）。每项都只是几行代码加一条测试。
6. **评估 pHash 缩小解码**：用一批真实照片对比 `draft()` 前后的分组差异。如果可以接受，相似扫描能提速一个数量级；必要时重新调阈值。
7. **工程化**：锁定依赖版本（L13）；加 CI，跑 pytest、node 测试和 pip-audit；把 `test_scan_directory_symlink_cycle` 改成跨平台写法（用 `os.symlink`，或在非 Windows 上 skip），并断言每个文件只枚举一次。
8. **补测试覆盖**（M10）：64 KiB 边界、哈希中途取消、`done` 回调抛异常、「全部去重」的正向路径、3 秒计时器到期自动提交。
