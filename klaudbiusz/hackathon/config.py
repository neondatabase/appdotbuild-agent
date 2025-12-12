from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EvolutionConfig:
    skills_dir: Path
    output_dir: Path
    num_iterations: int = 3
    prompts_per_iteration: int = 5
    model: str = "claude-sonnet-4-5"
    max_turns: int = 50
    prompts: dict[str, str] = field(default_factory=dict)
    verbose: bool = False
