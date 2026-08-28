# HF-v2 核心重构：Codex 执行入口

## 1. 当前状态

P2 无接触静力算法继续保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

历史静态接触裁决继续保持：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`。

P3R2 已按 Pro 授权完成，G3R2 冻结裁决为：

`NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`

当前强制停止门为：

`G3R2_PRO_REVIEW`

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

当前没有已授权的后续 Codex 实现任务。P4、P5、P6、动态接触、正式程序迁移、公共 API、HDF5、UI、装置级物理验证和实验验证全部关闭。

## 2. 继续前必须读取

下一次任务按以下顺序读取：

1. 顶层 `AGENTS.md`；
2. `90_候选工作区/交接说明_current.md`；
3. 本文件；
4. `10_PRO_G3R_REVIEW_AND_P3R2_GATE.md`；
5. `HF-v2-core/contracts/P3R2_FROZEN_PROTOCOL.md`；
6. `HF-v2-core/contracts/p3r2_acceptance_manifest.json`；
7. `HF-v2-core/reports/G3R2_REPORT.md`；
8. `HF-v2-core/reports/g3r2_metrics.json`；
9. `HF-v2-core/src/ypendulum_hfv2_p3r2/solver.py`；
10. `HF-v2-core/src/ypendulum_hfv2_p3r2/restoration.py`；
11. `HF-v2-core/src/ypendulum_hfv2_p3r2/kkt.py`；
12. `HF-v2-core/src/ypendulum_hfv2_p3r2/evidence.py`；
13. 按需读取 P3R2 组装、认证、算例、测试和历史 P3/P3R 工件。

P3/G3、P3R/G3R 和 P3R2/G3R2 的协议、目标、种子、报告、指标及绑定哈希均是不可变历史证据。不得修改旧文件后追溯改写任何 NO-GO。

## 3. 已完成的提交边界

Pro 要求的三个有序提交已经进入远程 `main`：

1. P3R2 预冻结：`227b4472cc33f4c5f70d81185030bb5709f6cfa1`；
2. P3R2 实现：`61b107d27db015b71d7b48bad5dd0431367e67f4`；
3. G3R2 证据：`507f403c2c08697d111e286eac88e3126564ff98`。

前两项进入 Git 历史前，两个新资格目标运行数均为零。G3R2 指标 SHA-256 为：

`b9580859b3eccbaf21ee240b911d2c83354ffe7a88916612f6993efdeab2bfe8`

## 4. 冻结算法与身份

P3R2 使用：

- 模型 `HFV2-DISCRETE-CORD-RIGID-BOB-0.5-CONTACT-CANDIDATE`；
- 组装 `YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-3.0`；
- 算法 `YPS-HFV2-P3R2-COMPOSITE-SLSQP-KKT-RESTORATION-1.0`；
- 尺度 `YPS-HFV2-P3R2-COMPONENT-SCALE-1.0`；
- 独立包 `ypendulum_hfv2_p3r2`。

每个种子均执行固定 SLSQP 和总是执行的投影 KKT 恢复；恢复不是失败触发的备用求解器。完整分量站立残差分别以 N、N·m 和无量纲分量记录，旧 `1e-8` 混合标量门继续用于历史 35 度回归，NNLS/LP 使用同一尺度合同。

## 5. 冻结结果

历史 35 度三个原种子全部通过，反偏种子的旧站立残差从 `1.1056080207858129e-8` 恢复到 `9.06677484273175e-13`。

两个新目标均为 `0/3`：

- 非对称 32/41 度解析参考的真实临界锥最小支持曲率为 `-4.816125831771666`；两个偏置种子转入不同稳定分支，且尺度化同带 LP 不可行；
- 1.4 倍几何尺度解析参考的最小支持曲率为 `-0.0022739949514351543`；两个偏置种子转入不同稳定分支并偏离冻结参考。

两个解析参考均为驻点而不是局部稳定平衡。因此，冻结资格门必须给出：

`NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`

该结论只否决 `0.5-CONTACT-CANDIDATE` 与冻结 P3R2/G3R2 协议，不否决静态刚性接触物理路线。

## 6. 下一步唯一范围

下一步只允许：

`G3R2_PRO_REVIEW`

Pro 必须独立审查提交顺序、预冻结身份、复合算法、尺度合同、完整分量证据、两个新目标的稳定性和分支结构，并裁决是否允许另开版本化协议。

收到 Pro 新裁决和用户新的明确继续指令前，Codex 不得自行：

- 修改两个新目标、解析参考、种子、算法、门槛、报告或指标；
- 把解析驻点改写为合格稳定平衡；
- 删除偏置种子或把 `0/3` 改为部分通过；
- 调整尺度化 NNLS/LP 来追求事后 PASS；
- 增加其他求解器、fallback、随机重启、罚刚度或柔顺接触；
- 修改接触登记活动域、P2 方程或正式目录；
- 开始 P4、P5、P6、动力学或正式提升。

## 7. 结论与验证边界

完整候选测试为 `117 passed`；Ruff、`compileall`、JSON、生成器逐字节检查、Pandoc 解析和 PDF 栅格化逐页视觉检查通过。装置级物理验证、实验验证、动力学、P4/P5/P6 和正式提升未执行。

正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、公共 API、HDF5 和 UI 均未修改。
