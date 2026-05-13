from __future__ import annotations

from deeppresenter.rules.base import HTMLRule
from deeppresenter.tools.reflect import Issue, _collect_contrast_issues


class ContrastRatioRule(HTMLRule):
    name = "contrast_ratio"
    severity = "error"

    def check(self, *, html_text: str) -> list[Issue]:
        return _collect_contrast_issues(html_text)
