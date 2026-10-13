"""Readiness checks shared by `jarviscore check`, `dev` and deploy commands."""

from dataclasses import dataclass

ERROR = "error"
WARNING = "warning"
INFO = "info"


@dataclass(frozen=True)
class CheckResult:
    id: str
    severity: str
    ok: bool
    message: str
    fix: str | None = None

    def as_dict(self) -> dict:
        return {
            "id": self.id, "severity": self.severity, "ok": self.ok,
            "message": self.message, "fix": self.fix,
        }


def has_errors(results: list[CheckResult]) -> bool:
    return any(not r.ok and r.severity == ERROR for r in results)
