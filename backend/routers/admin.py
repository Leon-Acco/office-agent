"""
管理与治理路由 — 完整 CRUD
7 大模块：组织管理 / 资源中心 / 能力中心 / 工具中心 / 岗位库 / 员工管理 / 权限与审计
"""
import json
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select, func, delete, or_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models.agent import Agent, RolePack
from backend.models.company import Company, Department, Domain
from backend.models.governance import AgentRepoBinding, Repository
from backend.models.knowledge import KnowledgeCandidate
from backend.models.resource import Resource, Skill, Tool, AuditLog
from backend.services.llm import chat_completion
from backend.services.skill_validator import (
    validate_skill_payload, parse_skill_content, extract_llm_json,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _uuid() -> str:
    return uuid.uuid4().hex


# ════════════════════════════════════════════════
#  统计 & 步骤
# ════════════════════════════════════════════════

@router.get("/stats")
async def admin_stats(db: AsyncSession = Depends(get_db)):
    """管理后台统计数据"""
    counts = {}
    for model, key in [(Department, "department_count"), (Agent, "agent_count"),
                       (Domain, "domain_count"), (KnowledgeCandidate, "knowledge_count"),
                       (Resource, "resource_count"), (Skill, "skill_count"),
                       (Tool, "tool_count"), (RolePack, "role_pack_count")]:
        counts[key] = (await db.execute(select(func.count(model.id)))).scalar() or 0

    counts["online_agents"] = (await db.execute(
        select(func.count(Agent.id)).where(Agent.status == "online"))).scalar() or 0
    counts["in_trial"] = (await db.execute(
        select(func.count(Agent.id)).where(Agent.status == "trial"))).scalar() or 0
    counts["pending_check"] = (await db.execute(
        select(func.count(Agent.id)).where(Agent.status == "pending_check"))).scalar() or 0
    return counts


@router.get("/steps")
async def admin_steps():
    """返回配置向导步骤定义（8 步，对齐产品 PRD）"""
    return [
        {"step": i + 1, "title": t} for i, t in enumerate([
            "基本信息", "归属", "组装岗位包", "权限",
            "输出承诺", "预检", "试运行", "提交上线"
        ])
    ]


# ════════════════════════════════════════════════
#  1. 组织管理 — 部门 + 领域 CRUD
# ════════════════════════════════════════════════

class DeptBody(BaseModel):
    name: str
    emoji: str = "📦"
    description: str = ""

class DomainBody(BaseModel):
    name: str
    department_id: str
    description: str = ""


@router.get("/org")
async def get_org_tree(db: AsyncSession = Depends(get_db)):
    """获取组织树：部门 → 领域"""
    depts = (await db.execute(select(Department))).scalars().all()
    domains = (await db.execute(select(Domain))).scalars().all()

    return [
        {
            "id": d.id, "name": d.name, "emoji": d.emoji,
            "description": d.description,
            "domains": [
                {"id": dm.id, "name": dm.name, "description": dm.description}
                for dm in domains if dm.department_id == d.id
            ],
        }
        for d in depts
    ]


@router.post("/departments")
async def create_dept(body: DeptBody, db: AsyncSession = Depends(get_db)):
    # 确保有默认公司（没有则自动创建）
    company = (await db.execute(select(Company))).scalars().first()
    if not company:
        company = Company(id=_uuid(), name="Agent 办公室", description="AI 虚拟公司")
        db.add(company)
        await db.flush()

    dept = Department(id=_uuid(), company_id=company.id,
                      name=body.name, emoji=body.emoji, description=body.description)
    db.add(dept)
    await db.flush()
    return {"id": dept.id, "message": "部门创建成功"}


@router.put("/departments/{dept_id}")
async def update_dept(dept_id: str, body: DeptBody, db: AsyncSession = Depends(get_db)):
    dept = (await db.execute(select(Department).where(Department.id == dept_id))).scalar_one_or_none()
    if not dept:
        raise HTTPException(404, "部门不存在")
    dept.name = body.name
    dept.emoji = body.emoji
    dept.description = body.description
    await db.flush()
    return {"message": "部门更新成功"}


@router.delete("/departments/{dept_id}")
async def delete_dept(dept_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Domain).where(Domain.department_id == dept_id))
    await db.execute(delete(Department).where(Department.id == dept_id))
    await db.flush()
    return {"message": "部门已删除"}


@router.post("/domains")
async def create_domain(body: DomainBody, db: AsyncSession = Depends(get_db)):
    dm = Domain(id=_uuid(), department_id=body.department_id, name=body.name, description=body.description)
    db.add(dm)
    await db.flush()
    return {"id": dm.id, "message": "领域创建成功"}


@router.put("/domains/{domain_id}")
async def update_domain(domain_id: str, body: DomainBody, db: AsyncSession = Depends(get_db)):
    dm = (await db.execute(select(Domain).where(Domain.id == domain_id))).scalar_one_or_none()
    if not dm:
        raise HTTPException(404, "领域不存在")
    dm.name = body.name
    dm.department_id = body.department_id
    dm.description = body.description
    await db.flush()
    return {"message": "领域更新成功"}


