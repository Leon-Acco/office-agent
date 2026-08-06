"""
Skill 确定性校验器 + SKILL.md 解析器
纯函数、无 DB 依赖，供 admin 端点（AI 生成/导入/校验）复用
"""
import json
import re

import yaml

# skill_key 命名规则：小写字母/数字开头，可含中划线，最长 64
SKILL_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
# 语义化版本号
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

SKILL_TYPES = {"search", "analysis", "generation", "api", "workflow"}
RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}
SKILL_STATES = {"DRAFT", "IN_REVIEW", "CANARY", "RELEASED", "RETIRED"}

# 指令体最小有效长度（去空白后）
MIN_INSTRUCTIONS_LEN = 50
# 指令体超过该长度时给出 warning（运行时会被截断）
MAX_INSTRUCTIONS_LEN = 8000


def validate_skill_payload(payload: dict) -> dict:
    """
    对 Skill payload 做确定性校验

    Args:
        payload: {name, skill_key, type, version, state?, risk_level, description?, config?, instructions}

    Returns:
        {"ok": bool, "errors": [str], "warnings": [str]}
    """
    errors: list[str] = []
    warnings: list[str] = []

    name = (payload.get("name") or "").strip()
    skill_key = (payload.get("skill_key") or "").strip()
    version = (payload.get("version") or "").strip()
    stype = (payload.get("type") or "").strip()
    risk_level = (payload.get("risk_level") or "").strip()
    state = (payload.get("state") or "").strip()
    description = (payload.get("description") or "").strip()
    config = (payload.get("config") or "").strip()
    instructions = payload.get("instructions") or ""

    if not name:
        errors.append("name 不能为空")
    if not skill_key:
        errors.append("skill_key 不能为空")
    elif not SKILL_KEY_RE.match(skill_key):
        errors.append("skill_key 格式非法：须匹配 ^[a-z0-9][a-z0-9-]{0,63}$（小写字母/数字开头，可含中划线）")
    if not version:
        errors.append("version 不能为空")
    elif not SEMVER_RE.match(version):
        errors.append("version 须为语义化版本号（如 1.0.0）")
    if stype not in SKILL_TYPES:
        errors.append(f"type 非法：须为 {'/'.join(sorted(SKILL_TYPES))} 之一")
    if risk_level not in RISK_LEVELS:
        errors.append("risk_level 非法：须为 LOW/MEDIUM/HIGH 之一")
    if state and state not in SKILL_STATES:
        errors.append(f"state 非法：须为 {'/'.join(sorted(SKILL_STATES))} 之一")

    if len(instructions.strip()) < MIN_INSTRUCTIONS_LEN:
        errors.append(f"instructions（指令体）不能为空且去空白后至少 {MIN_INSTRUCTIONS_LEN} 字符")
    elif len(instructions) > MAX_INSTRUCTIONS_LEN:
        warnings.append(f"instructions 超过 {MAX_INSTRUCTIONS_LEN} 字符，运行时注入提示词会被截断")

    if config:
        if not _parseable(config):
            errors.append("config 无法解析：须为合法的 JSON 或 YAML（Manifest）")
    else:
        warnings.append("config（Manifest）为空")

    if not description:
        warnings.append("description 为空，建议补充能力简介")

    return {"ok": not errors, "errors": errors, "warnings": warnings}


def _parseable(text: str) -> bool:
    """判断文本是否可被 JSON 或 YAML 解析"""
    try:
        json.loads(text)
        return True
    except Exception:
        pass
    try:
        yaml.safe_load(text)
        return True
    except Exception:
        return False


def parse_skill_content(content: str) -> dict:
    """
    解析导入内容为 Skill payload
    1. 以 --- 开头按 SKILL.md 解析：YAML frontmatter（name/skill_key/type/version/risk_level/description/config）
       + 正文作为 instructions
    2. 否则依次尝试 json.loads、yaml.safe_load 作为 Manifest（instructions 可内嵌其中）

    Raises:
        ValueError: 内容无法解析
    """
    text = (content or "").strip()
    if not text:
        raise ValueError("导入内容为空")

    # 1. SKILL.md 格式：--- frontmatter --- 正文
    if text.startswith("---"):
        parts = text.split("---", 2)
        # parts: ['', frontmatter, body]（split 后第一段为空串）
        if len(parts) >= 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except Exception as e:
                raise ValueError(f"frontmatter YAML 解析失败: {e}")
            if not isinstance(meta, dict):
                raise ValueError("frontmatter 须为键值对结构")
            payload = dict(meta)
            # config 若是 dict/list，转回文本存储（与表字段 Text 一致）
            if isinstance(payload.get("config"), (dict, list)):
                payload["config"] = json.dumps(payload["config"], ensure_ascii=False, indent=2)
            payload["instructions"] = parts[2].strip()
            return payload
        raise ValueError("SKILL.md 格式不完整：缺少结束的 ---")

    # 2. 纯 JSON Manifest
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return _normalize_manifest(data)
    except Exception:
        pass

    # 3. 纯 YAML Manifest
    try:
        data = yaml.safe_load(text)
        if isinstance(data, dict):
            return _normalize_manifest(data)
    except Exception:
        pass

    raise ValueError("内容无法解析：须为 SKILL.md（--- frontmatter ---）或 JSON/YAML Manifest")


def _normalize_manifest(data: dict) -> dict:
    """规范化 Manifest：config 为结构化数据时转文本"""
    payload = dict(data)
    if isinstance(payload.get("config"), (dict, list)):
        payload["config"] = json.dumps(payload["config"], ensure_ascii=False, indent=2)
    return payload


def extract_llm_json(raw: str) -> dict | None:
    """
    从 LLM 输出中提取 JSON 对象（剥离 ```json 围栏）
    与 frontdesk.py 的路由解析逻辑一致，供 AI 生成端点复用
    """
    if not raw:
        return None
    text = raw.strip()
    # 剥离 markdown 代码围栏
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except Exception:
        pass
    # 兜底：截取第一个 { 到最后一个 } 之间再试
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            return data if isinstance(data, dict) else None
        except Exception:
            return None
    return None
