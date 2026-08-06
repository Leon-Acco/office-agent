"""
LangChain Agent 模块
用 LangChain/LangGraph 替换自研 Runtime

模块结构：
- llm.py: ChatAnthropic 实例（智谱 BigModel Anthropic 兼容端点，惰性导入，旁路默认关闭）
- tools.py: @tool 装饰器重写所有工具
- graph.py: LangGraph StateGraph（单 Agent ReAct 循环）
- multi_agent.py: 多 Agent 图（总台分诊 -> 领域员工）
"""
