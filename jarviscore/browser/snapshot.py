"""
Role-based snapshot generation and ref assignment.
Port of OpenClaw's pw-role-snapshot.ts to Python.
"""
import re
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Set, Tuple

# Interactive roles that should always get refs
INTERACTIVE_ROLES: Set[str] = {
    "button", "link", "textbox", "checkbox", "radio", "combobox",
    "listbox", "menuitem", "menuitemcheckbox", "menuitemradio",
    "option", "searchbox", "slider", "spinbutton", "switch",
    "tab", "treeitem"
}

# Content roles that get refs only when named
CONTENT_ROLES: Set[str] = {
    "heading", "cell", "gridcell", "columnheader", "rowheader",
    "listitem", "article", "region", "main", "navigation"
}

# Structural roles (typically unnamed containers)
STRUCTURAL_ROLES: Set[str] = {
    "generic", "group", "list", "table", "row", "rowgroup",
    "grid", "treegrid", "menu", "menubar", "toolbar", "tablist",
    "tree", "directory", "document", "application", "presentation", "none"
}


@dataclass
class RoleRef:
    """Reference to a UI element by role."""
    role: str
    name: Optional[str] = None
    nth: Optional[int] = None  # Index when role+name has duplicates


@dataclass
class RoleSnapshotOptions:
    """Options for snapshot generation."""
    interactive_only: bool = False  # Only include interactive elements
    max_depth: Optional[int] = None  # Maximum depth to include
    compact: bool = False  # Remove unnamed structural elements
    max_name_length: Optional[int] = None  # Truncate element names beyond this length


@dataclass
class RoleSnapshotResult:
    """Result of snapshot generation."""
    snapshot: str
    refs: Dict[str, RoleRef]
    stats: Dict[str, int] = field(default_factory=dict)


class RoleNameTracker:
    """Tracks role+name combinations for nth index assignment."""
    
    def __init__(self):
        self._counts: Dict[str, int] = {}
        self._refs_by_key: Dict[str, List[str]] = {}
    
    def _get_key(self, role: str, name: Optional[str]) -> str:
        return f"{role}:{name or ''}"
    
    def get_next_index(self, role: str, name: Optional[str]) -> int:
        key = self._get_key(role, name)
        current = self._counts.get(key, 0)
        self._counts[key] = current + 1
        return current
    
    def track_ref(self, role: str, name: Optional[str], ref: str) -> None:
        key = self._get_key(role, name)
        if key not in self._refs_by_key:
            self._refs_by_key[key] = []
        self._refs_by_key[key].append(ref)
    
    def get_duplicate_keys(self) -> Set[str]:
        return {key for key, refs in self._refs_by_key.items() if len(refs) > 1}


def _get_indent_level(line: str) -> int:
    """Get indentation level (2 spaces = 1 level)."""
    match = re.match(r'^(\s*)', line)
    return len(match.group(1)) // 2 if match else 0


def _parse_aria_line(line: str) -> Optional[Tuple[str, str, Optional[str], str]]:
    """
    Parse an aria snapshot line.
    Returns: (prefix, role, name, suffix) or None if not a valid line.
    """
    # Pattern: "  - role" or "  - role \"name\"" with optional suffix
    match = re.match(r'^(\s*-\s*)(\w+)(?:\s+"([^"]*)")?(.*)$', line)
    if not match:
        return None
    
    prefix, role_raw, name, suffix = match.groups()
    
    # Skip comments/close tags
    if role_raw.startswith('/'):
        return None
    
    return prefix, role_raw, name, suffix or ""


def _parse_ai_line(line: str) -> Optional[Tuple[str, Optional[str], str, Optional[int]]]:
    """
    Parse an AI snapshot line with [ref=...] markers.
    Returns: (role, name, ref, nth) or None.
    """
    match = re.match(r'^\s*-\s*([^\s"[\]]+)(?:\s+"([^"]*)")?(.*)$', line)
    if not match:
        return None
    role_raw, name, suffix = match.groups()
    if role_raw.startswith("/"):
        return None
    ref_match = re.search(r"\[ref=([^\]]+)\]", suffix or "")
    if not ref_match:
        return None
    ref = ref_match.group(1).strip()
    nth_match = re.search(r"\[nth=(\d+)\]", suffix or "")
    nth = int(nth_match.group(1)) if nth_match else None
    return role_raw, name, ref, nth


