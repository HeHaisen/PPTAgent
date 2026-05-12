"""Unit tests for core logic functions that don't require LLM calls or external services."""

import os
import tempfile
from pathlib import Path

import pytest

from pptagent.mcp_server import PPTAgentServer
from pptagent.presentation.layout import Element, Layout


# ── Layout._truncate_text ──────────────────────────────────────────────


class TestTruncateText:
    def test_short_text_unchanged(self):
        assert Layout._truncate_text("hello", 10) == "hello"

    def test_exact_length_unchanged(self):
        assert Layout._truncate_text("hello", 5) == "hello"

    def test_truncate_at_sentence_boundary(self):
        text = "First sentence. Second sentence that is much longer."
        result = Layout._truncate_text(text, 20)
        assert result == "First sentence."

    def test_truncate_at_word_boundary(self):
        text = "word1 word2 word3 word4"
        result = Layout._truncate_text(text, 15)
        assert result.endswith("...")
        assert len(result) <= 15

    def test_truncate_chinese_sentence(self):
        # "。" at position 4, but 4 < 15*0.5=7.5 so sentence boundary isn't used.
        # Falls through to rstrip + "..."
        text = "第一句话。第二句话比较长需要截断处理。"
        result = Layout._truncate_text(text, 15)
        assert result.startswith("第一句话。第二句话比较长需")
        assert result.endswith("...")

    def test_truncate_chinese_at_boundary(self):
        # Position of "。" must be > max_len * 0.5 to cut there
        text = "前面的内容比较长。后面也有内容"
        result = Layout._truncate_text(text, 12)
        assert result == "前面的内容比较长。"

    def test_truncate_fallback(self):
        # No sentence or word boundaries: cut at max_len + "..."
        text = "a" * 100
        result = Layout._truncate_text(text, 50)
        assert result == "a" * 50 + "..."

    def test_truncate_no_boundary(self):
        text = "abcdefghijklmnop"
        result = Layout._truncate_text(text, 8)
        assert result == "abcdefgh..."


# ── Element ────────────────────────────────────────────────────────────


class TestElement:
    def test_suggested_characters(self):
        el = Element(name="title", data=["short", "a longer title"], type="text")
        assert el.suggested_characters == len("a longer title")

    def test_image_element_no_suggested_chars(self):
        el = Element(name="img", data=["img1.png"], type="image")
        assert el.suggested_characters is None

    def test_get_schema_text(self):
        el = Element(name="title", data=["Hello World"], type="text")
        schema = el.get_schema()
        assert "title" in schema
        assert "text" in schema
        assert "suggested_characters" in schema

    def test_get_schema_variable(self):
        el = Element(
            name="bullets",
            data=["item1"],
            type="text",
            variable_length=(1, 5),
            variable_data={"1": ["item1"], "5": ["a", "b", "c", "d", "e"]},
        )
        schema = el.get_schema()
        assert "vary between 1 and 5" in schema


# ── Layout containment ─────────────────────────────────────────────────


class TestLayoutContainment:
    def _make_layout(self):
        return Layout(
            title="Test",
            template_id=1,
            slides=[1, 2, 3],
            elements=[
                Element(name="title", data=["Hello"], type="text"),
                Element(name="body", data=["Content"], type="text"),
            ],
        )

    def test_contains_element_name(self):
        layout = self._make_layout()
        assert "title" in layout
        assert "body" in layout
        assert "missing" not in layout

    def test_contains_slide_number(self):
        layout = self._make_layout()
        assert 1 in layout
        assert 3 in layout
        assert 4 not in layout

    def test_getitem(self):
        layout = self._make_layout()
        el = layout["title"]
        assert el.name == "title"
        assert el.type == "text"

    def test_getitem_missing_raises(self):
        layout = self._make_layout()
        with pytest.raises(ValueError, match="not found"):
            layout["nonexistent"]

    def test_len(self):
        layout = self._make_layout()
        assert len(layout) == 2

    def test_iter(self):
        layout = self._make_layout()
        names = [el.name for el in layout]
        assert names == ["title", "body"]

    def test_content_schema(self):
        layout = self._make_layout()
        schema = layout.content_schema
        assert "title" in schema
        assert "body" in schema

    def test_remove_item(self):
        layout = self._make_layout()
        layout.remove_item("Hello")
        assert "title" not in layout
        assert len(layout) == 1

    def test_remove_item_not_found(self):
        layout = self._make_layout()
        with pytest.raises(ValueError, match="not found"):
            layout.remove_item("nonexistent")


# ── Layout validation ──────────────────────────────────────────────────


