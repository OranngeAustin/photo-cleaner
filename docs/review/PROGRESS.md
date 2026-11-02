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
| 6 | 算法优化（前 3 项，各自 `claude/perf-*` 分支 + PR → review-fixes） | 🔄 进行中 | 6.1 聚类 ✅ [PR #5](https://github.com/OranngeAustin/photo-cleaner/pull/5)（−69%）；6.2 结果路径白名单 ✅ [PR #6](https://github.com/OranngeAustin/photo-cleaner/pull/6)（−58%）；6.3 并行调度 ⬜ |
| 7 | 总结 → `00-SUMMARY.md` | ⬜ 未开始 | |

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