def remove_nth_from_non_duplicates(refs: Dict[str, RoleRef], tracker: RoleNameTracker) -> None:
    """Remove nth from refs where there's only one instance."""
    duplicates = tracker.get_duplicate_keys()
    for ref, data in refs.items():
        key = tracker._get_key(data.role, data.name)
        if key not in duplicates:
            data.nth = None


def compact_tree(tree: str) -> str:
    """Remove branches without refs."""
    lines = tree.split('\n')
    result: List[str] = []
    
    for i, line in enumerate(lines):
        # Always keep lines with refs
        if '[ref=' in line:
            result.append(line)
            continue
        
        # Keep lines with actual content (role: "name")
        if ':' in line and not line.rstrip().endswith(':'):
            result.append(line)
            continue
        
        # Check if this structural element has relevant children
        current_indent = _get_indent_level(line)
        has_relevant_children = False
        
        for j in range(i + 1, len(lines)):
            child_indent = _get_indent_level(lines[j])
            if child_indent <= current_indent:
                break
            if '[ref=' in lines[j]:
                has_relevant_children = True
                break
        
        if has_relevant_children:
            result.append(line)
    
    return '\n'.join(result)


def _truncate_name(name: Optional[str], max_length: Optional[int]) -> Optional[str]:
    """Truncate an element name for display, preserving full text in RoleRef."""
    if not name or not max_length or len(name) <= max_length:
        return name
    return name[:max_length].rstrip() + "\u2026"


def build_role_snapshot_from_aria(
    aria_snapshot: str,
    options: Optional[RoleSnapshotOptions] = None
) -> RoleSnapshotResult:
    """
    Build a role snapshot from Playwright's aria snapshot.
    Assigns refs (e1, e2, ...) to interactive elements.
    """
    options = options or RoleSnapshotOptions()
    lines = aria_snapshot.split('\n')
    refs: Dict[str, RoleRef] = {}
    tracker = RoleNameTracker()
    max_len = options.max_name_length

    counter = [0]  # Mutable counter for closure

    def next_ref() -> str:
        counter[0] += 1
        return f"e{counter[0]}"

    # Interactive-only mode: flat list of interactive elements
    if options.interactive_only:
        result_lines: List[str] = []

        for line in lines:
            depth = _get_indent_level(line)
            if options.max_depth is not None and depth > options.max_depth:
                continue

            parsed = _parse_aria_line(line)
            if not parsed:
                continue

            prefix, role_raw, name, suffix = parsed
            role = role_raw.lower()

            if role not in INTERACTIVE_ROLES:
                continue

            ref = next_ref()
            nth = tracker.get_next_index(role, name)
            tracker.track_ref(role, name, ref)

            refs[ref] = RoleRef(role=role, name=name, nth=nth)

            display_name = _truncate_name(name, max_len)
            enhanced = f"- {role_raw}"
            if display_name:
                enhanced += f' "{display_name}"'
            enhanced += f' [ref={ref}]'
            if nth > 0:
                enhanced += f' [nth={nth}]'
            if '[' in suffix:
                enhanced += suffix

            result_lines.append(enhanced)

        remove_nth_from_non_duplicates(refs, tracker)

        snapshot = '\n'.join(result_lines) if result_lines else "(no interactive elements)"
        return RoleSnapshotResult(
            snapshot=snapshot,
            refs=refs,
            stats=_compute_stats(snapshot, refs)
        )

    # Full tree mode with refs
    result_lines = []

    for line in lines:
        depth = _get_indent_level(line)
        if options.max_depth is not None and depth > options.max_depth:
            continue

        parsed = _parse_aria_line(line)
        if not parsed:
            if not options.interactive_only:
                result_lines.append(line)
            continue

        prefix, role_raw, name, suffix = parsed
        role = role_raw.lower()

        is_interactive = role in INTERACTIVE_ROLES
        is_content = role in CONTENT_ROLES
        is_structural = role in STRUCTURAL_ROLES

        if options.compact and is_structural and not name:
            continue

        should_have_ref = is_interactive or (is_content and name)

        if not should_have_ref:
            display_name = _truncate_name(name, max_len)
            if display_name and display_name != name:
                result_lines.append(f"{prefix}{role_raw} \"{display_name}\"{suffix}")
            else:
                result_lines.append(line)
            continue

        ref = next_ref()
        nth = tracker.get_next_index(role, name)
        tracker.track_ref(role, name, ref)

        refs[ref] = RoleRef(role=role, name=name, nth=nth)

        display_name = _truncate_name(name, max_len)
        enhanced = f"{prefix}{role_raw}"
        if display_name:
            enhanced += f' "{display_name}"'
        enhanced += f' [ref={ref}]'
        if nth > 0:
            enhanced += f' [nth={nth}]'
        if suffix:
            enhanced += suffix

        result_lines.append(enhanced)

    remove_nth_from_non_duplicates(refs, tracker)

    tree = '\n'.join(result_lines) if result_lines else "(empty)"
    snapshot = compact_tree(tree) if options.compact else tree

    return RoleSnapshotResult(
        snapshot=snapshot,
        refs=refs,
        stats=_compute_stats(snapshot, refs)
    )


