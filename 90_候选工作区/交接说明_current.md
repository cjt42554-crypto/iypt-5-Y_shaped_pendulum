# 交接说明（current）

更新时间：2026-08-28 12:04 +0800（P3R2/G3R2 完成，冻结 NO-GO，等待 Pro 复审）

## 1. 当前裁决

本轮已从 GitHub 快进到 Pro 的 G3R 复审收口提交：

`5b5b288506c8e3eb5e810fe7a569e3ac6f07e3f4`

历史裁决继续保持：

- `NO_GO_G3_STATIC_CONTACT_ALGORITHM`；
- `NO_GO_G3R_STATIC_CONTACT_ALGORITHM`；
- `G3R_PRO_REVIEW_CONFIRMS_FROZEN_NO_GO__P3R2_AUTHORIZED`。

P3R2 已按授权完成，G3R2 冻结裁决为：

`NO_GO_G3R2_STATIC_CONTACT_ALGORITHM`

本轮强制停在：

`G3R2_PRO_REVIEW`

P2 无接触静力算法继续保持：

`G2_NO_CONTACT_STATIC_ALGORITHM_CONDITIONALLY_QUALIFIED`

正式高保真总状态继续为：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

P4、P5、P6、动态接触、正式程序迁移、公共 API、HDF5、UI、装置级物理验证和实验验证全部关闭。

## 2. P3R2 有序提交与身份

Pro 要求的三段式边界已经满足并均已推送到远程 `main`：

1. 预冻结协议与机器清单：`227b4472cc33f4c5f70d81185030bb5709f6cfa1`；
2. 实现与预目标基准：`61b107d27db015b71d7b48bad5dd0431367e67f4`；
3. 首次 G3R2 结果证据：`507f403c2c08697d111e286eac88e3126564ff98`。

前两项进入 Git 历史前，两个新资格目标的运行数均为零。冻结身份为：

- 候选模型：`HFV2-DISCRETE-CORD-RIGID-BOB-0.5-CONTACT-CANDIDATE`；
- 接触组装：`YPS-HFV2-CONTACT-ASSEMBLY-IDENTITY-3.0`；
- 复合算法：`YPS-HFV2-P3R2-COMPOSITE-SLSQP-KKT-RESTORATION-1.0`；
- 尺度合同：`YPS-HFV2-P3R2-COMPONENT-SCALE-1.0`；
- 独立包：`ypendulum_hfv2_p3r2`。

所有种子执行同一条“固定 SLSQP 主阶段 + 总是执行的投影 KKT 恢复阶段”路径；没有失败触发的 fallback、随机重启、罚刚度、柔顺接触、摩擦、恢复系数、冲量或结果驱动阈值放宽。P3/P3R 的历史目标、种子、报告、指标和旧 `1e-8` 回归门均未修改。

## 3. G3R2 结果

历史 35 度目标的三个原种子全部通过。反偏种子在一次固定 Newton 恢复后，旧混合标量站立残差由 `1.1056080207858129e-8` 降至 `9.06677484273175e-13`；旧 `1e-8` 门保持不变。

两个预冻结的新资格目标均为 `0/3`，因此总门必须为 NO-GO：

### 3.1 非对称 32/41 度双接触目标

- 解析种子精确满足参考位置、KKT 和解析乘子，但真实临界锥最小支持曲率为 `-4.816125831771666`，稳定性门失败；
- 正偏和反偏种子确定性收敛到两个不同的稳定分支，摆球横向位移约为 `+/-0.00749908 m`，旋转分量约为 `+/-0.07546885 rad`；
- 两个偏置分支相对解析参考的位置误差约为 `0.00754294 m`，乘子误差约为 `0.47173 N`；
- 两个偏置分支的尺度化同带 LP 均给出 `dual_interval_feasible=false`，因此 KKT/支撑区间门也失败。

### 3.2 1.4 倍几何尺度目标

