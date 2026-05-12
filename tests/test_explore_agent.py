"""测试Explore Agent"""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from code_agent.agents.loader import AgentLoader
from code_agent.agents import BUNDLED_AGENTS_DIR

# 创建agent loader
project_agents = Path.cwd() / ".code-agent" / "agents"
personal_agents = Path.home() / ".code-agent" / "agents"
loader = AgentLoader(personal_agents, project_agents, BUNDLED_AGENTS_DIR)

# 列出所有agents
print("=" * 60)
print("所有可用的Agents")
print("=" * 60)

agents = loader.list_agents()
for agent in agents:
    source = "内置" if "bundled" in agent.source else "自定义"
    print(f"\n[{source}] {agent.name}")
    print(f"  描述: {agent.description}")
    print(f"  工具: {', '.join(agent.tools) if agent.tools else '全部'}")
    print(f"  最大轮数: {agent.max_turns}")

# 测试读取explore agent
print("\n" + "=" * 60)
print("Explore Agent 详细信息")
print("=" * 60)

explore = loader.get_agent("explore")
if explore:
    print(f"名称: {explore.name}")
    print(f"描述: {explore.description}")
    print(f"工具列表: {explore.tools}")
    print(f"禁用工具: {explore.disallowed_tools}")
    print(f"最大轮数: {explore.max_turns}")
    print(f"\nSystem Prompt 预览:")
    print(explore.system_prompt[:500] + "...")
else:
    print("❌ 未找到 explore agent")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
