# Acquire Pregame Lobby

A small FastAPI app for hosting one Acquire pregame lobby per server process.

## Run

Install dependencies:

```powershell
python -m pip install -e ".[dev]"
```

Start one lobby:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Start a second independent lobby on another port:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8001
```

Players on the same reachable LAN should browse to the host computer's LAN IP and port, such as `http://192.168.1.42:8000`.

## Test

```powershell
python -m pytest
```
