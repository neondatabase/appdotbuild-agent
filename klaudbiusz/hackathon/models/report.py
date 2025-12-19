from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .history import HistoryEntry


@dataclass
class EvolutionReport:
    config: dict
    history: list[HistoryEntry]
    final_avg_score: float | None = None

    def to_markdown(self) -> str:
        lines = [
            "# Skill Evolution Report",
            "",
            f"Generated: {datetime.now():%Y-%m-%d %H:%M:%S}",
            "",
            "## Configuration",
            "",
            f"- Iterations: {self.config.get('num_iterations', 'N/A')}",
            f"- Apps per iteration: {self.config.get('prompts_per_iteration', 'N/A')}",
            f"- Model: {self.config.get('model', 'N/A')}",
            "",
        ]

        # score progression table
        lines.extend([
            "## Score Progression",
            "",
            "| Iteration | Avg Score | Delta |",
            "|-----------|-----------|-------|",
        ])

        for entry in self.history:
            delta_str = "-"
            if entry.score_delta is not None:
                sign = "+" if entry.score_delta >= 0 else ""
                delta_str = f"{sign}{entry.score_delta:.2f}"
            lines.append(f"| {entry.iteration} | {entry.before_avg_score:.2f} | {delta_str} |")

        # add final iteration score if available
        if self.final_avg_score is not None and self.history:
            last = self.history[-1]
            if last.after_avg_score is not None:
                final_delta = last.after_avg_score - last.before_avg_score
                sign = "+" if final_delta >= 0 else ""
                lines.append(f"| {last.iteration + 1} (final) | {last.after_avg_score:.2f} | {sign}{final_delta:.2f} |")

        # overall delta
        if self.history and self.history[0].before_avg_score is not None:
            first_score = self.history[0].before_avg_score
            last_score = self.final_avg_score or (self.history[-1].after_avg_score if self.history else None)
            if last_score is not None:
                overall_delta = last_score - first_score
                sign = "+" if overall_delta >= 0 else ""
                lines.extend([
                    "",
                    f"**Overall Delta**: {sign}{overall_delta:.2f} ({first_score:.2f} -> {last_score:.2f})",
                ])

        # iteration details
        lines.extend([
            "",
            "## Iteration Details",
            "",
        ])

        for entry in self.history:
            next_iter = entry.iteration + 1
            lines.extend([
                f"### Iteration {entry.iteration} -> {next_iter}",
                "",
                "**Plan**:",
                "```",
                entry.plan,
                "```",
                "",
            ])

            if entry.score_delta is not None:
                sign = "+" if entry.score_delta >= 0 else ""
                result_emoji = "✅" if entry.score_delta > 0 else ("⚠️" if entry.score_delta == 0 else "❌")
                lines.append(f"**Result**: {sign}{entry.score_delta:.2f} {result_emoji}")
            else:
                lines.append("**Result**: Pending")

            lines.append("")

        # key learnings section
        lines.extend([
            "## Key Learnings",
            "",
        ])

        positive_changes = [e for e in self.history if e.score_delta is not None and e.score_delta > 0]
        negative_changes = [e for e in self.history if e.score_delta is not None and e.score_delta < 0]

        if positive_changes:
            lines.append("**What worked:**")
            for e in positive_changes:
                first_line = e.plan.split("\n")[0][:60]
                lines.append(f"- Iteration {e.iteration}: {first_line}... (+{e.score_delta:.2f})")
            lines.append("")

        if negative_changes:
            lines.append("**What didn't work:**")
            for e in negative_changes:
                first_line = e.plan.split("\n")[0][:60]
                lines.append(f"- Iteration {e.iteration}: {first_line}... ({e.score_delta:.2f})")
            lines.append("")

        if not positive_changes and not negative_changes:
            lines.append("No completed iterations with measurable deltas yet.")
            lines.append("")

        return "\n".join(lines)

    def save(self, path: Path) -> None:
        path.write_text(self.to_markdown())
