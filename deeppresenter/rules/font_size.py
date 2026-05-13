from __future__ import annotations

from deeppresenter.rules.base import HTMLRule
from deeppresenter.tools.reflect import Issue, _collect_font_size_issues


class FontSizeRule(HTMLRule):
    name = "font_size"
    severity = "error"

    def check(self, *, html_text: str) -> list[Issue]:
        return _collect_font_size_issues(html_text)
