"""
LangChain 工具定义 - 用 @tool 装饰器替换自研 Tool ABC

关键优势（对比自研 Tool ABC）：
1. @tool 装饰器自动生成 JSON Schema（无需手写 parameters）
2. LangChain Tool 自动集成到 AgentExecutor / LangGraph
3. 工具描述就是 docstring（LLM 直接读取）
4. 支持 async（原生 asyncio）

工具清单（9 个）：
- 业务工具：search_knowledge / get_employee_info / search_resource
- 代码工具：search_code / get_code_excerpt / list_files / clone_repo
- 扩展工具：get_project_structure / search_in_docs
"""
from langchain_core.tools import tool
from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.knowledge import KnowledgeCandidate
from backend.models.agent import Agent
from backend.models.resource import Resource
from backend.models.company import Department, Domain
from backend.services import git_service


# ═══════════════════════════════════════════════
#  业务工具（数据库查询）
# ═══════════════════════════════════════════════

@tool
async def search_knowledge(query: str, domain: str = "") -> str:
    """搜索已审核通过的知识库，查找业务文档、FAQ、最佳实践。当需要查找业务知识、规范、流程时调用。

    Args:
        query: 搜索关键词（可为空，空时返回最新知识）
        domain: 可选：限定领域（如 订单域/支付域）
    """
    from backend.database import async_session

    async with async_session() as db:
        sql = select(KnowledgeCandidate).where(KnowledgeCandidate.state == "APPROVED")
        if domain:
            sql = sql.where(KnowledgeCandidate.domain.contains(domain))
        sql = sql.order_by(KnowledgeCandidate.created_at.desc()).limit(5)

        result = await db.execute(sql)
        items = result.scalars().all()

        if query:
            items = [k for k in items if query.lower() in (k.title + (k.body_md or "")).lower()][:3]

        if not items:
            return f"未找到与 '{query}' 相关的知识。"

        lines = [f"找到 {len(items)} 条相关知识：\n"]
        for k in items:
            lines.append(f"### {k.title}\n领域: {k.domain} | 置信度: {k.confidence}\n{(k.body_md or '')[:500]}\n")
        return "\n".join(lines)


@tool
async def get_employee_info(keyword: str = "") -> str:
    """查找公司内的 AI 员工信息，包括姓名、职位、所属部门、专业领域。

    Args:
        keyword: 员工姓名或领域关键词（可为空，空时返回全部员工）
    """
    from backend.database import async_session

    async with async_session() as db:
        sql = select(Agent).where(Agent.status.in_(["online", "trial"]))
        if keyword:
            sql = sql.where(or_(Agent.name.contains(keyword), Agent.title.contains(keyword)))
        sql = sql.limit(10)

        result = await db.execute(sql)
        agents = result.scalars().all()

        if not agents:
            return "未找到相关员工。"

        all_depts = {d.id: d.name for d in (await db.execute(select(Department))).scalars().all()}
        all_domains = {d.id: d.name for d in (await db.execute(select(Domain))).scalars().all()}

        lines = [f"找到 {len(agents)} 位员工：\n"]
        for a in agents:
            dept = all_depts.get(a.department_id, "未知")
            dom = all_domains.get(a.domain_id, "未知")
            lines.append(f"- {a.emoji} {a.name}（{a.title}）\n  部门: {dept} | 领域: {dom} | 状态: {a.status}\n  职责: {(a.description or '')[:200]}\n")
        return "\n".join(lines)


@tool
async def search_resource(keyword: str = "", type: str = "") -> str:
    """搜索公司资源库（代码仓库、API 文档、数据集）。

    Args:
        keyword: 资源名称关键词（可为空，空时返回全部资源）
        type: 可选：资源类型（service/document/dataset/knowledge）
    """
    from backend.database import async_session

    async with async_session() as db:
        sql = select(Resource)
        if type:
            sql = sql.where(Resource.type == type)
        if keyword:
            sql = sql.where(Resource.name.contains(keyword))
        sql = sql.limit(5)

        result = await db.execute(sql)
        items = result.scalars().all()

        if not items:
            return f"未找到与 '{keyword}' 相关的资源。"

        lines = [f"找到 {len(items)} 个相关资源：\n"]
        for r in items:
            lines.append(f"- {r.icon} {r.name}（类型: {r.type}）\n  URL: {r.url or '无'} | 状态: {r.status}\n  描述: {(r.description or '')[:200]}\n")
        return "\n".join(lines)


