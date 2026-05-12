import os
import re
import shutil
import socket
import sys
import time
import uuid
import json
import html
import asyncio
from datetime import datetime
from pathlib import Path
from shutil import which
from urllib.parse import quote

import gradio as gr
import jsonlines
from pdf2image import convert_from_path

from deeppresenter.main import AgentLoop
from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.constants import WORKSPACE_BASE
from deeppresenter.utils.log import create_logger
from deeppresenter.utils.typings import ChatMessage, ConvertType, InputRequest, Role
from deeppresenter.utils.webview import PlaywrightConverter
from pptagent import PPTAgentServer
from pptagent.uploaded_template import (
    TemplatePreparationError,
    prepare_uploaded_template,
)
from pptagent.utils import ppt_to_images

def resolve_webui_log_file() -> Path:
    """Resolve writable log file path for web UI process."""
    timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    preferred_dir = Path(
        os.getenv("DEEPPRESENTER_WEBUI_LOG_DIR", "/tmp/deeppresenter/logs")
    )
    return preferred_dir / f"{timestamp}.log"


logger = create_logger(
    "DeepPresenterUI",
    log_file=str(resolve_webui_log_file()),
)


ROLE_EMOJI = {
    Role.SYSTEM: "⚙️",
    Role.USER: "👤",
    Role.ASSISTANT: "🤖",
    Role.TOOL: "📝",
}

CONVERT_MAPPING = {
    "自由生成 (freeform)": ConvertType.DEEPPRESENTER,
    "模版 (templates)": ConvertType.PPTAGENT,
}

MISSING_PPT_PREVIEW_DEP_MSG = "Neither unoconvert nor soffice is installed"
LIVE_PREVIEW_PPTX_REL_PATH = Path(".preview") / "live_preview.pptx"
_MAX_PREVIEW_DIRS = 5  # keep at most N most-recent preview cache dirs


def cleanup_preview_dirs(workspace: Path, keep: int = _MAX_PREVIEW_DIRS) -> None:
    """Remove old preview cache directories, keeping the most recent `keep`."""
    preview_root = workspace / ".preview"
    if not preview_root.exists():
        return
    dirs = sorted(
        [d for d in preview_root.iterdir() if d.is_dir()],
        key=lambda d: d.stat().st_mtime,
        reverse=True,
    )
    for old_dir in dirs[keep:]:
        try:
            shutil.rmtree(old_dir)
        except OSError:
            pass


_MAX_CONCURRENT_SESSIONS = int(os.getenv("DP_MAX_CONCURRENT", "3"))
_session_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_SESSIONS)


def detect_ppt_preview_dependencies() -> dict[str, object]:
    """Detect runtime dependencies for PPT image preview."""
    unoconvert_path = which("unoconvert")
    soffice_path = which("soffice")

    unoserver_host = os.environ.get("UNOSERVER_URL", "127.0.0.1")
    unoserver_port_raw = os.environ.get("UNOSERVER_PORT", "2003")
    unoserver_reachable = False
    unoserver_note = "未检查"

    if unoconvert_path:
        try:
            unoserver_port = int(unoserver_port_raw)
            with socket.create_connection(
                (unoserver_host, unoserver_port), timeout=0.4
            ) as conn:
                conn.settimeout(0.4)
            unoserver_reachable = True
            unoserver_note = "可连接"
        except ValueError:
            unoserver_note = f"端口无效（UNOSERVER_PORT={unoserver_port_raw}）"
        except OSError:
            unoserver_note = "不可连接"

    can_use_unoconvert = bool(unoconvert_path and unoserver_reachable)
    can_ppt_image_preview = bool(soffice_path or can_use_unoconvert)

    if can_ppt_image_preview:
        failure_reason = ""
    elif not unoconvert_path and not soffice_path:
        failure_reason = "未检测到 `unoconvert` 和 `soffice`"
    elif unoconvert_path and not soffice_path:
        failure_reason = (
            "检测到 `unoconvert`，但 `unoserver` 未就绪（"
            f"{unoserver_host}:{unoserver_port_raw}）"
        )
    else:
        failure_reason = "PPT 图片预览依赖未就绪"

    return {
        "unoconvert_path": unoconvert_path,
        "soffice_path": soffice_path,
        "unoserver_host": unoserver_host,
        "unoserver_port": unoserver_port_raw,
        "unoserver_reachable": unoserver_reachable,
        "unoserver_note": unoserver_note,
        "can_ppt_image_preview": can_ppt_image_preview,
        "failure_reason": failure_reason,
    }


def render_ppt_preview_dependency_markdown() -> str:
    """Build markdown for preview dependency self-check panel."""
    dep = detect_ppt_preview_dependencies()

    def mark(ok: bool) -> str:
        return "✅" if ok else "❌"

    lines = [
        "当前环境状态（用于 PPT 图片预览）",
        f"- {mark(bool(dep['soffice_path']))} `soffice`: "
        f"`{dep['soffice_path'] or '未检测到'}`",
        f"- {mark(bool(dep['unoconvert_path']))} `unoconvert`: "
        f"`{dep['unoconvert_path'] or '未检测到'}`",
    ]

    if dep["unoconvert_path"]:
        lines.append(
            f"- {mark(bool(dep['unoserver_reachable']))} `unoserver` "
            f"({dep['unoserver_host']}:{dep['unoserver_port']}): {dep['unoserver_note']}"
        )

    if dep["can_ppt_image_preview"]:
        lines.append("- ✅ PPT 图片预览能力：可用")
    else:
        lines.append("- ⚠️ PPT 图片预览能力：不可用")
        lines.append(
            f"- 建议：{dep['failure_reason']}。优先安装 LibreOffice（提供 `soffice`）。"
        )

    return "\n".join(lines)


def load_runtime_config() -> DeepPresenterConfig:
    """Load runtime config and MCP file path for web UI."""
    local_config = Path.cwd() / "deeppresenter" / "config.yaml"
    local_mcp = Path.cwd() / "deeppresenter" / "mcp.json"
    user_config_dir = Path.home() / ".config" / "deeppresenter"
    user_config = user_config_dir / "config.yaml"
    user_mcp = user_config_dir / "mcp.json"

    for config_path, mcp_path in (
        (local_config, local_mcp),
        (user_config, user_mcp),
    ):
        if config_path.exists() and mcp_path.exists():
            config = DeepPresenterConfig.load_from_file(str(config_path))
            config.mcp_config_file = str(mcp_path.resolve())
            return config

    raise FileNotFoundError(
        "No valid config found. Expected one of: "
        f"{local_config} + {local_mcp}, "
        f"{user_config} + {user_mcp}. "
        "Please run `pptagent onboard` first."
    )


