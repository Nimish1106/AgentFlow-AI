"""Deterministic paragraph-aware text chunking (SRS §32: Chunking step).

Plain Python, no LLM: the same document always produces the same chunks, so
re-ingestion is idempotent (chunk ids derive from source + chunk index).
"""

import re
from typing import List


def chunk_text(text: str, *, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Split ``text`` into chunks of at most ``chunk_size`` characters.

    Paragraphs (blank-line separated) are packed together while they fit; a
    paragraph longer than ``chunk_size`` is split on a sliding window with
    ``chunk_overlap`` characters carried between windows so no sentence is
    lost at a boundary.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: List[str] = []
    current = ""
    for paragraph in paragraphs:
        pieces = (
            [paragraph]
            if len(paragraph) <= chunk_size
            else _split_long_paragraph(paragraph, chunk_size, chunk_overlap)
        )
        for piece in pieces:
            candidate = f"{current}\n\n{piece}" if current else piece
            if len(candidate) <= chunk_size:
                current = candidate
            else:
                if current:
                    chunks.append(current)
                current = piece
    if current:
        chunks.append(current)
    return chunks


def _split_long_paragraph(paragraph: str, chunk_size: int, overlap: int) -> List[str]:
    """Sliding-window split for a single over-long paragraph."""
    step = chunk_size - overlap
    pieces = []
    for start in range(0, len(paragraph), step):
        piece = paragraph[start : start + chunk_size].strip()
        if piece:
            pieces.append(piece)
        if start + chunk_size >= len(paragraph):
            break
    return pieces
