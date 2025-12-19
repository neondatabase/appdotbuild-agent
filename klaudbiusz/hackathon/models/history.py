from dataclasses import dataclass, field, asdict


@dataclass
class HistoryEntry:
    iteration: int
    plan: str  # free form plan text
    before_avg_score: float
    after_avg_score: float | None = None

    @property
    def score_delta(self) -> float | None:
        if self.after_avg_score is None:
            return None
        return self.after_avg_score - self.before_avg_score

    def to_context(self) -> dict:
        """Format for engineer prompt context."""
        return {
            "iteration": self.iteration,
            "plan": self.plan,
            "before_avg_score": self.before_avg_score,
            "after_avg_score": self.after_avg_score,
            "delta": self.score_delta,
        }


@dataclass
class EvolutionHistory:
    entries: list[HistoryEntry] = field(default_factory=list)
    max_entries: int = 10

    def add(self, entry: HistoryEntry) -> None:
        # update previous entry's after_avg_score if exists
        if self.entries:
            self.entries[-1].after_avg_score = entry.before_avg_score

        self.entries.append(entry)

        if len(self.entries) > self.max_entries:
            self._subsample()

    def _subsample(self) -> None:
        """Keep most informative entries when exceeding max_entries.

        Strategy:
        1. Always keep first entry (baseline)
        2. Always keep last 2 entries (recent context)
        3. Keep entries with largest absolute deltas (most informative)
        """
        if len(self.entries) <= self.max_entries:
            return

        # always keep first and last 2
        first = self.entries[0]
        last_two = self.entries[-2:]
        middle = self.entries[1:-2]

        # sort middle by absolute delta (largest first), None deltas go last
        def delta_key(e: HistoryEntry) -> float:
            d = e.score_delta
            return abs(d) if d is not None else -1

        middle_sorted = sorted(middle, key=delta_key, reverse=True)

        # keep top entries to fit within max_entries
        slots_for_middle = self.max_entries - 3  # 1 first + 2 last
        kept_middle = middle_sorted[:slots_for_middle]

        # reconstruct in chronological order
        kept_middle_sorted = sorted(kept_middle, key=lambda e: e.iteration)
        self.entries = [first] + kept_middle_sorted + last_two

    def to_context(self) -> list[dict]:
        """Format all entries for planner prompt."""
        return [e.to_context() for e in self.entries]

    def to_dict_list(self) -> list[dict]:
        """Serialize for JSON storage."""
        return [asdict(e) for e in self.entries]

    @classmethod
    def from_dict_list(cls, data: list[dict], max_entries: int = 10) -> "EvolutionHistory":
        """Deserialize from JSON."""
        entries = [
            HistoryEntry(
                iteration=d["iteration"],
                plan=d["plan"],
                before_avg_score=d["before_avg_score"],
                after_avg_score=d.get("after_avg_score"),
            )
            for d in data
        ]
        return cls(entries=entries, max_entries=max_entries)
