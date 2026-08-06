"""
代码检索工具 - 借鉴 nanobot agent/tools/filesystem.py + search.py
适配 Office_Agent：搜索本地 Git 仓库代码

工具列表：
1. searchCode - 在仓库中搜索代码关键词（grep 模式）
2. getCodeExcerpt - 读取代码文件片段
3. listFiles - 列出仓库文件树
4. cloneRepo - clone Git 仓库到本地

全部 read_only=True（cloneRepo 除外）

作用域设计：
- 只读检索工具构造时可注入 allowed_repos（绑定仓库白名单）/ default_repo（单仓库默认值）
- allowed_repos 为空 = 不限制（总前台自答 / 未绑定员工保持全局检索）
- 越权访问采用软限制：返回纠错提示而非报错，让 LLM 在 ReAct 循环中自我纠正
"""
from backend.runtime.tool_base import Tool, ToolResult
from backend.services import git_service


class _RepoScopeMixin:
    """
    仓库作用域混入：为代码检索工具提供白名单校验与默认仓库填充

    注入方式：Tool 实例化时传入（execute 签名不变，runner/registry 无感知）
    """

    def __init__(self, allowed_repos: list[str] | None = None,
                 default_repo: str | None = None):
        self._allowed_repos = allowed_repos or []
        self._default_repo = default_repo

    def _resolve_repo(self, repo_id: str | None) -> tuple[str | None, ToolResult | None]:
        """
        解析并校验 repo_id
        返回 (实际使用的 repo_id, 拦截结果)；拦截结果为 None 表示放行
        """
        # 空白名单 = 不限制（向后兼容：总台自答、未绑定员工全局检索）
        if not self._allowed_repos:
            return repo_id, None
        # repo_id 省略时：恰好绑定 1 个仓库则自动填充
        if not repo_id:
            if self._default_repo:
                return self._default_repo, None
            return None, ToolResult.ok(
                "请指定要检索的仓库（repo_id），你当前可访问的仓库："
                + "、".join(self._allowed_repos)
            )
        # 越权访问 → 软限制：返回纠错提示（不 error），引导 LLM 自我纠正
        if repo_id not in self._allowed_repos:
            return None, ToolResult.ok(
                f"你未被授权访问仓库 '{repo_id}'，当前可访问的仓库："
                + "、".join(self._allowed_repos)
                + "。请改用上述仓库；如确需跨仓库协助，请向用户说明。"
            )
        return repo_id, None

    def _repo_param_schema(self, base_description: str = "仓库 ID") -> dict:
        """repo_id 参数 schema：有默认仓库时提示可省略"""
        desc = base_description
        if self._default_repo:
            desc += f"（当前授权仓库：{self._default_repo}，可省略）"
        return {"type": "string", "description": desc}

    def _required_with_repo(self, *others: str) -> list[str]:
        """required 列表：有默认仓库时 repo_id 不再是必填"""
        if self._default_repo:
            return list(others)
        return ["repo_id", *others]


class SearchCodeTool(_RepoScopeMixin, Tool):
    """在 Git 仓库中搜索代码（只读，借鉴 nanobot search）"""

    @property
    def name(self) -> str:
        return "searchCode"

    @property
    def description(self) -> str:
        desc = ("搜索代码仓库中的代码。在指定的 Git 仓库中搜索关键词，"
                "返回匹配的文件名、行号和代码片段。"
                "适用于查找函数定义、变量使用、配置项等。")
        if self._allowed_repos:
            desc += "当前授权仓库：" + "、".join(self._allowed_repos) + "。"
        return desc

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_id": self._repo_param_schema("仓库 ID（如 order-service）"),
                "query": {
                    "type": "string",
                    "description": "搜索关键词（函数名、类名、变量名等）",
                },
                "file_pattern": {
                    "type": "string",
                    "description": "可选：文件匹配模式（如 *.java, *.py），默认搜索所有代码文件",
                },
            },
            "required": self._required_with_repo("query"),
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, repo_id: str = "", query: str = "", file_pattern: str = "*",
                      **kwargs) -> ToolResult:
        """执行代码搜索"""
        repo_id, blocked = self._resolve_repo(repo_id)
        if blocked:
            return blocked
        results = git_service.search_in_repo(repo_id, query, file_pattern)

        if not results:
            return ToolResult.ok(f"在仓库 '{repo_id}' 中未找到包含 '{query}' 的代码。")

        if isinstance(results[0], dict) and "error" in results[0]:
            return ToolResult.error(results[0]["error"])

        lines = [f"在仓库 '{repo_id}' 中找到 {len(results)} 处匹配 '{query}'：\n"]
        for r in results[:15]:
            lines.append(f"📄 {r['file']}:{r['line']}")
            # git 作者信息:创建人/最后改动人(总前台可据此回答"这文件谁开发的")
            author_bits = []
            if r.get("creator"):
                author_bits.append(f"创建:{r['creator']}")
            if r.get("last_modifier"):
                last_bit = f"最后修改:{r['last_modifier']}"
                if r.get("last_modified"):
                    last_bit += f"({r['last_modified']})"
                author_bits.append(last_bit)
            if author_bits:
                lines.append(f"   👤 {' · '.join(author_bits)}")
            lines.append(f"   {r['content']}\n")

        if len(results) > 15:
            lines.append(f"... 还有 {len(results) - 15} 处匹配未显示")

        return ToolResult.ok("\n".join(lines))


