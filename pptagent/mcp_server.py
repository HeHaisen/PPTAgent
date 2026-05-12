import json
import os
from copy import deepcopy
from math import ceil
from os.path import exists
from pathlib import Path
from random import shuffle

from fastmcp import FastMCP
import yaml
from mistune import html as markdown_to_html

from pptagent.llms import AsyncLLM
from pptagent.multimodal import ImageLabler
from pptagent.pptgen import PPTAgent, get_length_factor
from pptagent.presentation import Presentation
from pptagent.presentation.layout import Layout
from pptagent.response.pptgen import (
    EditorOutput,
    SlideElement,
)
from pptagent.utils import (
    Config,
    Language,
    get_html_table_image,
    get_logger,
    package_join,
)
from pptagent.uploaded_template import load_prepared_template_presentation

logger = get_logger(__name__)


def mcp_slide_validate(editor_output: EditorOutput, layout: Layout, prs_lang: Language):
    warnings = []
    errors = []
    length_factor = get_length_factor(prs_lang, Language.english())
    layout_elements = {el.name for el in layout.elements}
    editor_elements = {el.name for el in editor_output.elements}
    for el in layout_elements - editor_elements:
        errors.append(f"Element {el} not found in editor output")
    for el in editor_elements - layout_elements:
        errors.append(f"Element {el} not found in layout")
    for el in layout.elements:
        if layout[el.name].type == "image":
            for i in range(len(editor_output[el.name].data)):
                if not exists(editor_output[el.name].data[i]):
                    errors.append(f"Image {editor_output[el.name].data[i]} not found")
        else:
            charater_counts = max([len(i) for i in editor_output[el.name].data])
            expected_length = ceil(layout[el.name].suggested_characters * length_factor)
            if charater_counts - expected_length > 5:
                warnings.append(
                    f"Element {el.name} has {charater_counts} characters, but the expected length is {expected_length}"
                )
    return warnings, errors


