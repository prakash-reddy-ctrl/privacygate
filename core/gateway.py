"""
PrivacyGateAI - AI Gateway Layer
Handles the full round-trip: sanitize → call AI → restore.
Supports both Anthropic Claude and OpenAI GPT models.
"""

import os
import httpx
import json
from typing import AsyncIterator
from dataclasses import dataclass

from core.engine import PrivacyEngine, SanitizeResult


@dataclass
class GatewayResponse:
    original_prompt: str
    sanitized_prompt: str
    raw_ai_response: str
    restored_response: str
    entity_count: int
    entity_types: list[str]
    model_used: str
    provider: str


class AIGateway:
    """
    The central gateway that orchestrates the full pipeline:
    User prompt → Sanitize → AI Model → Restore → User response
    """

    SUPPORTED_PROVIDERS = ["anthropic", "openai"]

    def __init__(
        self,
        provider: str = "anthropic",
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
    ):
        if provider not in self.SUPPORTED_PROVIDERS:
            raise ValueError(f"Provider must be one of {self.SUPPORTED_PROVIDERS}")

        self.provider = provider
        self.model = model
        self.api_key = api_key or self._get_api_key(provider)
        self.engine = PrivacyEngine()

    def _get_api_key(self, provider: str) -> str:
        key_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        key = os.getenv(key_map[provider])
        if not key:
            raise ValueError(
                f"No API key found. Set {key_map[provider]} environment variable."
            )
        return key

    async def process(
        self,
        prompt: str,
        system_prompt: str | None = None,
        session_id: str | None = None,
        max_tokens: int = 1024,
    ) -> GatewayResponse:
        """
        Full pipeline: sanitize → AI → restore.
        This is the main method your API will call.
        """
        import uuid
        session_id = session_id or str(uuid.uuid4())

        # Step 1: Sanitize the prompt
        sanitize_result = self.engine.sanitize(prompt, session_id)

        # Step 2: Also sanitize the system prompt if provided
        sanitized_system = None
        if system_prompt:
            sys_result = self.engine.sanitize(system_prompt, session_id)
            sanitized_system = sys_result.sanitized_text
            # Merge entity maps
            sanitize_result.entity_map.update(sys_result.entity_map)

        # Step 3: Call the AI model with sanitized data
        if self.provider == "anthropic":
            raw_response = await self._call_anthropic(
                sanitize_result.sanitized_text,
                sanitized_system,
                max_tokens,
            )
        else:
            raw_response = await self._call_openai(
                sanitize_result.sanitized_text,
                sanitized_system,
                max_tokens,
            )

        # Step 4: Restore original values in the AI response
        restored = self.engine.restore(raw_response, sanitize_result.entity_map)

        return GatewayResponse(
            original_prompt=prompt,
            sanitized_prompt=sanitize_result.sanitized_text,
            raw_ai_response=raw_response,
            restored_response=restored,
            entity_count=sanitize_result.entity_count,
            entity_types=sanitize_result.entity_types,
            model_used=self.model,
            provider=self.provider,
        )

    async def _call_anthropic(
        self,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int,
    ) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

        body: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }

        if system_prompt:
            body["system"] = system_prompt

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["content"][0]["text"]

    async def _call_openai(
        self,
        prompt: str,
        system_prompt: str | None,
        max_tokens: int,
    ) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        body = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": messages,
        }

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
