"""最小 OpenAI 兼容客户端。零依赖，只用标准库。

为什么不用 openai SDK / LangChain：
  - 第一版你要能看清每一行在干什么。框架会把这些藏起来，
    等出问题时你不知道是框架的锅还是你的锅。
"""

import json
import urllib.request
import urllib.error


def _headers(key):
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + key,
    }


def _build_payload(cfg, messages, model, stream, temperature, max_tokens):
    return {
        "model": model,
        "messages": messages,
        "stream": stream,
        "temperature": cfg.get("temperature", 0.7) if temperature is None else temperature,
        "max_tokens": cfg.get("max_tokens", 2048) if max_tokens is None else max_tokens,
    }


def chat(api, cfg, messages, model=None, temperature=None, max_tokens=None):
    """非流式调用。返回纯文本。"""
    url = api["base_url"].rstrip("/") + "/chat/completions"
    payload = _build_payload(
        cfg, messages, model or cfg["model"], False, temperature, max_tokens
    )
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=_headers(api["api_key"])
    )
    try:
        with urllib.request.urlopen(req, timeout=api.get("timeout_sec", 180)) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM 连不上: {e.reason}") from None

    try:
        return body["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError):
        raise RuntimeError(f"LLM 返回格式不对: {json.dumps(body)[:500]}")


def chat_message(api, cfg, messages, model=None, temperature=None,
                 max_tokens=None, tools=None):
    """返回完整 message 对象（含 tool_calls）。工具调用必须走非流式。

    和 chat() 的区别：chat() 只要文本，这个要整个 message——
    因为主意识可能不是"说话"，而是"要求调用工具"。
    """
    url = api["base_url"].rstrip("/") + "/chat/completions"
    payload = _build_payload(
        cfg, messages, model or cfg["model"], False, temperature, max_tokens
    )
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"

    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=_headers(api["api_key"])
    )
    try:
        with urllib.request.urlopen(req, timeout=api.get("timeout_sec", 180)) as r:
            body = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM 连不上: {e.reason}") from None

    try:
        return body["choices"][0]["message"]
    except (KeyError, IndexError):
        raise RuntimeError(f"LLM 返回格式不对: {json.dumps(body)[:500]}")


def chat_stream(api, cfg, messages, model=None, temperature=None, max_tokens=None):
    """流式调用。逐段 yield 文本增量。"""
    url = api["base_url"].rstrip("/") + "/chat/completions"
    payload = _build_payload(
        cfg, messages, model or cfg["model"], True, temperature, max_tokens
    )
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=_headers(api["api_key"])
    )
    try:
        resp = urllib.request.urlopen(req, timeout=api.get("timeout_sec", 180))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"LLM HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"LLM 连不上: {e.reason}") from None

    with resp:
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except json.JSONDecodeError:
                continue
            choices = obj.get("choices") or []
            if not choices:
                continue
            delta = choices[0].get("delta") or {}
            # 推理模型会把思考放在 reasoning_content，一起收，别丢
            piece = delta.get("content")
            if piece:
                yield piece
            think = delta.get("reasoning_content")
            if think:
                yield think
