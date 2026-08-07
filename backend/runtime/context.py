"""
上下文管理 - 借鉴 nanobot agent/context.py + memory.py
适配 Office_Agent：从 Session/Message 表读取历史，绑定岗位包预算

关键设计（借鉴 nanobot）：
1. 短期记忆：从 Message 表读取最近 N 条历史注入上下文
2. 预算追踪：步数/调用数/Token/超时（从 RolePack.spec.budget 加载）
3. SHA 锁定：会话首次检索锁定 commit_sha（对齐 LLD §7.2）
4. Consolidator：token 超预算时压缩旧消息（借鉴 nanobot 降级原样归档）
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.session import Session, Message
from backend.models.agent import Agent


@dataclass
class Budget:
    """
    执行预算（对齐 LLD §7.2 / §14）
    从 RolePack.spec.permission.budget 加载
    """
    max_steps: int = 8          # 最大推理步数
    max_calls: int = 6          # 最大工具调用次数
    timeout_sec: int = 60       # 总超时（秒）
    max_token: int = 48000      # Token 上限

    # 运行时计数
    current_step: int = 0
    current_calls: int = 0
    current_token: int = 0

    def can_continue(self) -> bool:
        """是否还有预算"""
        return (
            self.current_step < self.max_steps
            and self.current_calls < self.max_calls
            and self.current_token < self.max_token
        )

    def consume_step(self) -> None:
        self.current_step += 1

    def consume_call(self) -> None:
        self.current_calls += 1

    def consume_token(self, tokens: int) -> None:
        self.current_token += tokens

    @property
    def remaining_steps(self) -> int:
        return max(0, self.max_steps - self.current_step)

    @property
    def remaining_calls(self) -> int:
        return max(0, self.max_calls - self.current_calls)


@dataclass
class AgentContext:
    """
    Agent 执行上下文（借鉴 nanobot agent/context.py）
    绑定 Office_Agent 业务：员工档案 + 岗位包 + 预算 + 会话历史
    """
    # 业务身份
    agent: Agent                      # 当前执行的员工
    session_id: str                   # 会话 ID
    department_name: str = ""         # 部门名
    domain_name: str = ""             # 领域名

    # 岗位包配置（从 RolePack.spec 加载）
    role_pack_spec: dict = field(default_factory=dict)  # 岗位包完整定义
    allowed_tools: list[str] = field(default_factory=list)  # 工具白名单
    allowed_skills: list[str] = field(default_factory=list)  # 能力白名单（skill_key 或历史名称）
    skill_specs: list[dict] = field(default_factory=list)  # 能力详情 [{skill_key,name,description,instructions}]
    resources: list[str] = field(default_factory=list)  # 授权资源（展示用）

    # 代码仓库作用域（从 AgentRepoBinding -> Repository 解析）
    # 候选同时含仓库 name 与 id，兼容历史 clone 用 uuid 当目录名的数据；
    # 为空表示不限制（总前台自答 / 未绑定员工保持全局检索）
    allowed_repos: list[str] = field(default_factory=list)  # 绑定仓库白名单
    default_repo: Optional[str] = None  # 恰好绑定 1 个仓库时自动填充，repo_id 可省略
    # 绑定仓库详情 [{name, description}],prompt 动态渲染「绑定仓库+说明」用,
    # 取代 agents_md 里手写的易漂移仓库清单
    repo_details: list[dict] = field(default_factory=list)

    # 资源中心已上传文档的名称清单,prompt 渲染「已上传文档」用:
    # 让 LLM 知道文档存在、可经 searchResource 按名检索读正文(否则只会闷头搜代码仓库)
    doc_resources: list[str] = field(default_factory=list)

    # 预算
    budget: Budget = field(default_factory=Budget)

    # 会话历史（短期记忆）
    history: list[dict] = field(default_factory=list)  # OpenAI 格式消息

    # 代码版本锁定（对齐 LLD §7.2）
    commit_sha: Optional[str] = None

    # ACL 过滤条件
    acl_filters: dict = field(default_factory=dict)

    # 收集的证据
    evidence_cards: list[dict] = field(default_factory=list)

    @property
    def role_pack_name(self) -> str:
        return self.role_pack_spec.get("name", "")

    @property
    def read_only(self) -> bool:
        """是否只读模式（从岗位包权限配置加载）"""
        perm = self.role_pack_spec.get("permission", {})
        return perm.get("read_only", True)


async def build_context(
    agent: Agent,
    session_id: str,
    db: AsyncSession,
    role_pack_spec: dict | None = None,
    dept_name: str = "",
    domain_name: str = "",
    history_limit: int = 10,
) -> AgentContext:
    """
    构建 Agent 执行上下文
    1. 从 Message 表加载历史（短期记忆）
    2. 从 RolePack.spec 加载工具白名单 + 预算
    3. 初始化预算计数器
    """
    # 从岗位包配置加载
    spec = role_pack_spec or {}
    perm = spec.get("permission", {})
    budget_def = perm.get("budget", {})

    budget = Budget(
        max_steps=budget_def.get("steps", 8),
        max_calls=budget_def.get("calls", 6),
        timeout_sec=budget_def.get("timeout", 60),
        max_token=budget_def.get("token", 48000),
    )

    # 工具白名单
    allowed_tools = spec.get("tools", [])
    # Agent 直绑 skills（skill_key 列表）优先，回退岗位包 spec.skills（历史数据可能是名称）
    allowed_skills = agent.skills or spec.get("skills", [])
    resources = agent.resources or spec.get("resources", [])

    # 解析能力详情（一次 IN 查询；skill_key 与名称双兼容，兼容历史"名称"数据）
    # instructions 保留全文：prompt 里只注入摘要（build_system_prompt 控制），
    # 全文由 LLM 需要时通过 loadSkill 工具按需获取（省 token）
    skill_specs = []
    if allowed_skills:
        from backend.models.resource import Skill  # 函数内 import，避免模块级循环
        rows = (await db.execute(
            select(Skill).where(
                or_(Skill.skill_key.in_(allowed_skills), Skill.name.in_(allowed_skills))
            )
        )).scalars().all()
        skill_specs = [{
            "skill_key": s.skill_key,
            "name": s.name,
            "description": (s.description or "")[:300],
            "instructions": s.instructions or "",
        } for s in rows]

    # 解析员工绑定的代码仓库（AgentRepoBinding -> Repository）
    # 失败静默降级为空列表 = 全局检索（总前台自答 / 未绑定员工不受影响）
    allowed_repos: list[str] = []
    default_repo: Optional[str] = None
    repo_details: list[dict] = []
    try:
        from backend.models.governance import AgentRepoBinding, Repository
        binding_repo_ids = (await db.execute(
            select(AgentRepoBinding.repo_id).where(AgentRepoBinding.agent_id == agent.id)
        )).scalars().all()
        if binding_repo_ids:
            repos = (await db.execute(
                select(Repository).where(Repository.id.in_(binding_repo_ids))
            )).scalars().all()
            # 候选同时收集 name 与 id，兼容历史 clone 用 uuid 当目录名的数据
            for r in repos:
                if r.name and r.name not in allowed_repos:
                    allowed_repos.append(r.name)
                if r.id and r.id not in allowed_repos:
                    allowed_repos.append(r.id)
                repo_details.append({"name": r.name, "description": r.description or ""})
            # 恰好绑定 1 个仓库时作为默认值，工具调用可省略 repo_id
            named = [r.name for r in repos if r.name]
            if len(set(named)) == 1:
                default_repo = named[0]
    except Exception:
        pass  # 绑定解析失败不阻断执行，保持全局检索

    # 资源中心已上传文档清单（只取名称,prompt 展示用;上限 20 条防膨胀）
    # 失败静默降级为空列表 = 不渲染文档段,不影响主流程
    doc_resources: list[str] = []
    try:
        from backend.models.resource import Resource
        doc_resources = (await db.execute(
            select(Resource.name).where(Resource.type == "document").limit(20)
        )).scalars().all()
    except Exception:
        pass  # 文档清单加载失败不阻断执行

    # 从 Message 表加载历史（借鉴 nanobot session 回放）
    history = []
    try:
        result = await db.execute(
            select(Message)
            .where(Message.session_id == session_id)
            .order_by(Message.created_at.desc())
            .limit(history_limit)
        )
        msgs = result.scalars().all()
        # 按时间正序排列
        msgs = list(reversed(msgs))
        for msg in msgs:
            if msg.role == "user":
                history.append({"role": "user", "content": msg.content})
            elif msg.role == "assistant":
                history.append({"role": "assistant", "content": msg.content})
    except Exception:
        pass  # 历史加载失败不阻断执行

    return AgentContext(
        agent=agent,
        session_id=session_id,
        department_name=dept_name,
        domain_name=domain_name,
        role_pack_spec=spec,
        allowed_tools=allowed_tools,
        allowed_skills=allowed_skills,
        skill_specs=skill_specs,
        resources=resources,
        allowed_repos=allowed_repos,
        default_repo=default_repo,
        repo_details=repo_details,
        doc_resources=doc_resources,
        budget=budget,
        history=history,
    )


def build_system_prompt(context: AgentContext) -> str:
    """
    构建 system prompt（借鉴 nanobot 的 Stable + Volatile 分层）
    Stable：岗位身份 + 职责 + 工具契约 + 行动规则
    Volatile：会话上下文 + 已收集证据

    关键改进：强约束 LLM 必须使用工具获取信息（借鉴 nanobot 的"不编造"约束）
    """
    agent = context.agent

    # === Stable 层（不变） ===
    prompt = f"""你是「{agent.name}」，{agent.title}，隶属于{context.department_name}的{context.domain_name}。