# ═══════════════════════════════════════════════
#  代码工具（本地 Git 仓库检索）
# ═══════════════════════════════════════════════

@tool
def search_code(repo_id: str, query: str, file_pattern: str = "*") -> str:
    """在 Git 仓库中搜索代码关键词。返回匹配的文件名、行号和代码片段。

    Args:
        repo_id: 仓库 ID（如 dst-iot-da）
        query: 搜索关键词（函数名、类名、变量名等）
        file_pattern: 可选：文件匹配模式（如 *.java, *.py），默认搜索所有代码文件
    """
    results = git_service.search_in_repo(repo_id, query, file_pattern)

    if not results:
        return f"在仓库 '{repo_id}' 中未找到包含 '{query}' 的代码。"

    if isinstance(results[0], dict) and "error" in results[0]:
        return f"错误: {results[0]['error']}"

    lines = [f"在仓库 '{repo_id}' 中找到 {len(results)} 处匹配 '{query}'：\n"]
    for r in results[:15]:
        lines.append(f"📄 {r['file']}:{r['line']}")
        lines.append(f"   {r['content']}\n")
    return "\n".join(lines)


@tool
def get_code_excerpt(repo_id: str, file_path: str, start_line: int = 1, end_line: int = 50) -> str:
    """读取代码文件的指定片段。

    Args:
        repo_id: 仓库 ID
        file_path: 文件相对路径（如 src/main/java/OrderService.java）
        start_line: 起始行号（默认 1）
        end_line: 结束行号（默认 50）
    """
    result = git_service.read_code_excerpt(repo_id, file_path, start_line, end_line)

    if "error" in result:
        return f"错误: {result['error']}"

    header = f"📄 {result['file']} (L{result['start_line']}-{result['end_line']}/{result['total_lines']}行)\n\n"
    return header + result["content"]


@tool
def list_files(repo_id: str, subdir: str = "", pattern: str = "*") -> str:
    """列出 Git 仓库的文件结构。

    Args:
        repo_id: 仓库 ID
        subdir: 可选：子目录路径（如 src/main/java）
        pattern: 可选：文件匹配模式（如 *.java），默认列出所有代码文件
    """
    files = git_service.list_repo_files(repo_id, subdir, pattern)

    if not files:
        return f"仓库 '{repo_id}' 目录 '{subdir}' 下没有匹配的文件。"

    if isinstance(files[0], dict) and "error" in files[0]:
        return f"错误: {files[0]['error']}"

    lines = [f"仓库 '{repo_id}' 目录 '{subdir or '/'}' 下找到 {len(files)} 个文件：\n"]
    for f in files[:30]:
        lines.append(f"  {f['path']} ({f['size']/1024:.1f}KB)")
    return "\n".join(lines)


@tool
async def clone_repo(git_url: str, repo_id: str, branch: str = "main") -> str:
    """Clone 一个 Git 仓库到本地。用户提供 Git 地址时调用，clone 后可用 search_code 检索。

    Args:
        git_url: Git 仓库地址（如 https://gitee.com/user/repo.git）
        repo_id: 仓库 ID（用于后续检索，如 my-project）
        branch: 可选：分支名（默认 main）
    """
    result = await git_service.clone_repo(git_url, repo_id, branch)

    if not result.get("success"):
        return f"Clone 失败: {result.get('error', '未知错误')}"

    return (f"仓库 clone 成功！\n"
            f"  仓库 ID: {result['repo_id']}\n"
            f"  分支: {result.get('branch', branch)}\n"
            f"  文件数: {result.get('file_count', '?')}\n"
            f"现在可以使用 search_code、get_code_excerpt、list_files 来检索代码。")


