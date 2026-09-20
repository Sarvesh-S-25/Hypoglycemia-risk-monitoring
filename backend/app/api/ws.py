"""
/ws/live -- docs/API_CONTRACT.md section 4.

Sends a `hello` frame with the same payload as GET /api/status immediately on
connect (so the client has full state without a second round-trip), then fans
out every frame published to the module-level event bus until the client
disconnects.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.events import bus

logger = logging.getLogger("glucosentry.ws")

router = APIRouter()


@router.websocket("/ws/live")
async def ws_live(websocket: WebSocket) -> None:
    await websocket.accept()
    gs = websocket.app.state.gs

    await websocket.send_json({"type": "hello", "data": gs.status_dict()})

    queue = bus.subscribe()
    try:
        while True:
            frame = await queue.get()
            await websocket.send_json(frame.to_dict())
    except WebSocketDisconnect:
        logger.debug("client disconnected from /ws/live")
    except asyncio.CancelledError:
        raise
    finally:
        bus.unsubscribe(queue)
