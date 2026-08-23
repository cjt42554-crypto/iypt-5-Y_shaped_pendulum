# ADR-0003：增加稀疏二阶 Newmark 交叉积分路径

状态：Accepted as optional cross-solver。

Radau 仍是冻结默认。平均加速度 Newmark（\(\beta=1/4,\gamma=1/2\)）直接求解

\[
M a_{n+1}-F(q_{n+1},v_{n+1},t_{n+1})=0,
\]

并使用稀疏有效切线，避免把一致质量消元后的一阶 Jacobian 预先稠密化。它不引入算法阻尼，不会隐藏未解析纵波。非光滑活跃集切换仍需时间步收敛；Newton 不收敛时明确失败，不静默跨越事件。
