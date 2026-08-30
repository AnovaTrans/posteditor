"""Thin Claude wrapper for the MTPE engine.

Two hard-won rules baked in (current Claude API drift):
  * `temperature` is REJECTED (400) on current Claude — never send it.
  * a response can contain thinking blocks — read text via `_response_text`,
    never `response.content[0].text`.
"""
import json
import re

# Live model list shown in both apps' dropdowns (no legacy models).
CURRENT_MODELS = ["claude-sonnet-5", "claude-opus-5", "claude-opus-4-8", "claude-haiku-4-5-20251001"]
DEFAULT_MODEL = "claude-sonnet-5"

# Rough per-MTok USD (input, output) — for a cost estimate only; refresh as needed.
_PRICE = {
    "claude-opus-5": (5.0, 25.0), "claude-opus-4-8": (5.0, 25.0),
    "claude-sonnet-5": (3.0, 15.0), "claude-haiku-4-5-20251001": (1.0, 5.0),
}


class MissingKey(RuntimeError):
    pass


def _response_text(resp) -> str:
    """Concatenate only the text blocks (skips thinking/tool blocks)."""
    parts = []
    for block in getattr(resp, "content", []) or []:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
        elif isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
    return "".join(parts)


def _extract_json(text: str):
    """Parse a JSON object/array out of a model reply (tolerates ``` fences)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.I | re.S).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            return json.loads(m.group(1))
        raise


class LLMClient:
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        if not api_key:
            raise MissingKey("No Claude API key configured.")
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model or DEFAULT_MODEL
        self.input_tokens = 0
        self.output_tokens = 0

    def complete_json(self, system: str, user: str, max_tokens: int = 4000):
        resp = self._client.messages.create(
            model=self.model, max_tokens=max_tokens, system=system,
            messages=[{"role": "user", "content": user}],
        )
        usage = getattr(resp, "usage", None)
        if usage:
            self.input_tokens += getattr(usage, "input_tokens", 0)
            self.output_tokens += getattr(usage, "output_tokens", 0)
        return _extract_json(_response_text(resp))

    @property
    def cost_usd(self) -> float:
        pin, pout = _PRICE.get(self.model, (0.0, 0.0))
        return round(self.input_tokens / 1e6 * pin + self.output_tokens / 1e6 * pout, 4)
