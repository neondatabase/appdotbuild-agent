use eyre::Result;
use regex::Regex;

#[derive(Debug, Clone)]
pub struct FunctionSignature {
    pub name: String,
    pub args: Option<String>,
    pub return_type: Option<String>,
}

/// Extract function signatures from Python source code
/// Simple regex-based parsing - good enough for hackathon/prototype
pub fn extract_function_signatures(python_source: &str) -> Result<Vec<FunctionSignature>> {
    // Match: def function_name(args) -> return_type:
    // Handles both with and without return type annotation
    let re = Regex::new(r"def\s+(\w+)\s*\((.*?)\)\s*(?:->\s*([^:]+))?:")?;

    let mut functions = Vec::new();
    for cap in re.captures_iter(python_source) {
        let name = cap.get(1).map(|m| m.as_str().to_string()).unwrap();
        let args = cap.get(2).map(|m| m.as_str().trim().to_string());
        let return_type = cap.get(3).map(|m| m.as_str().trim().to_string());

        functions.push(FunctionSignature {
            name,
            args,
            return_type,
        });
    }

    Ok(functions)
}

/// Generate Rust stub implementation with TODO comments
pub fn generate_rust_stubs(functions: &[FunctionSignature]) -> String {
    let mut content = String::from("use pyo3::prelude::*;\n\n");

    for func in functions {
        let args_display = func.args.as_deref().unwrap_or("");
        let ret_display = func.return_type.as_deref().unwrap_or("None");

        content.push_str(&format!(
            r#"/// TODO: Implement equivalent to Python `{name}`
/// Original signature: def {name}({args}) -> {ret}
///
/// Implementation notes:
/// - Replace the todo!() with your Rust implementation
/// - Ensure return type matches Python behavior
/// - Add proper error handling with PyResult
#[pyfunction]
fn {name}(/* TODO: add typed arguments */) -> PyResult<()> {{
    todo!("Implement {name} - see GUIDELINES.md for patterns")
}}

"#,
            name = func.name,
            args = args_display,
            ret = ret_display,
        ));
    }

    // Generate module registration
    content.push_str("#[pymodule]\nfn _rust_impl(_py: Python, m: &PyModule) -> PyResult<()> {\n");
    for func in functions {
        content.push_str(&format!(
            "    m.add_function(wrap_pyfunction!({}, m)?)?;\n",
            func.name
        ));
    }
    content.push_str("    Ok(())\n}\n");

    content
}

/// Generate equivalence test template
pub fn generate_equivalence_tests(
    functions: &[FunctionSignature],
    python_module_name: &str,
) -> String {
    let mut content = String::from(
        r#""""
Equivalence tests comparing Python original with Rust implementation.

Tests verify that Rust implementation produces identical outputs to Python.
"""

import pytest

"#,
    );

    content.push_str(&format!(
        "# Import original Python module (adjust path if needed)\n"
    ));
    content.push_str(&format!("# import {}\n\n", python_module_name));
    content.push_str("# Import Rust implementation\n");
    content.push_str("from rust_impl import _rust_impl\n\n");

    for func in functions {
        content.push_str(&format!(
            r#"def test_{name}_equivalence():
    """Test that {name} produces same output in Rust and Python."""
    # TODO: Add test inputs
    # test_input = ...

    # TODO: Call Python version
    # py_result = {module}.{name}(test_input)

    # Call Rust version
    # rust_result = _rust_impl.{name}(test_input)

    # Verify equivalence
    # assert py_result == rust_result
    pass


"#,
            name = func.name,
            module = python_module_name,
        ));
    }

    content
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_simple_function() {
        let python = r#"
def hello(name: str) -> str:
    return f"Hello, {name}!"
"#;
        let funcs = extract_function_signatures(python).unwrap();
        assert_eq!(funcs.len(), 1);
        assert_eq!(funcs[0].name, "hello");
        assert!(funcs[0].args.as_ref().unwrap().contains("name: str"));
        assert_eq!(funcs[0].return_type.as_deref(), Some("str"));
    }

    #[test]
    fn test_extract_no_return_type() {
        let python = r#"
def process(items):
    return [x * 2 for x in items]
"#;
        let funcs = extract_function_signatures(python).unwrap();
        assert_eq!(funcs.len(), 1);
        assert_eq!(funcs[0].name, "process");
        assert!(funcs[0].return_type.is_none());
    }

    #[test]
    fn test_extract_multiple_functions() {
        let python = r#"
def add(a: int, b: int) -> int:
    return a + b

def multiply(a: int, b: int) -> int:
    return a * b
"#;
        let funcs = extract_function_signatures(python).unwrap();
        assert_eq!(funcs.len(), 2);
        assert_eq!(funcs[0].name, "add");
        assert_eq!(funcs[1].name, "multiply");
    }

    #[test]
    fn test_generate_rust_stubs() {
        let funcs = vec![FunctionSignature {
            name: "add".to_string(),
            args: Some("a: int, b: int".to_string()),
            return_type: Some("int".to_string()),
        }];

        let rust_code = generate_rust_stubs(&funcs);
        assert!(rust_code.contains("#[pyfunction]"));
        assert!(rust_code.contains("fn add"));
        assert!(rust_code.contains("todo!"));
        assert!(rust_code.contains("#[pymodule]"));
        assert!(rust_code.contains("wrap_pyfunction!(add"));
    }
}
