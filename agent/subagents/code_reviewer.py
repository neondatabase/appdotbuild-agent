"""
IC6 FAANG Code Reviewer Subagent

Principal Engineer level code reviewer enforcing highest quality standards.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import ast
import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class IssueLevel(Enum):
    """Severity levels for code issues."""
    CRITICAL = "critical"  # Must fix - blocks deployment
    HIGH = "high"         # Should fix - impacts quality
    MEDIUM = "medium"     # Consider fixing - best practice
    LOW = "low"          # Nice to have - style/preference

@dataclass
class CodeIssue:
    """Represents a code quality issue."""
    level: IssueLevel
    category: str
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    suggestion: Optional[str] = None
    
    @property
    def is_blocking(self) -> bool:
        """Check if issue blocks approval."""
        return self.level in [IssueLevel.CRITICAL, IssueLevel.HIGH]

@dataclass
class ReviewResult:
    """Result of code review."""
    approved: bool
    score: float
    issues: List[CodeIssue] = field(default_factory=list)
    strengths: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    @property
    def blocking_issues(self) -> List[CodeIssue]:
        """Get issues that block approval."""
        return [issue for issue in self.issues if issue.is_blocking]

class CodeReviewerAgent:
    """
    IC6-level code reviewer implementing FAANG standards.
    
    Reviews for:
    - Architecture & Design
    - Code Quality
    - Performance
    - Security
    - Maintainability
    """
    
    def __init__(self):
        self.min_score = 0.85
        self.review_categories = [
            "architecture",
            "quality",
            "performance",
            "security",
            "maintainability",
            "testing",
            "documentation"
        ]
    
    def process(self, code_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform comprehensive code review.
        
        Args:
            code_result: Dictionary containing code and metadata
            
        Returns:
            Dictionary with review results
        """
        implementation = code_result.get("implementation", "")
        tests = code_result.get("tests", "")
        documentation = code_result.get("documentation", "")
        
        # Perform multi-dimensional review
        review = self._comprehensive_review(implementation, tests, documentation)
        
        return {
            "approved": review.approved,
            "score": review.score,
            "issues": [self._issue_to_dict(issue) for issue in review.issues],
            "strengths": review.strengths,
            "suggestions": review.suggestions,
            "feedback": self._generate_feedback(review)
        }
    
    def _comprehensive_review(self, code: str, tests: str, docs: str) -> ReviewResult:
        """Perform comprehensive code review."""
        issues: List[CodeIssue] = []
        strengths: List[str] = []
        
        # Architecture review
        arch_issues, arch_strengths = self._review_architecture(code)
        issues.extend(arch_issues)
        strengths.extend(arch_strengths)
        
        # Code quality review
        quality_issues, quality_strengths = self._review_code_quality(code)
        issues.extend(quality_issues)
        strengths.extend(quality_strengths)
        
        # Performance review
        perf_issues, perf_strengths = self._review_performance(code)
        issues.extend(perf_issues)
        strengths.extend(perf_strengths)
        
        # Security review
        sec_issues, sec_strengths = self._review_security(code)
        issues.extend(sec_issues)
        strengths.extend(sec_strengths)
        
        # Test coverage review
        test_issues, test_strengths = self._review_tests(tests, code)
        issues.extend(test_issues)
        strengths.extend(test_strengths)
        
        # Documentation review
        doc_issues, doc_strengths = self._review_documentation(docs, code)
        issues.extend(doc_issues)
        strengths.extend(doc_strengths)
        
        # Calculate overall score
        score = self._calculate_review_score(issues, strengths)
        
        # Generate suggestions
        suggestions = self._generate_suggestions(issues, code)
        
        # Determine approval
        approved = score >= self.min_score and not any(issue.is_blocking for issue in issues)
        
        return ReviewResult(
            approved=approved,
            score=score,
            issues=issues,
            strengths=strengths,
            suggestions=suggestions
        )
    
    def _review_architecture(self, code: str) -> Tuple[List[CodeIssue], List[str]]:
        """Review system architecture and design."""
        issues = []
        strengths = []
        
        try:
            tree = ast.parse(code)
            
            # Check for proper abstraction
            classes = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]
            functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)]
            
            # SOLID principles check
            if len(classes) > 0:
                # Single Responsibility
                for cls in classes:
                    methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)]
                    if len(methods) > 10:
                        issues.append(CodeIssue(
                            level=IssueLevel.HIGH,
                            category="architecture",
                            message=f"Class '{cls.name}' has {len(methods)} methods - consider splitting responsibilities",
                            line=cls.lineno,
                            suggestion="Apply Single Responsibility Principle - split into smaller, focused classes"
                        ))
                
                # Check for dependency injection
                has_di = any(
                    any(arg.annotation for arg in node.args.args)
                    for node in ast.walk(tree)
                    if isinstance(node, ast.FunctionDef) and node.name == "__init__"
                )
                if has_di:
                    strengths.append("Good use of dependency injection")
                else:
                    issues.append(CodeIssue(
                        level=IssueLevel.MEDIUM,
                        category="architecture",
                        message="Consider using dependency injection for better testability",
                        suggestion="Pass dependencies as constructor parameters instead of creating them internally"
                    ))
            
            # Check for proper layering
            if "Repository" in code or "Service" in code:
                strengths.append("Good architectural layering (Repository/Service pattern)")
            
            # Check for interface segregation
            protocols = [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef) and any(base.id == "Protocol" for base in node.bases if hasattr(base, "id"))]
            if protocols:
                strengths.append("Excellent use of Protocol for interface definition")
            
        except SyntaxError:
            issues.append(CodeIssue(
                level=IssueLevel.CRITICAL,
                category="architecture",
                message="Code has syntax errors - cannot parse",
                suggestion="Fix syntax errors before review"
            ))
        
        return issues, strengths
    
    def _review_code_quality(self, code: str) -> Tuple[List[CodeIssue], List[str]]:
        """Review code quality metrics."""
        issues = []
        strengths = []
        
        try:
            tree = ast.parse(code)
            
            # Check function complexity
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    complexity = self._calculate_cyclomatic_complexity(node)
                    if complexity > 10:
                        issues.append(CodeIssue(
                            level=IssueLevel.HIGH,
                            category="quality",
                            message=f"Function '{node.name}' has cyclomatic complexity of {complexity}",
                            line=node.lineno,
                            suggestion="Refactor to reduce complexity - extract methods or simplify logic"
                        ))
                    
                    # Check function length
                    lines = node.end_lineno - node.lineno if hasattr(node, 'end_lineno') else 0
                    if lines > 50:
                        issues.append(CodeIssue(
                            level=IssueLevel.MEDIUM,
                            category="quality",
                            message=f"Function '{node.name}' is {lines} lines long",
                            line=node.lineno,
                            suggestion="Consider breaking into smaller functions"
                        ))
            
            # Check for type hints
            typed_functions = 0
            total_functions = 0
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef):
                    total_functions += 1
                    if node.returns or any(arg.annotation for arg in node.args.args):
                        typed_functions += 1
            
            type_coverage = typed_functions / total_functions if total_functions > 0 else 0
            if type_coverage > 0.9:
                strengths.append(f"Excellent type coverage ({type_coverage:.0%})")
            elif type_coverage < 0.5:
                issues.append(CodeIssue(
                    level=IssueLevel.HIGH,
                    category="quality",
                    message=f"Low type hint coverage ({type_coverage:.0%})",
                    suggestion="Add type hints to all function signatures"
                ))
            
            # Check for proper error handling
            try_blocks = [node for node in ast.walk(tree) if isinstance(node, ast.Try)]
            bare_excepts = [t for t in try_blocks if any(not handler.type for handler in t.handlers)]
            if bare_excepts:
                issues.append(CodeIssue(
                    level=IssueLevel.HIGH,
                    category="quality",
                    message="Found bare except clauses",
                    suggestion="Always specify exception types to catch"
                ))
            elif try_blocks:
                strengths.append("Good error handling with specific exceptions")
            
        except SyntaxError:
            pass  # Already handled in architecture review
        
        return issues, strengths
    
    def _review_performance(self, code: str) -> Tuple[List[CodeIssue], List[str]]:
        """Review performance considerations."""
        issues = []
        strengths = []
        
        # Check for common performance issues
        performance_patterns = {
            r'for .+ in .+:\s*for .+ in .+:': (
                "Nested loops detected",
                IssueLevel.MEDIUM,
                "Consider using more efficient algorithms or data structures"
            ),
            r'\.append\(.+\) for .+ in': (
                "List comprehension might be more efficient",
                IssueLevel.LOW,
                "Use list comprehension instead of append in loop"
            ),
            r'time\.sleep': (
                "Synchronous sleep detected",
                IssueLevel.MEDIUM,
                "Consider using asyncio.sleep for async code"
            )
        }
        
        for pattern, (message, level, suggestion) in performance_patterns.items():
            if re.search(pattern, code):
                issues.append(CodeIssue(
                    level=level,
                    category="performance",
                    message=message,
                    suggestion=suggestion
                ))
        
        # Check for good practices
        if "@lru_cache" in code or "functools.cache" in code:
            strengths.append("Good use of caching for performance")
        
        if "async def" in code and "await" in code:
            strengths.append("Proper use of async/await for I/O operations")
        
        if "with" in code:
            strengths.append("Good use of context managers for resource management")
        
        return issues, strengths
    
    def _review_security(self, code: str) -> Tuple[List[CodeIssue], List[str]]:
        """Review security considerations."""
        issues = []
        strengths = []
        
        # Critical security issues
        dangerous_functions = {
            "eval(": (IssueLevel.CRITICAL, "Never use eval() - extreme security risk"),
            "exec(": (IssueLevel.CRITICAL, "Never use exec() - extreme security risk"),
            "__import__": (IssueLevel.CRITICAL, "Dynamic imports are a security risk"),
            "pickle.loads": (IssueLevel.CRITICAL, "Pickle can execute arbitrary code"),
            "os.system": (IssueLevel.HIGH, "Use subprocess with proper escaping instead"),
            "shell=True": (IssueLevel.HIGH, "Shell injection risk - avoid shell=True"),
        }
        
        for pattern, (level, message) in dangerous_functions.items():
            if pattern in code:
                issues.append(CodeIssue(
                    level=level,
                    category="security",
                    message=message,
                    suggestion="Use safe alternatives"
                ))
        
        # SQL injection check
        if "f\"SELECT" in code or "f'SELECT" in code or '+ "SELECT' in code:
            issues.append(CodeIssue(
                level=IssueLevel.CRITICAL,
                category="security",
                message="Potential SQL injection vulnerability",
                suggestion="Use parameterized queries instead of string formatting"
            ))
        
        # Check for good security practices
        if "hashlib" in code or "bcrypt" in code or "argon2" in code:
            strengths.append("Proper use of cryptographic hashing")
        
        if "secrets" in code:
            strengths.append("Good use of secrets module for secure random generation")
        
        if not issues:
            strengths.append("No critical security vulnerabilities detected")
        
        return issues, strengths
    
    def _review_tests(self, tests: str, code: str) -> Tuple[List[CodeIssue], List[str]]:
        """Review test coverage and quality."""
        issues = []
        strengths = []
        
        if not tests or len(tests) < 100:
            issues.append(CodeIssue(
                level=IssueLevel.CRITICAL,
                category="testing",
                message="Insufficient test coverage",
                suggestion="Add comprehensive unit tests for all public methods"
            ))
            return issues, strengths
        
        # Check test quality indicators
        test_indicators = {
            "@pytest.fixture": "Good use of fixtures",
            "@pytest.mark.parametrize": "Excellent parametrized testing",
            "@pytest.mark.asyncio": "Proper async test support",
            "Mock": "Good use of mocking",
            "hypothesis": "Excellent property-based testing",
            "assert": "Tests contain assertions"
        }
        
        for indicator, strength in test_indicators.items():
            if indicator in tests:
                strengths.append(strength)
        
        # Check for test organization
        test_classes = re.findall(r'class Test\w+', tests)
        if test_classes:
            strengths.append(f"Well-organized tests in {len(test_classes)} test classes")
        
        # Estimate coverage (simplified)
        functions_in_code = len(re.findall(r'def \w+', code))
        test_functions = len(re.findall(r'def test_\w+', tests))
        
        if test_functions < functions_in_code * 0.8:
            issues.append(CodeIssue(
                level=IssueLevel.HIGH,
                category="testing",
                message=f"Low test coverage - {test_functions} tests for {functions_in_code} functions",
                suggestion="Aim for at least one test per public function"
            ))
        
        return issues, strengths
    
    def _review_documentation(self, docs: str, code: str) -> Tuple[List[CodeIssue], List[str]]:
        """Review documentation quality."""
        issues = []
        strengths = []
        
        # Check for docstrings in code
        try:
            tree = ast.parse(code)
            
            undocumented = []
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                    if not ast.get_docstring(node):
                        undocumented.append(node.name)
            
            if undocumented:
                issues.append(CodeIssue(
                    level=IssueLevel.MEDIUM,
                    category="documentation",
                    message=f"Missing docstrings for: {', '.join(undocumented[:5])}",
                    suggestion="Add docstrings to all public functions and classes"
                ))
            else:
                strengths.append("All functions and classes have docstrings")
            
        except SyntaxError:
            pass
        
        # Check external documentation
        if docs and len(docs) > 500:
            strengths.append("Comprehensive external documentation provided")
            
            if "## Usage" in docs or "## Examples" in docs:
                strengths.append("Good usage examples in documentation")
            
            if "## API" in docs or "## Reference" in docs:
                strengths.append("API documentation provided")
        else:
            issues.append(CodeIssue(
                level=IssueLevel.MEDIUM,
                category="documentation",
                message="Limited external documentation",
                suggestion="Add README with usage examples and API reference"
            ))
        
        return issues, strengths
    
    def _calculate_cyclomatic_complexity(self, node: ast.FunctionDef) -> int:
        """Calculate cyclomatic complexity of a function."""
        complexity = 1  # Base complexity
        
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                complexity += 1
            elif isinstance(child, ast.BoolOp):
                complexity += len(child.values) - 1
        
        return complexity
    
    def _calculate_review_score(self, issues: List[CodeIssue], strengths: List[str]) -> float:
        """Calculate overall review score."""
        # Weight issues by severity
        issue_weights = {
            IssueLevel.CRITICAL: 0.3,
            IssueLevel.HIGH: 0.15,
            IssueLevel.MEDIUM: 0.05,
            IssueLevel.LOW: 0.02
        }
        
        total_deduction = sum(
            issue_weights.get(issue.level, 0)
            for issue in issues
        )
        
        # Bonus for strengths
        strength_bonus = min(0.2, len(strengths) * 0.02)
        
        # Calculate final score
        score = max(0, min(1, 1 - total_deduction + strength_bonus))
        
        return score
    
    def _generate_suggestions(self, issues: List[CodeIssue], code: str) -> List[str]:
        """Generate improvement suggestions."""
        suggestions = []
        
        # Prioritize critical issues
        critical_issues = [i for i in issues if i.level == IssueLevel.CRITICAL]
        if critical_issues:
            suggestions.append(f"🚨 Address {len(critical_issues)} critical issues immediately")
        
        # Group issues by category
        categories = {}
        for issue in issues:
            if issue.category not in categories:
                categories[issue.category] = []
            categories[issue.category].append(issue)
        
        # Generate category-specific suggestions
        if "architecture" in categories:
            suggestions.append("📐 Refactor architecture to follow SOLID principles")
        
        if "performance" in categories:
            suggestions.append("⚡ Optimize performance bottlenecks")
        
        if "security" in categories:
            suggestions.append("🔒 Fix security vulnerabilities")
        
        if "testing" in categories:
            suggestions.append("🧪 Increase test coverage to >90%")
        
        # Add general improvement suggestions
        if len(issues) == 0:
            suggestions.append("✨ Code meets high quality standards - consider adding more advanced features")
        elif len(issues) < 5:
            suggestions.append("👍 Minor improvements needed - close to approval")
        else:
            suggestions.append("🔧 Significant refactoring required")
        
        return suggestions
    
    def _generate_feedback(self, review: ReviewResult) -> str:
        """Generate human-readable feedback."""
        feedback = []
        
        # Overall assessment
        if review.approved:
            feedback.append("✅ **Code Approved** - Meets IC6 quality standards\n")
        else:
            feedback.append("❌ **Changes Required** - Does not meet quality standards\n")
        
        feedback.append(f"**Overall Score**: {review.score:.1%}\n")
        
        # Strengths
        if review.strengths:
            feedback.append("\n**Strengths**:")
            for strength in review.strengths[:5]:
                feedback.append(f"  ✓ {strength}")
        
        # Critical issues
        if review.blocking_issues:
            feedback.append("\n**Blocking Issues**:")
            for issue in review.blocking_issues[:5]:
                feedback.append(f"  ✗ [{issue.level.value.upper()}] {issue.message}")
                if issue.suggestion:
                    feedback.append(f"    → {issue.suggestion}")
        
        # Suggestions
        if review.suggestions:
            feedback.append("\n**Recommendations**:")
            for suggestion in review.suggestions[:3]:
                feedback.append(f"  • {suggestion}")
        
        return "\n".join(feedback)
    
    def _issue_to_dict(self, issue: CodeIssue) -> Dict[str, Any]:
        """Convert issue to dictionary."""
        return {
            "level": issue.level.value,
            "category": issue.category,
            "message": issue.message,
            "line": issue.line,
            "column": issue.column,
            "suggestion": issue.suggestion
        }
    
    def validate(self, result: Dict[str, Any]) -> bool:
        """Validate review result."""
        return result.get("approved", False)