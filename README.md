# Acquire

A small FastAPI app for playing Acquire in the browser with one game per server process.

## Run

Install dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Start one game server:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The server log prints the local and LAN links players can use to join.

Start a second independent game on another port:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Players on the same reachable LAN should browse to the host computer's LAN IP and port, such as `http://192.168.1.42:8000`.

## Test

```powershell
python -m pytest
```
