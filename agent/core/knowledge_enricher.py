from pathlib import Path
import logging

from llm.common import Message, TextRaw, Tool, ToolUse, Completion
from llm.utils import get_universal_llm_client

logger = logging.getLogger(__name__)


class KnowledgeBaseEnricher:
    """dynamic prompt enrichment based on knowledge base topics."""

    _instances: dict[str, "KnowledgeBaseEnricher"] = {}

    def __new__(cls, knowledge_base_dir: str | Path | None = None) -> "KnowledgeBaseEnricher":
        # determine the canonical path for the knowledge base directory
        if knowledge_base_dir:
            kb_dir = Path(knowledge_base_dir).resolve()
        else:
            # fallback: look for knowledge_base relative to this file
            current_dir = Path(__file__).parent
            kb_dir = (current_dir / "knowledge_base").resolve()

        # use the resolved path as the key
        key = str(kb_dir)

        if key not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[key] = instance
            instance._initialized = False

        return cls._instances[key]

    def __init__(self, knowledge_base_dir: str | Path | None = None):
        # singleton pattern - only initialize once per directory
        if self._initialized:
            return

        self.llm = get_universal_llm_client()
        self.knowledge_base_dir = Path(knowledge_base_dir) if knowledge_base_dir else None
        self.knowledge_base = self._load_knowledge_base()
        self._select_topics_tool = self._create_selection_tool()
        self._initialized = True

    def _load_knowledge_base(self) -> dict[str, str]:
        """load all .md files from knowledge_base directory as key-value pairs."""
        knowledge_base = {}

        # determine knowledge base directory
        if self.knowledge_base_dir:
            kb_dir = self.knowledge_base_dir
        else:
            # fallback: look for knowledge_base relative to this file
            current_dir = Path(__file__).parent
            kb_dir = current_dir / "knowledge_base"

        if not kb_dir.exists():
            raise FileNotFoundError(f"knowledge base directory not found: {kb_dir}")

        # load all .md files
        for md_file in kb_dir.glob("*.md"):
            key = md_file.stem  # filename without .md extension
            try:
                content = md_file.read_text(encoding="utf-8")
                knowledge_base[key] = content
                logger.debug(f"loaded knowledge topic: {key}")
            except Exception as e:
                logger.error(f"failed to load {md_file}: {e}")

        logger.info(f"loaded {len(knowledge_base)} knowledge base topics")
        return knowledge_base

    def _create_selection_tool(self) -> Tool:
        """create tool for LLM to select relevant knowledge topics."""
        return {
            "name": "select_knowledge_topics",
            "description": "select relevant knowledge base topics for the given task",
            "input_schema": {
                "type": "object",
                "properties": {
                    "topics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "list of topic keys to include in the system prompt"
                    }
                },
                "required": ["topics"]
            }
        }

    def _get_phase_description(self, phase: str) -> str:
        """get human-readable description of development phase."""
        phase_descriptions = {
            # tRPC phases
            "draft": "creating schemas, types, and database models",
            "handler": "implementing API handlers and business logic", 
            "frontend": "building user interface components and interactions",
            "edit": "modifying existing code based on feedback",
            # NiceGUI phases
            "data_model": "designing SQLModel data structures and database schemas",
            "application": "building UI components and application logic with NiceGUI",
            # Generic fallback
            "default": "general development phase"
        }
        return phase_descriptions.get(phase, f"development phase: {phase}")

    async def enrich_prompt(self, user_prompt: str, development_phase: str | None = None) -> str:
        """select relevant knowledge topics and return concatenated content."""
        if not self.knowledge_base:
            logger.warning("no knowledge base topics available")
            return ""

        available_topics = list(self.knowledge_base.keys())

        # build context message including development phase if provided
        context_parts = []
        if development_phase:
            phase_description = self._get_phase_description(development_phase)
            context_parts.append(f"current development phase: {development_phase} ({phase_description})")
        context_parts.extend([
            f"user task: {user_prompt}",
            f"available knowledge topics: {available_topics}",
            "",
            "select only the relevant topics needed for this specific development phase and task. "
            "prioritize topics that provide guidance for the current phase of development. "
            "focus on topics that are directly applicable to what needs to be implemented right now."
        ])

        # create message asking LLM to select relevant topics
        messages = [Message(
            role="user",
            content=[TextRaw("\n\n".join(context_parts))]
        )]

        try:
            response = await self.llm.completion(
                messages=messages,
                max_tokens=1000,
                tools=[self._select_topics_tool],
                tool_choice="auto"
            )

            selected_topics = self._extract_selected_topics(response)
            enrichment = self._build_system_prompt(selected_topics)

            # log selection and size info
            logger.info(f"selected {len(selected_topics)} topics from {len(available_topics)} available: {selected_topics}")
            if enrichment:
                char_count = len(enrichment)
                line_count = enrichment.count('\n') + 1
                logger.info(f"enrichment added: {char_count} characters, {line_count} lines")
            else:
                logger.info("no enrichment added (no topics selected)")

            return enrichment

        except Exception as e:
            logger.error(f"failed to get topic selection from LLM: {e}")
            # fallback to empty enrichment
            return ""

    def _extract_selected_topics(self, response: Completion) -> list[str]:
        """extract selected topic keys from LLM tool call response."""
        selected_topics = []

        for content_block in response.content:
            if isinstance(content_block, ToolUse) and content_block.name == "select_knowledge_topics":
                tool_input = content_block.input
                if isinstance(tool_input, dict) and "topics" in tool_input:
                    topics = tool_input["topics"]
                    if isinstance(topics, list):
                        selected_topics.extend([str(topic) for topic in topics])

        # filter out invalid topic keys
        valid_topics = [topic for topic in selected_topics if topic in self.knowledge_base]

        if len(valid_topics) != len(selected_topics):
            invalid = [topic for topic in selected_topics if topic not in self.knowledge_base]
            logger.warning(f"invalid topics requested: {invalid}")

        return valid_topics

    def _build_system_prompt(self, topic_keys: list[str]) -> str:
        """concatenate selected topics into system prompt section."""
        if not topic_keys:
            return ""

        sections = []
        sections.append("# relevant knowledge base:")

        for key in topic_keys:
            if key in self.knowledge_base:
                content = self.knowledge_base[key].strip()
                sections.append(f"## {key}")
                sections.append(content)

        return "\n\n".join(sections)

    def get_available_topics(self) -> list[str]:
        """return list of available knowledge base topic keys."""
        return list(self.knowledge_base.keys())
