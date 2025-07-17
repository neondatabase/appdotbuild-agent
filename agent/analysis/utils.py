from fire import Fire
import ujson as json
from typing import List, Dict, Any
import os
from glob import glob

from core.statemachine import StateMachine
from trpc_agent.application import ApplicationContext, FSMEvent, FSMApplication, Node, EditActor
from trpc_agent.actors import ConcurrentActor, DraftActor
import dagger
import anyio


async def _get_actors(data: Dict[str, Any]):
    async with dagger.Connection(dagger.Config(log_output=open(os.devnull, "w"))) as client:
        root = await FSMApplication.make_states(client)
    fsm = await StateMachine[ApplicationContext, FSMEvent].load(root, data, ApplicationContext)
    match fsm.root.states:
        case None:
            raise ValueError("No states found in the FSM data.")
        case _:
            actors = [state.invoke["src"] for state in fsm.root.states.values() if state.invoke is not None]
            return actors


def get_all_trajectories(root: Node, prefix: str = ""):
    nodes = list(filter(lambda x: x.is_leaf, root.get_all_children()))
    for i, n in enumerate(nodes):
        leaf_messages = []
        for traj_node in n.get_trajectory():
            leaf_messages.extend(traj_node.data.messages)

        yield f"{prefix}_{i}", [msg.to_dict() for msg in leaf_messages]


def extract_trajectories_from_dump(data: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    """Extract trajectories from FSM dump data.

    Args:
        data: Dict containing the FSM checkpoint data
    """
    actors = anyio.run(_get_actors, data)
    messages = {}

    for actor in actors:
        match actor:
            case ConcurrentActor():
                handlers = actor.handlers
                for name, handler in handlers.handlers.items():
                    for k, v in get_all_trajectories(handler, f"backend_{name}"):
                        messages[k] = v

                frontend = actor.frontend.root
                if frontend:
                    for k, v in get_all_trajectories(frontend, "frontend"):
                        messages[k] = v

            case DraftActor():
                root = actor.root
                if root is None:
                    continue
                for k, v in get_all_trajectories(root, "draft"):
                    messages[k] = v

            case EditActor():
                root = actor.root
                if root is None:
                    continue
                for k, v in get_all_trajectories(root, "edit"):
                    messages[k] = v

            case _:
                raise ValueError(f"Unknown actor type: {type(actor)}")

    return messages


def main(dumps_path: str, output_path: str):
    if os.path.isdir(dumps_path):
        dump_files = glob(os.path.join(dumps_path, "*.json"))
    elif os.path.isfile(dumps_path):
        dump_files = [dumps_path]
    else:
        raise ValueError(f"Invalid dumps path: {dumps_path}")

    os.makedirs(output_path, exist_ok=True)

    final_result = {}

    for dump_file in dump_files:
        print(f"Processing {dump_file}...")
        try:
            with open(dump_file, "r") as f:
                dump_data = json.load(f)
            trajectories = extract_trajectories_from_dump(dump_data)
            final_result[os.path.basename(dump_file)] = trajectories
            output_file = os.path.join(output_path, os.path.basename(dump_file))

            with open(output_file, "w") as f:
                json.dump(trajectories, f, indent=2)

            print(f"Trajectories saved to {output_file}")
        except Exception as e:
            print(f"Error processing {dump_file}: {e}")

    # for AI-assisted analysis, we can format the output in a more readable way
    for file_name, trajectories in final_result.items():
        acc = ""  # markdown accumulator for final output
        for key, messages in trajectories.items():
            acc += f"Trajectory: {key}\n"
            for msg in messages:
                role = msg.get("role", "unknown")
                content = msg.get("content", [])
                for x in content:
                    if x.get("text"):
                        acc += f"- **{role}**:\n {x['text']}\n\n"
                    else:
                        acc += f"- **{role}**: {x}\n\n"

        with open(os.path.join(output_path, file_name.replace(".json", ".txt")), "w") as f:
            f.write(acc)


if __name__ == "__main__":
    Fire(main)
