from __future__ import annotations

from typing import TYPE_CHECKING

from deeppresenter.rules.base import HTMLRule, SlideRule
from deeppresenter.tools.reflect import Issue, _collect_overlap_issues, inspect_slide_structured

if TYPE_CHECKING:
    from pptagent.presentation.presentation import SlidePage


class OverlapDetectionRule(HTMLRule, SlideRule):
    name = "overlap_elements"
    severity = "warning"

    def check(self, *, html_text: str = None, slide: "SlidePage" = None) -> list[Issue]:
        issues: list[Issue] = []
        if html_text is not None:
            issues.extend(_collect_overlap_issues(html_text))
        if slide is not None:
            slide_issues = inspect_slide_structured(slide)
            issues.extend(i for i in slide_issues if i.rule_name == "overlap_elements")
        return issues