- 解析种子精确满足参考位置、KKT 和解析乘子，但真实临界锥最小支持曲率为 `-0.0022739949514351543`，稳定性门失败；
- 正偏和反偏种子确定性收敛到两个稳定分支，摆球横向位移约为 `+/-0.001181709 m`，旋转分量约为 `+/-0.008496954 rad`；
- 两个偏置分支相对解析参考的位置误差约为 `0.001181808 m`，乘子误差约为 `0.00817143 N`；
- 这两个偏置分支的 KKT 和支撑身份门通过，但不满足冻结参考一致性门。

现有证据表明两个预冻结解析参考都是驻点而非局部稳定平衡；偏置种子落入其他稳定分支。不得在同一协议内修改目标、参考、种子、算法或阈值后重跑。

## 4. 证据与验证

主要证据：

- `90_候选工作区/current/HF-v2-core/contracts/P3R2_FROZEN_PROTOCOL.md`；
- `90_候选工作区/current/HF-v2-core/reports/g3r2_metrics.json`；
- `90_候选工作区/current/HF-v2-core/reports/G3R2_REPORT_RAW.md`；
- `90_候选工作区/current/HF-v2-core/reports/G3R2_REPORT.md`。

固定哈希：

- G3R2 指标 SHA-256：`b9580859b3eccbaf21ee240b911d2c83354ffe7a88916612f6993efdeab2bfe8`；
- 原始报告 SHA-256：`b033326bb3b369b059656deb3276760cc9ef168dd185b573c0dcd5755504f307`；
- 人类报告 SHA-256：`b033326bb3b369b059656deb3276760cc9ef168dd185b573c0dcd5755504f307`。

已执行：

- 精确环境：CPython 3.12.3、NumPy 2.5.2、SciPy 1.18.1、pytest 9.1.1；
- 完整候选测试：`117 passed`；
- Ruff、`compileall`、JSON 解析、架构门和 `git diff --check`；
- G3R2 生成器 `--check`；
- 两份独立临时输出与提交证据逐字节一致，三份指标 SHA-256 相同；
- Pandoc `--from=markdown` 解析；
- P3R2 协议 6 页和 G3R2 报告 2 页经 Pandoc、LibreOffice PDF、Poppler 栅格化后逐页检查，公式、中文、列表和分页无截断或重叠。

应用内浏览器因安全策略拒绝本地 `file://` 页面，没有绕过该限制；成功完成的是上述独立 PDF 实际渲染链。

未执行：装置级物理验证、实验验证、动力学、P4/P5/P6、正式程序提升和公共接口集成。

## 5. 结论上限

当前证据只支持：

`HFV2-DISCRETE-CORD-RIGID-BOB-0.5-CONTACT-CANDIDATE` 在冻结 P3R2/G3R2 协议下未取得静态接触算法资格。

它不支持否定静态刚性无摩擦接触路线，也不构成装置预测、物理验证、实验验证或正式程序资格。历史 G3/G3R NO-GO 与正式 `HF_NUMERICAL_QUALIFICATION_NO_GO` 均保持。

## 6. 下一步唯一动作

下一步只能由 Pro 执行独立复审：

`G3R2_PRO_REVIEW`

复审应至少裁决：

1. 两个新目标把解析驻点预登记为稳定参考是否属于目标设计错误；
2. 非对称目标偏置稳定分支的尺度化同带 LP 不可行是否暴露独立认证合同问题；
3. 是否允许另开版本化修正协议，以及其物理目标、稳定性定义和资格角色；
4. 在任何情况下，本轮证据都不能自动开放 P4、P5、P6 或正式提升。

当前没有已授权的后续 Codex 实现范围。收到新的 Pro 裁决和用户明确指令前，不得新增目标、修改冻结证据或继续算法迭代。

## 7. 修改边界

本轮只在 `90_候选工作区/current/**` 新增 P3R2 候选合同、独立实现、测试、工具和证据，并更新候选治理与交接文件。正式 `01_最终理论/**`、`02_模拟程序/**`、顶层 `AGENTS.md`、公共 API、HDF5 和 UI 均未修改。