gradio_css = """
:root {
    --dp-bg: #f3ede3;
    --dp-surface: rgba(255, 252, 246, 0.92);
    --dp-surface-strong: #fffdf8;
    --dp-border: rgba(23, 42, 58, 0.12);
    --dp-text: #162534;
    --dp-muted: #5f6e7a;
    --dp-primary: #0d6b62;
    --dp-primary-strong: #0a554f;
    --dp-soft: #e6f5f1;
    --dp-soft-strong: #d8efe8;
    --dp-ink-soft: #ebf0f4;
    --dp-warm: #f6e6d3;
    --dp-shadow: 0 20px 60px rgba(16, 33, 47, 0.10);
    --dp-preview-height-desktop: 700px;
    --dp-preview-height-mobile: 520px;
    --dp-status-bg: #eef4fb;
}
body {
    margin: 0 !important;
    padding: 0 !important;
    font-family: "IBM Plex Sans", "Source Han Sans SC", "Noto Sans SC", "PingFang SC", sans-serif;
    background:
        radial-gradient(circle at 0% 0%, rgba(184, 218, 240, 0.70) 0%, transparent 38%),
        radial-gradient(circle at 100% 0%, rgba(228, 211, 178, 0.55) 0%, transparent 30%),
        linear-gradient(135deg, rgba(255, 255, 255, 0.55), transparent 55%),
        var(--dp-bg);
}
.gradio-container {
    max-width: 1680px !important;
    margin: 0 auto !important;
    padding: 18px 18px 26px !important;
    color: var(--dp-text);
}
.hero-banner {
    display: grid;
    grid-template-columns: minmax(0, 1.8fr) minmax(280px, 1fr);
    gap: 18px;
    margin-bottom: 16px;
    padding: 22px 24px;
    border: 1px solid rgba(16, 33, 47, 0.10);
    border-radius: 28px;
    background:
        linear-gradient(135deg, rgba(255, 255, 255, 0.92), rgba(243, 248, 246, 0.88)),
        linear-gradient(120deg, rgba(13, 107, 98, 0.06), rgba(23, 42, 58, 0.03));
    box-shadow: var(--dp-shadow);
    animation: rise-in 0.4s ease-out both;
    overflow: visible !important;
}
.hero-copy {
    display: flex;
    flex-direction: column;
    gap: 10px;
}
.hero-badge {
    display: inline-flex;
    width: fit-content;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    border-radius: 999px;
    background: rgba(13, 107, 98, 0.10);
    color: var(--dp-primary-strong);
    font-size: 0.85rem;
    font-weight: 700;
    letter-spacing: 0.04em;
    text-transform: uppercase;
}
.hero-copy h1 {
    margin: 0;
    font-size: clamp(2rem, 3vw, 3.1rem);
    line-height: 1.02;
    letter-spacing: -0.03em;
}
.hero-copy p {
    margin: 0;
    max-width: 720px;
    color: var(--dp-muted);
    font-size: 1rem;
    line-height: 1.7;
}
.hero-side {
    display: flex;
    flex-direction: column;
    gap: 10px;
    justify-content: center;
}
.metric-pill {
    padding: 14px 16px;
    border-radius: 18px;
    border: 1px solid rgba(13, 107, 98, 0.10);
    background: rgba(255, 255, 255, 0.72);
}
.metric-pill strong,
.metric-pill span {
    display: block;
}
.metric-pill strong {
    font-size: 0.95rem;
    margin-bottom: 4px;
}
.metric-pill span {
    color: var(--dp-muted);
    font-size: 0.92rem;
}
.main-layout {
    gap: 18px;
    align-items: stretch;
    justify-content: center;
    overflow: visible !important;
}
.panel-card {
    background: var(--dp-surface);
    border: 1px solid var(--dp-border);
    border-radius: 24px;
    padding: 18px;
    box-shadow: var(--dp-shadow);
    backdrop-filter: blur(12px);
    animation: rise-in 0.35s ease-out both;
    position: relative;
    overflow: visible !important;
}
.input-panel {
    animation-delay: 0.04s;
    z-index: 3;
}
.result-panel {
    animation-delay: 0.08s;
    position: sticky;
    top: 12px;
    align-self: start;
    z-index: 1;
}
.section-heading {
    display: flex;
    flex-direction: column;
    gap: 5px;
    margin-bottom: 14px;
}
.section-heading h3 {
    margin: 0;
    font-size: 1.4rem;
}
.section-kicker {
    color: var(--dp-primary-strong);
    font-size: 0.78rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.section-heading p {
    margin: 0;
    color: var(--dp-muted);
    line-height: 1.6;
}
.panel-note {
    margin: 0 0 14px 0;
}
.panel-note-strip {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 10px;
}
.note-chip {
    padding: 12px 14px;
    border-radius: 16px;
    background: linear-gradient(180deg, rgba(255,255,255,0.82), rgba(232, 244, 239, 0.86));
    border: 1px solid rgba(13, 107, 98, 0.10);
}
.note-chip strong,
.note-chip span {
    display: block;
}
.note-chip strong {
    margin-bottom: 4px;
    font-size: 0.92rem;
}
.note-chip span {
    color: var(--dp-muted);
    font-size: 0.86rem;
    line-height: 1.5;
}
.control-shell,
.composer-shell,
.log-shell {
    border: 1px solid var(--dp-border);
    border-radius: 20px;
    padding: 14px;
    background: rgba(255, 255, 255, 0.66);
    margin-bottom: 14px;
    position: relative;
    overflow: visible !important;
}
.control-shell {
    background:
        linear-gradient(180deg, rgba(255,255,255,0.82), rgba(245, 248, 250, 0.72));
}
.composer-shell {
    background:
        linear-gradient(180deg, rgba(255,255,255,0.84), rgba(230, 245, 241, 0.62));
}
.subsection-title {
    margin: 0 0 10px 0;
}
.subsection-title strong,
.subsection-title span {
    display: block;
}
.subsection-title strong {
    font-size: 1rem;
    margin-bottom: 4px;
}
.subsection-title span {
    font-size: 0.88rem;
    color: var(--dp-muted);
    line-height: 1.5;
}
.field-grid {
    gap: 10px;
    overflow: visible !important;
}
.field-row-tight {
    gap: 10px;
    margin-top: 2px;
    overflow: visible !important;
}
.template-row {
    position: relative;
    z-index: 24;
    overflow: visible !important;
}
.template-row > div {
    overflow: visible !important;
}
.template-dropdown {
    position: relative;
    z-index: 80;
    overflow: visible !important;
}
.template-dropdown [data-testid="dropdown"] {
    z-index: 90 !important;
}
.template-dropdown [data-testid="dropdown"],
.template-dropdown [data-testid="dropdown"] > div,
.template-dropdown [data-testid="dropdown"] > div > div {
    position: relative;
    overflow: visible !important;
}
.template-dropdown ul,
.template-dropdown [role="listbox"],
.template-dropdown [data-testid="dropdown-options"] {
    z-index: 120 !important;
    pointer-events: auto !important;
}
.search-toggle-wrap {
    margin-top: 8px;
}
.search-toggle-wrap .wrap {
    border: 1px solid rgba(13, 107, 98, 0.12);
    border-radius: 16px;
    padding: 10px 12px;
    background: linear-gradient(180deg, rgba(255,255,255,0.88), rgba(230, 245, 241, 0.70));
}
.gradio-container [data-testid="dropdown"] {
    position: relative;
    z-index: 40;
}
.gradio-container [data-testid="dropdown"] button,
.gradio-container [data-testid="dropdown"] input,
.gradio-container [data-testid="dropdown"] label {
    pointer-events: auto !important;
}
.gradio-container [data-testid="dropdown"] ul,
.gradio-container [data-testid="dropdown"] [role="listbox"] {
    z-index: 60 !important;
}
.file-container {
    position: relative;
    z-index: 1;
}
.full-send-btn button {
    min-height: 52px;
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: 0.01em;
    background: linear-gradient(135deg, var(--dp-primary), #138779) !important;
    border: none !important;
    box-shadow: 0 14px 34px rgba(13, 107, 98, 0.22);
}
.full-send-btn button:hover {
    background: linear-gradient(135deg, var(--dp-primary-strong), var(--dp-primary)) !important;
}
.chat-shell {
    margin-bottom: 10px;
}
.chat-container {
    border: 1px solid var(--dp-border);
    border-radius: 18px;
    overflow: hidden;
    background:
        linear-gradient(180deg, rgba(255,255,255,0.90), rgba(242, 247, 249, 0.88));
}
.chat-container {
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.7);
}
.token-display {
    line-height: 1.6;
    padding: 6px 2px;
}
.preview-status {
    min-height: 72px;
    padding: 14px 16px;
    border: 1px solid var(--dp-border);
    border-radius: 18px;
    background: var(--dp-status-bg);
    color: var(--dp-text);
    font-weight: 500;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.7);
}
.preview-status p {
    margin: 0;
    color: var(--dp-text) !important;
}
.result-toolbar {
    gap: 12px;
    align-items: stretch;
    margin-bottom: 14px;
}
.download-shell {
    min-width: 0;
}
.download-card {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 14px;
    min-height: 72px;
    padding: 14px 16px;
    border-radius: 18px;
    border: 1px solid rgba(13, 107, 98, 0.12);
    background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(230, 245, 241, 0.84));
}
.download-card.is-empty {
    border-style: dashed;
    background: linear-gradient(180deg, rgba(255,255,255,0.92), rgba(241, 246, 248, 0.85));
}
.download-copy {
    min-width: 0;
}
.download-copy strong,
.download-copy span,
.download-copy p {
    display: block;
}
.download-copy strong {
    font-size: 1rem;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}
.download-copy p {
    margin: 3px 0 0 0;
    color: var(--dp-muted);
    font-size: 0.86rem;
}
.download-kicker {
    margin-bottom: 4px;
    color: var(--dp-primary-strong);
    font-size: 0.74rem;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.download-actions {
    display: flex;
    align-items: center;
    gap: 8px;
    flex-wrap: wrap;
    justify-content: flex-end;
}
.download-link {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-height: 42px;
    padding: 0 14px;
    border-radius: 999px;
    text-decoration: none !important;
    font-weight: 700;
    transition: transform 0.18s ease, background 0.18s ease, border-color 0.18s ease;
}
.download-link.primary {
    background: var(--dp-primary);
    color: #ffffff !important;
    box-shadow: 0 12px 28px rgba(13, 107, 98, 0.18);
}
.download-link.primary:hover {
    background: var(--dp-primary-strong);
    transform: translateY(-1px);
}
.download-link.secondary {
    border: 1px solid rgba(22, 37, 52, 0.12);
    background: rgba(255, 255, 255, 0.70);
    color: var(--dp-text) !important;
}
.download-link.secondary:hover {
    background: #ffffff;
    transform: translateY(-1px);
}
.download-link.disabled {
    background: #e7edf2;
    color: #768492 !important;
    pointer-events: none;
}
.dep-check-panel {
    margin-top: 8px;
    border: 1px dashed #c8d8e8;
    border-radius: 10px;
    background: #f6fbff;
    padding: 8px 10px;
}
.dep-check-panel p {
    margin: 0;
}
.dep-refresh-btn button {
    border-color: #c5d5e5 !important;
    background: #edf4fb !important;
    color: #17334d !important;
}
.preview-gallery {
    border: 1px solid var(--dp-border);
    border-radius: 18px;
    overflow: hidden;
    min-height: var(--dp-preview-height-desktop);
    background: rgba(255, 255, 255, 0.76);
}
.preview-tabs [role="tablist"] {
    background: rgba(255, 255, 255, 0.72);
    border: 1px solid var(--dp-border);
    border-radius: 14px;
    padding: 5px;
}
.preview-tabs button[role="tab"] {
    color: #1f3850 !important;
    background: rgba(232, 240, 248, 0.92) !important;
    border: 1px solid #cfdeec !important;
    border-radius: 10px !important;
    font-weight: 600;
}
.preview-tabs button[role="tab"][aria-selected="true"] {
    color: #ffffff !important;
    background: var(--dp-primary) !important;
    border-color: var(--dp-primary-strong) !important;
}
.preview-tabs button[role="tab"]:hover {
    color: #102a42 !important;
    background: #dce9f6 !important;
}
.pdf-preview-shell {
    width: 100%;
    min-height: var(--dp-preview-height-desktop);
    border: 1px solid var(--dp-border);
    border-radius: 18px;
    overflow: hidden;
    background: #fff;
}
.pdf-preview-shell iframe {
    width: 100%;
    min-height: var(--dp-preview-height-desktop);
    border: 0;
    display: block;
}
footer,
.gradio-container .footer {
    display: none !important;
}
@keyframes rise-in {
    from {
        opacity: 0;
        transform: translateY(10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}
@media (max-width: 980px) {
    .gradio-container {
        padding: 10px 10px 16px !important;
    }
    .hero-banner {
        grid-template-columns: 1fr;
        padding: 18px;
    }
    .panel-card {
        padding: 12px;
    }
    .panel-note-strip {
        grid-template-columns: 1fr;
    }
    .result-panel {
        position: static;
    }
    .result-toolbar,
    .download-card {
        flex-direction: column;
        align-items: stretch;
    }
    .download-actions {
        justify-content: stretch;
    }
    .download-link {
        width: 100%;
    }
    .preview-gallery {
        min-height: var(--dp-preview-height-mobile);
    }
    .pdf-preview-shell,
    .pdf-preview-shell iframe {
        min-height: var(--dp-preview-height-mobile);
    }
}
"""

