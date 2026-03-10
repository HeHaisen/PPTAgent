import hashlib
import json
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from pptagent.multimodal import ImageLabler
from pptagent.presentation import Picture, Presentation
from pptagent.utils import Config
from pptagent_pptx.enum.shapes import MSO_SHAPE_TYPE

UPLOADED_TEMPLATE_FORMAT_VERSION = 2


class TemplatePreparationError(RuntimeError):
    """Raised when uploaded template cannot be prepared for runtime use."""


@dataclass(frozen=True)
class PreparedUploadedTemplate:
    template_name: str
    warnings: list[str]
    total_slide_count: int
    editable_layout_names: list[str]
    preserved_slide_indices: list[int]


def _safe_template_name(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return normalized or "uploaded-template"


def _safe_element_name(name: str, used_names: set[str], fallback_prefix: str) -> str:
    normalized = re.sub(r"\s+", "_", name.strip())
    candidate = re.sub(r"[^\w\u4e00-\u9fff]+", "_", normalized, flags=re.UNICODE).strip("_")
    if candidate.isascii():
        candidate = candidate.lower()
    candidate = candidate[:48]
    if not candidate:
        candidate = fallback_prefix
    unique_name = candidate
    suffix = 2
    while unique_name in used_names:
        unique_name = f"{candidate}_{suffix}"
        suffix += 1
    used_names.add(unique_name)
    return unique_name


def _pptx_has_nested_groups(source_pptx: Path) -> bool:
    ns = {"p": "http://schemas.openxmlformats.org/presentationml/2006/main"}
    try:
        with zipfile.ZipFile(source_pptx, "r") as zf:
            for member in zf.namelist():
                if not member.startswith("ppt/slides/slide") or not member.endswith(
                    ".xml"
                ):
                    continue
                root = ET.fromstring(zf.read(member))
                for group_shape in root.findall(".//p:grpSp", ns):
                    if group_shape.find("./p:grpSp", ns) is not None:
                        return True
    except Exception:
        return False
    return False


def _has_nested_group_errors(error_history: list[tuple[int, str]]) -> bool:
    return any("Nested group shapes are not allowed" in msg for _, msg in error_history)


def _parse_uploaded_presentation(
    source_pptx: Path,
    config: Config,
) -> tuple[Presentation, list[str]]:
    warnings: list[str] = []
    if _pptx_has_nested_groups(source_pptx):
        presentation = Presentation.from_file(
            str(source_pptx),
            config,
            shape_cast={MSO_SHAPE_TYPE.GROUP: None},
        )
        if presentation.slides:
            warnings.append("检测到模板包含嵌套分组，已启用兼容模式并忽略 Group 形状。")
        else:
            presentation = Presentation.from_file(str(source_pptx), config)
    else:
        presentation = Presentation.from_file(str(source_pptx), config)
        if not presentation.slides and _has_nested_group_errors(presentation.error_history):
            presentation = Presentation.from_file(
                str(source_pptx),
                config,
                shape_cast={MSO_SHAPE_TYPE.GROUP: None},
            )
            if presentation.slides:
                warnings.append("检测到模板包含嵌套分组，已启用兼容模式并忽略 Group 形状。")

    if not presentation.slides:
        if presentation.error_history:
            raise TemplatePreparationError(
                f"模板解析失败：{presentation.error_history[0][1]}"
            )
        raise TemplatePreparationError("模板解析失败：未解析到可用页面。")

    if presentation.error_history:
        warnings.append(
            f"模板有 {len(presentation.error_history)} 页解析失败，系统将忽略这些失败页面。"
        )

    return presentation, warnings


def load_prepared_template_presentation(template_root: Path) -> tuple[Presentation, dict]:
    config = Config(str(template_root))
    metadata_path = template_root / "metadata.json"
    metadata = (
        json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata_path.exists()
        else {}
    )
    if metadata.get("direct_edit"):
        presentation, _ = _parse_uploaded_presentation(
            template_root / "source.pptx",
            config,
        )
    else:
        presentation = Presentation.from_file(str(template_root / "source.pptx"), config)
    return presentation, metadata


def _build_local_image_stats(image_labler: ImageLabler) -> dict[str, dict]:
    stats = image_labler.image_stats
    for slide in image_labler.presentation.slides:
        for shape in slide.shape_filter(Picture):
            image_name = Path(shape.img_path).name
            stats.setdefault(image_name, {})
    for image_name, image_data in stats.items():
        image_data.setdefault("caption", Path(image_name).stem.replace("_", " "))
    return stats


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


def _is_decorative_text(paragraphs: list[str]) -> bool:
    merged = " ".join(item.strip() for item in paragraphs if item.strip())
    if not merged:
        return True
    if re.fullmatch(r"[\d\s./:-年月日]+", merged):
        return True
    if re.fullmatch(r"\d+\.", merged):
        return True
    if re.fullmatch(r"[A-Z][A-Z0-9\s.&/-]{1,20}", merged):
        return True
    if merged.upper() in {"WORK SUMMARY", "SUAT"}:
        return True
    return False


def _build_direct_edit_slide_induction(
    presentation: Presentation,
) -> tuple[dict[str, object], list[str], list[int]]:
    induction: dict[str, object] = {"functional_keys": []}
    editable_layout_names: list[str] = []
    preserved_slide_indices: list[int] = []
    merged_text: list[str] = []

    for slide_idx, slide in enumerate(presentation.slides, start=1):
        used_names: set[str] = set()
        elements: list[dict[str, object]] = []

        for shape_idx, shape in enumerate(slide.shapes, start=1):
            if not shape.text_frame.is_textframe:
                continue
            paragraphs = [
                para.text.strip()
                for para in shape.text_frame.paragraphs
                if para.idx != -1 and para.text and para.text.strip()
            ]
            if not paragraphs:
                continue
            if _is_decorative_text(paragraphs):
                continue

            merged_text.extend(paragraphs)
            base_name = (
                paragraphs[0]
                or getattr(shape, "semantic_name", None)
                or shape.style.get("name")
                or f"text_block_{shape_idx}"
            )
            element_name = _safe_element_name(
                str(base_name),
                used_names,
                fallback_prefix=f"text_block_{shape_idx}",
            )
            elements.append(
                {
                    "name": element_name,
                    "type": "text",
                    "data": paragraphs,
                }
            )

        if not elements:
            preserved_slide_indices.append(slide_idx)
            continue

        layout_name = f"user_slide_{slide_idx:02d}"
        induction[layout_name] = {
            "template_id": slide_idx,
            "slides": [slide_idx],
            "elements": elements,
        }
        editable_layout_names.append(layout_name)

    if not editable_layout_names:
        raise TemplatePreparationError(
            "上传的 PPT 未解析到可编辑的文本元素，暂时无法基于原模板直接编辑。"
        )

    induction["language"] = {"lid": "zh" if _contains_cjk("\n".join(merged_text)) else "en"}
    return induction, editable_layout_names, preserved_slide_indices


def prepare_uploaded_template(
    uploaded_path: str,
    workspace: Path,
) -> PreparedUploadedTemplate:
    template_file = Path(uploaded_path)
    if not template_file.exists():
        raise TemplatePreparationError("上传模板文件不存在或已失效，请重新上传。")
    if template_file.suffix.lower() != ".pptx":
        raise TemplatePreparationError("上传模板仅支持 .pptx 文件。")

    digest = hashlib.md5(template_file.read_bytes()).hexdigest()[:8]
    folder_name = f"{_safe_template_name(template_file.stem)}-{digest}"
    template_root = workspace / "uploaded_templates" / folder_name
    metadata_path = template_root / "metadata.json"
    template_name = f"user/{folder_name}"

    required_files = [
        template_root / "source.pptx",
        template_root / "slide_induction.json",
        template_root / "image_stats.json",
        template_root / "description.txt",
        metadata_path,
    ]
    if all(path.exists() for path in required_files):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("format_version") == UPLOADED_TEMPLATE_FORMAT_VERSION:
            return PreparedUploadedTemplate(
                template_name=template_name,
                warnings=metadata.get("warnings", []),
                total_slide_count=metadata["total_slide_count"],
                editable_layout_names=metadata["editable_layout_names"],
                preserved_slide_indices=metadata.get("preserved_slide_indices", []),
            )

    if template_root.exists():
        shutil.rmtree(template_root)
    template_root.mkdir(parents=True, exist_ok=True)

    source_pptx = template_root / "source.pptx"
    shutil.copy2(template_file, source_pptx)

    config = Config(str(template_root))
    presentation, warnings = _parse_uploaded_presentation(source_pptx, config)

    image_labler = ImageLabler(presentation, config)
    image_stats = _build_local_image_stats(image_labler)
    image_labler.apply_stats(image_stats)
    (template_root / "image_stats.json").write_text(
        json.dumps(image_stats, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    slide_induction, editable_layout_names, preserved_slide_indices = (
        _build_direct_edit_slide_induction(presentation)
    )
    (template_root / "slide_induction.json").write_text(
        json.dumps(slide_induction, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    description_lines = [
        f"User uploaded template: {template_file.name}",
        "Mode: direct edit on uploaded PPT",
        f"Total slides: {len(presentation.slides)}",
        f"Editable slides: {len(editable_layout_names)}",
    ]
    if preserved_slide_indices:
        description_lines.append(
            "Preserved slides: "
            + ", ".join(str(idx) for idx in preserved_slide_indices)
        )
        warnings.append(
            "以下页面未暴露为可编辑布局，将在最终输出中保持原样："
            + ", ".join(str(idx) for idx in preserved_slide_indices)
        )
    (template_root / "description.txt").write_text(
        "\n".join(description_lines),
        encoding="utf-8",
    )

    metadata = {
        "format_version": UPLOADED_TEMPLATE_FORMAT_VERSION,
        "direct_edit": True,
        "warnings": warnings,
        "total_slide_count": len(presentation.slides),
        "editable_layout_names": editable_layout_names,
        "preserved_slide_indices": preserved_slide_indices,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    return PreparedUploadedTemplate(
        template_name=template_name,
        warnings=warnings,
        total_slide_count=len(presentation.slides),
        editable_layout_names=editable_layout_names,
        preserved_slide_indices=preserved_slide_indices,
    )
