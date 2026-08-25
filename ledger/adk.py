"""ADK adapter (plan §5): every Gemini call the fleet makes is a pollard model_call node.

ADK has no native pollard adapter, so this is the callback pair each agent carries:

  before_model  replay/hybrid: if the ledger already holds this exact request at the
                run's cursor, serve the recorded response — ADK skips Gemini entirely.
                Otherwise stash the request identity for `after_model`.
  after_model   record: the final (non-partial) response becomes the node's result,
                with usage for the token meter.

The identity payload is the request as the model saw it — model, system instruction,
tool declarations, the full contents — made identity-safe (floats to strings; bytes
such as Gemini 3 thought signatures arrive base64 from pydantic). So a replay is the
same conversation byte for byte, and a changed prompt is a different node.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import ledger

if TYPE_CHECKING:  # ADK is a runtime dependency of the fleet, not of this package
    from google.adk.agents.callback_context import CallbackContext
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.llm_response import LlmResponse


def identity_safe(value: Any) -> Any:
    """pollard identity payloads allow str/int/bool/None/list/dict — never floats."""
    if isinstance(value, bool) or value is None or isinstance(value, (int, str)):
        return value
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, dict):
        return {str(k): identity_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [identity_safe(v) for v in value]
    return str(value)


def model_payload(agent_name: str, llm_request: LlmRequest) -> dict[str, Any]:
    """The request identity: what this agent asked the model, exactly."""
    dumped = llm_request.model_dump(
        mode="json", exclude_none=True, include={"model", "contents", "config"}
    )
    config = dict(dumped.get("config") or {})
    config.pop("http_options", None)  # transport, not conversation
    return identity_safe(
        {
            "agent": agent_name,
            "model": dumped.get("model") or "",
            "config": config,
            "contents": dumped.get("contents") or [],
        }
    )


def response_result(llm_response: LlmResponse) -> dict[str, Any]:
    """The node result: the response verbatim (JSON mode) plus meter-shaped usage."""
    usage = llm_response.usage_metadata
    return {
        "response": llm_response.model_dump(mode="json", exclude_none=True),
        "usage": {
            "input_tokens": int(getattr(usage, "prompt_token_count", 0) or 0),
            "output_tokens": int(getattr(usage, "candidates_token_count", 0) or 0),
        },
    }


def before_model(callback_context: CallbackContext, llm_request: LlmRequest) -> LlmResponse | None:
    review = ledger.review_run_for(callback_context.invocation_id)
    payload = model_payload(callback_context.agent_name, llm_request)
    node = review.recorded_model_call(payload)
    if node is None:
        review.pending_model_calls[callback_context.agent_name] = payload
        return None
    from google.adk.models.llm_response import LlmResponse

    return LlmResponse.model_validate(node.result["response"])


def after_model(callback_context: CallbackContext, llm_response: LlmResponse) -> None:
    if llm_response.partial:  # streaming chunk; the aggregated final response follows
        return None
    review = ledger.review_run_for(callback_context.invocation_id)
    payload = review.pending_model_calls.pop(callback_context.agent_name, None)
    if payload is None:  # served from the ledger in before_model, or nothing pending
        return None
    review.record_model_call(payload, response_result(llm_response))
    return None
