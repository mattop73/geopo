import logging
from typing import AsyncGenerator

import httpx
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


async def stream_llm(prompt: str, model: str, system: str = "") -> AsyncGenerator[str, None]:
    if model.startswith("ollama:"):
        async for chunk in _stream_ollama(prompt, model[7:], system):
            yield chunk
    elif model.startswith("claude") or model.startswith("anthropic:"):
        model_id = model.replace("anthropic:", "")
        async for chunk in _stream_anthropic(prompt, model_id, system):
            yield chunk
    elif model.startswith("gpt") or model.startswith("openai:"):
        model_id = model.replace("openai:", "")
        async for chunk in _stream_openai(prompt, model_id, system):
            yield chunk
    else:
        yield f"Unknown model prefix: {model}. Use ollama:<model>, claude-*, or gpt-*"


async def _stream_ollama(prompt: str, model: str, system: str) -> AsyncGenerator[str, None]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{settings.ollama_base_url}/api/chat",
                json={"model": model, "messages": messages, "stream": True},
            ) as r:
                r.raise_for_status()
                import json
                async for line in r.aiter_lines():
                    if line:
                        try:
                            data = json.loads(line)
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                            if data.get("done"):
                                break
                        except json.JSONDecodeError:
                            continue
    except Exception as e:
        yield f"\n[Ollama error: {e}]"


async def _stream_anthropic(prompt: str, model: str, system: str) -> AsyncGenerator[str, None]:
    if not settings.anthropic_api_key:
        yield "[No ANTHROPIC_API_KEY configured]"
        return
    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        kwargs: dict = {
            "model": model or "claude-sonnet-4-6",
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        async with client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text
    except Exception as e:
        yield f"\n[Anthropic error: {e}]"


async def _stream_openai(prompt: str, model: str, system: str) -> AsyncGenerator[str, None]:
    if not settings.openai_api_key:
        yield "[No OPENAI_API_KEY configured]"
        return
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        stream = await client.chat.completions.create(
            model=model or "gpt-4o",
            messages=messages,
            stream=True,
            max_tokens=2048,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta
    except Exception as e:
        yield f"\n[OpenAI error: {e}]"


async def list_ollama_models() -> list[str]:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        return []
