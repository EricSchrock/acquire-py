from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from random import Random


BOARD_COLUMNS = range(1, 13)
BOARD_ROWS = tuple("ABCDEFGHI")
HAND_SIZE = 6
STARTING_CASH = 6000
STOCKS_PER_CHAIN = 25
MAX_STOCK_PURCHASE = 3


class GameError(ValueError):
    pass


class GamePhase(StrEnum):
    PLACE_TILE = "place_tile"
    FOUND_CHAIN = "found_chain"
    CHOOSE_SURVIVOR = "choose_survivor"
    RESOLVE_MERGE = "resolve_merge"
    BUY_STOCK = "buy_stock"
    GAME_OVER = "game_over"


class HotelChain(StrEnum):
    SACKSON = "Sackson"
    ZETA = "Zeta"
    AMERICA = "America"
    FUSION = "Fusion"
    HYDRA = "Hydra"
    QUANTUM = "Quantum"
    PHOENIX = "Phoenix"


EXPENSIVE_CHAINS = {HotelChain.AMERICA, HotelChain.PHOENIX}
MID_CHAINS = {HotelChain.FUSION, HotelChain.HYDRA, HotelChain.QUANTUM}


@dataclass
class PlayerState:
    id: str
    name: str
    cash: int = STARTING_CASH
    hand: list[str] = field(default_factory=list)
    stocks: dict[HotelChain, int] = field(default_factory=dict)

    def stock_count(self, chain: HotelChain) -> int:
        return self.stocks.get(chain, 0)


@dataclass
class MergeState:
    tile: str
    survivor_options: list[HotelChain]
    survivor: HotelChain | None
    defunct_chains: list[HotelChain]


