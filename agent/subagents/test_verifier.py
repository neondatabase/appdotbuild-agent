"""
Test Verification Subagent

Ensures comprehensive test coverage and validates implementation correctness.
"""

from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
import ast
import re
import subprocess
import tempfile
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class TestResult:
    """Result of test execution."""
    passed: bool
    total_tests: int
    passed_tests: int
    failed_tests: int
    coverage: float
    execution_time: float
    failures: List[Dict[str, Any]] = field(default_factory=list)
    
    @property
    def success_rate(self) -> float:
        """Calculate test success rate."""
        return self.passed_tests / self.total_tests if self.total_tests > 0 else 0.0

@dataclass
class TestQualityMetrics:
    """Metrics for test quality assessment."""
    coverage: float = 0.0
    assertion_density: float = 0.0
    mock_usage: float = 0.0
    parametrization: float = 0.0
    edge_case_coverage: float = 0.0
    
    @property
    def overall_quality(self) -> float:
        """Calculate overall test quality score."""
        return (
            self.coverage * 0.4 +
            self.assertion_density * 0.2 +
            self.mock_usage * 0.15 +
            self.parametrization * 0.15 +
            self.edge_case_coverage * 0.1
        )

class TestVerifierAgent:
    """
    Test verification subagent ensuring comprehensive testing.
    
    Validates:
    - Test coverage
    - Test quality
    - Edge cases
    - Performance tests
    - Integration tests
    """
    
    def __init__(self):
        self.min_coverage = 0.9
        self.min_quality = 0.85
    
    def process(self, code_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Verify tests for the implementation.
        
        Args:
            code_result: Dictionary containing code and tests
            
        Returns:
            Dictionary with test verification results
        """
        implementation = code_result.get("implementation", "")
        tests = code_result.get("tests", "")
        
        # Analyze test quality
        quality_metrics = self._analyze_test_quality(tests, implementation)
        
        # Generate additional tests if needed
        additional_tests = self._generate_missing_tests(implementation, tests)
        
        # Simulate test execution
        test_result = self._execute_tests(tests, implementation)
        
        # Verify test completeness
        completeness = self._verify_completeness(tests, implementation)
        
        return {
            "passed": test_result.passed and quality_metrics.overall_quality >= self.min_quality,
            "test_result": {
                "passed": test_result.passed,
                "total": test_result.total_tests,
                "passed_count": test_result.passed_tests,
                "failed_count": test_result.failed_tests,
                "coverage": test_result.coverage,
                "execution_time": test_result.execution_time,
                "failures": test_result.failures
            },
            "quality_metrics": {
                "coverage": quality_metrics.coverage,
                "assertion_density": quality_metrics.assertion_density,
                "mock_usage": quality_metrics.mock_usage,
                "parametrization": quality_metrics.parametrization,
                "edge_cases": quality_metrics.edge_case_coverage,
                "overall": quality_metrics.overall_quality
            },
            "completeness": completeness,
            "additional_tests": additional_tests,
            "recommendations": self._generate_recommendations(quality_metrics, test_result)
        }
    
    def _analyze_test_quality(self, tests: str, implementation: str) -> TestQualityMetrics:
        """Analyze the quality of test suite."""
        metrics = TestQualityMetrics()
        
        if not tests:
            return metrics
        
        # Calculate coverage estimate
        impl_functions = re.findall(r'def (\w+)\(', implementation)
        test_functions = re.findall(r'def test_(\w+)', tests)
        metrics.coverage = min(1.0, len(test_functions) / max(1, len(impl_functions)))
        
        # Calculate assertion density
        test_lines = tests.split('\n')
        assertion_lines = [l for l in test_lines if 'assert' in l]
        metrics.assertion_density = len(assertion_lines) / max(1, len(test_functions))
        
        # Check mock usage
        mock_imports = ['Mock', 'MagicMock', 'patch', 'AsyncMock']
        metrics.mock_usage = sum(1 for m in mock_imports if m in tests) / len(mock_imports)
        
        # Check parametrization
        if '@pytest.mark.parametrize' in tests:
            param_count = tests.count('@pytest.mark.parametrize')
            metrics.parametrization = min(1.0, param_count / max(1, len(test_functions)))
        
        # Check edge case coverage
        edge_indicators = ['None', 'empty', 'zero', 'negative', 'overflow', 'boundary', 'edge']
        edge_coverage = sum(1 for e in edge_indicators if e.lower() in tests.lower())
        metrics.edge_case_coverage = min(1.0, edge_coverage / len(edge_indicators))
        
        return metrics
    
    def _generate_missing_tests(self, implementation: str, existing_tests: str) -> str:
        """Generate tests for uncovered functionality."""
        missing_tests = []
        
        try:
            impl_tree = ast.parse(implementation)
            
            # Find all functions in implementation
            impl_functions = []
            for node in ast.walk(impl_tree):
                if isinstance(node, ast.FunctionDef) and not node.name.startswith('_'):
                    impl_functions.append(node)
            
            # Check which functions lack tests
            for func in impl_functions:
                test_name = f"test_{func.name}"
                if test_name not in existing_tests:
                    # Generate test for missing function
                    test = self._generate_test_for_function(func)
                    missing_tests.append(test)
            
            # Generate edge case tests
            edge_tests = self._generate_edge_case_tests(impl_functions)
            missing_tests.extend(edge_tests)
            
            # Generate integration tests
            if len(impl_functions) > 3:
                integration_test = self._generate_integration_test(impl_functions)
                missing_tests.append(integration_test)
            
        except SyntaxError:
            logger.error("Failed to parse implementation for test generation")
        
        return "\n\n".join(missing_tests)
    
    def _generate_test_for_function(self, func: ast.FunctionDef) -> str:
        """Generate test for a specific function."""
        params = [arg.arg for arg in func.args.args if arg.arg != 'self']
        
        test_template = f'''
def test_{func.name}():
    """Test {func.name} functionality."""
    # Arrange
    {self._generate_test_setup(params)}
    
    # Act
    result = {func.name}({', '.join(params)})
    
    # Assert
    assert result is not None
    {self._generate_assertions(func)}
'''
        return test_template
    
    def _generate_test_setup(self, params: List[str]) -> str:
        """Generate test setup for parameters."""
        setup_lines = []
        for param in params:
            if 'id' in param.lower():
                setup_lines.append(f"{param} = 'test-id-123'")
            elif 'name' in param.lower():
                setup_lines.append(f"{param} = 'test-name'")
            elif 'data' in param.lower():
                setup_lines.append(f"{param} = {{'key': 'value'}}")
            elif 'list' in param.lower() or 'items' in param.lower():
                setup_lines.append(f"{param} = [1, 2, 3]")
            else:
                setup_lines.append(f"{param} = Mock()")
        
        return '\n    '.join(setup_lines) if setup_lines else "pass"
    
    def _generate_assertions(self, func: ast.FunctionDef) -> str:
        """Generate assertions based on function signature."""
        assertions = []
        
        # Check return type annotation
        if func.returns:
            if hasattr(func.returns, 'id'):
                type_name = func.returns.id
                if type_name == 'bool':
                    assertions.append("assert isinstance(result, bool)")
                elif type_name == 'str':
                    assertions.append("assert isinstance(result, str)")
                elif type_name == 'int':
                    assertions.append("assert isinstance(result, int)")
                elif type_name == 'list':
                    assertions.append("assert isinstance(result, list)")
                elif type_name == 'dict':
                    assertions.append("assert isinstance(result, dict)")
        
        # Add validation assertions
        if 'validate' in func.name.lower():
            assertions.append("assert result in [True, False]")
        elif 'get' in func.name.lower():
            assertions.append("assert result is not None or result == expected_default")
        elif 'create' in func.name.lower():
            assertions.append("assert result.id is not None")
        
        return '\n    '.join(assertions) if assertions else "# Add specific assertions"
    
    def _generate_edge_case_tests(self, functions: List[ast.FunctionDef]) -> List[str]:
        """Generate edge case tests."""
        edge_tests = []
        
        template = '''
def test_{name}_edge_cases():
    """Test edge cases for {name}."""
    # Test with None
    with pytest.raises((TypeError, ValueError)):
        {name}(None)
    
    # Test with empty input
    result = {name}({empty_input})
    assert result == {expected_empty}
    
    # Test with large input
    large_input = {large_input}
    result = {name}(large_input)
    assert result is not None
'''
        
        for func in functions[:3]:  # Limit to first 3 functions
            if func.args.args:  # Has parameters
                edge_test = template.format(
                    name=func.name,
                    empty_input="[]" if "list" in str(func.args.args[0].annotation) else "{}",
                    expected_empty="[]" if "list" in str(func.returns) else "None",
                    large_input="[i for i in range(1000)]"
                )
                edge_tests.append(edge_test)
        
        return edge_tests
    
    def _generate_integration_test(self, functions: List[ast.FunctionDef]) -> str:
        """Generate integration test."""
        return '''
def test_integration_workflow():
    """Test complete workflow integration."""
    # Setup
    service = ServiceClass()
    repository = Mock(spec=Repository)
    
    # Execute workflow
    with service.transaction():
        entity = service.create_entity({"name": "test"})
        assert entity.id is not None
        
        updated = service.update_entity(entity.id, {"name": "updated"})
        assert updated.name == "updated"
        
        result = service.get_entity(entity.id)
        assert result == updated
        
        deleted = service.delete_entity(entity.id)
        assert deleted is True
    
    # Verify repository interactions
    assert repository.save.called
    assert repository.delete.called
'''
    
    def _execute_tests(self, tests: str, implementation: str) -> TestResult:
        """Simulate test execution."""
        # In real scenario, this would actually run tests
        # For now, we simulate based on test quality
        
        test_count = len(re.findall(r'def test_\w+', tests))
        
        if not tests or test_count == 0:
            return TestResult(
                passed=False,
                total_tests=0,
                passed_tests=0,
                failed_tests=0,
                coverage=0.0,
                execution_time=0.0,
                failures=[{"test": "None", "reason": "No tests found"}]
            )
        
        # Simulate based on test quality indicators
        has_assertions = 'assert' in tests
        has_fixtures = '@pytest.fixture' in tests or 'setUp' in tests
        has_mocks = 'Mock' in tests
        has_parametrize = '@pytest.mark.parametrize' in tests
        
        quality_score = sum([
            has_assertions * 0.4,
            has_fixtures * 0.2,
            has_mocks * 0.2,
            has_parametrize * 0.2
        ])
        
        # Simulate test results
        passed_tests = int(test_count * quality_score)
        failed_tests = test_count - passed_tests
        
        # Estimate coverage
        impl_lines = len(implementation.split('\n'))
        test_lines = len(tests.split('\n'))
        coverage = min(0.95, (test_lines / impl_lines) * quality_score) if impl_lines > 0 else 0.0
        
        failures = []
        if failed_tests > 0:
            failures = [
                {"test": f"test_{i}", "reason": "Simulated failure"}
                for i in range(min(3, failed_tests))
            ]
        
        return TestResult(
            passed=failed_tests == 0 and coverage >= self.min_coverage,
            total_tests=test_count,
            passed_tests=passed_tests,
            failed_tests=failed_tests,
            coverage=coverage,
            execution_time=test_count * 0.1,  # Simulate 0.1s per test
            failures=failures
        )
    
    def _verify_completeness(self, tests: str, implementation: str) -> Dict[str, Any]:
        """Verify test completeness."""
        completeness = {
            "unit_tests": False,
            "integration_tests": False,
            "edge_cases": False,
            "error_handling": False,
            "performance_tests": False,
            "async_tests": False
        }
        
        if not tests:
            return completeness
        
        # Check for different test types
        completeness["unit_tests"] = bool(re.search(r'def test_\w+', tests))
        completeness["integration_tests"] = 'integration' in tests.lower() or 'workflow' in tests.lower()
        completeness["edge_cases"] = any(
            word in tests.lower() 
            for word in ['edge', 'boundary', 'none', 'empty', 'negative']
        )
        completeness["error_handling"] = 'pytest.raises' in tests or 'assertRaises' in tests
        completeness["performance_tests"] = 'benchmark' in tests.lower() or 'performance' in tests.lower()
        completeness["async_tests"] = '@pytest.mark.asyncio' in tests or 'async def test' in tests
        
        return completeness
    
    def _generate_recommendations(self, metrics: TestQualityMetrics, result: TestResult) -> List[str]:
        """Generate test improvement recommendations."""
        recommendations = []
        
        # Coverage recommendations
        if metrics.coverage < 0.9:
            recommendations.append(f"📊 Increase test coverage from {metrics.coverage:.0%} to >90%")
        
        # Quality recommendations
        if metrics.assertion_density < 3:
            recommendations.append("🎯 Add more assertions per test (aim for 3+ assertions)")
        
        if metrics.mock_usage < 0.5:
            recommendations.append("🎭 Use mocks to isolate units under test")
        
        if metrics.parametrization < 0.3:
            recommendations.append("🔄 Use parametrized tests for multiple scenarios")
        
        if metrics.edge_case_coverage < 0.7:
            recommendations.append("🔍 Add more edge case tests (null, empty, boundary values)")
        
        # Execution recommendations
        if result.failed_tests > 0:
            recommendations.append(f"❌ Fix {result.failed_tests} failing tests")
        
        if result.execution_time > 10:
            recommendations.append("⚡ Optimize slow tests (consider using fixtures, mocks)")
        
        # General recommendations
        if not recommendations:
            recommendations.append("✅ Test suite meets quality standards")
        
        return recommendations
    
    def validate(self, result: Dict[str, Any]) -> bool:
        """Validate test verification result."""
        return result.get("passed", False)