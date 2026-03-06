#!/usr/bin/env python3
"""DeepPresenter CLI - Terminal interface for PPT generation"""

import asyncio
import json
import platform
import shutil
import subprocess
import sys
import time
import traceback
import uuid
import warnings
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

# Suppress common warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*urllib3.*")
warnings.filterwarnings("ignore", message=".*chardet.*")
warnings.filterwarnings("ignore", message=".*charset_normalizer.*")

# ruff: noqa: E402
# Import after setting environment variables to suppress warnings
import typer
import yaml
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

import deeppresenter.utils.webview as webview
from deeppresenter import __version__ as version
from deeppresenter.main import AgentLoop, InputRequest
from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.constants import PACKAGE_DIR

app = typer.Typer(
    help="DeepPresenter - Agentic PowerPoint Generation", no_args_is_help=True
)
console = Console()

CONFIG_DIR = Path.home() / ".config" / "deeppresenter"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
MCP_FILE = CONFIG_DIR / "mcp.json"

LOCAL_MODEL = "Forceless/DeepPresenter-9B-GGUF:q4_K_M"
LOCAL_BASE_URL = "http://127.0.0.1:8080/v1"
REQUIRED_LLM_KEYS = [
    "research_agent",
    "design_agent",
    "long_context_model",
]


def is_local_model_server_running() -> bool:
    """Check whether local OpenAI-compatible server responds on /v1/models."""
    try:
        models_url = f"{LOCAL_BASE_URL.rstrip('/')}/models"
        req = Request(models_url, method="GET")
        with urlopen(req, timeout=2) as resp:
            if resp.status != 200:
                return False
            payload = json.loads(resp.read().decode("utf-8") or "{}")
            return isinstance(payload, dict) and isinstance(payload.get("data"), list)
    except (
        HTTPError,
        URLError,
        TimeoutError,
        ValueError,
        json.JSONDecodeError,
        OSError,
    ):
        return False


def setup_inference() -> bool:
    """Ensure local inference service is running."""
    if is_local_model_server_running():
        return True

    system = platform.system().lower()
    cmd: list[str] | None = None

    if system == "darwin":
        console.print(
            f"[cyan]Local model service is not running, starting llama-server -hf {LOCAL_MODEL}[/cyan]"
        )
        cmd = ["llama-server", "-hf", LOCAL_MODEL, "-c", "50000"]
    elif system == "linux":
        script_path = PACKAGE_DIR / "deeppresenter" / "sglang.sh"
        if not script_path.exists():
            console.print(
                f"[bold red]Error:[/bold red] Missing startup script: {script_path}"
            )
            return False
        console.print(
            f"[cyan]Local model service is not running, starting {script_path}[/cyan]"
        )
        cmd = ["bash", str(script_path)]
    elif system == "windows":
        console.print(
            "[bold red]Error:[/bold red] Please use WSL and run resource/sglang.sh inside WSL first."
        )
        return False

    if cmd is None:
        return False

    try:
        process = subprocess.Popen(cmd)
    except FileNotFoundError:
        console.print(
            "[bold red]Error:[/bold red] llama-server not found. Please install llama.cpp first."
        )
        return False
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] Failed to start local service: {e}")
        return False

    while True:
        if is_local_model_server_running():
            return True

        if process.poll() is not None:
            if is_local_model_server_running():
                return True
            console.print(
                f"[bold red]Error:[/bold red] Local model service exited unexpectedly with code {process.returncode}."
            )
            return False

        time.sleep(1)


def is_onboarded() -> bool:
    """Check if user has completed onboarding"""
    return CONFIG_FILE.exists() and MCP_FILE.exists()


def prompt_llm_config(
    name: str,
    optional: bool = False,
    existing: dict | None = None,
    previous_config: tuple[str, dict] | None = None,
) -> dict | None:
    """Prompt user for LLM configuration

    Args:
        name: Name of the LLM to configure
        optional: Whether this configuration is optional
        existing: Existing configuration from previous onboarding
        previous_config: (name, config) tuple from the last configured model
    """
    if optional:
        if not Confirm.ask(f"Configure {name}?", default=False):
            return None

    console.print(f"\n[bold cyan]Configuring {name}[/bold cyan]")

    # Show existing config from previous onboarding
    if existing:
        console.print(
            f"[dim]Previous: {existing.get('model', 'N/A')} @ {existing.get('base_url', 'N/A')}[/dim]"
        )
        if Confirm.ask(f"Reuse previous {name} configuration?", default=True):
            return existing

    # Show last configured model in this session
    if previous_config:
        prev_name, prev_cfg = previous_config
        console.print(
            f"[dim]Last configured: {prev_name} - {prev_cfg.get('model', 'N/A')} @ {prev_cfg.get('base_url', 'N/A')}[/dim]"
        )
        if Confirm.ask(f"Reuse {prev_name} configuration?", default=True):
            return prev_cfg

    base_url = Prompt.ask("Base URL")
    model = Prompt.ask("Model name")
    api_key = Prompt.ask("API key", password=True)

    config = {
        "base_url": base_url,
        "model": model,
        "api_key": api_key,
    }

    return config


