from jarviscore.profiles import AutoAgent


class Reporter(AutoAgent):
    role = "reporter"
    capabilities = ["reporting"]
    system_prompt = """
    You write short reports from analysis results.

    Given statistics and patterns, write the report using Python and store it in a
    variable named `result`:

    result = {
        "headline": str,
        "report": str,            # markdown, under 300 words
    }
    """
