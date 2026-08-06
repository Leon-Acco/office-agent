"""
LLM 实例（LangChain 旁路，默认不启用）
对接智谱 BigModel Anthropic 兼容端点（GLM-5.2，原生 1M 上下文）

注意：本模块仅供 LangChain/LangGraph 旁路（USE_LANGCHAIN=true / USE_MULTI_AGENT=true）使用，
生产默认链路是自研 AgentRunner（backend/runtime/provider.py，raw httpx 直调），不走这里。
"""
from backend.config import LLM_BASE_URL, LLM_API_KEY, LLM_MODEL, LLM_MAX_TOKENS, LLM_TEMPERATURE


def _new_chat_anthropic(temperature: float, max_tokens: int, streaming: bool):
    """
    惰性构造 ChatAnthropic（base_url 指向智谱 Anthropic 兼容端点）

    惰性导入原因：当前环境 langchain_anthropic 与 langchain_core 版本不匹配
    （ContextOverflowError 导入失败），模块级导入会导致本文件整体不可用；
    旁路默认关闭，只有显式启用时才需要该依赖就绪。
    """
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as e:
        raise RuntimeError(
            "LangChain 旁路需要可用的 langchain_anthropic（当前与 langchain_core 版本不匹配）。"
            "请修复依赖，或保持 USE_LANGCHAIN=false 走默认的自研 AgentRunner 链路。"
        ) from e
    return ChatAnthropic(
        base_url=LLM_BASE_URL,  # https://open.bigmodel.cn/api/anthropic
        api_key=LLM_API_KEY,
        model=LLM_MODEL,
        temperature=temperature,
        max_tokens=max_tokens,
        streaming=streaming,
    )


def get_llm(temperature: float | None = None, max_tokens: int | None = None):
    """创建流式 ChatAnthropic 实例（GLM-5.2）"""
    return _new_chat_anthropic(
        temperature=temperature or LLM_TEMPERATURE,
        max_tokens=max_tokens or LLM_MAX_TOKENS,
        streaming=True,
    )


def get_llm_no_stream(temperature: float = 0.1, max_tokens: int = 200):
    """非流式 LLM（用于分诊决策、总结等需要完整结果的场景）"""
    return _new_chat_anthropic(temperature=temperature, max_tokens=max_tokens, streaming=False)
