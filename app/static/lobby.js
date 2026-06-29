const joinForm = document.querySelector("#join-form");
const playerNameInput = document.querySelector("#player-name");
const joinView = document.querySelector("#join-view");
const playerView = document.querySelector("#player-view");
const startedView = document.querySelector("#started-view");
const currentPlayerName = document.querySelector("#current-player-name");
const startButton = document.querySelector("#start-button");
const leaveButton = document.querySelector("#leave-button");
const message = document.querySelector("#message");
const playersList = document.querySelector("#players");
const playerCount = document.querySelector("#player-count");
const statusPill = document.querySelector("#status-pill");
const board = document.querySelector("#board");
const gameActions = document.querySelector("#game-actions");
const chains = document.querySelector("#chains");

const rows = "ABCDEFGHI".split("");
const columns = Array.from({ length: 12 }, (_, index) => index + 1);
const chainClasses = {
  Sackson: "chain-sackson",
  Zeta: "chain-zeta",
  America: "chain-america",
  Fusion: "chain-fusion",
  Hydra: "chain-hydra",
  Quantum: "chain-quantum",
  Phoenix: "chain-phoenix",
};

let lobby = window.INITIAL_LOBBY;
let game = window.INITIAL_GAME;
let playerId = window.sessionStorage.getItem("playerId");
let playerName = window.sessionStorage.getItem("playerName");
let selectedTile = null;
let stockPurchases = {};
let stockPurchaseTurnKey = "";
let socket;

render();
connectSocket();

joinForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setMessage("");

  const form = new FormData(joinForm);
  const response = await fetch("/join", { method: "POST", body: form });
  const data = await response.json();

  if (!response.ok) {
    lobby = data.lobby;
    setMessage(data.error);
    render();
    return;
  }

  playerId = data.player_id;
  playerName = form.get("player_name").trim();
  window.sessionStorage.setItem("playerId", playerId);
  window.sessionStorage.setItem("playerName", playerName);
  lobby = data.lobby;
  game = data.game;
  render();
  connectSocket();
});

startButton.addEventListener("click", async () => {
  setMessage("");
  const form = new FormData();
  form.set("player_id", playerId);

  const response = await fetch("/start", { method: "POST", body: form });
  const data = await response.json();
  lobby = data.lobby;
  game = data.game;

  if (!response.ok) {
    setMessage(data.error);
  }

  render();
});

leaveButton.addEventListener("click", async () => {
  if (!playerId) {
    return;
  }

  const form = new FormData();
  form.set("player_id", playerId);
  await fetch("/leave", { method: "POST", body: form });
  clearPlayer();
  render();
});

window.addEventListener("beforeunload", () => {
  if (socket) {
    socket.close();
  }
});

function connectSocket() {
  if (!playerId) {
    return;
  }

  if (!lobby.players.some((player) => player.id === playerId)) {
    clearPlayer();
    return;
  }

  if (socket) {
    socket.close();
  }

  const protocol = window.location.protocol === "https:" ? "wss" : "ws";
  socket = new WebSocket(`${protocol}://${window.location.host}/ws?player_id=${encodeURIComponent(playerId)}`);

  socket.addEventListener("message", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.type === "state" || payload.type === "lobby") {
      lobby = payload.lobby;
      game = payload.game;
      if (playerId && !lobby.players.some((player) => player.id === playerId) && lobby.status === "waiting") {
        clearPlayer();
      }
      render();
    }
  });
}

function render() {
  const currentPlayer = playerId ? lobby.players.find((player) => player.id === playerId) : null;
  const isStarted = lobby.status === "started";
  const isHost = currentPlayer && currentPlayer.id === lobby.host_player_id;

  statusPill.textContent = isStarted ? "Started" : "Waiting";
  playerCount.textContent = `${lobby.players.length} / ${lobby.max_players}`;

  joinView.classList.toggle("hidden", Boolean(currentPlayer) || isStarted);
  playerView.classList.toggle("hidden", !currentPlayer || isStarted);
  startedView.classList.toggle("hidden", !isStarted);

  if (currentPlayer) {
    currentPlayerName.textContent = currentPlayer.name;
  }

  startButton.disabled = !isHost || !lobby.can_start;
  leaveButton.disabled = !currentPlayer || isStarted;

  playersList.replaceChildren(...lobby.players.map(renderPlayer));

  if (isStarted) {
    setMessage("");
    renderGame();
  }
}

