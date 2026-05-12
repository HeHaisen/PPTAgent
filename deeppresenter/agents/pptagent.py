from deeppresenter.agents.agent import Agent
from deeppresenter.utils.typings import InputRequest


class PPTAgent(Agent):
    async def loop(self, req: InputRequest, markdown_file: str):
        markdown_content = ""
        try:
            with open(markdown_file, encoding="utf-8") as f:
                markdown_content = f.read()
        except OSError:
            markdown_content = ""
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
