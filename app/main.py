from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Form, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.lobby import Lobby, LobbyError


BASE_DIR = Path(__file__).resolve().parent

app = FastAPI(title="Acquire Pregame Lobby")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")

lobby = Lobby()
connections: dict[str, WebSocket] = {}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"snapshot": lobby.snapshot()},
    )


@app.post("/join")
async def join(player_name: str = Form(...)) -> JSONResponse:
    try:
        player = lobby.join(player_name)
    except LobbyError as error:
        return JSONResponse({"error": str(error), "lobby": lobby.snapshot()}, status_code=400)

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
    await websocket.send_json({"type": "lobby", "lobby": lobby.snapshot()})

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        if connections.get(player_id) is websocket:
            connections.pop(player_id, None)
            await remove_player(player_id)


async def remove_player(player_id: str) -> None:
    before = lobby.snapshot()
    lobby.leave(player_id)
    if before != lobby.snapshot():
        await broadcast_lobby()


async def broadcast_lobby() -> None:
    message = {"type": "lobby", "lobby": lobby.snapshot()}
    disconnected: list[str] = []

    for player_id, websocket in connections.items():
        try:
            await websocket.send_json(message)
        except RuntimeError:
            disconnected.append(player_id)

    for player_id in disconnected:
        connections.pop(player_id, None)