@router.delete("/domains/{domain_id}")
async def delete_domain(domain_id: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Domain).where(Domain.id == domain_id))
    await db.flush()
    return {"message": "领域已删除"}


# 兼容旧接口
@router.get("/departments")
async def list_departments(db: AsyncSession = Depends(get_db)):
    return await get_org_tree(db)


@router.get("/domains")
async def list_domains(db: AsyncSession = Depends(get_db)):
    domains = (await db.execute(select(Domain))).scalars().all()
    return [{"id": d.id, "name": d.name, "department_id": d.department_id, "description": d.description} for d in domains]


# ════════════════════════════════════════════════
#  2. 资源中心 CRUD
# ════════════════════════════════════════════════

class ResourceBody(BaseModel):
    name: str
    type: str = "document"
    icon: str = "📄"
    description: str = ""
    url: str = ""
    owner: str = ""


@router.get("/resources")
async def list_resources(type: str | None = None, db: AsyncSession = Depends(get_db)):
    # type 过滤（如 ?type=document 只取已上传文档，供员工表单「知识资源」勾选用）
    stmt = select(Resource).order_by(Resource.created_at.desc())
    if type:
        stmt = stmt.where(Resource.type == type)
    resources = (await db.execute(stmt)).scalars().all()
    if not resources:
        # 如果 Resource 表为空，从 Agent.resources JSON 字段聚合
        agents = (await db.execute(select(Agent))).scalars().all()
        seen = set()
        result = []
        for a in agents:
            for r in (a.resources or []):
                if r not in seen:
                    seen.add(r)
                    parts = r.split(" ", 1)
                    icon = parts[0] if len(parts) > 1 else "📄"
                    name = parts[1] if len(parts) > 1 else r
                    result.append({"id": r, "name": name, "type": "service" if "💻" in icon else "document",
                                   "icon": icon, "description": name, "url": "", "owner": "", "status": "ready"})
        return result
    return [{"id": r.id, "name": r.name, "type": r.type, "icon": r.icon,
             "description": r.description, "url": r.url, "owner": r.owner, "status": r.status} for r in resources]


@router.get("/resources/search")
async def search_resources(q: str = "", db: AsyncSession = Depends(get_db)):
    """
    资源检索:名称 + 已解析 Markdown 正文 LIKE 匹配,返回命中片段(±60 字)
    注意:必须注册在 /resources/{rid} 之前,否则 search 会被路径参数吞掉
    """
    from backend.services import file_service
    q = q.strip()
    if not q:
        return []
    ql = q.lower()
    hits = []
    resources = (await db.execute(select(Resource).order_by(Resource.created_at.desc()))).scalars().all()
    for r in resources:
        if ql in (r.name or "").lower():
            hits.append({"id": r.id, "name": r.name, "type": r.type, "icon": r.icon,
                         "match_in": "name", "snippet": (r.description or "")[:120]})
            continue
        # 正文检索:DB content 优先(md 全文已入库,跨机可读),本机文件兜底兼容旧数据
        md = r.content or (file_service.read_upload_md(r.id) if (r.url or "").endswith("/md") else None)
        if md:
            idx = md.lower().find(ql)
            if idx >= 0:
                start = max(0, idx - 60)
                end = min(len(md), idx + len(q) + 60)
                snippet = ("…" if start > 0 else "") + md[start:end] + ("…" if end < len(md) else "")
                hits.append({"id": r.id, "name": r.name, "type": r.type, "icon": r.icon,
                             "match_in": "content", "snippet": snippet})
    return hits


@router.post("/resources")
async def create_resource(body: ResourceBody, db: AsyncSession = Depends(get_db)):
    r = Resource(id=_uuid(), name=body.name, type=body.type, icon=body.icon,
                 description=body.description, url=body.url or None, owner=body.owner)
    db.add(r)
    await db.flush()
    return {"id": r.id, "message": "资源创建成功"}


@router.put("/resources/{rid}")
async def update_resource(rid: str, body: ResourceBody, db: AsyncSession = Depends(get_db)):
    r = (await db.execute(select(Resource).where(Resource.id == rid))).scalar_one_or_none()
    if not r:
        raise HTTPException(404, "资源不存在")
    r.name, r.type, r.icon = body.name, body.type, body.icon
    r.description, r.url, r.owner = body.description, body.url or None, body.owner
    await db.flush()
    return {"message": "资源更新成功"}


@router.delete("/resources/{rid}")
async def delete_resource(rid: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Resource).where(Resource.id == rid))
    await db.flush()
    return {"message": "资源已删除"}