function renderPlayer(player) {
  const item = document.createElement("li");
  const details = game?.players.find((gamePlayer) => gamePlayer.id === player.id);
  const identity = document.createElement("span");
  identity.className = "player-identity";
  const name = document.createElement("strong");
  name.textContent = player.name;
  identity.append(name);

  if (player.is_host) {
    const badge = document.createElement("span");
    badge.className = "host-badge";
    badge.textContent = "Host";
    identity.append(badge);
  }

  if (game?.active_player_id === player.id) {
    const badge = document.createElement("span");
    badge.className = "turn-badge";
    badge.textContent = "Turn";
    identity.append(badge);
  }

  item.append(identity);

  if (details) {
    const lastMove = document.createElement("span");
    lastMove.className = "player-last-move";
    lastMove.textContent = details.last_move;
    item.append(lastMove);

    const cash = document.createElement("span");
    cash.className = "player-cash";
    cash.textContent = `$${details.cash}`;
    item.append(cash);
  }

  return item;
}

function renderGame() {
  if (!game) {
    return;
  }

  syncStockPurchaseState();
  const viewer = game.players.find((player) => player.id === playerId);
  const isTurn = game.active_player_id === playerId;

  renderBoard();
  renderActions(viewer, isTurn);
  renderChains();
}

function renderBoard() {
  const viewer = game.players.find((player) => player.id === playerId);
  const cells = [];
  for (const row of rows) {
    for (const column of columns) {
      const tile = `${column}${row}`;
      const occupied = Object.prototype.hasOwnProperty.call(game.board, tile);
      const inHand = Boolean(viewer?.hand.includes(tile));
      const cell = document.createElement("button");
      const chain = game.board[tile];
      cell.type = "button";
      cell.className = `board-cell ${chain ? chainClasses[chain] : occupied ? "placed-tile" : inHand ? "available-tile" : ""}`;
      cell.textContent = chain ? chain[0] : occupied ? "•" : tile;
      cell.title = chain ? `${tile} ${chain}` : occupied ? `${tile} placed` : inHand ? `${tile} in your hand` : tile;
      cell.disabled = occupied || game.phase !== "place_tile" || game.active_player_id !== playerId || !inHand;
      if (selectedTile === tile) {
        cell.classList.add("selected");
      }
      if (!occupied) {
        cell.addEventListener("click", () => {
          selectedTile = tile;
          renderGame();
        });
      }
      cells.push(cell);
    }
  }
  board.replaceChildren(...cells);
}

function renderActions(viewer, isTurn) {
  gameActions.replaceChildren();
  if (!viewer) {
    return;
  }

  if (game.phase === "game_over") {
    const winners = game.players.filter((player) => game.winner_ids.includes(player.id));
    gameActions.append(textBlock(`Winner: ${winners.map((winner) => winner.name).join(", ")}`));
    return;
  }

  if (!isTurn) {
    gameActions.append(textBlock("Waiting for the active player."));
    return;
  }

  if (game.phase === "place_tile") {
    const button = actionButton("Place Tile", async () => {
      const tile = selectedTile || viewer.hand[0];
      await postAction("/game/place-tile", { tile });
      selectedTile = null;
    });
    button.disabled = !selectedTile;
    gameActions.append(button);
  }

  if (game.phase === "found_chain") {
    gameActions.append(textBlock("Choose a chain from the table."));
  }

  if (game.phase === "choose_survivor") {
    const select = selectInput(game.pending_merge.survivor_options);
    gameActions.append(labelWrap("Surviving chain", select));
    gameActions.append(actionButton("Choose Survivor", () => postAction("/game/choose-survivor", { chain: select.value })));
  }

  if (game.phase === "resolve_merge") {
    const decisions = {};
    for (const chain of game.pending_merge.defunct_chains) {
      const select = selectInput(["hold", "sell", "trade"]);
      decisions[chain] = select;
      gameActions.append(labelWrap(`${chain} stock`, select));
    }
    gameActions.append(actionButton("Resolve Merger", () => {
      const payload = {};
      for (const [chain, select] of Object.entries(decisions)) {
        payload[chain] = select.value;
      }
      return postAction("/game/resolve-merge", { decisions: JSON.stringify(payload) });
    }));
  }

  if (game.phase === "buy_stock") {
    gameActions.append(actionButton(stockPurchaseTotal() ? "Buy Selected Stock" : "Buy No Stock", () => {
      const purchases = Object.entries(stockPurchases)
        .flatMap(([chain, count]) => Array.from({ length: count }, () => chain))
        .join(",");
      stockPurchases = {};
      return postAction("/game/buy-stock", { purchases });
    }));
  }

}

