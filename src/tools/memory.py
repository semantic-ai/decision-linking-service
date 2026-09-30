"""File-backed, source-specific search guidelines with deduplicated lessons."""

import re
from datetime import datetime, timezone
from pathlib import Path


# ---------------------------------------------------------------------------
# Guideline file configuration
# ---------------------------------------------------------------------------


_GUIDELINES = Path(__file__).resolve().parent / "search-guidelines"
_MEMORY_FILES = {
    "codex": _GUIDELINES / "codex.md",
    "dsi": _GUIDELINES / "dsi.md",
    "ebesluitvorming": _GUIDELINES / "ebesluitvorming.md",
    "lblod": _GUIDELINES / "lblod.md",
    "reglement": _GUIDELINES / "reglement.md",
    "web_search": _GUIDELINES / "web_search.md",
}
_PRACTICAL_LESSONS_HEADING = "## Practical lessons"
_LESSON_ENTRY = re.compile(
    r"^- \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z - (.*)$",
    re.MULTILINE,
)


def _guideline_path(source: str) -> Path:
    """Return the guideline file for a supported source name."""
    try:
        return _MEMORY_FILES[source]
    except KeyError:
        raise ValueError(
            "Unsupported source "
            f"{source!r}; expected 'codex', 'dsi', 'ebesluitvorming', 'lblod', "
            "'reglement', or 'web_search'"
        ) from None


# ---------------------------------------------------------------------------
# Public memory operations
# ---------------------------------------------------------------------------


def fetch_memory(source: str) -> str:
    """Return the complete Markdown search guide for a supported source."""
    return _guideline_path(source).read_text(encoding="utf-8")


def write_memory(source: str, lesson: str) -> bool:
    """Append one timestamped lesson to a source's final learning section.

    Lessons must be non-empty single lines.  Exact lesson text is deduplicated
    within ``## Practical lessons`` without considering its timestamp.

    Returns
    -------
    bool
        ``True`` when the lesson is appended and ``False`` when it already
        exists verbatim.
    """
    lesson = lesson.strip()
    if not lesson:
        raise ValueError("Lesson must not be empty")
    if "\n" in lesson or "\r" in lesson:
        raise ValueError("Lesson must be a single line")

    path = _guideline_path(source)
    content = path.read_text(encoding="utf-8")
    section_start = content.rfind(_PRACTICAL_LESSONS_HEADING)
    if section_start == -1:
        raise ValueError(f"Memory file for {source!r} has no Practical lessons section")

    section = content[section_start:]
    if re.search(r"^##\s+", section[len(_PRACTICAL_LESSONS_HEADING) :], re.MULTILINE):
        raise ValueError("Practical lessons must be the final section")

    if any(match.group(1) == lesson for match in _LESSON_ENTRY.finditer(section)):
        return False

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    leading_newline = "" if content.endswith(("\n", "\r")) else "\n"
    with path.open("a", encoding="utf-8", newline="") as memory_file:
        memory_file.write(f"{leading_newline}- {timestamp} - {lesson}\n")

    return True
