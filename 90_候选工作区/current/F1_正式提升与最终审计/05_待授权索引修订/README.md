# `02_模拟程序/README.md` 待授权索引修订

状态：`NOT_APPLIED_PENDING_SEPARATE_AUTHORIZATION`

## 目的

路径 F 本轮授权只覆盖 T/A/S/R，没有覆盖正式索引 `02_模拟程序/README.md`。A 已在第三计算层下增加 `pattern_atlas/`，S 已增加新的无接触静态参考目录，因此原索引中“包含三个计算层级”的表述已不能完整反映正式程序树。

本目录只保存一份同目标最小补丁，不修改正式索引。补丁只做以下增补：

- 在第三计算层条目中列出 A，并写明其仓库绑定、`FWD-TORUS-1.0` 理想环面模型身份和非装置校准、非高保真资格、非实验验证边界；
- 增加 S 的正式目录条目，并写明其无接触静态参考能力、非完整模拟器边界和 `FORMAL_STATIC_REFERENCE_IMPLEMENTATION_AND_RUNTIME_EVIDENCE_ONLY` 结论上限；
- 明确保留仓库整体 `HF_NUMERICAL_QUALIFICATION_NO_GO` 状态。

补丁不改写其他索引条目，也不改变任何模型、实现、配置、阈值或资格结论。

## 绑定与应用门槛

- 正式目标：`02_模拟程序/README.md`
- 正式目标基线 SHA-256：`a04cc5269a1165e2f5f815b8da2476335f6d554bfb66f2f505da2310f6958164`
- 提议目标后态 SHA-256：`aa13ef5797eb834cb7c83586b1d3e7ac36157118a901cac5996dcd93fa5778cd`
- 补丁：`02_模拟程序_README.same-target.patch`
- 当前动作：仅候选保存和 dry-run；未应用
- 后续动作：取得对正式索引的单独授权后，先复核基线哈希，再以 zero-fuzz 方式应用并重新执行 Pandoc 解析与渲染检查

正式目标哈希不匹配时必须失败关闭，不得自动寻找相似上下文或扩大修改范围。
