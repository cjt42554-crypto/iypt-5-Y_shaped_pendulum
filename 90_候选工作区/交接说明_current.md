# 交接说明（current）

更新时间：2026-08-28（G3R Pro 复审完成，P3R2 已授权）

## 1. 当前裁决

历史 P3/G3 裁决保持：

`NO_GO_G3_STATIC_CONTACT_ALGORITHM`

P3R/G3R 冻结裁决保持：

`NO_GO_G3R_STATIC_CONTACT_ALGORITHM`

G3R Pro 独立复审裁决为：

`G3R_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R2_AUTHORIZED`

P3R2 当前状态为：

`P3R2_READY_FOR_CODEX_EXECUTION`

P2 无接触静力算法继续保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P4、P5、P6、动态接触、正式程序迁移、公共 API、HDF5、UI、装置级物理验证和实验验证全部关闭。

## 2. 本次 Pro 复审绑定

- P3R 源码基线：`5d1053e94c5bb692c505d2a3ca01327bb79ed242`；
- P3R/G3R 预冻结：`865775b6be5272405d62b9eba7f122704a08dcfd`；
- P3R 实现与 G3R 证据：`db45834588524ccc5b0884d4d1db9c53f3efa458`；
- G3R 交接：`bfeedcc656007b8579aeabe33cab69c0db4ac2c2`；
- G3R 指标 SHA-256：`4da70615db740ca345ae6032dfabac89a8188ffb374890126a41220ffb765241`；
- Pro 复审提交：`476403fee029703dbd89d6a0bffa0c562fcf9850`；
- 完整裁决：`90_候选工作区/current/HF-v2重构规划/10_PRO_G3R_REVIEW_AND_P3R2_GATE.md`。

以上 P3/P3R 历史协议、目标、种子、源码绑定、报告、指标、状态和哈希均为不可变证据。

## 3. G3R 复审结论

冻结 G3R NO-GO 必须保持。新 35° 资格目标三个种子只有 `2/3` 通过；反偏种子的独立站立残差为 `1.1056080207858155e-8`，超过冻结上限 `1.0e-8`，因此 KKT 和允许平衡带内的对偶区间失败。协议禁止看到结果后放宽阈值、更换种子或追加求解器，优化器 `success=true` 也不是验收证据。

该反偏种子的其余门全部通过，包括接触身份、秩、乘子误差、严格有效域、物理和有效域 Jacobian、作用—反作用、P2 只读性以及真实临界锥和二阶交叉检查。旧对称目标结构回归也通过并保留全部弱活动约束。

因此，证据只支持“`0.4-CONTACT-CANDIDATE` 在冻结 G3R 协议下未取得资格”，不支持否定静态刚性接触路线。

## 4. 复审发现的认证缺口

当前一次 SLSQP 返回后没有总是执行、参数预冻结的 KKT 恢复阶段，外部 NNLS/LP 平衡门与主求解终止没有算法闭合。

运行时虽计算完整 `stationarity_vector_N`，提交的 G3R JSON 只保存标量无穷范数，没有保存分量身份。六个广义坐标同时含平移和旋转，当前单一无穷范数又没有在证据中展开平移力 N、转动力矩 N·m 和特征长度换算。这些缺口不改变冻结 FAIL，但阻止把窄幅超限解释成物理路线否定。

## 5. 下一次 Codex 唯一任务

下一次只执行：

`P3R2_STATIC_CONTACT_NUMERICAL_CERTIFICATION_CORRECTION`

开始前必须读取：

1. 顶层 `AGENTS.md`；
2. 本文件；
3. `HF-v2重构规划/00_CODEX_EXECUTION_ENTRY.md`；
4. `HF-v2重构规划/10_PRO_G3R_REVIEW_AND_P3R2_GATE.md`；
5. P3R 冻结协议、机器清单、G3R 报告、指标、求解器、KKT 和证据序列化源码。

## 6. P3R2 强制边界

P3R2 必须使用新的候选模型、接触组装和独立包身份，不得复用 `0.4-CONTACT-CANDIDATE` 或覆盖 `ypendulum_hfv2_p3r`。

必须至少分为三个有序提交：

1. P3R2 预冻结协议与机器清单；
2. 实现与预目标基准；
3. G3R2 回归和资格证据。

第一次新目标运行前必须冻结：

- 一个对每个种子总是执行的单一复合算法；
- 固定 SLSQP 主阶段与固定 KKT 恢复阶段；
- 活动集、规范投影、投影 KKT 方程、Hessian、线性系统、迭代、阻尼/线搜索和失败关闭；
- 完整分量级站立残差、坐标身份、N/N·m 单位和无量纲尺度；
- 当前旧 `1e-8` 标量门继续作为回归门；
- 与同一尺度合同一致的 NNLS/LP 对偶认证；
- 当前 35° 目标及三个原种子的不可变回归角色；
- 至少两个新的未观察资格目标，每个至少三个确定性种子，其中一个必须是非镜像对称双接触目标。

任意一个回归或新资格种子失败，G3R2 必须为 NO-GO。

## 7. 禁止事项

不得：

- 修改 P3/P3R 冻结目标、种子、门槛、报告、指标或哈希；
- 把 P3R 的 `2/3` 改写为 PASS；
- 放宽旧 `1e-8` 门、删除反偏种子或降低所需通过数；
- 只在失败种子上启用 KKT 精化；
- 增加 fallback、随机重启、罚刚度、柔顺接触、摩擦、恢复系数或冲量；
- 修改接触登记活动域、P2 方程或正式目录；
- 开始 P4、P5、P6、动态接触或正式提升。

## 8. 停止门与验证边界

P3R2 完成后必须停在：

`G3R2_PRO_REVIEW`

本次 Pro 复审通过 GitHub 连接器完成提交顺序、协议、机器清单、源码和 G3R 指标的独立静态复核；没有重新运行仓库所称的 `106 passed`、Ruff、compileall、Pandoc、浏览器渲染或证据生成。GitHub 对 G3R 证据提交也没有绑定远端状态检查。

本轮只修改候选治理文档。正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、公共 API、HDF5 和 UI 均未修改。
