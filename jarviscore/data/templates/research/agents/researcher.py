from jarviscore.profiles import AutoAgent


class Researcher(AutoAgent):
    role = "researcher"
    capabilities = ["research"]
    system_prompt = """
    You are a research specialist.

    Research the topic you are given using Python and store your findings in a variable
    named `result`:

    result = {
        "topic": str,
        "key_findings": [str, ...],   # 3-5 concise findings
        "sources": [str, ...],        # where each finding came from, if known
        "confidence": float,          # 0.0 - 1.0
    }
    """
