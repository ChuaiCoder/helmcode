from __future__ import annotations

from helmcode.models.provider import ModelResponse, extract_usage


def test_extract_usage_handles_openai_token_details() -> None:
    usage = extract_usage(
        {
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 80},
                "completion_tokens_details": {"reasoning_tokens": 7},
            }
        }
    )

    assert usage == {
        "prompt_tokens": 100,
        "completion_tokens": 20,
        "total_tokens": 120,
        "cached_tokens": 80,
        "reasoning_tokens": 7,
    }


def test_extract_usage_handles_deepseek_cache_hit_and_miss_tokens() -> None:
    response = ModelResponse(
        content="ok",
        raw={
            "usage": {
                "prompt_tokens": "50",
                "completion_tokens": 10,
                "prompt_cache_hit_tokens": 30,
                "prompt_cache_miss_tokens": 20,
            }
        },
    )

    assert response.usage == {
        "prompt_tokens": 50,
        "completion_tokens": 10,
        "total_tokens": 60,
        "cached_tokens": 30,
        "cache_miss_tokens": 20,
    }