# Server-side session storage for reconnection support
_sessions: dict[str, "UserSession"] = {}
_session_lock = asyncio.Lock()
_SESSION_TTL = 2 * 60 * 60  # 2 hours
_last_loaded_session: "UserSession | None" = None

_MODIFICATION_RE = re.compile(
    r"(修改|改一下|把.*改成|替换|更新|调整|重新生成|重做)"
    r".*?"
    r"(第\s*(\d+)\s*页|(\d+)\s*页|那[个一]页|这[个一]页|前一页|后一页)",
    re.IGNORECASE,
)


def _detect_modification_request(message: str) -> list[int] | None:
    """Detect if the user message is a modification request targeting specific pages.

    Returns a list of 0-based page indices, or None if not a modification request.
    """
    if not message:
        return None
    matches = list(_MODIFICATION_RE.finditer(message))
    if not matches:
        return None
    pages = []
    for m in matches:
        num_str = m.group(3) or m.group(4)
        if num_str:
            pages.append(int(num_str) - 1)  # Convert to 0-based
    return pages if pages else None


def _find_latest_cache(workspace: Path) -> Path | None:
    """Find the most recent .cache.json file in the workspace."""
    cache_files = list(workspace.glob("**/*.cache.json"))
    if not cache_files:
        return None
    return max(cache_files, key=lambda f: f.stat().st_mtime)


