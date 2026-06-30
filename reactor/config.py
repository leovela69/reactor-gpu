"""Configuration loading from environment variables for REACTOR."""

from __future__ import annotations

import os
from typing import Any


def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int = 0) -> int:
    return int(os.environ.get(key, str(default)))


# ─── Server ──────────────────────────────────────────────────────────────────
REACTOR_PORT: int = _env_int("REACTOR_PORT", 9091)
BRIDGE_SECRET: str = _env("BRIDGE_SECRET", "")

# ─── Modal (remote GPU) ─────────────────────────────────────────────────────
MODAL_TOKEN_ID: str = _env("MODAL_TOKEN_ID")
MODAL_TOKEN_SECRET: str = _env("MODAL_TOKEN_SECRET")

# ─── Kaggle ──────────────────────────────────────────────────────────────────
KAGGLE_USERNAME: str = _env("KAGGLE_USERNAME")
KAGGLE_KEY: str = _env("KAGGLE_KEY")

# ─── Lightning AI ────────────────────────────────────────────────────────────
LIGHTNING_API_KEY: str = _env("LIGHTNING_API_KEY")

# ─── HuggingFace ─────────────────────────────────────────────────────────────
HUGGINGFACE_TOKEN: str = _env("HUGGINGFACE_TOKEN")

# ─── Magic Hour ──────────────────────────────────────────────────────────────
MAGIC_HOUR_API_KEY: str = _env("MAGIC_HOUR_API_KEY")

# ─── Kling AI ────────────────────────────────────────────────────────────────
KLING_ACCESS_KEY: str = _env("KLING_ACCESS_KEY")
KLING_SECRET_KEY: str = _env("KLING_SECRET_KEY")

# ─── Google AI (Veo3, Gemini) ────────────────────────────────────────────────
GOOGLE_AI_API_KEY: str = _env("GOOGLE_AI_API_KEY")

# ─── Agnes AI ────────────────────────────────────────────────────────────────
AGNES_API_KEY: str = _env("AGNES_API_KEY")

# ─── Pollinations ────────────────────────────────────────────────────────────
POLLINATIONS_API_KEY: str = _env("POLLINATIONS_API_KEY")


# ─── Worker Capabilities ─────────────────────────────────────────────────────
WORKER_CAPS: dict[str, dict[str, Any]] = {
    "modal_a100": {
        "vram_gb": 80,
        "tasks": [
            "video_4k", "video_hd", "video_express",
            "image_hd", "llm_heavy", "training",
        ],
        "speed": "fast",
        "availability": "on_demand",
    },
    "modal_t4": {
        "vram_gb": 16,
        "tasks": [
            "video_express", "image_hd", "image_express",
            "llm_light", "audio",
        ],
        "speed": "medium",
        "availability": "on_demand",
    },
    "kaggle_t4x2": {
        "vram_gb": 30,
        "tasks": [
            "video_hd", "video_express", "image_hd",
            "training", "llm_heavy",
        ],
        "speed": "slow",
        "availability": "limited",
    },
    "lightning_a10g": {
        "vram_gb": 24,
        "tasks": [
            "video_hd", "video_express", "image_hd",
            "llm_heavy", "audio",
        ],
        "speed": "medium",
        "availability": "limited",
    },
    "api_pollinations": {
        "vram_gb": 0,
        "tasks": [
            "video_express", "image_hd", "image_express",
            "audio_music",
        ],
        "speed": "fast",
        "availability": "always",
    },
    "api_agnes": {
        "vram_gb": 0,
        "tasks": ["video_express", "video_hd", "image_hd"],
        "speed": "medium",
        "availability": "always",
    },
    "api_huggingface": {
        "vram_gb": 0,
        "tasks": [
            "image_hd", "image_express", "llm_light",
            "audio",
        ],
        "speed": "medium",
        "availability": "rate_limited",
    },
    "api_magic_hour": {
        "vram_gb": 0,
        "tasks": ["video_express", "video_hd", "face_swap"],
        "speed": "fast",
        "availability": "limited",
    },
    "api_kling": {
        "vram_gb": 0,
        "tasks": ["video_hd", "video_4k", "image_hd"],
        "speed": "medium",
        "availability": "limited",
    },
    "api_veo3": {
        "vram_gb": 0,
        "tasks": ["video_hd", "video_4k"],
        "speed": "slow",
        "availability": "limited",
    },
}


# ─── Quota Limits (see quota_monitor.py) ─────────────────────────────────────
QUOTA_LIMITS: dict[str, dict[str, Any]] = {
    "modal": {"type": "monthly", "limit": 30.0, "unit": "usd"},
    "kaggle": {"type": "weekly", "limit": 30.0, "unit": "hours"},
    "lightning": {"type": "monthly", "limit": 22.0, "unit": "hours"},
    "magic_hour": {"type": "daily", "limit": 100, "unit": "requests"},
    "kling": {"type": "daily", "limit": 66, "unit": "requests"},
    "veo3": {"type": "monthly", "limit": 100, "unit": "requests"},
    "agnes": {"type": "unlimited", "limit": -1, "unit": "requests"},
    "huggingface": {"type": "rate_limited", "limit": 1000, "unit": "requests_per_day"},
    "pollinations": {"type": "rate_limited", "limit": 500, "unit": "requests_per_day"},
}
