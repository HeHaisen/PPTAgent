import csv
import math
import os
import re
import shutil
import sys
import warnings
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from filelock import FileLock
from PIL import Image
from pptagent_pptx import Presentation
from pydantic import BaseModel

from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.log import debug, set_logger, warning

warnings.filterwarnings(
    "ignore", category=DeprecationWarning, module="fastmcp.tools.tool"
)

Image.MAX_IMAGE_PIXELS = None  # only reading metadata, no actual decompression

mcp = FastMCP(name="Task")

CONFIG = DeepPresenterConfig.load_from_file(os.getenv("CONFIG_FILE"))


def _rewrite_image_link(match: re.Match[str], md_dir: Path) -> str:
    alt_text = match.group(1)
    target = match.group(2).strip()
    if not target:
        return match.group(0)
    parts = re.match(r"([^\s]+)(.*)", target)
    if not parts:
        return match.group(0)
    local_path = parts.group(1).strip("\"'")
    rest = parts.group(2)
    p = Path(local_path)
    if not p.is_absolute() and (md_dir / local_path).exists():
        p = md_dir / local_path
    if not p.exists():
        return match.group(0)

    updated_alt = alt_text
    try:
        with Image.open(p) as img:
            width, height = img.size
        if width > 0 and height > 0 and not re.search(r"\b\d+:\d+\b", updated_alt):
            factor = math.gcd(width, height)
            ratio = f"{width // factor}:{height // factor}"
            updated_alt = f"{updated_alt}, {ratio}" if updated_alt else ratio
    except Exception as e:
        warning(f"Failed to get image size for {p}: {e}")

    # ? since slides were placed in an independent folder, we convert image path to absolute path to avoid broken links
    new_path = p.resolve().as_posix()
    return f"![{updated_alt}]({new_path}{rest})"


class Todo(BaseModel):
    id: str
    content: str
    status: Literal["pending", "in_progress", "completed", "skipped"]


LOCAL_TODO_CSV_PATH = Path("todo.csv")
LOCAL_TODO_LOCK_PATH = Path(".todo.csv.lock")


def _load_todos() -> list[Todo]:
    """Load todos from CSV file."""
    if not LOCAL_TODO_CSV_PATH.exists():
        return []

    lock = FileLock(LOCAL_TODO_LOCK_PATH)
    with lock:
        with open(LOCAL_TODO_CSV_PATH, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            return [Todo(**row) for row in reader]


def _save_todos(todos: list[Todo]) -> None:
    """Save todos to CSV file."""
    lock = FileLock(LOCAL_TODO_LOCK_PATH)
    with lock:
        with open(LOCAL_TODO_CSV_PATH, "w", encoding="utf-8", newline="") as f:
            if todos:
                fieldnames = ["id", "content", "status"]
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                for todo in todos:
                    writer.writerow(todo.model_dump())


@mcp.tool()
def todo_create(todo_content: str) -> str:
    """
    Create a new todo item and add it to the todo list.

    Args:
        todo_content (str): The content/description of the todo item

    Returns:
        str: Confirmation message with the created todo's ID
    """
    todos = _load_todos()
    new_id = str(len(todos))
    new_todo = Todo(id=new_id, content=todo_content, status="pending")
    todos.append(new_todo)
    _save_todos(todos)
    return f"Todo {new_id} created"


@mcp.tool()
def todo_update(
    idx: int,
    todo_content: str = None,
    status: Literal["completed", "in_progress", "skipped"] = None,
) -> str:
    """
    Update an existing todo item's content or status.

    Args:
        idx (int): The index of the todo item to update
        todo_content (str, optional): New content for the todo item
        status (Literal["completed", "in_progress", "skipped"], optional): New status for the todo item

    Returns:
        str: Confirmation message with the updated todo's ID
    """
    todos = _load_todos()
    assert 0 <= idx < len(todos), f"Invalid todo index: {idx}"

    if todo_content is not None:
        todos[idx].content = todo_content
    if status is not None:
        todos[idx].status = status
    _save_todos(todos)
    return "Todo updated successfully"


@mcp.tool()
def todo_list() -> str | list[Todo]:
    """
    Get the current todo list or check if all todos are completed.

    Returns:
        str | list[Todo]: Either a completion message if all todos are done/skipped,
                         or the current list of todo items
    """
    todos = _load_todos()
    if not todos or all(todo.status in ["completed", "skipped"] for todo in todos):
        LOCAL_TODO_CSV_PATH.unlink(missing_ok=True)
        return "All todos completed"
    else:
        return todos


# @mcp.tool()
def ask_user(question: str) -> str:
    """
    Ask the user a question when encounters an unclear requirement.
    """
    print(f"User input required: {question}")
    return input("Your answer: ")


@mcp.tool()
def thinking(thought: str):
    """This tool is for explicitly reasoning about the current task state and next actions."""
    debug(f"Thought: {thought}")
    return thought


@mcp.tool(exclude_args=["agent_name"])
def finalize(outcome: str, agent_name: str = "") -> str:
    """
    When all tasks are finished, call this function to finalize the loop.
    Args:
        outcome (str): The path to the final outcome file or directory.
    """
    # here we conduct some final checks on agent's outcome
    path = Path(outcome)
    assert path.exists(), f"Outcome {outcome} does not exist"
    if agent_name == "Research":
        md_dir = path.parent
        assert path.suffix == ".md", (
            f"Outcome file should be a markdown file, got {path.suffix}"
        )
        with open(path, encoding="utf-8") as f:
            content = f.read()

        try:
            content = re.sub(
                r"!\[(.*?)\]\((.*?)\)",
                lambda match: _rewrite_image_link(match, md_dir),
                content,
            )
            shutil.copyfile(path, md_dir / ("." + path.name))
            path.write_text(content, encoding="utf-8")
        except Exception as e:
            warning(f"Failed to rewrite image links: {e}")

    elif agent_name == "PPTAgent":
        assert path.is_file() and path.suffix == ".pptx", (
            f"Outcome file should be a pptx file, got {path.suffix}"
        )
        prs = Presentation(str(path))
        if len(prs.slides) <= 0:
            return "PPTX file should contain at least one slide"
    elif agent_name == "Design":
        html_files = list(path.glob("*.html"))
        if len(html_files) <= 0:
            return "Outcome path should be a directory containing HTML files"
        if not all(f.stem.startswith("slide_") for f in html_files):
            return "All HTML files should start with 'slide_'"
    else:
        warning(f"Unverifiable agent: {agent_name}")

    if LOCAL_TODO_CSV_PATH.exists():
        LOCAL_TODO_CSV_PATH.unlink()
    if LOCAL_TODO_LOCK_PATH.exists():
        LOCAL_TODO_LOCK_PATH.unlink()

    debug(f"Agent {agent_name} finalized the outcome: {outcome}")
    return outcome


if __name__ == "__main__":
    assert len(sys.argv) == 2, "Usage: python task.py <workspace>"
    work_dir = Path(sys.argv[1])
    assert work_dir.exists(), f"Workspace {work_dir} does not exist."
    os.chdir(work_dir)
    set_logger(f"task-{work_dir.stem}", work_dir / ".history" / "task.log")

    mcp.run(show_banner=False)
