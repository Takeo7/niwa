"""Code review adapter — LLM reviews the diff before finalize (Phase 2)."""
from .adapter import ReviewAdapter, ReviewResult

__all__ = ["ReviewAdapter", "ReviewResult"]
