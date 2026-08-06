"""
Git 仓库管理服务
借鉴 LLD §12.5：用户提交 Git URL -> 服务器 clone 到本地 -> 索引/检索

流程：
1. 用户在资源中心提交 Git URL + 凭证引用
2. 服务器 clone 到 workspaces/{repo_id}/
3. Agent 通过代码检索工具搜索本地代码

安全约束（借鉴 nanobot workspace_access）：
- 所有操作限制在 workspaces/ 目录
- clone 使用只读身份
- 不保存明文凭证

部署要求：
- 服务器必须安装 Git CLI（yum install git / apt install git / 下载 Windows 版）
- workspaces/ 目录可写
- 如需访问私有仓库，需配置 SSH 密钥或 HTTPS 凭证
"""
import os
import shutil
import subprocess

# 检查 git 是否可用
_git_checked = False
_git_available = False


def check_git_available() -> dict:
    """
    检查 Git CLI 是否可用
    返回 {available, version, path, error}
    """
    global _git_checked, _git_available
    if _git_checked:
        return {"available": _git_available, "cached": True}

    _git_checked = True
    try:
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            _git_available = True
            # 获取 git 路径
            which = shutil.which("git") or "git"
            return {
                "available": True,
                "version": result.stdout.strip(),
                "path": which,
            }
        else:
            _git_available = False
            return {"available": False, "error": result.stderr.strip()}
    except FileNotFoundError:
        _git_available = False
        return {
            "available": False,
            "error": "Git CLI 未安装",
            "install_guide": {
                "CentOS/RHEL": "yum install -y git",
                "Ubuntu/Debian": "apt-get update && apt-get install -y git",
                "Alpine": "apk add git",
                "Windows": "下载 https://git-scm.com/download/win",
                "Docker": "Dockerfile 中添加: RUN apt-get update && apt-get install -y git",
            },
        }
    except Exception as e:
        _git_available = False
        return {"available": False, "error": str(e)}
import asyncio
import hashlib
from pathlib import Path
from typing import Optional

# 仓库存储根目录（可用环境变量 WORKSPACE_ROOT 覆盖，默认 <项目根>/workspaces）
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", str(Path(__file__).resolve().parents[2] / "workspaces")))
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)


def get_repo_path(repo_id: str) -> Path:
    """获取仓库本地路径"""
    return WORKSPACE_ROOT / repo_id


def resolve_safe_path(repo_id: str, relative_path: str) -> Path:
    """
    安全路径解析（借鉴 nanobot resolve_workspace_path）
    防止路径遍历攻击
    """
    repo_path = get_repo_path(repo_id).resolve()
    target = (repo_path / relative_path).resolve()
    # 确保 target 在 repo_path 内
    if not str(target).startswith(str(repo_path)):
        raise ValueError(f"路径遍历被阻断: {relative_path}")
    return target


