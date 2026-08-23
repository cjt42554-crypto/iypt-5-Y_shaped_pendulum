# 当前任务｜审查后科学修订与后续资格验证

## 任务身份

- 候选来源：2026-08-23 Y 形摆审查后修订版。
- 治理整理起点提交：
  **7e08546d0a6e06b19f3331088a2427a01b9142c7**。
- 规范分支：**main**，也是唯一允许长期存在和直接 commit/push 的分支。
- 整理开始时所在的 **codex/correct-04-scientific-revision** 仅作为历史来源；整理成果合入
  **main** 后删除，不作为后续工作入口。
- 当前目标：保留并复核纠正后的候选，完成新路径复现、独立审查和后续数值资格；
  未经明确批准不晋升到根目录 01/02/03。

## 内容导航

- [候选区说明](候选实现或候选内容/README.md)
- [候选修订入口](候选实现或候选内容/04_审查后修订版_2026-08-23/README.md)
- [变更映射](管理/变更映射.md)
- [验收清单](管理/验收清单.md)
- [修改记录](管理/修改记录.md)
- [验证记录](管理/验证记录.md)
- [当前审查](审查与复现/当前审查/README.md)
- [历史审查](审查与复现/历史审查/README.md)

## 当前状态

~~~text
WORKSPACE_ORGANIZED = true
CANDIDATE_PROMOTED = false
HISTORICAL_CODE_EVIDENCE = CODE_VERIFIED
READY_FOR_NUMERICAL_QUALIFICATION = true
NUMERICALLY_QUALIFIED = false
EXPERIMENTALLY_VALIDATED = false
PREDICTIVE = false
CURRENT_INDEPENDENT_REVIEW = NOT_RUN
REORGANIZATION_TESTS = PASS（现场 NumPy 2.5.2；完整证据包未重生成）
~~~

历史 **CODE_VERIFIED** 证据绑定候选内部记录的固定源码提交和旧路径口径。目录治理后，应先读
[验证记录](管理/验证记录.md)；不得用旧绝对命令直接宣称当前提交同样通过。

## 工作边界

1. 默认只修改本目录及其子目录。
2. 根目录成熟基线只用于读取、比较和非写回验证。
3. 新实现放入候选区；计划、映射、验收和结果必须同步落入管理区。
4. 新审查先进入 **当前审查**；被新结论取代的审查才进入 **历史审查**。
5. 所有阶段成果直接在 **main** 正常 commit/push；是否晋升由验收与用户批准决定。

## 下一位协作者的起步动作

1. 先读根目录 **每次任务前阅读/** 全部必读文件。
2. 实时检查 Git 状态，不以本页的起点提交代替现场 HEAD。
3. 查看 [验证记录](管理/验证记录.md) 与
   [当前审查](审查与复现/当前审查/README.md)。
4. 若继续候选代码，先确认活动证据驱动器和 README 使用的是新工作区路径。
5. 若准备晋升，必须先完成 [验收清单](管理/验收清单.md) 并取得明确授权。
