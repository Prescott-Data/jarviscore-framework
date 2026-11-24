"""What the trace scrubber takes out of text bound for traces."""
import base64
import json

from jarviscore.kernel.tracing import TraceManager


def _scrub(value):
    return TraceManager.__new__(TraceManager)._scrub(value)


def test_a_credential_inside_json_text_is_masked():
    text = json.dumps({"access_token": "abc123XYZ", "expires_in": 3599, "scope": "mail"})
    scrubbed = _scrub(text)
    assert "abc123XYZ" not in scrubbed
    assert "3599" in scrubbed and "mail" in scrubbed


def test_a_credential_inside_json_inside_a_string_is_masked():
    value = "made-up-" + "value-for-a-test"
    text = str({"status": "success", "output": json.dumps({"refresh_token": value})})
    assert value not in _scrub(text)


def test_a_credential_in_a_python_repr_is_masked():
    assert "hunter2" not in _scrub(str({"password": "hunter2", "user": "sam"}))


def _made_up(prefix: str, body: str, times: int) -> str:
    """A string with a credential's shape, assembled here so none is written in this file."""
    return prefix + body * times


def test_tokens_known_by_their_shape_are_masked_wherever_they_sit():
    part = base64.urlsafe_b64encode(b'{"made":"up","for":"a test"}').decode().rstrip("=")
    samples = [
        _made_up("s" + "k-", "a1B2", 8),
        _made_up("gh" + "p_", "Z9y8", 9),
        _made_up("xo" + "xb-", "12345-abcde", 2),
        _made_up("ya" + "29.", "A0b", 10),
        _made_up("AK" + "IA", "ABCDEFGH", 2),
        f"{part}.{part}.c2lnbmF0dXJl",
    ]
    for sample in samples:
        scrubbed = _scrub(f"the reply carried {sample} in its body")
        assert sample not in scrubbed and "the reply carried" in scrubbed


def test_a_private_key_is_masked_whole():
    dashes, kind = "-" * 5, "RSA PRIVATE" + " KEY"
    key = f"{dashes}BEGIN {kind}{dashes}\nMIIEow\nIBAAKC\n{dashes}END {kind}{dashes}"
    scrubbed = _scrub(f"key follows\n{key}\nend")
    assert "MIIEow" not in scrubbed and scrubbed.endswith("end")


def test_counts_and_ordinary_words_survive():
    text = json.dumps({"tokens": 512, "subject": "Token economics", "note": "the secretary called"})
    scrubbed = _scrub(text)
    assert "512" in scrubbed and "Token economics" in scrubbed and "the secretary called" in scrubbed
    assert _scrub({"tokens": 512}) == {"tokens": 512}
