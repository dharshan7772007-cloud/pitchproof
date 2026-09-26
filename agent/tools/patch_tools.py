"""
agent/tools/patch_tools.py
---------------------------
Safe utilities for representing and validating proposed code changes.

SECURITY RULES enforced by this module:
  - Never execute any code from the repository or from patches.
  - Never use shell=True or pass user-controlled strings to subprocess.
  - All target paths are validated to remain inside repo_root (no traversal).
  - Patches are always "proposed" — nothing is written to disk by this module.
  - Destructive operations require an explicit caller decision (not auto-applied).

Public API:
    ProposedChange         — dataclass representing a single file change
    PatchSet               — dataclass holding a collection of ProposedChanges
    validate_target_path(repo_root, rel_path) → Path  (raises on traversal)
    make_proposed_change(...)                  → ProposedChange
    make_patch_set(changes)                    → PatchSet
    preview_patch_set(patch_set)               → str   (human-readable preview)
    generate_unified_diff(original, modified, filename) → str
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------------------------
# Data structures  (proposed only — nothing touches disk)
# ---------------------------------------------------------------------------

@dataclass
class ProposedChange:
    """
    A single proposed file modification.

    Attributes:
        rel_path:      Relative path from repo root (POSIX separators).
        original_code: The original file content (None if file is new).
        proposed_code: The proposed replacement content.
        description:   Human-readable explanation of what the change does.
        is_new_file:   True when the file does not yet exist in the repo.
        applied:       Always False at creation; set True only when explicitly
                       written to disk by an authorised caller.
    """
    rel_path:      str
    original_code: Optional[str]
    proposed_code: str
    description:   str
    is_new_file:   bool   = False
    applied:       bool   = False   # Must remain False inside this module

    @property
    def unified_diff(self) -> str:
        """Lazily compute the unified diff for this change."""
        return generate_unified_diff(
            original=self.original_code or "",
            modified=self.proposed_code,
            filename=self.rel_path,
        )


@dataclass
class PatchSet:
    """
    An ordered collection of ProposedChanges for a single pipeline run.

    The patch set is the canonical representation of what the code fixer
    wants to do.  It is PROPOSED — not applied — until explicitly written.
    """
    changes: List[ProposedChange] = field(default_factory=list)
    validation_errors: List[str]  = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return len(self.validation_errors) == 0

    @property
    def affected_files(self) -> List[str]:
        return [c.rel_path for c in self.changes]

    def as_unified_diff(self) -> str:
        """Return all changes concatenated as a single unified-diff string."""
        return "\n".join(c.unified_diff for c in self.changes)


# ---------------------------------------------------------------------------
# Path validation  (security-critical)
# ---------------------------------------------------------------------------

def validate_target_path(repo_root: str, rel_path: str) -> Path:
    """
    Validate that *rel_path* resolves to a location inside *repo_root*.

    Raises:
        ValueError: if rel_path is empty, absolute, contains null bytes,
                    or resolves outside repo_root (path traversal attempt).
    """
    if not rel_path or not rel_path.strip():
        raise ValueError("Target path must not be empty.")

    # Reject null bytes — they can confuse OS path handling
    if "\x00" in rel_path:
        raise ValueError("Target path contains null bytes.")

    # Reject absolute paths outright
    if Path(rel_path).is_absolute():
        raise ValueError(f"Target path must be relative, got absolute: {rel_path!r}")

    root   = Path(repo_root).resolve()
    target = (root / rel_path).resolve()

    try:
        target.relative_to(root)
    except ValueError:
        raise ValueError(
            f"Path traversal detected: {rel_path!r} resolves outside "
            f"repository root {str(root)!r}."
        )

    return target


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def make_proposed_change(
    repo_root: str,
    rel_path: str,
    proposed_code: str,
    description: str,
    original_code: Optional[str] = None,
    is_new_file: bool = False,
) -> ProposedChange:
    """
    Create a validated ProposedChange.

    Validates the target path before constructing the change object.
    Raises ValueError if the path is invalid or outside repo_root.

    Args:
        repo_root:     Absolute path to the repository root.
        rel_path:      Relative path of the file to change.
        proposed_code: The full proposed content of the file.
        description:   What this change does.
        original_code: Current content (None for new files).
        is_new_file:   True if this creates a new file.

    Returns:
        A ProposedChange with applied=False.
    """
    validate_target_path(repo_root, rel_path)   # raises on traversal

    return ProposedChange(
        rel_path=rel_path,
        original_code=original_code,
        proposed_code=proposed_code,
        description=description,
        is_new_file=is_new_file,
        applied=False,
    )


def make_patch_set(
    repo_root: str,
    raw_changes: List[dict],
) -> PatchSet:
    """
    Build a PatchSet from a list of raw change dicts.

    Each dict must contain:
        rel_path      (str)
        proposed_code (str)
        description   (str)

    Optional keys:
        original_code (str | None)
        is_new_file   (bool)

    Malformed entries are skipped and an error is recorded in
    PatchSet.validation_errors — the function never raises.

    Args:
        repo_root:    Absolute path to the repository root.
        raw_changes:  List of raw change dicts from the LLM parser.

    Returns:
        PatchSet (valid=True only if all entries were accepted).
    """
    changes: List[ProposedChange] = []
    errors:  List[str]            = []

    for i, raw in enumerate(raw_changes):
        if not isinstance(raw, dict):
            errors.append(f"Entry {i}: expected dict, got {type(raw).__name__}")
            continue

        rel_path      = raw.get("rel_path", "")
        proposed_code = raw.get("proposed_code", "")
        description   = raw.get("description", "")

        if not rel_path:
            errors.append(f"Entry {i}: missing 'rel_path'")
            continue
        if not proposed_code:
            errors.append(f"Entry {i}: missing 'proposed_code'")
            continue

        try:
            change = make_proposed_change(
                repo_root=repo_root,
                rel_path=rel_path,
                proposed_code=proposed_code,
                description=description,
                original_code=raw.get("original_code"),
                is_new_file=bool(raw.get("is_new_file", False)),
            )
            changes.append(change)
        except ValueError as exc:
            errors.append(f"Entry {i} ({rel_path!r}): {exc}")

    return PatchSet(changes=changes, validation_errors=errors)


# ---------------------------------------------------------------------------
# Diff generation
# ---------------------------------------------------------------------------

def generate_unified_diff(
    original: str,
    modified: str,
    filename: str = "file",
) -> str:
    """
    Produce a unified diff string comparing *original* with *modified*.

    Args:
        original: Original file content (empty string for new files).
        modified: Proposed file content.
        filename: File path label used in the diff header.

    Returns:
        Unified diff string (may be empty if there are no changes).
    """
    original_lines = original.splitlines(keepends=True)
    modified_lines = modified.splitlines(keepends=True)

    diff_lines = list(difflib.unified_diff(
        original_lines,
        modified_lines,
        fromfile=f"a/{filename}",
        tofile=f"b/{filename}",
        lineterm="",
    ))

    return "\n".join(diff_lines)


# ---------------------------------------------------------------------------
# Human-readable preview
# ---------------------------------------------------------------------------

def preview_patch_set(patch_set: PatchSet) -> str:
    """
    Return a concise human-readable preview of *patch_set*.

    Shows validation errors (if any), then per-file diffs.
    Does NOT write anything to disk.
    """
    lines: List[str] = []

    if not patch_set.is_valid:
        lines.append("⚠️  VALIDATION ERRORS:")
        for err in patch_set.validation_errors:
            lines.append(f"  • {err}")
        lines.append("")

    if not patch_set.changes:
        lines.append("(No proposed changes)")
        return "\n".join(lines)

    lines.append(
        f"PROPOSED PATCH SET — {len(patch_set.changes)} file(s) "
        f"[STATUS: proposed, not applied]"
    )
    lines.append("=" * 60)

    for change in patch_set.changes:
        tag = "[NEW FILE]" if change.is_new_file else "[MODIFY]"
        lines.append(f"\n{tag} {change.rel_path}")
        lines.append(f"  {change.description}")
        diff = change.unified_diff
        if diff:
            lines.append(diff)
        else:
            lines.append("  (no diff — content unchanged)")

    return "\n".join(lines)
