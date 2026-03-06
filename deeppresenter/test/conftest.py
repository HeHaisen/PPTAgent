"""Pytest configuration and shared fixtures."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest  # noqa: E402
from openai.types.chat.chat_completion_message_tool_call import (
    ChatCompletionMessageFunctionToolCall as ToolCall,  # noqa: E402
)
from openai.types.chat.chat_completion_message_tool_call import Function  # noqa: E402
from utils.config import DeepPresenterConfig  # noqa: E402

from deeppresenter.agents.env import AgentEnv

TEST_OUTPUT_DIR = Path(__file__).parent / "test_outputs"


def pytest_addoption(parser):
    """Add --output-dir option: temp (auto-cleanup) or permanent (keep results)."""
    parser.addoption(
        "--output-dir",
        action="store",
        default="temp",
        choices=["temp", "permanent"],
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line("markers", "sandbox: requires Docker sandbox environment")


def create_tool_call(
    name: str, arguments: dict, call_id: str | None = None
) -> ToolCall:
    """Create a ToolCall object for testing."""
    return ToolCall(
        id=call_id or f"call_{uuid.uuid4().hex[:8]}",
        type="function",
        function=Function(
            name=name, arguments=json.dumps(arguments, ensure_ascii=False)
        ),
    )


@pytest.fixture(scope="session")
def test_output_dir() -> Path:
    """Return the permanent test outputs directory."""
    TEST_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return TEST_OUTPUT_DIR


@pytest.fixture
def workspace(tmp_path: Path, request) -> Path:
    """Create a workspace directory for testing."""
    if request.config.getoption("--output-dir", "temp") == "permanent":
        path = TEST_OUTPUT_DIR / request.node.name
    else:
        path = tmp_path / "test_workspace"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
async def agent_env(workspace: Path):
    """Create an AgentEnv instance with test MCP config (sandbox only)."""
    # Use test config that only includes sandbox server
    config = DeepPresenterConfig.load_from_file()
    async with AgentEnv(workspace, config=config) as env:
        yield env


@pytest.fixture
def tool_call_helper():
    """Return the create_tool_call helper function."""
    return create_tool_call


@pytest.fixture
def mermaid_sequence_diagram() -> str:
    """Return a Chinese sequence diagram for testing."""
    return """\
sequenceDiagram
    participant 用户
    participant 前端
    participant 后端
    participant 数据库

    用户->>前端：提交请求
    前端->>后端：发送 API 调用
    后端->>数据库：查询数据
    数据库-->>后端：返回结果
    后端-->>前端：返回 JSON 数据
    前端-->>用户：显示结果
"""
