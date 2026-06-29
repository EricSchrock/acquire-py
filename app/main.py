from __future__ import annotations

import logging
import os
import json
from pathlib import Path
import socket
import sys
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Sequence

from fastapi import FastAPI, Form, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.game import Game, GameError
from app.lobby import Lobby, LobbyError


logger = logging.getLogger("uvicorn.error")
BASE_DIR = Path(__file__).resolve().parent
LOOPBACK_HOST = "127.0.0.1"


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log_join_urls()
    yield


app = FastAPI(title="Acquire", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

lobby = Lobby()
game: Game | None = None
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
        {"snapshot": lobby.snapshot(), "game_snapshot": None},
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
    await broadcast_state()
    return JSONResponse({"player_id": player.id, "lobby": lobby.snapshot(), "game": None})


@app.post("/start")
async def start(player_id: str = Form(...)) -> JSONResponse:
    global game
    try:
        lobby.start(player_id)
        game = Game.new([(player.id, player.name) for player in lobby.players])
    except LobbyError as error:
        return JSONResponse({"error": str(error), "lobby": lobby.snapshot(), "game": None}, status_code=400)
    except GameError as error:
        return JSONResponse({"error": str(error), "lobby": lobby.snapshot(), "game": None}, status_code=400)

    await broadcast_state()
    return JSONResponse({"lobby": lobby.snapshot(), "game": game.snapshot(player_id)})


@app.post("/leave")
async def leave(player_id: str = Form(...)) -> JSONResponse:
    await remove_player(player_id)
    return JSONResponse({"lobby": lobby.snapshot(), "game": game_snapshot(player_id)})


@app.post("/game/place-tile")
async def place_tile(player_id: str = Form(...), tile: str = Form(...)) -> JSONResponse:
    return await game_action(player_id, lambda active_game: active_game.place_tile(player_id, tile))


@app.post("/game/found-chain")
async def found_chain(player_id: str = Form(...), chain: str = Form(...)) -> JSONResponse:
    return await game_action(player_id, lambda active_game: active_game.found_chain(player_id, chain))


@app.post("/game/choose-survivor")
async def choose_survivor(player_id: str = Form(...), chain: str = Form(...)) -> JSONResponse:
    return await game_action(player_id, lambda active_game: active_game.choose_survivor(player_id, chain))


@app.post("/game/resolve-merge")
async def resolve_merge(player_id: str = Form(...), decisions: str = Form("{}")) -> JSONResponse:
    try:
        parsed_decisions = json.loads(decisions)
    except json.JSONDecodeError:
        parsed_decisions = {}
    return await game_action(player_id, lambda active_game: active_game.resolve_merge(player_id, parsed_decisions))


@app.post("/game/buy-stock")
async def buy_stock(player_id: str = Form(...), purchases: str = Form("")) -> JSONResponse:
    requested = [purchase for purchase in purchases.split(",") if purchase]
    return await game_action(player_id, lambda active_game: active_game.buy_stock(player_id, requested))

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
    await websocket.send_json(state_message(player_id))

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
        await broadcast_state()


async def game_action(player_id: str, action) -> JSONResponse:
    if game is None:
        return JSONResponse({"error": "The game has not started.", "lobby": lobby.snapshot(), "game": None}, status_code=400)
    try:
        action(game)
    except GameError as error:
        return JSONResponse({"error": str(error), "lobby": lobby.snapshot(), "game": game.snapshot(player_id)}, status_code=400)

    await broadcast_state()
    return JSONResponse({"lobby": lobby.snapshot(), "game": game.snapshot(player_id)})


async def broadcast_lobby() -> None:
    await broadcast_state()


async def broadcast_state() -> None:
    disconnected: list[str] = []

    for player_id, websocket in connections.items():
        try:
            await websocket.send_json(state_message(player_id))
        except (RuntimeError, WebSocketDisconnect):
            disconnected.append(player_id)

    for player_id in disconnected:
        connections.pop(player_id, None)


def state_message(player_id: str) -> dict:
    return {"type": "state", "lobby": lobby.snapshot(), "game": game_snapshot(player_id)}


def game_snapshot(player_id: str) -> dict | None:
    return game.snapshot(player_id) if game else None


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
