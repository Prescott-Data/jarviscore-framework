from jarviscore.profiles import AutoAgent


class Assistant(AutoAgent):
    role = "assistant"
    capabilities = ["assistant", "general"]
    system_prompt = """
    You are a helpful, precise assistant.

    Complete the task you are given using Python and store the answer in a variable
    named `result`:

    result = {
        "answer": str,        # the direct answer to the task
        "reasoning": str,     # one or two sentences on how you got there
    }
    """
