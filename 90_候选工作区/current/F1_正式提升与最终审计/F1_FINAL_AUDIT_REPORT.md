# 路径 F 正式提升与最终审计报告

审计日期：2026-08-29

实现与干净复演裁决：

`F1_IMPLEMENTATION_AND_CLEAN_REPLAY_PASS__STOP_AT_F1_FINAL_PRO_REVIEW`

正式高保真总状态保持：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

这个 PASS 仅表示用户明确批准的 T/A/S/R 正式提升、实现级验证、受限理想模型数值复演、发布边界和 Git 闭包已完成。它不授予高保真数值资格、接触或动力学资格、装置物理验证或实验验证。

## 1. 授权、基线与提交链

用户原话为“我明确选择并批准路径F，去工作吧。”。本轮严格解释为同时授权 T、A、S、R 四批正式目标，不包含 `02_模拟程序/README.md`、M 类插值工件、E 类实验清单、P3–P3R5 接触包或任何新科学阶段。

绑定提交链为：

- 提升前基线：`3ea4892ab56b47d9aa6d61bc717bc242717c76be`；
- T/A/S/R 正式提升：`d29f4392debd8fb39abb0cd0781d7ba5849d7369`；
- A installed-wheel 失败关闭修正与证据重建：`fed0fa621e1133a2787cf75dce71fef5c9a77500`。

F1 manifest 精确包含 60 个正式目标：T=1、A=17、S=41、R=1。清单 SHA-256 为 `dff7c4ed9a04923cefa4cf90ad814f5a50e0e5d9ae8776a83ce81b049072c99d`，`--check` 通过，60 项的当前字节数和 SHA-256 全部匹配。

## 2. 正式变更闭包

### 2.1 T：结构性理论

正式目标 `01_最终理论/03-结构性理论.md` 从 `3c932edf50a5fdee8df3c685b9f0c098fa190b279969c750fd3ca516bf3002e3` 变为 `235666d7e7d1e23a4c4785e1b9721e1538f75ba9af24ed5e207e4ead77d77bdb`，与冻结 F1 正式稿逐字节一致。

同目标补丁 SHA-256 为 `0be7071c350736075f011e47b2334a4fabce87ca303f2508461464d76a98f333`。从 `3ea4892` 导出的临时树执行 zero-fuzz dry-run 和实际应用均通过，应用结果与 F1 稿和正式目标逐字节相等。修正只包含：

- 在来源受限状态段与 `---` 之间恢复空行，防止 Pandoc 误解为 Setext H2；
- 把 P9 标题的“目标 HF 配置”改为“目标配置”，只澄清来源层级。

方程和数值数组不变。系统 Pandoc 3.1.3 与 Zettlr 随附 Pandoc 3.10.1 得到相同 AST：87 headers（H1=1、H2=19、H3=67）、20 horizontal rules、339 math nodes 和 9 tables。F1 验证证据 SHA-256 为 `e4e6a17b34e6238100b2e81ab8cb47abdc9a6d1cd7fabcb6f0ca15b41f7e17de`，临时重生与提交版逐字节一致。

### 2.2 A：理想环面参数—图样图谱

新增正式目录 `02_模拟程序/03_结构性理论分析程序/pattern_atlas/**`，精确 17 个文件，正式身份为 `YPS-IDEAL-TORUS-PATTERN-ATLAS-1.1`。它只消费正式 `FWD-TORUS-1.0` 后端，生产源中没有第二套 ODE、RHS 或积分器。

冻结运行环境为 CPython 3.12.3、jsonschema 4.10.3、Matplotlib 3.8.4、NumPy 1.26.4 和 SciPy 1.11.4。源锁 SHA-256 为 `427bbc7d3d55a5ceaeadba3df58f74b13efb2c92a697900ea4fbf63bede1f2b8`，绑定 15 项正式来源，候选路径为 0，源 manifest SHA-256 为 `4f09859be7e5e6c4a0422f9f82b9da2728891c67e13779e4155c171ee9778a58`。

干净环境实测为 `20 passed`，Ruff lint、compileall、四个 Draft 2020-12 schema 自校验和源锁 `--check` 通过。三次串行、相互隔离的完整复算均为 16 cases、48 primary trajectories 和 9 artifacts；四类聚合门全部为 true，16 个调谐器状态均为 `CONVERGED`。三次的 9 个工件逐文件、逐字节完全一致，验证 JSON SHA-256 为 `28683aa78759be4f5628f5e618de5fa17eff6dc37510dfa0d9e1f7a07eb2db08`。

