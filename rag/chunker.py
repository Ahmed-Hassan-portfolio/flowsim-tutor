"""Adaptive Markdown chunker for FlowSim documentation.

Splits documents on ``---`` separators, parses the header hierarchy at all
levels (``##`` through ``######``), preserves numbered step sequences, and
merges ``Model description`` + ``How to use`` pairs into a single chunk so the
retriever can return a self-contained answer.

The chunker is content-agnostic: it works on any Markdown corpus that follows
the same structural conventions.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

MAX_TOKENS = 1000
OVERLAP_TOKENS = 150
MERGE_MAX_TOKENS = 1200

STEP_PATTERN = re.compile(r"^\s*(\d+)\.\s", re.MULTILINE)
HEADER_PATTERN = re.compile(r"^(#{2,6})\s+(.+)$", re.MULTILINE)
H1_TITLE_PATTERN = re.compile(r"^#\s+.+$", re.MULTILINE)
SEPARATOR = re.compile(r"\n---\n")


@dataclass
class Chunk:
    """A single chunk of documentation with metadata."""

    id: str
    text: str
    metadata: dict
    token_count: int


@dataclass
class _Section:
    """Internal representation of a parsed section."""

    heading: str
    level: int  # 2-6
    text: str
    token_count: int
    section_path: str
    parent_heading: str


def chunk_file(file_path: Path) -> List[Chunk]:
    """Chunk a single Markdown file into metadata-rich chunks."""
    content = file_path.read_text(encoding="utf-8")
    file_name = file_path.stem
    sections = _parse_sections(content, file_name)
    return _sections_to_chunks(sections, file_name)


def chunk_all(docs_dir: Path) -> List[Chunk]:
    """Chunk all Markdown files in a directory."""
    all_chunks: List[Chunk] = []
    for md_file in sorted(docs_dir.glob("*.md")):
        all_chunks.extend(chunk_file(md_file))
    return all_chunks


def _estimate_tokens(text: str) -> int:
    """Estimate token count by whitespace splitting."""
    return len(text.split())


def _parse_sections(content: str, file_name: str) -> List[_Section]:
    """Parse Markdown content into sections using ``---`` separators and headers."""
    raw_blocks = SEPARATOR.split(content)

    sections: List[_Section] = []
    ancestors: Dict[int, str] = {}
    skip_toc = False

    for block in raw_blocks:
        block = block.strip()
        if not block:
            continue

        header_match = HEADER_PATTERN.search(block)
        if not header_match:
            continue

        level = len(header_match.group(1))
        heading = header_match.group(2).strip()

        if heading == "Table of Contents":
            skip_toc = True
            continue
        if skip_toc:
            skip_toc = False

        ancestors = {k: v for k, v in ancestors.items() if k < level}
        ancestors[level] = heading

        path_parts = [file_name]
        for lvl in sorted(ancestors.keys()):
            path_parts.append(ancestors[lvl])
        section_path = " > ".join(path_parts)

        parent_levels = sorted(k for k in ancestors.keys() if k < level)
        parent_heading = ancestors[parent_levels[-1]] if parent_levels else ""

        text_after_header = block[header_match.end():].strip()
        text_after_header = _strip_redundant_h1(text_after_header)

        if not text_after_header:
            continue

        sections.append(
            _Section(
                heading=heading,
                level=level,
                text=text_after_header,
                token_count=_estimate_tokens(text_after_header),
                section_path=section_path,
                parent_heading=parent_heading,
            )
        )

    return sections


def _strip_redundant_h1(text: str) -> str:
    """Drop a redundant ``# Title`` line if it duplicates the section heading."""
    lines = text.split("\n", 2)
    if lines and re.match(r"^#\s+\S", lines[0]):
        rest = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
        return rest
    return text


