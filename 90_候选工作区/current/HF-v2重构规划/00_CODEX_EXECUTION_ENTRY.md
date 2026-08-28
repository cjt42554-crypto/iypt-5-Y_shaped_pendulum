# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

P2 无接触静力算法继续保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

历史静态接触裁决继续保持：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`。

G3R2 Pro 独立复审裁决为：

`G3R2_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R3_TARGET_ADMISSIBILITY_AND_DUAL_CERTIFICATION_AUTHORIZED`

P3R3 当前执行状态为：

`P3R3_READY_FOR_CODEX_EXECUTION`

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P4、P5、P6、动力学、动态接触、正式程序迁移、公共 API、HDF5、UI、装置级物理验证和实验验证全部关闭。

## 2. 开始任务前必须读取

按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `11_PRO_G3R2_REVIEW_AND_P3R3_GATE.md`；
5. `HF-v2-core/contracts/P3R2_FROZEN_PROTOCOL.md`；
6. `HF-v2-core/contracts/p3r2_acceptance_manifest.json`；
7. `HF-v2-core/reports/G3R2_REPORT.md`；
8. `HF-v2-core/reports/g3r2_metrics.json`；
9. `HF-v2-core/src/ypendulum_hfv2_p3r2/certification.py`；
10. `HF-v2-core/src/ypendulum_hfv2_p3r2/kkt.py`；
11. `HF-v2-core/src/ypendulum_hfv2_p3r2/restoration.py`；
12. `HF-v2-core/src/ypendulum_hfv2_p3r2/solver.py`；
13. 按需读取 P3R2 组装、算例、临界锥、测试和历史 P3/P3R 工件。

P3/G3、P3R/G3R、P3R2/G3R2 的协议、目标、种子、报告、指标和哈希均是不可变历史证据。不得修改旧文件后追溯改写任何 NO-GO。

## 3. Pro 复审的因果裁决

冻结 G3R2 NO-GO 必须保持，因为两个新目标均为 `0/3`，不满足冻结协议的全种子通过门。

但两个解析参考均只是一阶 KKT 驻点，不是局部稳定平衡：

- 非对称 32/41 度参考最小临界锥曲率 `-4.816125831771666`；
- 1.4 倍几何尺度参考最小临界锥曲率 `-0.0022739949514351543`。

偏置种子确定性进入正曲率稳定分支。因此，本轮目标套件没有把“目标参考有效性”和“算法恢复能力”分开，不能把偏置种子离开不稳定参考直接归因于复合算法失效。

非对称稳定分支还暴露对偶区间认证矛盾：正的规范乘子使驻定残差约 `4.16e-16`，远低于约 `9e-9` 的分量允许带，按 LP 定义该乘子是显式可行见证；提交证据却记录 LP 不可行并返回 NaN 区间。P3R3 必须修正认证自洽性，而不是事后放宽门。

恢复残差使用状态相关规范投影，但当前矩阵没有显式包含投影导数。P3R3 必须把方法严格定义为精确 Newton 或拟 Newton，并对完整复合残差 Jacobian 做独立多步长验证。

完整裁决见：

`90_候选工作区/current/HF-v2重构规划/11_PRO_G3R2_REVIEW_AND_P3R3_GATE.md`

## 4. 下一次唯一范围

下一次只执行：

`P3R3_STATIC_CONTACT_TARGET_ADMISSIBILITY_AND_DUAL_CERTIFICATION_CORRECTION`

P3R3 只修正：

- 资格参考的独立稳定性准入；
- 局部稳定分支与预认证盆地定义；
- 规范乘子可行见证和对偶区间认证自洽性；
- 状态相关投影恢复的 Jacobian 闭合；
- 目标无效与算法种子失败的证据分类。

不得修改 P2 势能/广义力、刚性无摩擦单边接触间隙、正式登记活动域或历史证据。

P3R3 必须使用新身份，建议起点为：

- `HFV2-DISCRETE-CORD-RIGID-BOB-0.6-CONTACT-CANDIDATE`；
- 新的认证/组装身份，不复用 3.0；
- `ypendulum_hfv2_p3r3`。

## 5. 必须分开的提交边界

Codex 必须至少形成三个有序提交：

1. **P3R3 预冻结提交**：协议、机器清单、新身份、目标准入、对偶见证、恢复 Jacobian、历史回归角色和新目标规则；所有新资格目标运行数为零；
2. **P3R3 实现/准入工具提交**：独立包、测试、准入器、对偶认证器和证据生成器；仍不得包含新资格种子结果；
3. **G3R3 证据提交**：前两项进入 Git 历史后，才运行通过准入的新资格目标种子并提交证据。

若不足两个新参考通过目标准入，不得运行算法资格种子，应提交 `TARGET_SUITE_NOT_ADMISSIBLE` 并停止。

## 6. 目标准入门

每个新参考必须在资格种子冻结前独立通过：

- 身份、严格有效域、非活动正间隙和预期接触身份；
- 正乘子 KKT 可行见证、互补、作用—反作用和 P2 只读；
- 真实一侧临界锥最小曲率严格大于预冻结正裕量；
- 矩阵 Hessian 与独立方向有限差分交叉检查；
- 规范自由度处理；
- 局部稳定分支身份和尺度化局部盆地证书。

未通过时必须报告 `TARGET_INVALID`，不得计作算法种子失败，也不得继续运行该目标资格种子。

## 7. 对偶区间与恢复闭合

对偶认证必须保存规范乘子、逐分量驻定残差、允许带和 LP 松弛。显式见证可行时，LP 后端不得报告不可行；否则状态为 `CERTIFIER_INTERNAL_INCONSISTENCY`。区间端点必须使用独立方法复核，且全部缩放、预处理和后端身份在目标结果前冻结。

恢复阶段必须明确精确 Newton 或拟 Newton身份，并对完整复合残差 Jacobian 做多步长独立复核。线搜索必须保持或显式认证活动乘子非负、非活动正间隙和严格有效域。

## 8. 新目标与历史回归

至少冻结两个新的、未观察、局部稳定的双接触目标，每个至少三个确定性种子：

1. 一个非镜像对称目标，两个正乘子不相等；
2. 一个改变几何或载荷尺度的目标。

资格种子必须位于预认证局部盆地内。P3R2 的两个不稳定参考及其已发现稳定分支均已观察，只能作诊断/回归，不能充当新资格目标。

历史 35 度三个原种子继续保持不变并通过旧 `1.0e-8` 混合标量门。

## 9. 禁止事项

不得：

- 修改或覆盖 P3/P3R/P3R2 的冻结协议、目标、种子、报告、指标或哈希；
- 把 G3R2 的 `0/3` 追溯改写为 PASS；
- 把已观察稳定分支包装为未观察目标；
- 把 `TARGET_INVALID` 与算法失败混为一类；
- 在显式可行见证存在时接受 LP 不可行结果；
- 事后调整目标、种子、盆地、曲率裕量、LP 缩放、预处理或容差；
- 增加 fallback、随机重启、罚刚度、柔顺接触、摩擦、恢复系数或冲量；
- 修改接触登记活动域、P2 方程或正式目录；
- 开始 P4、P5、P6、动力学或正式提升。

## 10. 完成与停止规则

P3R3 完成后必须形成独立 G3R3 证据并停止在：

`G3R3_PRO_REVIEW`

自动门的任何结果都不自动开放 P4、P5、P6、动态接触或正式提升。

## 11. 当前验证边界

本次 Pro 复审通过 GitHub 连接器完成提交顺序、合同、指标和源码静态复核，没有重新运行仓库所称的 `117 passed`、Ruff、`compileall`、证据生成器、Pandoc 或 PDF 渲染。

本次只更新候选治理、计划和交接文档。正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、数值源码、测试、公共 API、HDF5 和 UI 均未修改。
