from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from .storage import TraceStorage
from .structures import ActionTraceEntry, Violation

if TYPE_CHECKING:
    from pptagent.presentation.presentation import SlidePage


def generate_action_id() -> str:
    """Generate a unique action ID."""
    return f"action_{datetime.now().strftime('%H%M%S')}_{uuid.uuid4().hex[:6]}"


def capture_slide_state(slide: "SlidePage") -> dict:
    """Capture a summary of a slide's state for trace recording."""
    shapes_info = []
    for s in slide.shapes:
        info = {
            "name": s.style.get("name", f"shape_{s.shape_idx}"),
            "type": type(s).__name__,
            "left": s.left,
            "top": s.top,
            "width": s.width,
            "height": s.height,
        }
        if hasattr(s, "text_frame") and s.text_frame:
            info["text_length"] = len(s.text_frame.text)
        shapes_info.append(info)
    return {
        "slide_idx": slide.slide_idx,
        "shape_count": len(shapes_info),
        "shapes": shapes_info,
    }


def issues_to_violations(issues: list) -> list[dict]:
    """Convert Issue objects to Violation dicts for trace storage."""
    return [
        {
            "rule_name": i.rule_name,
            "severity": i.severity,
            "message": i.message,
            "element": i.element,
        }
        for i in issues
    ]


def record_slide_action(
    storage: TraceStorage,
    action_type: str,
    target_slide: int,
    slide: "SlidePage",
    issues: list | None = None,
    model: str | None = None,
    token_count: int = 0,
) -> str:
    """Record a slide action in the trace.

    Args:
        storage: The TraceStorage instance.
        action_type: Type of action (edit_slide, generate_slide, etc.).
        target_slide: Target slide index.
        slide: The SlidePage object after the action.
        issues: Optional list of Issue objects from inspection.
        model: Optional model name used.
        token_count: Optional token count.

    Returns:
        The action ID of the recorded entry.
    """
    violations = issues_to_violations(issues) if issues else []
    if issues:
        has_error = any(i.severity == "error" for i in issues)
        status = "violation" if has_error else "warning"
    else:
        status = "pass"

    entry = ActionTraceEntry(
        action_id=generate_action_id(),
        action_type=action_type,  # type: ignore
        target_slide=target_slide,
        post_state=capture_slide_state(slide),
        model=model,
        token_count=token_count,
        verification_status=status,
        violations=violations,
    )
    return storage.record(entry)
