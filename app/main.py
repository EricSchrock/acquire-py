from __future__ import annotations

import logging
import os
from pathlib import Path
import socket
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Sequence

from fastapi import FastAPI, Form, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.lobby import Lobby, LobbyError


logger = logging.getLogger("uvicorn.error")
BASE_DIR = Path(__file__).resolve().parent
LOOPBACK_HOST = "127.0.0.1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log_join_urls()
    yield


app = FastAPI(title="Acquire Pregame Lobby", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

lobby = Lobby()
connections: dict[str, WebSocket] = {}
FAVICON = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="10" fill="#0f6b5f"/>
  <text x="32" y="42" text-anchor="middle" font-family="Arial, sans-serif" font-size="32" font-weight="700" fill="white">A</text>
</svg>"""


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"snapshot": lobby.snapshot()},
    )


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(content=FAVICON, media_type="image/svg+xml")


@app.post("/join")
async def join(player_name: str = Form(...)) -> JSONResponse:
    try:
        player = lobby.join(player_name)
    except LobbyError as error:
        return JSONResponse({"error": str(error), "lobby": lobby.snapshot()}, status_code=400)

    logger.info("Player joined lobby: %s", player.name)
    await broadcast_lobby()
    return JSONResponse({"player_id": player.id, "lobby": lobby.snapshot()})


@app.post("/start")
async def start(player_id: str = Form(...)) -> JSONResponse:
    try:
        lobby.start(player_id)
    except LobbyError as error:
        return JSONResponse({"error": str(error), "lobby": lobby.snapshot()}, status_code=400)

    await broadcast_lobby()
    return JSONResponse({"lobby": lobby.snapshot()})


@app.post("/leave")
async def leave(player_id: str = Form(...)) -> JSONResponse:
    await remove_player(player_id)
    return JSONResponse({"lobby": lobby.snapshot()})


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    player_id: str = Query(...),
) -> None:
    if not any(player.id == player_id for player in lobby.players):
        await websocket.close(code=1008)
        return

    await websocket.accept()

    old_connection = connections.pop(player_id, None)
    if old_connection is not None:
        await old_connection.close(code=1000)

    connections[player_id] = websocket
    logger.info("Player connected to lobby: %s", player_name(player_id))
    await websocket.send_json({"type": "lobby", "lobby": lobby.snapshot()})

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if connections.get(player_id) is websocket:
            connections.pop(player_id, None)
            await remove_player(player_id)


async def remove_player(player_id: str) -> None:
    name = player_name(player_id)
    before = lobby.snapshot()
    lobby.leave(player_id)
    if before != lobby.snapshot():
        logger.info("Player disconnected from lobby: %s", name)
        await broadcast_lobby()


async def broadcast_lobby() -> None:
    message = {"type": "lobby", "lobby": lobby.snapshot()}
    disconnected: list[str] = []

    for player_id, websocket in connections.items():
        try:
            await websocket.send_json(message)
        except (RuntimeError, WebSocketDisconnect):
            disconnected.append(player_id)

    for player_id in disconnected:
        connections.pop(player_id, None)


def player_name(player_id: str) -> str:
    for player in lobby.players:
        if player.id == player_id:
            return player.name
    return "unknown player"


def log_join_urls() -> None:
    logger.info("Players can join this lobby at:")
    for url in join_urls(configured_port()):
        logger.info("  %s", url)


def join_urls(port: int, addresses: Sequence[str] | None = None) -> list[str]:
    if addresses is None:
        addresses = local_ipv4_addresses()

    urls = [f"http://{LOOPBACK_HOST}:{port}"]
    urls.extend(f"http://{address}:{port}" for address in addresses if address != LOOPBACK_HOST)
    return list(dict.fromkeys(urls))


def local_ipv4_addresses() -> list[str]:
    addresses: set[str] = set()
    try:
        for address in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not address.startswith("127."):
                addresses.add(address)
    except OSError:
        pass
    return sorted(addresses)


def configured_port(argv: Sequence[str] | None = None) -> int:
    env_port = os.environ.get("ACQUIRE_PORT")
    if env_port:
        return int(env_port)

    args = list(sys.argv if argv is None else argv)
    for index, arg in enumerate(args):
        if arg == "--port" and index + 1 < len(args):
            return int(args[index + 1])
        if arg.startswith("--port="):
            return int(arg.split("=", 1)[1])

    return 8000
