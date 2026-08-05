"""TLS context factory tests.

Guards issue #89: no code path may silently disable certificate
verification. The only opt-out is JARVISCORE_TLS_INSECURE, and it
must log a warning.
"""

import ssl

import pytest

from jarviscore.core.tls import create_ssl_context


def test_default_context_verifies(monkeypatch):
    monkeypatch.delenv("JARVISCORE_TLS_INSECURE", raising=False)
    ctx = create_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True


def test_insecure_env_opt_out_warns(monkeypatch, caplog):
    monkeypatch.setenv("JARVISCORE_TLS_INSECURE", "1")
    with caplog.at_level("WARNING", logger="jarviscore.core.tls"):
        ctx = create_ssl_context()
    assert ctx.verify_mode == ssl.CERT_NONE
    assert ctx.check_hostname is False
    assert any("DISABLED" in r.message for r in caplog.records)


@pytest.mark.parametrize("value", ["0", "false", "", "no"])
def test_falsy_env_values_stay_secure(monkeypatch, value):
    monkeypatch.setenv("JARVISCORE_TLS_INSECURE", value)
    ctx = create_ssl_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_no_remaining_cert_none_in_source():
    """No module outside the factory may construct a CERT_NONE context."""
    from pathlib import Path

    import jarviscore

    root = Path(jarviscore.__file__).parent
    offenders = [
        str(p.relative_to(root))
        for p in root.rglob("*.py")
        if p.name != "tls.py" and "CERT_NONE" in p.read_text(errors="ignore")
    ]
    assert offenders == [], f"TLS verification bypassed in: {offenders}"
