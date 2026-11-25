"""Local ASGI entrypoint with bounded uploads and concurrent analysis."""
import asyncio
from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders
from app import app as core_app

MAX_REQUEST_BYTES = 11 * 1024 * 1024
_slots = asyncio.Semaphore(2)

async def app(scope, receive, send):
    if scope["type"] != "http":
        await core_app(scope, receive, send)
        return
    request = Request(scope, receive)
    async def guarded_send(message):
        if message["type"] == "http.response.start":
            headers = MutableHeaders(scope=message)
            headers["Cache-Control"] = "no-store"
            headers["X-Content-Type-Options"] = "nosniff"
            headers["X-Frame-Options"] = "DENY"
            headers["Referrer-Policy"] = "no-referrer"
        await send(message)
    async def respond(response):
        await response(scope, receive, guarded_send)
    # This is an unauthenticated local tool, not a public hosted service.
    if request.method != "POST" or request.url.path not in ("/preview", "/analyze"):
        await core_app(scope, receive, guarded_send)
        return
    origin = request.headers.get("origin")
    if origin and origin != str(request.base_url).rstrip("/"):
        await respond(JSONResponse({"detail": "Cross-origin upload refused."}, status_code=403))
        return
    if not request.headers.get(
        "content-type",
        "",
    ).lower().startswith(
        "multipart/form-data;"
    ):
        await respond(
            JSONResponse(
                {
                    "detail":
                        "Multipart upload required."
                },
                status_code=415,
            )
        )
        return

    size = request.headers.get(
        "content-length",
        "",
    )

    if size:
        try:
            if int(size) > MAX_REQUEST_BYTES:
                await respond(
                    JSONResponse(
                        {
                            "detail":
                                "Total upload request "
                                "exceeds 11 MB."
                        },
                        status_code=413,
                    )
                )
                return

        except ValueError:
            await respond(
                JSONResponse(
                    {
                        "detail":
                            "Invalid Content-Length."
                    },
                    status_code=400,
                )
            )
            return

    try:
        await asyncio.wait_for(
            _slots.acquire(),
            timeout=0.25,
        )

    except asyncio.TimeoutError:
        await respond(
            JSONResponse(
                {
                    "detail":
                        "Analyzer is busy; retry shortly."
                },
                status_code=503,
                headers={
                    "Retry-After": "3"
                },
            )
        )
        return

    try:
        chunks = bytearray()

        try:
            async with asyncio.timeout(60):
                async for piece in request.stream():
                    if (
                        len(chunks) + len(piece)
                        > MAX_REQUEST_BYTES
                    ):
                        await respond(
                            JSONResponse(
                                {
                                    "detail":
                                        "Total upload request "
                                        "exceeds 11 MB."
                                },
                                status_code=413,
                            )
                        )
                        return

                    chunks.extend(piece)

        except TimeoutError:
            await respond(
                JSONResponse(
                    {
                        "detail": "Upload timed out."
                    },
                    status_code=408,
                )
            )
            return

        except Exception:
            await respond(
                JSONResponse(
                    {
                        "detail": "Upload interrupted."
                    },
                    status_code=400,
                )
            )
            return

        payload = bytes(chunks)
        delivered = False

        async def replay_receive():
            nonlocal delivered

            if not delivered:
                delivered = True

                return {
                    "type": "http.request",
                    "body": payload,
                    "more_body": False,
                }

            return await receive()

        await core_app(
            scope,
            replay_receive,
            guarded_send,
        )

    finally:
        _slots.release()