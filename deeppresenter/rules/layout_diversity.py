from __future__ import annotations

from deeppresenter.rules.base import Rule
from deeppresenter.tools.reflect import Issue


class LayoutDiversityRule(Rule):
    """Check for consecutive layout repetition (requires external tracking)."""

    name = "layout_repetition"
    severity = "warning"

    def check(self, *, recent_layouts: list[str] = None) -> list[Issue]:
        if recent_layouts is None or len(recent_layouts) < 3:
            return []
        if len(set(recent_layouts[-3:])) == 1:
            return [Issue(
                rule_name=self.name,
                severity=self.severity,
                message=f"布局重复: 连续 3 页使用相同布局 '{recent_layouts[-1]}'",
                element="slides",
            )]
        return []