def check_playwright_browsers():
    """Check if Playwright browsers are installed, install if not"""
    console.print("\n[bold cyan]Checking Playwright browsers...[/bold cyan]")

    try:
        # Try to run playwright install
        result = subprocess.run(
            ["playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode == 0:
            console.print("[green]✓[/green] Playwright browsers installed")
            return True
        else:
            console.print(
                f"[yellow]⚠[/yellow] Failed to install Playwright browsers: {result.stderr}"
            )
            return False

    except subprocess.TimeoutExpired:
        console.print("[yellow]⚠[/yellow] Playwright installation timed out")
        return False
    except FileNotFoundError:
        console.print(
            "[yellow]⚠[/yellow] Playwright not found. Installing browsers may fail."
        )
        return False
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow] Error installing Playwright browsers: {e}")
        return False


def check_npm_dependencies():
    """Check required html2pptx npm dependencies"""
    console.print("\n[bold cyan]Checking Node.js dependencies...[/bold cyan]")

    if webview._NODE_PATH:
        console.print(
            f"[green]✓[/green] Node.js dependencies found at {webview._NODE_PATH}"
        )
        return True

    cache_html2pptx_dir = webview._CACHE_HTML2PPTX_DIR
    cache_html2pptx_dir.mkdir(parents=True, exist_ok=True)

    console.print(
        "[yellow]⚠[/yellow] html2pptx Node dependencies are missing, installing to cache..."
    )

    result = subprocess.run(
        [
            "npm",
            "install",
            "--prefix",
            str(cache_html2pptx_dir),
            *webview._REQUIRED_PACKAGES,
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        console.print(
            f"[yellow]⚠[/yellow] Failed to install Node.js dependencies: {result.stderr or result.stdout}"
        )
        console.print("[yellow]Please install dependencies manually:[/yellow]")
        console.print(f"  cd {cache_html2pptx_dir} && npm install")
        return False

    node_modules_dir = cache_html2pptx_dir / "node_modules"
    if all((node_modules_dir / pkg).exists() for pkg in webview._REQUIRED_PACKAGES):
        webview._NODE_PATH = str(node_modules_dir)
        console.print(
            f"[green]✓[/green] Node.js dependencies installed at {webview._NODE_PATH}"
        )
        return True

    console.print(
        "[yellow]⚠[/yellow] Install finished but required packages are still missing"
    )
    console.print("[yellow]Please install dependencies manually:[/yellow]")
    console.print(f"  cd {cache_html2pptx_dir} && npm install")
    return False


def check_docker_image():
    """Check if deeppresenter-sandbox image exists, pull if not"""
    console.print("\n[bold cyan]Checking Docker sandbox image...[/bold cyan]")

    try:
        # Check if image exists
        result = subprocess.run(
            ["docker", "images", "-q", "deeppresenter-sandbox:0.1.0"],
            capture_output=True,
            text=True,
            timeout=10,
        )

        if result.returncode == 0 and result.stdout.strip():
            console.print(
                "[green]✓[/green] Docker image deeppresenter-sandbox:0.1.0 found"
            )
            return True

        # Image not found, try to pull
        console.print(
            "[yellow]Docker image not found, pulling from forceless/deeppresenter-sandbox...[/yellow]"
        )

        pull_result = subprocess.run(
            ["docker", "pull", "forceless/deeppresenter-sandbox:0.1.0"],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if pull_result.returncode == 0:
            # Tag the pulled image
            subprocess.run(
                [
                    "docker",
                    "tag",
                    "forceless/deeppresenter-sandbox:0.1.0",
                    "deeppresenter-sandbox:0.1.0",
                ],
                capture_output=True,
                timeout=10,
            )
            console.print(
                "[green]✓[/green] Successfully pulled and tagged Docker image"
            )
            return True
        else:
            console.print(
                f"[yellow]⚠[/yellow] Failed to pull Docker image: {pull_result.stderr}"
            )
            console.print(
                "[yellow]Sandbox functionality may not work. You can pull it manually:[/yellow]"
            )
            console.print("  docker pull forceless/deeppresenter-sandbox:0.1.0")
            console.print(
                "  docker tag forceless/deeppresenter-sandbox:0.1.0 deeppresenter-sandbox:0.1.0"
            )
            return False

    except subprocess.TimeoutExpired:
        console.print("[yellow]⚠[/yellow] Docker command timed out")
        return False
    except FileNotFoundError:
        console.print(
            "[yellow]⚠[/yellow] Docker not found. Please install Docker to use sandbox features."
        )
        return False
    except Exception as e:
        console.print(f"[yellow]⚠[/yellow] Error checking Docker image: {e}")
        return False


@app.command()
def onboard():
    """Configure DeepPresenter (config.yaml and mcp.json)"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # Load existing config if available
    existing_config = None
    if is_onboarded():
        console.print("[yellow]Configuration already exists.[/yellow]")
        console.print(f"Config: {CONFIG_FILE}")
        console.print(f"MCP: {MCP_FILE}")

        if not Confirm.ask(
            "\nDo you want to reconfigure (existing config will be backed up)?",
            default=False,
        ):
            console.print("[green]Keeping existing configuration.[/green]")
            return

        # Load existing config to potentially reuse
        with open(CONFIG_FILE) as f:
            existing_config = yaml.safe_load(f)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = CONFIG_DIR / f"backup_{timestamp}"
        backup_dir.mkdir(exist_ok=True)
        shutil.copy(CONFIG_FILE, backup_dir / "config.yaml")
        shutil.copy(MCP_FILE, backup_dir / "mcp.json")
        console.print(f"[green]✓[/green] Backed up to {backup_dir}")

    console.print(
        Panel.fit(
            f"[bold green]Welcome to DeepPresenter v{version}![/bold green]\n"
            "Let's configure your environment.",
            title="Onboarding",
        )
    )

    # Check Docker sandbox image
    check_docker_image()

    # Check Playwright browsers
    check_playwright_browsers()

    # Check npm dependencies
    check_npm_dependencies()

    # Check if config files exist in current directory
    local_config = Path.cwd() / "deeppresenter" / "config.yaml"
    local_mcp = Path.cwd() / "deeppresenter" / "mcp.json"

    config_data = None
    mcp_data = None

    if local_config.exists() and local_mcp.exists():
        console.print("\n[cyan]Found existing config in current directory:[/cyan]")
        console.print(f"  • {local_config}")
        console.print(f"  • {local_mcp}")

        if Confirm.ask("\nDo you want to reuse these configurations?", default=True):
            console.print("[green]✓[/green] Reusing existing configurations")
            with open(local_config) as f:
                config_data = yaml.safe_load(f)
            with open(local_mcp) as f:
                mcp_data = json.load(f)

    # Load example configs if not reusing
    if config_data is None or mcp_data is None:
        config_example = PACKAGE_DIR / "config.yaml.example"
        mcp_example = PACKAGE_DIR / "mcp.json.example"

        with open(config_example) as f:
            config_data = yaml.safe_load(f)

        with open(mcp_example) as f:
            mcp_data = json.load(f)

        use_local_model = False
        if not (
            isinstance(existing_config, dict)
            and all(
                isinstance(existing_config.get(key), dict)
                and existing_config.get(key, {}).get("base_url")
                and existing_config.get(key, {}).get("model")
                for key in REQUIRED_LLM_KEYS
            )
        ):
            console.print("\n[bold yellow]Quick Setup[/bold yellow]")
            use_local_model = Confirm.ask(
                f"No complete model configuration found. Configure local model service with {LOCAL_MODEL}?",
                default=True,
            )
            if use_local_model:
                system = platform.system().lower()
                if system == "darwin":
                    if shutil.which("brew") is None:
                        console.print(
                            "[bold red]✗[/bold red] Homebrew not found. Please install Homebrew first."
                        )
                        use_local_model = False
                    else:
                        console.print(
                            "[cyan]Installing llama.cpp with Homebrew...[/cyan]"
                        )
                        result = subprocess.run(
                            ["brew", "install", "llama.cpp"],
                            capture_output=True,
                            text=True,
                        )
                        if result.returncode != 0:
                            console.print(
                                f"[bold red]✗[/bold red] Failed to install llama.cpp: {result.stderr.strip() or result.stdout.strip()}"
                            )
                            use_local_model = False
                        else:
                            console.print("[green]✓[/green] llama.cpp installed")
                elif system == "windows":
                    console.print(
                        "[bold red]✗[/bold red] Windows is not directly supported for local service setup."
                    )
                    console.print(
                        "[yellow]Please use WSL, then run onboarding again inside WSL.[/yellow]"
                    )
                    use_local_model = False

                if use_local_model and not setup_inference():
                    console.print(
                        "[yellow]Falling back to manual model configuration because local service is not running.[/yellow]"
                    )
                    use_local_model = False

        # Track last configured model
        last_config = None

        # Configure required LLMs
        console.print("\n[bold yellow]Required LLM Configurations[/bold yellow]")

        if use_local_model:
            local_cfg = {
                "base_url": LOCAL_BASE_URL,
                "model": LOCAL_MODEL,
                "api_key": "",
            }
            for key in REQUIRED_LLM_KEYS:
                display_name = " ".join([i.capitalize() for i in key.split("_")])
                config_data[key] = dict(local_cfg)
                last_config = (display_name, dict(local_cfg))
                console.print(
                    f"[green]✓[/green] {display_name}: {LOCAL_MODEL} @ {LOCAL_BASE_URL}"
                )
            config_data["vision_model"] = None
        else:
            research_agent = prompt_llm_config(
                "Research Agent",
                existing=existing_config.get("research_agent")
                if existing_config
                else None,
                previous_config=last_config,
            )
            config_data["research_agent"] = research_agent
            last_config = ("Research Agent", research_agent)

            design_agent = prompt_llm_config(
                "Design Agent",
                existing=existing_config.get("design_agent")
                if existing_config
                else None,
                previous_config=last_config,
            )
            config_data["design_agent"] = design_agent
            last_config = ("Design Agent", design_agent)

            long_context = prompt_llm_config(
                "Long Context Model",
                existing=existing_config.get("long_context_model")
                if existing_config
                else None,
                previous_config=last_config,
            )
            config_data["long_context_model"] = long_context
            last_config = ("Long Context Model", long_context)

            vision_model = prompt_llm_config(
                "Vision Model",
                optional=True,
                existing=existing_config.get("vision_model")
                if existing_config
                else None,
                previous_config=last_config,
            )
            config_data["vision_model"] = vision_model
            last_config = ("Vision Model", vision_model)

        # Optional T2I model
        console.print("\n[bold yellow]Optional Configurations[/bold yellow]")
        t2i_config = prompt_llm_config(
            "Text-to-Image Model",
            optional=True,
            existing=existing_config.get("t2i_model") if existing_config else None,
            previous_config=last_config,
        )
        if t2i_config:
            config_data["t2i_model"] = t2i_config

        # Configure MCP (optional Tavily API key)
        console.print("\n[bold cyan]MCP Configuration[/bold cyan]")
        if Confirm.ask("Configure Tavily API key for web search?", default=False):
            tavily_key = Prompt.ask("Tavily API key", password=True)
            # Update tavily key in mcp config
            for server in mcp_data:
                if server.get("name") == "search":
                    server["env"]["TAVILY_API_KEY"] = tavily_key
                    break
            else:
                raise ValueError("search server not found in mcp.json")

        # Configure MinerU API key
        if Confirm.ask("Configure MinerU API key for PDF parsing?", default=False):
            mineru_key = Prompt.ask("MinerU API key", password=True)
            for server in mcp_data:
                if server.get("name") == "any2markdown":
                    server["env"]["MINERU_API_KEY"] = mineru_key
                    break
            else:
                raise ValueError("any2markdown server not found in mcp.json")

    # Save configs
    with open(CONFIG_FILE, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False, allow_unicode=True)

    with open(MCP_FILE, "w") as f:
        json.dump(mcp_data, f, indent=2, ensure_ascii=False)

    console.print(f"\n[bold green]✓[/bold green] Configuration saved to {CONFIG_DIR}")

    # Validate LLMs
    console.print("\n[bold cyan]Validating LLM configurations...[/bold cyan]")
    try:
        config = DeepPresenterConfig.load_from_file(str(CONFIG_FILE))
        asyncio.run(config.validate_llms())
        console.print("[bold green]✓[/bold green] All LLMs validated successfully!")
    except Exception as e:
        console.print(f"[bold red]✗[/bold red] Validation failed: {e}")
        console.print("Please check your configuration and try again.")
        sys.exit(1)


@app.command()
def serve():
    """Start local inference service and stream server output"""
    if setup_inference():
        console.print("[bold green]✓[/bold green] Local model service is ready")
        return
    sys.exit(1)


@app.command()
def generate(
    prompt: Annotated[str, typer.Argument(help="Presentation prompt/instruction")],
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output file path (e.g., output.pptx)"),
    ],
    files: Annotated[
        list[Path], typer.Option("--file", "-f", help="Attachment files")
    ] = None,
    pages: Annotated[
        str, typer.Option("--pages", "-p", help="Number of pages (e.g., '8', '5-10')")
    ] = None,
    aspect_ratio: Annotated[
        str,
        typer.Option("--aspect", "-a", help="Aspect ratio (16:9, 4:3, A1, A3, A2, A4)"),
    ] = "16:9",
    language: Annotated[
        str, typer.Option("--lang", "-l", help="Language (en/zh)")
    ] = "en",
):
    """Generate a presentation from prompt and optional files"""

    # Check onboarding
    if not is_onboarded():
        console.print(
            "[bold red]Error:[/bold red] Please run 'deeppresenter onboard' (or 'pptagent onboard') first"
        )
        sys.exit(1)

    # Validate files
    attachments = []
    if files:
        for f in files:
            if not f.exists():
                console.print(f"[bold red]Error:[/bold red] File not found: {f}")
                sys.exit(1)
            attachments.append(str(f.resolve()))

    # Create request
    request = InputRequest(
        instruction=prompt,
        attachments=attachments,
        num_pages=pages,
        powerpoint_type=aspect_ratio,
    )

    # Load config
    config = DeepPresenterConfig.load_from_file(str(CONFIG_FILE))
    config.mcp_config_file = str(MCP_FILE)

    # Ensure local model service is available
    if any(
        "127.0.0.1" in str(config.model_dump().get(key, {}).get("base_url", ""))
        or "localhost" in str(config.model_dump().get(key, {}).get("base_url", ""))
        for key in REQUIRED_LLM_KEYS
    ):
        if not is_local_model_server_running() and not setup_inference():
            sys.exit(1)

    # Run generation
    async def run():
        session_id = str(uuid.uuid4())[:8]

        loop = AgentLoop(
            config=config,
            session_id=session_id,
            workspace=None,  # Let AgentLoop create workspace automatically
            language=language,
        )

        console.print(
            Panel.fit(
                f"[bold]Prompt:[/bold] {prompt}\n"
                f"[bold]Attachments:[/bold] {len(attachments)}\n"
                f"[bold]Workspace:[/bold] {loop.workspace}\n"
                f"[bold]Version:[/bold] {version}",
                title="Generation Task",
            )
        )

        try:
            async for msg in loop.run(request):
                if isinstance(msg, (str, Path)):
                    generated_file = Path(msg)

                    # Copy to output location
                    output_path = Path(output).resolve()
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy(generated_file, output_path)
                    console.print(
                        f"\n[bold green]✓[/bold green] Generated: {generated_file}"
                    )
                    console.print(
                        f"[bold green]✓[/bold green] Copied to: {output_path}"
                    )
                    return str(output_path)
        except Exception as e:
            console.print(f"[bold red]✗[/bold red] Generation failed: {e}")
            raise

    try:
        result = asyncio.run(run())
        console.print(f"\n[bold green]Success![/bold green] Output: {result}")
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[bold red]Failed:[/bold red] {e}")
        console.print("\n[dim]Traceback:[/dim]")
        console.print(traceback.format_exc())
        sys.exit(1)


@app.command()
def config():
    """Show current configuration"""
    if not is_onboarded():
        console.print(
            "[bold red]Not configured.[/bold red] Run 'deeppresenter onboard' (or 'pptagent onboard') first."
        )
        return

    console.print(f"\n[bold]Config file:[/bold] {CONFIG_FILE}")
    console.print(f"[bold]MCP file:[/bold] {MCP_FILE}")

    with open(CONFIG_FILE) as f:
        config_data = yaml.safe_load(f)

    console.print("\n[bold cyan]LLM Configuration:[/bold cyan]")
    for key in [
        "research_agent",
        "design_agent",
        "long_context_model",
        "vision_model",
        "t2i_model",
    ]:
        if key in config_data:
            llm = config_data[key]
            if isinstance(llm, dict):
                console.print(f"  {key}: {llm.get('model', 'N/A')}")


@app.command()
def reset():
    """Reset configuration (delete config files)"""
    if Confirm.ask(f"Delete configuration at {CONFIG_DIR}?", default=False):
        if CONFIG_DIR.exists():
            shutil.rmtree(CONFIG_DIR)
            console.print("[bold green]✓[/bold green] Configuration reset")
        else:
            console.print("[yellow]No configuration found[/yellow]")


def main():
    """Entry point for uvx"""
    app()


if __name__ == "__main__":
    main()
