"""
Office_Agent 配置模块
统一管理 MySQL / Redis / LLM 等连接配置
"""
import os

# ── 项目路径 ────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ── 应用配置 ────────────────────────────────────
APP_NAME = "Agent 办公室"
APP_VERSION = "0.2.0"
DEBUG = os.getenv("DEBUG", "true").lower() == "true"
CORS_ORIGINS = ["*"]

# ── MySQL 配置 ──────────────────────────────────
MYSQL_HOST = os.getenv("MYSQL_HOST", "172.16.8.225")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "30316"))
MYSQL_DB = os.getenv("MYSQL_DB", "office_agent_ai")
MYSQL_USER = os.getenv("MYSQL_USER", "test-admin")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "i1q7k7lmQZ")

# SQLAlchemy 异步连接 URL（pool 参数由 create_async_engine 管理，不放 URL）
DATABASE_URL = (
    f"mysql+aiomysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
)
# 同步 URL（Alembic 迁移、DDL 执行用）
DATABASE_URL_SYNC = (
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}"
    f"@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DB}?charset=utf8mb4"
)

# ── Redis 配置 ──────────────────────────────────
REDIS_HOST = os.getenv("REDIS_HOST", "172.16.8.225")
REDIS_PORT = int(os.getenv("REDIS_PORT", "30689"))
REDIS_DB = int(os.getenv("REDIS_DB", "0"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "a21pHjguXZha")
REDIS_URL = f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{REDIS_DB}"

# ── 智谱 BigModel LLM 配置 ───────────────────────────
# 模型：glm-5.2（智谱开放平台 Anthropic 兼容端点，协议为 Anthropic Messages，路径约定 /api/anthropic/v1/messages）
# glm-5.2 原生支持 1M 上下文窗口 + 128K 最大输出，无需额外 beta 参数
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/anthropic")
LLM_API_KEY = os.getenv("LLM_API_KEY", "e42a240b85fe4b4a8e52440b4331d6e9.2HhhNbsBjfk6wSA0")
LLM_MODEL = os.getenv("LLM_MODEL", "glm-5.2")
# 输出预算:glm-5.2 为推理模型,思考过程同样消耗输出 token,
# 4096 对长 Markdown 回答(表格+代码块)容易顶满被截断,默认提到 16384(模型上限 128K)
LLM_MAX_TOKENS = int(os.getenv("LLM_MAX_TOKENS", "16384"))
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
LLM_TIMEOUT = int(os.getenv("LLM_TIMEOUT", "60"))
# 全局 LLM 并发上限:会议室多子任务并发 + 前台聊天叠加会触发智谱 429 限流,
# 用信号量把并发压在配额内(可慢不能断,排队等待而非直接报错)
LLM_CONCURRENCY = int(os.getenv("LLM_CONCURRENCY", "2"))