## 岗位职责
{agent.description}

## 授权资源
"""
    # 绑定的代码仓库（来自 AgentRepoBinding，检索工具会自动限定在该范围内）
    # 渲染 name + description(职责说明存 repository.description,改绑定/改说明即生效,不再有 agents_md 漂移)
    if context.repo_details:
        prompt += "  绑定代码仓库：\n"
        for r in context.repo_details:
            desc = f" — {r['description']}" if r.get("description") else ""
            prompt += f"  - 💻 {r['name']}{desc}\n"
    # 资源中心已上传文档（searchResource 按名称命中可直接返回正文阅读）
    if context.doc_resources:
        prompt += "  已上传文档（问文档内容时调 searchResource 按名称检索，可直接阅读正文）：\n"
        for name in context.doc_resources:
            prompt += f"  - 📄 {name}\n"
    # resources 字符串列表降级为补充展示（不再作为任何逻辑输入）
    for r in context.resources:
        prompt += f"  - {r}\n"
    if not context.repo_details and not context.doc_resources and not context.resources:
        prompt += "  （未绑定专属资源，可全局检索）\n"

    # AGENTS.md 行为准则（Harness Engineering：员工级人格/边界指令，截断防 prompt 膨胀）
    if agent.agents_md:
        prompt += f"\n## 行为准则（AGENTS.md）\n{agent.agents_md[:4000]}\n"

    # 工具说明（详细描述每个工具的用途，引导 LLM 调用）
    if context.allowed_tools:
        prompt += "\n## 可用工具\n"
        # searchCode 在有默认仓库时提示可省略 repo_id
        search_code_desc = "searchCode(repo_id, query, file_pattern?) - 在 Git 仓库中搜索代码关键词。返回匹配的文件名、行号和代码片段。查找函数定义、变量使用时调用。"
        if context.default_repo:
            search_code_desc += f"（当前授权仓库：{context.default_repo}，repo_id 可省略）"
        tool_descs = {
            "searchKnowledge": f"searchKnowledge(query, domain?) - 搜索已审核通过的知识库，查找业务文档、FAQ、最佳实践。当你需要查找业务知识、规范、流程时调用。（默认按「{context.domain_name}」领域过滤）" if context.domain_name and context.domain_name != "通用" else "searchKnowledge(query, domain?) - 搜索已审核通过的知识库，查找业务文档、FAQ、最佳实践。当你需要查找业务知识、规范、流程时调用。",
            "getEmployeeInfo": 'getEmployeeInfo(keyword) - 查找公司内的 AI 员工信息，包括姓名、职位、所属部门、专业领域。当用户问"谁负责""有哪些员工"时调用。',
            "searchResource": "searchResource(keyword, type?) - 搜索公司资源库（代码仓库、API 文档、数据集、已上传文档）。文档类资源按名称命中后直接返回正文内容，可阅读。当用户提到具体文档名（如《xxx指引.md》）或要查文档内容时，优先调用。",
            "searchCode": search_code_desc,
            "getCodeExcerpt": "getCodeExcerpt(repo_id, file_path, start_line?, end_line?) - 读取代码文件的指定片段。查看函数实现、配置内容时调用。",
            "listFiles": "listFiles(repo_id, subdir?, pattern?) - 列出仓库文件结构。了解项目结构时调用。",
            "cloneRepo": 'cloneRepo(git_url, repo_id, branch?) - Clone 一个 Git 仓库到本地。用户提供 Git 地址时调用，clone 后可用 searchCode 检索。',
            "getProjectStructure": "getProjectStructure(repo_id, depth?) - 获取项目结构概览（目录树+技术栈+文件统计）。了解项目架构时调用。",
            "searchInDocs": "searchInDocs(repo_id, query) - 搜索仓库文档（README/配置/API文档）。查找使用说明、配置项时调用。",
            "loadSkill": "loadSkill(skill_key) - 加载指定能力的完整指令（SKILL.md）。当任务需要使用某项能力的具体流程/规范时调用。",
        }
        for t in context.allowed_tools:
            if t in tool_descs:
                prompt += f"  - {tool_descs[t]}\n"
            else:
                # 不在内置工具表中的名字 = MCP Server 名，输出兜底行让 LLM 感知外部能力
                prompt += f"  - {t}（MCP 外部工具集，具体工具见 function 定义）\n"

    # 能力摘要注入（省 token：只注入名称+简介，指令全文由 LLM 需要时调 loadSkill 获取）
    # 兜底：仅 1 个 skill 且指令很短时直接内联全文，省一次工具调用
    if context.skill_specs:
        prompt += "\n## 具备能力（Skills）\n"
        inline_full = (
            len(context.skill_specs) == 1
            and len(context.skill_specs[0].get("instructions") or "") < 600
        )
        for sp in context.skill_specs[:10]:  # 上限 10 条，防 prompt 膨胀
            prompt += f"### {sp['name']}（{sp['skill_key']}）\n{sp['description'][:200]}\n"
            if inline_full and sp.get("instructions"):
                prompt += f"指令：\n{sp['instructions']}\n"
        if not inline_full:
            prompt += "（以上为能力摘要，需要某项能力的完整执行指令时，调用 loadSkill 获取）\n"
    elif context.allowed_skills:
        prompt += f"\n## 具备能力\n{', '.join(context.allowed_skills)}\n"

    # 权限边界
    if context.read_only:
        prompt += "\n## 权限边界\n⚠️ 只读模式：所有工具仅允许查询，不可执行写操作。跨部门协作需对接人授权。\n"

    # 预算
    prompt += f"\n## 执行预算\n最多 {context.budget.max_steps} 步推理、{context.budget.max_calls} 次工具调用、{context.budget.timeout_sec}s 超时。\n"

    # === 行动规则（强约束，借鉴 nanobot 的"不编造"原则） ===
    prompt += f"""
