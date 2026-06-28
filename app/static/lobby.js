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

let lobby = window.INITIAL_LOBBY;
let playerId = window.sessionStorage.getItem("playerId");
let playerName = window.sessionStorage.getItem("playerName");
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
  if (!playerId || lobby.status !== "waiting") {
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
    if (payload.type === "lobby") {
      lobby = payload.lobby;
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
  }
}

function renderPlayer(player) {
  const item = document.createElement("li");
  const name = document.createElement("span");
  name.textContent = player.name;
  item.append(name);

  if (player.is_host) {
    const badge = document.createElement("span");
    badge.className = "host-badge";
    badge.textContent = "Host";
    item.append(badge);
  }

  return item;
}

function setMessage(text) {
  message.textContent = text;
}

function clearPlayer() {
  playerId = null;
  playerName = null;
  window.sessionStorage.removeItem("playerId");
  window.sessionStorage.removeItem("playerName");
  if (socket) {
    socket.close();
    socket = null;
  }
}