class GetCodeExcerptTool(_RepoScopeMixin, Tool):
    """读取代码文件片段（只读，借鉴 nanobot read_file）"""

    @property
    def name(self) -> str:
        return "getCodeExcerpt"

    @property
    def description(self) -> str:
        return ("读取代码文件的指定片段。给定文件路径和行号范围，返回代码内容。"
                "适用于查看函数实现、配置文件内容等。")

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_id": self._repo_param_schema(),
                "file_path": {
                    "type": "string",
                    "description": "文件相对路径（如 src/main/java/OrderService.java）",
                },
                "start_line": {
                    "type": "integer",
                    "description": "起始行号（默认 1）",
                },
                "end_line": {
                    "type": "integer",
                    "description": "结束行号（默认 50）",
                },
            },
            "required": self._required_with_repo("file_path"),
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, repo_id: str = "", file_path: str = "",
                      start_line: int = 1, end_line: int = 50,
                      **kwargs) -> ToolResult:
        """读取代码片段"""
        repo_id, blocked = self._resolve_repo(repo_id)
        if blocked:
            return blocked
        result = git_service.read_code_excerpt(repo_id, file_path, start_line, end_line)

        if "error" in result:
            return ToolResult.error(result["error"])

        header = f"📄 {result['file']} (L{result['start_line']}-{result['end_line']}/{result['total_lines']}行)"
        # 附带 git 作者信息(创建人/最后改动人),便于回答"这文件谁开发的"
        author = git_service.get_file_author(repo_id, file_path)
        if "error" not in author:
            bits = []
            if author.get("creator"):
                bits.append(f"创建:{author['creator']['name']}")
            if author.get("last_modifier"):
                bits.append(f"最后修改:{author['last_modifier']['name']}({author['last_modifier']['date']})")
            if bits:
                header += f" · 👤 {' · '.join(bits)}"
        header += "\n\n"
        return ToolResult.ok(header + result["content"])


class ListFilesTool(_RepoScopeMixin, Tool):
    """列出仓库文件树（只读，借鉴 nanobot list_files）"""

    @property
    def name(self) -> str:
        return "listFiles"

    @property
    def description(self) -> str:
        return ("列出 Git 仓库的文件结构。返回指定目录下的文件列表，"
                "支持按文件类型过滤。适用于了解项目结构。")

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_id": self._repo_param_schema(),
                "subdir": {
                    "type": "string",
                    "description": "可选：子目录路径（如 src/main/java）",
                },
                "pattern": {
                    "type": "string",
                    "description": "可选：文件匹配模式（如 *.java），默认列出所有代码文件",
                },
            },
            "required": self._required_with_repo(),
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, repo_id: str = "", subdir: str = "", pattern: str = "*",
                      **kwargs) -> ToolResult:
        """列出文件"""
        repo_id, blocked = self._resolve_repo(repo_id)
        if blocked:
            return blocked
        files = git_service.list_repo_files(repo_id, subdir, pattern)

        if not files:
            return ToolResult.ok(f"仓库 '{repo_id}' 目录 '{subdir}' 下没有匹配的文件。")

        if isinstance(files[0], dict) and "error" in files[0]:
            return ToolResult.error(files[0]["error"])

        lines = [f"仓库 '{repo_id}' 目录 '{subdir or '/'}' 下找到 {len(files)} 个文件：\n"]
        for f in files[:30]:
            size_kb = f["size"] / 1024
            lines.append(f"  {f['path']} ({size_kb:.1f}KB)")

        if len(files) > 30:
            lines.append(f"... 还有 {len(files) - 30} 个文件未显示")

        return ToolResult.ok("\n".join(lines))


