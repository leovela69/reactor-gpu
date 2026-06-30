"""APIPoolWorker — rotates between free/cheap API sources."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

import aiohttp

from ..config import (
    AGNES_API_KEY,
    HUGGINGFACE_TOKEN,
    POLLINATIONS_API_KEY,
)
from ..models.task import Task, TaskType

logger = logging.getLogger("reactor.workers.api_pool")


class APIPoolWorker:
    """Worker that rotates between free API sources with fallthrough on failure."""

    def __init__(self, preferred_source: Optional[str] = None):
        self.preferred_source = preferred_source
        self.name = f"api_{preferred_source}" if preferred_source else "api_pool"
        self._sources = [
            ("pollinations", self._call_pollinations),
            ("agnes", self._call_agnes),
            ("huggingface", self._call_huggingface),
        ]

    async def execute(self, task: Task) -> dict[str, Any]:
        """Try each API source in order, fall through on failure."""
        sources = self._sources.copy()

        # Move preferred source to front
        if self.preferred_source:
            sources.sort(key=lambda x: 0 if x[0] == self.preferred_source else 1)

        errors = []
        for source_name, handler in sources:
            if not self._supports_task(source_name, task.type):
                continue

            try:
                result = await handler(task)
                if result.get("success"):
                    result["source"] = source_name
                    return result
                errors.append(f"{source_name}: {result.get('error', 'unknown')}")
            except Exception as e:
                errors.append(f"{source_name}: {str(e)}")
                logger.warning(f"API source {source_name} failed: {e}")

        return {
            "success": False,
            "error": f"All API sources failed: {'; '.join(errors)}",
        }

    def _supports_task(self, source: str, task_type: TaskType) -> bool:
        """Check if a source supports the given task type."""
        support_map = {
            "pollinations": [
                TaskType.VIDEO_EXPRESS, TaskType.IMAGE_HD,
                TaskType.IMAGE_EXPRESS, TaskType.AUDIO_MUSIC,
            ],
            "agnes": [
                TaskType.VIDEO_EXPRESS, TaskType.VIDEO_HD, TaskType.IMAGE_HD,
            ],
            "huggingface": [
                TaskType.IMAGE_HD, TaskType.IMAGE_EXPRESS,
                TaskType.LLM_LIGHT, TaskType.AUDIO,
            ],
        }
        return task_type in support_map.get(source, [])

    async def _call_pollinations(self, task: Task) -> dict[str, Any]:
        """Call Pollinations API for image/video generation."""
        timeout = aiohttp.ClientTimeout(total=120)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            if task.type in (TaskType.IMAGE_HD, TaskType.IMAGE_EXPRESS):
                # Pollinations image endpoint
                url = "https://image.pollinations.ai/prompt/" + task.prompt.replace(" ", "%20")
                params = {
                    "width": task.params.get("width", 1024),
                    "height": task.params.get("height", 1024),
                    "model": task.params.get("model", "flux"),
                    "nologo": "true",
                }
                async with session.get(url, params=params) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        return {
                            "success": True,
                            "url": str(resp.url),
                            "data": {"size_bytes": len(data), "source": "pollinations"},
                        }
                    return {"success": False, "error": f"Pollinations HTTP {resp.status}"}

            elif task.type == TaskType.VIDEO_EXPRESS:
                # Pollinations video endpoint
                url = "https://text.pollinations.ai/"
                payload = {
                    "prompt": task.prompt,
                    "model": "openai-video",
                }
                headers = {}
                if POLLINATIONS_API_KEY:
                    headers["Authorization"] = f"Bearer {POLLINATIONS_API_KEY}"

                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        return {
                            "success": True,
                            "url": result.get("url", ""),
                            "data": result,
                        }
                    return {"success": False, "error": f"Pollinations video HTTP {resp.status}"}

            elif task.type == TaskType.AUDIO_MUSIC:
                url = f"https://audio.pollinations.ai/{task.prompt.replace(' ', '%20')}"
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        return {
                            "success": True,
                            "data": {"size_bytes": len(data), "source": "pollinations"},
                        }
                    return {"success": False, "error": f"Pollinations audio HTTP {resp.status}"}

        return {"success": False, "error": "Unsupported task type for Pollinations"}

    async def _call_agnes(self, task: Task) -> dict[str, Any]:
        """Call Agnes AI API for video/image generation."""
        if not AGNES_API_KEY:
            return {"success": False, "error": "Agnes API key not configured"}

        timeout = aiohttp.ClientTimeout(total=180)
        headers = {
            "Authorization": f"Bearer {AGNES_API_KEY}",
            "Content-Type": "application/json",
        }

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            if task.type in (TaskType.VIDEO_EXPRESS, TaskType.VIDEO_HD):
                url = "https://api.agnes.ai/v1/video/generate"
                payload = {
                    "prompt": task.prompt,
                    "duration": task.params.get("duration", 5),
                    "resolution": "1080p" if task.type == TaskType.VIDEO_HD else "720p",
                    "model": task.params.get("model", "agnes-v1"),
                }
            else:
                url = "https://api.agnes.ai/v1/image/generate"
                payload = {
                    "prompt": task.prompt,
                    "width": task.params.get("width", 1024),
                    "height": task.params.get("height", 1024),
                }

            async with session.post(url, json=payload) as resp:
                if resp.status == 200:
                    result = await resp.json()
                    return {
                        "success": True,
                        "url": result.get("url", ""),
                        "data": result,
                    }
                body = await resp.text()
                return {"success": False, "error": f"Agnes HTTP {resp.status}: {body[:200]}"}

    async def _call_huggingface(self, task: Task) -> dict[str, Any]:
        """Call HuggingFace Inference API."""
        if not HUGGINGFACE_TOKEN:
            return {"success": False, "error": "HuggingFace token not configured"}

        timeout = aiohttp.ClientTimeout(total=120)
        headers = {
            "Authorization": f"Bearer {HUGGINGFACE_TOKEN}",
        }

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            if task.type in (TaskType.IMAGE_HD, TaskType.IMAGE_EXPRESS):
                model = task.params.get("model", "stabilityai/stable-diffusion-xl-base-1.0")
                url = f"https://api-inference.huggingface.co/models/{model}"
                payload = {"inputs": task.prompt}

                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        return {
                            "success": True,
                            "data": {"size_bytes": len(data), "source": "huggingface", "model": model},
                        }
                    body = await resp.text()
                    return {"success": False, "error": f"HuggingFace HTTP {resp.status}: {body[:200]}"}

            elif task.type == TaskType.LLM_LIGHT:
                model = task.params.get("model", "meta-llama/Meta-Llama-3-8B-Instruct")
                url = f"https://api-inference.huggingface.co/models/{model}"
                payload = {
                    "inputs": task.prompt,
                    "parameters": {
                        "max_new_tokens": task.params.get("max_tokens", 512),
                        "temperature": task.params.get("temperature", 0.7),
                    },
                }

                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        text = result[0].get("generated_text", "") if isinstance(result, list) else str(result)
                        return {
                            "success": True,
                            "data": {"text": text, "source": "huggingface", "model": model},
                        }
                    body = await resp.text()
                    return {"success": False, "error": f"HuggingFace HTTP {resp.status}: {body[:200]}"}

            elif task.type == TaskType.AUDIO:
                model = task.params.get("model", "facebook/musicgen-small")
                url = f"https://api-inference.huggingface.co/models/{model}"
                payload = {"inputs": task.prompt}

                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        return {
                            "success": True,
                            "data": {"size_bytes": len(data), "source": "huggingface"},
                        }
                    body = await resp.text()
                    return {"success": False, "error": f"HuggingFace audio HTTP {resp.status}: {body[:200]}"}

        return {"success": False, "error": "Unsupported task type for HuggingFace"}