## 行动规则（必须遵守）
1. **先查后答**：当用户询问公司信息、员工、文档、资源时，必须先调用对应工具获取数据，不要凭记忆回答。
2. **工具优先**：如果你有可用的工具，优先使用工具获取信息，再基于结果回答。
3. **数据准确**：回答必须基于工具返回的真实数据，不可编造员工姓名、资源名称或业务流程。
4. **领域边界**：只回答与{context.domain_name}相关的问题，超出范围时明确告知并建议转交其他领域。
5. **信息不足时**：如果工具未返回相关结果，明确告知"未找到相关信息"，不要编造答案。
6. **回答详尽**：默认给出完整、有深度的回答——先给结论，再展开背景、分析、步骤或示例，把问题讲透；涉及列表时用表格或项目符号，涉及代码时给出示例。不要只用一两句话概括作答（用户明确要求简短时除外）。
7. **整合加工**：工具返回的数据要整合、解释后再呈现，不要只做简单转述；在数据基础上给出你的分析和可执行建议。

## 工具调用示例
用户问"公司有哪些员工" -> 调用 getEmployeeInfo(keyword="员工")
用户问"搜索支付文档" -> 调用 searchKnowledge(query="支付")
用户问"《新车联网平台接口对接指引》里怎么规定的" -> 调用 searchResource(keyword="新车联网平台接口对接指引")
用户问"有哪些API文档" -> 调用 searchResource(keyword="API", type="document")
用户问"帮我 clone 这个仓库 https://github.com/xxx" -> 调用 cloneRepo(git_url="...", repo_id="xxx")
用户问"搜索 createOrder 函数" -> 调用 searchCode(repo_id="xxx", query="createOrder")
用户问"看一下 OrderService.java 的代码" -> 调用 getCodeExcerpt(repo_id="xxx", file_path="src/OrderService.java")
用户问"项目有哪些文件" -> 调用 listFiles(repo_id="xxx")
"""

    # === Volatile 层（变化） ===
    if context.evidence_cards:
        prompt += f"\n## 已收集的证据（{len(context.evidence_cards)} 条）\n"
        for ev in context.evidence_cards[-5:]:
            prompt += f"  - {ev.get('source', '未知')}: {ev.get('summary', '')}\n"

    # 历史上下文提示
    if context.history:
        prompt += f"\n## 会话上下文\n本次对话已有 {len(context.history)} 条历史消息，请参考上下文回答。\n"

    return prompt
