from __future__ import annotations

from typing import TYPE_CHECKING

from deeppresenter.rules.base import CrossSlideRule
from deeppresenter.tools.reflect import Issue, inspect_slides_structured

if TYPE_CHECKING:
    from pptagent.presentation.presentation import SlidePage


class ImageDistributionRule(CrossSlideRule):
    name = "image_distribution"
    severity = "warning"

    def check(self, *, slides: list["SlidePage"]) -> list[Issue]:
        return inspect_slides_structured(slides)
