# YP-FPSim 数值验证报告

- 模式：`full`
- 总体：`PASS`

| 案例 | 状态 | 指标 | 阈值 | 说明 |
|---|---:|---:|---:|---|
| V-001 | PASS | 8.88178e-16 | 1e-08 | Single-element extension F L/(EA). |
| V-002 | PASS | 0.0040657 | 0.01 | Finite-element cable approaches an inextensible catenary. |
| V-003 | PASS | 0.000114235 | 0.01 | First fixed-free longitudinal FE mode recovers c=sqrt(E/rho). |
| V-004 | PASS | 0 | 0.0005 | A1 pure fast mode matches the nonlinear pendulum period. |
| V-005 | PASS | 0 | 0.0005 | A1 pure slow mode matches the nonlinear pendulum period. |
| V-006 | PASS | 1.84308e-05 | 0.0005 | H1 low modes recover rho^2=1+h/l in the light-string stiff limit. |
| V-007 | PASS | 4.66241e-12 | 0.002 | Finite-junction transverse eigenvalues match the analytic two-root formula. |
| V-008 | PASS | 0.0852465 | 0.1 | Distributed lower-string mass approaches the Rayleigh slope +1/12. |
| V-009 | PASS | 0 | 1e-12 | When all lower elements are slack the bob is in free fall. |
| V-010 | PASS | 7.39568e-06 | 0.001 | Unilateral retension timing converges and the work-energy ledger closes. |
| V-011 | PASS | 6.10364e-10 | 0.0002 | Mirror releases generate mirrored trajectories and swap upper tensions. |
| V-012 | PASS | 9.51821e-05 | 0.0001 | Light-string stiff-limit frequencies are independent of bob mass. |
| V-013 | PASS | 2.22045e-16 | 1e-10 | Pinhole distortion and finite-exposure averaging match independent analytic calculations. |

该报告验证数值实现与解析/半解析基准；不构成实验 `VALIDATED` 或 `PREDICTIVE` 证明。