@tool
def get_project_structure(repo_id: str, depth: int = 2) -> str:
    """获取 Git 仓库的项目结构概览。返回目录树、技术栈和文件类型统计。

    Args:
        repo_id: 仓库 ID
        depth: 目录树深度（默认 2，最大 4）
    """
    try:
        base = git_service.resolve_safe_path(repo_id, "")
    except ValueError as e:
        return f"错误: {e}"

    if not base.exists():
        return f"仓库 '{repo_id}' 不存在"

    ext_counts = {}
    total_files = 0
    for f in base.rglob("*"):
        if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts:
            total_files += 1
            ext = f.suffix.lower() or "(无扩展名)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1

    tech_stack = []
    if ext_counts.get(".py", 0) > 3: tech_stack.append("Python")
    if ext_counts.get(".java", 0) > 3: tech_stack.append("Java")
    if ext_counts.get(".js", 0) + ext_counts.get(".ts", 0) > 3: tech_stack.append("JavaScript/TypeScript")
    if ext_counts.get(".vue", 0) > 0: tech_stack.append("Vue")
    if ext_counts.get(".go", 0) > 0: tech_stack.append("Go")

    lines = [f"仓库 '{repo_id}' 结构概览（{total_files} 个文件）\n"]
    if tech_stack:
        lines.append(f"技术栈：{', '.join(tech_stack)}\n")

    top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:5]
    lines.append("文件类型分布：")
    for ext, count in top_exts:
        lines.append(f"  {ext}: {count} 个")

    lines.append(f"\n目录树（深度 {depth}）：")

    def build_tree(path, prefix="", current_depth=0):
        if current_depth >= depth:
            return
        entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        entries = [e for e in entries if e.name not in {".git", "__pycache__", "node_modules"}]
        for i, entry in enumerate(entries[:15]):
            is_last = (i == len(entries[:15]) - 1)
            connector = "└── " if is_last else "├── "
            icon = "📁" if entry.is_dir() else "📄"
            lines.append(f"{prefix}{connector}{icon} {entry.name}")
            if entry.is_dir():
                ext = "    " if is_last else "│   "
                build_tree(entry, prefix + ext, current_depth + 1)

    build_tree(base)
    return "\n".join(lines)


@tool
def search_in_docs(repo_id: str, query: str) -> str:
    """搜索仓库中的文档文件（README、API 文档、Markdown、YAML 配置等）。

    Args:
        repo_id: 仓库 ID
        query: 搜索关键词
    """
    try:
        base = git_service.resolve_safe_path(repo_id, "")
    except ValueError as e:
        return f"错误: {e}"

    if not base.exists():
        return f"仓库 '{repo_id}' 不存在"

    doc_extensions = {".md", ".txt", ".rst", ".yaml", ".yml", ".json", ".xml", ".properties", ".conf", ".ini", ".toml", ".html"}
    query_lower = query.lower()
    results = []

    for f in base.rglob("*"):
        if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts:
            if f.suffix.lower() not in doc_extensions:
                continue
            if f.stat().st_size > 200_000:
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for line_num, line in enumerate(content.split("\n"), 1):
                if query_lower in line.lower():
                    results.append({"file": str(f.relative_to(base)).replace("\\", "/"), "line": line_num, "content": line.strip()[:200]})
                    if len(results) >= 15:
                        break
            if len(results) >= 15:
                break

    if not results:
        return f"在仓库 '{repo_id}' 的文档中未找到 '{query}'。"

    lines = [f"在仓库 '{repo_id}' 的文档中找到 {len(results)} 处匹配 '{query}'：\n"]
    for r in results[:10]:
        lines.append(f"📄 {r['file']}:{r['line']}")
        lines.append(f"   {r['content']}\n")
    return "\n".join(lines)


# ═══════════════════════════════════════════════
#  工具列表（供 LangGraph Agent 使用）
# ═══════════════════════════════════════════════

def get_all_tools() -> list:
    """获取所有工具实例（用于 LangGraph Agent）"""
    return [
        search_knowledge,
        get_employee_info,
        search_resource,
        search_code,
        get_code_excerpt,
        list_files,
        clone_repo,
        get_project_structure,
        search_in_docs,
    ]
