"""
agent/tools/git_tools.py
-------------------------
Safe local repository inspection utilities for Pitchproof.

SECURITY RULES enforced by this module:
  - Never execute code from the analysed repository.
  - Never use shell=True or pass user-supplied strings to subprocess.
  - No path traversal: all returned paths are resolved relative to repo_root.
  - Binary / unreadable / oversized files are skipped, never crashing analysis.

Public API:
    validate_repo_path(path)  → None  (raises ValueError on bad input)
    list_source_files(path)   → List[RepoFile]
    read_file_safe(path)      → Optional[str]
    detect_language(files)    → str
    get_repo_info(path)       → RepoInfo
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directories to skip entirely during traversal
IGNORED_DIRS: frozenset[str] = frozenset({
    ".git",
    ".venv",
    "venv",
    "env",
    "ENV",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "build",
    "dist",
    ".eggs",
    "*.egg-info",
    ".tox",
    ".nox",
    "htmlcov",
    "site",
    "target",           # Rust / Java Maven
    ".idea",
    ".vscode",
})

# File extensions considered source code (ordered by priority for language detection)
SOURCE_EXTENSIONS: tuple[str, ...] = (
    ".py",
    ".js", ".ts", ".jsx", ".tsx",
    ".java",
    ".go",
    ".rs",
    ".rb",
    ".cs",
    ".cpp", ".cc", ".cxx", ".c", ".h", ".hpp",
    ".kt", ".kts",
    ".swift",
    ".scala",
    ".php",
    ".sh", ".bash",
    ".yaml", ".yml",
    ".json",
    ".toml",
    ".md",
)

# Language name mapped from primary extension
_EXT_TO_LANG: dict[str, str] = {
    ".py":   "python",
    ".js":   "javascript",
    ".ts":   "typescript",
    ".jsx":  "javascript",
    ".tsx":  "typescript",
    ".java": "java",
    ".go":   "go",
    ".rs":   "rust",
    ".rb":   "ruby",
    ".cs":   "csharp",
    ".cpp":  "cpp", ".cc": "cpp", ".cxx": "cpp",
    ".c":    "c",
    ".kt":   "kotlin", ".kts": "kotlin",
    ".swift":"swift",
    ".scala":"scala",
    ".php":  "php",
    ".sh":   "shell", ".bash": "shell",
}

# Maximum bytes read per file (256 KB — prevents loading large generated files)
MAX_FILE_BYTES = 256 * 1024

# Maximum number of source files returned
MAX_FILES = 200


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RepoFile:
    """Metadata about a single source file in the repository."""
    rel_path: str           # Relative path from repo_root  (POSIX separators)
    abs_path: str           # Absolute OS path
    extension: str          # Lowercased file extension, e.g. ".py"
    size_bytes: int         # File size on disk
    is_test: bool           # True if file appears to be a test file


@dataclass
class RepoInfo:
    """High-level information about the inspected repository."""
    root: str                           # Absolute path to repo root
    is_git_repo: bool                   # True if a .git directory was found
    primary_language: str               # Best-guess primary language
    total_source_files: int             # Count of discovered source files
    files: List[RepoFile] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_repo_path(path: str) -> Path:
    """
    Validate that *path* is a readable directory.

    Raises:
        ValueError: if the path is empty, doesn't exist, or is not a directory.
        PermissionError: if the directory cannot be accessed.
    """
    if not path or not path.strip():
        raise ValueError("Repository path must not be empty.")

    p = Path(path).resolve()

    if not p.exists():
        raise ValueError(f"Repository path does not exist: {p}")

    if not p.is_dir():
        raise ValueError(f"Repository path is not a directory: {p}")

    # Quick permission check — os.access is advisory but sufficient for early validation
    if not os.access(p, os.R_OK | os.X_OK):
        raise PermissionError(f"Repository path is not readable: {p}")

    return p


# ---------------------------------------------------------------------------
# File discovery
# ---------------------------------------------------------------------------

def _is_ignored_dir(name: str) -> bool:
    """Return True if a directory name should be skipped."""
    return name in IGNORED_DIRS or name.endswith(".egg-info")


def _is_test_file(rel_path: str) -> bool:
    """Heuristic: file is a test if its name starts/ends with 'test'."""
    stem = Path(rel_path).stem.lower()
    return stem.startswith("test") or stem.endswith("test") or stem.endswith("_tests")


def list_source_files(repo_root: str) -> List[RepoFile]:
    """
    Walk *repo_root* and return a list of source files (up to MAX_FILES).

    Ignored directories are skipped entirely.
    Binary and unreadable files are excluded silently.

    Args:
        repo_root: Absolute or relative path to the repository root.

    Returns:
        List of RepoFile, ordered by relative path.
    """
    root = validate_repo_path(repo_root)
    found: List[RepoFile] = []

    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        # Prune ignored dirs in-place so os.walk skips them
        dirnames[:] = [d for d in dirnames if not _is_ignored_dir(d)]

        for filename in filenames:
            if len(found) >= MAX_FILES:
                break

            abs_path = Path(dirpath) / filename
            ext = abs_path.suffix.lower()

            if ext not in SOURCE_EXTENSIONS:
                continue

            # Guard: skip symlinks pointing outside root (path traversal)
            try:
                real = abs_path.resolve()
                real.relative_to(root)          # raises ValueError if outside
            except (ValueError, OSError):
                continue

            try:
                size = abs_path.stat().st_size
            except OSError:
                continue

            # Skip empty and oversized files
            if size == 0 or size > MAX_FILE_BYTES:
                continue

            rel = real.relative_to(root).as_posix()
            found.append(RepoFile(
                rel_path=rel,
                abs_path=str(real),
                extension=ext,
                size_bytes=size,
                is_test=_is_test_file(rel),
            ))

    return sorted(found, key=lambda f: f.rel_path)


# ---------------------------------------------------------------------------
# Safe file reading
# ---------------------------------------------------------------------------

def read_file_safe(abs_path: str, max_bytes: int = MAX_FILE_BYTES) -> Optional[str]:
    """
    Read a text file safely, returning None on any error.

    - Respects max_bytes limit.
    - Silently returns None for binary / unreadable files.
    - Never executes the file.
    """
    try:
        p = Path(abs_path)
        if p.stat().st_size > max_bytes:
            return None

        raw = p.read_bytes()

        # Cheap binary-detection: look for null bytes in the first 8 KB
        if b"\x00" in raw[:8192]:
            return None

        return raw.decode("utf-8", errors="replace")
    except (OSError, PermissionError):
        return None


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------

def detect_language(files: List[RepoFile]) -> str:
    """
    Return the most common source language across *files*.
    Falls back to "unknown" if no recognisable extensions are found.
    """
    counts: dict[str, int] = {}
    for f in files:
        lang = _EXT_TO_LANG.get(f.extension)
        if lang:
            counts[lang] = counts.get(lang, 0) + 1

    if not counts:
        return "unknown"

    return max(counts, key=lambda k: counts[k])


# ---------------------------------------------------------------------------
# High-level entry point
# ---------------------------------------------------------------------------

def get_repo_info(repo_root: str) -> RepoInfo:
    """
    Gather high-level repository information.

    Args:
        repo_root: Path to the repository root directory.

    Returns:
        RepoInfo with file list, language, and git status.
    """
    root = validate_repo_path(repo_root)
    files = list_source_files(str(root))
    language = detect_language(files)
    is_git = (root / ".git").exists()

    return RepoInfo(
        root=str(root),
        is_git_repo=is_git,
        primary_language=language,
        total_source_files=len(files),
        files=files,
    )
