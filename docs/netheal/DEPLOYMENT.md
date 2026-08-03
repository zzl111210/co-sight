# NetHeal-Agent 部署与安全配置

本文档用于本地演示、团队联调和容器部署。系统当前只允许仿真执行，`real_network_write_enabled` 始终为 `false`。

## 本地一键初始化

Windows PowerShell：

```powershell
.\setup-netheal.ps1
```

Linux/macOS：

```bash
./setup-netheal.sh
```

脚本会创建 `.venv`、安装锁定依赖、在缺失时复制 `.env_template`，然后运行全部 NetHeal 测试和 6 个验收场景。已有 `.env` 不会被覆盖。

启动服务：

```powershell
.\.venv\Scripts\python.exe cosight_server\deep_research\main.py
```

访问地址：

- 运维中心：`http://localhost:7788/cosight/netheal.html`
- 安全设置：`http://localhost:7788/cosight/settings.html`
- 健康检查：`http://localhost:7788/api/netheal/v1/health`

## 配置原则

1. 复制 `.env_template` 为 `.env`，只在本机填写 `API_KEY`、`API_BASE_URL` 和 `MODEL_NAME`。
2. `.env` 已被 Git 和 Docker 构建上下文排除，严禁提交、截图或通过前端表单传输密钥。
3. 设置页只读取“是否配置”和非敏感元数据；API 不返回密钥内容。
4. 开发模式兼容 `X-NetHeal-Actor`、`X-NetHeal-Role` 请求头，便于比赛演示。
5. 生产模式设置 `NETHEAL_AUTH_MODE=production` 和强随机 `NETHEAL_TOKEN_SECRET`。写操作必须携带签名 Bearer Token，本地登录接口自动关闭。

本地登录接口仅用于开发环境：

```http
POST /api/netheal/v1/auth/login
Content-Type: application/json

{"actor":"operator-a","role":"operator","tenant_id":"campus-5g"}
```

生产环境应由组织的 OIDC/SSO 网关签发身份，再按统一鉴权方案替换本地签发器。

## Docker Compose

先创建本地配置文件，并设置生产签名密钥：

```powershell
Copy-Item .env_template .env
```

然后构建并启动：

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f netheal
```

停止服务：

```bash
docker compose down
```

容器以 UID 10001 的非 root 用户运行，删除全部 Linux capabilities，启用 `no-new-privileges`，并将 `work_space` 与 `logs` 映射为持久卷。

不要把 7788 端口直接暴露到公网；正式部署应增加 TLS 反向代理、访问控制和速率限制。

## 上线前检查

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_netheal*.py" -v
.\.venv\Scripts\python.exe -m app.netheal.acceptance_runner
node --check cosight_server/web/js/netheal.js
node --check cosight_server/web/js/netheal-settings.js
git diff --check
```

必须满足：

- 23 项自动测试全部通过；
- TC-01、TC-02、TC-03、TC-06 诊断闭环通过；
- TC-04 RBAC 越权拦截通过；
- TC-05 非法状态跳转拦截通过；
- 健康检查显示数据库正常、仿真模式开启、真实网络写入禁用；
- `git status` 中不存在 `.env`、数据库、报告或日志。

当前开发机没有安装 Docker，因此已完成 Dockerfile 审查与 Compose YAML 静态解析，但镜像仍需在安装 Docker 的环境执行一次 `docker compose up --build` 验证。