@dataclass
class Game:
    players: list[PlayerState]
    tile_deck: list[str]
    stock_bank: dict[HotelChain, int]
    board: dict[str, HotelChain | None] = field(default_factory=dict)
    active_player_index: int = 0
    phase: GamePhase = GamePhase.PLACE_TILE
    pending_tile: str | None = None
    pending_merge: MergeState | None = None
    stock_purchases_this_turn: int = 0
    log: list[str] = field(default_factory=list)
    last_moves: dict[str, str] = field(default_factory=dict)
    winner_ids: list[str] = field(default_factory=list)

    @classmethod
    def new(cls, players: list[tuple[str, str]], seed: int | None = None) -> Game:
        if not 2 <= len(players) <= 4:
            raise GameError("Acquire needs 2 to 4 players.")

        deck = all_tiles()
        Random(seed).shuffle(deck)
        game = cls(
            players=[PlayerState(id=player_id, name=name) for player_id, name in players],
            tile_deck=deck,
            stock_bank={chain: STOCKS_PER_CHAIN for chain in HotelChain},
        )
        for player in game.players:
            game.draw_tiles(player)
        game.log.append("Game started.")
        return game

    @property
    def active_player(self) -> PlayerState:
        return self.players[self.active_player_index]

    def place_tile(self, player_id: str, tile: str) -> None:
        self.require_turn(player_id)
        self.require_phase(GamePhase.PLACE_TILE)
        tile = normalize_tile(tile)
        if tile not in self.active_player.hand:
            raise GameError("That tile is not in your hand.")
        if tile in self.board:
            raise GameError("That tile is already on the board.")

        self.active_player.hand.remove(tile)
        self.board[tile] = None
        self.pending_tile = tile
        neighboring_chains = sorted(
            {chain for chain in self.neighboring_chains(tile)},
            key=lambda chain: chain.value,
        )

        if len(neighboring_chains) > 1:
            self.begin_merge(tile, neighboring_chains)
            return

        if len(neighboring_chains) == 1:
            chain = neighboring_chains[0]
            self.assign_connected_unchained(tile, chain)
            self.phase = GamePhase.BUY_STOCK
            self.record_move(self.active_player, f"Expanded {chain.value}")
            return

        if len(self.connected_tiles(tile)) > 1:
            if self.available_chains():
                self.phase = GamePhase.FOUND_CHAIN
                self.record_move(self.active_player, f"Placed {tile}")
            else:
                self.phase = GamePhase.BUY_STOCK
                self.record_move(self.active_player, f"Placed {tile}")
            return

        self.phase = GamePhase.BUY_STOCK
        self.record_move(self.active_player, f"Placed {tile}")

    def found_chain(self, player_id: str, chain_name: str) -> None:
        self.require_turn(player_id)
        self.require_phase(GamePhase.FOUND_CHAIN)
        chain = parse_chain(chain_name)
        if chain not in self.available_chains():
            raise GameError("That chain is not available.")
        if self.pending_tile is None:
            raise GameError("No tile is waiting to found a chain.")

        founded_tiles = self.connected_tiles(self.pending_tile)
        for tile in founded_tiles:
            self.board[tile] = chain
        self.grant_founder_stock(chain)
        self.phase = GamePhase.BUY_STOCK
        self.record_move(self.active_player, f"Founded {chain.value}")

    def choose_survivor(self, player_id: str, chain_name: str) -> None:
        self.require_turn(player_id)
        self.require_phase(GamePhase.CHOOSE_SURVIVOR)
        if self.pending_merge is None:
            raise GameError("No merger is waiting.")

        survivor = parse_chain(chain_name)
        if survivor not in self.pending_merge.survivor_options:
            raise GameError("That chain cannot survive this merger.")
        self.pending_merge.survivor = survivor
        self.pending_merge.defunct_chains = [
            chain for chain in self.pending_merge.defunct_chains if chain != survivor
        ]
        self.phase = GamePhase.RESOLVE_MERGE
        self.record_move(self.active_player, f"Chose {survivor.value} to survive")

    def resolve_merge(self, player_id: str, decisions: dict[str, str] | None = None) -> None:
        self.require_turn(player_id)
        self.require_phase(GamePhase.RESOLVE_MERGE)
        if self.pending_merge is None or self.pending_merge.survivor is None:
            raise GameError("No merger is ready to resolve.")

        decisions = decisions or {}
        survivor = self.pending_merge.survivor
        for defunct in self.pending_merge.defunct_chains:
            self.pay_merge_bonuses(defunct)
            self.apply_stock_decisions(defunct, survivor, decisions.get(defunct.value, "hold"))
            self.convert_chain(defunct, survivor)
            self.log.append(f"{defunct.value} merged into {survivor.value}.")

        self.pending_merge = None
        self.phase = GamePhase.BUY_STOCK
        self.record_move(self.active_player, f"Resolved merger into {survivor.value}")

    def buy_stock(self, player_id: str, purchases: list[str]) -> None:
        self.require_turn(player_id)
        self.require_phase(GamePhase.BUY_STOCK)
        if len(purchases) > MAX_STOCK_PURCHASE:
            raise GameError("You can buy at most 3 stocks per turn.")

        chains = [parse_chain(name) for name in purchases]
        if any(chain not in self.active_chains() for chain in chains):
            raise GameError("You can only buy stock in active chains.")

        total_cost = sum(self.stock_price(chain) for chain in chains)
        if total_cost > self.active_player.cash:
            raise GameError("You do not have enough cash.")
        for chain in chains:
            if self.stock_bank[chain] <= 0:
                raise GameError(f"{chain.value} has no stock left.")

        for chain in chains:
            self.stock_bank[chain] -= 1
            self.active_player.stocks[chain] = self.active_player.stock_count(chain) + 1
        self.active_player.cash -= total_cost
        self.stock_purchases_this_turn = len(chains)
        if chains:
            self.record_move(self.active_player, f"Bought {format_stock_purchase(chains)}")
        else:
            self.record_move(self.active_player, "Bought no stock")
        self.advance_turn()

    def advance_turn(self) -> None:
        self.draw_tiles(self.active_player)
        if self.can_end_game():
            self.end_game()
            return

        self.active_player_index = (self.active_player_index + 1) % len(self.players)
        self.pending_tile = None
        self.stock_purchases_this_turn = 0
        self.phase = GamePhase.PLACE_TILE
        self.log.append(f"{self.active_player.name}'s turn.")

    def end_game(self) -> None:
        for chain in list(self.active_chains()):
            self.pay_merge_bonuses(chain)
        totals = {player.id: self.net_worth(player) for player in self.players}
        high_score = max(totals.values())
        self.winner_ids = [player_id for player_id, total in totals.items() if total == high_score]
        self.phase = GamePhase.GAME_OVER
        self.log.append("Game over.")

    def require_turn(self, player_id: str) -> None:
        if self.phase == GamePhase.GAME_OVER:
            raise GameError("The game is over.")
        if player_id != self.active_player.id:
            raise GameError("It is not your turn.")

    def require_phase(self, phase: GamePhase) -> None:
        if self.phase != phase:
            raise GameError(f"Expected {phase.value.replace('_', ' ')} phase.")

    def draw_tiles(self, player: PlayerState) -> None:
        while len(player.hand) < HAND_SIZE and self.tile_deck:
            player.hand.append(self.tile_deck.pop())
        player.hand.sort(key=tile_sort_key)

    def begin_merge(self, tile: str, chains: list[HotelChain]) -> None:
        sizes = {chain: self.chain_size(chain) for chain in chains}
        largest = max(sizes.values())
        survivor_options = [chain for chain in chains if sizes[chain] == largest]
        survivor = survivor_options[0] if len(survivor_options) == 1 else None
        defunct = [chain for chain in chains if chain != survivor] if survivor else chains.copy()
        self.pending_merge = MergeState(tile, survivor_options, survivor, defunct)
        self.phase = GamePhase.RESOLVE_MERGE if survivor else GamePhase.CHOOSE_SURVIVOR
        self.record_move(self.active_player, "Triggered a merger")

    def record_move(self, player: PlayerState, move: str) -> None:
        self.last_moves[player.id] = move
        self.log.append(f"{player.name} {move[:1].lower()}{move[1:]}.")

    def neighboring_chains(self, tile: str) -> list[HotelChain]:
        chains = []
        for neighbor in neighbors(tile):
            chain = self.board.get(neighbor)
            if chain is not None:
                chains.append(chain)
        return chains

    def connected_tiles(self, start: str) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            tile = stack.pop()
            if tile in seen or tile not in self.board:
                continue
            seen.add(tile)
            stack.extend(neighbor for neighbor in neighbors(tile) if neighbor in self.board)
        return seen

    def assign_connected_unchained(self, start: str, chain: HotelChain) -> None:
        for tile in self.connected_tiles(start):
            if self.board[tile] is None:
                self.board[tile] = chain

    def convert_chain(self, defunct: HotelChain, survivor: HotelChain) -> None:
        for tile, chain in list(self.board.items()):
            if chain in {defunct, None} and tile in self.connected_tiles(self.pending_merge.tile):
                self.board[tile] = survivor

    def grant_founder_stock(self, chain: HotelChain) -> None:
        grant = min(1, self.stock_bank[chain])
        if grant:
            self.stock_bank[chain] -= grant
            self.active_player.stocks[chain] = self.active_player.stock_count(chain) + grant

    def pay_merge_bonuses(self, chain: HotelChain) -> None:
        holders = [player for player in self.players if player.stock_count(chain) > 0]
        if not holders:
            return

        majority = max(player.stock_count(chain) for player in holders)
        majority_holders = [player for player in holders if player.stock_count(chain) == majority]
        majority_bonus = self.majority_bonus(chain)
        minority_bonus = self.minority_bonus(chain)

        if len(majority_holders) > 1:
            payout = split_bonus(majority_bonus + minority_bonus, len(majority_holders))
            for player in majority_holders:
                player.cash += payout
            return

        majority_holders[0].cash += majority_bonus
        minority_candidates = [player for player in holders if player.stock_count(chain) < majority]
        if not minority_candidates:
            majority_holders[0].cash += minority_bonus
            return

        minority = max(player.stock_count(chain) for player in minority_candidates)
        minority_holders = [player for player in minority_candidates if player.stock_count(chain) == minority]
        payout = split_bonus(minority_bonus, len(minority_holders))
        for player in minority_holders:
            player.cash += payout

    def apply_stock_decisions(self, defunct: HotelChain, survivor: HotelChain, decision: str) -> None:
        decision = decision.lower()
        for player in self.players:
            count = player.stock_count(defunct)
            if count == 0:
                continue
            if decision == "sell":
                player.cash += count * self.stock_price(defunct)
                self.stock_bank[defunct] += count
                player.stocks[defunct] = 0
            elif decision == "trade":
                tradeable = min(count // 2, self.stock_bank[survivor])
                player.stocks[survivor] = player.stock_count(survivor) + tradeable
                player.stocks[defunct] = count - tradeable * 2
                self.stock_bank[survivor] -= tradeable
                self.stock_bank[defunct] += tradeable * 2
            elif decision == "hold":
                continue
            else:
                raise GameError("Merge decisions must be sell, trade, or hold.")

    def active_chains(self) -> list[HotelChain]:
        return sorted({chain for chain in self.board.values() if chain is not None}, key=lambda chain: chain.value)

    def available_chains(self) -> list[HotelChain]:
        active = set(self.active_chains())
        return [chain for chain in HotelChain if chain not in active]

    def chain_size(self, chain: HotelChain) -> int:
        return sum(1 for value in self.board.values() if value == chain)

    def stock_price(self, chain: HotelChain) -> int:
        size = max(2, self.chain_size(chain))
        base = 200 if chain in EXPENSIVE_CHAINS else 100 if chain in MID_CHAINS else 0
        if size <= 2:
            return 200 + base
        if size <= 5:
            return 300 + base
        if size <= 10:
            return 400 + base
        if size <= 20:
            return 500 + base
        if size <= 30:
            return 600 + base
        if size <= 40:
            return 700 + base
        return 800 + base

    def majority_bonus(self, chain: HotelChain) -> int:
        return self.stock_price(chain) * 10

    def minority_bonus(self, chain: HotelChain) -> int:
        return self.stock_price(chain) * 5

    def can_end_game(self) -> bool:
        active = self.active_chains()
        return any(self.chain_size(chain) >= 41 for chain in active) or (
            bool(active) and all(self.chain_size(chain) >= 11 for chain in active)
        )

    def net_worth(self, player: PlayerState) -> int:
        return player.cash + sum(
            count * self.stock_price(chain)
            for chain, count in player.stocks.items()
            if chain in self.active_chains()
        )

    def snapshot(self, viewer_id: str | None = None) -> dict:
        return {
            "phase": self.phase.value,
            "active_player_id": self.active_player.id if self.phase != GamePhase.GAME_OVER else None,
            "active_player_name": self.active_player.name if self.phase != GamePhase.GAME_OVER else None,
            "players": [self.player_snapshot(player, viewer_id) for player in self.players],
            "board": {tile: chain.value if chain else None for tile, chain in sorted(self.board.items(), key=lambda item: tile_sort_key(item[0]))},
            "chains": [
                {
                    "name": chain.value,
                    "active": chain in self.active_chains(),
                    "size": self.chain_size(chain),
                    "stock_price": self.stock_price(chain),
                    "stock_bank": self.stock_bank[chain],
                }
                for chain in HotelChain
            ],
            "available_chains": [chain.value for chain in self.available_chains()],
            "pending_tile": self.pending_tile,
            "pending_merge": self.merge_snapshot(),
            "winner_ids": self.winner_ids,
        }

    def player_snapshot(self, player: PlayerState, viewer_id: str | None) -> dict:
        is_viewer = player.id == viewer_id
        return {
            "id": player.id,
            "name": player.name,
            "cash": player.cash,
            "hand": player.hand if is_viewer else [],
            "tile_count": len(player.hand),
            "stocks": {chain.value: player.stock_count(chain) for chain in HotelChain} if is_viewer else {},
            "net_worth": self.net_worth(player),
            "last_move": self.last_moves.get(player.id, ""),
        }

    def merge_snapshot(self) -> dict | None:
        if self.pending_merge is None:
            return None
        return {
            "tile": self.pending_merge.tile,
            "survivor_options": [chain.value for chain in self.pending_merge.survivor_options],
            "survivor": self.pending_merge.survivor.value if self.pending_merge.survivor else None,
            "defunct_chains": [chain.value for chain in self.pending_merge.defunct_chains],
        }


def all_tiles() -> list[str]:
    return [f"{column}{row}" for row in BOARD_ROWS for column in BOARD_COLUMNS]


def normalize_tile(tile: str) -> str:
    clean = tile.strip().upper()
    if len(clean) < 2:
        raise GameError("Unknown tile.")
    column_text = clean[:-1]
    row = clean[-1]
    if not column_text.isdigit():
        raise GameError("Unknown tile.")
    column = int(column_text)
    normalized = f"{column}{row}"
    if column not in BOARD_COLUMNS or row not in BOARD_ROWS:
        raise GameError("Unknown tile.")
    return normalized


def parse_chain(name: str) -> HotelChain:
    for chain in HotelChain:
        if chain.value.casefold() == name.casefold():
            return chain
    raise GameError("Unknown chain.")


def format_stock_purchase(chains: list[HotelChain]) -> str:
    return ", ".join(
        f"{chain.value} ({chains.count(chain)}x)"
        for chain in HotelChain
        if chain in chains
    )


def tile_sort_key(tile: str) -> tuple[str, int]:
    return tile[-1], int(tile[:-1])


def neighbors(tile: str) -> list[str]:
    column = int(tile[:-1])
    row = tile[-1]
    row_index = BOARD_ROWS.index(row)
    candidates = [
        (column - 1, row_index),
        (column + 1, row_index),
        (column, row_index - 1),
        (column, row_index + 1),
    ]
    return [
        f"{candidate_column}{BOARD_ROWS[candidate_row_index]}"
        for candidate_column, candidate_row_index in candidates
        if candidate_column in BOARD_COLUMNS and 0 <= candidate_row_index < len(BOARD_ROWS)
    ]


def split_bonus(amount: int, player_count: int) -> int:
    return (amount // player_count // 100) * 100
