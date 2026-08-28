# F0R 正式提升阻断项整改完成报告

## 1. 总结论

`F0R_FORMAL_PROMOTION_BLOCKER_CORRECTIONS` 的候选整改工件已经形成，并完成实现级、绑定级和规定数值复算验证。完成状态只表示候选工作区中的 F0R 交付闭合，不表示任何文件已经提升到正式目录。

本轮停止状态为：

`F0R_PRO_REVIEW`

正式高保真总状态保持：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P2 无接触静态历史结论上限保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

P3R5/G3R5 收口保持：

`G3R5_PRO_REVIEW_CONFIRMS_P3R5_TARGET_SUITE_NOT_ADMISSIBLE__G3R5_NOT_RUN__P3R5_CERTIFICATION_RETRY_PATH_CLOSED`

本轮没有修改 `01_最终理论/**`、`02_模拟程序/**` 或顶层 `AGENTS.md`；没有修改或重算 P3–P3R5 冻结证据；没有生成新接触资格卡，没有运行 G3R5，也没有开始 P3R6、P4、P5、P6、动力学或动态接触。

## 2. 授权、输入基线与结论边界

本轮按以下优先级执行：

1. 顶层 `AGENTS.md`；
2. F0R 开始时的 `90_候选工作区/交接说明_current.md`；
3. `PROJECT_WIDE_FORMAL_PROMOTION_REVIEW.md`；
4. `formal_promotion_matrix.json`。

旧 `HF-v2重构规划/plan_manifest.json` 只作历史快照，没有被用作当前执行指令。输入 Git 基线为 `main` 上的 `18a8a7055ddc70fd8a2b9898df0bb2b0d7368ca9`，开始时与 `origin/main` 相同且工作树干净。

F0R 只允许修改：

`90_候选工作区/current/F0_正式整理与解析稳定性图谱/**`

允许更新的交接文件只在全部交付与验证闭合后处理。一般的“继续”不构成正式目录写入授权。

## 3. 交付状态

| 编号 | 候选交付 | F0R 状态 | 结论上限 |
|---|---|---|---|
| T | 结构理论证据分级候选稿、同目标补丁、干净树应用证据 | 完成 | 候选勘误，不改变正式理论 |
| A | 严格合同、完整来源/运行时绑定、全量参数图谱及三重复核 | 完成 | 理想环面模型内部数值验证 |
| S | 静态-only 独立模型、窄 API、规范运行证据及双依赖单元 | 完成 | 候选静态实现与运行时证据 |
| M | 四点冻结观察与无外推描述性插值图 | 完成 | 四点证据加插值器性质 |
| G | 总报告、机器状态、迁移溯源和 92 条逐文件清单 | 完成 | 候选治理，不授予正式写入 |
| R | RC1 正式状态说明草案 | 保持 | 冻结参考和 NO-GO 状态说明 |
| E | 实验门最小测量清单 | 保持 | 测量合同，无实验数据 |

## 4. T：结构理论证据勘误

候选稿把理论证据统一分为五类：

- A：理想解析证据；
- NI：理想模型数值证据；
- C：配置直接量及其几何派生量；
- R：绑定于归档 RC1 候选轨迹的统计；
- E：必须由实验获得的结论。

R 类轨迹不再被写成已合格高保真模型中的机制证据。尤其是负有符号轴力、峰值弯曲能占比和保存样本守卫，都只按绑定归档轨迹解释；它们不能在 `HF_NUMERICAL_QUALIFICATION_NO_GO` 下判断高保真机制是否真实存在或失效，也不能替代连续时间守卫、空间收敛、装置验证或实验验证。

正式源 `01_最终理论/03-结构性理论.md` 的预期与实测 SHA-256 均为：

`3c932edf50a5fdee8df3c685b9f0c098fa190b279969c750fd3ca516bf3002e3`

候选全文 SHA-256 为：

`ae176119f46841d67a201d5b848b3f786c159f56b255ef78e8f19904419e485f`

同目标统一补丁 SHA-256 为：

`efb990109c7120dacfe616a35dd6186609afc6a8b496dd8d5836aaabf9f4023c`

验证器在临时干净树中完成正式源哈希核对、同一正式目标头检查、`patch --dry-run`、实际应用、应用结果与候选全文逐字节等价检查，并再次核对正式源未改变。机器证据位于 `theory_patch_verification.json`。

## 5. A：参数—图样图谱正式化迁移稿

### 5.1 合同与来源绑定

图谱身份为：

`YPS-IDEAL-TORUS-PATTERN-ATLAS-DRAFT-1.1`

