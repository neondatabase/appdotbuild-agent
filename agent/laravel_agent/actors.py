import jinja2
import logging
import anyio
from typing import Callable, Awaitable
from core.base_node import Node
from core.workspace import Workspace
from core.actors import BaseData, FileOperationsActor
from llm.common import AsyncLLM, Message, TextRaw
from laravel_agent import playbooks
from laravel_agent.utils import run_migrations, run_tests
from laravel_agent.playbooks import validate_migration_syntax, MIGRATION_SYNTAX_EXAMPLE
from laravel_agent.diversity_prompts import get_diversity_prompt_for_beam
from core.notification_utils import notify_if_callback, notify_stage

logger = logging.getLogger(__name__)


class LaravelActor(FileOperationsActor):
    root: Node[BaseData] | None = None

    def __init__(
        self,
        llm: AsyncLLM,
        workspace: Workspace,
        beam_width: int = 3,
        max_depth: int = 30,
        system_prompt: str = playbooks.APPLICATION_SYSTEM_PROMPT,
        files_protected: list[str] = None,
        files_allowed: list[str] = None,
        event_callback: Callable[[str], Awaitable[None]] | None = None,
    ):
        super().__init__(llm, workspace, beam_width, max_depth)
        self.system_prompt = system_prompt
        self.event_callback = event_callback
        self.files_protected = files_protected or [] # TODO: Add proper exclusion rules
        self.files_allowed = files_allowed  or ["resources/js/pages/", "app/Http/Controllers/Auth/"]

    async def run_llm(
        self, nodes: list[Node[BaseData]], system_prompt: str | None = None, **kwargs
    ) -> list[Node[BaseData]]:
        """Override run_llm to inject diversity prompts for better beam search exploration."""
        from anyio.streams.memory import MemoryObjectSendStream
        from llm.utils import loop_completion
        
        async def node_fn(
            node: Node[BaseData], 
            tx: MemoryObjectSendStream[Node[BaseData]], 
            beam_index: int,
            total_beams: int
        ):
            history = [m for n in node.get_trajectory() for m in n.data.messages]
            
            # Generate diversity prompt for this beam using simple round-robin
            diversity_prompt = get_diversity_prompt_for_beam(beam_index)
            
            # If we have a diversity prompt, inject it into the system prompt
            enhanced_system_prompt = system_prompt or self.system_prompt
            if diversity_prompt:
                enhanced_system_prompt = f"{enhanced_system_prompt}\n\n{diversity_prompt}"
                logger.debug(f"Beam {beam_index} diversity prompt: {diversity_prompt[:100]}...")
            
            new_node = Node[BaseData](
                data=BaseData(
                    workspace=node.data.workspace.clone(),
                    messages=[
                        await loop_completion(
                            self.llm, history, system_prompt=enhanced_system_prompt, **kwargs
                        )
                    ],
                ),
                parent=node,
            )
            async with tx:
                await tx.send(new_node)

        result = []
        tx, rx = anyio.create_memory_object_stream[Node[BaseData]]()
        async with anyio.create_task_group() as tg:
            for i, node in enumerate(nodes):
                tg.start_soon(node_fn, node, tx.clone(), i, len(nodes))
            tx.close()
            async with rx:
                async for new_node in rx:
                    new_node.parent.children.append(new_node)  # pyright: ignore[reportOptionalMemberAccess]
                    result.append(new_node)
        return result

    async def run_llm(
        self, nodes: list[Node[BaseData]], system_prompt: str | None = None, **kwargs
    ) -> list[Node[BaseData]]:
        """Override run_llm to inject diversity prompts for better beam search exploration."""
        from anyio.streams.memory import MemoryObjectSendStream
        from llm.utils import loop_completion
        
        async def node_fn(
            node: Node[BaseData], 
            tx: MemoryObjectSendStream[Node[BaseData]], 
            beam_index: int,
            total_beams: int
        ):
            history = [m for n in node.get_trajectory() for m in n.data.messages]
            
            # Generate diversity prompt for this beam using simple round-robin
            diversity_prompt = get_diversity_prompt_for_beam(beam_index)
            
            # If we have a diversity prompt, inject it into the system prompt
            enhanced_system_prompt = system_prompt or self.system_prompt
            if diversity_prompt:
                enhanced_system_prompt = f"{enhanced_system_prompt}\n\n{diversity_prompt}"
                logger.debug(f"Beam {beam_index} diversity prompt: {diversity_prompt[:100]}...")
            
            new_node = Node[BaseData](
                data=BaseData(
                    workspace=node.data.workspace.clone(),
                    messages=[
                        await loop_completion(
                            self.llm, history, system_prompt=enhanced_system_prompt, **kwargs
                        )
                    ],
                ),
                parent=node,
            )
            async with tx:
                await tx.send(new_node)

        result = []
        tx, rx = anyio.create_memory_object_stream[Node[BaseData]]()
        async with anyio.create_task_group() as tg:
            for i, node in enumerate(nodes):
                tg.start_soon(node_fn, node, tx.clone(), i, len(nodes))
            tx.close()
            async with rx:
                async for new_node in rx:
                    new_node.parent.children.append(new_node)  # pyright: ignore[reportOptionalMemberAccess]
                    result.append(new_node)
        return result

    async def execute(
        self,
        files: dict[str, str],
        user_prompt: str,
    ) -> Node[BaseData]:
        await notify_stage(self.event_callback, "🚀 Starting Laravel application generation", "in_progress")

        workspace = self.workspace.clone()
        logger.info(
            f"Start {self.__class__.__name__} execution with files: {files.keys()}"
        )
        for file_path, content in files.items():
            workspace.write_file(file_path, content)
        workspace.permissions(
            protected=self.files_protected, allowed=self.files_allowed
        )

        jinja_env = jinja2.Environment()
        user_prompt_template = jinja_env.from_string(playbooks.USER_PROMPT)
        repo_files = await self.get_repo_files(workspace, files)
        project_context = "\n".join(
            [
                "Project files:",
                *repo_files,
                "Writeable files and directories:",
                *self.files_allowed,
            ]
        )
        user_prompt_rendered = user_prompt_template.render(
            project_context=project_context,
            user_prompt=user_prompt,
        )
        message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
        self.root = Node(BaseData(workspace, [message], {}))

        solution: Node[BaseData] | None = None
        iteration = 0
        while solution is None:
            iteration += 1
            candidates = self.select(self.root)
            if not candidates:
                logger.info("No candidates to evaluate, search terminated")
                break

            await notify_if_callback(self.event_callback, f"🔄 Working on implementation (iteration {iteration})...", "iteration progress")

            logger.info(
                f"Iteration {iteration}: Running LLM on {len(candidates)} candidates"
            )
            nodes = await self.run_llm(
                candidates,
                system_prompt=self.system_prompt,
                tools=self.tools,
                max_tokens=8192,
            )
            logger.info(f"Received {len(nodes)} nodes from LLM")

            for i, new_node in enumerate(nodes):
                logger.info(f"Evaluating node {i + 1}/{len(nodes)}")
                if await self.eval_node(new_node, user_prompt):
                    logger.info(f"Found solution at depth {new_node.depth}")
                    await notify_stage(self.event_callback, "✅ Laravel application generated successfully", "completed")
                    solution = new_node
                    break
        if solution is None:
            logger.error(f"{self.__class__.__name__} failed to find a solution")
            await notify_stage(self.event_callback, "❌ Laravel application generation failed", "failed")
            raise ValueError("No solutions found")
        return solution

    def select(self, node: Node[BaseData]) -> list[Node[BaseData]]:
        candidates = []
        all_children = node.get_all_children()
        for n in all_children:
            if n.is_leaf and n.depth <= self.max_depth:
                if n.data.should_branch:
                    effective_beam_width = (
                        1 if len(all_children) > (n.depth + 1) else self.beam_width
                    )  # meaning we already branched once
                    logger.info(
                        f"Selecting candidates with effective beam width: {effective_beam_width}, current depth: {n.depth}/{self.max_depth}"
                    )
                    candidates.extend([n] * effective_beam_width)
                else:
                    candidates.append(n)
        logger.info(f"Selected {len(candidates)} leaf nodes for evaluation")
        return candidates

    async def run_ts_type_checks(self, node: Node[BaseData]) -> str | None:
        # CRITICAL: Ziggy-js causes typecheck to fail, agent fixes this but template has to be updated
        type_check_result = await node.data.workspace.exec(
            ["npm", "run", "types"]
        )
        if type_check_result.exit_code != 0:
            return f"{type_check_result.stdout}\n{type_check_result.stderr}"
        return None

    async def run_ts_lint_checks(self, node: Node[BaseData]) -> str | None:
        ts_lint_result = await node.data.workspace.exec(
            ["npm", "run", "lint"]
        )
        if ts_lint_result.exit_code != 0:
            return f"{ts_lint_result.stdout}\n{ts_lint_result.stderr}"
        return None

    async def run_php_lint_checks(self, node: Node[BaseData]) -> str | None:
        php_lint_result = await node.data.workspace.exec(
            ["composer", "lint"]
        )
        if php_lint_result.exit_code != 0:
            return f"{php_lint_result.stdout}\n{php_lint_result.stderr}"
        return None

    async def run_tests(self, node: Node[BaseData]) -> str | None:
        composer_result = await run_tests(node.data.workspace.ctr)
        if composer_result.exit_code != 0:
            return f"{composer_result.stdout}\n{composer_result.stderr}"
        return None

    async def run_migrations_checks(self, node: Node[BaseData]) -> str | None:
        migrations_result = await run_migrations(node.data.workspace.client, node.data.workspace.ctr)
        if migrations_result.exit_code != 0:
            return f"{migrations_result.stdout}\n{migrations_result.stderr}"
        return None

    async def run_checks(self, node: Node[BaseData], user_prompt: str) -> str | None:
        await notify_stage(self.event_callback, "🔍 Running validation checks", "in_progress")

        all_errors = ""
        results = {}

        async with anyio.create_task_group() as tg:

            async def run_and_store(key, coro):
                """Helper to run a coroutine and store its result in the results dict."""
                try:
                    results[key] = await coro
                except Exception as e:
                    # Catch unexpected exceptions during check execution
                    logger.error(f"Error running check {key}: {e}")
                    results[key] = f"Internal error running check {key}: {e}"

            tg.start_soon(run_and_store, "ts_lint", self.run_ts_lint_checks(node))
            tg.start_soon(run_and_store, "php_lint", self.run_php_lint_checks(node))
            tg.start_soon(run_and_store, "ts_type_check", self.run_ts_type_checks(node))
            tg.start_soon(run_and_store, "tests", self.run_tests(node))
            tg.start_soon(run_and_store, "migrations", self.run_migrations_checks(node))

        if ts_lint_result := results.get("ts_lint"):
            logger.info(f"TypeScript lint checks failed: {ts_lint_result}")
            all_errors += f"TypeScript lint errors:\n{ts_lint_result}\n"
        if php_lint_result := results.get("php_lint"):
            logger.info(f"PHP lint checks failed: {php_lint_result}")
            all_errors += f"PHP lint errors:\n{php_lint_result}\n"
        if ts_type_check_result := results.get("ts_type_check"):
            logger.info(f"TypeScript type checks failed: {ts_type_check_result}")
            all_errors += f"TypeScript type errors:\n{ts_type_check_result}\n"
        if tests_result := results.get("tests"):
            logger.info(f"Tests failed: {tests_result}")
            all_errors += f"Test errors:\n{tests_result}\n"
        if migrations_result := results.get("migrations"):
            logger.info(f"Migrations failed: {migrations_result}")
            all_errors += f"Migrations errors:\n{migrations_result}\n"

        if all_errors:
            await notify_stage(self.event_callback, "❌ Validation checks failed - fixing issues", "failed")
            return all_errors.strip()

        await notify_stage(self.event_callback, "✅ All validation checks passed", "completed")
        return None

    async def get_repo_files(
        self, workspace: Workspace, files: dict[str, str]
    ) -> list[str]:
        repo_files = set(files.keys())
        # TODO: Implement proper context gathering
        # Check and list directories that may exist in a Laravel project
        directories_to_check = [
            "./resources/js/pages",
            "./app/Http/Controllers/Auth",
            "./resources/js/Pages",  # Inertia.js convention (capital P)
            "./app/Http/Controllers",
            "./resources/views",
            "./routes"
        ]
        
        for dir_path in directories_to_check:
            try:
                dir_files = await workspace.ls(dir_path)
                for file_path in dir_files:
                    # Remove leading ./ from dir_path if present
                    clean_dir = dir_path.lstrip("./")
                    repo_files.add(f"{clean_dir}/{file_path}")
            except FileNotFoundError:
                # Directory doesn't exist, skip it
                logger.debug(f"Directory {dir_path} not found, skipping")
                continue
            except Exception as e:
                logger.warning(f"Error listing directory {dir_path}: {e}")
                continue
                
        return sorted(list(repo_files))