A 明确为 repository-checkout-only，不是 standalone wheel。真实 PEP 517 wheel 可构建、安装、import、显示 help 且 `pip check` 通过；从 checkout 外实际运行 CLI，无论是否显式传入真实 `--repository-root`，都在读取配置和写入输出前以 exit 2 失败关闭，stderr 明确含 `repository-bound`、checkout 和 installed-wheel unsupported，没有 traceback 或裸 schema 路径，没有生成输出。

### 2.3 S：离散杆—刚体无接触静态参考模型

新增正式目录 `02_模拟程序/04_离散杆刚体无接触静态参考模型/**`，精确 41 个文件、20 个生产 Python 源。正式身份为 `YPS-NO-CONTACT-STATIC-REFERENCE-1.1`，发布状态为 `FORMAL_RELEASE_STATIC_REFERENCE_ONLY`，结论上限为 `FORMAL_STATIC_REFERENCE_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY`，明确保留 `NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED`。

current 环境为 NumPy 2.5.2、SciPy 1.18.1、pytest 9.1.1、jsonschema 4.25.1；下界环境为 NumPy 1.26.4、SciPy 1.12.0、pytest 8.4.2、jsonschema 4.10.3。两个干净环境均为 `72 passed`，Ruff、compileall、wheel/sdist 构建、全新安装、import 和 `pip check` 均通过。

两环境的证据 SHA-256 分别为 `9d25936fccef4deca12bd8ca0c3ca3b83bcc144502162b772bbc9513be674981` 和 `5dc84c56541dd5847797a7f66e0c4f5dd40f43f840132430b4e28624aac9f95b`。除 `runtime` 和 `runtime_identity_sha256` 外的对象完全相同；26 项源 manifest、装配 token、种子和五项实现级独立诊断一致。BFGS 原始状态继续是 `status=2`、`success=false`，只作记录，不被改写为求解器 PASS 或数值资格。

### 2.4 R：RC1 冻结状态

新增 `02_模拟程序/02_第一性原理高保真模拟器/Y-Pendulum-Simulator-v1.0.0-rc1/STATUS.md`，SHA-256 为 `ae07d9e632fe446516309d865f88f57cf69e201b2337620224adceb9ae67b775`，43 行、1665 bytes。它只去除候选标题、候选前言和未授权尾段，其余状态正文逐行保留。

RC1 基线的 150 个 tracked 条目的模式、blob OID 和路径全部不变；唯一新增项是 `STATUS.md`。没有修改 RC1 物理、源码、配置、测试或历史工件。

## 3. F1 运行证据与干净复演

最终接受复演使用全新 clone：

`/tmp/yps_f1_final_accept_27hnOn3P/repo`

该 clone 的 `HEAD == origin/main == fed0fa621e1133a2787cf75dce71fef5c9a77500`。全新 CPython 3.12.3 venv 中安装冻结 A 运行依赖后，从头执行源锁、pytest、Ruff、compileall、schema、构建、wheel 负例和三次完整复算。

F1 runtime generator 从最终 A 三重复与 S 双环境原始证据重生三份审计 JSON，并与提交版逐字节一致：

- A 三重复审计：`8f548b4b2373059244e5a0946fda69850f8ef80ce3cc1d855b27c420dd2ecb0a`；
- S 双环境矩阵：`7ae30ca56769e82fa612c911a55b905f1aa72d3b1694ab50269873077d27dc33`；
- F1 master 状态：`d512031afd97fc8fec040726aa468f0bdedda0b97dea1029ddb470d86641c62a`。

复演完成后，该 clone 中 staged、unstaged、untracked、ignored residue、cache 目录和 `.pyc` 计数均为 0。

## 4. Markdown 与实际渲染

全部新增或实质修改的 Markdown 均通过系统 Pandoc 3.1.3 和 Zettlr 随附 Pandoc 3.10.1 的 `--from=markdown`。交叉兼容解析也使用 `--from=gfm` 完成，不作为数学渲染替代。仓库不存在 `tools/check_markdown_math.py`，因此该专用检查未执行。

