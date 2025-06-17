import os


class Config:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    @property
    def agent_type(self):
        return os.getenv("CODEGEN_AGENT", "trpc_agent")

    @property
    def builder_token(self):
        return os.getenv("BUILDER_TOKEN")

    @property
    def snapshot_bucket(self):
        return os.getenv("SNAPSHOT_BUCKET", None)

    @property
    def available_templates(self):
        """List of all available template IDs"""
        return ["trpc_agent"]

    @property
    def default_template_id(self):
        """Default template ID to use when none is specified"""
        return os.getenv("DEFAULT_TEMPLATE_ID", "trpc_agent")

    @property
    def template_paths(self):
        """Mapping of template IDs to their filesystem paths"""
        return {
            "trpc_agent": "trpc_agent/template"
        }


CONFIG = Config()
