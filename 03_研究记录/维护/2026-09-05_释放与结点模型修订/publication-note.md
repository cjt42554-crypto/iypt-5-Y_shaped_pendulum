# 发布收尾记录

验证运行 `33935164378` 的 22 项理论核查、16 项文档自测、入口检查、113 项原求解器回归全部通过；其工作流整体失败发生在提交前，原因是两份本地超时原始日志的截断行保留了行末空格。未发生物理检查或求解器回归失败。

本次恢复原始 artifact（SHA-256 `895010ff478f23f291814de41e2c4c6d88d138a9dd7a33a50d91e24c1e8acda3`），核对理论与检查脚本哈希、实际测试计数及退出码；不重复解释为新一次完整回归。只把上述两份原始日志排除在 Git 空白风格检查外，其余暂存文件照常检查，日志字节不改写，验证阈值不修改。初次恢复运行 `33935463006` 在 artifact 跨主机重定向处认证失败，未提交；改用不向跨主机重定向转发 API Authorization 的下载方式，仍校验同一 artifact 哈希。

原始日志 SHA-256：

- `solver-regression-initial-timeout.txt`：`c68c5d1d720872c3c0d6fc464d5b16ef35db6cff66dbb443fec7444403b9b8dc`
- `solver-regression-local-timeout.txt`：`c68c5d1d720872c3c0d6fc464d5b16ef35db6cff66dbb443fec7444403b9b8dc`
