import base64
import os
import re
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from mcp.types import ImageContent

from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.log import info, set_logger
from deeppresenter.utils.webview import PlaywrightConverter, convert_html_to_pptx
from pptagent.model_utils import _get_lid_model


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
    audit_issues = _collect_font_size_issues(html_text)
    contrast_issues = _collect_contrast_issues(html_text)
    all_issues = audit_issues + contrast_issues
    if all_issues:
        return _format_slide_audit_error(all_issues)

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

    pages = [p for p in markdown.split("\n---\n") if p.strip()]
    result = defaultdict(list)
    result["num_pages"] = len(pages)
    label = LID_MODEL.predict(markdown[:1000].replace("\n", " "))
    result["language"] = label[0][0].replace("__label__", "")

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

    if len(result["warnings"]) == 0:
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
