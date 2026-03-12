from typing import Dict, List



def build_follow_up_questions(topic: str, count: int = 3) -> Dict[str, List[str]]:
    """Generate simple follow-up questions for interactive live sessions."""
    n = max(1, min(count, 5))
    cleaned_topic = topic.strip() or "the request"

    questions = [
        f"What is the main goal for {cleaned_topic}?",
        f"What constraints should I follow for {cleaned_topic}?",
        f"What output format do you want for {cleaned_topic}?",
        f"Should I optimize for speed or depth on {cleaned_topic}?",
        f"Do you want examples for {cleaned_topic}?",
    ]

    return {"questions": questions[:n]}
