import os
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import gradio as gr

from deeppresenter.main import AgentLoop
from deeppresenter.utils.config import DeepPresenterConfig
from deeppresenter.utils.constants import WORKSPACE_BASE
from deeppresenter.utils.log import create_logger
from deeppresenter.utils.typings import ChatMessage, ConvertType, InputRequest, Role
from pptagent import PPTAgentServer
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
    --dp-bg: #f3f7fb;
    --dp-surface: #ffffff;
    --dp-border: #d7e2ed;
    --dp-text: #132436;
    --dp-muted: #5a6a79;
    --dp-primary: #0f7b6d;
    --dp-primary-strong: #0b655a;
    --dp-soft: #eaf8f4;
}
body {
    margin: 0 !important;
    padding: 0 !important;
    font-family: "IBM Plex Sans", "Source Han Sans SC", "Noto Sans SC", "PingFang SC", sans-serif;
    background:
        radial-gradient(circle at 0% 0%, #dceefb 0%, transparent 42%),
        radial-gradient(circle at 100% 0%, #e3f8ef 0%, transparent 35%),
        var(--dp-bg);
}
.gradio-container {
    max-width: 1680px !important;
    padding: 12px 14px 18px !important;
    color: var(--dp-text);
}
.center-title {
    text-align: center;
    margin: 4px 0 2px 0;
}
.center-title h1 {
    margin: 0;
    letter-spacing: 0.5px;
}
.center-subtitle {
    text-align: center;
    margin: 0 0 14px 0;
    color: var(--dp-muted);
    font-size: 0.95rem;
}
.main-layout {
    gap: 14px;
    align-items: stretch;
}
.panel-card {
    background: var(--dp-surface);
    border: 1px solid var(--dp-border);
    border-radius: 16px;
    padding: 14px;
    box-shadow: 0 10px 30px rgba(16, 42, 67, 0.07);
    animation: rise-in 0.35s ease-out both;
}
.result-panel {
    animation-delay: 0.08s;
}
.panel-title h3 {
    margin: 0 0 10px 0;
    color: var(--dp-text);
}
.chat-container {
    border: 1px solid var(--dp-border);
    border-radius: 12px;
    overflow: hidden;
}
.token-display {
    line-height: 1.6;
    padding: 6px 2px;
}
.compose-row {
    align-items: end;
    gap: 8px;
}
.send-btn button {
    background: var(--dp-primary) !important;
    border: none !important;
}
.send-btn button:hover {
    background: var(--dp-primary-strong) !important;
}
.download-btn button {
    border-color: var(--dp-border) !important;
    background: var(--dp-soft) !important;
    color: #0b514b !important;
}
.preview-status {
    min-height: 42px;
    padding: 8px 10px;
    border: 1px solid var(--dp-border);
    border-radius: 10px;
    background: #f8fcff;
}
.preview-gallery {
    border: 1px solid var(--dp-border);
    border-radius: 12px;
    overflow: hidden;
}
.result-path textarea {
    font-size: 12px !important;
}
.pdf-preview-shell {
    width: 100%;
    min-height: 560px;
    border: 1px solid var(--dp-border);
    border-radius: 12px;
    overflow: hidden;
    background: #fff;
}
.pdf-preview-shell iframe {
    width: 100%;
    min-height: 560px;
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
        padding: 8px 8px 12px !important;
    }
    .panel-card {
        padding: 12px;
    }
    .pdf-preview-shell,
    .pdf-preview-shell iframe {
        min-height: 420px;
    }
}
"""


class UserSession:
    """简化的用户会话类"""

    def __init__(self):
        runtime_config = load_runtime_config()
        self.loop = AgentLoop(
            config=runtime_config,
            session_id=f"{datetime.now().strftime('%Y%m%d')}/{uuid.uuid4().hex[:8]}",
        )
        self.created_time = time.time()


class ChatDemo:
    def create_interface(self):
        """创建 Gradio 界面"""
        with gr.Blocks(
            title="DeepPresenter",
            theme=gr.themes.Soft(),
            css=gradio_css,
        ) as demo:
            gr.Markdown(
                "# DeepPresenter",
                elem_classes=["center-title"],
            )
            gr.Markdown(
                "生成完成后会在右侧自动显示预览，无需先下载即可查看。"
                " 左侧用于输入与过程跟踪，右侧用于结果与预览。",
                elem_classes=["center-subtitle"],
            )

            with gr.Row(elem_classes=["main-layout"]):
                with gr.Column(scale=6, min_width=760, elem_classes=["panel-card"]):
                    gr.Markdown("### 对话与配置", elem_classes=["panel-title"])
                    chatbot = gr.Chatbot(
                        value=[],
                        height=480,
                        show_label=False,
                        type="messages",
                        render_markdown=True,
                        elem_classes=["chat-container"],
                    )

                    with gr.Row():
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
                        template_choices = PPTAgentServer.list_templates()
                        template_dd = gr.Dropdown(
                            label="选择模板 (template)",
                            choices=template_choices + ["auto"],
                            value="auto",
                            scale=2,
                            visible=False,
                        )

                    attachments_input = gr.File(
                        label="附件 (可多选)",
                        file_count="multiple",
                        type="filepath",
                        elem_classes=["file-container"],
                    )

                    with gr.Row(elem_classes=["compose-row"]):
                        msg_input = gr.Textbox(
                            label="指令",
                            placeholder="例如：生成一份 8 页的项目路演 PPT，突出问题、方案、商业模式和财务预测",
                            lines=3,
                            max_lines=6,
                            scale=5,
                        )
                        send_btn = gr.Button(
                            "生成并预览",
                            scale=1,
                            variant="primary",
                            elem_classes=["send-btn"],
                        )

                    with gr.Accordion("📊 Token 使用统计", open=False):
                        token_display = gr.Markdown(
                            value="暂无数据",
                            elem_classes=["token-display"],
                        )

                with gr.Column(
                    scale=4,
                    min_width=460,
                    elem_classes=["panel-card", "result-panel"],
                ):
                    gr.Markdown("### 结果与预览", elem_classes=["panel-title"])
                    preview_status = gr.Markdown(
                        value="等待任务开始。生成完成后会自动显示预览。",
                        elem_classes=["preview-status"],
                    )
                    result_file_display = gr.Textbox(
                        label="生成文件路径",
                        value="",
                        placeholder="生成后自动填写",
                        interactive=False,
                        elem_classes=["result-path"],
                    )
                    download_btn = gr.DownloadButton(
                        "📥 下载文件",
                        variant="secondary",
                        elem_classes=["download-btn"],
                    )
                    with gr.Tabs():
                        with gr.Tab("幻灯片预览"):
                            preview_gallery = gr.Gallery(
                                value=[],
                                label="PPT 页面预览",
                                columns=1,
                                height=560,
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
                return gr.update(visible=("模版" in v))

            convert_type_dd.change(
                _toggle_template_visibility,
                inputs=[convert_type_dd],
                outputs=[template_dd],
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

            async def prepare_preview_updates(
                output_path: Path, workspace: Path
            ) -> tuple[dict, dict, dict, dict]:
                output_path = output_path.resolve()
                result_file_update = gr.update(value=str(output_path))

                if not output_path.exists():
                    return (
                        gr.update(value=f"⚠️ 文件不存在：`{output_path}`"),
                        result_file_update,
                        gr.update(value=[], visible=False),
                        gr.update(value="", visible=False),
                    )

                suffix = output_path.suffix.lower()
                if suffix == ".pdf":
                    return (
                        gr.update(value="✅ 已完成生成并加载 PDF 在线预览。"),
                        result_file_update,
                        gr.update(value=[], visible=False),
                        gr.update(value=build_pdf_preview_html(output_path), visible=True),
                    )

                if suffix == ".pptx":
                    try:
                        preview_dir = (
                            workspace
                            / ".preview"
                            / f"{output_path.stem}_{int(time.time() * 1000)}"
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
                            result_file_update,
                            gr.update(value=gallery_items, visible=True),
                            gr.update(value="", visible=False),
                        )
                    except Exception as exc:
                        fallback_pdf = output_path.with_suffix(".pdf")
                        if fallback_pdf.exists():
                            return (
                                gr.update(
                                    value=(
                                        "⚠️ PPT 图片预览生成失败，已切换到 PDF 预览。"
                                        f"\n\n错误信息：`{exc}`"
                                    )
                                ),
                                result_file_update,
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
                                value=f"⚠️ PPT 预览生成失败：`{exc}`。可先下载文件查看。"
                            ),
                            result_file_update,
                            gr.update(value=[], visible=False),
                            gr.update(value="", visible=False),
                        )

                return (
                    gr.update(
                        value=f"⚠️ 文件已生成（`{suffix or 'unknown'}`），暂不支持在线预览。"
                    ),
                    result_file_update,
                    gr.update(value=[], visible=False),
                    gr.update(value="", visible=False),
                )

            async def send_message(
                message,
                history,
                attachments,
                convert_type_value,
                template_value,
                num_pages_value,
                request: gr.Request,
            ):
                user_session = UserSession()

                has_message = bool(message and message.strip())
                has_attachments = bool(attachments)
                if not has_message and not has_attachments:
                    yield (
                        history,
                        message,
                        gr.update(value=None),
                        gr.update(),
                        gr.update(),
                        gr.update(),
                        gr.update(),
                        gr.update(),
                        gr.update(),
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

                yield (
                    history,
                    message,
                    gr.update(),
                    gr.update(),
                    gr.update(),
                    gr.update(value="⏳ 正在生成内容，请稍候..."),
                    gr.update(value=""),
                    gr.update(value=[], visible=False),
                    gr.update(value="", visible=False),
                )

                async for yield_msg in loop.run(
                    InputRequest(
                        instruction=message or "请根据上传的附件制作 PPT",
                        template=template_value,
                        attachments=attachments or [],
                        num_pages=str(selected_num_pages),
                        convert_type=selected_convert_type,
                    )
                ):
                    if isinstance(yield_msg, (str, Path)):
                        output_path = Path(yield_msg)
                        if not output_path.is_absolute():
                            output_path = loop.workspace / output_path

                        (
                            preview_status_update,
                            result_file_update,
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
                            gr.update(value=str(output_path)),
                            gr.update(value=token_text),
                            preview_status_update,
                            result_file_update,
                            preview_gallery_update,
                            pdf_preview_update,
                        )

                    elif isinstance(yield_msg, ChatMessage):
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

                        token_text = collect_token_stats(loop)

                        yield (
                            history,
                            message,
                            gr.update(value=None),
                            gr.update(),
                            gr.update(value=token_text),
                            gr.update(value="⏳ 正在生成内容，请稍候..."),
                            gr.update(),
                            gr.update(),
                            gr.update(),
                        )

                    else:
                        raise ValueError(
                            f"Unsupported response message type: {type(yield_msg)}"
                        )

            msg_input.submit(
                send_message,
                inputs=[
                    msg_input,
                    chatbot,
                    attachments_input,
                    convert_type_dd,
                    template_dd,
                    pages_dd,
                ],
                outputs=[
                    chatbot,
                    msg_input,
                    attachments_input,
                    download_btn,
                    token_display,
                    preview_status,
                    result_file_display,
                    preview_gallery,
                    pdf_preview_html,
                ],
                concurrency_limit=None,
            )

            send_btn.click(
                send_message,
                inputs=[
                    msg_input,
                    chatbot,
                    attachments_input,
                    convert_type_dd,
                    template_dd,
                    pages_dd,
                ],
                outputs=[
                    chatbot,
                    msg_input,
                    attachments_input,
                    download_btn,
                    token_display,
                    preview_status,
                    result_file_display,
                    preview_gallery,
                    pdf_preview_html,
                ],
                concurrency_limit=None,
            )

        return demo


if __name__ == "__main__":
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
    demo.launch(
        debug=True,
        server_name=serve_url,
        server_port=serve_port,
        share=False,
        max_threads=16,
        allowed_paths=[WORKSPACE_BASE],
    )
