from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class Violation:
    """A single rule violation found during inspection."""

    rule_name: str
    severity: Literal["error", "warning"]
    message: str
    element: str | None = None
    details: dict | None = None

    def to_dict(self) -> dict:
        return {
            "rule_name": self.rule_name,
            "severity": self.severity,
            "message": self.message,
            "element": self.element,
            "details": self.details or {},
        }


@dataclass
class ViolationReport:
    """A collection of violations for a single slide/action."""

    action_id: str
    slide_index: int
    violations: list[Violation]
    rule_coverage_score: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    @property
    def has_errors(self) -> bool:
        return any(v.severity == "error" for v in self.violations)

    @property
    def has_warnings(self) -> bool:
        return any(v.severity == "warning" for v in self.violations)

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "slide_index": self.slide_index,
            "violations": [v.to_dict() for v in self.violations],
            "rule_coverage_score": self.rule_coverage_score,
            "timestamp": self.timestamp,
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
        }


@dataclass
class ActionTraceEntry:
    """A single action recorded in the generation trace."""

    action_id: str
    action_type: Literal[
        "create_slide",
        "write_slide",
        "generate_slide",
        "generate_slides_batch",
        "edit_slide",
        "repair_action",
    ]
    target_slide: int
    pre_state: dict = field(default_factory=dict)
    post_state: dict = field(default_factory=dict)
    parameters: dict = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    model: str | None = None
    token_count: int = 0
    verification_status: Literal["pending", "pass", "warning", "violation", "fixed"] = "pending"
    violations: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type,
            "target_slide": self.target_slide,
            "pre_state": self.pre_state,
            "post_state": self.post_state,
            "parameters": self.parameters,
            "timestamp": self.timestamp.isoformat(),
            "model": self.model,
            "token_count": self.token_count,
            "verification_status": self.verification_status,
            "violations": self.violations,
        }
