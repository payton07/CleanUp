"""FastAPI application: REST endpoints + a WebSocket for live sort progress.

Binds to localhost only — this drives the local filesystem and is not meant to
be exposed. Serves a single self-contained page from ``static/index.html``.
"""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import service
from .service import SortOptions

_STATIC = Path(__file__).parent / "static"

app = FastAPI(title="CleanUp", docs_url=None, redoc_url=None)


# ─── REQUEST MODELS ─────────────────────────────────────────────────────────

class PathBody(BaseModel):
    path: str


class ScanBody(BaseModel):
    path: str
    recursive: bool = False
    smart: bool = False
    scheme: str = "type"
    conflict: str = "rename"
    extensions: list[str] = []
    clean_empty: bool = False
    no_trash: bool = False
    ai: bool = False
    ai_creative: bool = False
    ai_model: str | None = None

    def to_options(self) -> SortOptions:
        return SortOptions(
            recursive=self.recursive, smart=self.smart, scheme=self.scheme,
            conflict=self.conflict, extensions=self.extensions,
            clean_empty=self.clean_empty, no_trash=self.no_trash,
            ai=self.ai, ai_creative=self.ai_creative, ai_model=self.ai_model,
        )


class CorrectBody(BaseModel):
    path: str
    src: str
    category: str


class DedupeBody(BaseModel):
    path: str
    recursive: bool = True


class DedupeApplyBody(BaseModel):
    path: str
    action: str = "move"
    no_trash: bool = False


# ─── PAGE ───────────────────────────────────────────────────────────────────

@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


# ─── API ────────────────────────────────────────────────────────────────────

@app.get("/api/browse")
def api_browse(path: str | None = None) -> JSONResponse:
    return JSONResponse(service.browse(path))


@app.get("/api/ai/status")
def api_ai_status() -> JSONResponse:
    return JSONResponse(service.ai_status())


@app.post("/api/ai/correct")
def api_ai_correct(body: CorrectBody) -> JSONResponse:
    try:
        directory = service.resolve_dir(body.path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(service.record_correction(directory, body.src, body.category))


@app.post("/api/scan")
def api_scan(body: ScanBody) -> JSONResponse:
    try:
        directory = service.resolve_dir(body.path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(service.scan(directory, body.to_options()))


@app.get("/api/history")
def api_history(path: str) -> JSONResponse:
    try:
        directory = service.resolve_dir(path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(service.history(directory))


@app.post("/api/undo")
def api_undo(body: PathBody) -> JSONResponse:
    directory = service.resolve_dir(body.path)
    return JSONResponse(service.undo(directory))


@app.post("/api/redo")
def api_redo(body: PathBody) -> JSONResponse:
    directory = service.resolve_dir(body.path)
    return JSONResponse(service.redo(directory))


@app.post("/api/dedupe")
def api_dedupe(body: DedupeBody) -> JSONResponse:
    try:
        directory = service.resolve_dir(body.path)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(service.dedupe_scan(directory, body.recursive))


@app.post("/api/dedupe/apply")
def api_dedupe_apply(body: DedupeApplyBody) -> JSONResponse:
    directory = service.resolve_dir(body.path)
    return JSONResponse(service.dedupe_apply(directory, body.action, body.no_trash))


# ─── WEBSOCKET: live sort ───────────────────────────────────────────────────

@app.websocket("/ws/sort")
async def ws_sort(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        request = await websocket.receive_json()
        try:
            directory = service.resolve_dir(request["path"])
        except (ValueError, KeyError) as exc:
            await websocket.send_json({"type": "error", "message": str(exc)})
            await websocket.close()
            return

        opts = ScanBody(**request).to_options()
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def on_event(payload: dict) -> None:
            loop.call_soon_threadsafe(queue.put_nowait, payload)

        async def run() -> None:
            summary = await asyncio.to_thread(service.run_sort, directory, opts, on_event)
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "summary", **summary})
            loop.call_soon_threadsafe(queue.put_nowait, None)

        task = asyncio.create_task(run())
        while True:
            item = await queue.get()
            if item is None:
                break
            await websocket.send_json(item)
        await task
        await websocket.close()
    except WebSocketDisconnect:
        pass


# ─── LAUNCHER ───────────────────────────────────────────────────────────────

def run(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    """Start the server and (optionally) open the browser."""
    import uvicorn

    url = f"http://{host}:{port}"
    print(f"\n  ✨ CleanUp web UI → {url}\n  (Ctrl+C to stop)\n")
    if open_browser:
        # Delay so the browser opens after the server is accepting connections.
        import threading
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(prog="cleanup-web", description="Launch the CleanUp web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true", help="Do not open a browser window")
    args = parser.parse_args()
    run(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
