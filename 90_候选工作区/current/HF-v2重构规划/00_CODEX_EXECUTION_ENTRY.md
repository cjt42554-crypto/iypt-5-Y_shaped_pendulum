# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

P0/P1 已在提交 `4d8777095e90f431d686ae338b754abb430a6a98` 完成。Pro 独立审查认可其范围控制和局部实现测试，但发现弯曲方程、材料坐标合同、状态布局绑定和证据自动化问题，因此 P2 暂停。

当前状态：

`G1_IMPLEMENTATION_TESTS_PASS__P2_HOLD_PENDING_G1R`

正式数值资格：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

动态硬接触：

`CLOSED_PENDING_PRO_REVIEW`

## 2. 开始前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `05_PRO_G1_REVIEW_AND_G1R.md`；
5. `01_ARCHITECTURE_AND_PHYSICS_CONTRACT.md`；
6. `02_PHASED_IMPLEMENTATION_PLAN.md`；
7. `03_ACCEPTANCE_MATRIX.md`；
8. `04_MIGRATION_AND_ROLLBACK.md`；
9. `plan_manifest.json`；
10. 按需读取 `HF-v2-core` 的 G1 报告、源码和测试。

`05_PRO_G1_REVIEW_AND_G1R.md` 是对原 P1 合同的审查性修正；与较早文件冲突时，以该审查和更新后的合同为准。

## 3. 下一次 Codex 的唯一范围

下一次只执行 **G1R**，不得进入 P2。

G1R 必须完成：

- 候选模型身份从 `0.1-CANDIDATE` 升级为 `0.2-CANDIDATE`；
- 用离散曲率二次能替换 RC1 切向差弯曲能，并实现解析负梯度；
- 消除材料坐标与静长的双重真值；
- 将状态与节点质量绑定明确的自由节点布局；
- 建立清单驱动、可由单一命令复算的 G1R 证据；
- 收紧物理核心模块发现与架构审计；
- 完成 Pro 审查中列出的低成本局部修正；
- 更新 G1R 报告和交接。

完成后必须停止并交回 Pro 审查。

## 4. 禁止事项

G1R 期间不得：

- 实现静态求解器、KKT 或多种子制备；
- 运行 P2 算例、三锚点或目标压缩尺度；
- 实现或接入静态/动态接触；
- 修改正式 `01_最终理论/**` 或 `02_模拟程序/**`；
- 修改顶层 `AGENTS.md`、UI、公共 API 或 HDF5；
- 复制 RC1 单体结构；
- 自动换算法、放宽门槛、裁剪状态或增加结果驱动特殊分支；
- 修改或删除历史 `0.1` G1 报告来伪装成新模型已通过。

## 5. 提交和停止规则

- 只使用 `main`，不得创建分支；
- G1R 至少形成一个语义明确的提交；
- 提交前运行 G1R 规定的全部检查；
- 将旧 `0.1` G1 工件保留为历史证据，新建 `0.2` 的 G1R 证据；
- 更新 `交接说明_current.md` 与 `交接说明_history.md`；
- 提交并推送后停止，不得自动开始 P2。
