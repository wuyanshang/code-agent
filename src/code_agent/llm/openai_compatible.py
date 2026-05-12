from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx

from code_agent.config import ModelConfig
from code_agent.llm.base import BaseLLMClient, StreamChunk
from code_agent.schemas import LLMResponse, ToolCall

logger = logging.getLogger(__name__)

_DEFAULT_RETRIES = 4
_RETRY_BACKOFF = (1.0, 2.0, 4.0, 8.0)
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _retry_wait_seconds(attempt: int, response: httpx.Response | None) -> float:
    if response is not None:
        ra = response.headers.get("retry-after")
        if ra:
            try:
                return float(ra)
            except ValueError:
                pass
    return _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]


class OpenAICompatibleClient(BaseLLMClient):
    def __init__(self, config: ModelConfig) -> None:
        self.config = config
        self._client = httpx.AsyncClient(
            timeout=config.timeout_seconds,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
        )
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    async def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        if not self.config.base_url or not self.config.api_key or not self.config.model_name:
            raise ValueError("model base_url, api_key, and model_name must be configured")

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = await self._request_with_retry(url, payload)

        usage = data.get("usage", {})
        self.total_input_tokens += usage.get("prompt_tokens", 0)
        self.total_output_tokens += usage.get("completion_tokens", 0)

        message = data["choices"][0]["message"]
        tool_calls = []
        for item in message.get("tool_calls", []) or []:
            tool_calls.append(
                ToolCall(
                    name=item["function"]["name"],
                    arguments=_safe_json_loads(item["function"]["arguments"]),
                    id=item.get("id"),
                )
            )
        return LLMResponse(
            text=message.get("content") or "",
            tool_calls=tool_calls,
            raw_response=data,
            finish_reason=data["choices"][0].get("finish_reason"),
        )

    async def chat_stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncGenerator[StreamChunk, None]:
        if not self.config.base_url or not self.config.api_key or not self.config.model_name:
            raise ValueError("model base_url, api_key, and model_name must be configured")

        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload: dict[str, Any] = {
            "model": self.config.model_name,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_exc: Exception | None = None
        for attempt in range(_DEFAULT_RETRIES):
            accumulated_tools: dict[int, dict[str, str]] = {}
            try:
                async with self._client.stream("POST", url, json=payload) as response:
                    if response.status_code in _RETRYABLE_STATUS and attempt < _DEFAULT_RETRIES - 1:
                        wait = _retry_wait_seconds(attempt, response)
                        logger.warning(
                            "LLM stream HTTP %s, retrying in %.1fs...", response.status_code, wait
                        )
                        await asyncio.sleep(wait)
                        continue
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str == "[DONE]":
                            break

                        try:
                            data = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue

                        if "usage" in data and data["usage"]:
                            usage = data["usage"]
                            self.total_input_tokens += usage.get("prompt_tokens", 0)
                            self.total_output_tokens += usage.get("completion_tokens", 0)

                        choices = data.get("choices", [])
                        if not choices:
                            continue

                        delta = choices[0].get("delta", {})
                        finish = choices[0].get("finish_reason")

                        if delta.get("content"):
                            yield StreamChunk(type="text_delta", text=delta["content"])

                        for tc_delta in delta.get("tool_calls", []) or []:
                            idx = tc_delta.get("index", 0)
                            if idx not in accumulated_tools:
                                accumulated_tools[idx] = {"id": "", "name": "", "arguments": ""}

                            if tc_delta.get("id"):
                                accumulated_tools[idx]["id"] = tc_delta["id"]
                            fn = tc_delta.get("function", {})
                            if fn.get("name"):
                                accumulated_tools[idx]["name"] = fn["name"]
                            if fn.get("arguments"):
                                accumulated_tools[idx]["arguments"] += fn["arguments"]

                        if finish:
                            for idx in sorted(accumulated_tools):
                                tc = accumulated_tools[idx]
                                yield StreamChunk(
                                    type="tool_call",
                                    tool_index=idx,
                                    tool_call_id=tc["id"],
                                    tool_name=tc["name"],
                                    tool_arguments_delta=tc["arguments"],
                                )
                            yield StreamChunk(type="done", finish_reason=finish)
                return
            except httpx.HTTPStatusError as exc:
                last_exc = exc
                if exc.response.status_code in _RETRYABLE_STATUS and attempt < _DEFAULT_RETRIES - 1:
                    wait = _retry_wait_seconds(attempt, exc.response)
                    logger.warning(
                        "LLM stream HTTPStatusError %s, retrying in %.1fs...",
                        exc.response.status_code,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                raise
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < _DEFAULT_RETRIES - 1:
                    wait = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                    logger.warning("LLM stream (%s), retrying in %.1fs...", exc, wait)
                    await asyncio.sleep(wait)
                    continue
                raise
        raise last_exc or RuntimeError("LLM stream failed after retries")

    async def _request_with_retry(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        last_exc: Exception | None = None
        for attempt in range(_DEFAULT_RETRIES):
            try:
                response = await self._client.post(url, json=payload)
                if response.status_code in _RETRYABLE_STATUS and attempt < _DEFAULT_RETRIES - 1:
                    wait = _retry_wait_seconds(attempt, response)
                    logger.warning(
                        "LLM request got %s, retrying in %.1fs...", response.status_code, wait
                    )
                    await asyncio.sleep(wait)
                    continue
                response.raise_for_status()
                return response.json()
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                last_exc = exc
                if attempt < _DEFAULT_RETRIES - 1:
                    wait = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                    logger.warning("LLM request failed (%s), retrying in %.1fs...", exc, wait)
                    await asyncio.sleep(wait)
        raise last_exc or RuntimeError("LLM request failed after retries")

    async def close(self) -> None:
        await self._client.aclose()


def _safe_json_loads(value: str) -> dict[str, Any]:
    parsed = json.loads(value) if value else {}
    if not isinstance(parsed, dict):
        raise ValueError("tool arguments must decode to an object")
    return parsed