async def clone_repo(git_url: str, repo_id: str, branch: str = "main") -> dict:
    """
    Clone 仓库到本地（异步执行 git clone）

    借鉴 LLD §12.5：以只读服务身份 clone，凭证只从环境变量解引用
    """
    # 前置检查：Git CLI 是否可用
    git_status = check_git_available()
    if not git_status.get("available"):
        guide = git_status.get("install_guide", {})
        msg = f"Git CLI 未安装，无法 clone 仓库。"
        if guide:
            msg += f"\n安装方式：{guide.get('Ubuntu/Debian', '')}"
        return {"success": False, "error": msg}

    repo_path = get_repo_path(repo_id)

    # 如果已存在，先拉取最新
    if repo_path.exists() and (repo_path / ".git").exists():
        return await pull_repo(repo_id)

    repo_path.mkdir(parents=True, exist_ok=True)

    # 执行 git clone(全量克隆:浅克隆 --depth 1 只有 1 条提交,
    # 无法支撑 git log 文件创建人/改动人查询与换分支,故不用)
    cmd = ["git", "clone", "--branch", branch, git_url, str(repo_path)]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=300)

        if process.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")
            return {"success": False, "error": f"git clone 失败: {error_msg}"}

        # 统计文件
        file_count = sum(1 for _ in repo_path.rglob("*") if _.is_file())

        return {
            "success": True,
            "repo_id": repo_id,
            "path": str(repo_path),
            "branch": branch,
            "file_count": file_count,
        }

    except asyncio.TimeoutError:
        return {"success": False, "error": "git clone 超时（300s）"}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def pull_repo(repo_id: str) -> dict:
    """拉取最新代码"""
    repo_path = get_repo_path(repo_id)

    if not repo_path.exists() or not (repo_path / ".git").exists():
        return {"success": False, "error": "仓库不存在"}

    cmd = ["git", "-C", str(repo_path), "pull", "--ff-only"]

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=60)

        if process.returncode != 0:
            return {"success": False, "error": stderr.decode("utf-8", errors="replace")[:200]}

        return {
            "success": True,
            "repo_id": repo_id,
            "message": stdout.decode("utf-8", errors="replace")[:200],
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


def _git_out(repo_path: Path, *args: str, timeout: int = 15) -> tuple[int, str]:
    """
    同步执行 git 命令并返回 (returncode, 输出)
    用于分支查询/作者信息等轻量只读操作
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), *args],
            capture_output=True, text=True, timeout=timeout,
            encoding="utf-8", errors="replace",
        )
        return result.returncode, (result.stdout or "") + (result.stderr or "")
    except Exception as e:
        return -1, str(e)


def current_branch(repo_id: str) -> str:
    """获取仓库当前分支名(失败返回空串)"""
    repo_path = get_repo_path(repo_id)
    if not (repo_path / ".git").exists():
        return ""
    code, out = _git_out(repo_path, "rev-parse", "--abbrev-ref", "HEAD")
    return out.strip().splitlines()[0] if code == 0 and out.strip() else ""


def list_branches(repo_id: str) -> dict:
    """
    列出本地+远端分支
    返回 {current, branches: [{name, remote, current}]}
    本地已有的分支与同名远端分支合并为一条(remote 标记保留)
    """
    repo_path = get_repo_path(repo_id)
    if not (repo_path / ".git").exists():
        return {"error": "仓库不存在"}

    cur = current_branch(repo_id)
    code, out = _git_out(repo_path, "branch", "-a", "--format=%(refname:short)")
    if code != 0:
        return {"error": out.strip()[:200]}

    merged: dict[str, dict] = {}
    for line in out.splitlines():
        b = line.strip()
        if not b or b.endswith("/HEAD"):
            continue
        remote = b.startswith("origin/")
        name = b[len("origin/"):] if remote else b
        if name not in merged:
            merged[name] = {"name": name, "remote": remote, "current": (not remote and name == cur)}
        else:
            merged[name]["remote"] = merged[name]["remote"] or remote
            merged[name]["current"] = merged[name]["current"] or (not remote and name == cur)

    # 当前分支排最前,其余按名称排序
    branches = sorted(merged.values(), key=lambda x: (not x["current"], x["name"]))
    return {"current": cur, "branches": branches}


async def checkout_branch(repo_id: str, branch: str) -> dict:
    """
    切换分支:
    1. git fetch origin 拉取远端引用
    2. 本地已有该分支则 checkout,否则基于 origin/<branch> 创建跟踪分支
    3. 切换后顺手 --ff-only 同步到最新
    """
    repo_path = get_repo_path(repo_id)
    if not (repo_path / ".git").exists():
        return {"success": False, "error": "仓库不存在"}

    async def _run(*args: str, timeout: int = 120) -> tuple[int, str]:
        process = await asyncio.create_subprocess_exec(
            "git", "-C", str(repo_path), *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        out = (stdout or b"").decode("utf-8", errors="replace") + (stderr or b"").decode("utf-8", errors="replace")
        return process.returncode or 0, out

    try:
        # fetch 失败不阻断(可能离线),本地分支仍可切换
        await _run("fetch", "origin", timeout=60)

        code, _ = _git_out(repo_path, "show-ref", "--verify", f"refs/heads/{branch}")
        if code == 0:
            rc, out = await _run("checkout", branch)
        else:
            rc, out = await _run("checkout", "-B", branch, f"origin/{branch}")
        if rc != 0:
            return {"success": False, "error": f"切换分支失败: {out.strip()[:200]}"}

        # 切完同步到远端最新(快进不了不算失败,如本地有改动)
        await _run("pull", "--ff-only", timeout=60)
        return {"success": True, "repo_id": repo_id, "branch": branch}
    except asyncio.TimeoutError:
        return {"success": False, "error": "切换分支超时"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def get_file_author(repo_id: str, file_path: str) -> dict:
    """
    获取文件的创建人与最后改动人(基于 git log)
    - creator: 最早一次新增该文件的提交作者(--diff-filter=A --follow 跟踪重命名)
    - last_modifier: 最近一次改动该文件的提交作者
    注:旧浅克隆仓库历史被截断,creator 可能等于 last_modifier
    """
    repo_path = get_repo_path(repo_id)
    if not (repo_path / ".git").exists():
        return {"error": "仓库不存在"}

    fmt = "%an|%ae|%ad"

    def _parse(line: str) -> Optional[dict]:
        parts = line.split("|")
        if len(parts) < 3:
            return None
        return {"name": parts[0].strip(), "email": parts[1].strip(), "date": parts[2].strip()}

    # 最后改动人(最近 1 条)
    last = None
    code, out = _git_out(repo_path, "log", "-1", f"--format={fmt}", "--", file_path)
    if code == 0 and out.strip():
        last = _parse(out.strip().splitlines()[0])

    # 创建人(新增提交中最早一条;git log 默认新→旧,取最后一行)
    creator = None
    code, out = _git_out(repo_path, "log", "--diff-filter=A", "--follow",
                         f"--format={fmt}", "--", file_path)
    if code == 0 and out.strip():
        creator = _parse(out.strip().splitlines()[-1])

    return {"file": file_path, "creator": creator, "last_modifier": last}


def list_repo_files(repo_id: str, subdir: str = "", pattern: str = "*",
                    max_results: int = 50) -> list[dict]:
    """
    列出仓库文件（借鉴 nanobot filesystem list_files）

    参数：
        repo_id: 仓库 ID
        subdir: 子目录（相对路径）
        pattern: 文件匹配模式（如 *.java, *.py）
        max_results: 最大返回数
    """
    try:
        base = resolve_safe_path(repo_id, subdir)
    except ValueError as e:
        return [{"error": str(e)}]

    if not base.exists():
        return [{"error": f"目录不存在: {subdir}"}]

    # 支持的代码文件扩展名
    code_extensions = {
        ".py", ".java", ".js", ".ts", ".jsx", ".tsx",
        ".vue", ".go", ".rs", ".c", ".cpp", ".h", ".hpp",
        ".cs", ".rb", ".php", ".swift", ".kt", ".scala",
        ".md", ".yaml", ".yml", ".json", ".xml", ".sql",
        ".html", ".css", ".scss", ".less",
        ".sh", ".bat", ".ps1", ".dockerfile",
        ".properties", ".conf", ".ini", ".toml",
    }

    files = []
    for f in base.rglob(pattern):
        if f.is_file():
            # 过滤掉 .git 目录
            if ".git" in f.parts:
                continue
            # 如果有特定 pattern，不过滤扩展名
            if pattern != "*":
                files.append({
                    "path": str(f.relative_to(base)).replace("\\", "/"),
                    "size": f.stat().st_size,
                })
            else:
                # 只返回代码文件
                if f.suffix.lower() in code_extensions:
                    files.append({
                        "path": str(f.relative_to(base)).replace("\\", "/"),
                        "size": f.stat().st_size,
                    })

        if len(files) >= max_results:
            break

    return files


def read_code_excerpt(repo_id: str, file_path: str,
                      start_line: int = 1, end_line: int = 50) -> dict:
    """
    读取代码文件片段（借鉴 nanobot read_file）

    参数：
        repo_id: 仓库 ID
        file_path: 文件相对路径
        start_line: 起始行
        end_line: 结束行
    """
    try:
        target = resolve_safe_path(repo_id, file_path)
    except ValueError as e:
        return {"error": str(e)}

    if not target.exists():
        return {"error": f"文件不存在: {file_path}"}

    if target.stat().st_size > 500_000:  # 500KB 限制
        return {"error": "文件过大（>500KB），请指定更小的范围"}

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return {"error": f"读取失败: {e}"}

    lines = content.split("\n")
    total_lines = len(lines)

    start = max(1, start_line) - 1  # 转为 0-indexed
    end = min(total_lines, end_line)

    excerpt = "\n".join(lines[start:end])

    return {
        "file": file_path,
        "start_line": start + 1,
        "end_line": end,
        "total_lines": total_lines,
        "content": excerpt,
    }


def _attach_authors(repo_id: str, results: list[dict]) -> list[dict]:
    """
    为搜索结果按唯一文件富化 git 作者信息(创建人/最后改动人)
    每文件一次 git log 调用,结果带 creator/last_modifier/last_modified 字段
    """
    cache: dict[str, dict] = {}
    for r in results:
        f = r.get("file")
        if not f:
            continue
        if f not in cache:
            cache[f] = get_file_author(repo_id, f)
        info = cache[f]
        if "error" not in info:
            creator = info.get("creator") or {}
            last = info.get("last_modifier") or {}
            r["creator"] = creator.get("name", "")
            r["last_modifier"] = last.get("name", "")
            r["last_modified"] = last.get("date", "")
    return results


def search_in_repo(repo_id: str, query: str, file_pattern: str = "*",
                   max_results: int = 20) -> list[dict]:
    """
    在仓库中搜索代码（借鉴 nanobot search + grep 思路）

    参数：
        repo_id: 仓库 ID
        query: 搜索关键词
        file_pattern: 文件匹配模式
        max_results: 最大结果数

    返回结果带 git 作者信息(creator 创建人 / last_modifier 最后改动人)
    """
    try:
        base = resolve_safe_path(repo_id, "")
    except ValueError as e:
        return [{"error": str(e)}]

    if not base.exists():
        return [{"error": "仓库不存在"}]

    results = []
    query_lower = query.lower()

    for f in base.rglob(file_pattern):
        if f.is_file():
            # 跳过 .git
            if ".git" in f.parts:
                continue

            # 跳过二进制文件
            if f.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".pdf",
                                     ".zip", ".jar", ".class", ".exe", ".dll",
                                     ".so", ".dylib", ".node", ".wasm"}:
                continue

            # 跳过大文件
            if f.stat().st_size > 200_000:
                continue

            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            lines = content.split("\n")
            for line_num, line in enumerate(lines, 1):
                if query_lower in line.lower():
                    rel_path = str(f.relative_to(base)).replace("\\", "/")
                    results.append({
                        "file": rel_path,
                        "line": line_num,
                        "content": line.strip()[:200],
                    })
                    if len(results) >= max_results:
                        return _attach_authors(repo_id, results)

    return _attach_authors(repo_id, results)
