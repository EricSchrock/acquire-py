from fastapi.testclient import TestClient

from app import main
from app.lobby import Lobby


def make_client() -> TestClient:
    main.lobby = Lobby()
    main.connections = {}
    return TestClient(main.app)


def test_join_endpoint_returns_player_id_and_snapshot():
    client = make_client()

    response = client.post("/join", data={"player_name": "Eric"})

    assert response.status_code == 200
    body = response.json()
    assert body["player_id"]
    assert body["lobby"]["players"][0]["name"] == "Eric"


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


def test_waiting_websocket_disconnect_removes_player():
    client = make_client()
    player_id = client.post("/join", data={"player_name": "Eric"}).json()["player_id"]

    with client.websocket_connect(f"/ws?player_id={player_id}") as websocket:
        assert websocket.receive_json()["lobby"]["players"][0]["name"] == "Eric"

    assert main.lobby.players == []
