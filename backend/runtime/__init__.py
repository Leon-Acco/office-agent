"""
Agent Runtime 模块
借鉴 nanobot 的双层分离设计，适配 Office_Agent 的业务场景：
- AgentRunner：ReAct 循环（LLM -> tool_call -> result -> LLM -> FINAL）
- Provider：封装 GLM-5.2，支持 function calling
- Context：历史注入 + 预算追踪
- ToolGateway：PEP 鉴权 + 工具执行
- 与岗位包（RolePack）绑定：工具白名单从 RolePack.spec 加载
"""
