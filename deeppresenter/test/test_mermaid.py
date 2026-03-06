"""Test mermaid diagram generation."""

import pytest

PUPPETEER_CONFIG = '{"args":["--no-sandbox","--disable-setuid-sandbox"]}'


@pytest.mark.asyncio
async def test_mermaid_sequence_chinese(
    agent_env, workspace, mermaid_sequence_diagram, tool_call_helper
):
    """Test mermaid sequence diagram with Chinese text."""
    diagram_path = workspace / "sequence.mmd"
    config_path = workspace / ".puppeteerrc.json"
    output_path = workspace / "sequence_diagram.png"

    for path, content in [
        (diagram_path, mermaid_sequence_diagram),
        (config_path, PUPPETEER_CONFIG),
    ]:
        call = tool_call_helper("write_file", {"path": str(path), "content": content})
        result = await agent_env.tool_execute(call)
        assert not result.is_error

    exec_call = tool_call_helper(
        "execute_command",
        {"command": f"mmdc -i {diagram_path} -o {output_path} -p {config_path}"},
    )
    result = await agent_env.tool_execute(exec_call)
    assert not result.is_error and "Error:" not in result.text

    list_call = tool_call_helper("list_directory", {"path": str(workspace)})
    list_result = await agent_env.tool_execute(list_call)
    assert "sequence_diagram.png" in list_result.text
