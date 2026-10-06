"""Images in model messages.

JarvisCore's canonical message content is either a string or a list of
OpenAI chat content parts: ``{"type": "text", "text": ...}`` and
``{"type": "image_url", "image_url": {"url": "data:<media>;base64,<data>"}}``.
Each provider adapter translates that shape into the provider's native image
input, so a tool that observes something visual can hand the model the pixels
instead of a description of them.

Tools attach images to a result under ``OBSERVED_IMAGES`` as ``Image``
objects. The agent loop lifts them out with ``split_images``: the model sees
the images, while state, traces and checkpoints keep only a receipt.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import math
import struct
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

OBSERVED_IMAGES = "observed_images"

# OpenAI's published high-detail accounting; used to reserve budget before a
# call. Providers report the billed figure afterwards.
_TILE = 512
_BASE_TOKENS = 85
_TILE_TOKENS = 170


@dataclass(frozen=True)
class Image:
    data: bytes
    media_type: str = "image/png"
    label: str = ""

    def part(self) -> Dict[str, Any]:
        encoded = base64.b64encode(self.data).decode("ascii")
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{self.media_type};base64,{encoded}"},
        }

    def receipt(self) -> Dict[str, Any]:
        width, height = image_size(self.data)
        return {
            "media_type": self.media_type,
            "bytes": len(self.data),
            "sha256": hashlib.sha256(self.data).hexdigest(),
            "width": width,
            "height": height,
            "label": self.label,
            "delivered_to_model": True,
        }


def image_size(data: bytes) -> Tuple[Optional[int], Optional[int]]:
    """Pixel dimensions read from a PNG or JPEG header."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height)
    if data[:2] == b"\xff\xd8":
        index = 2
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            length = struct.unpack(">H", data[index + 2:index + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[index + 5:index + 9])
                return int(width), int(height)
            index += 2 + length
    return None, None


def image_tokens(image: Image) -> int:
    width, height = image_size(image.data)
    if not width or not height:
        width = height = 1024
    scale = min(1.0, 2048 / max(width, height))
    width, height = width * scale, height * scale
    scale = min(1.0, 768 / min(width, height))
    width, height = width * scale, height * scale
    tiles = math.ceil(width / _TILE) * math.ceil(height / _TILE)
    return _BASE_TOKENS + _TILE_TOKENS * tiles


def parts(content: Any) -> List[Dict[str, Any]]:
    if isinstance(content, list):
        return [
            part if isinstance(part, dict) else {"type": "text", "text": str(part)}
            for part in content
        ]
    return [{"type": "text", "text": "" if content is None else str(content)}]


def is_image_part(part: Dict[str, Any]) -> bool:
    return part.get("type") == "image_url"


def has_images(messages: Iterable[Dict[str, Any]]) -> bool:
    return any(
        isinstance(message.get("content"), list)
        and any(is_image_part(part) for part in parts(message["content"]))
        for message in messages
    )


def text_of(content: Any) -> str:
    """The textual content, with each image marked where it appears."""
    if not isinstance(content, list):
        return "" if content is None else str(content)
    return "\n".join(
        "[image]" if is_image_part(part) else str(part.get("text", ""))
        for part in parts(content)
    )


def decode(part: Dict[str, Any]) -> Image:
    url = (part.get("image_url") or {}).get("url", "")
    header, separator, payload = url.partition(",")
    if not (url.startswith("data:") and separator and header.endswith(";base64")):
        raise ValueError("JarvisCore sends images inline; expected a base64 data URL.")
    try:
        data = base64.b64decode(payload, validate=True)
    except binascii.Error as exc:
        raise ValueError(f"Image data URL is not valid base64: {exc}") from exc
    return Image(data=data, media_type=header[len("data:"):-len(";base64")])


def with_images(text: str, images: Iterable[Image]) -> Any:
    images = list(images)
    if not images:
        return text
    return [{"type": "text", "text": text}, *(image.part() for image in images)]


def split_images(result: Any) -> Tuple[Any, List[Image]]:
    """Separate attached images from a tool result, leaving their receipts."""
    if not isinstance(result, dict):
        return result, []
    attached = result.get(OBSERVED_IMAGES)
    if not isinstance(attached, list) or not any(isinstance(item, Image) for item in attached):
        return result, []
    images = [item for item in attached if isinstance(item, Image)]
    receipts = [item if not isinstance(item, Image) else item.receipt() for item in attached]
    return {**result, OBSERVED_IMAGES: receipts}, images


def count_tokens(messages: List[Dict[str, Any]], count_text: Callable[[str], int]) -> int:
    images: List[Image] = []
    textual = []
    for message in messages:
        content = message.get("content")
        if isinstance(content, list) and any(is_image_part(part) for part in parts(content)):
            images.extend(decode(part) for part in parts(content) if is_image_part(part))
            message = {**message, "content": text_of(content)}
        textual.append(message)
    tokens = count_text(json.dumps(textual, ensure_ascii=False, default=str))
    return tokens + sum(image_tokens(image) for image in images)


def to_anthropic(content: Any) -> Any:
    if not isinstance(content, list):
        return content
    blocks = []
    for part in parts(content):
        if is_image_part(part):
            image = decode(part)
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": image.media_type,
                    "data": base64.b64encode(image.data).decode("ascii"),
                },
            })
        else:
            blocks.append({"type": "text", "text": str(part.get("text", ""))})
    return blocks


def to_responses(message: Dict[str, Any]) -> Dict[str, Any]:
    content = message.get("content")
    if not isinstance(content, list):
        return message
    text_type = "output_text" if message.get("role") == "assistant" else "input_text"
    converted = []
    for part in parts(content):
        if is_image_part(part):
            converted.append({"type": "input_image", "image_url": part["image_url"]["url"]})
        else:
            converted.append({"type": text_type, "text": str(part.get("text", ""))})
    return {**message, "content": converted}


_GENAI_LABELS = {"system": "System", "user": "User", "assistant": "Assistant"}


def to_genai(messages: List[Dict[str, Any]]) -> List[Any]:
    """One user turn for google-genai: role-labelled text with images in place."""
    from google.genai import types

    contents: List[Any] = []
    text: List[str] = []
    for message in messages:
        label = _GENAI_LABELS.get(message.get("role", ""))
        if label is None:
            continue
        segments = parts(message.get("content"))
        prefix = f"{label}: "
        for part in segments:
            if is_image_part(part):
                text.append(prefix)
                prefix = ""
                contents.append("".join(text))
                text = []
                image = decode(part)
                contents.append(types.Part.from_bytes(data=image.data, mime_type=image.media_type))
            else:
                text.append(prefix + str(part.get("text", "")))
                prefix = ""
        text.append("\n\n")
    if text:
        contents.append("".join(text).rstrip())
    return [item for item in contents if not (isinstance(item, str) and not item.strip())]
