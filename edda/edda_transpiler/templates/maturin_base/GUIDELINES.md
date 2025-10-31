# Python to Rust Transpilation Guidelines

You are implementing Rust equivalents of Python functions using PyO3.

## Step-by-Step Process

1. **Review stubs in `src/lib.rs`** - Each function has a TODO comment with the original Python signature
2. **Implement Rust logic** - Match Python behavior exactly
3. **Run `validate_rust_equivalent` tool** - It will show test failures and differences
4. **Iterate until validation passes** - Fix issues based on validation output

## PyO3 Basics

Every Python-callable function needs:
```rust
#[pyfunction]
fn function_name(/* args */) -> PyResult<ReturnType> {
    // implementation
    Ok(result)
}
```

Then register in the module:
```rust
#[pymodule]
fn _rust_impl(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(function_name, m)?)?;
    Ok(())
}
```

## Type Mapping

| Python Type | Rust Type | Notes |
|-------------|-----------|-------|
| `int` | `i64` or `i32` | Use i64 for large numbers |
| `float` | `f64` | Standard float precision |
| `str` | `String` or `&str` | Use String for owned, &str for borrowed |
| `bool` | `bool` | Direct mapping |
| `list[T]` | `Vec<T>` | Homogeneous collections |
| `dict[K, V]` | `HashMap<K, V>` or `PyDict` | Use HashMap for simple dicts |
| `tuple` | `(T1, T2, ...)` | Fixed-size tuples |
| `None` | `Option<T>` | Use None variant |
| `numpy.ndarray` | `PyArray<T, D>` | Use rust-numpy crate |

## Common Patterns

### Lists and Iteration
```python
# Python
def double_items(items: list[int]) -> list[int]:
    return [x * 2 for x in items]
```

```rust
// Rust
#[pyfunction]
fn double_items(items: Vec<i64>) -> PyResult<Vec<i64>> {
    Ok(items.iter().map(|x| x * 2).collect())
}
```

### String Operations
```python
# Python
def uppercase(s: str) -> str:
    return s.upper()
```

```rust
// Rust
#[pyfunction]
fn uppercase(s: String) -> PyResult<String> {
    Ok(s.to_uppercase())
}
```

### Dictionaries
```python
# Python
def count_chars(s: str) -> dict[str, int]:
    counts = {}
    for char in s:
        counts[char] = counts.get(char, 0) + 1
    return counts
```

```rust
// Rust
use std::collections::HashMap;

#[pyfunction]
fn count_chars(s: String) -> PyResult<HashMap<char, i32>> {
    let mut counts = HashMap::new();
    for char in s.chars() {
        *counts.entry(char).or_insert(0) += 1;
    }
    Ok(counts)
}
```

### NumPy Arrays
```python
# Python
import numpy as np
def square_array(arr: np.ndarray) -> np.ndarray:
    return arr ** 2
```

```rust
// Rust
use numpy::{PyArray1, PyReadonlyArray1};
use pyo3::Python;

#[pyfunction]
fn square_array<'py>(
    py: Python<'py>,
    arr: PyReadonlyArray1<'py, f64>
) -> PyResult<&'py PyArray1<f64>> {
    let arr = arr.as_array();
    let squared = arr.mapv(|x| x * x);
    Ok(PyArray1::from_vec(py, squared.to_vec()))
}
```

### Error Handling
```python
# Python
def divide(a: float, b: float) -> float:
    if b == 0:
        raise ValueError("Cannot divide by zero")
    return a / b
```

```rust
// Rust
use pyo3::exceptions::PyValueError;

#[pyfunction]
fn divide(a: f64, b: f64) -> PyResult<f64> {
    if b == 0.0 {
        return Err(PyValueError::new_err("Cannot divide by zero"));
    }
    Ok(a / b)
}
```

### Optional Arguments
```python
# Python
def greet(name: str, greeting: str = "Hello") -> str:
    return f"{greeting}, {name}!"
```

```rust
// Rust
#[pyfunction]
#[pyo3(signature = (name, greeting="Hello"))]
fn greet(name: String, greeting: &str) -> PyResult<String> {
    Ok(format!("{}, {}!", greeting, name))
}
```

## Testing Pattern

Tests in `tests/test_equivalence.py` should:
1. Import the original Python module
2. Import the Rust implementation (`rust_impl._rust_impl`)
3. Test same inputs produce same outputs

Example:
```python
import original_module
from rust_impl import _rust_impl

def test_function_equivalence():
    test_inputs = [1, 2, 3]

    py_result = original_module.process(test_inputs)
    rust_result = _rust_impl.process(test_inputs)

    assert py_result == rust_result
```

## Performance Tips

1. **Avoid unnecessary copies** - Use `&[T]` instead of `Vec<T>` for read-only slices
2. **Use iterators** - They're often optimized better than explicit loops
3. **Preallocate vectors** - Use `Vec::with_capacity()` when size is known
4. **Consider parallel processing** - Use `rayon` for parallelizable operations

## Common Pitfalls

1. **Integer division** - Python 3's `/` is float division, use `//` for integer division
   - Rust: Use `/` for integers (truncates), cast to f64 for float division

2. **Unicode strings** - Python strings are Unicode, Rust &str is UTF-8
   - Use `.chars()` not `.bytes()` for character iteration

3. **Mutable vs immutable** - Python objects often mutable by default
   - Rust requires explicit `mut`, decide if you need mutation

4. **None handling** - Python functions can return None implicitly
   - Rust: Use `Option<T>` and explicit `None` variant

5. **Exceptions vs Results** - Python uses exceptions, Rust uses Result
   - Return `Err(PyErr::new::<PyValueError, _>("message"))` for errors

## Next Steps

1. Implement all TODO functions in `src/lib.rs`
2. Run `validate_rust_equivalent` to see if tests pass
3. Read validation output carefully - it shows exact differences
4. Fix issues and repeat until all tests pass
5. Once passing, the Rust implementation is equivalent to Python!
