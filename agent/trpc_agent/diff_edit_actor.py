import jinja2
import logging
from core.base_node import Node
from core.workspace import Workspace
from core.actors import BaseData, FileOperationsActor
from llm.common import AsyncLLM, Message, TextRaw
from trpc_agent import playbooks
from trpc_agent.actors import run_tests, run_tsc_compile, run_frontend_build
from trpc_agent.playwright import PlaywrightRunner
from core.notification_utils import notify_if_callback

logger = logging.getLogger(__name__)




class EditActor(FileOperationsActor):
    root: Node[BaseData] | None = None

    def __init__(
        self,
        llm: AsyncLLM,
        vlm: AsyncLLM,
        workspace: Workspace,
        beam_width: int = 3,
        max_depth: int = 30,
        event_callback = None,
    ):
        super().__init__(llm, workspace, beam_width, max_depth)
        self.playwright = PlaywrightRunner(vlm)
        self.event_callback = event_callback

    async def execute(
        self,
        files: dict[str, str],
        user_prompt: str,
        feedback: str,
    ) -> Node[BaseData]:
        await notify_if_callback(self.event_callback, "🛠️ Applying requested changes...", "edit start")

        workspace = self.workspace.clone()
        logger.info(f"Start EditActor execution with files: {files.keys()}")
        for file_path, content in files.items():
            workspace.write_file(file_path, content)
        workspace.permissions(protected=self.files_protected, allowed=self.files_allowed)

        jinja_env = jinja2.Environment()
        user_prompt_template = jinja_env.from_string(playbooks.EDIT_ACTOR_USER_PROMPT)
        repo_files = await self.get_repo_files(workspace, files)
        project_context = "\n".join([
            "Project files:",
            *repo_files,
            "Writeable files and directories:",
            *self.files_allowed,
            "Protected files and directories:",
            *self.files_protected
        ])
        user_prompt_rendered = user_prompt_template.render(
            project_context=project_context,
            user_prompt=user_prompt,
            feedback=feedback
        )
        message = Message(role="user", content=[TextRaw(user_prompt_rendered)])
        self.root = Node(BaseData(workspace, [message], {}, True))

        solution: Node[BaseData] | None = None
        iteration = 0
        while solution is None:
            iteration += 1
            candidates = self.select(self.root)
            if not candidates:
                logger.info("No candidates to evaluate, search terminated")
                break

            await notify_if_callback(self.event_callback, f"🔄 Working on changes (iteration {iteration})...", "iteration progress")

            logger.info(f"Iteration {iteration}: Running LLM on {len(candidates)} candidates")
            nodes = await self.run_llm(
                candidates,
                system_prompt=playbooks.EDIT_ACTOR_SYSTEM_PROMPT,
                tools=self.tools,
                max_tokens=8192,
            )
            logger.info(f"Received {len(nodes)} nodes from LLM")

            for i, new_node in enumerate(nodes):
                logger.info(f"Evaluating node {i+1}/{len(nodes)}")
                if await self.eval_node(new_node, user_prompt):
                    logger.info(f"Found solution at depth {new_node.depth}")
                    await notify_if_callback(self.event_callback, "✅ Changes applied successfully!", "edit completion")
                    solution = new_node
                    break
        if solution is None:
            logger.error("EditActor failed to find a solution")
            raise ValueError("No solutions found")
        return solution

    def select(self, node: Node[BaseData]) -> list[Node[BaseData]]:
        candidates = []
        all_children = node.get_all_children()
        effective_beam_width = (
            1 if len(all_children) >= self.beam_width else self.beam_width
        )
        logger.info(
            f"Selecting candidates with effective beam width: {effective_beam_width}, total children: {len(all_children)}"
        )
        for n in all_children:
            if n.is_leaf and n.depth <= self.max_depth:
                if n.data.should_branch:
                    candidates.extend([n] * effective_beam_width)
                else:
                    candidates.append(n)
        logger.info(f"Selected {len(candidates)} leaf nodes for evaluation")
        return candidates

    async def run_checks(self, node: Node[BaseData], user_prompt: str) -> str | None:
        await notify_if_callback(self.event_callback, "🔍 Validating changes...", "validation start")

        _, tsc_compile_err = await run_tsc_compile(node, self.event_callback)
        if tsc_compile_err:
            return f"TypeScript compile errors (backend):\n{tsc_compile_err.text}\n"

        # client tsc compile - should be refactored for the consistency
        await notify_if_callback(self.event_callback, "🔧 Compiling frontend TypeScript...", "frontend compile start")

        tsc_result = await node.data.workspace.exec(["bun", "run", "tsc", "-p", "tsconfig.app.json", "--noEmit"], cwd="client")
        if tsc_result.exit_code != 0:
            await notify_if_callback(self.event_callback, "❌ Frontend TypeScript compilation failed", "frontend compile failure")
            return f"TypeScript compile errors (frontend): {tsc_result.stdout}"

        _, test_result = await run_tests(node, self.event_callback)
        if test_result:
            return f"Test errors:\n{test_result.text}\n"

        build_result = await run_frontend_build(node, self.event_callback)
        if build_result:
            return build_result

        await notify_if_callback(self.event_callback, "🎭 Running UI validation...", "playwright start")

        playwright_result = await self.playwright.evaluate(node, user_prompt, mode="full")
        if playwright_result:
            await notify_if_callback(self.event_callback, "❌ UI validation failed - adjusting...", "playwright failure")
            return "\n".join(playwright_result)

        await notify_if_callback(self.event_callback, "✅ All validations passed!", "validation success")

        return None

    @property
    def files_allowed(self) -> list[str]:
        return [
            "server/src/schema.ts",
            "server/src/db/schema.ts",
            "server/src/handlers/",
            "server/src/tests/",
            "server/src/index.ts",
            "client/src/App.tsx",
            "client/src/components/",
            "client/src/App.css",
        ]

    @property
    def files_protected(self) -> list[str]:
        return [
            "Dockerfile",
            "server/src/db/index.ts",
            "client/src/utils/trpc.ts",
            "client/src/components/ui/",
        ]

    @property
    def files_visible(self) -> list[str]:
        return [
            "client/src/components/ui/",
        ]

    async def get_repo_files(self, workspace: Workspace, files: dict[str, str]) -> list[str]:
        repo_files = set([
            "server/src/schema.ts",
            "server/src/db/index.ts",
            "server/src/db/schema.ts",
            "server/src/index.ts",
            "server/src/package.json",
            "client/src/App.tsx",
            "client/src/App.css",
            "client/src/utils/trpc.ts",
            "client/src/lib/utils.ts",
            "client/src/package.json",
        ])
        repo_files.update(files.keys())
        repo_files.update(await workspace.ls("client/src/components/ui"))
        return list(repo_files)
