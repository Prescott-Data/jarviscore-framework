"""
Chunking utilities for long-form document ingestion.
"""
from typing import List


def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[str]:
    """
    Chunk text by paragraph with fallback to fixed-size windows.
    """
    if not text:
        return []
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_size:
            current = f"{current}\n\n{para}".strip()
        else:
            if current:
                chunks.append(current)
            current = para
    if current:
        chunks.append(current)

    # Fallback: re-chunk any oversized chunks
    final_chunks: List[str] = []
    for c in chunks:
        if len(c) <= chunk_size:
            final_chunks.append(c)
            continue
        start = 0
        while start < len(c):
            end = min(len(c), start + chunk_size)
            final_chunks.append(c[start:end])
            start = max(end - overlap, start + 1)
    return final_chunks

