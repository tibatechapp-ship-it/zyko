"""Built-in agent tools — safe, cross-platform, stdlib-first.

Every tool executes inside the agent loop under three guards set by policy:
allow-list matching, per-call timeout, and output size caps. The ``shell``
tool is *dangerous* and is blocked unless a policy explicitly names it in
``tools.allow`` (a ``*`` wildcard never unlocks danger tools).
"""

from __future__ import annotations

import ast
import math
import operator
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from zyko.exceptions import ToolError
from zyko.log import get_logger

log = get_logger("agents.tools")

MAX_OUTPUT_CHARS = 20_000
DEFAULT_TIMEOUT_S = 30.0


@dataclass
class BuiltinTool:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]  # async fn(**args) -> str
    danger: bool = False

    def spec(self) -> dict[str, Any]:
        return {"name": self.name, "description": self.description, "parameters": self.parameters}


# ---------------------------------------------------------------- calculator
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_CONSTS = {"pi": math.pi, "e": math.e, "tau": math.tau}


def _safe_eval(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    ):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left, right = _safe_eval(node.left), _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("exponent too large")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _safe_eval(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    raise ValueError("unsupported expression element")


async def _calculator(expression: str, **_kw: Any) -> str:
    try:
        tree = ast.parse(expression, mode="eval")
        value = _safe_eval(tree)
    except (ValueError, SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise ToolError(f"calculator: {exc}") from exc
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value)


# ---------------------------------------------------------------- filesystem
def _resolve_in_workspace(path: str, workspace: Path) -> Path:
    candidate = (workspace / path).resolve()
    root = workspace.resolve()
    if not (candidate == root or root in candidate.parents):
        raise ToolError(f"path '{path}' escapes the agent workspace")
    return candidate


async def _read_file(path: str, workspace: str = ".", **_kw: Any) -> str:
    target = _resolve_in_workspace(path, Path(workspace))
    if not target.is_file():
        raise ToolError(f"no such file: {path}")
    data = target.read_text(encoding="utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
    return data


async def _write_file(path: str, content: str = "", workspace: str = ".", **_kw: Any) -> str:
    target = _resolve_in_workspace(path, Path(workspace))
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {path}"


async def _list_dir(path: str = ".", workspace: str = ".", **_kw: Any) -> str:
    target = _resolve_in_workspace(path or ".", Path(workspace))
    if not target.is_dir():
        raise ToolError(f"not a directory: {path}")
    entries = sorted(target.iterdir(), key=lambda p: (p.is_file(), p.name))[:500]
    return "\n".join(f"{'f' if p.is_file() else 'd'} {p.relative_to(workspace)}" for p in entries)


# ------------------------------------------------------------------- network
async def _http_get(url: str, max_bytes: int = 20_000, timeout: float = 20.0, **_kw: Any) -> str:
    if not url.lower().startswith(("http://", "https://")):
        raise ToolError("http_get: only http(s) URLs are allowed")
    import httpx

    async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text[: max(1, max_bytes)]


# --------------------------------------------------------------------- shell
async def _shell(command: str, timeout: float = DEFAULT_TIMEOUT_S, **_kw: Any) -> str:
    loop = __import__("asyncio").get_running_loop()

    def run() -> subprocess.CompletedProcess:
        # shell=True is the *documented purpose* of this tool (pipes, env
        # expansion, redirection). It is a `danger` tool: policy blocks it
        # unless a policy names "shell" explicitly in tools.allow — a "*"
        # wildcard never unlocks it — and every call is capped by timeout and
        # output size (see module docstring and tests/test_hardening.py).
        # (bandit reports B602 on the shell=True line — suppressed there.)
        return subprocess.run(
            command,
            shell=True,  # nosec B602
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    started = time.perf_counter()
    try:
        proc = await loop.run_in_executor(None, run)
    except subprocess.TimeoutExpired as exc:
        raise ToolError(f"shell: timed out after {timeout}s") from exc
    out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
    return f"exit={proc.returncode} ({time.perf_counter() - started:.1f}s)\n{out.strip()[:MAX_OUTPUT_CHARS]}"


# -------------------------------------------------------------------- registry
def builtin_tools(workspace: str = ".") -> dict[str, BuiltinTool]:
    tools = [
        BuiltinTool(
            "calculator",
            "Evaluate an arithmetic expression (+, -, *, /, //, %, **, parentheses, pi/e). No variables, no functions.",
            {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
            _calculator,
        ),
        BuiltinTool(
            "read_file",
            "Read a text file inside the agent workspace.",
            {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]},
            lambda **kw: _read_file(workspace=workspace, **kw),
        ),
        BuiltinTool(
            "write_file",
            "Write (or overwrite) a text file inside the agent workspace.",
            {
                "type": "object",
                "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                "required": ["path"],
            },
            lambda **kw: _write_file(workspace=workspace, **kw),
        ),
        BuiltinTool(
            "list_dir",
            "List a directory inside the agent workspace.",
            {"type": "object", "properties": {"path": {"type": "string", "default": "."}}},
            lambda **kw: _list_dir(workspace=workspace, **kw),
        ),
        BuiltinTool(
            "http_get",
            "Fetch a public http(s) URL and return the first bytes of the body (text).",
            {
                "type": "object",
                "properties": {
                    "url": {"type": "string"},
                    "max_bytes": {"type": "integer", "default": 20000},
                },
                "required": ["url"],
            },
            _http_get,
        ),
        BuiltinTool(
            "shell",
            "Run a shell command on this machine (DANGEROUS; needs explicit policy opt-in).",
            {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
            _shell,
            danger=True,
        ),
    ]
    return {tool.name: tool for tool in tools}


__all__ = ["BuiltinTool", "builtin_tools", "MAX_OUTPUT_CHARS"]
