from dataclasses import dataclass, field, asdict
from anyio import create_memory_object_stream
from claude_agent_sdk import (
    ClaudeAgentOptions,
    ClaudeSDKClient,
    Message,
    UserMessage,
    HookContext,
    HookInput,
    HookMatcher,
    McpServerConfig,
    AgentDefinition,
)
from claude_agent_sdk.types import SyncHookJSONOutput


@dataclass
class Config:
     allowed_tools: list[str] = field(default_factory=list)
     mcp_servers: dict[str, McpServerConfig] | str = field(default_factory=dict)
     max_turns: int | None = 75
     disallowed_tools: list[str] = field(default_factory=list)
     cwd: str | None = None
     add_dirs: list[str] = field(default_factory=list)
     max_buffer_size: int | None = None  # Max bytes when buffering CLI stdout
     agents: dict[str, AgentDefinition] | None = None


@dataclass
class CmdPrompt:
    prompt: str


@dataclass
class CmdContinue:
    ...


@dataclass
class CmdStop:
    ...


Command = CmdPrompt | CmdContinue | CmdStop


@dataclass
class EvtInterrupt:
    input_data: HookInput
    tool_use_id: str | None
    messages: list[Message]


@dataclass
class EvtResult:
    messages: list[Message]


Event = EvtInterrupt | EvtResult


class ClaudeRunner:
    def __init__(self, config: Config = Config(), buffer_size: int = 20):
        self.buffer_size = buffer_size
        self.cmd_tx, self.cmd_rx = create_memory_object_stream[Command](max_buffer_size=buffer_size)
        self.evt_tx, self.evt_rx = create_memory_object_stream[Event](max_buffer_size=buffer_size)
        self.options = ClaudeAgentOptions(
            **asdict(config),
            permission_mode="bypassPermissions",
            hooks={
                "PreToolUse": [
                    HookMatcher(matcher="Bash|Write|Edit|MultiEdit", hooks=[self.tool_use_interrupt]),
                    HookMatcher(matcher="mcp__databricks__invoke_databricks_cli", hooks=[self.tool_use_interrupt]),
                ],
            }
        )
        self.messages: list[Message] = []

    async def run(self):
        async with ClaudeSDKClient(options=self.options) as client:
            async for cmd in self.cmd_rx:
                if isinstance(cmd, CmdPrompt):
                    self.messages.append(UserMessage(content=cmd.prompt))
                    await client.query(cmd.prompt)
                    async for msg in client.receive_response():
                        self.messages.append(msg)
                    await self.evt_tx.send(EvtResult(messages=self.messages.copy()))

    async def tool_use_interrupt(self, input_data: HookInput, tool_use_id: str | None, context: HookContext) -> SyncHookJSONOutput:
        await self.evt_tx.send(EvtInterrupt(
            input_data=input_data,
            tool_use_id=tool_use_id,
            messages=self.messages.copy()
        ))
        cmd = await self.cmd_rx.receive()
        if isinstance(cmd, CmdContinue):
            return {}
        else:
            return {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": "Execution stopped by user.",
                }
            }

    async def send(self, command: Command):
        await self.cmd_tx.send(command)

    async def receive(self) -> Event:
        return await self.evt_rx.receive()
