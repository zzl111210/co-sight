# NetHeal-Agent 可执行性验收用例

本套件用于快速确认系统不是静态页面，而是能够真正完成“告警取证 → 根因定位 → 审批 → 仿真执行 → KPI 验证 → 报告生成”的可运行闭环。所有执行动作默认处于仿真模式，不会写入真实网络设备。

## 一、端到端业务用例

| 编号 | 故障场景 | 关键输入 | 预期根因 / 根网元 | 关键恢复指标 |
|---|---|---|---|---|
| TC-01 | UPF 负载过高导致视频业务高时延 | CPU 94%、时延 85 ms、丢包率 3.5% | `UPF_OVERLOAD` / `UPF-01` | 时延 22 ms、丢包率 0.4%、CPU 63% |
| TC-02 | 基站回传链路中断导致小区掉线 | 接入成功率 42%、链路可用率 0% | `BACKHAUL_LINK_DOWN` / `LINK-03` | 接入成功率 97%、链路可用率 100% |
| TC-03 | URLLC 切片容量不足导致 SLA 违约 | 带宽利用率 97%、时延 32 ms、丢包率 1.8% | `SLICE_CAPACITY_SHORTAGE` / `slice-urllc` | 带宽利用率 72%、时延 17 ms、丢包率 0.3% |

每个端到端用例还会自动检查：

1. 最终事件状态为 `closed`；
2. 根因置信度不低于 0.8；
3. 生成至少一条 `dry_run=true` 的仿真配置命令；
4. 生成工单、Markdown 报告和 HTML 报告；
5. 审计链包含诊断、修复执行和状态迁移事件。

## 二、安全与可靠性用例

| 编号 | 用例 | 操作 | 预期结果 |
|---|---|---|---|
| TC-04 | RBAC 越权拦截 | 使用 `viewer` 角色重置系统 | 抛出权限错误，操作被拒绝并写入审计 |
| TC-05 | 状态机非法跳转拦截 | 对已经闭环的事件再次执行恢复验证 | 拒绝重复验证，事件状态不被破坏 |

## 三、在控制台逐个验证

1. 打开 `http://127.0.0.1:7788/cosight/netheal.html`。
2. 保持右上角角色为“变更审批人”或“系统管理员”。
3. 在页面右上方的“测试用例”选择器中选择 `TC-01`、`TC-02` 或 `TC-03`。
4. 点击“运行闭环测试”。
5. 查看事件研判、拓扑影响路径、智能体协同链路、KPI 前后对比和审计记录。
6. 看到“闭环测试通过”且事件状态变成“已闭环”，即本用例通过。

如需恢复初始事件队列，请先将角色切换为“系统管理员”，再点击“重置演示”。

## 四、一条命令运行全部用例

在项目根目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_netheal_acceptance.ps1
```

预期终端输出：

```text
[PASS] TC-01 UPF负载过高导致视频业务高时延
[PASS] TC-02 基站回传链路异常导致小区掉线
[PASS] TC-03 URLLC切片资源不足导致工业业务SLA违约
[PASS] TC-04 RBAC越权操作拦截
[PASS] TC-05 事件状态机非法跳转拦截
结果：5/5 通过
```

只运行一个业务场景：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_netheal_acceptance.ps1 -Scenario upf-overload -SkipSafetyCases
```

也可以直接使用 Python：

```powershell
.\.venv\Scripts\python.exe -m app.netheal.acceptance_runner
```

## 五、验收产物

运行后生成：

- `work_space/netheal_acceptance/acceptance_report.md`：人类可读验收报告；
- `work_space/netheal_acceptance/acceptance_report.json`：机器可读结果；
- `work_space/netheal_acceptance/runtime/netheal_outputs/`：三个场景的 Markdown/HTML 闭环报告和 JSON 工单。

验收命令以非零退出码表示存在失败项，便于后续接入 CI。
