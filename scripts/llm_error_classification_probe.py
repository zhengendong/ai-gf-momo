"""Offline checks for safe Momo/LLM failure classification."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agents.momo import MomoAgent, MomoOutputError
from backend.core.runtime import AgentRuntime
from backend.services.llm import LLMServiceError, classify_http_failure


def main():
    assert classify_http_failure(429, "rate limit exceeded") == "rate_limited"
    assert classify_http_failure(503, "temporarily unavailable") == "provider_unavailable"
    assert classify_http_failure(403, "content_policy_violation") == "content_blocked"
    assert classify_http_failure(422, "maximum context length exceeded") == "context_rejected"
    assert classify_http_failure(401, "invalid api key") == "authentication_failed"
    assert classify_http_failure(422, "invalid request body") == "request_rejected"

    agent = MomoAgent(None)
    try:
        agent._parse_output("I cannot help with that because of the safety policy.")
    except MomoOutputError as error:
        assert error.code == "content_blocked"
    else:
        raise AssertionError("policy refusal must be classified")

    plain_roleplay = "小樱轻轻攥住床单，抬起湿润的眼眸望向你。\n\n“主人……我在这里。”"
    recovered = agent._parse_output(plain_roleplay)
    assert recovered.reply == plain_roleplay
    assert recovered.memory_candidate is None
    assert recovered.persist_context is True

    try:
        agent._parse_output("<think>模型认为连续性性描述或强迫型描述需要拒绝回复。</think>")
    except MomoOutputError as error:
        assert error.code == "content_blocked"
    else:
        raise AssertionError("think-only policy refusal must never become a role reply")

    try:
        agent._parse_output("这不是 JSON")
    except MomoOutputError as error:
        assert error.code == "output_format_invalid"
    else:
        raise AssertionError("plain model text must be classified as a format error")

    try:
        agent._parse_output(None)
    except MomoOutputError as error:
        assert error.code == "output_format_invalid"
    else:
        raise AssertionError("empty model content must be classified as a format error")

    old_field = agent._parse_output(json.dumps({
        "reply": "正常回复",
        "image_goal": {"purpose": "legacy"},
        "memory_candidate": None,
        "persist_context": True,
    }, ensure_ascii=False))
    assert old_field.image_goal is None

    assert "安全策略" in AgentRuntime._momo_error_message(
        LLMServiceError("content_blocked", "blocked")
    )
    assert "限流" in AgentRuntime._momo_error_message(
        LLMServiceError("rate_limited", "limited")
    )
    assert "格式异常" in AgentRuntime._momo_error_message(
        MomoOutputError("output_format_invalid", "invalid")
    )
    print("llm error classification probe: ok")


if __name__ == "__main__":
    main()
