"""Taxonomy helpers and the tagging prompt."""

from __future__ import annotations

import re
from typing import Any


def normalize_taxonomy(raw: Any) -> dict[str, Any]:
    """Expand YAML category lists into the schema used by the tagger.

    Lists allow several labels per category. A mapping with ``values`` and
    ``multi: false`` can be used when exactly one label at most is wanted.
    Detailed category mappings are accepted alongside simple lists.
    """
    if not isinstance(raw, dict):
        raise SystemExit("[!] taxonomy must be a mapping of category names to lists.")
    result = {}
    for axis, spec in raw.items():
        if not isinstance(axis, str) or not axis.strip():
            raise SystemExit("[!] Taxonomy category names must be non-empty strings.")
        if axis.startswith("_"):
            result[axis] = spec
            continue
        if isinstance(spec, list):
            spec = {"values": spec, "multi": True}
        if not isinstance(spec, dict):
            raise SystemExit(f"[!] taxonomy.{axis} must be a list or a mapping with values.")
        values = axis_values(spec)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(v, str) or not v.strip() for v in values)
        ):
            raise SystemExit(f"[!] Taxonomy axes without values: {axis} (use non-empty strings).")
        if "multi" in spec and not isinstance(spec["multi"], bool):
            raise SystemExit(f"[!] taxonomy.{axis}.multi must be true or false.")
        result[axis] = {**spec, "values": list(dict.fromkeys(values))}
    if not axis_names(result):
        raise SystemExit("[!] Taxonomy has no axes (keys not starting with _).")
    return result


def axis_names(taxonomy: dict[str, Any]) -> list[str]:
    """Axes are the keys that don't start with an underscore."""
    return [k for k in taxonomy if not k.startswith("_")]


def axis_values(spec: dict[str, Any]) -> list[str]:
    return spec.get("values") or spec.get("valori") or []


def axis_description(spec: dict[str, Any]) -> str:
    return spec.get("description") or spec.get("descrizione") or ""


DEFAULT_INSTRUCTIONS = [
    "You are an archivist cataloguing posts from a page about space exploration.",
    "For each caption, assign the correct values for every axis of the taxonomy below.",
    "",
    "RULES:",
    "- Use ONLY the listed values. Never invent new ones.",
    "- If an axis cannot be determined from the caption, return an empty list [].",
    "- Ignore hashtags: they carry no information.",
]


def build_tagging_prompt(taxonomy: dict[str, Any]) -> str:
    # Instructions live in the JSON so you can change them (and their
    # language) without touching the code.
    instructions = taxonomy.get("_instructions") or DEFAULT_INSTRUCTIONS
    if isinstance(instructions, str):
        instructions = instructions.splitlines()
    lines = list(instructions) + ["", "TAXONOMY:"]

    axes = axis_names(taxonomy)
    for axis in axes:
        spec = taxonomy[axis]
        card = "multiple values allowed" if spec.get("multi") else "at most one value"
        lines.append(f"- {axis} ({card}): {axis_description(spec)}")
        lines.append(f"  values: {', '.join(axis_values(spec))}")

    lines += [
        "",
        "Respond ONLY with a JSON object holding one entry per caption, in the",
        "same order received, in this format:",
        '{"posts": [{"id": "<received id>", ' + ", ".join(f'"{a}": []' for a in axes) + "}]}",
        "No text before or after. No markdown fences.",
    ]
    return "\n".join(lines)


def response_schema(taxonomy: dict[str, Any]) -> dict[str, Any]:
    """JSON schema for Ollama's `format`: only taxonomy values are allowed."""
    item: dict[str, Any] = {"id": {"type": "string"}}
    for axis in axis_names(taxonomy):
        spec = taxonomy[axis]
        values = {"type": "array", "items": {"type": "string", "enum": axis_values(spec)}}
        if not spec.get("multi"):
            values["maxItems"] = 1
        item[axis] = values
    return {
        "type": "object",
        "properties": {
            "posts": {
                "type": "array",
                "items": {"type": "object", "properties": item, "required": list(item)},
            }
        },
        "required": ["posts"],
    }


def clean_caption(caption: str, max_chars: int = 1200) -> str:
    text = re.sub(r"#\S+", "", caption)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:max_chars]