class CloneRepoTool(Tool):
    """Clone Git 仓库到本地（写操作）"""

    @property
    def name(self) -> str:
        return "cloneRepo"

    @property
    def description(self) -> str:
        return ("Clone 一个 Git 仓库到本地。提供 Git URL 和仓库名称，"
                "系统会拉取代码到本地以供检索。clone 完成后可以用 searchCode 搜索代码。")

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "git_url": {
                    "type": "string",
                    "description": "Git 仓库地址（如 https://github.com/user/repo.git）",
                },
                "repo_id": {
                    "type": "string",
                    "description": "仓库 ID（用于后续检索，如 my-project）",
                },
                "branch": {
                    "type": "string",
                    "description": "可选：分支名（默认 main）",
                },
            },
            "required": ["git_url", "repo_id"],
        }

    @property
    def read_only(self) -> bool:
        return False  # 写操作：clone 到本地文件系统

    @property
    def exclusive(self) -> bool:
        return True  # 排他操作

    async def execute(self, git_url: str, repo_id: str, branch: str = "main",
                      **kwargs) -> ToolResult:
        """Clone 仓库"""
        result = await git_service.clone_repo(git_url, repo_id, branch)

        if not result.get("success"):
            return ToolResult.error(result.get("error", "clone 失败"))

        # 补写 Repository 表：让 LLM 自助 clone 的仓库进入绑定体系（可被路由/授权）
        db = kwargs.get("db")
        if db is not None:
            try:
                from sqlalchemy import select as _select
                from backend.models.governance import Repository
                existing = (await db.execute(
                    _select(Repository).where(Repository.name == repo_id)
                )).scalar_one_or_none()
                if existing:
                    existing.clone_url = git_url
                    existing.state = "READY"
                else:
                    db.add(Repository(name=repo_id, clone_url=git_url, state="READY"))
                await db.commit()
            except Exception:
                await db.rollback()  # 登记表失败不影响 clone 结果

        msg = (f"仓库 clone 成功！\n"
               f"  仓库 ID: {result['repo_id']}\n"
               f"  分支: {result.get('branch', branch)}\n"
               f"  文件数: {result.get('file_count', '?')}\n"
               f"  本地路径: {result.get('path', '?')}\n\n"
               f"现在可以使用 searchCode、getCodeExcerpt、listFiles 来检索代码。")
        return ToolResult.ok(msg)


# ═══════════════════════════════════════════════
#  注册工具到 Registry
# ═══════════════════════════════════════════════

def get_code_tools(allowed_repos: list[str] | None = None,
                   default_repo: str | None = None) -> dict:
    """
    获取所有代码检索工具实例
    allowed_repos/default_repo：员工绑定仓库作用域，注入 5 个只读检索工具；
    不传（None）则保持全局检索（总前台自答 / 未绑定员工）
    """
    return {
        "searchCode": SearchCodeTool(allowed_repos=allowed_repos, default_repo=default_repo),
        "getCodeExcerpt": GetCodeExcerptTool(allowed_repos=allowed_repos, default_repo=default_repo),
        "listFiles": ListFilesTool(allowed_repos=allowed_repos, default_repo=default_repo),
        "cloneRepo": CloneRepoTool(),
        "getProjectStructure": GetProjectStructureTool(allowed_repos=allowed_repos, default_repo=default_repo),
        "searchInDocs": SearchInDocsTool(allowed_repos=allowed_repos, default_repo=default_repo),
    }


# ═══════════════════════════════════════════════
#  扩展工具（借鉴 nanobot search.py + filesystem.py）
# ═══════════════════════════════════════════════

