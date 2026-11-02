# 审查与优化进度（PROGRESS）

执行手册：[RUNBOOK.md](RUNBOOK.md)　工作分支：`claude/review-fixes`（从 `main` @ `c8a8e5c` 创建）

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
| L1 | ✅ 已修复 |  | M8 已把扫描结束时的 realpath/stat 移到锁外；本项补上删除路径中锁内的 `_path_key`，并加测试：整个扫描 + 删除过程中，`realpath` 都不在持锁时调用 |
| L2 | ✅ 已修复 |  | 缓存函数不再吞掉异常（`lru_cache` 不缓存异常），由外层 `generate_thumbnail` 捕获并返回空结果；下次请求会重新生成 |
| L3 | ✅ 已修复 |  | `_finish` 捕获并记录回调异常，`done` 只发一次；`main.py` 的扫描线程入口用 `finally` 兜底：任务仍未复位就释放 `active_scanner` 并报告扫描失败 |
| L4 | ✅ 已修复 |  | `_iter_parallel_results` 用 `try/finally` 取消所有排队中的任务，取消、消费方异常、提前关闭生成器三种情况都覆盖 |
| L5 | ✅ 已修复（文档） |  | 按建议的第一种做法在 CLAUDE.md 和代码注释中写明：联接点会被遍历，指向扫描根之外的结果能看到但无法预览和删除。是否跳过这类联接点仍等待 Q3 决定，扫描行为未改 |
| L6 | ✅ 已修复 |  | 扫描结束提示与 `showScanError` 共用 `hideStatusBarLater()`，到点时如果新的扫描正在进行就不隐藏进度栏 |
| L7 | ✅ 部分修复 |  | 状态轮询失败后按 0.5/1/2/4 秒退避重试，连续 5 次失败才放弃；放弃时顺带 `POST /api/cancel_scan`，避免后端继续扫描、下一次扫描返回 409。**未加取消按钮**：属于新增界面功能，留给人工决定（R3-D2） |
| L8 | ✅ 已修复 |  | 提交删除后焦点留在原来那张照片所在的组（组被删掉时落到下一个仍在列表中的组），不再跳回第 0 组；后端删除后不再清空缩略图缓存（键已包含 size 和 mtime）。整表重新渲染保留，改成增量更新风险更大 |
| L9 | ⬜ 待处理 | | |
| L10 | ⬜ 待处理 | | |
| L11 | ✅ 已修复（部分不成立） |  | 删除未使用的 `activeCountdownId`、`countdownInterval`，删除从不读取的 `pendingDeletion.type`，删除无效规则 `.group-row.focused`；`triggerClean` 和批量清理改为共用 `stageDeletion`。**两处已不成立、未改**：`scrollContainer` 现在被 H4 的修复使用；`.lightbox img.zoomed` 有效（`setZoom` 会给图片加 `zoomed`） |
| L12 | ⬜ 待处理 | | |
| L13 | ⬜ 待处理 | | |

### 第三轮决策记录

- **R3-D1 记录位置**：第三轮的进度写在阶段清单之后，而不是文件末尾。第二轮的记录只在 `claude/review-fixes` 上，
  追加在文件末尾；本分支基于 `claude/medium-fixes`，如果也追加到末尾，两条分支合并时会在同一位置冲突。
- **R3-D2 L7 不加取消按钮**：02-findings 建议「有限次重试并退避；提供取消按钮」。重试和放弃时自动取消后端扫描
  已经解决了「结果被丢弃、再次扫描返回 409」；取消按钮要改 HTML、样式和交互，属于新功能，不在低风险修复范围内。

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
