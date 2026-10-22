"""Three-way line merge: different lines combine, overlapping disagreements conflict."""

from jarviscore.execution.merge import merge_text

PLAN = b"# Launch plan\n\n## Goals\nGrow signups\n\n## Dates\nShip Tuesday\n\n## Owners\nAlice\n"


def merge(ours, theirs, base=PLAN):
    return merge_text(base, ours, theirs)


def test_edits_to_different_sections_both_land():
    ours = PLAN.replace(b"Grow signups", b"Grow signups by 20%")
    theirs = PLAN.replace(b"Ship Tuesday", b"Ship Wednesday")
    assert merge(ours, theirs) == PLAN.replace(b"Grow signups", b"Grow signups by 20%").replace(
        b"Ship Tuesday", b"Ship Wednesday")


def test_the_same_edit_on_both_sides_is_kept_once():
    both = PLAN.replace(b"Alice", b"Alice and Bob")
    assert merge(both, both) == both


def test_different_edits_to_the_same_line_conflict():
    assert merge(PLAN.replace(b"Ship Tuesday", b"Ship Monday"),
                 PLAN.replace(b"Ship Tuesday", b"Ship Friday")) is None


def test_two_insertions_at_the_same_place_conflict_unless_identical():
    ours = PLAN.replace(b"## Owners\n", b"## Risks\nNone\n\n## Owners\n")
    theirs = PLAN.replace(b"## Owners\n", b"## Budget\n$10k\n\n## Owners\n")
    assert merge(ours, theirs) is None
    assert merge(ours, ours) == ours


def test_appends_and_prepends_combine():
    ours = b"Draft\n" + PLAN
    theirs = PLAN + b"\n## Notes\nTBD\n"
    assert merge(ours, theirs) == b"Draft\n" + PLAN + b"\n## Notes\nTBD\n"


def test_adjacent_line_edits_combine():
    base = b"a\nb\nc\nd\n"
    assert merge_text(base, b"a\nB\nc\nd\n", b"a\nb\nC\nd\n") == b"a\nB\nC\nd\n"


def test_one_side_deleting_lines_the_other_did_not_touch():
    ours = PLAN.replace(b"## Owners\nAlice\n", b"")
    theirs = PLAN.replace(b"Grow signups", b"Grow revenue")
    assert merge(ours, theirs) == PLAN.replace(b"## Owners\nAlice\n", b"").replace(
        b"Grow signups", b"Grow revenue")


def test_deleting_a_line_the_other_side_edited_conflicts():
    assert merge(PLAN.replace(b"Alice\n", b""), PLAN.replace(b"Alice", b"Carol")) is None


def test_no_trailing_newline_is_preserved():
    base = b"one\ntwo"
    assert merge_text(base, b"ONE\ntwo", b"one\ntwo!") == b"ONE\ntwo!"


def test_binary_content_is_not_merged():
    assert merge_text(b"\xff\x00", b"\xff\x01", b"\xff\x02") is None


def test_only_one_side_changed():
    ours = PLAN.replace(b"Alice", b"Dana")
    assert merge(ours, PLAN) == ours
    assert merge(PLAN, ours) == ours
