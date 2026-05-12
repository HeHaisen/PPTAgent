import base64
import os
import re
import sys
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from mcp.types import ImageContent

from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.log import info, set_logger
from deeppresenter.utils.webview import PlaywrightConverter, convert_html_to_pptx
from pptagent.model_utils import _get_lid_model

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


def _to_px(value: float, unit: str) -> float:
    return value if unit.lower() == "px" else value * 96 / 72


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


def _collect_font_size_issues(html_text: str) -> list[str]:
    issues: list[str] = []
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
        issues.append(
            f"`{selector}` 的{role}字号只有 {size_px:.1f}px，低于最小可读阈值 {min_px:.0f}px"
        )

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


def _format_slide_audit_error(issues: list[str]) -> str:
    preview = issues[:8]
    details = "\n".join(f"- {issue}" for issue in preview)
    if len(issues) > len(preview):
        details += f"\n- 另外还有 {len(issues) - len(preview)} 处字号过小"
    return (
        "Slide readability check failed:\n"
        f"{details}\n"
        "请通过重排布局、增加换行、改为纵向堆叠或减少装饰元素来消除溢出，"
        "不要继续缩小字号。"
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
    audit_issues = _collect_font_size_issues(html_path.read_text(encoding="utf-8"))
    if audit_issues:
        return _format_slide_audit_error(audit_issues)

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
