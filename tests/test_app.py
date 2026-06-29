import logging
from asyncio import run

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import main
from app.lobby import Lobby


def make_client() -> TestClient:
    main.lobby = Lobby()
    main.game = None
    main.connections = {}
    return TestClient(main.app)


def test_join_endpoint_returns_player_id_and_snapshot():
    client = make_client()

    response = client.post("/join", data={"player_name": "Eric"})

    assert response.status_code == 200
    body = response.json()
    assert body["player_id"]
    assert body["lobby"]["players"][0]["name"] == "Eric"


def test_favicon_route_avoids_browser_404():
    client = make_client()

    response = client.get("/favicon.ico")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/svg+xml"


def test_start_endpoint_requires_host():
    client = make_client()
    host_id = client.post("/join", data={"player_name": "A"}).json()["player_id"]
    other_id = client.post("/join", data={"player_name": "B"}).json()["player_id"]

    response = client.post("/start", data={"player_id": other_id})

    assert response.status_code == 400
    assert "Only the host" in response.json()["error"]

    response = client.post("/start", data={"player_id": host_id})

    assert response.status_code == 200
    assert response.json()["lobby"]["status"] == "started"
    assert response.json()["game"]["phase"] == "place_tile"


def test_game_action_places_tile_after_start():
    client = make_client()
    host_id = client.post("/join", data={"player_name": "A"}).json()["player_id"]
    client.post("/join", data={"player_name": "B"})
    game = client.post("/start", data={"player_id": host_id}).json()["game"]
    tile = game["players"][0]["hand"][0]

    response = client.post("/game/place-tile", data={"player_id": host_id, "tile": tile})

    assert response.status_code == 200
    assert response.json()["game"]["board"][tile] is None


def test_waiting_websocket_disconnect_removes_player():
    client = make_client()
    player_id = client.post("/join", data={"player_name": "Eric"}).json()["player_id"]

    with client.websocket_connect(f"/ws?player_id={player_id}") as websocket:
        assert websocket.receive_json()["lobby"]["players"][0]["name"] == "Eric"

    assert main.lobby.players == []


def test_logs_player_names_for_connects_and_disconnects(caplog):
    client = make_client()

    with caplog.at_level(logging.INFO, logger="uvicorn.error"):
        player_id = client.post("/join", data={"player_name": "Eric"}).json()["player_id"]
        with client.websocket_connect(f"/ws?player_id={player_id}") as websocket:
            websocket.receive_json()

    messages = [record.getMessage() for record in caplog.records]
    assert "Player joined lobby: Eric" in messages
    assert "Player connected to lobby: Eric" in messages
    assert "Player disconnected from lobby: Eric" in messages


def test_broadcast_removes_websockets_that_disconnect_during_send():
    class ClosedWebSocket:
        async def send_json(self, message):
            raise WebSocketDisconnect(code=1006)

    main.lobby = Lobby()
    player = main.lobby.join("Eric")
    main.connections = {player.id: ClosedWebSocket()}

    run(main.broadcast_lobby())

    assert main.connections == {}


def test_join_urls_include_localhost_and_lan_addresses():
    urls = main.join_urls(8001, ["192.0.2.10", main.LOOPBACK_HOST])

    assert urls == ["http://127.0.0.1:8001", "http://192.0.2.10:8001"]


def test_configured_port_reads_uvicorn_port_argument(monkeypatch):
    monkeypatch.delenv("ACQUIRE_PORT", raising=False)

    assert main.configured_port(["uvicorn", "app.main:app", "--port", "8001"]) == 8001
    assert main.configured_port(["uvicorn", "app.main:app", "--port=8002"]) == 8002


def test_configured_port_prefers_environment_variable(monkeypatch):
    monkeypatch.setenv("ACQUIRE_PORT", "9000")

    assert main.configured_port(["uvicorn", "app.main:app", "--port", "8001"]) == 9000
