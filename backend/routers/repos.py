"""
Git 仓库 API 路由
提供 REST API 让前端直接管理 Git 仓库：
- GET /api/repos/env - 环境检查（git/磁盘/网络）
- POST /api/repos/clone - Clone 仓库
- GET /api/repos - 仓库列表
- GET /api/repos/{repo_id}/files - 文件列表
- POST /api/repos/{repo_id}/search - 代码搜索（结果带 git 作者信息）
- GET /api/repos/{repo_id}/read - 读取文件片段
- POST /api/repos/{repo_id}/pull - 拉取更新
- PATCH /api/repos/{repo_id} - 编辑仓库（名称/地址/默认分支/定时刷新）
- GET /api/repos/{repo_id}/branches - 分支列表
- POST /api/repos/{repo_id}/checkout - 切换分支
- GET /api/repos/{repo_id}/file-author - 文件创建人/最后改动人
- DELETE /api/repos/{repo_id} - 删除仓库
"""
import os
import shutil
import subprocess
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db, now_cn
from backend.models.governance import Repository
from backend.services import git_service

router = APIRouter(prefix="/api/repos", tags=["repositories"])


def _utcnow_naive() -> datetime:
    """东八区当前时间(naive)——MySQL DATETIME 不带时区,与 created_at 比较口径一致"""
    return now_cn()


class CloneRequest(BaseModel):
    """Clone 请求"""
    git_url: str
    repo_id: str  # 仓库名称/ID（用于本地路径和后续检索）
    branch: str = "main"
    name: str = ""  # 显示名（可选）


class UpdateRepoRequest(BaseModel):
    """编辑仓库请求(字段均可选,只更新传入项)"""
    name: str | None = None  # 仓库名称(=本地目录名,改名会同步重命名目录)
    clone_url: str | None = None
    branch: str | None = None  # 默认分支
    auto_refresh_minutes: int | None = None  # 定时自动拉取间隔(分钟),0/None=关闭


class CheckoutRequest(BaseModel):
    """切换分支请求"""
    branch: str


@router.get("/env")
async def check_environment():
    """
    环境检查：服务器是否具备拉取 Git 仓库的条件
    检查：Git CLI / 磁盘空间 / workspaces 目录 / 网络连通性
    """
    # 1. Git CLI
    git_status = git_service.check_git_available()

    # 2. 磁盘空间
    ws_path = git_service.WORKSPACE_ROOT
    usage = shutil.disk_usage(str(ws_path))

    # 3. workspaces 目录
    ws_exists = ws_path.exists()
    ws_writable = os.access(str(ws_path), os.W_OK) if ws_exists else False

    # 4. 已有仓库数
    repo_count = len([d for d in ws_path.iterdir() if d.is_dir()]) if ws_exists else 0

    # 5. Git 全局配置
    git_config = {}
    if git_status.get("available"):
        for key in ["user.name", "user.email"]:
            try:
                result = subprocess.run(["git", "config", "--global", key],
                                        capture_output=True, text=True, timeout=3)
                git_config[key] = result.stdout.strip() or "(未设置)"
            except Exception:
                git_config[key] = "(检测失败)"

    # 6. 网络连通性
    network = {}
    import urllib.request
    for name, url in [("Gitee", "https://gitee.com"), ("GitHub", "https://github.com"), ("GitLab", "https://gitlab.com")]:
        try:
            urllib.request.urlopen(url, timeout=3)
            network[name] = "✅ 可达"
        except Exception:
            network[name] = "❌ 不可达"

    ready = git_status.get("available", False) and ws_writable and usage.free > 1024**3  # 至少 1GB

    return {
        "ready": ready,
        "git": git_status,
        "disk": {
            "total_gb": round(usage.total / 1024**3, 1),
            "used_gb": round(usage.used / 1024**3, 1),
            "free_gb": round(usage.free / 1024**3, 1),
        },
        "workspace": {
            "path": str(ws_path),
            "exists": ws_exists,
            "writable": ws_writable,
            "repo_count": repo_count,
        },
        "git_config": git_config,
        "network": network,
    }


@router.post("/clone")
async def clone_repository(req: CloneRequest, db: AsyncSession = Depends(get_db)):
    """
    Clone Git 仓库到本地
    借鉴 LLD §12.5：用户提交 Git URL -> 服务器 clone -> 写入 repository 表
    """
    # 先 clone 到本地
    result = await git_service.clone_repo(req.git_url, req.repo_id, req.branch)

    if not result.get("success"):
        raise HTTPException(400, result.get("error", "clone 失败"))

    # 写入数据库
    import uuid
    repo = Repository(
        id=str(uuid.uuid4().hex),
        name=req.name or req.repo_id,
        provider="git",
        clone_url=req.git_url,
        default_branch=req.branch,
        state="READY" if result.get("success") else "FAILED",
        owner="admin",
    )
    db.add(repo)
    await db.flush()

    return {
        "success": True,
        "repo_id": req.repo_id,
        "db_id": repo.id,
        "file_count": result.get("file_count", 0),
        "message": f"仓库 '{req.repo_id}' clone 成功，共 {result.get('file_count', 0)} 个文件",
    }


