# NetHeal-Agent 演示指南

## 1. 离线自检

无需配置大模型：

```powershell
python -m unittest discover -s tests -v
python -m app.netheal.evaluation --workspace .\work_space
python -m app.netheal.scenario_runner --scenario upf-overload --workspace .\work_space
```

检查以下文件：

- `work_space/netheal_outputs/NetHeal_Report_upf-overload.html`
- `work_space/netheal_outputs/NetHeal_Report_upf-overload.md`
- `work_space/netheal_outputs/work_order_upf-overload.json`
- `work_space/netheal_outputs/evaluation_results.json`

## 2. Co-Sight 页面演示

复制 `.env_template` 为 `.env` 并配置模型后：

```powershell
python cosight_server/deep_research/main.py
```

打开 `http://localhost:7788/cosight/`。

主演示提示：

> 请诊断 campus-5g 当前视频业务时延升高问题，定位根因，生成修复方案并验证恢复效果。

预期页面过程：

1. planner 展示 8 步 DAG，前四步并发。
2. 工具事件依次出现告警、KPI、拓扑和知识取证。
3. 根因定位显示 `UPF_OVERLOAD`、`UPF-01` 和规则 `KB-UPF-001`。
4. 修复步骤显示风险等级、仿真命令、人工审批工单与回滚策略。
5. 验证步骤显示时延 85→22 ms、丢包率 3.5%→0.4%。
6. 最后打开 HTML 故障闭环报告。

## 3. 扩展案例

回传链路：

```powershell
python -m app.netheal.scenario_runner --scenario backhaul-link-down --workspace .\work_space
```

切片资源：

```powershell
python -m app.netheal.scenario_runner --scenario slice-capacity-shortage --workspace .\work_space
```

## 4. 答辩表述

- 明确说明当前为合成数据和仿真命令。
- 强调 Co-Sight 负责多智能体规划、DAG 并发调度和工具事件展示。
- 强调 NetHeal 场景包负责通信数据、证据融合、修复安全和量化验证。
- 不把 3 个样本的 100% 准确率表述为生产网络效果。
- 演示真实变更分支时只展示审批和 dry-run，不执行真实网元配置。
