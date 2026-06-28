from app.lobby import Lobby, LobbyError, LobbyStatus


def test_first_joined_player_becomes_host():
    lobby = Lobby()

    player = lobby.join("Eric")

    assert lobby.host_player_id == player.id


def test_join_two_to_four_players():
    lobby = Lobby()

    for name in ["A", "B", "C", "D"]:
        lobby.join(name)

    assert [player.name for player in lobby.players] == ["A", "B", "C", "D"]


def test_reject_fifth_player():
    lobby = Lobby()
    for name in ["A", "B", "C", "D"]:
        lobby.join(name)

    try:
        lobby.join("E")
    except LobbyError as error:
        assert "full" in str(error)
    else:
        raise AssertionError("Expected full lobby to reject a fifth player.")


def test_reject_duplicate_names_case_insensitively():
    lobby = Lobby()
    lobby.join("Eric")

    try:
        lobby.join("eric")
    except LobbyError as error:
        assert "already taken" in str(error)
    else:
        raise AssertionError("Expected duplicate player name to be rejected.")


def test_leave_removes_waiting_player():
    lobby = Lobby()
    player = lobby.join("Eric")

    lobby.leave(player.id)

    assert lobby.players == []
    assert lobby.host_player_id is None


def test_host_reassigned_to_earliest_remaining_player():
    lobby = Lobby()
    first = lobby.join("A")
    second = lobby.join("B")
    lobby.join("C")

    lobby.leave(first.id)

    assert lobby.host_player_id == second.id


def test_only_host_can_start():
    lobby = Lobby()
    lobby.join("A")
    second = lobby.join("B")

    try:
        lobby.start(second.id)
    except LobbyError as error:
        assert "Only the host" in str(error)
    else:
        raise AssertionError("Expected non-host start to fail.")


def test_cannot_start_with_fewer_than_two_players():
    lobby = Lobby()
    host = lobby.join("A")

    try:
        lobby.start(host.id)
    except LobbyError as error:
        assert "at least 2" in str(error)
    else:
        raise AssertionError("Expected one-player start to fail.")


def test_host_can_start_with_two_players():
    lobby = Lobby()
    host = lobby.join("A")
    lobby.join("B")

    lobby.start(host.id)

    assert lobby.status == LobbyStatus.STARTED
    assert lobby.started_at is not None


def test_cannot_join_after_game_starts():
    lobby = Lobby()
    host = lobby.join("A")
    lobby.join("B")
    lobby.start(host.id)

    try:
        lobby.join("C")
    except LobbyError as error:
        assert "already started" in str(error)
    else:
        raise AssertionError("Expected started lobby to reject joins.")
