import logging

logger = logging.getLogger(__name__)

class IntentNormalizer:
    """
    Distills a verbose, history-laden request down to a canonical intent.
    This prevents context pollution when embedding tasks for semantic search.
    """
    def __init__(self, llm_client):
        self.llm = llm_client
        self.system_prompt = (
            "You are an intent normalizer. Extract the core canonical action and entity from the following task. "
            "Remove all conversational fluff, pleasantries, history, context, and formatting instructions. "
            "Return ONLY the core intent as a concise string (e.g., 'fetch user profile', 'create stripe charge').\n\n"
        )

    async def normalize(self, task_description: str) -> str:
        if not task_description or len(task_description.split()) <= 3:
            return task_description

        try:
            messages = [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": f"Task:\n{task_description}"}
            ]

            # Using nano_model if available for speed
            eval_model = getattr(self.llm, "nano_model", None)
            kwargs = {"messages": messages, "temperature": 0.0}
            if eval_model:
                kwargs["model"] = eval_model

            res = await self.llm.generate(**kwargs)

            content = res.get("content", "").strip()
            if content:
                logger.info(f"Normalized intent: '{task_description[:30]}...' -> '{content}'")
                return content
            return task_description
        except Exception as e:
            logger.warning(f"Intent normalization failed, using original task: {e}")
            return task_description
