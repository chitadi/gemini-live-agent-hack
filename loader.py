from google.adk.tools import AgentTool

from subagents.generator import generator_agent
from tools.inspiration_image_search import search_inspiration_images
from tools.inspiration_search_plan import store_inspiration_search_queries
from tools.generation_confirmation import store_generation_confirmation
from tools.room_memory import store_room_memory
from tools.vibe_memory import store_vibe_memory


def load_tools():
    """Return all tool callables enabled for the coordinator agent."""
    return [
        store_room_memory,
        store_vibe_memory,
        store_inspiration_search_queries,
        search_inspiration_images,
        store_generation_confirmation,
        AgentTool(agent=generator_agent),
    ]
