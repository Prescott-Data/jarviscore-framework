from jarviscore.profiles import AutoAgent


class Extractor(AutoAgent):
    role = "extractor"
    capabilities = ["extraction"]
    system_prompt = """
    You extract structured records from raw input (text, CSV, JSON).

    Parse the input you are given using Python and store the records in a variable
    named `result`:

    result = {
        "records": [dict, ...],   # one dict per record, consistent keys
        "fields": [str, ...],     # the keys every record has
        "skipped": int,           # rows you could not parse
    }
    """
