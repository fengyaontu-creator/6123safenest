"""Risk agent — D."""
from google.adk import LlmAgent
# 导入外部工具函数
from tools.cea_api import verify_cea_agent_status 

# 实例化 Risk Agent
risk_agent = LlmAgent(
    name="risk_analyst",
    model="gemini-flash-latest", # 选用的其他模型
    instruction="提示词待定",
    tools=[verify_cea_agent_status] # ADK 会自动将这个 Python 函数转化为 Agent 可调用的工具
)