@router.get("")
async def list_repositories(db: AsyncSession = Depends(get_db)):
    """获取仓库列表（含本地状态）；先增量登记本地目录，保证手工导入的仓库入库可绑定"""
    from backend.services.repo_registry import sync_workspace_repos
    await sync_workspace_repos(db)

    # 数据库中的仓库
    db_repos = (await db.execute(
        select(Repository).order_by(Repository.created_at.desc())
    )).scalars().all()

    result = []
    for r in db_repos:
        # 检查本地是否存在
        local_path = git_service.get_repo_path(r.name or r.id)
        local_exists = local_path.exists()

        # 如果本地存在，统计文件数
        file_count = 0
        if local_exists:
            for f in local_path.rglob("*"):
                if f.is_file() and ".git" not in f.parts:
                    file_count += 1

        result.append({
            "id": r.id,
            "name": r.name,
            "repo_id": r.name,  # 本地路径 ID
            "clone_url": r.clone_url,
            "branch": r.default_branch,
            "current_branch": git_service.current_branch(r.name or r.id) if local_exists else "",
            "auto_refresh_minutes": r.auto_refresh_minutes or 0,
            "last_sync_at": r.last_sync_at.strftime("%Y-%m-%d %H:%M:%S") if r.last_sync_at else "",
            "state": "READY" if local_exists else "CLONED_BUT_MISSING",
            "local_exists": local_exists,
            "file_count": file_count,
            "owner": r.owner,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M:%S") if r.created_at else "",
        })

    # sync_workspace_repos 已保证本地目录全部入库，此处仅兜底异常场景（如登记后又被手工删行）
    workspace_root = git_service.WORKSPACE_ROOT
    if workspace_root.exists():
        db_names = {r.name for r in db_repos}
        for d in workspace_root.iterdir():
            # 同样要求 .git,跳过 collab_docs/uploads 等普通目录(与 repo_registry 口径一致)
            if d.is_dir() and d.name not in db_names and (d / ".git").exists():
                file_count = sum(1 for f in d.rglob("*") if f.is_file() and ".git" not in f.parts)
                result.append({
                    "id": "",
                    "name": d.name,
                    "repo_id": d.name,
                    "clone_url": "",
                    "branch": "",
                    "state": "LOCAL_ONLY",
                    "local_exists": True,
                    "file_count": file_count,
                    "owner": "",
                    "created_at": "",
                })

    return result


@router.get("/{repo_id}/files")
async def list_files(
    repo_id: str,
    subdir: str = Query("", description="子目录路径"),
    pattern: str = Query("*", description="文件匹配模式"),
    max_results: int = Query(50, le=200),
):
    """列出仓库文件"""
    files = git_service.list_repo_files(repo_id, subdir, pattern, max_results)

    if files and isinstance(files[0], dict) and "error" in files[0]:
        raise HTTPException(404, files[0]["error"])

    return {"repo_id": repo_id, "subdir": subdir, "files": files, "count": len(files)}


class SearchRequest(BaseModel):
    """代码搜索请求"""
    query: str
    file_pattern: str = "*"
    max_results: int = 20


@router.post("/{repo_id}/search")
async def search_code(repo_id: str, req: SearchRequest):
    """在仓库中搜索代码"""
    results = git_service.search_in_repo(repo_id, req.query, req.file_pattern, req.max_results)

    if results and isinstance(results[0], dict) and "error" in results[0]:
        raise HTTPException(404, results[0]["error"])

    return {
        "repo_id": repo_id,
        "query": req.query,
        "results": results,
        "count": len(results),
    }


@router.get("/{repo_id}/read")
async def read_file(
    repo_id: str,
    file_path: str = Query(..., description="文件相对路径"),
    start_line: int = Query(1, ge=1),
    end_line: int = Query(50, ge=1, le=500),
):
    """读取代码文件片段"""
    result = git_service.read_code_excerpt(repo_id, file_path, start_line, end_line)

    if "error" in result:
        raise HTTPException(404, result["error"])

    return result


@router.post("/{repo_id}/pull")
async def pull_repository(repo_id: str, db: AsyncSession = Depends(get_db)):
    """拉取仓库最新代码(成功后刷新 last_sync_at,供定时刷新调度判断)"""
    result = await git_service.pull_repo(repo_id)

    if not result.get("success"):
        raise HTTPException(400, result.get("error", "拉取失败"))

    row = (await db.execute(
        select(Repository).where(Repository.name == repo_id)
    )).scalar_one_or_none()
    if row:
        row.last_sync_at = _utcnow_naive()
        await db.flush()

    return {"success": True, "repo_id": repo_id, "message": result.get("message", "拉取成功")}


