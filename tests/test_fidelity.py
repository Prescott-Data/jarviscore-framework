"""Whole records or none — the budget never cuts inside one (#166).

A character limit applied inside a record decides what a reader may know by
counting bytes. These tests hold the selector to shedding whole records, naming
what it shed, and keeping what the caller declared essential.
"""

import pytest

from jarviscore.context.fidelity import Record, select_whole


def _records(count: int, size: int, priority: int = 1):
    return [Record(key=f"r{i}", text="x" * size, priority=priority) for i in range(count)]


class TestSelection:

    def test_everything_fits_when_the_budget_is_enough(self):
        selection = select_whole(_records(5, 10), budget=1000)
        assert selection.complete
        assert len(selection.kept) == 5
        assert selection.notice("the store") == ""

    def test_records_are_shed_whole(self):
        selection = select_whole(_records(10, 100), budget=350)
        assert len(selection.kept) == 3
        assert len(selection.withheld) == 7
        # Nothing kept is a fragment of anything.
        assert all(record.text == "x" * 100 for record in selection.kept)

    def test_nothing_is_shortened(self):
        selection = select_whole([Record(key="big", text="y" * 5000)], budget=100)
        assert selection.kept == []
        assert selection.withheld[0].text == "y" * 5000

    def test_priority_zero_survives_a_budget_it_exceeds(self):
        essential = Record(key="evidence", text="z" * 5000, priority=0)
        selection = select_whole([essential, *_records(3, 100)], budget=200)
        assert essential in selection.kept
        assert "evidence" not in [record.key for record in selection.withheld]

    def test_cheapest_first_keeps_the_most_complete_records(self):
        records = [
            Record(key="huge", text="h" * 900),
            *[Record(key=f"small{i}", text="s" * 100) for i in range(5)],
        ]
        selection = select_whole(records, budget=500)
        assert [record.key for record in selection.kept] == [f"small{i}" for i in range(5)]
        assert [record.key for record in selection.withheld] == ["huge"]

    def test_kept_records_keep_the_caller_order(self):
        """A prompt should read in the order it was written."""
        records = [
            Record(key="first", text="f" * 300),
            Record(key="second", text="s" * 10),
            Record(key="third", text="t" * 10),
        ]
        selection = select_whole(records, budget=100)
        assert [record.key for record in selection.kept] == ["second", "third"]

    def test_empty_input_is_complete(self):
        selection = select_whole([], budget=100)
        assert selection.complete
        assert selection.render() == ""


class TestNotice:

    def test_notice_names_what_is_missing_and_where_it_lives(self):
        selection = select_whole(_records(4, 100), budget=150)
        notice = selection.notice("the goal truth store")

        assert "3 of 4 records are not shown" in notice
        assert "`r1`" in notice
        assert "the goal truth store" in notice

    def test_notice_states_that_nothing_shown_was_shortened(self):
        notice = select_whole(_records(4, 100), budget=150).notice("the store")
        assert "Nothing shown has been shortened" in notice

    def test_notice_reports_the_real_cost(self):
        selection = select_whole(_records(4, 100), budget=150)
        assert selection.required == 400
        assert "400 of 150 characters" in selection.notice("the store")