def _sections_to_chunks(sections: List[_Section], file_name: str) -> List[Chunk]:
    """Convert parsed sections to chunks with merging and splitting rules."""
    chunks: List[Chunk] = []
    seen_ids: Dict[str, int] = {}
    i = 0

    while i < len(sections):
        section = sections[i]

        if i + 1 < len(sections) and _is_mergeable_pair(section, sections[i + 1]):
            next_section = sections[i + 1]
            combined_tokens = section.token_count + next_section.token_count

            if combined_tokens <= MERGE_MAX_TOKENS:
                chunk = _make_merged_chunk(section, next_section, file_name, seen_ids)
                chunks.append(chunk)
                i += 2
                continue
            else:
                paired_id_b = _make_unique_id(
                    _base_id_from_path(next_section.section_path), seen_ids, peek=True
                )
                if section.token_count > MAX_TOKENS:
                    a_chunks = _split_large_section(section, file_name, seen_ids)
                else:
                    a_chunks = [_make_chunk(section, file_name, seen_ids)]
                for c in a_chunks:
                    c.metadata["paired_with"] = paired_id_b
                chunks.extend(a_chunks)

                paired_id_a = a_chunks[0].id
                if next_section.token_count > MAX_TOKENS:
                    b_chunks = _split_large_section(next_section, file_name, seen_ids)
                else:
                    b_chunks = [_make_chunk(next_section, file_name, seen_ids)]
                for c in b_chunks:
                    c.metadata["paired_with"] = paired_id_a
                chunks.extend(b_chunks)
                i += 2
                continue

        if section.token_count <= MAX_TOKENS:
            chunks.append(_make_chunk(section, file_name, seen_ids))
            i += 1
            continue

        sub_chunks = _split_large_section(section, file_name, seen_ids)
        chunks.extend(sub_chunks)
        i += 1

    return chunks


def _is_mergeable_pair(a: _Section, b: _Section) -> bool:
    """Two consecutive sections form a ``Model description`` + ``How to use`` pair."""
    a_lower = a.heading.lower().strip()
    b_lower = b.heading.lower().strip()

    is_pair = (
        a_lower == "model description" and b_lower == "how to use"
    ) or (a_lower == "how to use" and b_lower == "model description")

    same_parent = a.parent_heading == b.parent_heading
    same_level = a.level == b.level

    return is_pair and same_parent and same_level


def _base_id_from_path(section_path: str) -> str:
    return _slugify(section_path)


def _make_unique_id(base_id: str, seen_ids: Dict[str, int], peek: bool = False) -> str:
    if peek:
        count = seen_ids.get(base_id, 0)
        return base_id if count == 0 else f"{base_id}__{count}"

    if base_id not in seen_ids:
        seen_ids[base_id] = 1
        return base_id

    idx = seen_ids[base_id]
    seen_ids[base_id] = idx + 1
    return f"{base_id}__{idx}"


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def _make_chunk(
    section: _Section,
    file_name: str,
    seen_ids: Dict[str, int],
    sub_index: int = 0,
    total_subs: int = 1,
) -> Chunk:
    base_id = _base_id_from_path(section.section_path)
    if total_subs > 1:
        base_id = f"{base_id}__part{sub_index}"

    chunk_id = _make_unique_id(base_id, seen_ids)

    path_parts = section.section_path.split(" > ")
    h2_header = path_parts[1] if len(path_parts) > 1 else section.heading
    h3_header = path_parts[2] if len(path_parts) > 2 else ""

    return Chunk(
        id=chunk_id,
        text=section.text,
        token_count=section.token_count,
        metadata={
            "source_file": f"{file_name}.md",
            "section_path": section.section_path,
            "heading_level": section.level,
            "h2_header": h2_header,
            "h3_header": h3_header,
            "chunk_index": sub_index,
            "total_sub_chunks": total_subs,
            "content_type": "section",
            "has_steps": _has_numbered_steps(section.text),
            "token_count": section.token_count,
        },
    )