@router.patch("/{repo_id}")
async def update_repository(repo_id: str, req: UpdateRepoRequest, db: AsyncSession = Depends(get_db)):
    """
    编辑仓库:名称/克隆地址/默认分支/定时刷新间隔
    改名会同步重命名本地目录(绑定表引用的是 Repository.id(uuid),不受改名影响)
    """
    row = (await db.execute(
        select(Repository).where(Repository.name == repo_id)
    )).scalar_one_or_none()
    if not row:
        raise HTTPException(404, f"仓库 '{repo_id}' 不存在")

    # 改名:校验重名 + 重命名本地目录
    if req.name and req.name != row.name:
        clash = (await db.execute(
            select(Repository).where(Repository.name == req.name)
        )).scalar_one_or_none()
        if clash:
            raise HTTPException(400, f"名称 '{req.name}' 已被其他仓库占用")
        old_path = git_service.get_repo_path(row.name)
        new_path = git_service.get_repo_path(req.name)
        if old_path.exists():
            if new_path.exists():
                raise HTTPException(400, f"本地目录 '{req.name}' 已存在")
            try:
                os.rename(str(old_path), str(new_path))
            except OSError as e:
                raise HTTPException(500, f"本地目录重命名失败: {e}")
        row.name = req.name

    if req.clone_url:
        row.clone_url = req.clone_url
    if req.branch:
        row.default_branch = req.branch
    if req.auto_refresh_minutes is not None:
        # 0 及负数视为关闭;上限 7 天防止误输
        minutes = max(0, min(req.auto_refresh_minutes, 7 * 24 * 60))
        row.auto_refresh_minutes = minutes or None

    await db.flush()
    return {
        "success": True,
        "repo_id": row.name,
        "name": row.name,
        "clone_url": row.clone_url,
        "branch": row.default_branch,
        "auto_refresh_minutes": row.auto_refresh_minutes or 0,
    }


@router.get("/{repo_id}/branches")
async def list_repo_branches(repo_id: str):
    """列出仓库本地+远端分支(含当前分支标记)"""
    result = git_service.list_branches(repo_id)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return {"repo_id": repo_id, **result}


@router.post("/{repo_id}/checkout")
async def checkout_repo_branch(repo_id: str, req: CheckoutRequest, db: AsyncSession = Depends(get_db)):
    """切换分支(fetch + checkout + 快进同步),成功后同步默认分支与同步时间"""
    result = await git_service.checkout_branch(repo_id, req.branch)
    if not result.get("success"):
        raise HTTPException(400, result.get("error", "切换分支失败"))

    row = (await db.execute(
        select(Repository).where(Repository.name == repo_id)
    )).scalar_one_or_none()
    if row:
        row.default_branch = req.branch
        row.last_sync_at = _utcnow_naive()
        await db.flush()

    return {"success": True, "repo_id": repo_id, "branch": req.branch}


@router.get("/{repo_id}/file-author")
async def get_file_author(repo_id: str, file_path: str = Query(..., description="文件相对路径")):
    """获取文件的创建人与最后改动人(git log)"""
    result = git_service.get_file_author(repo_id, file_path)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return {"repo_id": repo_id, **result}


@router.get("/{repo_id}/structure")
async def get_project_structure(repo_id: str, depth: int = Query(2, ge=1, le=4)):
    """获取项目结构概览"""
    from backend.runtime.tools.code_tools import GetProjectStructureTool
    tool = GetProjectStructureTool()
    result = await tool.execute(repo_id=repo_id, depth=depth)
    return {"repo_id": repo_id, "structure": str(result)}


@router.delete("/{repo_id}")
async def delete_repository(repo_id: str, db: AsyncSession = Depends(get_db)):
    """删除本地仓库：同时清理 repository 表记录与员工绑定，避免悬空绑定"""
    import stat
    from backend.models.governance import AgentRepoBinding
    repo_path = git_service.get_repo_path(repo_id)

    if repo_path.exists():
        # Windows 下 .git 内大量只读文件会让 rmtree 抛 PermissionError，
        # onexc 回调去掉只读属性后重试；绝不能用 ignore_errors=True——
        # 静默失败后 list 接口的 sync_workspace_repos 会把残留目录重新登记入库，表现为"删不掉"
        def _force_remove(func, path, exc_info):
            os.chmod(path, stat.S_IWRITE)
            func(path)

        try:
            shutil.rmtree(repo_path, onexc=_force_remove)
        except Exception as e:
            raise HTTPException(500, f"本地仓库目录删除失败: {e}")

    # 删除后校验：目录仍在即失败，提前报错而不是让前端误以为成功
    if repo_path.exists():
        raise HTTPException(500, "本地仓库目录删除失败，可能被其他进程占用，请关闭占用后重试")

    # 清理 DB（repo_id 参数为目录名，即 Repository.name）
    row = (await db.execute(
        select(Repository).where(Repository.name == repo_id)
    )).scalar_one_or_none()
    if row:
        await db.execute(delete(AgentRepoBinding).where(AgentRepoBinding.repo_id == row.id))
        await db.delete(row)
        await db.flush()

    return {"success": True, "message": f"仓库 '{repo_id}' 已删除"}