所有结果轨迹调用正式 `FWD-TORUS-1.0` 后端。候选包不保存第二套环面 ODE，也不自行调用另一个积分器。

输入、完整结果和运行证据分别由关闭嵌套对象的 JSON Schema 约束。配置中的 $p,q$ 必须为整数，不再接受字符串、小数或隐式 `int(...)` 强制转换。结果 schema 覆盖全部字段并禁止额外键。

来源清单和锁绑定 15 个条目，包括：

- 正式前向理论；
- 正式 `contracts.py`；
- 正式 `torus.py`；
- 全部候选生产源码；
- 配置、全部 schema 与构建元数据；
- CPython、NumPy、SciPy、Matplotlib 和 jsonschema 运行时身份。

运行前会核对正式后端路径、来源哈希和运行时；任何故意来源漂移、理论/合同漂移、后端路径错误或运行时漂移都会失败关闭。正式后端临时导入后，`sys.path` 在成功或失败路径均逐字恢复，不留下全局导入污染。`Agg` 后端在 `pyplot` 导入前选择。

### 5.2 全量复算

锁定环境为 CPython 3.12.3、NumPy 1.26.4、SciPy 1.11.4、Matplotlib 3.6.3、jsonschema 4.10.3。三次独立全量运行每次均覆盖：

- 4 个目标频率比；
- 4 组振幅；
- 16 个图谱案例；
- 48 条主结果轨迹；
- 4 条纯模态周期轨迹；
- 4 条步长减半轨迹。

每次 16 个 Brent 求根状态均为 `CONVERGED`。模型内诊断结果为：

- 纯模态周期最大相对差：$8.45754\times10^{-13}$；
- 48 条主轨迹最大相对能量漂移：$1.65064\times10^{-12}$；
- 全部报告轨迹的最小采样张紧守卫：$0.253199>0$；
- 最大步长 $0.16\to0.08$ 的最大频率比差：$5.10703\times10^{-14}$；
- 同一步长检查最大共振相位差：$1.47793\times10^{-11}\ \mathrm{rad}$；
- 同一步长检查最大闭合量差：$4.94196\times10^{-12}$。

三次运行各生成 9 个 JSON、CSV、SVG、PNG 与工件清单文件。两组目录级比较均为零差异；全部文件 SHA-256 在三次之间一致。`outputs/full_repeat_verification.json` 还复核了两个输出 schema、每份 artifact manifest、自身文件集合、16 案例与 48 主轨迹计数。

以上只属于理想、对称、无质量、不可伸长且始终张紧的环面模型内部数值验证。数值调谐固定解释为 `ideal_model_internal_not_experimental_calibration`，不是装置参数定值或实验校准。

## 6. S：无接触静态参考迁移稿

新模型身份为：

`YPS-NO-CONTACT-STATIC-REFERENCE-DRAFT-1.1`

能力为：

`position_orientation_conservative_no_contact_static_reference_only`

资格状态为：

`NO_FORMAL_NUMERICAL_QUALIFICATION_CARRIED`

生产状态只含材料结点位置、摆球位置和姿态；生产 API 不含速度、角速度、时间步、惯性动力学、动能、动量、阻力、耗散、功率或旋转时间推进。历史算例构造器、对象性辅助函数和历史接受清单均位于测试层。生产树精确包含 20 个语义静态抽取或候选新增模块；AST 静态边界检查没有发现动态或接触标识符。

规范运行合同绑定静态装配、单一种子、固定 BFGS 设置和审计阈值。机器证据包含 26 个来源条目、装配令牌、种子哈希、求解器、阈值、运行时和独立实现诊断。

两个受支持依赖单元的结果为：

| 单元 | Python | NumPy | SciPy | pytest | jsonschema | 完整测试 | 优化器记录 |
|---|---|---|---|---|---|---:|---|
| current | 3.12.3 | 2.5.2 | 1.18.1 | 9.1.1 | 4.25.1 | 57 passed | status 2, success false |
| lower | 3.12.3 | 1.26.4 | 1.12.0 | 8.4.2 | 4.10.3 | 57 passed | status 2, success false |

两个单元复现相同的装配令牌、种子哈希、优化器状态 2 和精度损失消息。状态 2 只作记录，没有被隐藏或改写成优化器成功；通过与否由冻结的独立实现诊断决定。五项独立诊断均通过，规范 current 单元的末级有限差分相对误差为 $5.63253\times10^{-10}$，尺度化广义力残差为 $1.20238\times10^{-8}$，尺度化全局力与力矩平衡分别为 $5.80433\times10^{-17}$ 和 $0$。

