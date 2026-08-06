"""
文件上传与解析服务
使用 markitdown（微软开源）将上传的文件解析为 Markdown

支持格式：PDF / Word / Excel / PPT / HTML / CSV / JSON / XML / 图片OCR / 纯文本
"""
import os
import uuid
from pathlib import Path
from typing import Optional

# 项目根目录（backend/services/file_service.py → 上两级）
_PROJECT_ROOT = Path(__file__).resolve().parents[2]

# 上传文件存储目录（可用环境变量 WORKSPACE_ROOT 覆盖，默认 <项目根>/workspaces）
_WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_ROOT", str(_PROJECT_ROOT / "workspaces")))
UPLOAD_ROOT = _WORKSPACE_ROOT / "uploads"
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

# 协作会议室完整方案（md）存储目录
COLLAB_DOC_ROOT = _WORKSPACE_ROOT / "collab_docs"
COLLAB_DOC_ROOT.mkdir(parents=True, exist_ok=True)

# 支持的文件扩展名
SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".ppt",
    ".html", ".htm", ".csv", ".json", ".xml", ".txt", ".md",
    ".py", ".java", ".js", ".ts", ".go", ".rs", ".c", ".cpp",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff",
    ".zip",  # markitdown 支持解压后处理
}

# 文件大小限制（50MB）
MAX_FILE_SIZE = 50 * 1024 * 1024


def get_upload_path(file_id: str, original_name: str) -> Path:
    """获取上传文件路径"""
    ext = Path(original_name).suffix
    return UPLOAD_ROOT / f"{file_id}{ext}"


def get_md_path(file_id: str) -> Path:
    """获取解析后的 Markdown 文件路径"""
    return UPLOAD_ROOT / f"{file_id}.md"


async def save_and_parse_upload(
    file_content: bytes,
    original_name: str,
    content_type: str = "",
) -> dict:
    """
    保存上传文件 + 用 markitdown 解析为 Markdown

    返回：
    {
        "file_id": "xxx",
        "original_name": "report.pdf",
        "file_path": "/path/to/xxx.pdf",
        "md_path": "/path/to/xxx.md",
        "md_content": "解析后的 Markdown 内容",
        "file_size": 12345,
        "parse_success": True,
    }
    """
    file_id = uuid.uuid4().hex[:12]
    ext = Path(original_name).suffix.lower()

    # 检查文件大小
    if len(file_content) > MAX_FILE_SIZE:
        return {"error": f"文件过大（{len(file_content)/1024/1024:.1f}MB），最大支持 50MB"}

    # 检查扩展名
    if ext not in SUPPORTED_EXTENSIONS:
        return {"error": f"不支持的文件类型: {ext}，支持: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"}

    # 保存原始文件（确保目录存在）
    file_path = get_upload_path(file_id, original_name)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(file_content)

    # 验证文件已写入
    if not file_path.exists():
        return {"error": f"文件保存失败：{file_path}"}

    # 用 markitdown 解析
    md_content = ""
    parse_success = False
    file_path_str = str(file_path.resolve())  # 使用绝对路径

    try:
        # markitdown 是同步的，用 run_in_executor 避免阻塞
        import asyncio
        loop = asyncio.get_event_loop()

        def _parse():
            from markitdown import MarkItDown
            converter = MarkItDown()
            result = converter.convert(file_path_str)
            return result.text_content

        md_content = await loop.run_in_executor(None, _parse)
        parse_success = True

        # 保存 Markdown
        md_path = get_md_path(file_id)
        md_path.write_text(md_content, encoding="utf-8")

    except Exception as e:
        md_content = f"[解析失败: {e}]"

    return {
        "file_id": file_id,
        "original_name": original_name,
        "file_path": str(file_path),
        "md_path": str(get_md_path(file_id)),
        "md_content": md_content[:500] if md_content else "",  # 预览前 500 字
        "md_full_length": len(md_content) if md_content else 0,
        "file_size": len(file_content),
        "parse_success": parse_success,
    }


def list_uploads() -> list[dict]:
    """列出所有上传的文件"""
    results = []
    if not UPLOAD_ROOT.exists():
        return results

    for f in UPLOAD_ROOT.iterdir():
        if f.is_file() and not f.name.endswith(".md"):
            file_id = f.stem
            md_file = UPLOAD_ROOT / f"{file_id}.md"
            results.append({
                "file_id": file_id,
                "filename": f.name,
                "size": f.stat().st_size,
                "has_md": md_file.exists(),
                "md_size": md_file.stat().st_size if md_file.exists() else 0,
                "uploaded_at": f.stat().st_mtime,
            })

    # 按时间倒序
    results.sort(key=lambda x: x["uploaded_at"], reverse=True)
    return results


def read_upload_md(file_id: str) -> Optional[str]:
    """读取上传文件的 Markdown 内容"""
    md_path = get_md_path(file_id)
    if md_path.exists():
        return md_path.read_text(encoding="utf-8", errors="replace")
    return None


def get_collab_doc_path(task_id: str) -> Path:
    """获取协作任务完整方案 md 路径（文件名由 task_id 派生，不信任外部传入）"""
    return COLLAB_DOC_ROOT / f"collab_{task_id}.md"


def write_collab_doc(task_id: str, content: str) -> str:
    """写入协作任务完整方案 md，返回文件名"""
    doc_path = get_collab_doc_path(task_id)
    doc_path.write_text(content, encoding="utf-8")
    return doc_path.name


def read_collab_doc(task_id: str) -> Optional[str]:
    """读取协作任务完整方案 md 内容，不存在返回 None"""
    doc_path = get_collab_doc_path(task_id)
    if doc_path.exists():
        return doc_path.read_text(encoding="utf-8", errors="replace")
    return None
