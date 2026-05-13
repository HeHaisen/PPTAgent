from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

from .structures import Violation, ViolationReport

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass
class RepairAction:
    """A proposed repair action for a rule violation."""

    original_action_id: str
    repair_type: Literal[
        "layout_adjust",
        "content_trim",
        "font_resize",
        "color_change",
        "element_remove",
        "element_add",
        "regenerate",
    ]
    target_elements: list[str] = field(default_factory=list)
    suggested_changes: dict = field(default_factory=dict)
    confidence: float = 1.0

    def to_dict(self) -> dict:
        return {
            "original_action_id": self.original_action_id,
            "repair_type": self.repair_type,
            "target_elements": self.target_elements,
            "suggested_changes": self.suggested_changes,
            "confidence": self.confidence,
        }


@dataclass
class RepairConfig:
    """Configuration for the repair loop."""

    max_iterations: int = 3
    confidence_threshold: float = 0.8


# Rule-based repair mapping
_RULE_REPAIR_MAP: dict[str, tuple[str, dict]] = {
    "overflow_text": ("content_trim", {"action": "reduce text length or add line breaks"}),
    "overflow_image": ("layout_adjust", {"action": "resize image to fit within slide boundaries"}),
    "font_size": ("font_resize", {"min_size_px": 24}),
    "contrast_ratio": ("color_change", {"min_ratio": 4.5}),
    "overlap_elements": ("layout_adjust", {"action": "reposition elements to remove overlap"}),
    "safe_margin": ("layout_adjust", {"action": "move elements at least 10pt from edges"}),
    "text_density": ("content_trim", {"action": "reduce text content or increase slide area"}),
    "image_too_small": ("layout_adjust", {"action": "increase image size to at least 5% of slide"}),
    "image_stretch": ("layout_adjust", {"action": "adjust image container aspect ratio"}),
}


def rule_based_repair(violation: Violation) -> RepairAction | None:
    """Generate a rule-based repair action for a violation.

    Returns None if no rule-based repair is available.
    """
    mapping = _RULE_REPAIR_MAP.get(violation.rule_name)
    if mapping is None:
        return None
    repair_type, suggested = mapping
    return RepairAction(
        original_action_id="",
        repair_type=repair_type,  # type: ignore
        target_elements=[violation.element] if violation.element else [],
        suggested_changes=suggested,
        confidence=1.0,
    )


def build_repair_feedback(violations: list[Violation]) -> str:
    """Build a feedback message for the coder agent based on violations.

    Includes rule-based repair suggestions where available.
    """
    messages = []
    for v in violations:
        msg = f"[{v.severity}] {v.message}"
        repair = rule_based_repair(v)
        if repair:
            msg += f" → Suggested: {repair.repair_type} - {repair.suggested_changes}"
        messages.append(msg)

    return (
        "Visual quality issues found:\n"
        + "\n".join(messages)
        + "\nPlease fix these issues by adjusting element positions, "
        "sizes, colors, or content."
    )