这只证明候选静态实现和两个声明依赖单元中的规范运行行为。迁移动作不继承或重新授予历史 G2 条件性资格，更不授予连续柔索、RC1、接触、动力学、装置或实验资格。

## 7. M：四点冻结观察与描述性插值

分析只读取四张冻结 P3R5 尺度卡及冻结 admissibility metrics，二者 SHA-256 分别为：

- `48f418094ef7ccaa595a63a080f65f82d5b0125eaec0fb25cc58acf823bcb0f0`；
- `e93eb9a0cb074ca1cc9a137149b89b8d2c4384f100c9a9eefaf5c0ff79a3f987`。

输出严格区分：

- `OBSERVED_AT_FOUR_FROZEN_POINTS`：四个冻结点直接记录的量；
- `INTERPOLANT_PROPERTY`：用四点构造的 PCHIP 描述曲线性质。

四个观察点的 $lambda_-$ 从 $-0.0346075$ 到 $-0.0678280$，另外两个保存特征值在四点上均为正。每个点的负方向只含归一化侧向平移与绕支点连线滚转，因此只支持四个固定双活动候选参考分别具有 $(-,+,+)$ 谱符号。

PCHIP 只在观察凸包 $0.74\le s\le1.62$ 内定义，求值函数对任何区间外输入失败关闭。机器状态 `INTERPOLANT_HAS_NO_ZERO_CROSSING_ON_OBSERVED_CONVEX_HULL` 只描述该插值器，不是未观察尺度上的模型求值、连续稳定性证明、临界尺度、分岔判据或装置预测。

复算收口时发现旧图形工件没有记录生成运行时，因此同一数值 JSON/CSV 在不同 Matplotlib 排版实现下可产生不同 PNG/SVG 字节。F0R 已把配置、构建元数据、全部分析源码和 CPython/NumPy/SciPy/Matplotlib 身份写入输出；artifact manifest 将字节确定性明确限定为相同已记录源码、配置和运行时。本轮绑定环境中三份完整稳定性输出逐字节一致。

本分析没有调用接触实现，没有生成新接触卡，没有运行 G3R5，也没有修改冻结证据。

## 8. G：治理与逐文件清单

`formal_promotion_file_map.json` 已从当前候选树重新生成，共 92 条条目：

- 63 条只在具体正式目标获得明确人工授权后才可考虑新增或修改；
- 29 条保持候选、迁移工具或数值证据；
- `formal_write_authorized=true` 的条目数为 0；
- 没有缺失候选文件或指向已删除旧路径的条目。

理论验证器与证据、严格 schema、来源锁、全量运行证据、三重复核、静态运行合同与证据、历史测试夹具及稳定性运行时绑定均已进入逐文件清单。R/E 候选文档没有扩大结论；引用和文件移动没有留下活动依赖断裂。

## 9. 已执行验证

### 9.1 完整测试

实际执行命令为：

```bash
PYTHONPATH=src /tmp/yps-f0r-atlas-venv-20260829/bin/python -m pytest -q
```

参数图谱结果：`14 passed in 11.58s`。

```bash
PYTHONPATH=src /tmp/yps-f0r-static-current-20260829/bin/python -m pytest -q
PYTHONPATH=src /tmp/yps-f0r-static-lower-20260829/bin/python -m pytest -q
```

无接触静态结果：current 单元 `57 passed in 0.64s`；lower 单元 `57 passed in 0.53s`。

```bash
PYTHONPATH=src /tmp/yps-f0r-atlas-venv-20260829/bin/python -m pytest -q
```

稳定性图谱在加入来源/运行时绑定并完成图形排版复核后结果：`7 passed in 1.88s`。

这些测试覆盖严格配置、输出和运行证据 schema 的正例与负例；小数/字符串 $p,q$、未知嵌套键和输出额外字段的拒绝；错误后端路径；正式理论、合同、生产源码和运行时故意漂移失败；`sys.path` 无污染；规范静态证据 schema；静态-only AST；插值外推拒绝；工件字节确定性。

### 9.2 全量图谱与重复证据

三次分别执行：

```bash
PYTHONPATH=src /tmp/yps-f0r-atlas-venv-20260829/bin/python \
  -m y_pendulum_pattern_atlas \
  --config configs/atlas_v1.json \
  --output /tmp/yps-f0r-atlas-full-<repeat>-20260829 \
  --repository-root ../../../..
```

重复验证执行：

