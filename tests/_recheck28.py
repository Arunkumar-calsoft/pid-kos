"""Quick recheck of test 28."""
import logging; logging.disable(logging.CRITICAL)
from agent.cli import build_agent
agent, _, _ = build_agent()
r = agent.answer("Show details for PSV-A-123", pid_id="PID_0")
print(f"strategy={r['strategy']}  rows={len(r['records'])}")
