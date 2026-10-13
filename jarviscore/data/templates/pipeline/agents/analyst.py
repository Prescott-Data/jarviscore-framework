from jarviscore.profiles import AutoAgent


class Analyst(AutoAgent):
    role = "analyst"
    capabilities = ["analysis"]
    system_prompt = """
    You analyse structured records.

    Compute summary statistics and notable patterns using Python and store them in a
    variable named `result`:

    result = {
        "stats": dict,            # counts, totals, averages per relevant field
        "patterns": [str, ...],   # 2-4 notable trends or anomalies
    }
    """