```bash
/tmp/yps-f0r-atlas-venv-20260829/bin/python \
  tools/verify_full_repeats.py \
  /tmp/yps-f0r-atlas-full-a-20260829 \
  /tmp/yps-f0r-atlas-full-b-20260829 \
  /tmp/yps-f0r-atlas-full-c-20260829 \
  --project-root . \
  --output outputs/full_repeat_verification.json
```

结果：三次均为 16 案例、48 主轨迹，九个工件逐字节一致；manifest 自核、两个 schema 和语义计数均通过。

### 9.3 补丁、来源、状态 2 与工件复算

实际执行并通过：

```bash
python3 verify_theory_erratum.py
PYTHONPATH=src /tmp/yps-f0r-atlas-venv-20260829/bin/python \
  tools/generate_source_manifest_lock.py --check
python3 tools/generate_migration_provenance.py \
  --repository-root ../../../.. \
  --output migration_provenance.json \
  --check
```

两个静态依赖单元分别运行 `tools/runtime_probe.py`。current 输出与候选规范证据逐字节相同；lower 输出复现相同装配、种子、状态 2、`success=false` 和五项通过的独立诊断。

稳定性图谱在绑定环境中重新生成候选输出及两份临时输出，三份目录 `diff -qr` 均为零差异。

### 9.4 静态检查与结构化工件

三个 Python 子项目分别执行并通过：

```bash
ruff check .
python -m compileall -q src tests tools
```

稳定性子项目没有 `tools/`，相应 compileall 只覆盖 `src tests`。所有候选 JSON 均完成解析；各 artifact manifest 的路径、大小和 SHA-256 完成复核；迁移溯源和逐文件清单从当前源码重算。正式目录、顶层规范和 P3–P3R5 冻结工件完成 Git 差分与绑定 SHA-256 检查。

### 9.5 Markdown 解析与实际渲染

F0 目录中的 10 份交付 Markdown 均使用 Pandoc 3.1.3 的 `--from=markdown` 完成解析；Pandoc AST 复核没有发现落入普通文本或代码节点的未配对 `$`，源文本也没有意外制表符、尾随空格或未闭合代码围栏。

三份关键报告使用 Pandoc HTML、临时固定的本地 MathJax 3.2.2、Playwright 和 Google Chrome 实际渲染为 A4 PDF。候选理论、F0R 总报告、稳定性报告分别有 339、18、28 个公式源节点；385/385 个节点均完成渲染，MathJax processing error 和 `mjx-merror` 均为 0。稳定性报告中的 1440×1475 PNG 完整加载。

最终临时渲染页数分别为 30、10、5，共 45 页。全部页面均经 Poppler 转为 PNG 并按页检查，公式、表格、代码块、中文字体和图片没有缺失或越界；另外以原始分辨率检查了复杂表格、长状态串和稳定性图页。第一次图形检查发现说明框与图例局部遮挡，修正位置、重新生成三份字节一致工件并复跑测试后再次渲染检查通过。

Pandoc 直接 MathML 路径对候选理论中的旧式 `\rm`、`\boldsymbol` 和矩阵环境产生 28 条转换警告，因此该路径没有被计作通过。系统自带 MathJax 2.1 也没有被作为验收路径。最终通过只绑定上述 MathJax 3.2.2 浏览器渲染链；临时渲染依赖没有写入仓库或全局环境。

### 9.6 远端背书

仓库没有 `.github/workflows/**` 状态检查。本轮结论没有独立远端 CI 背书；本报告只陈述本机实际执行的命令和证据。提交推送成功也不等同于独立验证。

## 10. 未执行验证与禁止动作

本轮未执行：

- 任何正式目录实际合并；
- 连续柔索或 RC1 新数值复算；
- P3–P3R5 冻结证据重算或修改；
- 新接触资格卡、G3R5 或 P3R6；
- P4、P5、P6、动力学或动态接触；
- RC1 扩展、修补或重新资格化；
- 装置级物理验证；
- 实验测量或实验验证。

## 11. 结论上限与停止门

F0R 的最高结论是：四个候选整改包及其本机绑定验证已经闭合，可进入独立候选复审。它不能改写正式高保真 NO-GO，不能把理想图谱调谐解释成实验校准，不能把静态实现证据解释成历史资格继承，不能把四点插值解释成连续物理证明，也不能给出装置或实验结论。

全部验证和交接更新后，本轮必须停止在：

`F0R_PRO_REVIEW`

只有独立复审通过，且用户随后对具体正式目标逐项明确授权，才可讨论正式提升批次。