function renderChains() {
  const viewer = game.players.find((player) => player.id === playerId);
  const canBuyStock = game.phase === "buy_stock" && game.active_player_id === playerId;
  const canFoundChain = game.phase === "found_chain" && game.active_player_id === playerId;
  const items = game.chains.map((chain) => {
    const item = document.createElement("tr");
    const owned = viewer?.stocks[chain.name] || 0;
    const swatchClass = chain.active ? chainClasses[chain.name] : "chain-inactive";
    const pending = stockPurchases[chain.name] || 0;

    const nameCell = document.createElement("th");
    nameCell.scope = "row";
    const chainName = document.createElement("span");
    chainName.className = "chain-name";
    const swatch = document.createElement("span");
    swatch.className = `chain-swatch ${swatchClass}`;
    chainName.append(swatch, chain.name);
    nameCell.append(chainName);

    const priceCell = tableCell(`$${chain.stock_price}`);
    const leftCell = tableCell(chain.stock_bank - pending);
    const ownedCell = document.createElement("td");

    if (canFoundChain && game.available_chains.includes(chain.name)) {
      ownedCell.append(actionMiniButton("Found", `Found ${chain.name}`, () => postAction("/game/found-chain", { chain: chain.name })));
    } else if (canBuyStock && chain.active) {
      ownedCell.append(stockControl(chain, owned, pending, viewer));
    } else {
      ownedCell.textContent = owned;
    }

    item.append(nameCell, priceCell, leftCell, ownedCell);
    return item;
  });
  chains.replaceChildren(...items);
}

function stockControl(chain, owned, pending, viewer) {
  const control = document.createElement("span");
  control.className = "stock-control";

  const minus = iconButton("-", `Remove ${chain.name} stock`, () => {
    stockPurchases[chain.name] = Math.max(0, pending - 1);
    renderGame();
  });
  minus.disabled = pending === 0;

  const count = document.createElement("span");
  count.className = "stock-count";
  count.textContent = pending ? `${owned}+${pending}` : owned;

  const plus = iconButton("+", `Add ${chain.name} stock`, () => {
    stockPurchases[chain.name] = pending + 1;
    renderGame();
  });
  plus.disabled = !canAddStock(chain, viewer);

  control.append(minus, count, plus);
  return control;
}

function canAddStock(chain, viewer) {
  const pending = stockPurchases[chain.name] || 0;
  const pendingCost = stockPurchaseCost();
  return (
    chain.active &&
    chain.stock_bank - pending > 0 &&
    stockPurchaseTotal() < 3 &&
    pendingCost + chain.stock_price <= viewer.cash
  );
}

function stockPurchaseTotal() {
  return Object.values(stockPurchases).reduce((total, count) => total + count, 0);
}

function stockPurchaseCost() {
  return Object.entries(stockPurchases).reduce((total, [chainName, count]) => {
    const chain = game.chains.find((candidate) => candidate.name === chainName);
    return total + (chain ? chain.stock_price * count : 0);
  }, 0);
}

function syncStockPurchaseState() {
  const turnKey = `${game.phase}:${game.active_player_id}`;
  if (turnKey !== stockPurchaseTurnKey || game.phase !== "buy_stock" || game.active_player_id !== playerId) {
    stockPurchases = {};
    stockPurchaseTurnKey = turnKey;
  }
}

function tableCell(text) {
  const cell = document.createElement("td");
  cell.textContent = text;
  return cell;
}

async function postAction(path, fields) {
  setMessage("");
  const form = new FormData();
  form.set("player_id", playerId);
  for (const [key, value] of Object.entries(fields)) {
    form.set(key, value);
  }
  const response = await fetch(path, { method: "POST", body: form });
  const data = await response.json();
  lobby = data.lobby;
  game = data.game;
  if (!response.ok) {
    setMessage(data.error);
  }
  render();
}

function selectInput(options) {
  const select = document.createElement("select");
  for (const option of options) {
    const element = document.createElement("option");
    element.value = option;
    element.textContent = option || "None";
    select.append(element);
  }
  return select;
}

function labelWrap(text, control) {
  const label = document.createElement("label");
  label.className = "action-field";
  const span = document.createElement("span");
  span.textContent = text;
  label.append(span, control);
  return label;
}

function actionButton(text, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = text;
  button.addEventListener("click", handler);
  return button;
}

function iconButton(text, label, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "icon-button";
  button.textContent = text;
  button.setAttribute("aria-label", label);
  button.title = label;
  button.addEventListener("click", handler);
  return button;
}

function actionMiniButton(text, label, handler) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "mini-button";
  button.textContent = text;
  button.setAttribute("aria-label", label);
  button.title = label;
  button.addEventListener("click", handler);
  return button;
}

function textBlock(text) {
  const paragraph = document.createElement("p");
  paragraph.textContent = text;
  return paragraph;
}

function setMessage(text) {
  message.textContent = text;
}

function clearPlayer() {
  playerId = null;
  playerName = null;
  game = null;
  window.sessionStorage.removeItem("playerId");
  window.sessionStorage.removeItem("playerName");
  if (socket) {
    socket.close();
    socket = null;
  }
}
