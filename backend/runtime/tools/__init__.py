"""
内置工具 - 借鉴 nanobot agent/tools/filesystem.py 等
适配 Office_Agent 业务：搜索知识库 / 获取员工信息 / 搜索资源

设计要点：
1. 全部 read_only=True（只读，可并发）
2. 绑定业务数据：从数据库查询，不是文件系统操作
3. 返回 ToolResult（字符串直接喂回模型）
"""
from sqlalchemy import select, or_, literal
from sqlalchemy.ext.asyncio import AsyncSession

from backend.runtime.tool_base import Tool, ToolResult
from backend.runtime.tool_registry import ToolRegistry
from backend.models.knowledge import KnowledgeCandidate
from backend.models.agent import Agent
from backend.models.resource import Resource, Skill
from backend.models.company import Department, Domain


def _domain_bidir_filter(d: str):
    """
    领域双向包含过滤条件（按领域约定绑定知识库）
    兼容历史数据命名不一致："后端" 能匹配 "后端域"，反之亦然
    """
    return or_(
        KnowledgeCandidate.domain.contains(d),
        literal(d).contains(KnowledgeCandidate.domain),
    )


class SearchKnowledgeTool(Tool):
    """搜索知识库（只读）"""

    def __init__(self, default_domain: str = ""):
        # 员工所属领域：LLM 未显式传 domain 时按此过滤；空/"通用" = 全局检索（总前台兼容）
        self._default_domain = default_domain or ""

    @property
    def name(self) -> str:
        return "searchKnowledge"

    @property
    def description(self) -> str:
        desc = "搜索已审核通过的知识库，查找业务文档、FAQ、最佳实践。输入搜索关键词。"
        if self._default_domain and self._default_domain != "通用":
            desc += f"（默认按「{self._default_domain}」领域过滤，可传 domain 参数检索其他领域）"
        return desc

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词（可为空，空时返回最新知识）",
                },
                "domain": {
                    "type": "string",
                    "description": "可选：限定领域（如 后端域/前端域）",
                },
            },
            "required": [],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, db: AsyncSession, query: str, domain: str = "") -> ToolResult:
        """执行搜索：LLM 显式传 domain 优先；否则回落到员工默认领域；空/"通用" 全局"""
        effective_domain = domain or self._default_domain
        sql = select(KnowledgeCandidate).where(
            KnowledgeCandidate.state == "APPROVED"
        )
        if effective_domain and effective_domain != "通用":
            sql = sql.where(_domain_bidir_filter(effective_domain))
        sql = sql.order_by(KnowledgeCandidate.created_at.desc()).limit(5)

        result = await db.execute(sql)
        items = result.scalars().all()

        # 关键词过滤（简化版，实际应该用全文检索）
        if query:
            items = [k for k in items if query.lower() in (k.title + k.body_md).lower()][:3]

        if not items:
            scope_hint = f"（领域：{effective_domain}）" if effective_domain else ""
            return ToolResult.ok(f"未找到与 '{query}' 相关的知识{scope_hint}。")

        lines = [f"找到 {len(items)} 条相关知识：\n"]
        for k in items:
            lines.append(f"### {k.title}\n领域: {k.domain} | 置信度: {k.confidence}\n{k.body_md[:500]}\n")
        return ToolResult.ok("\n".join(lines))


