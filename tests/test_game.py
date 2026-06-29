from app.game import Game, GamePhase, HotelChain


def test_new_game_deals_six_tiles_to_each_player():
    game = Game.new([("a", "A"), ("b", "B")], seed=1)

    assert [len(player.hand) for player in game.players] == [6, 6]
    assert game.phase == GamePhase.PLACE_TILE
    assert len(game.tile_deck) == 96


def test_adjacent_tiles_can_found_chain_and_grant_founder_stock():
    game = Game.new([("a", "A"), ("b", "B")], seed=1)
    game.players[0].hand = ["1A"]
    game.place_tile("a", "1A")
    game.buy_stock("a", [])
    game.players[1].hand = ["2A"]

    game.place_tile("b", "2A")
    game.found_chain("b", "Sackson")

    assert game.phase == GamePhase.BUY_STOCK
    assert game.board["1A"] == HotelChain.SACKSON
    assert game.board["2A"] == HotelChain.SACKSON
    assert game.players[1].stock_count(HotelChain.SACKSON) == 1
    assert game.stock_bank[HotelChain.SACKSON] == 24


def test_buy_stock_charges_cash_and_advances_to_next_player():
    game = Game.new([("a", "A"), ("b", "B")], seed=1)
    game.board = {"1A": HotelChain.SACKSON, "2A": HotelChain.SACKSON}
    game.phase = GamePhase.BUY_STOCK

    game.buy_stock("a", ["Sackson", "Sackson"])

    assert game.players[0].cash == 5600
    assert game.players[0].stock_count(HotelChain.SACKSON) == 2
    assert game.phase == GamePhase.PLACE_TILE
    assert game.active_player.id == "b"


def test_buy_stock_last_move_groups_chains_in_table_order():
    game = Game.new([("a", "A"), ("b", "B")], seed=1)
    game.board = {
        "1A": HotelChain.SACKSON,
        "2A": HotelChain.SACKSON,
        "4A": HotelChain.ZETA,
        "5A": HotelChain.ZETA,
    }
    game.phase = GamePhase.BUY_STOCK

    game.buy_stock("a", ["Zeta", "Sackson", "Zeta"])

    assert game.snapshot("a")["players"][0]["last_move"] == "Bought Sackson (1x), Zeta (2x)"


def test_snapshot_only_reveals_viewers_stock_portfolio():
    game = Game.new([("a", "A"), ("b", "B")], seed=1)
    game.players[0].stocks[HotelChain.SACKSON] = 2
    game.players[1].stocks[HotelChain.ZETA] = 1

    snapshot = game.snapshot("a")

    assert snapshot["players"][0]["stocks"]["Sackson"] == 2
    assert snapshot["players"][1]["stocks"] == {}


def test_snapshot_includes_each_players_last_move():
    game = Game.new([("a", "A"), ("b", "B")], seed=1)
    game.players[0].hand = ["1A"]

    game.place_tile("a", "1A")

    assert game.snapshot("a")["players"][0]["last_move"] == "Placed 1A"
    assert game.snapshot("a")["players"][1]["last_move"] == ""


def test_merger_pays_bonus_and_converts_defunct_chain():
    game = Game.new([("a", "A"), ("b", "B")], seed=1)
    game.players[0].hand = ["3A"]
    game.board = {
        "1A": HotelChain.SACKSON,
        "2A": HotelChain.SACKSON,
        "4A": HotelChain.ZETA,
        "5A": HotelChain.ZETA,
        "6A": HotelChain.ZETA,
    }
    game.players[0].stocks[HotelChain.SACKSON] = 2
    game.players[1].stocks[HotelChain.SACKSON] = 1

    game.place_tile("a", "3A")
    game.resolve_merge("a", {"Sackson": "sell"})

    assert game.phase == GamePhase.BUY_STOCK
    assert game.board["1A"] == HotelChain.ZETA
    assert game.board["3A"] == HotelChain.ZETA
    assert game.players[0].cash > 6000
    assert game.players[0].stock_count(HotelChain.SACKSON) == 0
