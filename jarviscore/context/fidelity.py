"""Fitting whole records into a bounded prompt.

Nothing here shortens a value. A character limit applied inside a record decides
what a reader may know by counting bytes, and the part it removes is simply gone
— a half payload is not a smaller payload, it is a different one. Planning and
evaluation are where that costs most: a planner reasons about work that has not
happened yet, and an evaluator issues a verdict on work that has. Both are
judging the record they were handed, so handing them a fragment does not make
them slightly less accurate, it makes them accurate about the wrong thing.

So a budget is spent on whole records, in priority order, and whatever does not
fit is named rather than halved. Naming matters: a reader told "6 of 41 facts
are not shown here" knows its picture is partial and can ask for the rest. A
reader handed a value cut at 200 characters has no idea anything is missing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, List, Sequence

__all__ = ["Record", "Selection", "select_whole"]


@dataclass(frozen=True)
class Record:
    """One indivisible item competing for room in a prompt.

    Attributes:
        key: How the record is named if it does not fit.
        text: The rendered record, always used whole or not at all.
        priority: Lower is kept first. 0 is never shed.
    """

    key: str
    text: str
    priority: int = 1

    @property
    def cost(self) -> int:
        return len(self.text)


@dataclass
class Selection:
    kept: List[Record] = field(default_factory=list)
    withheld: List[Record] = field(default_factory=list)
    budget: int = 0
    required: int = 0

    @property
    def complete(self) -> bool:
        return not self.withheld

    def render(self, separator: str = "\n") -> str:
        return separator.join(record.text for record in self.kept)

    def notice(self, where: str) -> str:
        """What is missing and where it still lives, in the reader's own prompt."""
        if self.complete:
            return ""
        names = ", ".join(f"`{record.key}`" for record in self.withheld)
        return (
            f"{len(self.withheld)} of {len(self.kept) + len(self.withheld)} records are "
            f"not shown here because the prompt budget could not hold them whole "
            f"({self.required} of {self.budget} characters at full fidelity): {names}. "
            f"Nothing shown has been shortened. The full records are unchanged in {where}."
        )


def select_whole(records: Iterable[Record], budget: int) -> Selection:
    """Spend ``budget`` on whole records, cheapest first within each priority.

    Priority 0 is always kept, even past the budget: a record the caller has
    declared essential is not something to trade away for room, and silently
    dropping it would be the same failure as cutting it.

    Cheapest-first within a priority keeps the greatest number of complete
    records rather than letting one large one crowd out many small ones. What
    survives is then restored to the caller's order — the reader's prompt should
    read in the order it was written, not in the order the budget was spent.
    """
    ordered = sorted(enumerate(records), key=lambda pair: (pair[1].priority, pair[1].cost))
    selection = Selection(budget=budget, required=sum(record.cost for _, record in ordered))
    spent = 0
    kept: List[tuple] = []
    withheld: List[tuple] = []
    for index, record in ordered:
        if record.priority == 0 or spent + record.cost <= budget:
            kept.append((index, record))
            spent += record.cost
        else:
            withheld.append((index, record))
    selection.kept = [record for _, record in sorted(kept)]
    selection.withheld = [record for _, record in sorted(withheld)]
    return selection
