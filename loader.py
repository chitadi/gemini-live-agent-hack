from tools.tool1 import persist_snapshot_observation
from tools.tool2 import get_live_session_context


def load_tools():
    """Return all tool callables enabled for the coordinator agent."""
    return [get_live_session_context, persist_snapshot_observation]