正式理论、A README、S README 和 R STATUS 使用 Pandoc HTML、本地 MathJax 3.2.2、Chrome 151 和 Poppler 生成 A4 PDF 并栅格化检查：

- 理论 23 页，339/339 个数学容器，数学错误、浏览器错误和文档水平溢出均为 0；
- A README 3 页，1/1 个数学容器，错误和溢出为 0；
- S README 3 页，错误和溢出为 0；
- R STATUS 1 页，错误和溢出为 0。

所有页面均完成逐页或联络表视觉检查，未见中文缺字、标题层级异常、表格或公式裁切、长状态串溢出或图像丢失。PDF、HTML 和页面 PNG 只作临时 QA，不进入正式包或 Git。

## 5. Git 范围与排除项

`3ea4892..fed0fa6` 的实现范围仍为 74 个路径：60 个正式目标加 14 个 F1 审计文件。`d29f439..fed0fa6` 只包含 9 个 A/F1 失败关闭修正与证据文件。T、R、S 在这个修正提交中的 Git 对象完全不变。

原始 `git diff --check 3ea4892..fed0fa6` 的唯一报告来自两个 unified-patch-as-data 文件对空上下文行所必需的单空格前缀，以及冻结 R STATUS 的终端空行。排除这三个已逐字节审计路径后，`git diff --check` 通过；60 个正式文件本体中没有 tab 或 trailing spaces。

明确排除：

- A 的全部候选 `outputs/**`；
- S 的 `outputs/**`、`runtime_matrix.json`、`migration_provenance.json` 和一次性迁移生成器；
- 缓存、字节码、build、dist 和 egg-info；
- M/E、P3–P3R5、动力学、动态接触、RC1 扩展、物理和实验工件。

`02_模拟程序/README.md` 保持基线 SHA-256 `a04cc5269a1165e2f5f815b8da2476335f6d554bfb66f2f505da2310f6958164`，未修改。F1 区只保存一份同目标补丁，状态为 `NOT_APPLIED_PENDING_SEPARATE_AUTHORIZATION`。

## 6. 失败、纠偏与非阻断边界

本轮没有隐藏失败：

- Matplotlib 3.6.3 在 CPython 3.12 环境预检中因无可用 wheel 且缺少 `Python.h` 而停止，发生在结果运行前；随后冻结为可安装的 3.8.4。
- A 首次完整 pytest 在文件尚未冻结时为 3 failed / 14 passed：两项源锁漂移和一项未到达预期层级的负例。冻结文件、重生锁并把负例改为 schema 合法的 `3.12.999` 后，先达到 19 passed，才启动结果运行。
- `d29f439` 的干净包装复演发现 installed wheel 实际运行会暴露裸 `FileNotFoundError`。这被视为正式发布质量阻断，在 `fed0fa6` 中修正，随后重建源锁、全部 A 数值证据和 F1 审计证据。修正前的 A 三重复不作最终接受证据。

Ruff lint 通过；额外执行的 `ruff format --check` 会对 A 的 5 个文件建议纯排版重排。该命令不是冻结验收门，本轮不为格式重排而再改写已绑定源锁和数值证据。

A/S 的 wheel/sdist 两次构建成员集与成员内容一致，但归档整体因 ZIP/tar/gzip 时间元数据不是逐字节可重现。本轮没有声称构建归档 byte-reproducible。sdist 只作可重建 wheel 的源归档，不声称自带完整、独立的测试复演闭包。

## 7. 未执行项与停止门

本轮未执行：

- RC1 重新资格化、扩展或新轨迹运行；
- 连续柔索等价性证明或新高保真空间/时间收敛；
- P3R6、G3R5、P4/P5/P6、接触、摩擦、动力学或动态接触；
- 装置参数标定、物理验证或实验验证；
- 远端 CI；仓库没有 `.github/workflows/**`，因此不把本地干净复演写成 CI PASS；
- Zettlr GUI 截图验收；本轮已使用 Zettlr 实际随附的 Pandoc reader，但没有打开 GUI。

当前唯一合法下一步是独立 `F1_FINAL_PRO_REVIEW`。本轮到此停止；不自动应用待授权索引补丁，不自动进入实验、新理论、新模拟或资格阶段。
