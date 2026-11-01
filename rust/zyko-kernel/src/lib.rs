//! ZYKO Rust kernel — optional accelerator, identical semantics to the
//! pure-Python fallback in `zyko/kernel/python_impl.py`. Parity is enforced
//! by tests/test_kernel.py whenever this extension is installed.
//!
//! Build & install (from the repository root):
//!     pip install maturin
//!     maturin develop --release -m rust/zyko-kernel/Cargo.toml

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyModule;

/// Same heuristic as the Python implementation: ~4 chars per token, floored
/// by the whitespace-separated word count.
#[pyfunction]
fn estimate_tokens(text: &str) -> i64 {
    if text.is_empty() {
        return 0;
    }
    let chars = text.chars().count() as i64;
    let words = text.split_whitespace().count() as i64;
    std::cmp::max(1, std::cmp::max((chars + 3) / 4, words))
}

#[pyfunction]
fn cosine_similarity(a: Vec<f64>, b: Vec<f64>) -> PyResult<f64> {
    if a.len() != b.len() || a.is_empty() {
        return Err(PyValueError::new_err("vectors must be non-empty and equal length"));
    }
    let dot: f64 = a.iter().zip(&b).map(|(x, y)| x * y).sum();
    let na: f64 = a.iter().map(|x| x * x).sum::<f64>().sqrt();
    let nb: f64 = b.iter().map(|y| y * y).sum::<f64>().sqrt();
    if na == 0.0 || nb == 0.0 {
        return Ok(0.0);
    }
    Ok(dot / (na * nb))
}

/// Indices of the k highest scores, best first (stable).
#[pyfunction]
fn top_k(scores: Vec<f64>, k: usize) -> Vec<usize> {
    let mut order: Vec<usize> = (0..scores.len()).collect();
    order.sort_by(|&i, &j| scores[j].partial_cmp(&scores[i]).unwrap_or(std::cmp::Ordering::Equal));
    order.truncate(k);
    // Vec<usize> converts to a Python list on every pyo3 release — no
    // version-sensitive PyList constructor APIs involved.
    order
}

#[pyfunction]
fn moving_average(values: Vec<f64>, window: usize) -> Vec<f64> {
    if window <= 1 || values.is_empty() {
        return values;
    }
    let mut out = Vec::with_capacity(values.len());
    let mut running = 0.0f64;
    for (i, value) in values.iter().enumerate() {
        running += value;
        if i >= window {
            running -= values[i - window];
        }
        out.push(running / std::cmp::min(i + 1, window) as f64);
    }
    out
}

#[pymodule]
fn zyko_kernel(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add_function(wrap_pyfunction!(estimate_tokens, module)?)?;
    module.add_function(wrap_pyfunction!(cosine_similarity, module)?)?;
    module.add_function(wrap_pyfunction!(top_k, module)?)?;
    module.add_function(wrap_pyfunction!(moving_average, module)?)?;
    module.add("__version__", env!("CARGO_PKG_VERSION"))?;
    Ok(())
}
