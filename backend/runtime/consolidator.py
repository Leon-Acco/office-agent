"""
Consolidator - 借鉴 nanobot agent/memory.py 的 Consolidator
当会话上下文超出 token 预算时，压缩旧消息

关键设计（借鉴 nanobot）：
1. 估算 messages 的 token 数
2. 超预算时，总结旧消息（调用 LLM 压缩）
3. 总结失败 -> 降级为原样归档（保证信息不丢）
4. 保留最近 N 条消息不压缩
"""
from typing import Optional


# 粗略 token 估算（1 个中文字约 2 token，1 个英文单词约 1.3 token）
def estimate_tokens(text: str) -> int:
    """估算文本的 token 数"""
    if not text:
        return 0
    chinese_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_count = len(text) - chinese_count
    return int(chinese_count * 2 + other_count * 0.3)


def estimate_messages_tokens(messages: list[dict]) -> int:
    """估算消息列表的 token 数"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    total += estimate_tokens(block.get("text", ""))
        # 每条消息额外 4 token 开销（role + 结构）
        total += 4
    return total


class Consolidator:
    """
    轻量上下文压缩器（借鉴 nanobot Consolidator）
    当 token 超预算时，总结旧消息

    策略：
    1. 保留 system prompt + 最近 N 条消息
    2. 对中间消息调用 LLM 压缩为摘要
    3. 压缩失败 -> 降级为原样截断（保证不崩）
    """

    # 保留最近 N 条消息不压缩
    _KEEP_RECENT = 6
    # 压缩摘要最大 token
    _SUMMARY_MAX_TOKENS = 500
    # 降级标记（借鉴 nanobot 的 [RAW] 原始归档）
    _DEGRADED_PREFIX = "[consolidated] "

    def __init__(self, max_tokens: int = 32000):
        self.max_tokens = max_tokens

    def needs_consolidation(self, messages: list[dict]) -> bool:
        """检查是否需要压缩"""
        return estimate_messages_tokens(messages) > self.max_tokens

    async def consolidate(
        self,
        messages: list[dict],
        provider=None,
    ) -> list[dict]:
        """
        压缩消息列表

        参数：
            messages: 原始消息列表
            provider: LLM Provider（用于压缩摘要）

        返回：
            压缩后的消息列表
        """
        if not self.needs_consolidation(messages):
            return messages

        if len(messages) <= self._KEEP_RECENT + 1:
            return messages  # 消息太少，不需要压缩

        # 分区：system（保留） + 中间（压缩） + 最近（保留）
        system_msgs = [m for m in messages if m.get("role") == "system"]
        non_system = [m for m in messages if m.get("role") != "system"]
        recent = non_system[-self._KEEP_RECENT:]
        to_consolidate = non_system[:-self._KEEP_RECENT]

        if not to_consolidate:
            return messages

        # 尝试 LLM 压缩
        summary = await self._summarize(to_consolidate, provider)

        if summary:
            # 成功压缩
            consolidated_msg = {
                "role": "system",
                "content": f"\n{self._DEGRADED_PREFIX}历史对话摘要（{len(to_consolidate)} 条消息压缩）：\n{summary}\n",
            }
            return system_msgs + [consolidated_msg] + recent
        else:
            # 降级：原样截断（借鉴 nanobot 的 [RAW] 原始归档）
            # 保留每条消息的前 200 字
            truncated = []
            for msg in to_consolidate:
                content = msg.get("content", "")
                if isinstance(content, str) and len(content) > 200:
                    content = content[:200] + "...[truncated]"
                truncated_msg = dict(msg)
                truncated_msg["content"] = content
                truncated.append(truncated_msg)

            print(f"[Consolidator] LLM 压缩失败，降级为原样截断 {len(truncated)} 条消息")
            return system_msgs + truncated + recent

    async def _summarize(self, messages: list[dict], provider=None) -> Optional[str]:
        """
        用 LLM 总结消息（借鉴 nanobot Consolidator 的总结逻辑）
        失败时返回 None（触发降级）
        """
        if not provider:
            return None

        try:
            # 构建压缩 prompt
            conversation_text = "\n".join([
                f"[{m.get('role', '?')}] {str(m.get('content', ''))[:500]}"
                for m in messages
            ])

            summary_prompt = f"""请将以下对话历史压缩为简洁摘要（不超过 500 字），保留关键信息和工具调用结果：

{conversation_text}

摘要："""

            response = await provider.chat(
                messages=[{"role": "user", "content": summary_prompt}],
                max_tokens=self._SUMMARY_MAX_TOKENS,
                temperature=0.1,
            )

            if response and response.content and response.finish_reason != "error":
                return response.content
            return None

        except Exception as e:
            print(f"[Consolidator] 压缩失败: {e}")
            return None
