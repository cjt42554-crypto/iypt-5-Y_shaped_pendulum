# 交接说明（current）

更新时间：2026-08-28 13:38 +0800（G3R2 Pro 复审完成，P3R3 已授权）

## 1. 当前裁决

G3R2 Pro 独立复审已进入远程 `main`：

`c543b8a37db02e90b391567a0ae45d0b59a4082a`

历史冻结裁决继续保持：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`。

G3R2 Pro 复审裁决为：

`G3R2_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R3_TARGET_ADMISSIBILITY_AND_DUAL_CERTIFICATION_AUTHORIZED`

P3R3 当前状态为：

`P3R3_READY_FOR_CODEX_EXECUTION`

P2 无接触静力算法继续保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P4、P5、P6、动力学、动态接触、正式程序迁移、公共 API、HDF5、UI、装置级物理验证和实验验证全部关闭。

## 2. G3R2 冻结结果不可改写

P3R2/G3R2 的有序提交为：

1. 预冻结：`227b4472cc33f4c5f70d81185030bb5709f6cfa1`；
2. 实现：`61b107d27db015b71d7b48bad5dd0431367e67f4`；
3. G3R2 证据：`507f403c2c08697d111e286eac88e3126564ff98`；
4. G3R2 交接：`c28b2221b722a6d86023698b8a8516f20574c0a9`。

G3R2 指标 SHA-256 保持：

`b9580859b3eccbaf21ee240b911d2c83354ffe7a88916612f6993efdeab2bfe8`

历史 35 度三个原种子全部通过，反偏种子的旧混合站立残差由 `1.1056080207858129e-8` 经固定 KKT 恢复降至 `9.06677484273175e-13`；旧 `1e-8` 门没有修改。

两个新目标均为 `0/3`，因此冻结裁决必须保持 `NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`，不得追溯改判。

## 3. Pro 复审确认的两个根因

### 3.1 资格参考本身不满足稳定准入

两个预冻结解析参考都精确满足一阶 KKT，但不是局部稳定平衡：

- 非对称 32/41 度参考最小临界锥曲率为 `-4.816125831771666`；
- 1.4 倍几何尺度参考最小临界锥曲率为 `-0.0022739949514351543`。

偏置种子确定性进入正曲率稳定分支。因此 G3R2 的目标合同把“一阶驻点参考有效性”和“算法恢复能力”混在同一资格门内。P3R3 必须先独立准入目标，再运行算法资格种子。

已观察的两个不稳定参考和已经发现的稳定分支只能作为诊断或回归，不能重新包装为未观察资格目标。

### 3.2 对偶区间认证存在自洽性矛盾

非对称稳定分支中，规范乘子为非负，且其逐分量驻定残差远小于冻结允许带，按同一 LP 定义该规范乘子本身就是显式可行见证；提交证据却记录 `dual_interval_feasible=false` 和 NaN 区间。

P3R3 必须把这种情况标记为认证器内部矛盾，而不能解释为空物理支撑集。对偶认证需要冻结缩放、预处理、后端身份和容差，并保存显式可行见证、LP 松弛及端点独立复核。

## 4. 下一步唯一范围

Codex 下一次只执行：

`P3R3_STATIC_CONTACT_TARGET_ADMISSIBILITY_AND_DUAL_CERTIFICATION_CORRECTION`

完整裁决文件：

`90_候选工作区/current/HF-v2重构规划/11_PRO_G3R2_REVIEW_AND_P3R3_GATE.md`

开始前按顺序读取：

1. 顶层 `AGENTS.md`；
2. 本文件；
3. `90_候选工作区/current/HF-v2重构规划/00_CODEX_EXECUTION_ENTRY.md`；
4. `90_候选工作区/current/HF-v2重构规划/11_PRO_G3R2_REVIEW_AND_P3R3_GATE.md`；
5. `90_候选工作区/current/HF-v2-core/contracts/P3R2_FROZEN_PROTOCOL.md`；
6. `90_候选工作区/current/HF-v2-core/contracts/p3r2_acceptance_manifest.json`；
7. `90_候选工作区/current/HF-v2-core/reports/G3R2_REPORT.md`；
8. `90_候选工作区/current/HF-v2-core/reports/g3r2_metrics.json`；
9. P3R2 `certification.py`、`kkt.py`、`restoration.py`、`solver.py`；
10. 按需读取 P3R2 组装、算例、临界锥、测试和历史 P3/P3R 工件。

## 5. P3R3 必须实现的边界

P3R3 只允许修正：

- 资格参考的独立稳定性准入；
- 局部稳定分支与预认证局部盆地定义；
- 规范乘子显式可行见证和对偶区间认证自洽性；
- 状态相关规范投影恢复的 Jacobian 闭合；
- `TARGET_INVALID`、算法种子失败和认证器内部矛盾的证据分类。

不得修改 P2 势能或广义力、刚性无摩擦单边接触物理间隙、正式登记活动域、材料、质量、重力、浮力或历史冻结证据。

P3R3 必须使用新的版本化身份，不得覆盖 `0.5-CONTACT-CANDIDATE`、组装身份 3.0 或 `ypendulum_hfv2_p3r2`。建议起点为：

- `HFV2-DISCRETE-CORD-RIGID-BOB-0.6-CONTACT-CANDIDATE`；
- 新的认证/组装身份；
- `ypendulum_hfv2_p3r3`。

## 6. 必须分开的提交顺序

至少形成以下三个有序提交：

1. **P3R3 预冻结提交**：协议、机器清单、新身份、目标准入、对偶见证、恢复 Jacobian、历史回归角色和新目标规则；所有新资格目标运行数必须为零；
2. **P3R3 实现/准入工具提交**：独立包、测试、准入器、对偶认证器和证据生成器；仍不得包含新资格种子结果；
3. **G3R3 证据提交**：前两项进入 Git 历史后，才运行通过准入的新资格目标种子并提交证据。

如果不足两个新参考通过目标准入，不得运行算法资格种子；应报告 `TARGET_SUITE_NOT_ADMISSIBLE` 并停止。

## 7. 新目标最低要求

至少冻结两个新的、未观察、局部稳定的双接触目标，每个至少三个确定性种子：

1. 一个非镜像对称目标，两项正接触乘子不相等；
2. 一个改变几何或载荷尺度的目标。

每个参考必须在资格种子冻结前独立通过：身份和有效域、非活动正间隙、预期接触身份、正乘子 KKT 可行见证、互补、作用—反作用、P2 只读、真实一侧临界锥正曲率裕量、Hessian 独立方向交叉检查、规范自由度处理和局部盆地证书。

未通过时状态为 `TARGET_INVALID`，不得计作算法种子失败。

## 8. 对偶和恢复认证要求

显式规范乘子满足同一逐分量允许带时，LP 不得返回不可行；否则必须失败关闭为认证器内部不一致，例如：

`CERTIFIER_INTERNAL_INCONSISTENCY`

对偶区间端点必须独立复核。LP 缩放、预处理、方法、版本和可行性容差必须在目标结果前冻结。

状态相关投影恢复必须明确为精确 Newton 或拟 Newton，并对完整复合残差 Jacobian 做多步长独立复核。线搜索必须保持或显式认证活动乘子非负、非活动正间隙和严格有效域。

## 9. 禁止事项

不得：

- 修改 P3/P3R/P3R2 的冻结协议、目标、种子、报告、指标或哈希；
- 把 G3R2 的 `0/3` 追溯改写为 PASS；
- 把已观察稳定分支包装成未观察目标；
- 事后修改目标、种子、盆地、曲率裕量、LP 缩放、预处理或容差；
- 在显式可行见证存在时接受 LP 不可行结果；
- 增加 fallback、随机重启、罚刚度、柔顺接触、摩擦、恢复系数或冲量；
- 修改接触登记活动域、P2 方程或正式目录；
- 开始 P4、P5、P6、动力学或正式提升。

## 10. 停止门与验证边界

P3R3 完成后必须形成独立 G3R3 证据并停止在：

`G3R3_PRO_REVIEW`

自动门的任何结果都不自动开放 P4、P5、P6、动态接触或正式提升。

G3R2 原执行环境曾记录完整候选 `117 passed`、Ruff、`compileall`、JSON、架构门、生成器 `--check`、独立证据逐字节复算、Pandoc 和 PDF 栅格化视觉检查。本次 Pro 复审本身是基于 GitHub 已提交合同、源码和数值证据的独立静态复核，没有重新运行这些工具。

正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、公共 API、HDF5 和 UI 均未修改。