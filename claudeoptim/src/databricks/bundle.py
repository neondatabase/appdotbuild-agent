from pathlib import Path
import shutil
import tempfile
import docker
from git import Repo


class CliBundle:
    def __init__(self, cli_repo_url: str, branch: str = "main"):
        self.tmp_dir = Path(tempfile.mkdtemp())
        Repo.clone_from(cli_repo_url, self.tmp_dir, branch=branch)
        self.docker_client = docker.from_env()

    def write_file(self, relative_path: str, content: str) -> None:
        file_path = self.tmp_dir / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        with open(file_path, "w") as f:
            f.write(content)

    def read_file(self, relative_path: str) -> str:
        file_path = self.tmp_dir / relative_path
        with open(file_path, "r") as f:
            return f.read()

    def build(self, image_name = "golang:1.25-trixie") -> str:
        output = self.docker_client.containers.run(
            image=image_name,
            command=["make", "build"],
            volumes={str(self.tmp_dir): {'bind': '/app', 'mode': 'rw'}},
            working_dir="/app",
            remove=True,
        )
        return output.decode('utf-8')

    def __del__(self):
        shutil.rmtree(self.tmp_dir)


if __name__ == "__main__":
    builder = CliBundle(cli_repo_url="https://github.com/databricks/cli")
    build_output = builder.build()
    print("Build output:")
    print(build_output)
