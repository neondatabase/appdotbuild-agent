import pytest
from core.statemachine import Actor, Context, State, StateMachine

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return 'asyncio'


class SimpleContext(Context):
    def __init__(self):
        self.log: list[str] = []

    def dump(self) -> dict:
        return {"log": self.log.copy()}

    @classmethod
    def load(cls, data: object) -> "SimpleContext":
        if not isinstance(data, dict):
            raise ValueError("Invalid data format")
        ctx = cls()
        ctx.log = data["log"]
        return ctx


class SimpleActor(Actor):
    def __init__(self):
        self.log: list[str] = []

    async def execute(self, *args, **kwargs) -> str:
        self.log.append("actor_executed")
        return "done"

    async def dump(self) -> dict:
        return {"log": self.log.copy()}

    async def load(self, data: object):
        if not isinstance(data, dict):
            raise ValueError("Invalid data format")
        self.log = data["log"]


async def enter_A(ctx: SimpleContext):
    ctx.log.append("enter_A")


async def enter_B(ctx: SimpleContext):
    ctx.log.append("enter_B")


async def actor_on_done(ctx: SimpleContext, result: object):
    ctx.log.append("actor_on_done")


async def actor_on_error(ctx: SimpleContext, error: Exception):
    ctx.log.append("actor_on_error")


def create_state(actor: SimpleActor) -> State[SimpleContext, str]:
    root = State[SimpleContext, str](
        on={"go": "A"},
        states={
            "A": State(
                entry=[enter_A],
                invoke={
                    "src": actor,
                    "input_fn": lambda ctx: [],
                    "on_done": {"target": "B", "actions": [actor_on_done]},
                    "on_error": {"target": "B", "actions": [actor_on_error]},
                },
                states={
                    "B": State(
                        entry=[enter_B],
                        on={"reset": "A"}
                    )
                },
            )
        }
    )
    return root


async def test_checkpoint_recovery():
    machine = StateMachine[SimpleContext, str](create_state(SimpleActor()), SimpleContext())

    await machine.send("go")

    checkpoint = await machine.dump()

    loaded_machine = await StateMachine[SimpleContext, str].load(create_state(SimpleActor()), checkpoint, SimpleContext)

    assert machine.stack_path == loaded_machine.stack_path
    assert machine.context.log == loaded_machine.context.log

    assert machine.root.states is not None
    assert machine.root.states["A"].invoke is not None
    assert loaded_machine.root.states is not None
    assert loaded_machine.root.states["A"].invoke is not None
    original_actor = machine.root.states["A"].invoke["src"]
    loaded_actor = loaded_machine.root.states["A"].invoke["src"]
    assert await original_actor.dump() == await loaded_actor.dump()


async def test_recovered_behavior():
    machine = StateMachine[SimpleContext, str](create_state(SimpleActor()), SimpleContext())

    await machine.send("go")

    checkpoint = await machine.dump()

    await machine.send("reset")

    loaded_machine = await StateMachine[SimpleContext, str].load(create_state(SimpleActor()), checkpoint, SimpleContext)

    await loaded_machine.send("reset")

    assert machine.context.log == loaded_machine.context.log

    assert machine.root.states is not None
    assert machine.root.states["A"].invoke is not None
    assert loaded_machine.root.states is not None
    assert loaded_machine.root.states["A"].invoke is not None
    original_actor = machine.root.states["A"].invoke["src"]
    loaded_actor = loaded_machine.root.states["A"].invoke["src"]
    assert await original_actor.dump() == await loaded_actor.dump()