def build_role_snapshot_from_ai(
    ai_snapshot: str,
    options: Optional[RoleSnapshotOptions] = None
) -> RoleSnapshotResult:
    """
    Build a role snapshot from AI snapshot text that already contains [ref=...] markers.
    """
    options = options or RoleSnapshotOptions()
    lines = ai_snapshot.split("\n")
    refs: Dict[str, RoleRef] = {}
    tracker = RoleNameTracker()

    result_lines: List[str] = []
    for line in lines:
        parsed = _parse_ai_line(line)
        if not parsed:
            continue
        role_raw, name, ref, nth = parsed
        role = role_raw.lower()
        if options.interactive_only and role not in INTERACTIVE_ROLES:
            continue
        if options.max_depth is not None and _get_indent_level(line) > options.max_depth:
            continue

        if nth is None:
            nth = tracker.get_next_index(role, name)
        tracker.track_ref(role, name, ref)
        refs[ref] = RoleRef(role=role, name=name, nth=nth)
        result_lines.append(line)

    remove_nth_from_non_duplicates(refs, tracker)
    snapshot = "\n".join(result_lines) if result_lines else "(no interactive elements)"
    if options.compact:
        snapshot = compact_tree(snapshot)

    return RoleSnapshotResult(
        snapshot=snapshot,
        refs=refs,
        stats=_compute_stats(snapshot, refs),
    )


def _compute_stats(snapshot: str, refs: Dict[str, RoleRef]) -> Dict[str, int]:
    """Compute snapshot statistics."""
    interactive_count = sum(
        1 for r in refs.values() if r.role in INTERACTIVE_ROLES
    )
    return {
        "lines": len(snapshot.split('\n')),
        "chars": len(snapshot),
        "refs": len(refs),
        "interactive": interactive_count
    }


def parse_role_ref(raw: str) -> Optional[str]:
    """
    Parse a ref string (e.g., "@e1", "ref=e1", "e1") to normalized form.
    Returns None if invalid.
    """
    trimmed = raw.strip()
    if not trimmed:
        return None
    
    # Normalize different formats
    if trimmed.startswith('@'):
        normalized = trimmed[1:]
    elif trimmed.startswith('ref='):
        normalized = trimmed[4:]
    else:
        normalized = trimmed
    
    # Validate format
    if re.match(r'^e\d+$', normalized):
        return normalized
    return None