class GetEmployeeInfoTool(Tool):
    """获取员工信息（只读）"""

    @property
    def name(self) -> str:
        return "getEmployeeInfo"

    @property
    def description(self) -> str:
        return "查找公司内的 AI 员工信息，包括姓名、职位、所属部门、专业领域。输入员工姓名或领域关键词。"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "员工姓名或领域关键词（可为空，空时返回全部员工）",
                },
            },
            "required": [],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, db: AsyncSession, keyword: str = "") -> ToolResult:
        """执行搜索（keyword 为空时返回全部员工）"""
        sql = select(Agent).where(Agent.status.in_(["online", "trial"]))
        if keyword:
            sql = sql.where(or_(
                Agent.name.contains(keyword),
                Agent.title.contains(keyword),
            ))
        sql = sql.limit(10)
        result = await db.execute(sql)
        agents = result.scalars().all()

        if not agents:
            return ToolResult.ok(f"未找到相关员工。")

        # 查询部门/领域名
        all_depts = {d.id: d.name for d in (await db.execute(select(Department))).scalars().all()}
        all_domains = {d.id: d.name for d in (await db.execute(select(Domain))).scalars().all()}

        lines = [f"找到 {len(agents)} 位员工：\n"]
        for agent in agents:
            dept_name = all_depts.get(agent.department_id, "未知")
            domain_name = all_domains.get(agent.domain_id, "未知")
            lines.append(f"- {agent.emoji} {agent.name}（{agent.title}）\n  部门: {dept_name} | 领域: {domain_name} | 状态: {agent.status}\n  职责: {(agent.description or '')[:200]}\n")
        return ToolResult.ok("\n".join(lines))


class SearchResourceTool(Tool):
    """搜索授权资源（只读）"""

    @property
    def name(self) -> str:
        return "searchResource"

    @property
    def description(self) -> str:
        return "搜索公司资源库（代码仓库、API 文档、数据集）。文档类资源返回正文内容，可直接阅读。输入资源名称或正文关键词。"

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "keyword": {
                    "type": "string",
                    "description": "资源名称或正文关键词（可为空，空时返回全部资源）",
                },
                "type": {
                    "type": "string",
                    "enum": ["service", "document", "dataset", "knowledge"],
                    "description": "可选：资源类型",
                },
            },
            "required": [],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, db: AsyncSession, keyword: str = "", type: str = "") -> ToolResult:
        """执行搜索：名称命中返回正文预览；名称无命中则退到正文 LIKE 检索并返回命中片段"""
        from backend.services import file_service  # 函数内 import，避免模块级循环依赖

        def _content_of(r: Resource) -> str:
            # 正文 DB 优先;content 未回填时读本机 uploads 兜底(与 admin.py 取文档行为一致)
            if r.content:
                return r.content
            if (r.url or "").endswith("/md"):
                return file_service.read_upload_md(r.id) or ""
            return ""

        sql = select(Resource)
        if type:
            sql = sql.where(Resource.type == type)
        items = (await db.execute(sql)).scalars().all()
        kw = (keyword or "").strip().lower()

        if kw:
            name_hits = [r for r in items if kw in (r.name or "").lower()]
            if name_hits:
                hits, mode = name_hits[:5], "name"
            else:
                hits = [r for r in items if kw in _content_of(r).lower()][:5]
                mode = "content"
        else:
            hits, mode = items[:5], "all"

        if not hits:
            return ToolResult.ok(f"未找到与 '{keyword}' 相关的资源。")

        lines = [f"找到 {len(hits)} 个相关资源：\n"]
        for r in hits:
            content = _content_of(r)
            lines.append(f"- {r.icon} {r.name}（类型: {r.type}）\n  URL: {r.url or '无'} | 状态: {r.status}\n  描述: {(r.description or '')[:200]}\n")
            # name 命中且正文可读:附正文预览,LLM 可直接阅读文档内容
            if mode == "name" and content:
                preview = content[:2000]
                more = f"\n  …（全文共 {len(content)} 字，可换更精确的正文关键词继续检索）" if len(content) > 2000 else ""
                lines.append(f"  正文:\n{preview}{more}\n")
            elif mode == "name":
                # 正文不可读(content 未入库且本机无文件)时必须显式告知,
                # 否则 LLM 会凭文档名+描述臆造内容当作文档事实输出(实测发生过)
                lines.append("  ⚠️ 正文暂不可读（内容未同步到本机）。禁止凭文档名称或描述推测文档内容；"
                             "请如实告知用户:文档已收录、正文待同步,并给出文档 URL。\n")
            elif mode == "content":
                idx = content.lower().find(kw)
                start = max(0, idx - 150)
                end = min(len(content), idx + len(kw) + 150)
                snippet = ("…" if start > 0 else "") + content[start:end] + ("…" if end < len(content) else "")
                lines.append(f"  正文命中片段: {snippet}\n")
        return ToolResult.ok("\n".join(lines))


