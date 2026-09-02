# `02_模拟程序/README.md` 索引修订记录

状态：`APPLIED_WITH_BOUNDARY_CORRECTION`

## 原提案

路径 F 当时只授权 T/A/S/R，没有覆盖正式索引 `02_模拟程序/README.md`。A 已在第三计算层下增加 `pattern_atlas/`，S 已增加新的无接触静态参考目录，因此原索引中“包含三个计算层级”的表述不能完整反映正式程序树。

原提案保留在 `02_模拟程序_README.same-target.patch`，其目标是：

- 在第三计算层条目中列出 A，并写明仓库绑定、`FWD-TORUS-1.0` 理想环面模型身份和非装置校准、非高保真资格、非实验验证边界；
- 增加 S 的正式目录条目，并写明无接触静态参考能力、非完整模拟器边界和 `FORMAL_STATIC_REFERENCE_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY` 结论上限；
- 明确保留仓库整体 `HF_NUMERICAL_QUALIFICATION_NO_GO` 状态。

## 实际应用

用户随后明确授权重新审查并更新正式目录。正式目标基线 SHA-256 复核为：

`a04cc5269a1165e2f5f815b8da2476335f6d554bfb66f2f505da2310f6958164`

原补丁的 hunk 行数只覆盖到新增空行；以标准 `git apply` 应用后得到原提议 SHA-256：

`aa13ef5797eb834cb7c83586b1d3e7ac36157118a901cac5996dcd93fa5778cd`

该后态没有包含原提案同时要求保留的最终 `HF_NUMERICAL_QUALIFICATION_NO_GO` 明示行。因此没有把原补丁逐字作为当前正式目标，而是依据原提案的三项语义要求和当前正式程序树，独立形成边界完整的正式索引。

正式索引更新提交为：

`e97f166aa0905262821a1d74aa09c847901b0207`

实际正式目标 SHA-256 为：

`0e141360041192aa1179f84a8629c93cc0909ecc75140dbf33aa95d77a713128`

原补丁文件保持原字节，作为当时待授权提案及其边界偏差的审计记录；它不再是当前正式索引的权威后态。

## 结论边界

本次只更新正式程序索引，没有修改 A、S 或其他模型的实现、配置、阈值、运行证据和资格状态。正式结论仍限于各子项目自身声明的模型身份与验证层级；仓库整体高保真数值资格继续为 `HF_NUMERICAL_QUALIFICATION_NO_GO`。
