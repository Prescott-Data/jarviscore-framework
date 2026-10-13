from jarviscore.profiles import AutoAgent


class Triage(AutoAgent):
    role = "triage"
    capabilities = ["triage", "classification"]
    system_prompt = """
    You triage customer support messages.

    Classify the message you are given using Python and store the outcome in a variable
    named `result`:

    result = {
        "category": str,      # one of: billing, login, bug, feature_request, other
        "urgency": str,       # one of: low, normal, high
        "summary": str,       # one sentence describing the customer's problem
    }
    """
