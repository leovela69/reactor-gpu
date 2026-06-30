"""aiohttp web server — REACTOR REST API."""

from __future__ import annotations

import logging
from typing import Any

from aiohttp import web

from .config import BRIDGE_SECRET, REACTOR_PORT
from .coordinator import Coordinator
from .models.task import Task, TaskPriority, TaskStatus, TaskType

logger = logging.getLogger("reactor.api")


def auth_middleware():
    """Bearer token authentication middleware."""

    @web.middleware
    async def middleware(request: web.Request, handler):
        # Skip auth for health check
        if request.path == "/health":
            return await handler(request)

        if BRIDGE_SECRET:
            auth = request.headers.get("Authorization", "")
            if not auth.startswith("Bearer ") or auth[7:] != BRIDGE_SECRET:
                return web.json_response(
                    {"error": "Unauthorized"}, status=401
                )
        return await handler(request)

    return middleware


async def health(request: web.Request) -> web.Response:
    """GET /health — basic health check."""
    return web.json_response({
        "status": "ok",
        "service": "reactor-gpu",
        "version": "1.0.0",
    })


async def generate(request: web.Request) -> web.Response:
    """POST /api/generate — submit a new task."""
    coordinator: Coordinator = request.app["coordinator"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    # Validate task type
    task_type_str = body.get("type", "image_hd")
    try:
        task_type = TaskType(task_type_str)
    except ValueError:
        return web.json_response(
            {"error": f"Invalid type: {task_type_str}", "valid": [t.value for t in TaskType]},
            status=400,
        )

    # Validate priority
    priority_val = body.get("priority", 2)
    try:
        priority = TaskPriority(int(priority_val))
    except (ValueError, KeyError):
        priority = TaskPriority.NORMAL

    prompt = body.get("prompt", "")
    if not prompt:
        return web.json_response({"error": "prompt is required"}, status=400)

    task = Task(
        type=task_type,
        priority=priority,
        prompt=prompt,
        params=body.get("params", {}),
        source_bot=body.get("source", "api"),
        callback_url=body.get("callback_url"),
    )

    await coordinator.submit_task(task)

    return web.json_response({
        "task_id": task.id,
        "status": task.status.value,
        "type": task.type.value,
        "priority": task.priority.name,
    }, status=202)


async def status(request: web.Request) -> web.Response:
    """GET /api/status — coordinator status."""
    coordinator: Coordinator = request.app["coordinator"]
    return web.json_response(coordinator.get_status())


async def quota(request: web.Request) -> web.Response:
    """GET /api/quota — quota information."""
    coordinator: Coordinator = request.app["coordinator"]
    return web.json_response(coordinator.quota.get_all_quotas())


async def get_task(request: web.Request) -> web.Response:
    """GET /api/task/{id} — get task details."""
    coordinator: Coordinator = request.app["coordinator"]
    task_id = request.match_info["id"]
    task = coordinator.get_task(task_id)
    if not task:
        return web.json_response({"error": "Task not found"}, status=404)
    return web.json_response(task.to_dict())


async def cancel_task(request: web.Request) -> web.Response:
    """POST /api/cancel/{id} — cancel a task."""
    coordinator: Coordinator = request.app["coordinator"]
    task_id = request.match_info["id"]
    success = await coordinator.cancel_task(task_id)
    if not success:
        return web.json_response({"error": "Cannot cancel task"}, status=400)
    return web.json_response({"cancelled": True, "task_id": task_id})


async def notify_complete(request: web.Request) -> web.Response:
    """POST /api/notify — callback for external workers (Kaggle)."""
    coordinator: Coordinator = request.app["coordinator"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    task_id = body.get("task_id")
    task = coordinator.get_task(task_id)
    if not task:
        return web.json_response({"error": "Task not found"}, status=404)

    if body.get("success"):
        task.mark_completed(
            result_url=body.get("url"),
            result_data=body.get("data"),
        )
    else:
        error = body.get("error", "External worker failed")
        if task.can_retry:
            task.mark_retrying()
        else:
            task.mark_failed(error)

    return web.json_response({"ok": True})


def create_app(coordinator: Coordinator) -> web.Application:
    """Create and configure the aiohttp application."""
    app = web.Application(middlewares=[auth_middleware()])
    app["coordinator"] = coordinator

    app.router.add_get("/health", health)
    app.router.add_post("/api/generate", generate)
    app.router.add_get("/api/status", status)
    app.router.add_get("/api/quota", quota)
    app.router.add_get("/api/task/{id}", get_task)
    app.router.add_post("/api/cancel/{id}", cancel_task)
    app.router.add_post("/api/notify", notify_complete)

    return app


async def start_server(coordinator: Coordinator) -> web.AppRunner:
    """Start the API server."""
    app = create_app(coordinator)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", REACTOR_PORT)
    await site.start()
    logger.info(f"REACTOR API listening on 0.0.0.0:{REACTOR_PORT}")
    return runner
