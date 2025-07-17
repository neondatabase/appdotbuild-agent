from typing import Any, Awaitable, Callable, NotRequired, Protocol, Self, TypedDict
from log import get_logger
from dataclasses import dataclass

logger = get_logger(__name__)

class EventType(Protocol):
    def __str__(self) -> str: ...


class Actor(Protocol):
    async def execute(self, *args, **kwargs) -> Any:
        ...

    async def dump(self) -> object:
        ...

    async def load(self, data: object):
        ...


class Context(Protocol):
    def dump(self) -> object:
        ...

    @classmethod
    def load(cls, data: object) -> Self:
        ...


class ActorCheckpoint(TypedDict):
    path: list[str]
    data: object


class MachineCheckpoint(TypedDict):
    stack_path: list[str]
    context: object
    actors: list[ActorCheckpoint]


class InvokeCallback[T](TypedDict):
    target: str
    actions: NotRequired[list[Callable[[T, Any], Awaitable[Any]]]] # = []


class Invoke[T](TypedDict):
    src: Actor
    input_fn: Callable[[T], Any]
    on_done: NotRequired[InvokeCallback[T]]
    on_error: NotRequired[InvokeCallback[T]]


class AlwaysRun[T](TypedDict):
    target: str
    guard: NotRequired[Callable[[T], Awaitable[bool]]]
    actions: NotRequired[list[Callable[[T], Awaitable[Any]]]]


@dataclass
class State[T, E_T: EventType]:
    entry: list[Callable[[T], Awaitable[Any]]] | None = None
    invoke: Invoke[T] | None = None
    on: dict[E_T, str] | None = None
    exit: list[Callable[[T], Awaitable[Any]]] | None = None
    always: AlwaysRun[T] | list[AlwaysRun[T]] | None = None
    states: dict[str, "State[T, E_T]"] | None = None
    initial: str | None = None


class StateMachine[T: Context, E_t: EventType]:
    def __init__(self, root: State[T, E_t], context: T):
        self.root = root
        self.context = context
        self.state_stack: list[State[T, E_t]] = [root]
        self._queued_transition: str | None = None

    async def send(self, event: E_t):
        for state in reversed(self.state_stack):
            if state.on and event in state.on:
                self._queued_transition = state.on[event]
                await self._process_transitions()
                return
        raise RuntimeError(f"Invalid event: {event}, stack: {self.stack_path}")

    async def _process_transitions(self):
        while self._queued_transition:
            logger.info(f"Processing transition: {self.stack_path} {self._queued_transition}")
            next_state = self._queued_transition
            self._queued_transition = None
            await self._transition(next_state)

    async def _transition(self, next_state: str):
        exit_stack = []
        while self.state_stack:
            parent_state = self.state_stack.pop()
            if not parent_state.states or next_state not in parent_state.states:
                exit_stack.append(parent_state)
                continue
            target_state = parent_state.states[next_state]
            for state in reversed(exit_stack):
                await self._run_exit(state)
            await self._run_entry(target_state)
            await self._run_invoke(target_state)
            await self._run_always(target_state)
            self.state_stack.extend([parent_state, target_state]) # put target state on stack
            return
        self.state_stack.extend(reversed(exit_stack)) # restore stack
        raise RuntimeError(f"Invalid transition: {next_state}, stack: {self.stack_path}")

    @property
    def stack_path(self) -> list[str]:
        path = []
        for p, n in zip(self.state_stack, self.state_stack[1:]):
            if not p.states:
                break
            for key, value in p.states.items():
                if value == n:
                    path.append(key)
                    break
        return path

    async def _run_entry(self, state: State[T, E_t]):
        if state.entry:
            for action in state.entry:
                await action(self.context)

    async def _run_exit(self, state: State[T, E_t]):
        if state.exit:
            for action in state.exit:
                await action(self.context)

    async def _run_invoke(self, state: State[T, E_t]):
        if state.invoke:
            invoke = state.invoke
            try:
                args = invoke["input_fn"](self.context)
                event = await invoke["src"].execute(*args)
                if "on_done" in invoke:
                    self._queued_transition = invoke["on_done"]["target"]
                    for action in invoke["on_done"].get("actions", []):
                        await action(self.context, event)
            except Exception as e:
                if "on_error" in invoke:
                    self._queued_transition = invoke["on_error"]["target"]
                    for action in invoke["on_error"].get("actions", []):
                        await action(self.context, e)
                else:
                    raise e

    async def _run_always(self, state: State[T, E_t]):
        if state.always:
            branches = state.always if isinstance(state.always, list) else [state.always]
            for always in branches:
                if "guard" not in always or await always["guard"](self.context):
                    self._queued_transition = always["target"]
                    for action in always.get("actions", []):
                        await action(self.context)
                    return

    async def dump(self) -> MachineCheckpoint:
        stack, actors = [(self.root, [])], []
        while stack:
            current, path = stack.pop()
            if current.invoke:
                actors.append({
                    "path": path,
                    "data": await current.invoke["src"].dump(),
                })
            if not current.states:
                continue
            for key, value in current.states.items():
                stack.append((value, path + [key]))
        checkpoint: MachineCheckpoint = {
            "stack_path": self.stack_path,
            "context": self.context.dump(),
            "actors": actors,
        }
        return checkpoint

    @classmethod
    async def load(cls, root: State[T, E_t], data: MachineCheckpoint, context_type: type[T]) -> Self:
        stack = [(root, [])]
        while stack:
            current, path = stack.pop()
            if current.invoke:
                for actor in data["actors"]:
                    if actor["path"] == path:
                        await current.invoke["src"].load(actor["data"])
            if not current.states:
                continue
            for key, value in current.states.items():
                stack.append((value, path + [key]))
        context = context_type.load(data["context"])
        machine = cls(root, context)
        for state_name in data["stack_path"]:
            if not machine.state_stack[-1].states:
                raise RuntimeError(f"Invalid state stack: {machine.state_stack[-1]}")
            if state_name not in machine.state_stack[-1].states:
                raise RuntimeError(f"Invalid state name: {state_name}, stack: {machine.state_stack[-1]}")
            machine.state_stack.append(machine.state_stack[-1].states[state_name])
        return machine
