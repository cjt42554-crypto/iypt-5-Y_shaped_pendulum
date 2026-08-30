# 既有实验门复用矩阵

## 1. 单一规范输入

E0 直接复用既有[实验门最小测量清单](../F0_正式整理与解析稳定性图谱/07_实验门最小测量清单/EXPERIMENT_GATE_MINIMUM_MEASUREMENTS.md)。该文件已经规定“最低测什么”和模型判别顺序；E0 只补机器可执行层，不建立第二份测量需求清单。

## 2. 要求映射

| 既有要求 | 处理方式 | E0 执行层 |
|---|---|---|
| 最低仪器、双相机和公共同步 | 直接引用 | `03_CAMERA_TRAJECTORY_DATA_CONTRACT.md`、完整相机 schema 与 2D detection schema |
| A 级装置几何、质量和材料输入 | 直接引用 | `01_MEASUREMENT_REGISTER_PROTOCOL.md` 与长表式测量 schema |
| 力--伸长、循环滞回和速率效应 | 直接引用 | 材料试验 manifest 与原始文件哈希合同 |
| 小振幅两个方向、每方向至少 5 次 | 直接引用 | 预生成且不可复用的 run ID 与纳入/排除规则 |
| 四个振幅层、每级至少 5 次 | 直接引用 | 3:2 主矩阵与升级停止规则 |
| 失张、接近和接触筛查 | 直接引用 | 事件代码、检测下限、第一事件截断与失败记录 |
| 从低复杂度模型开始判别 | 直接引用 | Torus/Cable 只读适配和 `OUT_OF_MODEL_DOMAIN` |
| 原始数据、配置、代码和结论可追踪 | 直接引用 | planned slot、actual attempt、逐帧时间、交叉核验身份与 SHA-256 链 |
| 实验门五项通过条件 | 保持为最终实验门 | E0-A1 至 E0-A10 只验证准备包 |

## 3. E0 新增而既有清单未冻结的内容

E0 新增以下执行合同：

1. 每一个测量量的机器字段、来源类型和条件必填关系；
2. 第一轮 70 条结果型运行的 run ID、机器冻结的释放振幅、几何分配和分析预注册；
3. 每个 pilot/full-round repeat 的计划 slot、实际 attempt、进行中 campaign、硬停止 disposition 与 retry parent 的采集 ledger；
4. 世界坐标、完整 Brown--Conrady 相机、逐相机原始/对齐帧时间、掉帧和双目三角化数据合同；
5. 原始视频到 2D detection、逐帧 $2\times2$ covariance 和 3D $3\times3$ covariance 的 schema 校验、身份交叉核验与哈希链；
6. 大型数组 NPZ 与紧凑 JSON manifest 的分离；
7. `YPS-EXPERIMENT-COMMON-OBSERVABLES-1.2` 共同比较接口及 trajectory source identity 核验；
8. 测量 ID、测量 bundle、实际派生内容及其 canonical hash、轨迹和兼容性证据到正式输入的绑定；
9. 正式 Torus/Cable 输入不兼容时的失败关闭状态；
10. 合成夹具不得升级为实验结论的机器检查。

## 4. 不重复实现的内容

E0 不复制正式方程、ODE、ensemble engine、Brown--Conrady 物理定义或实验门清单。正式模型适配器必须指向仓库内的正式包；若正式输入接口不能无损表达实测初态，记录 `ADAPTER_LIMITATION_MEASURED_INITIAL_STATE_NOT_REPRESENTABLE`，不得因此修改正式程序。
