import asyncio
import copy
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import logger, stdio_client

from deeppresenter.utils.constants import MCP_CALL_TIMEOUT, MCP_CONNECT_TIMEOUT
from deeppresenter.utils.log import debug, error, exception, warning
from deeppresenter.utils.typings import MCPServer

logger.setLevel("WARNING")


class MCPClient:
    def __init__(self, envs: dict[str, Any]):
        # Initialize session and client objects
        self.sessions: dict[str, ClientSession] = {}
        # for avoid error
        self.task: dict[str, asyncio.Task] = {}
        self.stop_event: dict[str, asyncio.Event] = {}
        self.envs = envs
        self._server_configs: dict[str, MCPServer] = {}  # for reconnection

    async def tool_execute(
        self, server_id: str, tool_name: str, tool_params: dict | None
    ):
        if server_id not in self.sessions:
            raise ValueError(f"Server {server_id} is not connected.")
        try:
            session = self.sessions[server_id]
            result = await asyncio.wait_for(
                session.call_tool(tool_name, tool_params), MCP_CALL_TIMEOUT
            )
            return result
        except (BrokenPipeError, ConnectionError, OSError, EOFError) as e:
            warning(f"Server {server_id} connection lost ({e}), attempting reconnect...")
            await self._reconnect_server(server_id)
            session = self.sessions[server_id]
            result = await asyncio.wait_for(
                session.call_tool(tool_name, tool_params), MCP_CALL_TIMEOUT
            )
            return result

    async def _reconnect_server(self, server_id: str):
        """Reconnect a crashed MCP server."""
        config = self._server_configs.get(server_id)
        if config is None:
            raise ValueError(f"No config stored for server {server_id}, cannot reconnect.")
        try:
            await self._close_server(server_id)
        except Exception:
            pass
        await self.connect_server(server_id, config)
        debug(f"Reconnected to server {server_id}")

    async def connect_server(self, server_id: str, config: MCPServer):
        """Connect to a single MCP server using MCPServer configuration

        Args:
            server_id: Unique identifier for the server
            config: MCPServer object with server configuration
        """
        if server_id in self.sessions:
            return
        self._server_configs[server_id] = config
        ready_event = asyncio.Event()

        # This is necessary to ensure in the same event loop
        config.env.update(self.envs)
        config._process_escape()

        async def mcp_session_runner() -> None:
            exit_stack = AsyncExitStack()
            if config.command:
                await self.connect_to_server(
                    server_id, config.command, config.args, config.env, exit_stack
                )
            elif config.url:
                await self.connect_to_server_sse(
                    server_id, config.url, config.header, exit_stack
                )
            else:
                raise ValueError(
                    "Config must contain either a command or a url for the server"
                )
            ready_event.set()
            try:
                stop_event = asyncio.Event()
                current_task = asyncio.current_task()
                self.stop_event[server_id] = stop_event
                self.task[server_id] = current_task
                assert current_task is not None, "Current task should not be None"
                await stop_event.wait()
            finally:
                try:
                    await exit_stack.aclose()
                except Exception:
                    exception("Error during exit stack close")
                debug(f"MCP session {server_id} closed")

        asyncio.create_task(mcp_session_runner())
        await ready_event.wait()

    async def connect_to_server_sse(
        self, server_id: str, url: str, header=None, exit_stack: AsyncExitStack = None
    ):
        # Connect to the server using SSE
        try:
            sse_transport = await exit_stack.enter_async_context(
                sse_client(url, header)
            )
            sse, write = sse_transport
            session = await exit_stack.enter_async_context(
                ClientSession(sse, write, MCP_CONNECT_TIMEOUT)
            )
            await asyncio.wait_for(session.initialize(), timeout=MCP_CONNECT_TIMEOUT)
            self.sessions[server_id] = session
            debug(f"Connected to server {server_id}")
        except TimeoutError:
            error(f"Timeout connecting to SSE server {server_id}")
            self._close_server(server_id)
            raise
        except Exception as e:
            error(f"Error connecting to SSE server {server_id}: {e}")
            self._close_server(server_id)
            raise

    async def connect_to_server(
        self,
        server_id: str,
        command: str,
        args: list,
        env: dict | None = None,
        exit_stack: AsyncExitStack = None,
    ):
        # Connect to an MCP server
        try:
            server_params = StdioServerParameters(command=command, args=args, env=env)
            stdio_transport = await exit_stack.enter_async_context(
                stdio_client(server_params)
            )
            stdio, write = stdio_transport
            session = await exit_stack.enter_async_context(ClientSession(stdio, write))
            await asyncio.wait_for(session.initialize(), timeout=MCP_CONNECT_TIMEOUT)
            self.sessions[server_id] = session
            debug(f"Connected to server {server_id}.")
        except TimeoutError:
            error(f"Timeout connecting to server {server_id}")
            await self._close_server(server_id)
            raise
        except Exception as e:
            error(f"Error connecting to server {server_id}: {e}")
            await self._close_server(server_id)
            raise

    async def list_tools(self, server_id: str) -> dict[str, dict]:
        """Lists all available tools from a connected MCP server."""
        if server_id not in self.sessions:
            warning(f"Server {server_id} not connected, cannot list tools.")
            return {}
        session = self.sessions[server_id]
        list_tools = await session.list_tools()
        list_tools = list_tools.tools
        actual_tools_dict = {x.name: x for x in list_tools}
        return actual_tools_dict

    async def _close_server(self, server_id: str):
        if server_id in self.stop_event:
            self.stop_event[server_id].set()
        if server_id in self.task:
            try:
                await asyncio.wait_for(self.task[server_id], timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self.task[server_id].cancel()
        self.sessions.pop(server_id, None)
        self.stop_event.pop(server_id, None)
        self.task.pop(server_id, None)

    async def cleanup(self):
        """Clean up resources"""
        try:
            server_ids = copy.deepcopy(list(self.sessions.keys()))
            for server_id in server_ids:
                await self._close_server(server_id)
        except TimeoutError:
            warning("Timeout during cleanup")
        except Exception as e:
            error(f"Error during cleanup: {e}")