class TestLayoutValidation:
    def test_multiple_variable_elements_rejected(self):
        with pytest.raises(ValueError, match="Only one variable element"):
            Layout(
                title="Bad",
                template_id=1,
                slides=[1],
                elements=[
                    Element(
                        name="a",
                        data=["x"],
                        type="text",
                        variable_length=(1, 3),
                        variable_data={"1": ["x"]},
                    ),
                    Element(
                        name="b",
                        data=["y"],
                        type="text",
                        variable_length=(1, 3),
                        variable_data={"1": ["y"]},
                    ),
                ],
            )


# ── PPTAgentServer._ensure_session ─────────────────────────────────────


class TestEnsureSession:
    def test_no_reset_when_workspace_unchanged(self):
        """If WORKSPACE env hasn't changed, _ensure_session should be a no-op."""
        server = object.__new__(PPTAgentServer)
        server._workspace = "/tmp/test-workspace"
        server._initialized = True
        server.slides = ["slide1"]

        old_env = os.environ.get("WORKSPACE")
        try:
            os.environ["WORKSPACE"] = "/tmp/test-workspace"
            server._ensure_session()
            assert server._initialized is True
            assert server.slides == ["slide1"]
        finally:
            if old_env is None:
                os.environ.pop("WORKSPACE", None)
            else:
                os.environ["WORKSPACE"] = old_env

    def test_reset_when_workspace_changed(self):
        """If WORKSPACE env changed, _ensure_session should reset generation state."""
        server = object.__new__(PPTAgentServer)
        server._workspace = "/tmp/old-workspace"
        server._initialized = True
        server.slides = ["slide1"]
        server.direct_edit_mode = True
        server.direct_edit_layout_order = ["a"]
        server.direct_edit_next_layout_idx = 1
        server.generated_slides_by_template_id = {1: "slide1"}
        server.layout = "something"
        server.editor_output = "something"
        server._slide_count_since_preview = 5

        old_env = os.environ.get("WORKSPACE")
        old_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                os.environ["WORKSPACE"] = tmpdir
                server._ensure_session()
                # Generation state should be reset
                assert server.slides == []
                assert server.direct_edit_mode is False
                assert server.direct_edit_layout_order == []
                assert server.direct_edit_next_layout_idx == 0
                assert server.generated_slides_by_template_id == {}
                assert server.layout is None
                assert server.editor_output is None
                # Workspace should be updated
                assert server._workspace == tmpdir
        finally:
            os.chdir(old_cwd)
            if old_env is None:
                os.environ.pop("WORKSPACE", None)
            else:
                os.environ["WORKSPACE"] = old_env


# ── index_template_slide ───────────────────────────────────────────────


class TestIndexTemplateSlide:
    def test_basic_indexing(self):
        from unittest.mock import MagicMock

        layout = Layout(
            title="Test",
            template_id=1,
            slides=[1],
            elements=[
                Element(name="title", data=["Hello"], type="text"),
            ],
        )

        # Mock EditorOutput
        editor_output = MagicMock()
        title_el = MagicMock()
        title_el.data = ["New Title"]
        editor_output.__getitem__ = lambda self, key: title_el
        editor_output.__contains__ = lambda self, key: True

        template_id, old_data = layout.index_template_slide(editor_output)
        assert template_id == 1
        assert "title" in old_data
        assert old_data["title"] == ["Hello"]

    def test_variable_element_indexing(self):
        from unittest.mock import MagicMock

        layout = Layout(
            title="Var",
            template_id=1,
            slides=[1],
            elements=[
                Element(
                    name="bullets",
                    data=["a"],
                    type="text",
                    variable_length=(1, 3),
                    variable_data={
                        "1": ["a"],
                        "2": ["a", "b"],
                        "3": ["a", "b", "c"],
                    },
                ),
            ],
            vary_mapping={1: 1, 2: 2, 3: 3},
        )

        editor_output = MagicMock()
        bullets_el = MagicMock()
        bullets_el.data = ["x", "y"]
        editor_output.__getitem__ = lambda self, key: bullets_el
        editor_output.__contains__ = lambda self, key: True

        template_id, old_data = layout.index_template_slide(editor_output)
        assert template_id == 2
        assert old_data["bullets"] == ["a", "b"]

    def test_variable_length_out_of_range(self):
        from unittest.mock import MagicMock

        layout = Layout(
            title="Var",
            template_id=1,
            slides=[1],
            elements=[
                Element(
                    name="bullets",
                    data=["a"],
                    type="text",
                    variable_length=(1, 3),
                    variable_data={"1": ["a"]},
                    vary_mapping={"1": 1},
                ),
            ],
        )

        editor_output = MagicMock()
        bullets_el = MagicMock()
        bullets_el.data = ["a", "b", "c", "d", "e"]  # 5 items, max is 3
        editor_output.__getitem__ = lambda self, key: bullets_el
        editor_output.__contains__ = lambda self, key: True

        with pytest.raises(ValueError, match="not within the allowed range"):
            layout.index_template_slide(editor_output)
