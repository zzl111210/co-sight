# NetHeal-Agent 场景包

NetHeal-Agent 是在 Co-Sight 通用框架之上的 5G 校园专网智能运维场景增强，不复制或替换原有 planner、DAG 调度器与前端。

## 主案例

`upf-overload`：UPF-01 负载过高，导致视频切片时延从 18 ms 上升到 85 ms、丢包率从 0.2% 上升到 3.5%。仿真修复后时延恢复到 22 ms，丢包率恢复到 0.4%。

扩展案例：

- `backhaul-link-down`：基站回传链路中断导致小区掉线。
- `slice-capacity-shortage`：URLLC 切片资源不足导致工业业务 SLA 违约。

## 专用工具

1. `read_alarm_events`
2. `query_kpi_metrics`
3. `query_network_topology`
4. `retrieve_fault_knowledge`
5. `diagnose_root_cause`
6. `generate_repair_plan`
7. `generate_config_commands`
8. `generate_work_order`
9. `verify_recovery`
10. `generate_incident_report`

所有工具返回 JSON 证据，配置命令默认为 `dry_run`，不连接或修改真实网元。

## 不依赖大模型的一键验证

```powershell
python -m app.netheal.scenario_runner --scenario upf-overload --workspace .\work_space
python -m app.netheal.evaluation --workspace .\work_space
python -m app.netheal.robustness_evaluation
python -m unittest discover -s tests -v
```

输出文件位于 `work_space/netheal_outputs/`。

## Co-Sight 前端演示

按项目根目录的 `.env_template` 配置兼容模型后启动原服务：

```powershell
python cosight_server/deep_research/main.py
```

访问 `http://localhost:7788/cosight/`，输入：

> 请诊断 campus-5g 当前视频业务时延升高问题，定位根因，生成修复方案并验证恢复效果。

NetHeal 场景提示会要求 planner 创建 4 路并行取证的 8 步 DAG，Actor 随后调用上述专用工具完成闭环。

专业运维驾驶舱：

`http://localhost:7788/cosight/netheal.html`

驾驶舱通过 `/api/netheal/v1` 管理事件状态、审批、仿真执行、恢复验证和审计；运行时状态保存在 git 忽略的 `work_space/netheal/netheal.db`。
