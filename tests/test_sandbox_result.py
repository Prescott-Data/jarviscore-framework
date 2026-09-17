"""The sandbox keeps the answer the code produced.

`main()` was awaited and its return value discarded, so every atom capability
call and every agent script came back as "finished without returning any
content" while having actually succeeded. And a returned dict was read as this
sandbox's own envelope, so an atom's payload was dropped whenever it did not
happen to use a key named `data`.
"""

import pytest

from jarviscore.execution.coder_sandbox import CoderSandbox, create_coder_sandbox


@pytest.fixture
def sandbox():
    return create_coder_sandbox(timeout=20)


class TestTheEntryPointReturnValueSurvives:

    @pytest.mark.asyncio
    async def test_what_main_returns_is_the_result(self, sandbox):
        out = await sandbox.execute(
            "async def main():\n"
            "    return {'success': True, 'contacts': [{'email': 'a@b.c'}]}\n"
        )
        assert out["data"] == {"success": True, "contacts": [{"email": "a@b.c"}]}

    @pytest.mark.asyncio
    async def test_a_falsy_answer_is_still_an_answer(self, sandbox):
        out = await sandbox.execute("async def main():\n    return {'data': 0}\n")
        assert out["data"] == 0

    @pytest.mark.asyncio
    async def test_code_that_assigns_result_still_works(self, sandbox):
        out = await sandbox.execute("result = {'data': {'count': 7}}\n")
        assert out["data"] == {"count": 7}

    @pytest.mark.asyncio
    async def test_returning_nothing_leaves_stdout_as_the_record(self, sandbox):
        out = await sandbox.execute("async def main():\n    print('hello')\n")
        assert out["data"] is None
        assert out["stdout"] == "hello\n"


class TestAnAtomsShapeIsNotTheEnvelope:
    """Only the sandbox's own keys mean the sandbox's own contract."""

    @staticmethod
    def parse(raw):
        return CoderSandbox.__new__(CoderSandbox)._parse_result(raw, "", 0.1)

    def test_an_atom_payload_is_kept_whole(self):
        atom = {"success": True, "contacts": [{"id": "1"}], "paging": None}
        assert self.parse(atom).data == atom

    def test_an_atom_failure_is_reported_as_failure(self):
        result = self.parse({"success": False, "error": "unauthorised"})
        assert result.success is False
        assert result.error == "unauthorised"

    def test_the_envelope_is_still_read_as_an_envelope(self):
        result = self.parse({"success": True, "files_created": ["a.txt"], "data": {"x": 1}})
        assert result.data == {"x": 1}
        assert result.files_created == ["a.txt"]