class PPTAgentServer(PPTAgent):
    roles = ["coder"]
    CUSTOM_TEMPLATE_PREFIX = "user/"

    @classmethod
    def _iter_template_dirs(cls) -> list[tuple[str, Path]]:
        template_dirs: list[tuple[str, Path]] = []
        builtin_dir = Path(package_join("templates"))
        if builtin_dir.exists():
            for template_dir in builtin_dir.iterdir():
                if template_dir.is_dir():
                    template_dirs.append((template_dir.name, template_dir))

        workspace_uploaded = Path.cwd() / "uploaded_templates"
        if workspace_uploaded.exists():
            for template_dir in workspace_uploaded.iterdir():
                if template_dir.is_dir():
                    template_dirs.append(
                        (f"{cls.CUSTOM_TEMPLATE_PREFIX}{template_dir.name}", template_dir)
                    )
        return template_dirs

    def __init__(self):
        self.source_doc = None
        self.mcp = FastMCP("PPTAgent")
        self.slides = []
        self.layout: Layout | None = None
        self.editor_output: EditorOutput | None = None
        self.preview_pptx_path = Path(".preview") / "live_preview.pptx"
        self.direct_edit_mode = False
        self.direct_edit_layout_order: list[str] = []
        self.direct_edit_next_layout_idx = 0
        self.generated_slides_by_template_id: dict[int, object] = {}
        model_name, api_base, api_key = self._resolve_model_endpoint()
        model = AsyncLLM(model_name, api_base, api_key)
        workspace = os.getenv("WORKSPACE", None)
        if workspace is not None:
            os.chdir(workspace)

        if not model.to_sync().test_connection():
            logger.warning(
                "PPTAgent model preflight check failed; continuing and will rely on runtime tool-call validation."
            )
        super().__init__(language_model=model, vision_model=model)

        # load templates, a directory containing pptx, json, and description for each template
        self.template_description = {}
        self.templates = {}

        for template_name, template_dir in self._iter_template_dirs():
            try:
                desc_path = template_dir / "description.txt"
                if desc_path.exists():
                    self.template_description[template_name] = desc_path.read_text()
                else:
                    self.template_description[template_name] = (
                        f"Template loaded from {template_dir}"
                    )

                prs, metadata = load_prepared_template_presentation(template_dir)
                prs_config = Config(str(template_dir))
                image_labler = ImageLabler(prs, prs_config)
                image_stats_path = template_dir / "image_stats.json"
                image_labler.apply_stats(json.loads(image_stats_path.read_text()))

                slide_induction = json.loads(
                    (template_dir / "slide_induction.json").read_text()
                )

                self.templates[template_name] = {
                    "presentation": prs,
                    "slide_induction": slide_induction,
                    "config": prs_config,
                    "metadata": metadata,
                }

            except Exception as e:
                logger.warning(f"Failed to load template {template_name}: {e}")
                continue

        logger.info(
            f"{len(self.templates)} templates loaded successfully: "
            + ", ".join(self.templates.keys())
        )

    @staticmethod
    def _resolve_model_endpoint() -> tuple[str | None, str | None, str | None]:
        """Resolve model endpoint from env first, then DeepPresenter config file."""
        model_name = os.getenv("PPTAGENT_MODEL")
        api_base = os.getenv("PPTAGENT_API_BASE")
        api_key = os.getenv("PPTAGENT_API_KEY")
        if model_name and api_base and api_key:
            return model_name, api_base, api_key

        config_file = os.getenv("CONFIG_FILE")
        if not config_file:
            return model_name, api_base, api_key

        try:
            cfg = yaml.safe_load(Path(config_file).read_text(encoding="utf-8")) or {}
        except Exception as e:
            logger.warning(f"Failed to load config file {config_file}: {e}")
            return model_name, api_base, api_key

        for section in ("research_agent", "design_agent", "long_context_model"):
            endpoint = cfg.get(section) or {}
            if (
                endpoint.get("model")
                and endpoint.get("base_url")
                and endpoint.get("api_key")
            ):
                return (
                    endpoint["model"],
                    endpoint["base_url"],
                    endpoint["api_key"],
                )

        return model_name, api_base, api_key

    def _reset_generation_state(self) -> None:
        self.slides = []
        self.layout = None
        self.editor_output = None
        self.direct_edit_mode = False
        self.direct_edit_layout_order = []
        self.direct_edit_next_layout_idx = 0
        self.generated_slides_by_template_id = {}

    def _build_output_slides(self) -> list:
        if not self.direct_edit_mode:
            return list(self.slides)

        merged_slides = deepcopy(self.presentation.slides)
        for template_id, slide in self.generated_slides_by_template_id.items():
            merged_slides[template_id - 1] = slide
        return merged_slides

    def _save_live_preview_snapshot(self) -> str:
        """Save current generated slides as a live preview PPTX snapshot."""
        self.preview_pptx_path.parent.mkdir(parents=True, exist_ok=True)
        preview_presentation = deepcopy(self.empty_prs)
        preview_presentation.slides = self._build_output_slides()
        preview_presentation.save(str(self.preview_pptx_path))
        return str(self.preview_pptx_path.resolve())

    @classmethod
    def list_templates(cls) -> list[str]:
        return [name for name, _ in cls._iter_template_dirs()]

    def register_tools(self):
        @self.mcp.tool()
        def markdown_table_to_image(markdown_table: str, path: str, css: str) -> str:
            """
            Convert a markdown table to an image and save it to the specified path.

            Args:
                markdown_table (str): The markdown table content to convert
                path (str): The file path where the image will be saved
                css (str): Custom CSS styles for the table. Use class selectors
                                    (table, thead, th, td) to style the table elements. Avoid
                                    changing background colors outside the table area.

            Returns:
                str: Confirmation message with the path to the saved image
            """
            html = markdown_to_html(markdown_table)
            get_html_table_image(html, path, css)
            return f"Markdown table converted to image and saved to {path}"

        @self.mcp.tool()
        def list_templates() -> dict:
            """List all available templates."""
            return {
                "message": "Please choose one the following templates by calling `set_template`",
                "templates": [
                    {
                        "name": template_name,
                        "description": self.template_description[template_name],
                    }
                    for template_name in self.templates.keys()
                ],
            }

        @self.mcp.tool()
        def set_template(template_name: str = "default"):
            """Select a PowerPoint template by name.

            Args:
                template_name: The name of the template to select

            Returns:
                dict: Success message and list of available layouts
            """
            assert template_name in self.templates, (
                f"Template {template_name} not available, please choose from {', '.join(self.templates.keys())}"
            )

            template_data = self.templates[template_name]
            self._reset_generation_state()
            self.direct_edit_mode = bool(
                template_data.get("metadata", {}).get("direct_edit")
            )
            self.set_reference(
                slide_induction=deepcopy(template_data["slide_induction"]),
                presentation=template_data["presentation"],
                hide_small_pic_ratio=None if self.direct_edit_mode else 0.2,
            )
            if self.direct_edit_mode:
                ordered_layouts = sorted(
                    self.layouts.values(),
                    key=lambda item: item.template_id,
                )
                self.direct_edit_layout_order = [layout.title for layout in ordered_layouts]
            metadata = template_data.get("metadata", {})

            response = {
                "message": "Template set successfully, please select layout from given layouts later",
                "template_description": self.template_description[template_name],
                "available_layouts": (
                    self.direct_edit_layout_order or list(self.layouts.keys())
                ),
            }
            if self.direct_edit_mode:
                response.update(
                    {
                        "message": (
                            "Uploaded template set successfully. "
                            "This template will be edited in place. "
                            "Use the available layouts exactly once and strictly in the listed order."
                        ),
                        "direct_edit_mode": True,
                        "editable_slide_count": len(self.direct_edit_layout_order),
                        "total_slide_count": metadata.get("total_slide_count"),
                        "preserved_slide_indices": metadata.get(
                            "preserved_slide_indices", []
                        ),
                    }
                )

            return response

        @self.mcp.tool()
        async def create_slide(layout: str):
            """Create a slide with a given layout.

            Args:
                layout: Name of the layout to use. Must be one of the available layouts given by set_template.

            Returns:
                dict: Success message, instructions, and content schema for the selected layout.
            """
            assert self._initialized, (
                "PPTAgent not initialized, please call `set_template` first"
            )
            assert layout in self.layouts, (
                "Given layout was not in available layouts: " + ", ".join(self.layouts)
            )
            if self.direct_edit_mode:
                if self.direct_edit_next_layout_idx >= len(self.direct_edit_layout_order):
                    raise ValueError(
                        "All editable uploaded-template pages have already been used. "
                        "Please save the slides or stop generating new slides."
                    )
                expected_layout = self.direct_edit_layout_order[
                    self.direct_edit_next_layout_idx
                ]
                if layout != expected_layout:
                    raise ValueError(
                        "Direct edit mode requires following the uploaded template order. "
                        f"The next expected layout is `{expected_layout}`."
                    )
            if self.layout is not None:
                message = "Layout update from " + self.layout.title + " to " + layout
                message += "\nDid you forget to call `generate_slide` after setting slide content?"
            else:
                message = "Layout " + layout + " selected successfully"
            self.layout = self.layouts[layout]
            return {
                "message": message,
                "instructions": "Generate slide content strictly following the schema below",
                "schema": self.layout.content_schema,
            }

        @self.mcp.tool()
        async def write_slide(structured_slide_elements: list[dict]):
            """Write the slide elements for generating a PowerPoint slide.
            Note that this function will not generate a slide, you should call `generate_slide`.

            Args:
                structured_slide_elements: List of slide elements with their content
                should follow the content schema and adhere to
                [
                    {
                        "name": "element_name",
                        "data": ["content1", "content2", "..."]
                        // Array of strings for text elements
                        // OR array of image paths for image elements: ["/path/to/image1.jpg", "/path/to/image2.png"]
                    }
                ]
            Returns:
                dict: Success message, warnings, and errors
            """
            self.structured_slide_elements = structured_slide_elements
            assert self.layout is not None, (
                "Layout is not selected, please call `create_slide` before writing slide"
            )
            editor_output = EditorOutput(
                elements=[SlideElement(**e) for e in structured_slide_elements]
            )
            warnings, errors = mcp_slide_validate(
                editor_output, self.layout, self.reference_lang
            )
            if errors:
                raise ValueError("Errors:\n" + "\n".join(errors))

            self.editor_output = editor_output
            if warnings:
                return {
                    "message": "Slide elements set with warnings, please try your best to fix the. You should only proceed after fixing all warnings or 5 retries.",
                    "warnings": warnings,
                }
            return {
                "message": "Slide elements set successfully. Ready to generate slide."
            }

        @self.mcp.tool()
        async def generate_slide():
            """Generate a PowerPoint slide after layout and slide elements are set.

            Returns:
                dict: Success message with slide number and next steps
            """
            if self.editor_output is None:
                raise ValueError(
                    "Slide elements are not set, please call `write_slide` before generating slide"
                )

            command_list, template_id = self._generate_commands(
                self.editor_output, self.layout
            )
            slide, _ = await self._edit_slide(command_list, template_id)

            # Reset state after successful generation
            self.layout = None
            self.editor_output = None
            self.slides.append(slide)
            if self.direct_edit_mode:
                if template_id in self.generated_slides_by_template_id:
                    raise ValueError(
                        f"Template page {template_id} has already been edited once in direct edit mode."
                    )
                self.generated_slides_by_template_id[template_id] = slide
                self.direct_edit_next_layout_idx += 1

            slide_number = len(self.slides)
            if self.direct_edit_mode:
                available_layouts = self.direct_edit_layout_order[
                    self.direct_edit_next_layout_idx :
                ]
            else:
                available_layouts = list(self.layouts.keys())
                shuffle(available_layouts)
            preview_warning = None
            preview_pptx_path = None
            try:
                preview_pptx_path = self._save_live_preview_snapshot()
            except Exception as e:
                preview_warning = f"Failed to save live preview snapshot: {e}"
                logger.warning(preview_warning)

            result = {
                "message": f"Slide {slide_number:02d} generated successfully",
                "slide_number": slide_number,
                "next_steps": "You can now save the slides or continue generating more slides",
                "available_layouts": available_layouts,
            }
            if preview_pptx_path:
                result["preview_pptx_path"] = preview_pptx_path
            if preview_warning:
                result["preview_warning"] = preview_warning
            return result

        @self.mcp.tool()
        async def save_generated_slides(pptx_path: str):
            """Save the generated slides to a PowerPoint file.

            Args:
                pptx_path: The path to save the PowerPoint file
            """
            pptx = Path(pptx_path)
            assert len(self.slides), (
                "No slides generated, please call `generate_slide` first"
            )
            pptx.parent.mkdir(parents=True, exist_ok=True)
            output_presentation = deepcopy(self.empty_prs)
            output_presentation.slides = self._build_output_slides()
            output_presentation.save(pptx_path)
            saved_slide_count = len(output_presentation.slides)
            is_live_preview_snapshot = (
                pptx.resolve() == self.preview_pptx_path.resolve()
            )
            if is_live_preview_snapshot:
                return (
                    "Live preview snapshot updated successfully. "
                    f"Current preview contains {saved_slide_count} slides at {pptx.resolve()}. "
                    "Generation state is preserved; continue creating remaining slides."
                )
            self._reset_generation_state()
            self._initialized = False
            if self.preview_pptx_path.exists():
                self.preview_pptx_path.unlink()
            return f"total {saved_slide_count} slides saved to {pptx}"


def main():
    server = PPTAgentServer()
    server.register_tools()
    server.mcp.run(show_banner=False)


if __name__ == "__main__":
    main()
