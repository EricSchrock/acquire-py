from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from uuid import uuid4


MAX_PLAYERS = 4
MIN_PLAYERS = 2


class LobbyError(ValueError):
    pass


class LobbyStatus(StrEnum):
    WAITING = "waiting"
    STARTED = "started"


@dataclass(frozen=True)
class Player:
    id: str
    name: str
    joined_at: datetime


@dataclass
class Lobby:
    status: LobbyStatus = LobbyStatus.WAITING
    host_player_id: str | None = None
    players: list[Player] = field(default_factory=list)
    started_at: datetime | None = None

    def join(self, name: str) -> Player:
        clean_name = name.strip()
        if not clean_name:
            raise LobbyError("Enter a player name.")
        if self.status != LobbyStatus.WAITING:
            raise LobbyError("This game has already started.")
        if len(self.players) >= MAX_PLAYERS:
            raise LobbyError("This lobby is full.")
        if any(player.name.casefold() == clean_name.casefold() for player in self.players):
            raise LobbyError("That player name is already taken.")

        player = Player(id=uuid4().hex, name=clean_name, joined_at=_now())
        self.players.append(player)
        if self.host_player_id is None:
            self.host_player_id = player.id
        return player

    def leave(self, player_id: str) -> None:
        if self.status != LobbyStatus.WAITING:
            return

        original_count = len(self.players)
        self.players = [player for player in self.players if player.id != player_id]
        if len(self.players) == original_count:
            return

        if self.host_player_id == player_id:
            self.host_player_id = self.players[0].id if self.players else None

    def start(self, player_id: str) -> None:
        if self.status != LobbyStatus.WAITING:
            raise LobbyError("This game has already started.")
        if player_id != self.host_player_id:
            raise LobbyError("Only the host can start the game.")
        if len(self.players) < MIN_PLAYERS:
            raise LobbyError("Acquire needs at least 2 players.")
        if len(self.players) > MAX_PLAYERS:
            raise LobbyError("Acquire supports at most 4 players.")

        self.status = LobbyStatus.STARTED
        self.started_at = _now()

    def snapshot(self) -> dict:
        return {
            "status": self.status.value,
            "host_player_id": self.host_player_id,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "players": [
                {
                    "id": player.id,
                    "name": player.name,
                    "is_host": player.id == self.host_player_id,
                    "joined_at": player.joined_at.isoformat(),
                }
                for player in self.players
            ],
            "can_start": self.status == LobbyStatus.WAITING
            and MIN_PLAYERS <= len(self.players) <= MAX_PLAYERS,
            "min_players": MIN_PLAYERS,
            "max_players": MAX_PLAYERS,
        }


def _now() -> datetime:
    return datetime.now(timezone.utc)