def _make_merged_chunk(
    a: _Section, b: _Section, file_name: str, seen_ids: Dict[str, int]
) -> Chunk:
    parent_path = " > ".join(a.section_path.split(" > ")[:-1])
    base_id = _base_id_from_path(parent_path) + "__merged"
    chunk_id = _make_unique_id(base_id, seen_ids)

    merged_text = f"### {a.heading}\n\n{a.text}\n\n### {b.heading}\n\n{b.text}"
    merged_tokens = _estimate_tokens(merged_text)
    merged_path = parent_path + f" > {a.heading} + {b.heading}"

    path_parts = merged_path.split(" > ")
    h2_header = path_parts[1] if len(path_parts) > 1 else a.parent_heading
    h3_header = path_parts[2] if len(path_parts) > 2 else ""

    return Chunk(
        id=chunk_id,
        text=merged_text,
        token_count=merged_tokens,
        metadata={
            "source_file": f"{file_name}.md",
            "section_path": merged_path,
            "heading_level": a.level,
            "h2_header": h2_header,
            "h3_header": h3_header,
            "chunk_index": 0,
            "total_sub_chunks": 1,
            "content_type": "merged",
            "has_steps": _has_numbered_steps(a.text) or _has_numbered_steps(b.text),
            "token_count": merged_tokens,
            "is_merged": True,
        },
    )


def _has_numbered_steps(text: str) -> bool:
    matches = STEP_PATTERN.findall(text)
    if len(matches) < 2:
        return False
    numbers = [int(m) for m in matches]
    consecutive = sum(
        1 for i in range(1, len(numbers)) if numbers[i] == numbers[i - 1] + 1
    )
    return consecutive >= 1


def _split_large_section(
    section: _Section, file_name: str, seen_ids: Dict[str, int]
) -> List[Chunk]:
    paragraphs = _split_preserving_steps(section.text)
    sub_chunks_text = _group_paragraphs(paragraphs, MAX_TOKENS, OVERLAP_TOKENS)

    total_subs = len(sub_chunks_text)
    chunks = []
    for idx, text in enumerate(sub_chunks_text):
        chunk = _make_chunk(
            section, file_name, seen_ids, sub_index=idx, total_subs=total_subs
        )
        chunk.text = text
        chunk.token_count = _estimate_tokens(text)
        chunk.metadata["token_count"] = chunk.token_count
        chunk.metadata["has_steps"] = _has_numbered_steps(text)
        chunks.append(chunk)

    return chunks


def _split_preserving_steps(text: str) -> List[str]:
    raw_paragraphs = re.split(r"\n\n+", text.strip())

    merged: List[str] = []
    current_steps: List[str] = []

    for para in raw_paragraphs:
        stripped = para.strip()
        if re.match(r"^\s*\d+[\.\)]\s", stripped):
            current_steps.append(para)
        else:
            if current_steps:
                merged.append("\n\n".join(current_steps))
                current_steps = []
            merged.append(para)

    if current_steps:
        merged.append("\n\n".join(current_steps))

    return [p for p in merged if p.strip()]


def _group_paragraphs(
    paragraphs: List[str], max_tokens: int, overlap_tokens: int
) -> List[str]:
    if not paragraphs:
        return []

    sub_chunks: List[str] = []
    current_parts: List[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _estimate_tokens(para)

        if current_tokens + para_tokens > max_tokens and current_parts:
            sub_chunks.append("\n\n".join(current_parts))

            overlap_parts = _get_overlap_tail(current_parts, overlap_tokens)
            current_parts = overlap_parts
            current_tokens = sum(_estimate_tokens(p) for p in current_parts)

        current_parts.append(para)
        current_tokens += para_tokens

    if current_parts:
        sub_chunks.append("\n\n".join(current_parts))

    return sub_chunks


def _get_overlap_tail(parts: List[str], overlap_tokens: int) -> List[str]:
    tail: List[str] = []
    total = 0
    for part in reversed(parts):
        tokens = _estimate_tokens(part)
        if total + tokens > overlap_tokens:
            break
        tail.insert(0, part)
        total += tokens
    return tail
