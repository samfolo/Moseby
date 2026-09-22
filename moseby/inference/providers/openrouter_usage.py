"""Read reported usage without estimating absent counts."""

from pydantic import ValidationError

from moseby.common.types import JsonObject
from moseby.common.usage import TokenUsage


def read_usage(response: JsonObject) -> TokenUsage | None:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return None
    input_details = usage.get("prompt_tokens_details") or {}
    output_details = usage.get("completion_tokens_details") or {}
    if not isinstance(input_details, dict):
        return None
    output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
    reasoning = (
        output_details.get("reasoning_tokens")
        if isinstance(output_details, dict)
        else None
    )
    # An inconsistent optional subtotal must not discard valid input and cache counts.
    if not (
        type(reasoning) is int
        and type(output_tokens) is int
        and 0 <= reasoning <= output_tokens
    ):
        reasoning = None
    try:
        return TokenUsage(
            input_tokens=usage.get("prompt_tokens", usage.get("input_tokens")),
            output_tokens=output_tokens,
            cache_read_tokens=input_details.get("cached_tokens", 0),
            cache_write_tokens=input_details.get("cache_write_tokens", 0),
            reasoning_tokens=reasoning,
        )
    except ValidationError:
        return None


def total_tokens(response: JsonObject) -> int | None:
    """Retain the provider's full count, including cached input and reasoning output."""
    usage = response.get("usage")
    total = usage.get("total_tokens") if isinstance(usage, dict) else None
    if type(total) is int and total >= 0:
        return total
    breakdown = read_usage(response)
    return (
        breakdown.input_tokens + breakdown.output_tokens
        if breakdown is not None
        else None
    )
