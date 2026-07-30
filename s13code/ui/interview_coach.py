"""A safe, self-contained Interview Coach surface used in the S14 submission.

The coach deliberately demonstrates a complete interview loop without asking a
model to author browser code: question, response capture, rubric feedback and
a candidate rating are all catalog components and data bindings.
"""

from __future__ import annotations


def coach_feedback(answer: str) -> dict[str, object]:
    """Score one response with a transparent, offline STAR-style rubric."""
    lowered = answer.lower()
    checks = {
        "context": ("situation", "context", "when ", "previous"),
        "action": ("i proposed", "i led", "i changed", "i tested", "i built"),
        "evidence": ("evidence", "data", "metric", "analytics", "recording", "survey"),
        "result": ("result", "increased", "reduced", "improved", "%", "percent"),
    }
    strengths = [name for name, words in checks.items() if any(word in lowered for word in words)]
    score = min(5, len(strengths) + (1 if len(answer.split()) >= 55 else 0))
    missing = [name for name in checks if name not in strengths]
    praise = ", ".join(strengths) if strengths else "a clear starting point"
    next_step = ", ".join(missing[:2]) if missing else "a sharper one-sentence takeaway"
    return {
        "feedback_title": f"Feedback: {score}/5 rubric signals",
        "feedback": (
            f"You included {praise}. Strengthen the answer by adding {next_step}; "
            "end with the decision you changed and a measurable outcome."
        ),
        "coach_score": score,
    }


def build_interview_coach_surface() -> dict:
    """Return the deterministic first-turn Interview Coach interface."""
    data = {
        "title": "Interview Coach",
        "step": "Question 1 of 3 · product-thinking practice",
        "question": "Tell me about a time you used evidence to change a product decision.",
        "prompt": "Use STAR: situation, task, action, and measurable result.",
        "answer": "",
        "feedback_title": "Submit an answer to receive feedback",
        "feedback": "The rubric will check for context, action, evidence, and a measurable result.",
        "coach_score": 0,
        "candidate_rating": 0,
        "rating_hint": "After reviewing the rubric, rate how ready you feel to answer this question.",
    }
    components = [
        {"id": "root", "type": "Column", "children": ["title", "step", "question_card", "answer", "submit", "feedback_card", "self_rating"]},
        {"id": "title", "type": "Text", "variant": "heading", "text": {"$bind": "/title"}},
        {"id": "step", "type": "Text", "variant": "caption", "text": {"$bind": "/step"}},
        {"id": "question_card", "type": "Card", "title": "Your interview question", "children": ["question", "prompt"]},
        {"id": "question", "type": "Text", "variant": "body", "text": {"$bind": "/question"}},
        {"id": "prompt", "type": "Text", "variant": "subtitle", "text": {"$bind": "/prompt"}},
        {"id": "answer", "type": "TextField", "label": "Your answer", "placeholder": "Write or paste your response…", "value": {"$bind": "/answer"}},
        {"id": "submit", "type": "Button", "label": "Get coaching feedback", "onPress": {"action": "submit_interview_answer"}},
        {"id": "feedback_card", "type": "Card", "title": "Coach rubric", "children": ["feedback_title", "feedback", "coach_score"]},
        {"id": "feedback_title", "type": "Text", "variant": "subtitle", "text": {"$bind": "/feedback_title"}},
        {"id": "feedback", "type": "Text", "variant": "body", "text": {"$bind": "/feedback"}},
        {"id": "coach_score", "type": "Rating", "label": "Rubric target", "value": {"$bind": "/coach_score"}, "max": 5, "readOnly": True},
        {"id": "self_rating", "type": "Rating", "label": "Your readiness", "value": {"$bind": "/candidate_rating"}, "max": 5, "readOnly": False, "onRate": {"action": "rate_interview_answer"}},
        {"id": "rating_hint", "type": "Text", "variant": "caption", "text": {"$bind": "/rating_hint"}},
    ]
    # Keep the hint adjacent to the interactive control while retaining a flat,
    # validator-friendly component graph.
    components[0]["children"].append("rating_hint")
    return {"root": "root", "components": components, "dataModel": data}