@router.post("/resources/upload")
async def upload_resource(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    上传文件资源 + markitdown 自动解析为 Markdown
    支持：PDF / Word / Excel / PPT / HTML / 图片 / 纯文本等
    """
    from backend.services import file_service

    content = await file.read()

    result = await file_service.save_and_parse_upload(
        file_content=content,
        original_name=file.filename or "unnamed",
        content_type=file.content_type or "",
    )

    if "error" in result:
        raise HTTPException(400, result["error"])

    # 写入 Resource 表
    ext = result.get("original_name", "").rsplit(".", 1)[-1].lower() if "." in result.get("original_name", "") else ""
    type_map = {"pdf": "document", "docx": "document", "doc": "document",
                "xlsx": "dataset", "xls": "dataset", "csv": "dataset",
                "pptx": "document", "ppt": "document",
                "py": "service", "java": "service", "js": "service"}
    resource_type = type_map.get(ext, "document")

    icon_map = {"pdf": "📕", "docx": "📘", "doc": "📘", "xlsx": "📗", "xls": "📗",
                "pptx": "📙", "ppt": "📙", "py": "🐍", "java": "☕", "js": "📜"}
    icon = icon_map.get(ext, "📄")

    # 解析成功的 md 全文入库(共享 DB + 各机本地盘架构下,文件只在上传机上,入库后跨机可读)
    md_full = file_service.read_upload_md(result["file_id"]) if result.get("parse_success") else ""

    resource = Resource(
        id=result["file_id"],
        name=result["original_name"],
        type=resource_type,
        icon=icon,
        description=f"已解析为 Markdown（{result.get('md_full_length', 0)} 字）" if result.get("parse_success") else "解析失败",
        url=f"/api/admin/resources/{result['file_id']}/md",
        status="ready" if result.get("parse_success") else "parse_failed",
        owner="uploader",
        content=md_full or "",
    )
    db.add(resource)
    await db.flush()

    return {
        "id": resource.id,
        "message": f"文件 '{result['original_name']}' 上传成功，已解析为 {result.get('md_full_length', 0)} 字 Markdown",
        "parse_success": result.get("parse_success", False),
        "md_preview": result.get("md_content", "")[:200],
        "file_size": result.get("file_size", 0),
    }


@router.get("/resources/{rid}/md")
async def get_resource_markdown(rid: str, db: AsyncSession = Depends(get_db)):
    """获取资源解析后的 Markdown 内容(DB content 优先,本机文件兜底兼容旧数据)"""
    from backend.services import file_service
    r = (await db.execute(select(Resource).where(Resource.id == rid))).scalar_one_or_none()
    md = (r.content if r else "") or file_service.read_upload_md(rid)
    if not md:
        raise HTTPException(404, "Markdown 内容不存在（可能未解析或解析失败）")
    return {"file_id": rid, "content": md, "length": len(md)}


# ════════════════════════════════════════════════
#  3. 能力中心 (Skill) CRUD
# ════════════════════════════════════════════════

class SkillBody(BaseModel):
    name: str
    skill_key: str = ""
    type: str = "search"
    version: str = "1.0.0"
    state: str = "RELEASED"
    risk_level: str = "LOW"
    description: str = ""
    config: str = ""
    instructions: str = ""  # SKILL.md 式 markdown 指令体
    owner: str = ""


@router.get("/skills")
async def list_skills(db: AsyncSession = Depends(get_db)):
    skills = (await db.execute(select(Skill).order_by(Skill.created_at.desc()))).scalars().all()
    return [{"id": s.id, "name": s.name, "skill_key": s.skill_key, "type": s.type,
             "version": s.version, "state": s.state, "risk_level": s.risk_level,
             "description": s.description, "config": s.config, "instructions": s.instructions,
             "owner": s.owner, "status": s.status} for s in skills]


@router.post("/skills")
async def create_skill(body: SkillBody, db: AsyncSession = Depends(get_db)):
    s = Skill(id=_uuid(), name=body.name, skill_key=body.skill_key, type=body.type,
              version=body.version, state=body.state, risk_level=body.risk_level,
              description=body.description, config=body.config or None,
              instructions=body.instructions, owner=body.owner)
    db.add(s)
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor="admin", action="create", target_type="skill",
                    target_id=s.id, target_name=s.name, detail=f"创建能力 {s.name}"))
    await db.flush()
    return {"id": s.id, "message": "能力创建成功"}


@router.put("/skills/{sid}")
async def update_skill(sid: str, body: SkillBody, db: AsyncSession = Depends(get_db)):
    s = (await db.execute(select(Skill).where(Skill.id == sid))).scalar_one_or_none()
    if not s:
        raise HTTPException(404, "能力不存在")
    s.name, s.skill_key, s.type = body.name, body.skill_key, body.type
    s.version, s.state, s.risk_level = body.version, body.state, body.risk_level
    s.description, s.config, s.owner = body.description, body.config or None, body.owner
    s.instructions = body.instructions
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor="admin", action="update", target_type="skill",
                    target_id=s.id, target_name=s.name, detail=f"更新能力 {s.name}"))
    await db.flush()
    return {"message": "能力更新成功"}


@router.delete("/skills/{sid}")
async def delete_skill(sid: str, db: AsyncSession = Depends(get_db)):
    s = (await db.execute(select(Skill).where(Skill.id == sid))).scalar_one_or_none()
    name = s.name if s else ""
    await db.execute(delete(Skill).where(Skill.id == sid))
    db.add(AuditLog(id=_uuid(), actor="admin", action="delete", target_type="skill",
                    target_id=sid, target_name=name, detail=f"删除能力 {name}"))
    await db.flush()
    return {"message": "能力已删除"}


# ── Skill 增强端点：AI 生成 / 校验 / 导入（Harness Engineering 绑定） ──

class SkillAIGenBody(BaseModel):
    """AI 生成能力请求：需求描述或名称至少填一个"""
    name: str = ""
    type: str = "search"
    hint: str = ""


class SkillImportBody(BaseModel):
    """导入能力请求：前端 FileReader 读好的文件全文（SKILL.md / YAML / JSON）"""
    content: str


# AI 生成 Skill 的输出 schema 说明（注入 prompt，保证结构化输出）
_SKILL_GEN_SCHEMA = """{
  "skill_key": "小写字母/数字/中划线，如 call-chain",
  "name": "能力中文名",
  "type": "search|analysis|generation|api|workflow 之一",
  "version": "1.0.0",
  "risk_level": "LOW|MEDIUM|HIGH 之一",
  "description": "一句话能力简介",
  "config": "YAML 或 JSON 文本的 Manifest（触发条件、输入输出、依赖工具等）",
  "instructions": "Markdown 指令体（至少 50 字）：何时使用、执行步骤、输出格式、注意事项"
}"""


@router.post("/skills/ai-generate")
async def ai_generate_skill(body: SkillAIGenBody, db: AsyncSession = Depends(get_db)):
    """
    AI 生成能力草案（不落库）：
    LLM 生成 → 确定性校验 → 不合格则把错误反馈给 LLM 修复，最多 3 轮
    """
    if not body.name.strip() and not body.hint.strip():
        raise HTTPException(422, "name（能力名）与 hint（需求描述）至少填写一项")

    # 库内已有 skill_key，防止生成重名
    existing = (await db.execute(select(Skill.skill_key))).scalars().all()
    existing_keys = [k for k in existing if k]

    requirement = body.name.strip() or body.hint.strip()
    messages = [
        {"role": "system", "content": (
            "你是企业 AI 员工平台的 Skill 架构师。根据用户需求设计一个 Skill（声明式能力），"
            "严格输出一个 JSON 对象（不要输出其它任何文字），字段结构如下：\n"
            f"{_SKILL_GEN_SCHEMA}\n"
            f"约束：skill_key 不得与已有的重复：{existing_keys or '（空）'}；"
            f"本次需求的 type 建议为 {body.type}。"
        )},
        {"role": "user", "content": f"需求：{requirement}\n补充说明：{body.hint or '（无）'}"},
    ]

    preview, report, attempts = {}, {"ok": False, "errors": ["LLM 未返回有效 JSON"], "warnings": []}, 0
    for attempt in range(1, 4):
        attempts = attempt
        try:
            raw = await chat_completion(messages, temperature=0.3, max_tokens=3000)
        except Exception as e:
            raise HTTPException(502, f"LLM 调用失败: {e}")
        data = extract_llm_json(raw)
        if data is None:
            messages.append({"role": "assistant", "content": raw[:2000]})
            messages.append({"role": "user", "content": "输出无法解析为 JSON，请仅输出一个完整 JSON 对象，重试。"})
            continue
        # 规整字段类型（LLM 可能把 config 输出为对象）
        if isinstance(data.get("config"), (dict, list)):
            data["config"] = json.dumps(data["config"], ensure_ascii=False, indent=2)
        preview = data
        report = validate_skill_payload(data)
        if report["ok"]:
            break
        # 不合格：把校验错误反馈给 LLM 修复
        messages.append({"role": "assistant", "content": raw[:2000]})
        messages.append({"role": "user", "content": (
            "上次输出未通过校验：\n- " + "\n- ".join(report["errors"]) +
            "\n请仅修正这些问题后重新输出完整 JSON 对象。"
        )})

    db.add(AuditLog(id=_uuid(), actor="admin", action="ai_generate", target_type="skill",
                    target_name=preview.get("name", requirement),
                    detail=f"AI 生成能力草案（{attempts} 轮），校验 {'通过' if report['ok'] else '未通过: ' + '; '.join(report['errors'][:3])}"))
    await db.flush()
    return {"preview": preview, "validation": report, "attempts": attempts}


@router.post("/skills/validate")
async def validate_skill(body: SkillBody, db: AsyncSession = Depends(get_db)):
    """对任意 Skill payload 跑确定性校验（纯函数，不落库）"""
    report = validate_skill_payload(body.model_dump())
    # 补充：skill_key 查重提示（新增场景下有用，编辑同名不算错误，仅 warning）
    if body.skill_key:
        dup = (await db.execute(select(Skill).where(Skill.skill_key == body.skill_key))).scalars().first()
        if dup and dup.name != body.name:
            report["warnings"].append(f"skill_key 已被能力「{dup.name}」占用")
    return report


@router.post("/skills/import")
async def import_skill(body: SkillImportBody, db: AsyncSession = Depends(get_db)):
    """
    导入能力：解析 SKILL.md（frontmatter + 正文）或 YAML/JSON Manifest
    → 校验 → 落库为 DRAFT 状态
    """
    try:
        payload = parse_skill_content(body.content)
    except ValueError as e:
        raise HTTPException(422, f"解析失败: {e}")

    report = validate_skill_payload(payload)
    if not report["ok"]:
        raise HTTPException(422, detail={"message": "校验未通过", "validation": report})

    # skill_key 查重
    dup = (await db.execute(
        select(Skill).where(Skill.skill_key == payload["skill_key"].strip()))).scalars().first()
    if dup:
        raise HTTPException(409, f"skill_key「{payload['skill_key']}」已被能力「{dup.name}」占用")

    s = Skill(
        id=_uuid(),
        name=payload["name"].strip(),
        skill_key=payload["skill_key"].strip(),
        type=payload.get("type") or "search",
        version=payload.get("version") or "1.0.0",
        state="DRAFT",  # 导入一律从草稿开始，走治理流程发布
        risk_level=payload.get("risk_level") or "LOW",
        description=payload.get("description") or "",
        config=(payload.get("config") or "").strip() or None,
        instructions=payload.get("instructions") or "",
    )
    db.add(s)
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor="admin", action="create", target_type="skill",
                    target_id=s.id, target_name=s.name, detail=f"导入能力 {s.name}（DRAFT）"))
    await db.flush()
    return {"id": s.id, "message": "能力导入成功（草稿态）", "validation": report}


# ════════════════════════════════════════════════
#  4. 工具中心 (MCP) CRUD
# ════════════════════════════════════════════════

class ToolBody(BaseModel):
    name: str
    tool_key: str = ""
    type: str = "mcp"
    mode: str = "READ_ONLY"
    endpoint: str = ""
    risk_level: str = "LOW"
    timeout_ms: int = 5000
    description: str = ""
    config: str = ""
    read_only: str = "true"
    owner: str = ""


@router.get("/tools")
async def list_tools(db: AsyncSession = Depends(get_db)):
    tools = (await db.execute(select(Tool).order_by(Tool.created_at.desc()))).scalars().all()
    return [{"id": t.id, "name": t.name, "tool_key": t.tool_key, "type": t.type,
             "mode": t.mode, "endpoint": t.endpoint, "risk_level": t.risk_level,
             "timeout_ms": t.timeout_ms, "description": t.description, "config": t.config,
             "read_only": t.read_only, "owner": t.owner, "status": t.status} for t in tools]


@router.get("/tools/options")
async def list_tool_options(db: AsyncSession = Depends(get_db)):
    """
    工具勾选项聚合：只列已接入的 MCP Server / API 工具（Tool 表）。
    内置工具恒定全开、不进勾选项（见 runtime/tools.BUILTIN_TOOL_NAMES 与 runtime/context.py）。
    """
    options = []
    tools = (await db.execute(select(Tool).order_by(Tool.created_at.desc()))).scalars().all()
    for t in tools:
        options.append({"value": t.name, "label": f"{t.name}（{t.type or 'mcp'}）", "kind": t.type or "mcp"})
    return options


class ToolTestConnBody(BaseModel):
    endpoint: str
    config: str = ""
    timeout_ms: int = 10000


@router.post("/tools/test-connection")
async def test_tool_connection(body: ToolTestConnBody):
    """测试 MCP Server 连接：连接 + list_tools 预览发现的工具（不落库）"""
    if not body.endpoint.strip():
        raise HTTPException(400, "endpoint 不能为空")
    try:
        from backend.runtime.mcp_client import test_mcp_connection
        return await test_mcp_connection(body.endpoint.strip(), body.config, body.timeout_ms)
    except Exception as e:
        raise HTTPException(502, f"连接失败: {e}")


@router.get("/tools/{tid}/tools")
async def list_mcp_server_tools(tid: str, db: AsyncSession = Depends(get_db)):
    """实时拉取已登记 MCP Server 的工具清单（不落库，供工具中心浏览）"""
    t = (await db.execute(select(Tool).where(Tool.id == tid))).scalar_one_or_none()
    if not t:
        raise HTTPException(404, "工具不存在")
    if not t.endpoint:
        raise HTTPException(400, "该工具未配置 endpoint，无法拉取远程工具清单")
    try:
        from backend.runtime.mcp_client import test_mcp_connection
        return await test_mcp_connection(t.endpoint, t.config or "", t.timeout_ms or 10000)
    except Exception as e:
        raise HTTPException(502, f"连接失败: {e}")


@router.post("/tools")
async def create_tool(body: ToolBody, db: AsyncSession = Depends(get_db)):
    t = Tool(id=_uuid(), name=body.name, tool_key=body.tool_key, type=body.type,
             mode=body.mode, endpoint=body.endpoint or None, risk_level=body.risk_level,
             timeout_ms=body.timeout_ms, description=body.description,
             config=body.config or None, read_only=body.read_only, owner=body.owner)
    db.add(t)
    await db.flush()
    return {"id": t.id, "message": "工具创建成功"}


@router.put("/tools/{tid}")
async def update_tool(tid: str, body: ToolBody, db: AsyncSession = Depends(get_db)):
    t = (await db.execute(select(Tool).where(Tool.id == tid))).scalar_one_or_none()
    if not t:
        raise HTTPException(404, "工具不存在")
    t.name, t.tool_key, t.type = body.name, body.tool_key, body.type
    t.mode, t.endpoint = body.mode, body.endpoint or None
    t.risk_level, t.timeout_ms = body.risk_level, body.timeout_ms
    t.description, t.config = body.description, body.config or None
    t.read_only, t.owner = body.read_only, body.owner
    await db.flush()
    return {"message": "工具更新成功"}


@router.delete("/tools/{tid}")
async def delete_tool(tid: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(Tool).where(Tool.id == tid))
    await db.flush()
    return {"message": "工具已删除"}


# ════════════════════════════════════════════════
#  5. 岗位库 (Role Pack) CRUD
# ════════════════════════════════════════════════

class RolePackBody(BaseModel):
    name: str
    version: str = "1.0.0"
    owner: str = ""
    # None = 未提交（编辑表单不含 config 字段时不得清空已有配置）；{} = 显式清空
    config: dict | None = None


@router.get("/role-packs")
async def list_role_packs(db: AsyncSession = Depends(get_db)):
    packs = (await db.execute(select(RolePack).order_by(RolePack.created_at.desc()))).scalars().all()
    return [{"id": p.id, "name": p.name, "version": p.version, "owner": p.owner,
             "config": p.config} for p in packs]


@router.post("/role-packs")
async def create_role_pack(body: RolePackBody, db: AsyncSession = Depends(get_db)):
    p = RolePack(id=_uuid(), name=body.name, version=body.version, owner=body.owner, config=body.config or {})
    db.add(p)
    await db.flush()
    return {"id": p.id, "message": "岗位包创建成功"}


@router.put("/role-packs/{pid}")
async def update_role_pack(pid: str, body: RolePackBody, db: AsyncSession = Depends(get_db)):
    p = (await db.execute(select(RolePack).where(RolePack.id == pid))).scalar_one_or_none()
    if not p:
        raise HTTPException(404, "岗位包不存在")
    p.name, p.version, p.owner = body.name, body.version, body.owner
    # 仅当请求显式携带 config 时才覆盖：编辑表单可能不含 config 字段，
    # 若无条件 body.config or {} 会把岗位包配置（工具白名单/权限/承诺）清空
    if body.config is not None:
        p.config = body.config
    await db.flush()
    return {"message": "岗位包更新成功"}


@router.delete("/role-packs/{pid}")
async def delete_role_pack(pid: str, db: AsyncSession = Depends(get_db)):
    await db.execute(delete(RolePack).where(RolePack.id == pid))
    await db.flush()
    return {"message": "岗位包已删除"}


# ════════════════════════════════════════════════
#  6. 员工管理 CRUD
# ════════════════════════════════════════════════

class AgentBody(BaseModel):
    name: str
    title: str
    emoji: str = "🧑‍💻"
    department_id: str = ""
    domain_id: str = ""
    role_pack_id: str = ""  # 关联岗位包 ID（可选，由向导创建后传入）
    status: str = "online"
    version: int = 1
    owner: str = ""
    description: str = ""
    resources: list = []
    tags: list = []
    agents_md: str = ""  # AGENTS.md 行为准则（Harness Engineering）
    skills: list = []    # 直绑 skill_key 列表（优先于岗位包配置）
    tools: list = []     # 直绑工具白名单（内置工具名/MCP Server 名，优先于岗位包配置；空=回落岗位包）
    repo_ids: list = []  # 绑定代码仓库 ID 列表（AgentRepoBinding 同步）
    adoption_rate: int = 0
    session_count: int = 0


async def _sync_repo_bindings(db: AsyncSession, agent_id: str, repo_ids: list) -> list[str]:
    """
    同步员工仓库绑定（差集删除 + 交集新增，同事务由调用方提交）
    返回变更后的仓库名列表（用于审计日志）
    """
    existing = (await db.execute(
        select(AgentRepoBinding).where(AgentRepoBinding.agent_id == agent_id)
    )).scalars().all()
    existing_ids = {b.repo_id for b in existing}
    target_ids = set(repo_ids or [])

    # 删差集
    for b in existing:
        if b.repo_id not in target_ids:
            await db.delete(b)
    # 增交集
    for rid in target_ids - existing_ids:
        db.add(AgentRepoBinding(agent_id=agent_id, repo_id=rid))
    await db.flush()

    # 返回变更后的仓库名（审计展示用）
    if not target_ids:
        return []
    repos = (await db.execute(
        select(Repository).where(Repository.id.in_(target_ids))
    )).scalars().all()
    return [r.name for r in repos if r.name]


@router.get("/agents")
async def list_agents(
    lifecycle: Optional[str] = Query(None),
    department_id: Optional[str] = Query(None, alias="departmentId"),
    db: AsyncSession = Depends(get_db),
):
    query = select(Agent)
    if lifecycle:
        query = query.where(Agent.status == lifecycle)
    if department_id:
        query = query.where(Agent.department_id == department_id)

    agents = (await db.execute(query)).scalars().all()
    depts = {d.id: d.name for d in (await db.execute(select(Department))).scalars().all()}
    domains = {d.id: d.name for d in (await db.execute(select(Domain))).scalars().all()}

    # 批量查仓库绑定（一次 IN，避免 N+1）：agent_id -> [(repo_id, repo_name)]
    agent_ids = [a.id for a in agents]
    bindings = (await db.execute(
        select(AgentRepoBinding).where(AgentRepoBinding.agent_id.in_(agent_ids))
    )).scalars().all() if agent_ids else []
    repo_ids_all = list({b.repo_id for b in bindings})
    repo_name_map = {}
    if repo_ids_all:
        repo_name_map = {
            r.id: r.name
            for r in (await db.execute(select(Repository).where(Repository.id.in_(repo_ids_all)))).scalars().all()
        }
    agent_repo_ids: dict[str, list[str]] = {}
    for b in bindings:
        agent_repo_ids.setdefault(b.agent_id, []).append(b.repo_id)

    return [
        {
            "id": a.id, "name": a.name, "emoji": a.emoji, "role": a.title,
            "department_id": depts.get(a.department_id, ""), "domain_id": domains.get(a.domain_id, ""),
            "owner": a.owner, "version": f"v{a.version}",
            "lifecycle": a.status, "status": a.status,
            "description": a.description,
            "agents_md": a.agents_md, "skills": a.skills or [],
            "tools": a.tools or [],
            "resources": a.resources or [],
            "repo_ids": agent_repo_ids.get(a.id, []),
            "repo_names": [repo_name_map.get(rid, rid) for rid in agent_repo_ids.get(a.id, [])],
        }
        for a in agents
    ]


@router.post("/agents")
async def create_agent(body: AgentBody, db: AsyncSession = Depends(get_db)):
    a = Agent(
        id=_uuid(), name=body.name, title=body.title, emoji=body.emoji,
        department_id=await _resolve_org_id(db, Department, body.department_id),
        domain_id=await _resolve_org_id(db, Domain, body.domain_id),
        role_pack_id=body.role_pack_id or None,
        status=body.status, version=body.version, owner=body.owner,
        description=body.description, resources=body.resources, tags=body.tags,
        agents_md=body.agents_md, skills=body.skills, tools=body.tools,
        adoption_rate=body.adoption_rate, session_count=body.session_count,
    )
    db.add(a)
    await db.flush()
    # 同步仓库绑定（前端未传 repo_ids 时不清空，兼容旧客户端）
    bind_detail = ""
    if body.repo_ids:
        repo_names = await _sync_repo_bindings(db, a.id, body.repo_ids)
        bind_detail = f"，绑定仓库：{'、'.join(repo_names)}"
    # 审计
    db.add(AuditLog(id=_uuid(), actor="admin", action="create", target_type="agent",
                   target_id=a.id, target_name=a.name, detail=f"创建员工 {a.name}{bind_detail}"))
    await db.flush()
    return {"id": a.id, "message": "员工创建成功"}


async def _resolve_org_id(db: AsyncSession, model, val: str) -> str:
    """兼容 ID 或显示名提交：GET /agents 返回显示名，编辑表单原样回填，保存时按名称解析回真 ID"""
    if not val:
        return val
    hit = (await db.execute(
        select(model).where(or_(model.id == val, model.name == val))
    )).scalars().first()
    return hit.id if hit else val


@router.put("/agents/{aid}")
async def update_agent(aid: str, body: AgentBody, db: AsyncSession = Depends(get_db)):
    a = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
    if not a:
        raise HTTPException(404, "员工不存在")
    a.name, a.title, a.emoji = body.name, body.title, body.emoji
    a.department_id = await _resolve_org_id(db, Department, body.department_id)
    a.domain_id = await _resolve_org_id(db, Domain, body.domain_id)
    if body.role_pack_id:
        a.role_pack_id = body.role_pack_id
    a.status, a.owner = body.status, body.owner
    a.description, a.resources, a.tags = body.description, body.resources, body.tags
    # 前端始终全量提交，直接赋值（允许清空 AGENTS.md / 解绑全部能力）
    a.agents_md, a.skills = body.agents_md, body.skills
    a.tools = body.tools  # 直绑工具白名单：全量提交，空数组=回落岗位包配置
    # 同步仓库绑定（与 skills 同语义：全量提交，空数组 = 解绑全部）
    repo_names = await _sync_repo_bindings(db, a.id, body.repo_ids)
    bind_detail = f"，绑定仓库：{'、'.join(repo_names) if repo_names else '（无）'}"
    await db.flush()
    db.add(AuditLog(id=_uuid(), actor="admin", action="update", target_type="agent",
                   target_id=a.id, target_name=a.name, detail=f"更新员工 {a.name}{bind_detail}"))
    await db.flush()
    return {"message": "员工更新成功"}


class AgentAIGenBody(BaseModel):
    """AI 生成员工配置草案请求"""
    department_id: str = ""
    domain_id: str = ""
    title: str = ""
    hint: str = ""


@router.post("/agents/ai-generate")
async def ai_generate_agent(body: AgentAIGenBody, db: AsyncSession = Depends(get_db)):
    """
    AI 生成员工配置草案（不落库）：
    根据部门/领域/职位生成 name/emoji/description/agents_md/建议绑定能力
    建议能力必须 ⊆ 库内现有 skill_key（确定性过滤兜底）
    """
    dept_name, domain_name = "", ""
    if body.department_id:
        d = (await db.execute(select(Department).where(Department.id == body.department_id))).scalar_one_or_none()
        dept_name = d.name if d else ""
    if body.domain_id:
        dm = (await db.execute(select(Domain).where(Domain.id == body.domain_id))).scalar_one_or_none()
        domain_name = dm.name if dm else ""

    # 库内能力清单（喂给 LLM 限定选择范围）
    skills = (await db.execute(select(Skill))).scalars().all()
    skill_catalog = [
        {"skill_key": s.skill_key, "name": s.name, "type": s.type,
         "description": (s.description or "")[:80]}
        for s in skills if s.skill_key
    ]
    catalog_keys = {s["skill_key"] for s in skill_catalog}

    messages = [
        {"role": "system", "content": (
            "你是企业 AI 员工平台的组织设计师。根据岗位信息设计一个 AI 员工配置草案，"
            "严格输出一个 JSON 对象（不要输出其它任何文字），字段结构如下：\n"
            "{\n"
            '  "name": "员工中文姓名（拟人化，2-4 字）",\n'
            '  "emoji": "一个代表岗位的 emoji",\n'
            '  "description": "岗位职责描述（100-200 字，说明负责什么、服务谁、交付什么）",\n'
            '  "agents_md": "AGENTS.md 行为准则（Markdown，含：角色定位、工作原则、协作边界、输出规范，200-400 字）",\n'
            '  "suggested_skills": ["从给定能力清单中选择的 skill_key"]\n'
            "}\n"
            f"可选能力清单（suggested_skills 只能从中选择 skill_key，不得编造）：\n"
            f"{json.dumps(skill_catalog, ensure_ascii=False)}"
        )},
        {"role": "user", "content": (
            f"部门：{dept_name or '未指定'}\n领域：{domain_name or '未指定'}\n"
            f"职位：{body.title or '未指定'}\n补充说明：{body.hint or '（无）'}"
        )},
    ]

    draft = None
    for attempt in range(2):  # 解析失败重试 1 次
        try:
            raw = await chat_completion(messages, temperature=0.5, max_tokens=2500)
        except Exception as e:
            raise HTTPException(502, f"LLM 调用失败: {e}")
        draft = extract_llm_json(raw)
        if draft is not None:
            break
        messages.append({"role": "assistant", "content": raw[:2000]})
        messages.append({"role": "user", "content": "输出无法解析为 JSON，请仅输出一个完整 JSON 对象，重试。"})
    if draft is None:
        raise HTTPException(502, "LLM 两次输出均无法解析为 JSON，请重试")

    # 确定性过滤：建议能力必须与库内 skill_key 求交集
    suggested = draft.get("suggested_skills") or []
    if not isinstance(suggested, list):
        suggested = []
    valid = [k for k in suggested if k in catalog_keys]
    filtered = [k for k in suggested if k not in catalog_keys]
    draft["suggested_skills"] = valid

    db.add(AuditLog(id=_uuid(), actor="admin", action="ai_generate", target_type="agent",
                    target_name=draft.get("name", ""),
                    detail=f"AI 生成员工草案（{dept_name}/{domain_name}/{body.title}），建议能力 {len(valid)} 个"))
    await db.flush()
    return {"draft": draft, "filtered_skills": filtered}


@router.delete("/agents/{aid}")
async def delete_agent(aid: str, db: AsyncSession = Depends(get_db)):
    a = (await db.execute(select(Agent).where(Agent.id == aid))).scalar_one_or_none()
    name = a.name if a else ""
    # 顺带清理仓库绑定，避免残留脏数据
    await db.execute(delete(AgentRepoBinding).where(AgentRepoBinding.agent_id == aid))
    await db.execute(delete(Agent).where(Agent.id == aid))
    db.add(AuditLog(id=_uuid(), actor="admin", action="delete", target_type="agent",
                   target_id=aid, target_name=name, detail=f"删除员工 {name}"))
    await db.flush()
    return {"message": "员工已删除"}


# ════════════════════════════════════════════════
#  7. 权限与审计
# ════════════════════════════════════════════════

@router.get("/audit")
async def list_audit_logs(
    limit: int = Query(50, le=200),
    action: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """获取审计日志"""
    query = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
    if action:
        query = query.where(AuditLog.action == action)
    logs = (await db.execute(query)).scalars().all()
    return [
        {
            "id": l.id, "actor": l.actor, "action": l.action,
            "target_type": l.target_type, "target_name": l.target_name,
            "detail": l.detail,
            "created_at": l.created_at.strftime("%Y-%m-%d %H:%M:%S") if l.created_at else "",
        }
        for l in logs
    ]


@router.get("/permissions")
async def get_permissions(db: AsyncSession = Depends(get_db)):
    """获取权限矩阵概览"""
    agents = (await db.execute(select(Agent))).scalars().all()
    return {
        "policy": "最小授权原则 · 默认只读 · 证据可追溯",
        "rules": [
            {"rule": "所有工具调用经过 PEP（Policy Enforcement Point）", "status": "active"},
            {"rule": "Agent 只能访问其 Role Pack 中声明的资源", "status": "active"},
            {"rule": "跨部门协作需部门对接人授权", "status": "active"},
            {"rule": "知识候选审核通过前不参与共享检索", "status": "active"},
            {"rule": "证据打开时执行二次 ACL 校验", "status": "active"},
        ],
        "agent_count": len(agents),
        "readonly_mode": True,
    }
