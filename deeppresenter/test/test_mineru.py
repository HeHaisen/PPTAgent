"""Test MinerU PDF parsing."""

from pathlib import Path

import httpx
import pytest


@pytest.mark.skip(reason="Requires any2markdown MCP server with MinerU API")
@pytest.mark.asyncio
async def test_mineru_pdf_parsing(agent_env, workspace: Path, tool_call_helper):
    """Test PDF to markdown conversion with MinerU."""
    pdf_path = workspace / "attention.pdf"
    async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
        resp = await client.get("https://arxiv.org/pdf/1706.03762")
        assert resp.status_code == 200
        pdf_path.write_bytes(resp.content)

    output_dir = workspace / "mineru_output"
    call = tool_call_helper(
        "convert_to_markdown",
        {"file_path": str(pdf_path), "output_folder": str(output_dir)},
    )
    result = await agent_env.tool_execute(call)
    assert not result.is_error, f"MinerU failed: {result.text}"

    md_file = next(output_dir.glob("*.md"))
    assert "Attention Is All You Need" in md_file.read_text()
