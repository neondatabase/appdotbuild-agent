from dataclasses import dataclass, field


@dataclass
class Issue:
    severity: str  # high, medium, low
    category: str  # types, logic, ui, skill
    description: str


@dataclass
class SkillSuggestion:
    file: str
    suggestion: str


@dataclass
class FeedbackReport:
    app_name: str
    score: int
    type_safe: bool
    works: bool
    issues: list[Issue] = field(default_factory=list)
    successes: list[str] = field(default_factory=list)
    skill_suggestions: list[SkillSuggestion] = field(default_factory=list)
    trajectory_insights: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "FeedbackReport":
        issues = [Issue(**i) for i in data.get("issues", [])]
        suggestions = [SkillSuggestion(**s) for s in data.get("skill_suggestions", [])]
        return cls(
            app_name=data.get("app_name", "unknown"),
            score=data.get("score", 0),
            type_safe=data.get("type_safe", False),
            works=data.get("works", False),
            issues=issues,
            successes=data.get("successes", []),
            skill_suggestions=suggestions,
            trajectory_insights=data.get("trajectory_insights", []),
        )

    def to_dict(self) -> dict:
        return {
            "app_name": self.app_name,
            "score": self.score,
            "type_safe": self.type_safe,
            "works": self.works,
            "issues": [{"severity": i.severity, "category": i.category, "description": i.description} for i in self.issues],
            "successes": self.successes,
            "skill_suggestions": [{"file": s.file, "suggestion": s.suggestion} for s in self.skill_suggestions],
            "trajectory_insights": self.trajectory_insights,
        }
