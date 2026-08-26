# 交接说明（current）

更新时间：2026-08-26T20:20:56+09:00

## 1. 本轮完成

在 `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/` 完成接触路线裁决和候选静态 KKT 数学原语，未修改正式理论或正式程序。

裁决结果：

- 不在无接触边界处立即终止，因为无摩擦刚性静态接触可以在不引入接触刚度、阻尼和摩擦标定参数的前提下检验目标 `alpha` 是否存在受约束平衡态；
- 暂不采用柔顺接触，因为当前仓库没有可辨识的接触刚度、阻尼、摩擦或表面形变校准；
- 只开放静态 KKT 可行性层，动态互补/冲量层继续关闭。

源码核对确认：正式 `_rod_self_contact_margin` 只返回所有登记接触域的全局最小净空；正式定端制备和 `rhs` 均以 `compute_contact=False` 计算，动力学只在净空守卫零穿越时终止。因此不能只给静态态增加不穿透约束后，再把它释放进当前无接触 ODE。

候选实现包括：

- 普通段对和固定材料分离域的最近点见证；
- 非唯一平行接触、零距离见证和塌缩段失败关闭；
- 端点间隙雅可比与全局节点装配；
- 非负法向乘子重构和有量纲 KKT 审计；
- 通用 SLSQP 静态受约束能量原型；
- 活跃约束零空间 Hessian 半正定充分检查；
- 预冻结合同、源码哈希、定向测试和验证报告。

预冻结前观察到的接触运行数为 `0`，动态接触运行数为 `0`。

## 2. 新增路径

- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/__init__.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/geometry_kkt.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/types.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/parameter_domain.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/witness.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/witness_candidates.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/assembly.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/kkt.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/kkt_audit.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/multipliers.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/hessian.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/static_solver.py`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/contract.json`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/prefreeze.json`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/validation_report.json`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/README.md`
- `90_候选工作区/current/三锚点高保真资格/hard_contact_candidate/decision.md`
- `90_候选工作区/current/三锚点高保真资格/tests/test_contact_geometry_candidate.py`
- `90_候选工作区/current/三锚点高保真资格/tests/test_contact_degeneracy_candidate.py`
- `90_候选工作区/current/三锚点高保真资格/tests/test_contact_kkt_candidate.py`
- `90_候选工作区/current/三锚点高保真资格/tests/test_contact_prefreeze_candidate.py`

## 3. 已执行验证

隔离候选验证：

- `python -m py_compile ...`：通过；
- `python -m pytest -q tests/test_contact_*_candidate.py`：`12 passed`；
- `contract.json`、`prefreeze.json`、`validation_report.json`：JSON 解析通过；
- `README.md`、`decision.md`：Pandoc 解析通过；
- 预冻结清单自校验：通过。

未执行：完整既有候选测试套件、正式 `HighFidelityModel` 适配、任何目标 `alpha` 接触制备、任何动态接触积分。

## 4. 当前结论

正式高保真状态保持：

`HF_NUMERICAL_QUALIFICATION_NO_GO`

无接触路线仍不能到达 `alpha=1e-2`、`1e-4`、`1e-6`。本轮只证明候选静态接触路线已经有可测试的逐约束几何和 KKT 基础，不证明任何目标尺度存在合法接触平衡，更不证明压缩极限或动态轨迹已经实现。

## 5. 下一项唯一主任务

建立正式登记到逐接触约束的只读适配器，并在看到任何新结果前冻结运行协议：

1. 精确展开 `same_branch_contact_registration.full_pairs`；
2. 精确展开 `partial_pairs` 的固定材料分离参数域；
3. 精确展开结点套筒裁剪后的跨支活动段，不改变杆径、`minimum_clearance` 或套筒身份；
4. 对每项间隙复算最近点、雅可比和接触对身份；
5. 冻结 KKT、二阶稳定性、多种子和退化见证门；
6. 首先且只运行 `alpha=1e-2` 静态接触制备。

若 `alpha=1e-2` 失败，先裁决几何不可行、约束奇异或求解器问题，不进入动态层；若通过，再分别冻结 `1e-4`、`1e-6` 静态协议。动态互补、冲量、摩擦和恢复系数需要另行裁决。
