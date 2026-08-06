"""
Office_Agent - FastAPI 后端入口
===============================
多 Agent 虚拟办公室后端服务。
MySQL + Redis + 火山 LLM（GLM-5.2）
"""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pathlib import Path

from backend.routers import (
    auth, dashboard, agents, frontdesk,
    knowledge, tasks, graph, admin, governance, repos,
)
from backend.models.models import HealthResponse
from backend.config import APP_NAME, APP_VERSION


# ── 生命周期管理 ──────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动与关闭钩子"""
    # === 启动 ===
    print("[startup] 正在初始化数据库...")
    try:
        from backend.database import init_db
        await init_db()
        print("[startup] 数据库初始化完成")
    except Exception as e:
        print(f"[startup] 数据库初始化失败: {e}")
        print("[startup] 请确保 MySQL 可访问，将使用空数据库模式继续")

    # 仓库定时自动刷新调度器(60s 轮询,到期仓库 git pull)
    import asyncio
    from backend.services.repo_scheduler import auto_refresh_loop
    scheduler_task = asyncio.create_task(auto_refresh_loop())
    print("[startup] 仓库定时刷新调度器已启动")

    # === 运行 ===
    yield

    # === 关闭 ===
    scheduler_task.cancel()
    try:
        await scheduler_task
    except asyncio.CancelledError:
        pass
    from backend.services.redis_client import close_redis
    await close_redis()
    print("[shutdown] Redis 连接已关闭")


# ── FastAPI 应用 ──────────────────────────────
app = FastAPI(
    title=f"{APP_NAME} API",
    description="多 Agent 虚拟办公室后端服务",
    version=APP_VERSION,
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── 注册 API 路由 ─────────────────────────────
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(agents.router)
app.include_router(frontdesk.router)
app.include_router(knowledge.router)
app.include_router(tasks.router)
app.include_router(graph.router)
app.include_router(admin.router)
app.include_router(governance.router)
app.include_router(repos.router)


# ── 健康检查 ──────────────────────────────────
@app.get("/api/health")
async def health_check():
    return HealthResponse()


# ── LLM 连接测试 ──────────────────────────────
@app.get("/api/llm/test")
async def test_llm():
    """测试 LLM 连接是否正常"""
    from backend.services.llm import test_connection
    return await test_connection()


# ── 前端静态文件 ──────────────────────────────
BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
FRONTEND_DIR = PROJECT_ROOT / "frontend" / "static"

if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse)
    async def serve_index():
        """根路由：返回前端首页"""
        index_path = FRONTEND_DIR / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))
        return HTMLResponse("<h1>frontend/static/index.html not found</h1>", status_code=404)


# ── 启动入口 ──────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print("=" * 50)
    print(f"  {APP_NAME} 启动中...")
    print(f"  前端页面: http://localhost:8000")
    print(f"  API 文档: http://localhost:8000/docs")
    print(f"  LLM 测试: http://localhost:8000/api/llm/test")
    print("=" * 50)
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8000, reload=True)
