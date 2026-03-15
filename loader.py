from google.adk.tools import AgentTool

from subagents.generator import generator_agent
from tools.inspiration_image_search import search_inspiration_images
from tools.inspiration_search_plan import store_inspiration_search_queries


def load_tools():
    """Return all tool callables enabled for the coordinator agent."""
    return [
        store_inspiration_search_queries,
        search_inspiration_images,
        AgentTool(agent=generator_agent),
    ]
