"""Errors the stores raise, importable without the stores' own dependencies."""


class RoomStateChanged(RuntimeError):
    """A room changed in a way that makes a requested transition invalid."""

    def __init__(self, *, head_moved: bool = False, proposal_status: str = ""):
        self.head_moved = head_moved
        self.proposal_status = proposal_status
        super().__init__("the room's head moved" if head_moved
                         else f"the proposal is {proposal_status}")
