import jsonlines

from deeppresenter.agents.agent import Agent
from deeppresenter.utils.typings import ChatMessage, InputRequest, Role


class PPTAgent(Agent):
    async def loop(self, req: InputRequest, markdown_file: str):
        markdown_content = ""
        try:
            with open(markdown_file, encoding="utf-8") as f:
                markdown_content = f.read()
        except OSError:
            markdown_content = ""

        # Resume: restore chat history from previous run
        if req.extra_info.get("resume"):
            history_file = self.workspace / ".history" / "PPTAgent-history.jsonl"
            if history_file.exists():
                try:
                    with jsonlines.open(history_file) as reader:
                        saved_messages = list(reader)
                    if len(saved_messages) > 1:
                        # Keep new system message, restore the rest
                        restored = []
                        for msg_dict in saved_messages[1:]:
                            restored.append(ChatMessage(**msg_dict))
                        self.chat_history = [self.chat_history[0]] + restored
                        # Append resume instruction
                        self.chat_history.append(ChatMessage(
                            role=Role.SYSTEM,
                            content=(
                                "检测到上次生成中断。请调用 generate_slides_resume 继续生成，"
                                "不要重新生成已有的幻灯片。"
                            ),
                        ))
                except Exception:
                    pass  # If restore fails, start fresh

        while True:
            agent_message = await self.action(
                markdown_file=markdown_file,
                markdown_content=markdown_content,
                prompt=req.pptagent_prompt,
            )
            yield agent_message
            outcome = await self.execute(self.chat_history[-1].tool_calls)
            if isinstance(outcome, list):
                for item in outcome:
                    yield item
            else:
                yield outcome
                break
