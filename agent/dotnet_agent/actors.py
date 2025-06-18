import logging
import anyio
from trpc_agent.actors import BaseTRPCActor
from dotnet_agent import playbooks
from core.base_node import Node
from core.workspace import Workspace
from core.actors import BaseData
from llm.common import AsyncLLM
import jinja2

logger = logging.getLogger(__name__)


class DotNetDraftActor(BaseTRPCActor):
    """Actor for creating .NET application drafts with models, DTOs and controller stubs"""

    def __init__(self, llm: AsyncLLM, workspace: Workspace, model_params: dict):
        super().__init__(llm, workspace, model_params, beam_width=1, max_depth=1)

    async def run_impl(self, user_prompt: str) -> Node[BaseData]:
        """Generate .NET application draft with models, DTOs, and controller stubs"""
        logger.info("Generating .NET application draft")
        
        template = jinja2.Template(playbooks.DOTNET_BACKEND_DRAFT_USER_PROMPT)
        user_content = template.render(
            user_prompt=user_prompt,
            project_context="Creating .NET Web API with Entity Framework Core"
        )

        messages = [
            {"role": "system", "content": playbooks.DOTNET_BACKEND_DRAFT_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        response = await self.llm.ainvoke(messages)
        
        node = Node[BaseData](
            data=BaseData(
                workspace=self.workspace.clone(),
                files=self.extract_files_from_response(response.content),
                context={"user_prompt": user_prompt, "response": response.content}
            ),
            parent=None,
            depth=0
        )
        
        logger.info(f"Generated {len(node.data.files)} files for .NET draft")
        return node

    def extract_files_from_response(self, content: str) -> dict[str, str]:
        """Extract files from LLM response with <file path="...">...</file> tags"""
        import re
        files = {}
        
        # Pattern to match <file path="...">content</file>
        pattern = r'<file path="([^"]+)">\s*(.*?)\s*</file>'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for path, file_content in matches:
            files[path] = file_content.strip()
            logger.debug(f"Extracted file: {path}")
        
        return files


class DotNetHandlersActor(BaseTRPCActor):
    """Actor for implementing .NET controller methods and Entity Framework operations"""

    def __init__(self, llm: AsyncLLM, workspace: Workspace, model_params: dict, beam_width: int = 3):
        super().__init__(llm, workspace, model_params, beam_width=beam_width, max_depth=5)

    async def run_impl(self, user_prompt: str, files: dict[str, str], feedback_data: str = None) -> Node[BaseData]:
        """Implement .NET controllers with Entity Framework operations"""
        logger.info("Implementing .NET controller handlers")
        
        # Extract controller and model names from the files or user prompt
        controller_name = self.extract_controller_name(files, user_prompt)
        model_name = self.extract_model_name(files, user_prompt)
        
        template = jinja2.Template(playbooks.DOTNET_BACKEND_HANDLER_USER_PROMPT)
        user_content = template.render(
            project_context=self.format_project_context(files),
            controller_name=controller_name,
            model_name=model_name,
            feedback_data=feedback_data
        )

        messages = [
            {"role": "system", "content": playbooks.DOTNET_BACKEND_HANDLER_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        response = await self.llm.ainvoke(messages)
        
        node = Node[BaseData](
            data=BaseData(
                workspace=self.workspace.clone(),
                files=self.extract_files_from_response(response.content),
                context={"user_prompt": user_prompt, "files": files, "response": response.content}
            ),
            parent=None,
            depth=0
        )
        
        logger.info(f"Generated {len(node.data.files)} files for .NET handlers")
        return node

    def extract_controller_name(self, files: dict[str, str], user_prompt: str) -> str:
        """Extract controller name from files or derive from user prompt"""
        # Look for existing controller files
        for path in files.keys():
            if path.endswith("Controller.cs"):
                return path.split("/")[-1].replace(".cs", "")
        
        # Default fallback
        return "ProductsController"

    def extract_model_name(self, files: dict[str, str], user_prompt: str) -> str:
        """Extract model name from files or derive from user prompt"""
        # Look for existing model files
        for path in files.keys():
            if path.startswith("server/Models/") and path.endswith(".cs"):
                return path.split("/")[-1].replace(".cs", "")
        
        # Default fallback
        return "Product"

    def format_project_context(self, files: dict[str, str]) -> str:
        """Format project files as context for the LLM"""
        context_parts = []
        for path, content in files.items():
            if path.endswith((".cs", ".json")):
                context_parts.append(f"<file path=\"{path}\">\n{content}\n</file>")
        
        return "\n\n".join(context_parts)

    def extract_files_from_response(self, content: str) -> dict[str, str]:
        """Extract files from LLM response with <file path="...">...</file> tags"""
        import re
        files = {}
        
        # Pattern to match <file path="...">content</file>
        pattern = r'<file path="([^"]+)">\s*(.*?)\s*</file>'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for path, file_content in matches:
            files[path] = file_content.strip()
            logger.debug(f"Extracted file: {path}")
        
        return files


class DotNetFrontendActor(BaseTRPCActor):
    """Actor for creating React frontend that communicates with .NET API"""

    def __init__(self, llm: AsyncLLM, vlm: AsyncLLM, workspace: Workspace, model_params: dict, beam_width: int = 1, max_depth: int = 20):
        super().__init__(llm, workspace, model_params, beam_width=beam_width, max_depth=max_depth)
        self.vlm = vlm

    async def run_impl(self, user_prompt: str, files: dict[str, str], feedback_data: str = None) -> Node[BaseData]:
        """Generate React frontend components for .NET API"""
        logger.info("Generating .NET React frontend")
        
        template = jinja2.Template(playbooks.DOTNET_FRONTEND_USER_PROMPT)
        user_content = template.render(
            project_context=self.format_project_context(files),
            user_prompt=user_prompt
        )

        messages = [
            {"role": "system", "content": playbooks.DOTNET_FRONTEND_SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]

        response = await self.llm.ainvoke(messages)
        
        node = Node[BaseData](
            data=BaseData(
                workspace=self.workspace.clone(),
                files=self.extract_files_from_response(response.content),
                context={"user_prompt": user_prompt, "files": files, "response": response.content}
            ),
            parent=None,
            depth=0
        )
        
        logger.info(f"Generated {len(node.data.files)} files for .NET React frontend")
        return node

    def format_project_context(self, files: dict[str, str]) -> str:
        """Format project files as context for the LLM"""
        context_parts = []
        
        # Include relevant backend files for understanding the API
        for path, content in files.items():
            if (path.endswith((".cs", ".tsx", ".ts")) and 
                ("Controller" in path or "Models" in path or "client/src" in path)):
                context_parts.append(f"<file path=\"{path}\">\n{content}\n</file>")
        
        return "\n\n".join(context_parts)

    def extract_files_from_response(self, content: str) -> dict[str, str]:
        """Extract files from LLM response with <file path="...">...</file> tags"""
        import re
        files = {}
        
        # Pattern to match <file path="...">content</file>
        pattern = r'<file path="([^"]+)">\s*(.*?)\s*</file>'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for path, file_content in matches:
            files[path] = file_content.strip()
            logger.debug(f"Extracted file: {path}")
        
        return files


class DotNetConcurrentActor(BaseTRPCActor):
    """Concurrent actor for running .NET handlers and frontend together"""

    def __init__(self, handlers: DotNetHandlersActor, frontend: DotNetFrontendActor):
        self.handlers = handlers
        self.frontend = frontend
        self.llm = handlers.llm
        self.workspace = handlers.workspace
        self.model_params = handlers.model_params

    async def run_impl(self, user_prompt: str, files: dict[str, str], feedback_data: str = None) -> dict[str, Node[BaseData]]:
        """Run handlers and frontend generation concurrently"""
        logger.info("Running .NET handlers and frontend concurrently")
        
        async with anyio.create_task_group() as tg:
            handlers_result = None
            frontend_result = None
            
            async def run_handlers():
                nonlocal handlers_result
                handlers_result = await self.handlers.run_impl(user_prompt, files, feedback_data)
            
            async def run_frontend():
                nonlocal frontend_result
                frontend_result = await self.frontend.run_impl(user_prompt, files, feedback_data)
            
            tg.start_task(run_handlers)
            tg.start_task(run_frontend)
        
        return {
            "handlers": handlers_result,
            "frontend": frontend_result
        }