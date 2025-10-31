# Examples

## sample_python.py

A simple Python module demonstrating typical functions that can be transpiled:

- `add(a, b)` - Basic arithmetic
- `multiply(a, b)` - Another arithmetic function
- `greet(name, greeting="Hello")` - String formatting with default args
- `process_list(items)` - List comprehension

## Usage Flow

1. **Agent reads** `sample_python.py`
2. **Agent calls** `scaffold_maturin_project`:
   ```json
   {
     "work_dir": "/tmp/rust_math",
     "python_source": "<contents of sample_python.py>",
     "python_module_name": "sample_python"
   }
   ```
3. **MCP returns** project structure with stubs in `/tmp/rust_math/src/lib.rs`:
   ```rust
   /// TODO: Implement equivalent to Python `add`
   /// Original signature: def add(a: int, b: int) -> int
   #[pyfunction]
   fn add(/* TODO: add typed arguments */) -> PyResult<()> {
       todo!("Implement add - see GUIDELINES.md for patterns")
   }
   ```
4. **Agent implements** based on guidelines:
   ```rust
   #[pyfunction]
   fn add(a: i64, b: i64) -> PyResult<i64> {
       Ok(a + b)
   }
   ```
5. **Agent calls** `validate_rust_equivalent`:
   ```json
   {
     "python_dir": "/path/to/original/python/project",
     "rust_dir": "/tmp/rust_math"
   }
   ```
6. **MCP validates** in sandbox and returns results
7. **Agent iterates** until all tests pass

## Expected Rust Implementation

After transpilation, `src/lib.rs` should contain:

```rust
use pyo3::prelude::*;

#[pyfunction]
fn add(a: i64, b: i64) -> PyResult<i64> {
    Ok(a + b)
}

#[pyfunction]
fn multiply(a: i64, b: i64) -> PyResult<i64> {
    Ok(a * b)
}

#[pyfunction]
#[pyo3(signature = (name, greeting="Hello"))]
fn greet(name: String, greeting: &str) -> PyResult<String> {
    Ok(format!("{}, {}!", greeting, name))
}

#[pyfunction]
fn process_list(items: Vec<i64>) -> PyResult<Vec<i64>> {
    Ok(items.iter().map(|x| x * 2).collect())
}

#[pymodule]
fn _rust_impl(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(add, m)?)?;
    m.add_function(wrap_pyfunction!(multiply, m)?)?;
    m.add_function(wrap_pyfunction!(greet, m)?)?;
    m.add_function(wrap_pyfunction!(process_list, m)?)?;
    Ok(())
}
```

## Testing

The equivalence tests would verify:

```python
import sample_python
from rust_impl import _rust_impl

def test_add_equivalence():
    assert sample_python.add(2, 3) == _rust_impl.add(2, 3)

def test_multiply_equivalence():
    assert sample_python.multiply(4, 5) == _rust_impl.multiply(4, 5)

def test_greet_equivalence():
    assert sample_python.greet("World") == _rust_impl.greet("World")
    assert sample_python.greet("Alice", "Hi") == _rust_impl.greet("Alice", "Hi")

def test_process_list_equivalence():
    assert sample_python.process_list([1, 2, 3]) == _rust_impl.process_list([1, 2, 3])
```
