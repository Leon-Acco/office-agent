# Office_Agent 服务器部署指南

裸机 + systemd 部署，中间件沿用 `172.16.8.225`（MySQL 30316 / Redis 30689），业务仓库在服务器上 git clone。

## 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | ≥ 3.10 | 代码使用 3.10+ 语法（`str \| None`），install.sh 自动检查/安装 |
| Git | 任意 | clone 业务仓库必需 |
| MySQL | 8.x | 默认沿用 `172.16.8.225:30316`，库 `office_agent_ai` 数据已在库中 |
| Redis | 5+ | 默认沿用 `172.16.8.225:30689` |
| nginx | 可选 | 需要域名/HTTPS 时用，SSE 配置见第 6 步 |
| systemd | — | 服务托管（CentOS 7+/Ubuntu 16.04+ 均自带） |

## 文件清单

| 文件 | 用途 |
|------|------|
| `office-agent.service` | systemd unit 模板（install.sh 按实际路径替换后写入 `/etc/systemd/system/`） |
| `office-agent.env.example` | 环境变量样例（**占位符，不含真实密钥**） |
| `nginx.conf` | nginx 反代配置（可选，SSE 流式必需配置已内置） |
| `install.sh` | 一键安装：检查依赖 → venv → 装包 → 注册 systemd |
| `clone_repos.sh` | 批量 clone 车联网团队 15 个代码仓库到 workspaces |
| `README.md` | 本文件 |

## 部署步骤

### 1. 上传项目代码

```bash
# 方式 A：git clone（如果项目本身入了 GitLab）
git clone <项目仓库地址> /opt/office-agent-src

# 方式 B：开发机 scp/rsync
scp -r D:\code\my_workspace_python\Office_Agent root@<服务器>:/opt/office-agent-src
```

### 2. 运行安装脚本

```bash
cd /opt/office-agent-src
bash deploy/install.sh
```

脚本完成：依赖检查（python3≥3.10、git）→ 同步到 `/opt/office-agent` → 建 venv 装依赖 → 生成 env 文件 → 注册 systemd。

### 3. 填写密钥

```bash
vi /opt/office-agent/deploy/office-agent.env
chmod 600 /opt/office-agent/deploy/office-agent.env
```

将 `__CHANGE_ME__` 占位符替换为真实值（MySQL / Redis / 智谱 LLM API Key）。MySQL 库 `office_agent_ai` 数据已在 225 上，服务首启会自动 ensure 表结构与新增列，**无需重建数据**。

### 配置项说明

`backend/config.py` 中所有配置均有默认值，env 文件只写需要覆盖的项：

| 变量 | 默认 | 说明 |
|------|------|------|
| `APP_HOST` / `APP_PORT` | 0.0.0.0 / 8000 | 监听地址；nginx 反代时改 127.0.0.1 |
| `MYSQL_*` | 172.16.8.225:30316 / office_agent_ai | MySQL 连接（host/port/db/user/password） |
| `REDIS_*` | 172.16.8.225:30689 / db 0 | Redis 连接（host/port/db/password） |
| `LLM_BASE_URL` | https://open.bigmodel.cn/api/anthropic | 智谱 Anthropic 兼容端点 |
| `LLM_API_KEY` | — | **必须配置** |
| `LLM_MODEL` | glm-5.2 | 原生 1M 上下文，无需 beta 参数 |
| `LLM_MAX_TOKENS` | 16384 | 输出预算；推理模型思考也耗输出 token，**勿调小** |
| `LLM_CONCURRENCY` | 2 | 全局 LLM 并发闸，防 429 限流（可慢不能断） |
| `WORKSPACE_ROOT` | `<项目根>/workspaces` | 仓库 clone/上传/协作落盘根目录 |
| `DEBUG` | true | 生产务必 false |

### 4. 启动并验证

```bash
systemctl start office-agent
systemctl status office-agent
journalctl -u office-agent -f        # 观察日志

curl http://127.0.0.1:8000/api/health      # 健康检查
curl http://127.0.0.1:8000/api/llm/test    # LLM 连通性
```

### 5. clone 业务仓库

```bash
# 前置：服务器 SSH key 已加到 GitLab（gitlab.dstcar.com）
ssh-keygen -t ed25519 -C "office-agent-server"
cat ~/.ssh/id_ed25519.pub   # 粘贴到 GitLab SSH Keys
ssh -T git@gitlab.dstcar.com

bash /opt/office-agent/deploy/clone_repos.sh
```

15 个仓自动 clone（14 个 `prod` 分支 + `dst-iot-protocol-tbox` 为 `v1.0.0`）。另有 2 个无 origin 的目录（`business adas`、`dst-iot-da`）需手动 scp 上传，脚本末尾会提示命令。

### 6.（可选）配置 nginx 反代

```bash
cp /opt/office-agent/deploy/nginx.conf /etc/nginx/conf.d/office-agent.conf
# 把 env 中 APP_HOST 改为 127.0.0.1，重启服务
systemctl restart office-agent
nginx -t && systemctl reload nginx
```

**SSE 流式注意**：聊天接口是 SSE 长连接，nginx 配置里的 `proxy_buffering off` / `proxy_read_timeout 600s` 不能删，否则前端收不到逐字输出。

## 运维命令

```bash
systemctl restart office-agent     # 重启
journalctl -u office-agent -f      # 实时日志
journalctl -u office-agent --since today | grep -i error   # 今天的错误
```

## 更新与回滚

**更新代码**：重新上传代码到源码目录后再跑一遍 `install.sh`（rsync 增量同步，跳过 `.venv`/`workspaces`/`__pycache__`，已生成的 env 文件不会被覆盖），然后 `systemctl restart office-agent`。

```bash
# 开发机推送更新
scp -r D:\code\my_workspace_python\Office_Agent root@<服务器>:/opt/office-agent-src
ssh root@<服务器> "cd /opt/office-agent-src && bash deploy/install.sh && systemctl restart office-agent"
```

**回滚**：把上一版源码目录重新执行一次上述流程即可。数据库表结构只增不删（首启 ensure 模式），回滚代码无需动库。

## 初始化演示数据（可选）

服务器上需要重建车联网团队演示数据时（幂等，可重跑）：

```bash
cd /opt/office-agent
.venv/bin/python scripts/_init_iov_team.py   # 7 员工/6 领域/仓库绑定
.venv/bin/python scripts/_seed_knowledge.py  # 种子 6 条领域知识
```

## 常见问题

| 现象 | 可能原因 | 处理 |
|------|---------|------|
| install.sh 报 ensurepip is not available | Ubuntu/Debian 的 python3 不带 venv 模块 | `apt install python3.12-venv`（版本号对应 python3 版本），删掉半成品 `.venv` 后重跑；新版 install.sh 已自动检测安装 |
| 启动报 DB 初始化失败 | 服务器与 225:30316 不通，或密钥填错 | `telnet 172.16.8.225 30316` 验证网络；检查 env 文件 |
| 前端聊天不逐字输出 | nginx 缓冲了 SSE | 确认 `proxy_buffering off` 生效 |
| clone 仓库 Permission denied | 服务器 SSH key 未加 GitLab | 执行第 5 步前置 |
| 员工 Agent 看不到仓库 | workspaces 目录与 `WORKSPACE_ROOT` 不一致 | env 中显式设置 `WORKSPACE_ROOT=/opt/office-agent/workspaces` |
| LLM 返回空/报错 429 | 智谱限流或欠费（错误码 1113=欠费） | 降 `LLM_CONCURRENCY`；充值账户 |
