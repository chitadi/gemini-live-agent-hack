from tools.tool1 import prepare_live_context
from tools.tool2 import build_follow_up_questions



def load_tools():
    """Return all tool callables enabled for the coordinator agent."""
    return [prepare_live_context, build_follow_up_questions]
