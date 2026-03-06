"""Test Playwright PDF export."""

import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageFunctionToolCall as ToolCall,
)

from deeppresenter.agents.env import AgentEnv
from deeppresenter.utils.webview import PlaywrightConverter

HTML = """\
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <title>Test</title>
    <style>
      html, body {
        margin: 0;
        padding: 0;
        width: 1280px;
        height: 720px;
      }
      body {
        display: flex;
        align-items: center;
        justify-content: center;
        font-family: Arial, sans-serif;
      }
    </style>
  </head>
  <body>
    <h1>Hello 16:9</h1>
  </body>
</html>
"""

PLAYWRIGHT_SCRIPT = """\
import tempfile
from pathlib import Path

from deeppresenter.utils.webview import PlaywrightConverter

HTML = {html!r}


async def main() -> None:
    async with PlaywrightConverter() as converter:
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            f.write(HTML.encode())
            html_path = f.name

        pdf_path = Path(tempfile.mkstemp(suffix=".pdf")[1])
        await converter.convert_to_pdf(
            html_files=[html_path],
            output_pdf=pdf_path,
            aspect_ratio="16:9",
        )

        if not (pdf_path.exists() and pdf_path.stat().st_size > 0):
            raise RuntimeError("PDF not generated")
        print(f"SUCCESS: {pdf_path}")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
""".format(html=HTML)


@pytest.mark.asyncio
async def test_pdf_export():
    """Test HTML to PDF conversion."""
    async with PlaywrightConverter() as converter:
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as f:
            f.write(HTML.encode())
            html_path = f.name

        pdf_path = Path(tempfile.mkstemp(suffix=".pdf")[1])
        await converter.convert_to_pdf(
            html_files=[html_path],
            output_pdf=pdf_path,
            aspect_ratio="16:9",
        )

        assert pdf_path.exists() and pdf_path.stat().st_size > 0


@pytest.mark.asyncio
async def test_pdf_export_via_agent_env(
    agent_env: AgentEnv,
    workspace: Path,
    tool_call_helper: Callable[[str, dict, str | None], ToolCall],
) -> None:
    """Test HTML to PDF conversion via AgentEnv sandbox execution."""
    write_call = tool_call_helper(
        "write_file",
        {
            "path": str(workspace / "playwright_pdf.py"),
            "content": PLAYWRIGHT_SCRIPT,
        },
    )
    await agent_env.tool_execute(write_call)

    exec_call = tool_call_helper(
        "execute_command",
        {"command": f"python {workspace / 'playwright_pdf.py'}"},
    )
    result = await agent_env.tool_execute(exec_call)
    assert not result.is_error and "SUCCESS" in result.text
