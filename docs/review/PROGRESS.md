# 审查与优化进度（PROGRESS）

执行手册：[RUNBOOK.md](RUNBOOK.md)　工作分支：`claude/review-fixes`（从 `main` @ `c8a8e5c` 创建）

> 第二轮（修复中风险 M1–M11）的进度见文末[「第二轮」](#第二轮修复中风险-m1m11)。

## 阶段清单

| 阶段 | 内容 | 状态 | 备注 |
|---|---|---|---|
| 0 | 准备：依赖、基线测试、分支、进度文件 | ✅ 完成 | 基线见下 |
| 1 | 架构摸底 → `01-architecture.md` | ✅ 完成 | 审查顺序：main.py → web/ → backend/ → tests/ → 根配置 → docs/.claude |
| 2 | 代码审查 → `02-findings.md` | ✅ 完成 | 高 4（H1–H4）、中 10、低 13、待人工确认 5 |
| 3 | 安全审计 → `02-findings.md`「安全」 | ✅ 完成 | 新增 M11（DNS 重绑定）、L14、L15；注入/反序列化/密钥：无；pip-audit：无已知漏洞 |
| 4 | 修复高危问题 + PR → main | ✅ 完成 | H1–H4 已修复（各 1 commit + 回归测试），[PR #4](https://github.com/OranngeAustin/photo-cleaner/pull/4) → main；Python 21✓/1✗（既有）、Node 23✓ |
| 5 | 性能分析 → `03-perf-plan.md` | ✅ 完成 | 新增 `benchmarks/bench_scanner.py`；选中：聚类、结果路径白名单、并行调度 |
| 6 | 算法优化（前 3 项，各自 `claude/perf-*` 分支 + PR → review-fixes） | ✅ 完成 | 6.1 聚类 [PR #5](https://github.com/OranngeAustin/photo-cleaner/pull/5) −69%；6.2 结果路径白名单 [PR #6](https://github.com/OranngeAustin/photo-cleaner/pull/6) −58%；6.3 并行调度 [PR #7](https://github.com/OranngeAustin/photo-cleaner/pull/7) −9%（3 种方案均未达 20%，按规则保留最好的正确版本） |
| 7 | 总结 → `00-SUMMARY.md` | ✅ 完成 | 见 [00-SUMMARY.md](00-SUMMARY.md) |

## 第三轮：修复低风险 L1–L13（分支 `claude/low-fixes`）

从 `claude/medium-fixes` @ `b916739` 创建，PR 目标为 `claude/medium-fixes`。本轮只遵守 RUNBOOK 的「工作规则」：
每个问题一个 commit，提交信息引用编号；能写测试的先写测试，并确认修复前失败；每次修复后运行全部测试；
误报、纯风格偏好或修复风险过大的问题不改，标「⏭ 跳过」并写明原因。

基线（`b916739`）：Python 86 passed、1 skipped（Windows 联接点测试）；Node 32 passed。

| 编号 | 状态 | commit | 说明 |
|---|---|---|---|
| L1 | ✅ 已修复 | `d206e6f` | M8 已把扫描结束时的 realpath/stat 移到锁外；本项补上删除路径中锁内的 `_path_key`，并加测试：整个扫描 + 删除过程中，`realpath` 都不在持锁时调用 |
| L2 | ✅ 已修复 | `6bc63b2` | 缓存函数不再吞掉异常（`lru_cache` 不缓存异常），由外层 `generate_thumbnail` 捕获并返回空结果；下次请求会重新生成 |
| L3 | ✅ 已修复 | `d00772c` | `_finish` 捕获并记录回调异常，`done` 只发一次；`main.py` 的扫描线程入口用 `finally` 兜底：任务仍未复位就释放 `active_scanner` 并报告扫描失败 |
| L4 | ✅ 已修复 | `8e781bd` | `_iter_parallel_results` 用 `try/finally` 取消所有排队中的任务，取消、消费方异常、提前关闭生成器三种情况都覆盖 |
| L5 | ✅ 已修复（文档） | `271a3ab` | 按建议的第一种做法在 CLAUDE.md 和代码注释中写明：联接点会被遍历，指向扫描根之外的结果能看到但无法预览和删除。是否跳过这类联接点仍等待 Q3 决定，扫描行为未改 |
| L6 | ✅ 已修复 | `45c135a` | 扫描结束提示与 `showScanError` 共用 `hideStatusBarLater()`，到点时如果新的扫描正在进行就不隐藏进度栏 |
| L7 | ✅ 部分修复 | `9f2f0b2` | 状态轮询失败后按 0.5/1/2/4 秒退避重试，连续 5 次失败才放弃；放弃时顺带 `POST /api/cancel_scan`，避免后端继续扫描、下一次扫描返回 409。**未加取消按钮**：属于新增界面功能，留给人工决定（R3-D2） |
| L8 | ✅ 已修复 | `b963353` | 提交删除后焦点留在原来那张照片所在的组（组被删掉时落到下一个仍在列表中的组），不再跳回第 0 组；后端删除后不再清空缩略图缓存（键已包含 size 和 mtime）。整表重新渲染保留，改成增量更新风险更大 |
| L9 | ✅ 已修复 | `d36d670` | 采用「像相似页那样合并」：撤销窗口内的新清理动作并入待删除批次（路径和行去重，计时器重新计 3 秒），一次撤销全部恢复，焦点回到第一次清理前的位置；相似页批量清理统计待删除行时改为按行所属标签过滤 |
| L10 | ✅ 已修复 | `12bc399` | 开始提交时提示改为「正在移到回收站」并隐藏 Undo 按钮；部分失败和失败提示不带 Undo，5 秒后自动隐藏（被更新的提示替换时不隐藏） |
| L11 | ✅ 已修复（部分不成立） | `be9ea32` | 删除未使用的 `activeCountdownId`、`countdownInterval`，删除从不读取的 `pendingDeletion.type`，删除无效规则 `.group-row.focused`；`triggerClean` 和批量清理改为共用 `stageDeletion`。**两处已不成立、未改**：`scrollContainer` 现在被 H4 的修复使用；`.lightbox img.zoomed` 有效（`setZoom` 会给图片加 `zoomed`） |
| L12 | ⏭ 跳过 | `dc1a847` | 修复风险过大、收益很小：建议的 lstat 复核只能缩小窗口，不能关闭 TOCTOU（send2trash 只接受路径字符串）；彻底修复需要 Windows 专用的基于句柄的删除，见 R3-D3 |
| L13 | ✅ 已修复 | `bb91302` | 新增 `requirements.lock`（当前测试环境的完整依赖闭包，精确版本），作为 constraints 文件可选使用：`pip install -r requirements.txt -c requirements.lock`；`requirements.txt` 不变。新增测试保证锁文件覆盖每个直接依赖以及影响 pHash 的 NumPy/SciPy/PyWavelets |

### 第三轮决策记录

- **R3-D1 记录位置**：第三轮的进度写在阶段清单之后，而不是文件末尾。第二轮的记录只在 `claude/review-fixes` 上，
  追加在文件末尾；本分支基于 `claude/medium-fixes`，如果也追加到末尾，两条分支合并时会在同一位置冲突。
- **R3-D2 L7 不加取消按钮**：02-findings 建议「有限次重试并退避；提供取消按钮」。重试和放弃时自动取消后端扫描
  已经解决了「结果被丢弃、再次扫描返回 409」；取消按钮要改 HTML、样式和交互，属于新功能，不在低风险修复范围内。
- **R3-D3 L12 跳过**：建议的「删除前用 `lstat` 复核」只能缩小检查与使用之间的窗口，不能消除它：`send2trash`
  只接受路径字符串，Windows 上由 Shell 按路径重新解析。现在每个文件的检查（realpath、白名单、M8 的指纹 stat）
  与 `send2trash` 之间只隔几微秒，再加一次复核几乎没有收益。真正关闭这个 TOCTOU 需要改成基于句柄的删除
  （打开句柄、用 `GetFinalPathNameByHandle` 核对、再交给 `IFileOperation` 回收），是 Windows 专用的大改动，
  风险远大于收益。利用前提是攻击者对扫描目录有写权限且能精确卡住时机，后果是文件进回收站（可还原）。
- **R3-D4 L11 中已不成立的两项**：`scrollContainer` 在 H4 修复后已被使用；`.lightbox img.zoomed` 是有效规则
  （`setZoom` 会给预览图加 `zoomed`）。这两项按误报处理，未改。
- **R3-D5 先 L11 后 L9**：L9 的合并逻辑放在 L11 抽出的公共函数 `stageDeletion` 里，所以先提交 L11 的纯清理
  （不改行为），再提交 L9 的行为修改，两个 commit 各自只对应一个编号。

### 第三轮结束状态

- 11 项修复（其中 L7 部分修复、L11 有两项不成立），L5 只改文档，L12 跳过。
- 测试：Python 由 86 passed / 1 skipped 变为 **93 passed / 1 skipped**；Node 由 32 变为 **40 passed**。
  除 L5、L11、L12 外，每项都先写测试并确认修复前失败；没有修改或删除任何已有测试的断言。
- 分支 `claude/low-fixes` 已推送，PR 目标为 `claude/medium-fixes`。未推送 `main`，未 force push，未合并任何 PR，未删除分支。

## 阶段 0：基线

环境：Linux x86_64（云端容器，4 核），Python 3.13.18，Node v22.23.4。
依赖：`pip install -r requirements.txt pytest` 全部已满足（fastapi 0.162.0、starlette 1.7.0、
Pillow 12.3.0、pillow-heif 1.8.1、ImageHash 4.3.2、Send2Trash 2.1.0、pywebview 6.2.1、pytest 9.2.0）。

| 测试套件 | 命令 | 结果 |
|---|---|---|
| Python 后端 | `python -m pytest -q` | **18 passed, 1 failed**（19 个） |
| 前端 | `node --test tests/test_frontend.js` | **19 passed, 0 failed** |
| 基准测试 | — | 仓库中**没有**基准测试（阶段 5 新建） |

已有失败（只记录、不修）：

- `tests/test_scanner.py::test_scan_directory_symlink_cycle`：测试调用 `cmd /c mklink /J` 创建 Windows
  目录联接点，Linux 上没有 `cmd`，抛出 `FileNotFoundError`（测试只捕获了 `CalledProcessError`，所以没有
  被 skip）。属于平台相关的测试问题，与产品代码无关。

后续判定标准：Python 失败数 ≤ 1（且只能是上面这一条），前端失败数 = 0。

## 决策记录

- **D1 分支**：会话默认分配的分支是 `claude/trusting-dijkstra-fpy2hd`，但 RUNBOOK 和用户目标明确要求在
  `claude/review-fixes` 上工作并推送，因此所有审查文档与修复都提交到 `claude/review-fixes`；
  性能优化按 RUNBOOK 使用 `claude/perf-<名称>` 分支。不推送 main、不 force push、不合并 PR、不删分支。
- **D2 已有失败测试**：`test_scan_directory_symlink_cycle` 在 Linux 必然失败，按 RUNBOOK 只记录不修；
  它不计入「失败数增加」。
- **D3 审查方式**：阶段 2 用 3 个 `code-reviewer` 子代理按目录并行审查（main.py / web / backend+tests），
  主会话逐条核对；高级别全部用脚本或测试复现后才定级，无法在 Linux 容器里验证的（send2trash 在无回收站卷上的行为）
  放进「待人工确认」(Q1)，不进入阶段 4 修复。
- **D4 基准脚本**：仓库原本没有基准测试；`benchmarks/bench_scanner.py` 已在阶段 5 提交。
- **D5 安全定级**：DNS 重绑定（M11）机制已验证，但端口随机、需要先探测，定为「中」。按 RUNBOOK，阶段 4
  只修「高」，所以 M11 只给出修复建议，列入总结的下一步。
- **D6 阶段 4 范围**：只修 H1–H4。Q1（send2trash 在无回收站卷上可能永久删除）虽然建议定为高，
  但无法在 Linux 上验证，而且修复需要 Windows 专用代码或新增 pywin32 依赖，所以留给人工确认。
  H4 保留了「焦点不可见时清理容器内第一个可见行」的退路，让纯鼠标滚动的使用方式保持原有行为。
- **D7 测试断言写法**：H4 的测试比较行 id，而不是直接比较假 DOM 元素。原因是断言失败时，
  Node 会深度展开整张带循环引用的假 DOM 图来生成错误信息，进程会因此被 SIGKILL。
- **D8 pHash 缩小解码不进入阶段 6**：JPEG `draft()` 可让 pHash 单张提速约 25×，但会改变哈希值、进而改变分组结果；
  RUNBOOK 要求优化前先用特征测试固定输入输出，这项优化做不到。因此只写进 03-perf-plan 和总结，交给人工决策。
- **D9 聚类取消粒度**：取消检查从每个候选一次改为每个锚点一次，单线程下的确定性结果与原实现一致，并由特征测试固定。
  多线程下取消发生在锚点内部的时间点本来就不确定。最坏偏斜输入仍为 O(K²)，只拿到 1.46× 的提升，已在 PR 中如实说明。
- **D10 白名单优化保持精确语义**：去掉逐文件的 `islink` 检查还能更快，但符号链接文件的白名单键会从「链接目标」变成「链接所在位置」。
  虽然这样更严格，却改变了行为，所以没有采用。现在的做法是：遇到符号链接文件就回退到原来的逐条 `realpath`。
- **D11 并行调度的取舍**：一共试了 3 种方案。完成队列（采用）：−9%；批量补交：−8.5%～−13%，与前者的差别在测量噪声内；
  自建线程池原型：调度 −56%，但端到端只快 −3%。热缓存下真正的瓶颈是线程 / GIL 争用。提升在 5%～20% 之间，
  按 RUNBOOK 保留最好的正确版本，并在 PR #7 中明确写出「未达目标、可以直接关闭」。
- **D12 合并检查**：在本地临时分支上，把 3 个 perf 分支依次合并进 review-fixes，均无冲突；合并后 Python 56 项通过、1 项失败（已有问题），
  Node 23 项通过。临时分支只在本地，检查完已删除，没有推送。

## 结束状态

- 推送到远端的分支：`claude/review-fixes`、`claude/perf-cluster`、`claude/perf-result-keys`、`claude/perf-parallel`。
- RUNBOOK 执行期间：未推送 `main`，未 force push，未合并任何 PR，未删除任何远端分支。
- 执行结束后，用户明确要求合并 #5、#6、#7（Q1 暂不处理），这三个 PR 已合并进 `claude/review-fixes`，合并方式为 merge commit：
  #5 → `a425b7b`，#6 → `7096e77`，#7 → `c10cdb5`。合并后 Python 57 项（56 项通过，1 项为已有的失败），Node 23 项全部通过；
  README 和 CLAUDE.md 中的测试基线同步改为 Python 57 项。#4（→ `main`）仍处于打开状态，未合并。

---

## 第二轮：修复中风险 M1–M11

用户目标：从 `claude/review-fixes` 创建 `claude/medium-fixes`，修复 M1–M11，按 RUNBOOK 再走一遍阶段 0–7。
代码分支：`claude/medium-fixes`（从 `claude/review-fixes` @ `4db7895` 创建）；审查文档仍提交到 `claude/review-fixes`。

| 阶段 | 内容 | 状态 | 备注 |
|---|---|---|---|
| 0 | 准备：基线测试、基准、分支、清单 | ✅ 完成 | 见下方「第二轮基线」 |
| 1 | 架构摸底（增量复核 `01-architecture.md`） | ✅ 完成 | 合并 #5–#7 后模块划分、入口、数据流都没变；文档里没有失效的行号引用（只引用到函数级）。本轮新增的防护（Host/Origin 校验、删除前比对文件指纹、解码像素预算）在阶段 4 完成后补进架构文档 |
| 2 | 代码审查：在当前代码上复核 M1–M11 | ✅ 完成 | 11 项全部仍然存在。用脚本复现了 5 项：M1（大小过期的两个不同文件被判为重复）、M2（显示 2030 而不是 2024）、M3（缩略图 256×128）、M8（替换过内容的文件照样被删）、M11（`Host: attacker.example` 返回 200）。M7 没有任何像素量 / 并发保护（worker 8 个，`MAX_IMAGE_PIXELS` 为默认值）。M9 是基线里那条失败的测试。M4–M6 会在阶段 4 先写测试，确认测试在修复前失败 |
| 3 | 安全审计：复核 M11，重跑 pip-audit | ✅ 完成 | M11 已复现（伪造 Host/Origin 的 POST 返回 200）。`pip-audit 2.10.1 -r requirements.txt`：No known vulnerabilities found。本轮没有新增依赖 |
| 4 | 修复 M1–M11（每项 1 个 commit + 测试）+ PR → `claude/review-fixes` | ✅ 完成 | 11 项全部修复（M10 为补测试），[PR #8](https://github.com/OranngeAustin/photo-cleaner/pull/8) → `claude/review-fixes`（未合并）；Python 86✓/1 skip/0✗，Node 32✓ |
| 5 | 性能分析：修复前后基准对比 | ✅ 完成 | 新旧代码交错 A/B（3 轮 × 5 次）：只有 `exact` 有真实回归（+6.5%，来自 M1 每个文件多一次 `fstat`），其余在噪声内；M8 新增每个结果文件一次 stat（约 1.35 µs/个）。见 `03-perf-plan.md`「第二轮」 |
| 6 | 算法优化 | ✅ 完成 | 只有 1 项：消除 M1 的回归。先提交特征测试 `55257c8`，再提交修改 `ba8fc9b`（`fstat` → 多读 1 字节），1133 → 1081 ms，与修复前的 1064 ms 差在噪声内。直接提交在 `claude/medium-fixes` 上（R2-D10）；第一轮其余候选的结论不变 |
| 7 | 总结：更新 `00-SUMMARY.md` | ✅ 完成 | `00-SUMMARY.md` 文首新增「第二轮」一节，同步更新了 PR 列表、跳过项、待人工确认和下一步 |

### 第二轮基线（`claude/medium-fixes` @ `4db7895`）

| 测试套件 | 结果 |
|---|---|
| Python `python -m pytest -q` | **56 passed, 1 failed**（57 项；失败的是已有的 `test_scan_directory_symlink_cycle`，即 M9 本身） |
| 前端 `node --test tests/test_frontend.js` | **23 passed, 0 failed** |
| 基准 | `exact`、`phash`、`thumbnail`、`result_keys`、`parallel` 各 5 次取中位数，结果写在阶段 5 |

判定标准：Python 失败数不超过 1，且只能是上面那一条（修好 M9 后应为 0）；前端失败数为 0。

### 第二轮决策记录

- **R2-D1 分支与文档的分工**：代码和测试只提交到 `claude/medium-fixes`，审查文档（PROGRESS、02-findings、
  03-perf-plan、00-SUMMARY）只提交到 `claude/review-fixes`。两条分支不改同一个文件，以后合并 PR 时不会冲突；
  同时满足目标里「00-SUMMARY.md 在 `claude/review-fixes` 上」的要求。README 和 CLAUDE.md 里的测试基线随代码一起改，放在 `claude/medium-fixes`。
- **R2-D2 PR 目标分支**：RUNBOOK 阶段 4 写的是「创建指向 main 的 PR」，但 `claude/medium-fixes` 是从 `claude/review-fixes` 拉出来的，
  直接指向 `main` 会把 #4 的全部内容重复带进来。所以 PR 指向 `claude/review-fixes`，等 #4 合并后再一起进入 `main`。不合并任何 PR。

### 第二轮阶段 4：修复明细

每项修复都先写测试并确认它在修复前失败，再写修复；每个 commit 后都跑 Python 和 Node 两套测试。

| 编号 | commit | 修复 | 新增测试（修复前失败 → 修复后通过） |
|---|---|---|---|
| M1 | `e64cb8e` | 读前缀时在同一句柄上 `fstat`；大小与枚举时不一致的组改走全量哈希 | 1 |
| M2 | `62ad778` | 先读 Exif 子 IFD 的 36867/36868，再退回 IFD0；`DecompressionBombError` 返回「未记录」 | 2 |
| M3 | `2d65a24` | 先读 Orientation，只旋转已经缩小的缩略图；HEIC 解码时已经转正（已验证），不会旋转两次 | 1 |
| M4 | `6e32f29` | 切换标签时，焦点移到新标签的第一个可见组；按键处理加越界检查 | 1 |
| M5 | `acec284` | 暂存删除时焦点移到相邻可见组；撤销或删除失败后恢复原焦点（用户已移动焦点时不覆盖） | 3 |
| M6 | `f54fadd` | 切标签自动扫描、换目录之前，先等暂存的删除提交完成 | 2 |
| M7 | `aa46c62` | 解码像素预算（1.92 亿像素，超大图独占，等待中可取消）；缩略图先缩小再合成白底，JPEG 按 draft 后的尺寸计入预算 | 4 |
| M8 | `7473547` | 扫描结束时记录 `(size, mtime_ns)` 指纹，删除前比对；指纹在锁外计算 | 2 |
| M9 | `2125ded` | 原测试的平台检查补上 `OSError`，在 Linux 上跳过，并新增「只枚举一次」的断言；新增可移植的目录符号链接环测试 | 1（另有 1 条加强了断言） |
| M10 | `2d48fea` | 只补测试：Python 3 条、前端 3 条；变异检查确认它们能抓到问题 | 6 |
| M11 | `97c7200` | `LocalRequestGuard` 校验 Host 和 Origin；用真实 Chromium 做了端到端验证 | 10（参数化） |
| 文档 | `cd7c1cf`、`b916739` | README、CLAUDE.md：测试基线改为 Python 87 项（非 Windows 上跳过 1 项）、Node 32 项，并补充行为说明 | — |
| 阶段 6 | `55257c8`、`ba8fc9b` | 先提交前缀哈希的特征测试，再把 M1 的检测方式由 `fstat` 改为多读 1 字节 | 3 + 3（参数化） |

阶段 4 结束时的测试结果：**Python 80 passed、1 skipped、0 failed；Node 32 passed、0 failed**。阶段 6 结束后：Python 86 passed、1 skipped、0 failed；Node 32 passed。基线是 Python 56 项通过、1 项失败，Node 23 项通过；失败数从 1 降到 0。

- **R2-D6 M11 不采用会话令牌**：Host 和 Origin 校验已经能挡住所有由浏览器发起的攻击，包括 DNS 重绑定和跨站 POST。
  令牌只能额外防住本机其他进程，而本机进程本来就能以同一用户的身份直接读写这些照片，不在威胁模型内。
  令牌还要改前后端接口（通过 `js_api` 传给前端，所有请求都要带上），按 RUNBOOK「不改对外接口」不做。
  `/api/scan` 只接受 `choose_directory` 返回过的目录这项也没有做，原因相同。
  L15（`/docs` 未关闭）不在本次范围内；Host 校验之后，重绑定的攻击者也读不到它了。
- **R2-D7 M8 缺少指纹时放行**：生产环境中，白名单和指纹在同一处同时写入，所以每个白名单路径都有指纹；
  只有测试直接填写白名单时才会缺少指纹。为了不修改原有测试，这种情况不做比对。
  扫描结束时 stat 失败的文件记为 `None`，删除时一律拒绝。
- **R2-D8 M9 修改了已有测试**：用户明确要求修复 M9，而 M9 指出的就是这条测试本身的问题。
  只改了平台检查（`except` 补上 `OSError`，与原来「没有权限就跳过」的意图一致），新增了断言，原有断言一条没改，不属于「为了通过测试而修改断言」。
- **R2-D9 M10 中 `done` 回调异常的测试只断言不变量**：只断言异常不外泄、任务能正常结束。
  不锁定 L3 讨论的「第二次 done」细节，以免以后修复 L3 时要改这条测试。

- **R2-D3 M6 选择「提交」而不是「撤销」**：用户已经明确发起删除，离开当前视图应当视为确认。
  文件进的是回收站，仍可还原；撤销反而会让照片在新扫描结果里重新出现，而用户以为它们已经删了。
- **R2-D4 M4 不记忆每个标签各自的焦点**：切回标签时一律从第一个可见组开始。
  记忆焦点还要处理另一个标签删除后行号重新编号的问题，复杂度不值得。
- **R2-D5 M5 部分删除成功后的焦点不动**：列表重新渲染后焦点回到第 0 组，这是原有行为（L8），不在本次范围内。
- **R2-D10 阶段 6 的处理方式**：第二轮阶段 5 发现的唯一热点，是本轮 M1 修复自己引入的回归，而且只存在于尚未合并的 `claude/medium-fixes` 上。
  如果按 RUNBOOK 另开 `claude/perf-*` 分支，再建一个 PR 指向 PR 分支，合并顺序会变得复杂，所以直接提交在 `claude/medium-fixes` 上，随 PR #8 一起审阅。
  RUNBOOK 的其他步骤都照做了：先单独提交特征测试；每项 5 次取中位数，并与旧代码交错对比；修改后清理。
  这是「消除回归」，不是「优化」，所以不套用「提升 20% / 不足 5% 回退」的标准，衡量标准是不慢于修复前（+1.6%，在噪声内）。
  第一轮剩下的性能候选（pHash 缩小解码、删除后不清缩略图缓存等）结论不变，本轮不做。
- **R2-D11 真实浏览器验证**：前端单元测试用的是假 DOM，所以另外用 Chromium（WebView2 的内核）配合真实后端，跑了 M4–M6 和 M11 的端到端脚本，结果见 PR #8。
  脚本放在会话的 scratchpad 里，没有提交到仓库（仓库没有 e2e 基础设施，新增会引入 Playwright 依赖）。

### 第二轮结束状态

- 推送到远端的分支：`claude/medium-fixes`（代码和测试）、`claude/review-fixes`（审查文档）。
- 新建 [PR #8](https://github.com/OranngeAustin/photo-cleaner/pull/8)：`claude/medium-fixes` → `claude/review-fixes`，未合并。
- 未推送 `main`，未 force push，未合并任何 PR，未删除任何分支。本地的临时 worktree（用于 A/B 对比和文档提交）不是分支，用完即清理。
