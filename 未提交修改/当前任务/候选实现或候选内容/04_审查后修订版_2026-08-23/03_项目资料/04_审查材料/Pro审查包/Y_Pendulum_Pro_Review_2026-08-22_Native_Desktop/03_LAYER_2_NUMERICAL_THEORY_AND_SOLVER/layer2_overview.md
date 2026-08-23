# 前向理论数值计算目录说明

本目录当前活动交付物只有两项：

1. `IYPT_2027_Y_Pendulum_前向预测理论的数值计算理论.md`：独立数值计算理论；
2. `y_pendulum_forward_solver/`：冻结 `FWD-CABLE-1.0` 与 `FWD-TORUS-1.0` 的活动研究程序。

活动程序唯一绑定的前向理论 SHA-256 为：

```text
7eaf18e30087438507aef73c481b49e5b1427a146d79c0fd2b35ca10dc02cdb2
```

`y_pendulum_closed_solver_v1_1/` 和同名 ZIP 是旧版二次 Ritz 原型及其可恢复档案。它们绑定旧理论、包含当前规范模型未注册的弯曲/转动/附加质量，并且不是活动前向求解器。

本目录不包含高保真后端或结构性理论。

