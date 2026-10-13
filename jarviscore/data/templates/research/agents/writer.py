from jarviscore.profiles import AutoAgent


class Writer(AutoAgent):
    role = "writer"
    capabilities = ["writing", "summarisation"]
    system_prompt = """
    You turn research findings into a clear brief.

    Given research findings, write the brief using Python and store it in a variable
    named `result`:

    result = {
        "title": str,
        "brief": str,                 # 200-300 words, plain language
        "open_questions": [str, ...], # what the research did not answer
    }
    """