class UserSession:
    """简化的用户会话类"""

    def __init__(self, workspace: str = "", session_id: str | None = None):
        runtime_config = load_runtime_config()
        self.session_id = session_id or f"{datetime.now().strftime('%Y%m%d')}/{uuid.uuid4().hex[:8]}"
        ws = Path(workspace) if workspace.strip() else None
        self.loop = AgentLoop(
            config=runtime_config,
            session_id=self.session_id,
            workspace=ws,
        )
        self.created_time = time.time()
        self.last_active = time.time()
        self.chat_history: list[dict] = []
        # Session metadata for history
        self.instruction: str = ""
        self.template: str = ""
        self.num_pages: int | None = None
        self.convert_type: str = ""
        self.status: str = "active"  # active, completed, failed

    def touch(self):
        """Update last activity timestamp."""
        self.last_active = time.time()

    @property
    def _sessions_dir(self) -> Path:
        """Return the sessions directory for this workspace."""
        return self.loop.workspace / ".sessions"

    @property
    def _session_dir(self) -> Path:
        """Return this session's storage directory."""
        return self._sessions_dir / self.session_id.replace("/", "_")

    def save(self):
        """Save session data to disk."""
        session_dir = self._session_dir
        session_dir.mkdir(parents=True, exist_ok=True)

        # Save session metadata
        meta = {
            "session_id": self.session_id,
            "created_at": datetime.fromtimestamp(self.created_time).isoformat(),
            "last_active": datetime.fromtimestamp(self.last_active).isoformat(),
            "instruction": self.instruction,
            "template": self.template,
            "num_pages": self.num_pages,
            "convert_type": self.convert_type,
            "status": self.status,
            "slide_count": len(self.chat_history),
            "workspace": str(self.loop.workspace),
        }
        (session_dir / "session.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # Save chat history
        with jsonlines.open(session_dir / "chat_history.jsonl", mode="w") as writer:
            for msg in self.chat_history:
                writer.write(msg)

    @classmethod
    def load(cls, workspace: Path, session_id: str) -> "UserSession | None":
        """Load a session from disk."""
        session_dir = workspace / ".sessions" / session_id.replace("/", "_")
        meta_file = session_dir / "session.json"
        if not meta_file.exists():
            return None

        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            session = cls(
                workspace=meta.get("workspace", str(workspace)),
                session_id=meta.get("session_id", session_id),
            )
            session.instruction = meta.get("instruction", "")
            session.template = meta.get("template", "")
            session.num_pages = meta.get("num_pages")
            session.convert_type = meta.get("convert_type", "")
            session.status = meta.get("status", "active")
            session.created_time = datetime.fromisoformat(meta["created_at"]).timestamp()
            session.last_active = datetime.fromisoformat(meta["last_active"]).timestamp()

            # Load chat history
            history_file = session_dir / "chat_history.jsonl"
            if history_file.exists():
                with jsonlines.open(history_file) as reader:
                    session.chat_history = list(reader)

            return session
        except Exception:
            return None

    @staticmethod
    def list_sessions(workspace: Path) -> list[dict]:
        """List all sessions in a workspace, sorted by last_active desc."""
        sessions_dir = workspace / ".sessions"
        if not sessions_dir.exists():
            return []

        sessions = []
        for session_file in sessions_dir.glob("*/session.json"):
            try:
                meta = json.loads(session_file.read_text(encoding="utf-8"))
                sessions.append(meta)
            except Exception:
                continue

        sessions.sort(key=lambda s: s.get("last_active", ""), reverse=True)
        return sessions


async def get_or_create_session(workspace: str, cookie_session_id: str | None) -> UserSession:
    """Get existing session by cookie ID or create a new one."""
    global _last_loaded_session
    async with _session_lock:
        # Clean expired sessions
        now = time.time()
        expired = [sid for sid, s in _sessions.items() if now - s.last_active > _SESSION_TTL]
        for sid in expired:
            del _sessions[sid]

        # Check if a session was just loaded from history
        if _last_loaded_session is not None:
            session = _last_loaded_session
            _last_loaded_session = None
            _sessions[session.session_id] = session
            session.touch()
            return session

        # Try to reuse existing session
        if cookie_session_id and cookie_session_id in _sessions:
            session = _sessions[cookie_session_id]
            session.touch()
            return session

        # Create new session
        session = UserSession(workspace=workspace)
        _sessions[session.session_id] = session
        return session


class ChatDemo:
    def create_interface(self):
        """创建 Gradio 界面"""
        def format_file_size(path: Path) -> str:
            size = float(path.stat().st_size)
            units = ["B", "KB", "MB", "GB"]
            for unit in units:
                if size < 1024 or unit == units[-1]:
                    return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} {unit}"
                size /= 1024
            return f"{int(path.stat().st_size)} B"

        def build_download_card_html(output_path: Path | None = None) -> str:
            if output_path is None or not output_path.exists():
                return (
                    '<div class="download-card is-empty">'
                    '<div class="download-copy">'
                    '<span class="download-kicker">Result</span>'
                    '<strong>结果文件会在这里出现</strong>'
                    '<p>生成完成后可直接下载 PPTX、PDF 或其他导出文件。</p>'
                    "</div>"
                    '<div class="download-actions">'
                    '<span class="download-link disabled">等待生成</span>'
                    "</div>"
                    "</div>"
                )

            safe_name = html.escape(output_path.name)
            file_url = f"/gradio_api/file={quote(str(output_path))}"
            meta = f"{output_path.suffix.lower().lstrip('.') or 'file'} · {format_file_size(output_path)}"
            safe_meta = html.escape(meta.upper())
            return (
                '<div class="download-card">'
                '<div class="download-copy">'
                '<span class="download-kicker">Result</span>'
                f'<strong title="{safe_name}">{safe_name}</strong>'
                f"<p>{safe_meta}</p>"
                "</div>"
                '<div class="download-actions">'
                f'<a class="download-link primary" href="{file_url}" download="{safe_name}">下载文件</a>'
                f'<a class="download-link secondary" href="{file_url}" target="_blank" rel="noopener noreferrer">打开文件</a>'
                "</div>"
                "</div>"
            )

        with gr.Blocks(
            title="DeepPresenter",
            theme=gr.themes.Soft(),
            css=gradio_css,
        ) as demo:
            gr.HTML(
                """
                <section class="hero-banner">
                    <div class="hero-copy">
                        <span class="hero-badge">DeepPresenter Studio</span>
                        <h1>把素材整理成可交付的演示文稿</h1>
                        <p>
                            左侧聚焦需求、模板与附件，右侧持续显示结果、预览和下载入口。
                            适合快速起稿，也适合在上传模板上直接编辑。
                        </p>
                    </div>
                    <div class="hero-side">
                        <div class="metric-pill">
                            <strong>双工作模式</strong>
                            <span>自由生成与模板直编可以按任务切换。</span>
                        </div>
                        <div class="metric-pill">
                            <strong>渐进预览</strong>
                            <span>生成中会自动刷新右侧预览，不必反复下载。</span>
                        </div>
                        <div class="metric-pill">
                            <strong>稳定下载</strong>
                            <span>结果区提供文件直链和打开入口，避免按钮失效。</span>
                        </div>
                    </div>
                </section>
                """
            )

            with gr.Row(elem_classes=["main-layout"]):
                with gr.Column(
                    scale=6,
                    min_width=760,
                    elem_classes=["panel-card", "input-panel"],
                ):
                    gr.HTML(
                        """
                        <div class="section-heading">
                            <span class="section-kicker">Workspace</span>
                            <h3>任务输入</h3>
                            <p>先配置模式、页数和模板，再补充附件与目标描述。</p>
                        </div>
                        """,
                    )
                    gr.HTML(
                        """
                        <div class="panel-note">
                            <div class="panel-note-strip">
                                <div class="note-chip">
                                    <strong>页数控制</strong>
                                    <span>可指定固定页数，也可以让系统自动判断。</span>
                                </div>
                                <div class="note-chip">
                                    <strong>模板工作流</strong>
                                    <span>上传自定义 PPT 后，会优先在原模板上直接编辑。</span>
                                </div>
                                <div class="note-chip">
                                    <strong>附件材料</strong>
                                    <span>PDF、文档和图片会被解析为内容素材参与生成。</span>
                                </div>
                            </div>
                        </div>
                        """,
                    )

                    with gr.Group(elem_classes=["control-shell"]):
                        gr.HTML(
                            """
                            <div class="subsection-title">
                                <strong>项目设定</strong>
                                <span>定义生成模式、页数规模和模板来源。</span>
                            </div>
                            """
                        )
                        with gr.Row(elem_classes=["field-grid"]):
                            pages_dd = gr.Dropdown(
                                label="幻灯片页数 (#pages)",
                                choices=["auto"] + [str(i) for i in range(1, 31)],
                                value="auto",
                                scale=1,
                            )
                            convert_type_dd = gr.Dropdown(
                                label="输出类型 (output type)",
                                choices=list(CONVERT_MAPPING),
                                value=list(CONVERT_MAPPING)[0],
                                scale=1,
                            )
                        with gr.Row(
                            elem_classes=["field-row-tight", "template-row"],
                        ) as template_row:
                            template_choices = PPTAgentServer.list_templates()
                            template_dd = gr.Radio(
                                label="选择模板 (template)",
                                choices=["auto"] + template_choices,
                                value="auto",
                                info="仅在模板模式下生效；自由生成模式下会忽略此项。",
                                interactive=True,
                                elem_classes=["template-dropdown"],
                            )
                        enable_search_cb = gr.Checkbox(
                            label="开启联网搜索",
                            value=True,
                            info="关闭后仅使用附件和本地工作区材料，不再调用网页、图片或论文搜索。",
                            elem_classes=["search-toggle-wrap"],
                        )
                        custom_template_input = gr.File(
                            label="上传自定义模板 (.pptx，可选，按原模板直接编辑)",
                            file_count="single",
                            file_types=[".pptx"],
                            type="filepath",
                            visible=False,
                        )
                        attachments_input = gr.File(
                            label="附件 (可多选)",
                            file_count="multiple",
                            type="filepath",
                            elem_classes=["file-container"],
                        )
                        workspace_input = gr.Textbox(
                            label="工作区路径 (workspace)",
                            value="",
                            placeholder=f"留空使用默认路径 ({WORKSPACE_BASE})",
                            info="自定义生成文件的存储目录，留空则使用环境变量 DEEPPRESENTER_WORKSPACE_BASE 或默认 /tmp",
                        )

                    with gr.Accordion("📜 历史会话", open=False):
                        session_dd = gr.Dropdown(
                            label="选择会话",
                            choices=[],
                            value=None,
                            info="选择一个历史会话加载",
                        )
                        with gr.Row():
                            refresh_sessions_btn = gr.Button(
                                "刷新列表", size="sm", scale=1
                            )
                            load_session_btn = gr.Button(
                                "加载选中会话",
                                size="sm",
                                variant="primary",
                                scale=1,
                                interactive=False,
                            )

                    with gr.Group(elem_classes=["composer-shell"]):
                        gr.HTML(
                            """
                            <div class="subsection-title">
                                <strong>需求描述</strong>
                                <span>明确受众、目标和内容重点，生成质量会更稳定。</span>
                            </div>
                            """
                        )
                        msg_input = gr.Textbox(
                            label="指令",
                            placeholder="例如：生成一份 8 页的项目路演 PPT\n或：把第 3 页的标题改成 Hello World\n或：修改第 5 页，增加数据图表",
                            lines=4,
                            max_lines=8,
                        )
                        send_btn = gr.Button(
                            "生成并刷新预览",
                            variant="primary",
                            elem_classes=["full-send-btn"],
                        )
                        cancel_btn = gr.Button(
                            "停止生成",
                            variant="stop",
                            visible=True,
                        )
                        loop_state = gr.State(None)
                        # JavaScript to persist session_id in cookie for reconnection
                        session_cookie_js = """
                        <script>
                        (function() {
                            var match = document.cookie.match(/dp_session_id=([^;]+)/);
                            if (!match) {
                                var sid = Date.now().toString(36) + Math.random().toString(36).slice(2);
                                document.cookie = 'dp_session_id=' + sid + ';path=/;max-age=7200';
                            }
                        })();
                        </script>
                        """
                        session_cookie = gr.HTML(value=session_cookie_js, visible=False)

                    with gr.Accordion("📊 Token 使用统计", open=False):
                        token_display = gr.Markdown(
                            value="暂无数据",
                            elem_classes=["token-display"],
                        )

                    with gr.Group(elem_classes=["log-shell"]):
                        gr.HTML(
                            """
                            <div class="subsection-title chat-shell">
                                <strong>执行轨迹</strong>
                                <span>显示代理消息、工具调用和生成过程，便于排查问题。</span>
                            </div>
                            """
                        )
                        chatbot = gr.Chatbot(
                            value=[],
                            height=560,
                            show_label=False,
                            type="messages",
                            render_markdown=True,
                            elem_classes=["chat-container"],
                        )
                        with gr.Accordion("📋 系统日志", open=False):
                            log_display = gr.Code(
                                value="",
                                language=None,
                                label="",
                                lines=12,
                                interactive=False,
                                elem_classes=["log-code-block"],
                            )
                            log_refresh_btn = gr.Button(
                                "刷新日志",
                                size="sm",
                                variant="secondary",
                            )

                with gr.Column(
                    scale=4,
                    min_width=460,
                    elem_classes=["panel-card", "result-panel"],
                ):
                    gr.HTML(
                        """
                        <div class="section-heading">
                            <span class="section-kicker">Output</span>
                            <h3>结果与预览</h3>
                            <p>生成完成后，这里会持续显示状态、预览和下载入口。</p>
                        </div>
                        """
                    )
                    with gr.Row(elem_classes=["result-toolbar"]):
                        with gr.Column(scale=5, min_width=280):
                            preview_status = gr.Markdown(
                                value="等待任务开始。生成完成后会自动显示预览。",
                                elem_classes=["preview-status"],
                            )
                        with gr.Column(scale=4, min_width=260):
                            download_card_html = gr.HTML(
                                value=build_download_card_html(),
                                elem_classes=["download-shell"],
                            )
                    with gr.Tabs(elem_classes=["preview-tabs"]):
                        with gr.Tab("幻灯片预览"):
                            preview_gallery = gr.Gallery(
                                value=[],
                                label="PPT 页面预览",
                                columns=1,
                                height=700,
                                object_fit="contain",
                                visible=False,
                                elem_classes=["preview-gallery"],
                            )
                        with gr.Tab("PDF预览"):
                            pdf_preview_html = gr.HTML(
                                value="",
                                visible=False,
                            )

            def _toggle_template_visibility(v: str):
                show_template = "模版" in v
                return gr.update(visible=show_template)

            convert_type_dd.change(
                _toggle_template_visibility,
                inputs=[convert_type_dd],
                outputs=[custom_template_input],
            )

            def collect_token_stats(loop: AgentLoop) -> str:
                """收集所有 agents 的 token 统计并生成显示文本"""
                all_agent_costs = {}

                if hasattr(loop, "research_agent") and loop.research_agent:
                    all_agent_costs["Research Agent"] = {
                        "prompt": getattr(loop.research_agent.cost, "prompt", 0),
                        "completion": getattr(
                            loop.research_agent.cost, "completion", 0
                        ),
                        "total": getattr(loop.research_agent.cost, "total", 0),
                        "model": loop.config.research_agent.model_name,
                    }

                if hasattr(loop, "designagent") and loop.designagent:
                    all_agent_costs["Design Agent"] = {
                        "prompt": getattr(loop.designagent.cost, "prompt", 0),
                        "completion": getattr(loop.designagent.cost, "completion", 0),
                        "total": getattr(loop.designagent.cost, "total", 0),
                        "model": loop.config.design_agent.model_name,
                    }
                elif hasattr(loop, "pptagent") and loop.pptagent:
                    all_agent_costs["PPT Agent"] = {
                        "prompt": getattr(loop.pptagent.cost, "prompt", 0),
                        "completion": getattr(loop.pptagent.cost, "completion", 0),
                        "total": getattr(loop.pptagent.cost, "total", 0),
                        "model": loop.config.research_agent.model_name,
                    }

                token_lines = ["## Token 使用统计\n"]
                total_prompt = 0
                total_completion = 0
                total_all = 0

                for agent_name, cost_info in all_agent_costs.items():
                    prompt = cost_info.get("prompt", 0)
                    completion = cost_info.get("completion", 0)
                    total = cost_info.get("total", 0)
                    model = cost_info.get("model", "N/A")
                    total_prompt += prompt
                    total_completion += completion
                    total_all += total

                    token_lines.append(
                        f"**{agent_name}** (Model: `{model}`)  \n"
                        f"- 输入: {prompt:,} tokens  \n"
                        f"- 输出: {completion:,} tokens  \n"
                        f"- 小计: {total:,} tokens  \n"
                    )

                if total_all > 0:
                    token_lines.append("\n---\n")
                    token_lines.append(
                        f"**总计**  \n"
                        f"- 输入: {total_prompt:,} tokens  \n"
                        f"- 输出: {total_completion:,} tokens  \n"
                        f"- **总计: {total_all:,} tokens**"
                    )

                return "\n".join(token_lines) if total_all > 0 else "暂无 token 数据"

            def build_pdf_preview_html(pdf_path: Path) -> str:
                pdf_url = f"/gradio_api/file={quote(str(pdf_path))}"
                return (
                    '<div class="pdf-preview-shell">'
                    f'<iframe src="{pdf_url}#toolbar=1&navpanes=0&scrollbar=1" '
                    'title="Generated PDF Preview"></iframe>'
                    "</div>"
                )

            def read_workspace_log(loop: AgentLoop, max_lines: int = 200) -> str:
                """Read the last N lines from the workspace log file."""
                log_file = loop.workspace / ".history" / "deeppresenter-loop.log"
                if not log_file.exists():
                    return "日志文件尚未生成。"
                try:
                    lines = log_file.read_text(encoding="utf-8").splitlines()
                    if len(lines) > max_lines:
                        lines = lines[-max_lines:]
                    return "\n".join(lines)
                except Exception as e:
                    return f"读取日志失败：{e}"

            async def prepare_preview_updates(
                output_path: Path, workspace: Path
            ) -> tuple[dict, dict, dict]:
                output_path = output_path.resolve()

                if not output_path.exists():
                    return (
                        gr.update(value=f"⚠️ 文件不存在：`{output_path}`"),
                        gr.update(value=[], visible=False),
                        gr.update(value="", visible=False),
                    )

                suffix = output_path.suffix.lower()
                if suffix == ".pdf":
                    return (
                        gr.update(value="✅ 已完成生成并加载 PDF 在线预览。"),
                        gr.update(value=[], visible=False),
                        gr.update(value=build_pdf_preview_html(output_path), visible=True),
                    )

                if suffix == ".pptx":
                    fallback_pdf = output_path.with_suffix(".pdf")
                    dep_status = detect_ppt_preview_dependencies()
                    if not dep_status["can_ppt_image_preview"]:
                        if fallback_pdf.exists():
                            return (
                                gr.update(
                                    value=(
                                        "⚠️ "
                                        f"{dep_status['failure_reason']}，"
                                        "幻灯片图片预览不可用，已自动切换到 PDF 预览。"
                                    )
                                ),
                                gr.update(value=[], visible=False),
                                gr.update(
                                    value=build_pdf_preview_html(fallback_pdf),
                                    visible=True,
                                ),
                            )
                        return (
                            gr.update(
                                value=(
                                    "⚠️ "
                                    f"{dep_status['failure_reason']}。"
                                    "请安装 LibreOffice（提供 `soffice`）或启用 unoserver。"
                                )
                            ),
                            gr.update(value=[], visible=False),
                            gr.update(value="", visible=False),
                        )

                    try:
                        stat = output_path.stat()
                        cache_key = f"{output_path.stem}_{int(stat.st_mtime)}_{stat.st_size}"
                        preview_dir = (
                            workspace
                            / ".preview"
                            / cache_key
                        )
                        preview_dir.mkdir(parents=True, exist_ok=True)
                        await ppt_to_images(
                            str(output_path),
                            str(preview_dir),
                            dpi=120,
                        )
                        slide_images = sorted(preview_dir.glob("slide_*.jpg"))
                        if not slide_images:
                            raise RuntimeError("未生成可预览图片")

                        gallery_items = [
                            (str(img_path), f"第 {idx} 页")
                            for idx, img_path in enumerate(slide_images, start=1)
                        ]
                        return (
                            gr.update(
                                value=f"✅ 已生成 {len(gallery_items)} 页在线预览，右侧可逐页查看。"
                            ),
                            gr.update(value=gallery_items, visible=True),
                            gr.update(value="", visible=False),
                        )
                    except Exception as exc:
                        dep_status = detect_ppt_preview_dependencies()
                        missing_dep = (
                            MISSING_PPT_PREVIEW_DEP_MSG in str(exc)
                            or (not dep_status["can_ppt_image_preview"])
                        )
                        if fallback_pdf.exists():
                            return (
                                gr.update(
                                    value=(
                                        "⚠️ "
                                        f"{dep_status['failure_reason']}，"
                                        "幻灯片图片预览不可用，已切换到 PDF 预览。"
                                        if missing_dep
                                        else (
                                            "⚠️ PPT 图片预览生成失败，已切换到 PDF 预览。"
                                            f"\n\n错误信息：`{exc}`"
                                        )
                                    )
                                ),
                                gr.update(value=[], visible=False),
                                gr.update(
                                    value=build_pdf_preview_html(fallback_pdf),
                                    visible=True,
                                ),
                            )
                        logger.warning(
                            f"Failed to build PPT preview for {output_path}: {exc}"
                        )
                        return (
                            gr.update(
                                value=(
                                    f"⚠️ {dep_status['failure_reason']}，无法生成幻灯片图片预览。"
                                    if missing_dep
                                    else f"⚠️ PPT 预览生成失败：`{exc}`。可先下载文件查看。"
                                )
                            ),
                            gr.update(value=[], visible=False),
                            gr.update(value="", visible=False),
                        )

                return (
                    gr.update(
                        value=f"⚠️ 文件已生成（`{suffix or 'unknown'}`），暂不支持在线预览。"
                    ),
                    gr.update(value=[], visible=False),
                    gr.update(value="", visible=False),
                )

            def resolve_download_output_path(
                output_path: Path, workspace: Path
            ) -> Path:
                """Prefer non-preview pptx as downloadable artifact."""
                if (
                    output_path.name == LIVE_PREVIEW_PPTX_REL_PATH.name
                    and output_path.parent.name == LIVE_PREVIEW_PPTX_REL_PATH.parent.name
                ):
                    candidates = sorted(
                        workspace.glob("*.pptx"),
                        key=lambda p: p.stat().st_mtime,
                        reverse=True,
                    )
                    if candidates:
                        return candidates[0]
                return output_path

            def parse_tool_result_payload(tool_text: str) -> dict | None:
                """Parse tool text result as JSON object when possible."""
                if not tool_text:
                    return None
                raw = tool_text.strip()
                if not raw:
                    return None
                try:
                    parsed = json.loads(raw)
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    pass
                start = raw.find("{")
                end = raw.rfind("}")
                if start == -1 or end <= start:
                    return None
                try:
                    parsed = json.loads(raw[start : end + 1])
                    return parsed if isinstance(parsed, dict) else None
                except json.JSONDecodeError:
                    return None

            async def prepare_freeform_preview_updates(
                workspace: Path,
            ) -> tuple[dict, dict, dict, int]:
                """Build incremental preview from generated slide HTML files."""
                slides_dir = workspace / "slides"
                html_files = sorted(slides_dir.glob("slide_*.html"))
                if not html_files:
                    return (
                        gr.update(),
                        gr.update(),
                        gr.update(),
                        0,
                    )

                page_cache_dir = workspace / ".preview" / "freeform_pages"
                page_cache_dir.mkdir(parents=True, exist_ok=True)

                # Build cache key for each HTML file; find pages needing render
                pages_to_render = []  # (html_file, cache_key)
                page_cache_keys = []  # ordered cache keys for all pages
                for html_file in html_files:
                    stat = html_file.stat()
                    cache_key = f"{html_file.stem}_{int(stat.st_mtime)}_{stat.st_size}"
                    page_cache_keys.append(cache_key)
                    cached_jpg = page_cache_dir / f"{cache_key}.jpg"
                    if not cached_jpg.exists():
                        pages_to_render.append((html_file, cache_key))

                # Only render new/changed pages
                if pages_to_render:
                    try:
                        async with PlaywrightConverter() as converter:
                            for html_file, cache_key in pages_to_render:
                                page_pdf = page_cache_dir / f"{cache_key}.pdf"
                                await converter.convert_single_html(
                                    html_file, page_pdf, aspect_ratio="16:9"
                                )
                                images = convert_from_path(str(page_pdf), dpi=100)
                                if images:
                                    images[0].save(
                                        str(page_cache_dir / f"{cache_key}.jpg")
                                    )
                    except Exception as exc:
                        logger.warning(
                            f"Failed to render new HTML pages: {exc}"
                        )

                # Collect all cached page images in order
                slide_images = []
                for cache_key in page_cache_keys:
                    cached_jpg = page_cache_dir / f"{cache_key}.jpg"
                    if cached_jpg.exists():
                        slide_images.append(cached_jpg)

                if not slide_images:
                    return (
                        gr.update(),
                        gr.update(),
                        gr.update(),
                        len(html_files),
                    )

                gallery_items = [
                    (str(img_path), f"第 {idx} 页")
                    for idx, img_path in enumerate(slide_images, start=1)
                ]
                return (
                    gr.update(
                        value=f"✅ 已生成 {len(gallery_items)} 页在线预览（逐页更新中）。"
                    ),
                    gr.update(value=gallery_items, visible=True),
                    gr.update(value="", visible=False),
                    len(html_files),
                )

            async def send_message(
                message,
                history,
                attachments,
                convert_type_value,
                template_value,
                custom_template_path,
                num_pages_value,
                enable_search_value,
                workspace_value,
                request: gr.Request,
            ):
                # Get session from cookie or create new one
                cookie_session_id = request.cookies.get("dp_session_id") if request.cookies else None
                user_session = await get_or_create_session(workspace_value, cookie_session_id)

                # Restore history if reconnecting and chatbot is empty
                if not history and user_session.chat_history:
                    history = list(user_session.chat_history)

                has_message = bool(message and message.strip())
                has_attachments = bool(attachments)
                if not has_message and not has_attachments:
                    yield (
                        history,
                        message,
                        gr.update(value=None),
                        gr.update(value=build_download_card_html()),
                        gr.update(),
                        gr.update(),
                        gr.update(),
                        gr.update(),
                        None,
                    )
                    return

                history.append(
                    {"role": "user", "content": message or "请根据上传的附件制作 PPT"}
                )

                aggregated_parts: list[str] = []
                history.append({"role": "assistant", "content": ""})

                loop = user_session.loop

                selected_convert_type = CONVERT_MAPPING[convert_type_value]
                selected_num_pages = (
                    None if num_pages_value == "auto" else int(num_pages_value)
                )
                if template_value == "auto":
                    template_value = None
                extra_info: dict[str, object] = {
                    "enable_search": bool(enable_search_value),
                }
                if not enable_search_value:
                    aggregated_parts.append("已关闭联网搜索，将仅基于附件和本地材料生成内容。")
                if (
                    selected_convert_type == ConvertType.PPTAGENT
                    and custom_template_path
                ):
                    try:
                        prepared_template = prepare_uploaded_template(
                            custom_template_path,
                            loop.workspace,
                        )
                    except TemplatePreparationError as exc:
                        history[-1]["content"] = f"模板处理失败：{exc}"
                        yield (
                            history,
                            message,
                            gr.update(value=None),
                            gr.update(value=build_download_card_html()),
                            gr.update(value="暂无数据"),
                            gr.update(value="⚠️ 自定义模板处理失败。"),
                            gr.update(value=[], visible=False),
                            gr.update(value="", visible=False),
                            None,
                        )
                        return

                    template_value = prepared_template.template_name
                    aggregated_parts.append(f"已加载自定义模板：`{template_value}`")
                    aggregated_parts.append(
                        "将按上传 PPT 的原页顺序直接编辑，未暴露为可编辑布局的页面将保持原样。"
                    )
                    for warning_msg in prepared_template.warnings:
                        aggregated_parts.append(f"[模板告警] {warning_msg}")
                    extra_info.update({
                        "pptagent_direct_edit": True,
                        "template_slide_count": prepared_template.total_slide_count,
                        "editable_template_layout_names": prepared_template.editable_layout_names,
                        "preserved_template_slide_indices": prepared_template.preserved_slide_indices,
                    })

                # Save session metadata
                user_session.instruction = message or "请根据上传的附件制作 PPT"
                user_session.template = template_value or "auto"
                user_session.num_pages = selected_num_pages
                user_session.convert_type = convert_type_value
                user_session.save()

                # Detect modification request for incremental generation
                modification_pages = _detect_modification_request(message or "")
                if modification_pages is not None:
                    cache_file = _find_latest_cache(loop.workspace)
                    if cache_file is not None:
                        extra_info["incremental_cache_path"] = str(cache_file)
                        extra_info["incremental_pages"] = modification_pages
                        aggregated_parts.append(
                            f"🔄 检测到修改请求（第 {', '.join(str(p + 1) for p in modification_pages)} 页），"
                            f"将使用增量生成模式复用已有缓存。"
                        )

                last_live_preview_mtime: float | None = None
                last_freeform_html_count = 0

                # Background preview task state
                _preview_task: asyncio.Task | None = None
                _last_preview_result: tuple | None = None

                def _cancel_preview_task():
                    nonlocal _preview_task
                    if _preview_task is not None and not _preview_task.done():
                        _preview_task.cancel()
                    _preview_task = None

                def _start_preview_task(coro):
                    nonlocal _preview_task
                    _cancel_preview_task()
                    _preview_task = asyncio.create_task(coro)

                def _collect_preview_result():
                    nonlocal _preview_task, _last_preview_result
                    if _preview_task is not None and _preview_task.done():
                        try:
                            _last_preview_result = _preview_task.result()
                        except (asyncio.CancelledError, Exception):
                            pass
                        _preview_task = None
                    return _last_preview_result

                yield (
                    history,
                    message,
                    gr.update(),
                    gr.update(value=build_download_card_html()),
                    gr.update(),
                    gr.update(value="⏳ 正在生成内容，请稍候..."),
                    gr.update(value=[], visible=False),
                    gr.update(value="", visible=False),
                    loop,
                )

                stream = loop.run(
                    InputRequest(
                        instruction=message or "请根据上传的附件制作 PPT",
                        template=template_value,
                        attachments=attachments or [],
                        num_pages=str(selected_num_pages),
                        convert_type=selected_convert_type,
                        extra_info=extra_info,
                    )
                )
                next_msg_task: asyncio.Task | None = asyncio.create_task(anext(stream))
                while True:
                    # Check for preview updates (non-blocking)
                    if selected_convert_type == ConvertType.PPTAGENT:
                        candidate_path = loop.workspace / LIVE_PREVIEW_PPTX_REL_PATH
                        if candidate_path.exists():
                            current_mtime = candidate_path.stat().st_mtime
                            if (
                                last_live_preview_mtime is None
                                or current_mtime > last_live_preview_mtime
                            ):
                                last_live_preview_mtime = current_mtime
                                _start_preview_task(
                                    prepare_preview_updates(
                                        candidate_path, loop.workspace
                                    )
                                )
                    elif selected_convert_type == ConvertType.DEEPPRESENTER:
                        slide_html_count = len(
                            list((loop.workspace / "slides").glob("slide_*.html"))
                        )
                        if slide_html_count > last_freeform_html_count:
                            last_freeform_html_count = slide_html_count
                            _start_preview_task(
                                prepare_freeform_preview_updates(loop.workspace)
                            )

                    result = _collect_preview_result()
                    if result is not None:
                        _last_preview_result = None
                        preview_status_update = gr.update()
                        preview_gallery_update = gr.update()
                        pdf_preview_update = gr.update()
                        if isinstance(result, tuple) and len(result) == 3:
                            preview_status_update, preview_gallery_update, pdf_preview_update = result
                        elif isinstance(result, tuple) and len(result) == 4:
                            preview_status_update, preview_gallery_update, pdf_preview_update, _ = result
                        if (
                            hasattr(preview_gallery_update, "value")
                            and preview_gallery_update.value
                        ):
                            latest_img = preview_gallery_update.value[-1][0]
                            img_url = f"/gradio_api/file={quote(str(latest_img))}"
                            img_markdown = f"![第 {len(preview_gallery_update.value)} 页]({img_url})"
                            history[-1]["content"] = (
                                history[-1].get("content", "").rstrip()
                                + "\n\n" + img_markdown
                            ).strip()
                        token_text = collect_token_stats(loop)
                        yield (
                            history,
                            message,
                            gr.update(value=None),
                            gr.update(),
                            gr.update(value=token_text),
                            preview_status_update,
                            preview_gallery_update,
                            pdf_preview_update,
                            loop,
                        )

                    # Wait for next agent message with timeout for preview checks
                    done, _ = await asyncio.wait({next_msg_task}, timeout=1.0)
                    if not done:
                        continue
                    # Task completed — process result
                    try:
                        yield_msg = next_msg_task.result()
                    except StopAsyncIteration:
                        break
                    except asyncio.CancelledError:
                        _cancel_preview_task()
                        raise
                    next_msg_task = asyncio.create_task(anext(stream))

                    if isinstance(yield_msg, (str, Path)):
                        output_path = Path(yield_msg)
                        if not output_path.is_absolute():
                            output_path = loop.workspace / output_path
                        download_output_path = resolve_download_output_path(
                            output_path, loop.workspace
                        )

                        _cancel_preview_task()
                        (
                            preview_status_update,
                            preview_gallery_update,
                            pdf_preview_update,
                        ) = await prepare_preview_updates(output_path, loop.workspace)

                        file_content = "📄 幻灯片生成完成，右侧可直接预览，并可按需下载文件。"
                        aggregated_parts.append(file_content)
                        aggregated_text = "\n\n".join(aggregated_parts).strip()
                        history[-1]["content"] = aggregated_text

                        token_text = collect_token_stats(loop)

                        yield (
                            history,
                            "",
                            gr.update(value=None),
                            gr.update(value=build_download_card_html(download_output_path)),
                            gr.update(value=token_text),
                            preview_status_update,
                            preview_gallery_update,
                            pdf_preview_update,
                            loop,
                        )

                    elif isinstance(yield_msg, ChatMessage):
                        preview_status_update = gr.update(
                            value="⏳ 正在生成内容，请稍候..."
                        )
                        preview_gallery_update = gr.update()
                        pdf_preview_update = gr.update()
                        if (
                            selected_convert_type == ConvertType.PPTAGENT
                            and yield_msg.role == Role.TOOL
                            and not yield_msg.is_error
                        ):
                            payload = parse_tool_result_payload(yield_msg.text)
                            preview_pptx_path = None
                            if isinstance(payload, dict):
                                preview_pptx_path = payload.get("preview_pptx_path")
                                # Show slide generation progress
                                slide_num = payload.get("slide_number")
                                if slide_num:
                                    if selected_num_pages:
                                        progress_text = (
                                            f"⏳ 正在生成第 {slide_num}/{selected_num_pages} 页..."
                                        )
                                    else:
                                        progress_text = (
                                            f"⏳ 正在生成第 {slide_num} 页..."
                                        )
                                    preview_status_update = gr.update(
                                        value=progress_text
                                    )
                                    history[-1]["content"] = progress_text
                            if not preview_pptx_path:
                                preview_pptx_path = str(
                                    (loop.workspace / LIVE_PREVIEW_PPTX_REL_PATH)
                                )
                            candidate_path = Path(preview_pptx_path)
                            if not candidate_path.is_absolute():
                                candidate_path = loop.workspace / candidate_path
                            if candidate_path.exists():
                                current_mtime = candidate_path.stat().st_mtime
                                if (
                                    last_live_preview_mtime is None
                                    or current_mtime > last_live_preview_mtime
                                ):
                                    last_live_preview_mtime = current_mtime
                                    _start_preview_task(
                                        prepare_preview_updates(
                                            candidate_path, loop.workspace
                                        )
                                    )
                        elif (
                            selected_convert_type == ConvertType.DEEPPRESENTER
                            and yield_msg.role == Role.TOOL
                            and not yield_msg.is_error
                        ):
                            slide_html_count = len(
                                list((loop.workspace / "slides").glob("slide_*.html"))
                            )
                            if slide_html_count > last_freeform_html_count:
                                last_freeform_html_count = slide_html_count
                                if selected_num_pages:
                                    progress_text = (
                                        f"⏳ 正在生成第 {slide_html_count}/{selected_num_pages} 页..."
                                    )
                                else:
                                    progress_text = (
                                        f"⏳ 正在生成第 {slide_html_count} 页..."
                                    )
                                preview_status_update = gr.update(
                                    value=progress_text
                                )
                                history[-1]["content"] = progress_text
                                _start_preview_task(
                                    prepare_freeform_preview_updates(loop.workspace)
                                )

                        role_msg = f"{ROLE_EMOJI[yield_msg.role]} **{str(yield_msg.role).title()} Message**"
                        if yield_msg.text:
                            aggregated_parts.append(role_msg)

                        if yield_msg.text is not None and yield_msg.text.strip():
                            if yield_msg.role == Role.TOOL:
                                aggregated_parts.append(
                                    "```json\n"
                                    + yield_msg.text.replace("\\n", "\n")
                                    + "\n```"
                                )
                            else:
                                aggregated_parts.append(yield_msg.text)

                        if yield_msg.tool_calls:
                            for tool_call in yield_msg.tool_calls:
                                tool_msg = f"{ROLE_EMOJI.get(yield_msg.role, '💬')} **Tool Call: {tool_call.function.name}**"
                                aggregated_parts.append(tool_msg)

                                if hasattr(tool_call.function, "arguments"):
                                    args_str = tool_call.function.arguments
                                    args_msg = f"```json\n{args_str}\n```"
                                    aggregated_parts.append(args_msg)

                        aggregated_text = "\n\n".join(aggregated_parts).strip()
                        history[-1]["content"] = aggregated_text

                        # Save history to session for reconnection
                        user_session.chat_history = list(history)

                        token_text = collect_token_stats(loop)

                        yield (
                            history,
                            message,
                            gr.update(value=None),
                            gr.update(),
                            gr.update(value=token_text),
                            preview_status_update,
                            preview_gallery_update,
                            pdf_preview_update,
                            loop,
                        )

                    else:
                        raise ValueError(
                            f"Unsupported response message type: {type(yield_msg)}"
                        )

                # Final save of history to session
                user_session.chat_history = list(history)
                user_session.status = "completed"
                user_session.save()
                cleanup_preview_dirs(loop.workspace)

            msg_input.submit(
                send_message,
                inputs=[
                    msg_input,
                    chatbot,
                    attachments_input,
                    convert_type_dd,
                    template_dd,
                    custom_template_input,
                    pages_dd,
                    enable_search_cb,
                    workspace_input,
                ],
                outputs=[
                    chatbot,
                    msg_input,
                    attachments_input,
                    download_card_html,
                    token_display,
                    preview_status,
                    preview_gallery,
                    pdf_preview_html,
                    loop_state,
                ],
                concurrency_limit=_MAX_CONCURRENT_SESSIONS,
            )

            send_btn.click(
                send_message,
                inputs=[
                    msg_input,
                    chatbot,
                    attachments_input,
                    convert_type_dd,
                    template_dd,
                    custom_template_input,
                    pages_dd,
                    enable_search_cb,
                    workspace_input,
                ],
                outputs=[
                    chatbot,
                    msg_input,
                    attachments_input,
                    download_card_html,
                    token_display,
                    preview_status,
                    preview_gallery,
                    pdf_preview_html,
                    loop_state,
                ],
                concurrency_limit=_MAX_CONCURRENT_SESSIONS,
            )

            def _on_cancel(current_loop):
                if current_loop is not None:
                    current_loop.cancel()
                    return gr.update(value="⏳ 正在停止...")
                return gr.update()

            cancel_btn.click(
                _on_cancel,
                inputs=[loop_state],
                outputs=[preview_status],
            )

            def _refresh_log(current_loop):
                if current_loop is not None:
                    return read_workspace_log(current_loop)
                return "尚无活跃会话，日志不可用。"

            log_refresh_btn.click(
                _refresh_log,
                inputs=[loop_state],
                outputs=[log_display],
            )

            def _refresh_sessions(workspace):
                ws = Path(workspace.strip()) if workspace.strip() else Path(WORKSPACE_BASE)
                sessions = UserSession.list_sessions(ws)
                if not sessions:
                    return gr.update(choices=[], value=None), gr.update(interactive=False)
                choices = []
                for s in sessions:
                    ts = s.get("last_active", "")[:16].replace("T", " ")
                    label = s.get("instruction", "无描述")[:40]
                    pages = s.get("num_pages", "?")
                    sid = s.get("session_id", "")
                    choices.append((f"[{ts}] {label} ({pages}页)", sid))
                return gr.update(choices=choices, value=None), gr.update(
                    interactive=False
                )

            def _on_session_select(sid):
                return gr.update(interactive=sid is not None)

            session_dd.change(
                _on_session_select,
                inputs=[session_dd],
                outputs=[load_session_btn],
            )

            refresh_sessions_btn.click(
                _refresh_sessions,
                inputs=[workspace_input],
                outputs=[session_dd, load_session_btn],
            )

            def _load_session(session_id, workspace, chatbot_history):
                global _last_loaded_session
                if not session_id:
                    return chatbot_history, gr.update(), gr.update(), gr.update(), gr.update()
                ws = Path(workspace.strip()) if workspace.strip() else Path(WORKSPACE_BASE)
                session = UserSession.load(ws, session_id)
                if session is None:
                    return chatbot_history, gr.update(), gr.update(), gr.update(), gr.update()
                # Store as last loaded so send_message can pick it up
                _last_loaded_session = session
                new_history = list(session.chat_history) if session.chat_history else chatbot_history
                return (
                    new_history,
                    gr.update(value=f"已加载: {session.instruction[:50]}"),
                    gr.update(value=session.template or "auto"),
                    gr.update(value=str(session.num_pages) if session.num_pages else "auto"),
                    gr.update(value=session.convert_type or list(CONVERT_MAPPING)[0]),
                )

            load_session_btn.click(
                _load_session,
                inputs=[session_dd, workspace_input, chatbot],
                outputs=[chatbot, session_dd, template_dd, pages_dd, convert_type_dd],
            )

        return demo


if __name__ == "__main__":
    import atexit
    import warnings

    chat_demo = ChatDemo()
    demo = chat_demo.create_interface()

    warnings.filterwarnings(
        "ignore", category=DeprecationWarning, module="websockets.legacy"
    )
    warnings.filterwarnings(
        "ignore", category=DeprecationWarning, module="uvicorn.protocols.websockets"
    )

    serve_url = "localhost" if len(sys.argv) <= 1 else sys.argv[1]
    serve_port = int(os.getenv("GRADIO_SERVER_PORT", "7861"))
    if len(sys.argv) > 2:
        serve_port = int(sys.argv[2])
    print(f"Please visit http://{serve_url}:{serve_port}")

    def _cleanup_playwright():
        asyncio.get_event_loop().run_until_complete(PlaywrightConverter.shutdown())

    atexit.register(_cleanup_playwright)

    demo.launch(
        debug=True,
        server_name=serve_url,
        server_port=serve_port,
        share=False,
        max_threads=16,
        allowed_paths=[WORKSPACE_BASE, str(Path.home()), "/tmp"],
    )
