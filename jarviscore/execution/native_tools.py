"""Native tool calling across providers.

The kernel threads one canonical conversation: OpenAI Chat Completions messages,
where an assistant turn carries ``tool_calls`` and each result is a ``tool``
message naming its ``tool_call_id``. Tools are OpenAI function definitions and a
model's calls come back as ``{"id", "name", "arguments"}`` records, plus a
``signature`` where the provider requires one to be returned with the call.

Each function here translates that canonical form to or from one provider's
native shape; the adapters in :mod:`jarviscore.execution.llm` call them.
"""

import base64
import json
import uuid
from typing import Any, Dict, List, Optional, Tuple

from jarviscore.execution import multimodal

#: Prefix of call ids JarvisCore assigns when a provider returns calls without one.
ASSIGNED_ID_PREFIX = "jc_call_"
_OPENAI_CALL_KEYS = ("id", "type", "function")


def _functions(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [tool.get("function") or tool for tool in tools or []]


def _arguments(call: Dict[str, Any]) -> Dict[str, Any]:
    """A threaded call's arguments as an object; a provider may have sent invalid JSON."""
    try:
        value = json.loads((call.get("function") or {}).get("arguments") or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _call_names(messages: List[Dict[str, Any]]) -> Dict[str, str]:
    return {
        call["id"]: call["function"]["name"]
        for message in messages
        for call in message.get("tool_calls") or []
    }


def is_openai_tools(tools: Any) -> bool:
    return bool(tools) and isinstance(tools, list) and all(
        isinstance(tool, dict) and tool.get("type") == "function" and "function" in tool
        for tool in tools
    )


# ── OpenAI wire (Azure Chat Completions, vLLM) ────────────────────────────


def openai_messages(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Canonical messages without the keys only other providers read."""
    cleaned = []
    for message in messages:
        if message.get("tool_calls"):
            message = {
                **message,
                "tool_calls": [
                    {key: call[key] for key in _OPENAI_CALL_KEYS if key in call}
                    for call in message["tool_calls"]
                ],
            }
        cleaned.append(message)
    return cleaned


# ── Azure Responses API ───────────────────────────────────────────────────


def responses_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    # Responses function tools are strict by default, which demands closed schemas.
    return [
        {
            "type": "function",
            "name": function["name"],
            "description": function.get("description", ""),
            "parameters": function.get("parameters") or {"type": "object", "properties": {}},
            "strict": False,
        }
        for function in _functions(tools)
    ]


def responses_input(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        if role == "tool":
            items.append({
                "type": "function_call_output",
                "call_id": message["tool_call_id"],
                "output": multimodal.text_of(message.get("content")),
            })
            continue
        if role == "assistant" and message.get("tool_calls"):
            if message.get("content"):
                items.append(multimodal.to_responses({"role": "assistant", "content": message["content"]}))
            for call in message["tool_calls"]:
                items.append({
                    "type": "function_call",
                    "call_id": call["id"],
                    "name": call["function"]["name"],
                    "arguments": call["function"].get("arguments") or "{}",
                })
            continue
        items.append(multimodal.to_responses(message))
    return items


# ── Anthropic Messages API ────────────────────────────────────────────────


def anthropic_tools(tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        {
            "name": function["name"],
            "description": function.get("description", ""),
            "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
        }
        for function in _functions(tools)
    ]


def anthropic_tool_choice(tool_choice: Any, parallel_tool_calls: Optional[bool]) -> Dict[str, Any]:
    choice = {"required": "any", "auto": "auto", "none": "none"}.get(tool_choice, "auto")
    selected: Dict[str, Any] = {"type": choice}
    if parallel_tool_calls is False and choice != "none":
        selected["disable_parallel_tool_use"] = True
    return selected


def anthropic_messages(messages: List[Dict[str, Any]]) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """The system prompt and the conversation as Anthropic content blocks."""
    system: List[str] = []
    turns: List[Dict[str, Any]] = []

    def add(role: str, blocks: List[Dict[str, Any]]) -> None:
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": blocks})

    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            system.append(multimodal.text_of(content))
        elif role == "tool":
            add("user", [{
                "type": "tool_result",
                "tool_use_id": message["tool_call_id"],
                "content": multimodal.text_of(content),
            }])
        elif role == "assistant":
            blocks = [{"type": "text", "text": multimodal.text_of(content)}] if content else []
            blocks += [
                {"type": "tool_use", "id": call["id"], "name": call["function"]["name"],
                 "input": _arguments(call)}
                for call in message.get("tool_calls") or []
            ]
            add("assistant", blocks)
        else:
            converted = multimodal.to_anthropic(content)
            add("user", converted if isinstance(converted, list) else [{"type": "text", "text": str(converted or "")}])
    return ("\n\n".join(system) or None), turns


def anthropic_calls(content_blocks: Any) -> List[Dict[str, str]]:
    return [
        {
            "id": str(getattr(block, "id", "") or ""),
            "name": str(getattr(block, "name", "") or ""),
            "arguments": json.dumps(getattr(block, "input", None) or {}),
        }
        for block in content_blocks or []
        if getattr(block, "type", None) == "tool_use"
    ]


# ── Google GenAI (Gemini, Vertex AI) ──────────────────────────────────────


def genai_tools(tools: List[Dict[str, Any]], types: Any) -> List[Any]:
    return [types.Tool(function_declarations=[
        types.FunctionDeclaration(
            name=function["name"],
            description=function.get("description", ""),
            parameters_json_schema=function.get("parameters") or {"type": "object", "properties": {}},
        )
        for function in _functions(tools)
    ])]


def genai_tool_config(tool_choice: Any, types: Any) -> Any:
    mode = {"required": "ANY", "auto": "AUTO", "none": "NONE"}.get(tool_choice, "AUTO")
    return types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode=mode))


def genai_contents(messages: List[Dict[str, Any]], types: Any) -> Tuple[Optional[str], List[Any]]:
    """The system instruction and the conversation as GenAI contents."""
    system: List[str] = []
    contents: List[Any] = []
    names = _call_names(messages)

    def add(role: str, parts: List[Any]) -> None:
        if contents and contents[-1].role == role:
            contents[-1].parts.extend(parts)
        else:
            contents.append(types.Content(role=role, parts=parts))

    def media(content: Any) -> List[Any]:
        parts = []
        for part in multimodal.parts(content):
            if multimodal.is_image_part(part):
                image = multimodal.decode(part)
                parts.append(types.Part.from_bytes(data=image.data, mime_type=image.media_type))
            elif part.get("text"):
                parts.append(types.Part(text=str(part["text"])))
        return parts

    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if role == "system":
            system.append(multimodal.text_of(content))
        elif role == "tool":
            call_id = message["tool_call_id"]
            add("user", [types.Part(function_response=types.FunctionResponse(
                id=None if call_id.startswith(ASSIGNED_ID_PREFIX) else call_id,
                name=names.get(call_id, ""),
                response={"output": multimodal.text_of(content)},
            ))])
        elif role == "assistant":
            parts = media(content) if content else []
            for call in message.get("tool_calls") or []:
                signature = call.get("signature")
                parts.append(types.Part(
                    function_call=types.FunctionCall(
                        id=None if call["id"].startswith(ASSIGNED_ID_PREFIX) else call["id"],
                        name=call["function"]["name"],
                        args=_arguments(call),
                    ),
                    thought_signature=base64.b64decode(signature) if signature else None,
                ))
            add("model", parts)
        else:
            add("user", media(content))
    return ("\n\n".join(system) or None), contents


def genai_calls(parts: Any) -> List[Dict[str, Any]]:
    calls = []
    for part in parts or []:
        function_call = getattr(part, "function_call", None)
        if not function_call:
            continue
        args = dict(function_call.args) if function_call.args else {}
        call_id = getattr(function_call, "id", None)
        call = {
            "id": call_id if isinstance(call_id, str) and call_id else f"{ASSIGNED_ID_PREFIX}{uuid.uuid4().hex}",
            "name": function_call.name,
            "arguments": json.dumps(args),
            "args": args,
        }
        signature = getattr(part, "thought_signature", None)
        if isinstance(signature, (bytes, bytearray)) and signature:
            call["signature"] = base64.b64encode(signature).decode("ascii")
        calls.append(call)
    return calls
