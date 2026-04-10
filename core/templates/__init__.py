"""Template registry: all 13 output templates."""

from __future__ import annotations

from .base import BaseTemplate, TemplateContext
from .brief import BriefTemplate
from .detailed import DetailedTemplate
from .mindmap import MindMapTemplate
from .flashcard import FlashCardTemplate
from .quiz import QuizTemplate
from .timeline import TimelineTemplate
from .exam import ExamTemplate
from .tutorial import TutorialTemplate
from .news import NewsTemplate
from .podcast import PodcastTemplate
from .xhs_note import XHSNoteTemplate
from .latex_pdf import LaTeXPDFTemplate
from .custom import CustomTemplate

TEMPLATES: dict[str, type[BaseTemplate]] = {
    "brief": BriefTemplate,
    "detailed": DetailedTemplate,
    "mindmap": MindMapTemplate,
    "flashcard": FlashCardTemplate,
    "quiz": QuizTemplate,
    "timeline": TimelineTemplate,
    "exam": ExamTemplate,
    "tutorial": TutorialTemplate,
    "news": NewsTemplate,
    "podcast": PodcastTemplate,
    "xhs_note": XHSNoteTemplate,
    "latex_pdf": LaTeXPDFTemplate,
    "custom": CustomTemplate,
}

TEMPLATE_LIST = [
    {"name": k, "display_name": v.display_name, "description": v.description}
    for k, v in TEMPLATES.items()
    if hasattr(v, "display_name")
]


def get_template(name: str, **kwargs) -> BaseTemplate:
    cls = TEMPLATES.get(name)
    if cls is None:
        raise ValueError(
            f"Unknown template '{name}'. Available: {', '.join(TEMPLATES.keys())}"
        )
    if name == "custom":
        return cls(**kwargs)
    return cls()


__all__ = [
    "TEMPLATES",
    "TEMPLATE_LIST",
    "get_template",
    "BaseTemplate",
    "TemplateContext",
]
