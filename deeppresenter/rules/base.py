from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Literal

from deeppresenter.tools.reflect import Issue

if TYPE_CHECKING:
    from pptagent.presentation.presentation import SlidePage


class Rule(ABC):
    """Base class for visual quality inspection rules."""

    name: str = ""
    severity: Literal["error", "warning"] = "warning"

    @abstractmethod
    def check(self, **kwargs) -> list[Issue]:
        """Run the rule and return a list of Issue objects."""
        ...


class HTMLRule(Rule):
    """Rule that operates on HTML text."""

    @abstractmethod
    def check(self, *, html_text: str) -> list[Issue]:
        ...


class SlideRule(Rule):
    """Rule that operates on a SlidePage object."""

    @abstractmethod
    def check(self, *, slide: "SlidePage") -> list[Issue]:
        ...


class CrossSlideRule(Rule):
    """Rule that operates across multiple slides."""

    @abstractmethod
    def check(self, *, slides: list["SlidePage"]) -> list[Issue]:
        ...


class RuleEngine:
    """Engine that runs a collection of rules."""

    def __init__(self, rules: list[Rule] | None = None):
        if rules is not None:
            self.rules = rules
        else:
            self.rules = self._default_rules()

    @staticmethod
    def _default_rules() -> list[Rule]:
        from .contrast import ContrastRatioRule
        from .font_size import FontSizeRule
        from .image_dist import ImageDistributionRule
        from .layout_diversity import LayoutDiversityRule
        from .margin import SafeMarginRule
        from .overlap import OverlapDetectionRule
        from .overflow import ImageOverflowRule, TextOverflowRule

        return [
            TextOverflowRule(),
            ImageOverflowRule(),
            FontSizeRule(),
            ContrastRatioRule(),
            OverlapDetectionRule(),
            SafeMarginRule(),
            LayoutDiversityRule(),
            ImageDistributionRule(),
        ]

    def check_html(self, html_text: str) -> list[Issue]:
        """Run all HTML-based rules."""
        issues: list[Issue] = []
        for rule in self.rules:
            if isinstance(rule, HTMLRule):
                try:
                    issues.extend(rule.check(html_text=html_text))
                except Exception as e:
                    from deeppresenter.utils.log import warn
                    warn(f"Rule {rule.name} failed: {e}")
        return issues

    def check_slide(self, slide: "SlidePage") -> list[Issue]:
        """Run all single-slide rules."""
        issues: list[Issue] = []
        for rule in self.rules:
            if isinstance(rule, SlideRule):
                try:
                    issues.extend(rule.check(slide=slide))
                except Exception as e:
                    from deeppresenter.utils.log import warn
                    warn(f"Rule {rule.name} failed: {e}")
        return issues

    def check_slides(self, slides: list["SlidePage"]) -> list[Issue]:
        """Run all cross-slide rules."""
        issues: list[Issue] = []
        for rule in self.rules:
            if isinstance(rule, CrossSlideRule):
                try:
                    issues.extend(rule.check(slides=slides))
                except Exception as e:
                    from deeppresenter.utils.log import warn
                    warn(f"Rule {rule.name} failed: {e}")
        return issues

    def is_enabled(self, rule_name: str) -> bool:
        """Check if a rule is enabled (always True, config support in Commit 13)."""
        return any(r.name == rule_name for r in self.rules)
