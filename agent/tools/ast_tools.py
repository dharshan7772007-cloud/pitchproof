"""
agent/tools/ast_tools.py
-------------------------
Lightweight Python AST analysis utilities for Pitchproof.

Parses Python source files using the stdlib `ast` module (no code execution).
Reports syntax errors gracefully without crashing the overall analysis.

Public API:
    parse_file(path)                     → Optional[ParsedModule]
    parse_source(source, filename)       → Optional[ParsedModule]
    extract_functions(tree)              → List[FunctionInfo]
    extract_classes(tree)                → List[ClassInfo]
    extract_imports(tree)                → List[ImportInfo]
    extract_calls(tree)                  → List[CallInfo]
    score_file_relevance(parsed, terms)  → float

SECURITY: This module uses Python's `ast.parse()` only.
          It never exec()s, eval()s, or imports user code.
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class FunctionInfo:
    name: str
    lineno: int
    end_lineno: int
    args: List[str]         # Parameter names
    decorators: List[str]   # Decorator names (as strings)
    is_method: bool         # True when defined inside a class
    docstring: Optional[str]


@dataclass
class ClassInfo:
    name: str
    lineno: int
    end_lineno: int
    bases: List[str]        # Base class names (as strings)
    methods: List[str]      # Method names only
    docstring: Optional[str]


@dataclass
class ImportInfo:
    module: str             # Top-level module, e.g. "os" or "os.path"
    names: List[str]        # Imported names; empty list means "import module"
    lineno: int
    is_from: bool           # True for "from X import Y" style


@dataclass
class CallInfo:
    name: str               # Called function/method name (best-effort)
    lineno: int


@dataclass
class ParsedModule:
    """All extracted information from a single Python source file."""
    filename: str
    source_lines: int
    functions: List[FunctionInfo]   = field(default_factory=list)
    classes: List[ClassInfo]        = field(default_factory=list)
    imports: List[ImportInfo]       = field(default_factory=list)
    calls: List[CallInfo]           = field(default_factory=list)
    syntax_error: Optional[str]     = None   # Set when parsing failed


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _arg_name(arg: ast.arg) -> str:
    return arg.arg


def _decorator_name(node: ast.expr) -> str:
    """Best-effort string representation of a decorator."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_decorator_name(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return _decorator_name(node.func)
    return "<decorator>"


def _base_name(node: ast.expr) -> str:
    """Best-effort string representation of a base class expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_base_name(node.value)}.{node.attr}"
    return "<base>"


def _call_name(node: ast.Call) -> str:
    """Extract a readable name from a Call node."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return f"{_call_name_expr(func.value)}.{func.attr}"
    return "<call>"


def _call_name_expr(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_call_name_expr(node.value)}.{node.attr}"
    return "?"


def _get_docstring(node: ast.AST) -> Optional[str]:
    """Return the docstring of a function/class/module node, or None."""
    try:
        doc = ast.get_docstring(node)  # type: ignore[arg-type]
        if doc:
            return textwrap.shorten(doc, width=200, placeholder="…")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Extraction passes
# ---------------------------------------------------------------------------

def extract_functions(tree: ast.Module) -> List[FunctionInfo]:
    """Extract all function and async-function definitions from *tree*."""
    results: List[FunctionInfo] = []
    class_method_names: set[int] = set()  # node ids of methods

    # First pass: collect all method node ids
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    class_method_names.add(id(item))

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        results.append(FunctionInfo(
            name=node.name,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", node.lineno),
            args=[_arg_name(a) for a in node.args.args],
            decorators=[_decorator_name(d) for d in node.decorator_list],
            is_method=id(node) in class_method_names,
            docstring=_get_docstring(node),
        ))

    return results


def extract_classes(tree: ast.Module) -> List[ClassInfo]:
    """Extract all class definitions from *tree*."""
    results: List[ClassInfo] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        methods = [
            item.name
            for item in node.body
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        results.append(ClassInfo(
            name=node.name,
            lineno=node.lineno,
            end_lineno=getattr(node, "end_lineno", node.lineno),
            bases=[_base_name(b) for b in node.bases],
            methods=methods,
            docstring=_get_docstring(node),
        ))

    return results


def extract_imports(tree: ast.Module) -> List[ImportInfo]:
    """Extract all import statements from *tree*."""
    results: List[ImportInfo] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                results.append(ImportInfo(
                    module=alias.name,
                    names=[],
                    lineno=node.lineno,
                    is_from=False,
                ))
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            names = [alias.name for alias in node.names]
            results.append(ImportInfo(
                module=module,
                names=names,
                lineno=node.lineno,
                is_from=True,
            ))

    return results


def extract_calls(tree: ast.Module) -> List[CallInfo]:
    """Extract all function call sites from *tree* (best-effort)."""
    results: List[CallInfo] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            results.append(CallInfo(
                name=_call_name(node),
                lineno=node.lineno,
            ))

    return results


# ---------------------------------------------------------------------------
# Parsing entry points
# ---------------------------------------------------------------------------

def parse_source(source: str, filename: str = "<string>") -> Optional[ParsedModule]:
    """
    Parse Python *source* text and extract code structure.

    Returns a ParsedModule with syntax_error set if parsing fails.
    Never raises; always returns a value.
    """
    line_count = source.count("\n") + 1

    try:
        tree = ast.parse(source, filename=filename, type_comments=False)
    except SyntaxError as exc:
        return ParsedModule(
            filename=filename,
            source_lines=line_count,
            syntax_error=f"SyntaxError at line {exc.lineno}: {exc.msg}",
        )
    except Exception as exc:       # pragma: no cover – unexpected parser errors
        return ParsedModule(
            filename=filename,
            source_lines=line_count,
            syntax_error=f"ParseError: {exc}",
        )

    return ParsedModule(
        filename=filename,
        source_lines=line_count,
        functions=extract_functions(tree),
        classes=extract_classes(tree),
        imports=extract_imports(tree),
        calls=extract_calls(tree),
    )


def parse_file(abs_path: str) -> Optional[ParsedModule]:
    """
    Read and parse a Python file at *abs_path*.

    Returns None if the file cannot be read.
    Returns a ParsedModule with syntax_error set if parsing fails.
    """
    try:
        source = Path(abs_path).read_text(encoding="utf-8", errors="replace")
    except (OSError, PermissionError):
        return None

    return parse_source(source, filename=abs_path)


# ---------------------------------------------------------------------------
# Relevance scoring
# ---------------------------------------------------------------------------

def score_file_relevance(parsed: ParsedModule, search_terms: List[str]) -> float:
    """
    Return a 0.0–1.0 relevance score for *parsed* against *search_terms*.

    Scoring heuristic:
      - +0.3 per term found in a function/class name  (capped at 1.0)
      - +0.1 per term found in an import module name
      - +0.05 per term found in a docstring

    This is intentionally simple and fast — no LLM required.
    """
    if not search_terms or parsed.syntax_error:
        return 0.0

    terms = [t.lower() for t in search_terms if t.strip()]
    score = 0.0

    all_names = (
        [f.name.lower() for f in parsed.functions]
        + [c.name.lower() for c in parsed.classes]
    )
    for term in terms:
        if any(term in name for name in all_names):
            score += 0.3

    import_modules = [i.module.lower() for i in parsed.imports]
    for term in terms:
        if any(term in m for m in import_modules):
            score += 0.1

    docstrings = [
        (f.docstring or "").lower() for f in parsed.functions
    ] + [(c.docstring or "").lower() for c in parsed.classes]
    for term in terms:
        if any(term in d for d in docstrings):
            score += 0.05

    return min(score, 1.0)
