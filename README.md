# Agent 办公室(Office_Agent)

多 Agent 虚拟办公室系统:把一家"虚拟公司"搬进浏览器——公司 → 部门 → 领域 → 员工(Agent)四级组织,员工绑定代码仓库与知识库,通过总前台分诊、单聊、协作会议室完成问答与多人协作任务。

- 后端:FastAPI + SQLAlchemy(async)+ MySQL + Redis
- LLM:智谱 BigModel `glm-5.2`(Anthropic 兼容端点,原生 1M 上下文),provider 内含 OpenAI→Anthropic 翻译层,可切其他模型
- 前端:无构建单页应用(原生 HTML/CSS/JS,`frontend/static/`)
- 工具生态:MCP 客户端(SSE transport)+ 内置工具注册表

## 核心功能

| 页面 | 说明 |
|---|---|
| 公司总览 | 组织 KPI、部门分布、员工状态仪表盘 |
| 总前台 | 群聊入口,三级分诊链(总前台 → 部门对接人 → 领域员工),SSE 流式输出,Markdown 代码/表格卡片 |
| 员工办公室 | 员工列表与单聊(绕过总前台分诊) |
| 协作会议室 | 多员工并行产出:草案 → 两轮互评 → 会议纪要合成,成果落盘 `workspaces/collab_docs/` |
| 关系图谱 | 公司→部门→领域→员工四环核心圈层布局,点阵网格底 |
| 资源中心 | 文档资源 + 代码仓库双卡;仓库支持 clone/浏览/搜索/分支切换/编辑/定时拉取 |
| 管理与治理 | 组织、员工、技能、工具、角色包、仓库绑定等后台管理 |

## 快速开始(Windows 开发环境)

### 环境要求

- Python 3.10+
- MySQL 8.x(默认指向 `172.16.8.225:30316`,库 `office_agent_ai`,首启自动建表/补列)
- Redis(默认 `172.16.8.225:30689`)
- Git(代码仓库功能需要)
- 智谱 BigModel API Key

### 安装与启动

```bash
pip install -r requirements.txt
```

三种启动方式(端口固定 8000,启动前都会清理旧进程):

| 方式 | 命令 | 适用 |
|---|---|---|
| 一键脚本 | `start.bat` | 日常使用(自动建 venv、装依赖) |
| Python 脚本 | `python start.py` | 带环境自检与启动后验证 |
| 独立后台进程 | `powershell -ExecutionPolicy Bypass -File start_dev.ps1` | 服务不随终端会话回收,日志落 `logs/` |

启动后访问:

- 应用入口:http://localhost:8000/
- API 文档:http://localhost:8000/docs
- 健康检查:http://localhost:8000/api/health
- LLM 连通性:http://localhost:8000/api/llm/test

停止:`stop.bat`

### 初始化演示数据(可选)

```bash
python scripts/_init_iov_team.py   # 车联网团队:7 员工/6 领域/仓库绑定(幂等可重跑)
python scripts/_seed_knowledge.py  # 种子 6 条领域知识
```

## 配置项

`backend/config.py` 中所有配置均有默认值,生产环境用环境变量覆盖(参考 `deploy/office-agent.env.example`):

