# NetHeal-Agent 仿真评测报告

## 评测口径

- 数据集：仓库内 `campus-5g` 合成数据集 v1。
- 样本数：3 个故障场景。
- 场景：UPF 过载、回传链路中断、URLLC 切片资源不足。
- NetHeal 方法：告警 + KPI + 拓扑 + 专家规则融合排序。
- 基线方法：只读取第一条最高等级告警，并按告警症状分类。
- 运行环境：本地标准库确定性工具链，不包含大模型 API 网络耗时。

## 实测结果

| 指标 | 单告警基线 | NetHeal-Agent |
|---|---:|---:|
| 根因定位准确率 | 33.33% | 100.00% |
| 恢复验证通过率 | 不支持 | 100.00% |
| 平均告警压缩率 | 不支持 | 77.78% |
| 本地诊断与验证平均耗时 | 未测 | 约 1.18 ms |

逐案例结果：

| 场景 | 真实根因 | 基线预测 | NetHeal 预测 | 置信度 | 恢复验证 |
|---|---|---|---|---:|---|
| UPF 过载 | `UPF_OVERLOAD` | `UPF_OVERLOAD` | `UPF_OVERLOAD` | 100% | 通过 |
| 回传链路中断 | `BACKHAUL_LINK_DOWN` | `RADIO_CELL_FAULT` | `BACKHAUL_LINK_DOWN` | 100% | 通过 |
| 切片资源不足 | `SLICE_CAPACITY_SHORTAGE` | `TRANSPORT_QUALITY_FAULT` | `SLICE_CAPACITY_SHORTAGE` | 100% | 通过 |

## 可复现命令

```powershell
python -m app.netheal.evaluation --workspace .\work_space
```

机器可读结果保存到 `work_space/netheal_outputs/evaluation_results.json`。

## 结果限制

当前 100% 准确率来自仅包含 3 类明确故障的合成小数据集，不能外推为真实网络准确率。文档和答辩应将它表述为“功能性基准测试”，不能声称生产效果。

下一阶段建议：

1. 每类扩充至少 30 个带噪声变体。
2. 增加告警缺失、KPI 延迟、多根因并发和未知故障。
3. 冻结训练/规则调试集与测试集。
4. 分别统计 Top-1、Top-3 根因准确率、误修复率、平均闭环时间和回溯成功率。
5. 单独测量包含 LLM 推理和前端事件传输的端到端耗时。