class GetProjectStructureTool(_RepoScopeMixin, Tool):
    """获取项目结构概览（只读，借鉴 nanobot list_files 的目录树模式）"""

    @property
    def name(self) -> str:
        return "getProjectStructure"

    @property
    def description(self) -> str:
        return ("获取 Git 仓库的项目结构概览。返回目录树（2-3 层深度），包括主要目录和文件类型统计。"
                "适用于快速了解项目架构和技术栈。")

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_id": self._repo_param_schema(),
                "depth": {
                    "type": "integer",
                    "description": "目录树深度（默认 2，最大 4）",
                },
            },
            "required": self._required_with_repo(),
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, repo_id: str = "", depth: int = 2, **kwargs) -> ToolResult:
        """生成项目结构概览"""
        repo_id, blocked = self._resolve_repo(repo_id)
        if blocked:
            return blocked
        depth = min(depth, 4)
        try:
            base = git_service.resolve_safe_path(repo_id, "")
        except ValueError as e:
            return ToolResult.error(str(e))

        if not base.exists():
            return ToolResult.error(f"仓库 '{repo_id}' 不存在")

        # 统计文件类型
        ext_counts = {}
        total_files = 0
        for f in base.rglob("*"):
            if f.is_file() and ".git" not in f.parts and "__pycache__" not in f.parts:
                total_files += 1
                ext = f.suffix.lower() or "(无扩展名)"
                ext_counts[ext] = ext_counts.get(ext, 0) + 1

        # 推断技术栈
        tech_stack = []
        if ext_counts.get(".py", 0) > 3:
            tech_stack.append("Python")
        if ext_counts.get(".java", 0) > 3:
            tech_stack.append("Java")
        if ext_counts.get(".js", 0) + ext_counts.get(".ts", 0) + ext_counts.get(".tsx", 0) > 3:
            tech_stack.append("JavaScript/TypeScript")
        if ext_counts.get(".vue", 0) > 0:
            tech_stack.append("Vue")
        if ext_counts.get(".go", 0) > 0:
            tech_stack.append("Go")

        # 生成目录树
        lines = [f"📦 仓库 '{repo_id}' 结构概览（{total_files} 个文件）\n"]
        if tech_stack:
            lines.append(f"🔧 技术栈：{', '.join(tech_stack)}\n")

        # 文件类型 Top 5
        top_exts = sorted(ext_counts.items(), key=lambda x: -x[1])[:5]
        lines.append("📊 文件类型分布：")
        for ext, count in top_exts:
            lines.append(f"  {ext}: {count} 个")

        lines.append(f"\n📁 目录树（深度 {depth}）：")

        # 递归生成目录树
        def build_tree(path, prefix="", current_depth=0):
            if current_depth >= depth:
                return
            entries = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
            # 过滤
            entries = [e for e in entries if e.name not in {".git", "__pycache__", "node_modules", ".idea", ".vscode"}]
            for i, entry in enumerate(entries[:15]):
                is_last = (i == len(entries[:15]) - 1)
                connector = "└── " if is_last else "├── "
                icon = "📁" if entry.is_dir() else "📄"
                lines.append(f"{prefix}{connector}{icon} {entry.name}")
                if entry.is_dir():
                    extension = "    " if is_last else "│   "
                    build_tree(entry, prefix + extension, current_depth + 1)
            if len(entries) > 15:
                lines.append(f"{prefix}└── ... 还有 {len(entries) - 15} 项")

        build_tree(base)
        return ToolResult.ok("\n".join(lines))


class SearchInDocsTool(_RepoScopeMixin, Tool):
    """搜索文档（只读，借鉴 nanobot search 在文档中的搜索）

    搜索仓库中的 README / API 文档 / Markdown / 配置文件等非代码文件
    """

    @property
    def name(self) -> str:
        return "searchInDocs"

    @property
    def description(self) -> str:
        return ("搜索仓库中的文档文件（README、API 文档、Markdown、YAML 配置等）。"
                "适用于查找使用说明、配置项、API 定义等文档内容。")

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "repo_id": self._repo_param_schema(),
                "query": {
                    "type": "string",
                    "description": "搜索关键词",
                },
            },
            "required": self._required_with_repo("query"),
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, repo_id: str = "", query: str = "", **kwargs) -> ToolResult:
        """搜索文档"""
        repo_id, blocked = self._resolve_repo(repo_id)
        if blocked:
            return blocked
        try:
            base = git_service.resolve_safe_path(repo_id, "")
        except ValueError as e:
            return ToolResult.error(str(e))

        if not base.exists():
            return ToolResult.error(f"仓库 '{repo_id}' 不存在")

        # 文档文件扩展名
        doc_extensions = {".md", ".txt", ".rst", ".yaml", ".yml", ".json",
                          ".xml", ".properties", ".conf", ".ini", ".toml",
                          ".html", ".csv", ".env"}
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

                lines = content.split("\n")
                for line_num, line in enumerate(lines, 1):
                    if query_lower in line.lower():
                        rel_path = str(f.relative_to(base))
                        results.append({
                            "file": rel_path,
                            "line": line_num,
                            "content": line.strip()[:200],
                        })
                        if len(results) >= 15:
                            break
                if len(results) >= 15:
                    break

        if not results:
            return ToolResult.ok(f"在仓库 '{repo_id}' 的文档中未找到 '{query}'。")

        lines = [f"在仓库 '{repo_id}' 的文档中找到 {len(results)} 处匹配 '{query}'：\n"]
        for r in results[:10]:
            lines.append(f"📄 {r['file']}:{r['line']}")
            lines.append(f"   {r['content']}\n")

        return ToolResult.ok("\n".join(lines))
