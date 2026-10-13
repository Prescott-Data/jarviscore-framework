from jarviscore.profiles import AutoAgent


class Responder(AutoAgent):
    role = "responder"
    capabilities = ["responder", "customer_reply"]
    system_prompt = """
    You write replies to customer support messages.

    Given the customer's message and its triage (category, urgency, summary), draft a
    reply using Python and store it in a variable named `result`:

    result = {
        "reply": str,         # friendly, specific, under 150 words
        "next_step": str,     # what the customer or support team should do next
    }
    """
