# NetHeal-Agent Docker 部署指南

> 5G 校园专网多智能体故障诊断与自愈系统 — 一键 Docker 部署

## 前提条件

- **Docker** 20.10+ 已安装
- 有效的 DeepSeek（或兼容 OpenAI 接口）API Key

## 快速开始（3 步）

```bash
# 1. 构建镜像
docker build -t netheal-agent .

# 2. 配置 API Key（复制模板并编辑）
cp .env_template .env
# 编辑 .env，填入你的 API_KEY、API_BASE_URL、MODEL_NAME

# 3. 启动
docker run -d \
  --name netheal-agent \
  -p 7788:7788 \
  -v $(pwd)/.env:/app/.env:ro \
  -v $(pwd)/work_space:/app/work_space \
  netheal-agent
```

打开浏览器访问：

| 页面 | 地址 |
|------|------|
| 驾驶舱 | http://localhost:7788/cosight/netheal.html |
| API 配置 | http://localhost:7788/cosight/settings.html |
| Co-Sight 工作台 | http://localhost:7788/cosight/ |
| API 文档 | http://localhost:7788/docs |

## 使用 docker-compose（推荐）

```bash
# 1. 配置 .env
cp .env_template .env
nano .env   # 填入 API Key

# 2. 一键启动
docker-compose up -d

# 3. 查看日志
docker-compose logs -f

# 4. 停止
docker-compose down
```

## 构建离线镜像包（给没有网络的环境）

```bash
# 在能上网的机器上
docker build -t netheal-agent .
docker save -o netheal-agent.tar netheal-agent

# 拷贝 netheal-agent.tar 到目标机器，加载
docker load -i netheal-agent.tar
docker run -d -p 7788:7788 -v ./.env:/app/.env:ro netheal-agent
```

## 验证部署

```bash
# 健康检查
curl http://localhost:7788/api/netheal/v1/health

# 预期输出
# {"status":"healthy","database":{"ok":true,"engine":"sqlite","journal_mode":"WAL"},...}
```

## 驾驶舱快速验收

1. 打开 `http://localhost:7788/cosight/netheal.html`
2. 右上角角色选 **"变更审批人"**
3. 选择 **TC-01** → 点击 **"运行闭环测试"**
4. 观察全自动流程：诊断 → 审批 → 仿真执行 → KPI 验证
5. 闭环后点击 **"下载报告"** 获取 HTML 文档

## 镜像内容

本镜像基于 `python:3.13-slim`，包含：

- ✅ Co-Sight 多智能体框架
- ✅ NetHeal-Agent 5G 专网运维场景（P0 全部功能）
- ✅ JWT 认证 + 审批工作流（P1）
- ✅ 后台任务队列 + 幂等重试（P1）
- ✅ 数据库迁移 + 多租户（P1）
- ✅ SSE 实时事件推送（P1）
- ✅ 报告全文检索 + 历史趋势（P1）
- ✅ KPI 时序图 + 候选根因对比（P2）
- ✅ 向量检索 + 图推理融合诊断（P2）
- ✅ 评估图表生成 + 演示回放（P2）
- ✅ Web UI API 配置页面
- ✅ 4 个端到端故障场景（TC-01~TC-03, TC-06）

## 常见问题

**Q: 启动后页面打不开？**
```bash
docker logs netheal-agent  # 查看日志
docker exec netheal-agent curl localhost:7788/api/netheal/v1/health  # 内部检查
```

**Q: 提示 API Key 未配置？**
访问 `http://localhost:7788/cosight/settings.html` 在 Web UI 中填写，或直接编辑 `.env` 后重启容器。

**Q: NetHeal 驾驶舱不依赖大模型吗？**
TC-01~TC-06 的闭环测试使用确定性诊断引擎，不消耗 API 额度。只有 Co-Sight 通用工作台的多智能体任务才需要大模型。

**Q: 如何持久化数据？**
`work_space/` 目录已通过 volume 挂载到宿主机，包含 SQLite 数据库、报告、工单和日志。