| 变量 | 默认 | 说明 |
|---|---|---|
| `MYSQL_HOST` / `MYSQL_PORT` / `MYSQL_DB` / `MYSQL_USER` / `MYSQL_PASSWORD` | 172.16.8.225:30316 / office_agent_ai | MySQL 连接 |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_DB` / `REDIS_PASSWORD` | 172.16.8.225:30689 / 0 | Redis 连接 |
| `LLM_BASE_URL` | https://open.bigmodel.cn/api/anthropic | 智谱 Anthropic 兼容端点 |
| `LLM_API_KEY` | — | **必须配置** |
| `LLM_MODEL` | glm-5.2 | 模型名 |
| `LLM_MAX_TOKENS` | 16384 | 输出预算(推理模型思考也耗输出 token,勿调小;结构化调用 ≥2000) |
| `LLM_CONCURRENCY` | 2 | 全局 LLM 并发闸,防 429 限流(可慢不能断) |
| `LLM_TIMEOUT` | 60 | 单次调用超时(秒) |
| `WORKSPACE_ROOT` | `<项目根>/workspaces` | 仓库 clone / 上传 / 协作落盘根目录 |
| `DEBUG` | true | 生产设 false |

## 目录结构

```
Office_Agent/
├── backend/                # FastAPI 后端
│   ├── main.py             # 入口:注册 10 个 router + 静态托管 + 生命周期
│   ├── config.py           # 全部配置(环境变量可覆盖)
│   ├── database.py         # 异步引擎/会话,get_db 依赖(yield 后自动 commit)
│   ├── routers/            # auth/dashboard/agents/frontdesk/knowledge/tasks/graph/admin/governance/repos
│   ├── models/             # SQLAlchemy 模型(公司/员工/任务/知识/治理/资源等)
│   ├── runtime/            # Agent 运行时:provider/llm/runner/context/hooks/mcp_client/tool_registry
│   ├── services/           # git_service/repo_registry/repo_scheduler/file_service/skill_validator 等
│   ├── agents/             # 分诊图谱/多 Agent 编排
│   └── schemas/            # Pydantic 模式
├── frontend/static/        # 无构建 SPA:index.html + js/{app,chat,admin,graph,login-particles,toast}.js
├── deploy/                 # 服务器部署六件套(systemd/nginx/install/clone/env 样例),见 deploy/README.md
├── scripts/                # 运维与验证脚本(见 scripts/README.md)
├── workspaces/             # 运行时数据:git 仓库/collab_docs/uploads/agents md(勿提交 git)
├── logs/                   # 运行日志
├── start.bat / start.py / start_dev.ps1 / stop.bat   # 启停脚本
└── requirements.txt
```

## 开发约定(重要)

1. **本项目当前未入 git,回滚全靠 `.bak` 备份链**:`frontend/static/` 下 `index.html.bak-*`、`js/*.bak-*` 按迭代轮次命名(softui < v3 < v4 < v5 < v6 < v7)。大改前端前先留备份;回滚 = 把对应 `.bak` 复制回原文件名。
2. **前端缓存破坏**:修改 `frontend/static/js/*.js` 后,必须在 `index.html` 中把对应 `<script src="...?v=N">` 的 N 加一,否则浏览器拿旧缓存。
3. **chat.js 含 `\x00` 占位字节**:编辑器精确匹配替换会失败,需用 Python 二进制补丁方式修改。
4. **日志统一落 `logs/`**,不要在根目录写日志文件。
5. **流式接口(SSE)内写库必须立即 commit**,否则连接挂起期间长事务锁表。

## 生产部署

见 **[deploy/README.md](deploy/README.md)**:裸机 + systemd 一键部署,中间件沿用 172.16.8.225(MySQL 30316 / Redis 30689),含 nginx SSE 反代配置与运维命令。

## 常见问题

| 现象 | 可能原因 | 处理 |
|---|---|---|
| LLM 429 | 智谱限流或欠费(错误码 1113=欠费) | 降 `LLM_CONCURRENCY`;先查错误码再排查 |
| 协作会议室有人无产出 | 瞬时网络错误被误判不重试(httpx 超时 `str(e)` 为空串) | 已内置三层防护:isinstance 类型判定 + 整轮重试 + 并发闸;查日志 `[LLM 调用失败` 标记 |
| LLM 返回空串 | 推理模型小 max_tokens 被思考耗光 | `LLM_MAX_TOKENS` ≥ 16384;结构化调用 ≥2000 且空返重试 |
| 仓库列表出现 collab_docs/uploads 假仓库 | 历史脏登记 | 已在 repo_registry/repos 双层修复,列表接口自动清理 |
| 前端样式/脚本不更新 | 浏览器缓存 | 确认改 js 时已 bump `?v=N`;硬刷新 Ctrl+F5 |