class LoadSkillTool(Tool):
    """按需加载能力完整指令（只读）

    配合 system prompt 的 Skill 摘要注入：prompt 只放 name+description，
    LLM 需要某项能力的具体流程/规范时调用本工具取 instructions 全文（省 token）
    """

    @property
    def name(self) -> str:
        return "loadSkill"

    @property
    def description(self) -> str:
        return ("加载指定能力（Skill）的完整执行指令。当你需要使用某项能力的"
                "具体流程、规范或步骤时调用，传入能力的 skill_key。")

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "skill_key": {
                    "type": "string",
                    "description": "能力标识（system prompt 「具备能力」段括号中的 skill_key）",
                },
            },
            "required": ["skill_key"],
        }

    @property
    def read_only(self) -> bool:
        return True

    async def execute(self, db: AsyncSession, skill_key: str = "") -> ToolResult:
        """按 skill_key（兼容名称）查询并返回能力完整指令"""
        skill = (await db.execute(
            select(Skill).where(
                or_(Skill.skill_key == skill_key, Skill.name == skill_key)
            )
        )).scalars().first()

        if not skill:
            # 未找到：返回可用能力列表引导 LLM 纠正
            all_skills = (await db.execute(select(Skill))).scalars().all()
            if all_skills:
                available = "、".join(f"{s.skill_key}({s.name})" for s in all_skills[:20])
                return ToolResult.ok(f"未找到能力 '{skill_key}'。可用能力：{available}")
            return ToolResult.ok(f"未找到能力 '{skill_key}'，系统中暂无已注册能力。")

        text = f"# {skill.name}（{skill.skill_key}）\n\n{skill.description or ''}\n\n"
        text += skill.instructions or "（该能力暂无详细指令）"
        return ToolResult.ok(text)


# ═══════════════════════════════════════════════
#  工具注册工厂：根据岗位包白名单构建 Registry
# ═══════════════════════════════════════════════

def build_tool_registry(allowed_tools: list[str],
                        allowed_repos: list[str] | None = None,
                        default_repo: str | None = None,
                        default_domain: str = "") -> ToolRegistry:
    """
    根据岗位包工具白名单构建 ToolRegistry
    借鉴 nanobot ToolLoader：按 scope 加载工具，子代理用独立 registry 做能力隔离

    作用域参数（员工绑定关系注入，默认 None/空 = 全局行为，向后兼容）：
    - allowed_repos / default_repo：代码检索工具的仓库白名单与默认仓库
    - default_domain：知识库检索的默认领域过滤

    工具清单（3 类）：
    1. 业务工具：searchKnowledge / getEmployeeInfo / searchResource / loadSkill
    2. 代码工具：searchCode / getCodeExcerpt / listFiles / cloneRepo
    """
    registry = ToolRegistry()

    # 业务工具（从数据库查询）
    biz_tools = {
        "searchKnowledge": SearchKnowledgeTool(default_domain=default_domain),
        "getEmployeeInfo": GetEmployeeInfoTool(),
        "searchResource": SearchResourceTool(),
        "loadSkill": LoadSkillTool(),
    }

    # 代码检索工具（从本地 Git 仓库检索，注入绑定仓库作用域）
    from backend.runtime.tools.code_tools import get_code_tools
    code_tools = get_code_tools(allowed_repos=allowed_repos, default_repo=default_repo)

    # 合并所有工具
    all_tools = {**biz_tools, **code_tools}

    # 按白名单注册
    for name in allowed_tools:
        if name in all_tools:
            registry.register(all_tools[name])

    # 白名单为空 = 不限制，注册全部（兜底）
    # 注意：白名单非空但无匹配（如仅含 MCP server 名）不再放开全部内置工具，
    #       MCP 工具由 frontdesk 另行注入（runtime/mcp_client.py）
    if not allowed_tools:
        for tool in all_tools.values():
            registry.register(tool)

    return registry
