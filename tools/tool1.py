from typing import Dict



def prepare_live_context(user_message: str) -> Dict[str, object]:
    """Prepare lightweight context metadata for a live turn."""
    normalized = user_message.strip()

    return {
        "normalized_message": normalized,
        "char_count": len(normalized),
        "has_question": "?" in normalized,
    }
