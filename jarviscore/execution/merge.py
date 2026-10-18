"""
Three-way line merge for text files.

Two people (or a person and an agent) changed the same file from a common
base. Changes to different lines are both kept; the same change made on both
sides is kept once; changes to overlapping lines that differ are a conflict.
Lines are compared exactly, as git does. Content that is not UTF-8 text is
not merged here.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import List, Optional, Tuple

Hunk = Tuple[int, int, List[str]]  # base[start:end] is replaced by lines


def _hunks(base: List[str], other: List[str]) -> List[Hunk]:
    matcher = SequenceMatcher(None, base, other, autojunk=False)
    return [
        (i1, i2, other[j1:j2])
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
        if tag != "equal"
    ]


def _apply(base: List[str], start: int, end: int, hunks: List[Hunk]) -> List[str]:
    """base[start:end] with one side's hunks applied (hunks lie within the span)."""
    out, pos = [], start
    for i1, i2, lines in hunks:
        out.extend(base[pos:i1])
        out.extend(lines)
        pos = i2
    out.extend(base[pos:end])
    return out


def merge_text(base: bytes, ours: bytes, theirs: bytes) -> Optional[bytes]:
    """The merged content, or None if the two changes conflict or are not text."""
    try:
        b = base.decode("utf-8").splitlines(keepends=True)
        o = ours.decode("utf-8").splitlines(keepends=True)
        t = theirs.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError:
        return None

    tagged = sorted(
        [(i1, i2, lines, "ours") for i1, i2, lines in _hunks(b, o)]
        + [(i1, i2, lines, "theirs") for i1, i2, lines in _hunks(b, t)],
        key=lambda hunk: (hunk[0], hunk[1]),
    )
    merged: List[str] = []
    pos = 0
    index = 0
    while index < len(tagged):
        start, end = tagged[index][0], tagged[index][1]
        group = [tagged[index]]
        index += 1
        # Hunks overlap the group, or insert at its very start: decide together.
        while index < len(tagged) and (tagged[index][0] < end or tagged[index][0] == start):
            group.append(tagged[index])
            end = max(end, tagged[index][1])
            index += 1
        mine = [(i1, i2, lines) for i1, i2, lines, side in group if side == "ours"]
        yours = [(i1, i2, lines) for i1, i2, lines, side in group if side == "theirs"]
        merged.extend(b[pos:start])
        if not yours:
            merged.extend(_apply(b, start, end, mine))
        elif not mine:
            merged.extend(_apply(b, start, end, yours))
        else:
            ours_span = _apply(b, start, end, mine)
            if ours_span != _apply(b, start, end, yours):
                return None
            merged.extend(ours_span)
        pos = end
    merged.extend(b[pos:])
    return "".join(merged).encode("utf-8")
