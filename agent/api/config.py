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


CONFIG = Config()
