import re
from dataclasses import dataclass

DEFAULT_OVERLAP_RATIO = 0.12

_TOKEN = re.compile(r"\S+")
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_FAQ_QUESTION = re.compile(r"^Q:\s*(.+?)\s*$")


@dataclass
class Chunk:
    text: str
    index: int
    section: str | None
    parent_text: str | None
    strategy: str  # fixed | heading | parent_child


@dataclass
class _Section:
    title: str | None
    text: str


def _split_windows(text: str, size_tokens: int, overlap_ratio: float) -> list[str]:
    """Split on whitespace tokens (a token approximation), preserving original spacing."""
    spans = [match.span() for match in _TOKEN.finditer(text)]
    if not spans:
        return []
    overlap = int(size_tokens * overlap_ratio)
    step = max(1, size_tokens - overlap)
    windows = []
    for start in range(0, len(spans), step):
        end = min(start + size_tokens, len(spans))
        windows.append(text[spans[start][0] : spans[end - 1][1]])
        if end == len(spans):
            break
    return windows


def _split_sections(text: str) -> list[_Section]:
    """Split at markdown headings and FAQ `Q:` lines. Heading-only blocks are dropped."""
    sections: list[_Section] = []
    title: str | None = None
    lines: list[str] = []

    def flush() -> None:
        has_body = any(line.strip() and not _HEADING.match(line) for line in lines)
        if has_body:
            sections.append(_Section(title, "\n".join(lines).strip()))

    for line in text.split("\n"):
        boundary = _HEADING.match(line) or _FAQ_QUESTION.match(line)
        if boundary:
            flush()
            title = boundary.group(1)
            lines = []
        lines.append(line)
    flush()
    return sections


def chunk_fixed(
    text: str,
    size_tokens: int = 512,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[Chunk]:
    windows = _split_windows(text, size_tokens, overlap_ratio)
    return [Chunk(w, i, None, None, "fixed") for i, w in enumerate(windows)]


def chunk_by_heading(
    text: str,
    max_tokens: int = 512,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    for section in _split_sections(text):
        for window in _split_windows(section.text, max_tokens, overlap_ratio):
            chunks.append(Chunk(window, len(chunks), section.title, None, "heading"))
    return chunks


def chunk_parent_child(
    text: str,
    child_tokens: int = 128,
    parent_tokens: int = 512,
    overlap_ratio: float = DEFAULT_OVERLAP_RATIO,
) -> list[Chunk]:
    """Small children are embedded for precise match; the parent is returned as context."""
    chunks: list[Chunk] = []
    for section in _split_sections(text):
        for parent in _split_windows(section.text, parent_tokens, overlap_ratio):
            for child in _split_windows(parent, child_tokens, overlap_ratio):
                chunks.append(
                    Chunk(child, len(chunks), section.title, parent, "parent_child")
                )
    return chunks


STRATEGIES = {
    "fixed": chunk_fixed,
    "heading": chunk_by_heading,
    "parent_child": chunk_parent_child,
}


def chunk_text(text: str, strategy: str) -> list[Chunk]:
    if strategy not in STRATEGIES:
        raise ValueError(f"Unknown chunk strategy: {strategy}")
    return STRATEGIES[strategy](text)
