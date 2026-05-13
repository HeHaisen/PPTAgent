from __future__ import annotations

from deeppresenter.rules.base import HTMLRule
from deeppresenter.tools.reflect import (
    Issue,
    _collect_overflow_image_issues,
    _collect_overflow_text_issues,
)


class TextOverflowRule(HTMLRule):
    name = "overflow_text"
    severity = "error"

    def check(self, *, html_text: str) -> list[Issue]:
        return _collect_overflow_text_issues(html_text)


class ImageOverflowRule(HTMLRule):
    name = "overflow_image"
    severity = "error"

    def check(self, *, html_text: str) -> list[Issue]:
        return _collect_overflow_image_issues(html_text)
