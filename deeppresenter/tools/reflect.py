import base64
import os
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from bs4 import BeautifulSoup, NavigableString
from fastmcp import FastMCP
from mcp.types import ImageContent

from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.log import info, set_logger
from deeppresenter.utils.webview import PlaywrightConverter, convert_html_to_pptx
from pptagent.model_utils import _get_lid_model

if TYPE_CHECKING:
    from pptagent.presentation.presentation import SlidePage


@dataclass
class Issue:
    """A single visual quality issue found during inspection."""

    rule_name: str
    severity: Literal["error", "warning"]
    message: str
    element: str = ""

mcp = FastMCP("DeepPresenter")
CONFIG = DeepPresenterConfig.load_from_file(os.getenv("CONFIG_FILE"))
LID_MODEL = _get_lid_model()
REFLECTIVE_DESIGN = CONFIG.design_agent.is_multimodal and CONFIG.heavy_reflect

_STYLE_BLOCK_RE = re.compile(r"<style\b[^>]*>(.*?)</style>", re.IGNORECASE | re.DOTALL)
_STYLE_RULE_RE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<declarations>[^{}]+)\}")
_INLINE_STYLE_RE = re.compile(
    r"<(?P<tag>[a-zA-Z0-9]+)(?P<attrs>[^>]*?)style\s*=\s*(?P<quote>['\"])(?P<style>.*?)(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)
_CLASS_ATTR_RE = re.compile(
    r"class\s*=\s*(?P<quote>['\"])(?P<classes>.*?)(?P=quote)",
    re.IGNORECASE | re.DOTALL,
)
_FONT_SIZE_RE = re.compile(
    r"font-size\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt)\b",
    re.IGNORECASE,
)
_COLOR_RE = re.compile(
    r"color\s*:\s*(#[0-9a-fA-F]{3,8}|rgb\([^)]+\)|rgba\([^)]+\))",
    re.IGNORECASE,
)
_BG_COLOR_RE = re.compile(
    r"background(?:-color)?\s*:\s*(#[0-9a-fA-F]{3,8}|rgb\([^)]+\)|rgba\([^)]+\))",
    re.IGNORECASE,
)
_PAGE_HEADING_RE = re.compile(
    r"^\s{0,3}#{2,6}\s*"
    r"(?:(?:第\s*)?(?:\d+|[一二三四五六七八九十百两]+)\s*[页頁]|slide\s*\d+)"
    r"(?:\s*[:：.．、-].*)?$",
    re.IGNORECASE | re.MULTILINE,
)


def _to_px(value: float, unit: str) -> float:
    return value if unit.lower() == "px" else value * 96 / 72


def _parse_color(color_str: str) -> tuple[int, int, int] | None:
    """Parse a CSS color string to (r, g, b) tuple. Returns None if unparseable."""
    color_str = color_str.strip().lower()
    if color_str.startswith("#"):
        hex_str = color_str[1:]
        if len(hex_str) == 3:
            return (int(hex_str[0] * 2, 16), int(hex_str[1] * 2, 16), int(hex_str[2] * 2, 16))
        if len(hex_str) >= 6:
            return (int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16))
    m = re.match(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", color_str)
    if m:
        return (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _relative_luminance(r: int, g: int, b: int) -> float:
    """Calculate relative luminance per WCAG 2.0."""
    def linearize(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * linearize(r) + 0.7152 * linearize(g) + 0.0722 * linearize(b)


def _contrast_ratio(color1: tuple[int, int, int], color2: tuple[int, int, int]) -> float:
    """Calculate WCAG contrast ratio between two colors."""
    l1 = _relative_luminance(*color1)
    l2 = _relative_luminance(*color2)
    lighter = max(l1, l2)
    darker = min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def _min_font_rule(selector: str) -> tuple[float, str] | None:
    normalized = " ".join(selector.lower().split())
    if normalized in {"", "*", "body", "html"}:
        return None

    if any(
        token in normalized
        for token in (
            "main-title",
            "hero",
            "cover",
            "closing",
            "title-cn",
            "title-en",
            "thank",
            "thanks",
        )
    ):
        return 28.0, "大标题"

    if any(
        token in normalized
        for token in (
            "subtitle",
            "contact",
            "meta",
            "caption",
            "note",
            "footer",
            "tagline",
            "icon-text",
            "author",
            "date",
            "year",
            "tag",
            "badge",
            "label",
        )
    ):
        return 14.0, "辅助文字"

    if any(
        token in normalized
        for token in ("title", "heading", "chapter", "section", "headline")
    ):
        return 24.0, "标题"

    return 18.0, "正文"


_TEXT_TAGS = {
    "a",
    "b",
    "code",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "i",
    "li",
    "mark",
    "p",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
}
_SKIP_TEXT_CHECK_TAGS = {"html", "head", "body", "script", "style", "title", "svg"}


def _collect_unwrapped_text_issues(html_text: str) -> list[Issue]:
    """Detect direct text nodes inside layout/container tags."""
    soup = BeautifulSoup(html_text, "html.parser")
    issues: list[Issue] = []

    for tag in soup.find_all(True):
        tag_name = tag.name.lower()
        if tag_name in _TEXT_TAGS or tag_name in _SKIP_TEXT_CHECK_TAGS:
            continue

        direct_text = " ".join(
            str(child).strip()
            for child in tag.children
            if isinstance(child, NavigableString) and str(child).strip()
        )
        if not direct_text:
            continue

        classes = tag.get("class") or []
        selector = f"<{tag_name}>"
        if classes:
            selector += "." + ".".join(classes)
        preview = direct_text[:50] + ("..." if len(direct_text) > 50 else "")
        issues.append(Issue(
            rule_name="unwrapped_text",
            severity="error",
            message=(
                f"{selector} contains unwrapped text `{preview}`. "
                "All visible text must be wrapped in <p>, <h1>-<h6>, <ul>/<ol>/<li>, or <span>."
            ),
            element=selector,
        ))

    return issues

def _collect_font_size_issues(html_text: str) -> list[Issue]:
    issues: list[Issue] = []
    seen: set[tuple[str, int, int]] = set()

    def check_rule(selector: str, declarations: str) -> None:
        size_match = _FONT_SIZE_RE.search(declarations)
        if size_match is None:
            return
        threshold = _min_font_rule(selector)
        if threshold is None:
            return

        size_px = _to_px(float(size_match.group(1)), size_match.group(2))
        min_px, role = threshold
        rounded_size = int(round(size_px * 10))
        rounded_min = int(round(min_px * 10))
        dedupe_key = (selector, rounded_size, rounded_min)
        if size_px + 0.01 >= min_px or dedupe_key in seen:
            return

        seen.add(dedupe_key)
        issues.append(Issue(
            rule_name="font_size",
            severity="error",
            message=f"`{selector}` 的{role}字号只有 {size_px:.1f}px，低于最小可读阈值 {min_px:.0f}px",
            element=selector,
        ))

    for style_block in _STYLE_BLOCK_RE.findall(html_text):
        for rule_match in _STYLE_RULE_RE.finditer(style_block):
            declarations = rule_match.group("declarations")
            selectors = [
                " ".join(selector.split())
                for selector in rule_match.group("selectors").split(",")
            ]
            for selector in selectors:
                check_rule(selector, declarations)

    for inline_match in _INLINE_STYLE_RE.finditer(html_text):
        tag = inline_match.group("tag").lower()
        attrs = inline_match.group("attrs")
        style = inline_match.group("style")
        class_match = _CLASS_ATTR_RE.search(attrs)
        classes = ""
        if class_match is not None:
            classes = "." + ".".join(class_match.group("classes").split())
        check_rule(f"inline <{tag}>{classes}", style)

    return issues


def _collect_contrast_issues(html_text: str) -> list[Issue]:
    """Check color contrast between text and background elements."""
    issues: list[Issue] = []
    seen: set[str] = set()

    def check_contrast(selector: str, declarations: str, font_size_px: float = 18.0) -> None:
        color_match = _COLOR_RE.search(declarations)
        bg_match = _BG_COLOR_RE.search(declarations)
        if not color_match or not bg_match:
            return
        fg = _parse_color(color_match.group(1))
        bg = _parse_color(bg_match.group(1))
        if fg is None or bg is None:
            return
        ratio = _contrast_ratio(fg, bg)
        min_ratio = 3.0 if font_size_px >= 24 else 4.5
        key = f"{selector}:{fg}:{bg}"
        if ratio >= min_ratio or key in seen:
            return
        seen.add(key)
        issues.append(Issue(
            rule_name="contrast_ratio",
            severity="error",
            message=f"`{selector}` 对比度 {ratio:.1f}:1 低于 WCAG AA 标准 ({min_ratio}:1)，"
                    f"前景色 {color_match.group(1)} 与背景色 {bg_match.group(1)}",
            element=selector,
        ))

    for style_block in _STYLE_BLOCK_RE.findall(html_text):
        for rule_match in _STYLE_RULE_RE.finditer(style_block):
            declarations = rule_match.group("declarations")
            selectors = [
                " ".join(s.split()) for s in rule_match.group("selectors").split(",")
            ]
            size_match = _FONT_SIZE_RE.search(declarations)
            font_px = _to_px(float(size_match.group(1)), size_match.group(2)) if size_match else 18.0
            for selector in selectors:
                if _min_font_rule(selector) is not None:
                    check_contrast(selector, declarations, font_px)

    for inline_match in _INLINE_STYLE_RE.finditer(html_text):
        tag = inline_match.group("tag").lower()
        attrs = inline_match.group("attrs")
        style = inline_match.group("style")
        class_match = _CLASS_ATTR_RE.search(attrs)
        classes = ""
        if class_match is not None:
            classes = "." + ".".join(class_match.group("classes").split())
        size_match = _FONT_SIZE_RE.search(style)
        font_px = _to_px(float(size_match.group(1)), size_match.group(2)) if size_match else 18.0
        check_contrast(f"inline <{tag}>{classes}", style, font_px)

    return issues


# Regex for extracting position/size from inline styles
_POS_SIZE_RE = re.compile(
    r"(?:left|top|width|height)\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt)\b",
    re.IGNORECASE,
)
_SLIDE_BODY_RE = re.compile(
    r'<body[^>]*style\s*=\s*["\'][^"\']*width\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt)[^"\']*height\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt)',
    re.IGNORECASE,
)
_MARGIN_THRESHOLD_PT = 10.0


def _parse_bounds(style_str: str) -> dict[str, float] | None:
    """Extract left/top/width/height in pt from a style string. Returns None if incomplete."""
    values: dict[str, float] = {}
    for m in _POS_SIZE_RE.finditer(style_str):
        prop = m.group(0).split(":")[0].strip().lower()
        val = float(m.group(1))
        unit = m.group(2)
        values[prop] = val if unit.lower() == "pt" else val * 72 / 96
    if {"left", "top", "width", "height"} <= values.keys():
        return values
    return None


def _rects_overlap(a: dict[str, float], b: dict[str, float]) -> bool:
    """Check if two rectangles (left, top, width, height) overlap."""
    return (
        a["left"] < b["left"] + b["width"]
        and a["left"] + a["width"] > b["left"]
        and a["top"] < b["top"] + b["height"]
        and a["top"] + a["height"] > b["top"]
    )


def _collect_overlap_issues(html_text: str) -> list[Issue]:
    """Detect overlapping elements via inline style position/size."""
    issues: list[Issue] = []
    elements: list[tuple[str, dict[str, float]]] = []

    for m in _INLINE_STYLE_RE.finditer(html_text):
        tag = m.group("tag").lower()
        if tag in ("html", "head", "body", "style", "script"):
            continue
        style = m.group("style")
        bounds = _parse_bounds(style)
        if bounds is None:
            continue
        attrs = m.group("attrs")
        class_match = _CLASS_ATTR_RE.search(attrs)
        label = f"<{tag}>"
        if class_match:
            label += f".{'.'.join(class_match.group('classes').split())}"
        elements.append((label, bounds))

    for i in range(len(elements)):
        for j in range(i + 1, len(elements)):
            label_a, bounds_a = elements[i]
            label_b, bounds_b = elements[j]
            if _rects_overlap(bounds_a, bounds_b):
                issues.append(Issue(
                    rule_name="overlap_elements",
                    severity="warning",
                    message=f"元素重叠: {label_a} 与 {label_b} 存在位置重叠",
                    element=f"{label_a}, {label_b}",
                ))
    return issues


def _collect_margin_issues(html_text: str) -> list[Issue]:
    """Detect elements too close to slide edges."""
    issues: list[Issue] = []

    # Extract slide dimensions from body style
    body_match = _SLIDE_BODY_RE.search(html_text)
    if not body_match:
        return issues
    slide_w = float(body_match.group(1))
    slide_h = float(body_match.group(3))
    unit = body_match.group(2)
    if unit.lower() != "pt":
        slide_w = slide_w * 72 / 96
        slide_h = slide_h * 72 / 96

    for m in _INLINE_STYLE_RE.finditer(html_text):
        tag = m.group("tag").lower()
        if tag in ("html", "head", "body", "style", "script"):
            continue
        style = m.group("style")
        bounds = _parse_bounds(style)
        if bounds is None:
            continue

        violations = []
        if bounds["left"] < _MARGIN_THRESHOLD_PT:
            violations.append(f"左边距 {bounds['left']:.0f}pt")
        if bounds["top"] < _MARGIN_THRESHOLD_PT:
            violations.append(f"上边距 {bounds['top']:.0f}pt")
        if bounds["left"] + bounds["width"] > slide_w - _MARGIN_THRESHOLD_PT:
            violations.append(f"右边距 {slide_w - bounds['left'] - bounds['width']:.0f}pt")
        if bounds["top"] + bounds["height"] > slide_h - _MARGIN_THRESHOLD_PT:
            violations.append(f"下边距 {slide_h - bounds['top'] - bounds['height']:.0f}pt")

        if violations:
            attrs = m.group("attrs")
            class_match = _CLASS_ATTR_RE.search(attrs)
            label = f"<{tag}>"
            if class_match:
                label += f".{'.'.join(class_match.group('classes').split())}"
            issues.append(Issue(
                rule_name="safe_margin",
                severity="warning",
                message=f"{label} 距离边缘过近: {', '.join(violations)}",
                element=label,
            ))
    return issues


def _collect_overflow_text_issues(html_text: str) -> list[Issue]:
    """Detect text elements that may overflow their containers."""
    issues: list[Issue] = []

    body_match = _SLIDE_BODY_RE.search(html_text)
    if not body_match:
        return issues
    slide_w = float(body_match.group(1))
    slide_h = float(body_match.group(3))
    unit = body_match.group(2)
    if unit.lower() != "pt":
        slide_w = slide_w * 72 / 96
        slide_h = slide_h * 72 / 96

    # Collect CSS rules with explicit width
    class_widths: dict[str, float] = {}
    class_font_sizes: dict[str, float] = {}
    for style_block in _STYLE_BLOCK_RE.findall(html_text):
        for rule_match in _STYLE_RULE_RE.finditer(style_block):
            declarations = rule_match.group("declarations")
            selectors = [s.strip() for s in rule_match.group("selectors").split(",")]
            width_match = re.search(r"width\s*:\s*([0-9]+(?:\.[0-9]+)?)\s*(px|pt)", declarations, re.IGNORECASE)
            font_match = _FONT_SIZE_RE.search(declarations)
            for selector in selectors:
                cls = selector.strip().lstrip(".")
                if cls and width_match:
                    w = float(width_match.group(1))
                    if width_match.group(2).lower() != "pt":
                        w = w * 72 / 96
                    class_widths[cls] = w
                if cls and font_match:
                    fs = _to_px(float(font_match.group(1)), font_match.group(2))
                    class_font_sizes[cls] = fs

    # Check text elements with known container widths
    text_content_re = re.compile(r">(.*?)<", re.DOTALL)
    element_re = re.compile(
        r"<(?P<tag>p|span|li|h[1-6]|div)(?P<attrs>[^>]*)>(?P<content>.*?)</(?P=tag)>",
        re.IGNORECASE | re.DOTALL,
    )
    for m in element_re.finditer(html_text):
        tag = m.group("tag").lower()
        attrs = m.group("attrs")
        content = re.sub(r"<[^>]+>", "", m.group("content")).strip()
        if not content:
            continue
        class_match = _CLASS_ATTR_RE.search(attrs)
        if not class_match:
            continue
        classes = class_match.group("classes").split()
        container_w = None
        font_px = 18.0
        for cls in classes:
            if cls in class_widths:
                container_w = class_widths[cls]
            if cls in class_font_sizes:
                font_px = class_font_sizes[cls]
        if container_w is None:
            continue
        # Estimate: CJK chars ~1em wide, Latin ~0.5em, use 0.8em as average
        cjk_count = sum(1 for c in content if "一" <= c <= "鿿")
        latin_count = len(content) - cjk_count
        estimated_width = (cjk_count * font_px + latin_count * font_px * 0.5)
        if estimated_width > container_w * 1.2:
            label = f"<{tag}>.{ '.'.join(classes)}"
            issues.append(Issue(
                rule_name="overflow_text",
                severity="error",
                message=f"{label} 文本可能溢出容器: 预估文本宽度 {estimated_width:.0f}px > 容器宽度 {container_w:.0f}px",
                element=label,
            ))
    return issues


def _collect_overflow_image_issues(html_text: str) -> list[Issue]:
    """Detect images that extend beyond the slide body boundaries."""
    issues: list[Issue] = []

    body_match = _SLIDE_BODY_RE.search(html_text)
    if not body_match:
        return issues
    slide_w = float(body_match.group(1))
    slide_h = float(body_match.group(3))
    unit = body_match.group(2)
    if unit.lower() != "pt":
        slide_w = slide_w * 72 / 96
        slide_h = slide_h * 72 / 96

    img_re = re.compile(r"<img(?P<attrs>[^>]*)/?>", re.IGNORECASE | re.DOTALL)
    for m in img_re.finditer(html_text):
        attrs = m.group("attrs")
        style_match = re.search(r"style\s*=\s*['\"]([^'\"]+)['\"]", attrs, re.IGNORECASE)
        if not style_match:
            continue
        style = style_match.group(1)
        bounds = _parse_bounds(style)
        if bounds is None:
            continue
        violations = []
        if bounds["left"] + bounds["width"] > slide_w + 1:
            violations.append(f"右侧溢出 {bounds['left'] + bounds['width'] - slide_w:.0f}pt")
        if bounds["top"] + bounds["height"] > slide_h + 1:
            violations.append(f"底部溢出 {bounds['top'] + bounds['height'] - slide_h:.0f}pt")
        if bounds["left"] < -1:
            violations.append(f"左侧溢出 {-bounds['left']:.0f}pt")
        if bounds["top"] < -1:
            violations.append(f"顶部溢出 {-bounds['top']:.0f}pt")
        if violations:
            class_match = _CLASS_ATTR_RE.search(attrs)
            label = "<img>"
            if class_match:
                label += f".{'.'.join(class_match.group('classes').split())}"
            issues.append(Issue(
                rule_name="overflow_image",
                severity="error",
                message=f"{label} 超出幻灯片边界: {', '.join(violations)}",
                element=label,
            ))
    return issues


def inspect_slide_structured(slide: "SlidePage") -> list[Issue]:
    """Inspect a SlidePage object directly using structured data.

    This bypasses HTML parsing and checks spatial relationships,
    image properties, and text density using the slide's shape data.

    Args:
        slide: A SlidePage object with populated shapes.

    Returns:
        A list of Issue objects found during inspection.
    """
    from pptagent.presentation.shapes import Picture

    issues: list[Issue] = []
    slide_w = float(slide.slide_width)
    slide_h = float(slide.slide_height)
    slide_area = slide_w * slide_h
    margin = 10.0  # pt

    visible_shapes = [
        s for s in slide.shapes
        if s.width > 0 and s.height > 0
    ]

    # 1. Element overlap detection
    for i in range(len(visible_shapes)):
        for j in range(i + 1, len(visible_shapes)):
            a, b = visible_shapes[i], visible_shapes[j]
            if (
                a.left < b.left + b.width
                and a.left + a.width > b.left
                and a.top < b.top + b.height
                and a.top + a.height > b.top
            ):
                a_name = a.style.get("name", f"shape_{a.shape_idx}")
                b_name = b.style.get("name", f"shape_{b.shape_idx}")
                issues.append(Issue(
                    rule_name="overlap_elements",
                    severity="warning",
                    message=f"元素重叠: {a_name} 与 {b_name} 存在位置重叠",
                    element=f"{a_name}, {b_name}",
                ))

    # 2. Safe margin detection
    for s in visible_shapes:
        name = s.style.get("name", f"shape_{s.shape_idx}")
        violations = []
        if s.left < margin:
            violations.append(f"左边距 {s.left:.0f}pt")
        if s.top < margin:
            violations.append(f"上边距 {s.top:.0f}pt")
        if s.left + s.width > slide_w - margin:
            violations.append(f"右边距 {slide_w - s.left - s.width:.0f}pt")
        if s.top + s.height > slide_h - margin:
            violations.append(f"下边距 {slide_h - s.top - s.height:.0f}pt")
        if violations:
            issues.append(Issue(
                rule_name="safe_margin",
                severity="warning",
                message=f"{name} 距离边缘过近: {', '.join(violations)}",
                element=name,
            ))

    # 3. Image-specific checks
    for s in visible_shapes:
        if not isinstance(s, Picture):
            continue
        name = s.style.get("name", f"picture_{s.shape_idx}")

        # 3a. Image too small (< 5% of slide area)
        ratio = s.area / slide_area
        if ratio < 0.05:
            issues.append(Issue(
                rule_name="image_too_small",
                severity="warning",
                message=f"{name} 面积仅占幻灯片的 {ratio*100:.1f}%，可能太小不易辨识",
                element=name,
            ))

        # 3b. Image stretch detection (aspect ratio mismatch)
        # Compare container aspect ratio with a reasonable range
        container_ratio = s.width / s.height if s.height > 0 else 0
        if container_ratio > 0 and (container_ratio > 3.0 or container_ratio < 0.33):
            issues.append(Issue(
                rule_name="image_stretch",
                severity="warning",
                message=f"{name} 宽高比 {container_ratio:.1f}:1 异常，图片可能被拉伸",
                element=name,
            ))

    # 4. Text density check
    text_area = 0.0
    for s in visible_shapes:
        if s.text_frame and s.text_frame.text.strip():
            text_area += s.area
    text_ratio = text_area / slide_area if slide_area > 0 else 0
    if text_ratio > 0.6:
        issues.append(Issue(
            rule_name="text_density",
            severity="warning",
            message=f"文本面积占幻灯片的 {text_ratio*100:.0f}%，密度过高",
            element="slide",
        ))

    return issues


def inspect_slides_structured(slides: "list[SlidePage]") -> list[Issue]:
    """Inspect multiple slides for cross-slide issues like image distribution.

    Args:
        slides: A list of SlidePage objects.

    Returns:
        A list of Issue objects found during cross-slide inspection.
    """
    from pptagent.presentation.shapes import Picture

    issues: list[Issue] = []
    if len(slides) < 2:
        return issues

    # Collect image positions per slide
    slide_image_positions: list[list[float]] = []  # list of [left_center, ...] per slide
    for slide in slides:
        positions = []
        for s in slide.shapes:
            if isinstance(s, Picture) and s.width > 0 and s.height > 0:
                center_x = s.left + s.width / 2
                positions.append(center_x)
        slide_image_positions.append(positions)

    # Check if images are concentrated on one side (80%+ on left or right half)
    all_positions = [p for positions in slide_image_positions for p in positions]
    if len(all_positions) >= 3:
        slide_w = float(slides[0].slide_width)
        mid = slide_w / 2
        left_count = sum(1 for p in all_positions if p < mid)
        right_count = len(all_positions) - left_count
        total = len(all_positions)
        if left_count / total > 0.8:
            issues.append(Issue(
                rule_name="image_distribution",
                severity="warning",
                message=f"图片分布不均: {left_count}/{total} ({left_count/total*100:.0f}%) 图片集中在幻灯片左侧",
                element="slides",
            ))
        elif right_count / total > 0.8:
            issues.append(Issue(
                rule_name="image_distribution",
                severity="warning",
                message=f"图片分布不均: {right_count}/{total} ({right_count/total*100:.0f}%) 图片集中在幻灯片右侧",
                element="slides",
            ))

    # Check if images are clustered on few slides while others have none
    slides_with_images = sum(1 for positions in slide_image_positions if positions)
    if slides_with_images > 0 and slides_with_images <= len(slides) // 3:
        issues.append(Issue(
            rule_name="image_distribution",
            severity="warning",
            message=f"图片分布不均: {len(slides)} 页中仅 {slides_with_images} 页包含图片",
            element="slides",
        ))

    return issues


def _format_slide_audit_warning(issues: list[Issue]) -> str:
    preview = issues[:8]
    details = "\n".join(f"- [{issue.rule_name}] {issue.message}" for issue in preview)
    if len(issues) > len(preview):
        details += f"\n- 另外还有 {len(issues) - len(preview)} 处可读性提醒"
    return (
        "Slide readability warnings:\n"
        f"{details}\n"
        "这些问题可能降低导出后的阅读体验；请优先通过调整间距、减少重叠或优化布局修复。"
    )


def _format_slide_audit_error(issues: list[Issue]) -> str:
    preview = issues[:8]
    details = "\n".join(f"- [{issue.rule_name}] {issue.message}" for issue in preview)
    if len(issues) > len(preview):
        details += f"\n- 另外还有 {len(issues) - len(preview)} 处可读性问题"
    return (
        "Slide readability check failed:\n"
        f"{details}\n"
        "请通过重排布局、增加换行、改为纵向堆叠或减少装饰元素来消除溢出，"
        "不要继续缩小字号。对比度不足时请调整文字或背景颜色。"
    )


@mcp.tool()
async def inspect_slide(
    html_file: str,
    aspect_ratio: Literal["16:9", "4:3", "A1", "A2", "A3", "A4"] = "16:9",
) -> ImageContent | str:
    """
    Read the HTML file as an image.

    Returns:
        ImageContent: The slide as an image content
        str: Error message if inspection fails
    """
    html_path = Path(html_file).absolute()
    assert html_path.is_file() and html_path.suffix == ".html", (
        f"HTML path {html_path} does not exist or is not an HTML file"
    )
    html_text = html_path.read_text(encoding="utf-8")
    all_issues: list[Issue] = []
    all_issues.extend(_collect_unwrapped_text_issues(html_text))
    all_issues.extend(_collect_font_size_issues(html_text))
    all_issues.extend(_collect_contrast_issues(html_text))
    all_issues.extend(_collect_overlap_issues(html_text))
    all_issues.extend(_collect_margin_issues(html_text))
    all_issues.extend(_collect_overflow_text_issues(html_text))
    all_issues.extend(_collect_overflow_image_issues(html_text))

    errors = [i for i in all_issues if i.severity == "error"]
    warnings = [i for i in all_issues if i.severity == "warning"]
    if errors:
        return _format_slide_audit_error(errors)

    try:
        await convert_html_to_pptx(html_path, aspect_ratio=aspect_ratio)
    except Exception as e:
        message = str(e)
        if "overflows body" in message:
            message += (
                "\n请优先通过减少单行文本长度、改为纵向堆叠/两行布局、"
                "缩减装饰元素或调整留白来解决溢出；"
                "禁止把正文缩到 18px 以下、辅助文字缩到 14px 以下。"
            )
        return message

    if warnings:
        return _format_slide_audit_warning(warnings)

    if REFLECTIVE_DESIGN:
        pdf_path = Path(tempfile.mkdtemp()) / "slide.pdf"
        async with PlaywrightConverter() as converter:
            image_dir = await converter.convert_to_pdf(
                [html_path], pdf_path, aspect_ratio
            )
        image_path = image_dir / "slide_01.jpg"
        image_data = image_path.read_bytes()
        base64_data = (
            f"data:image/jpeg;base64,{base64.b64encode(image_data).decode('utf-8')}"
        )
        return ImageContent(
            type="image",
            data=base64_data,
            mimeType="image/jpeg",
        )
    else:
        return "This slide is valid."


def _split_markdown_pages_by_separator(markdown: str) -> list[str]:
    return [p for p in re.split(r"\n\s*---\s*\n", markdown) if p.strip()]


def _count_markdown_pages(markdown: str) -> tuple[int, str, int, int, list[str]]:
    separator_count = len(_split_markdown_pages_by_separator(markdown))
    explicit_count = len(_PAGE_HEADING_RE.findall(markdown))
    warnings: list[str] = []

    if explicit_count > 0:
        if separator_count and separator_count != explicit_count:
            warnings.append(
                "Detected "
                f"{explicit_count} explicit page headings but {separator_count} horizontal-rule blocks; "
                "using explicit page headings for page count."
            )
        return explicit_count, "explicit_page_heading", separator_count, explicit_count, warnings

    return separator_count, "horizontal_rule_separator", separator_count, explicit_count, warnings


@mcp.tool()
def inspect_manuscript(md_file: str) -> dict:
    """
    Inspect the markdown manuscript for general statistics and image asset validation.
    Args:
        md_file (str): The path to the markdown file
    """
    md_path = Path(md_file)
    assert md_path.exists(), f"file does not exist: {md_file}"
    assert md_file.lower().endswith(".md"), f"file is not a markdown file: {md_file}"

    with open(md_file, encoding="utf-8") as f:
        markdown = f.read()

    page_count, strategy, separator_count, explicit_count, page_warnings = (
        _count_markdown_pages(markdown)
    )
    result = defaultdict(list)
    result["num_pages"] = page_count
    result["page_count_strategy"] = strategy
    result["separator_blocks"] = separator_count
    result["explicit_page_headings"] = explicit_count
    result["warnings"].extend(page_warnings)
    label = LID_MODEL.predict(markdown[:1000].replace("\n", " "))
    result["language"] = label[0][0].replace("__label__", "")

    image_warning_start = len(result["warnings"])
    seen_images = set()
    for match in re.finditer(r"!\[(.*?)\]\((.*?)\)", markdown):
        label, path = match.group(1), match.group(2)
        path = path.split()[0].strip("\"'")

        if path in seen_images:
            continue
        seen_images.add(path)

        if re.match(r"https?://", path):
            result["warnings"].append(
                f"External link detected: {match.group(0)}, consider downloading to local storage."
            )
            continue

        if not (md_path.parent / path).exists() and not Path(path).exists():
            result["warnings"].append(f"Image file does not exist: {path}")

        if not label.strip():
            result["warnings"].append(f"Image {path} is missing alt text.")

        count = markdown.count(path)
        if count > 1:
            result["warnings"].append(
                f"Image {path} used {count} times in the whole presentation manuscript."
            )

    if len(result["warnings"]) == image_warning_start:
        result["success"].append(
            "Image asset validation passed: all referenced images exist."
        )

    return result


if __name__ == "__main__":
    assert len(sys.argv) == 2, "Usage: python task.py <workspace>"
    work_dir = Path(sys.argv[1])
    assert work_dir.exists(), f"Workspace {work_dir} does not exist."
    os.chdir(work_dir)
    set_logger(f"task-{work_dir.stem}", work_dir / ".history" / "task.log")

    if REFLECTIVE_DESIGN:
        info("Reflective Design is enabled.")

    mcp.run(show_banner=False)
