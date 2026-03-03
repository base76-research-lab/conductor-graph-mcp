# CognOS Graph MCP Server — Setup

Fristående MCP-server som exponerar hela CognOS-armadan som en
maskinläsbar graf. Conductor (Claude76) anropar ett verktyg och
får hela systembilden direkt.

## Installation

```bash
cd /home/bjorn/Cognos-enterprise
pip install -r mcp/graph_requirements.txt
```

## Registrering i Claude Code

Lägg till i `~/.claude/settings.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "cognos-graph": {
      "command": "python3",
      "args": ["/home/bjorn/Cognos-enterprise/mcp/graph_server.py"],
      "env": {
        "COGNOS_BASE_URL": "http://127.0.0.1:8788",
        "COGNOS_API_KEY": "test-key"
      }
    }
  }
}
```

## Verktyg

| Verktyg | Beskrivning |
|---------|-------------|
| `get_agent_graph` | Hela grafen — primärt verktyg |
| `get_node_status(node_id)` | Status för en specifik nod |
| `get_edges` | Bara kanterna (kommunikationsflödet) |
| `get_blocked_nodes` | Shortcut: vad är blockerat just nu? |

## Kända nod-ID:n

```
conductor
trustplane-gateway
token-compressor
session-memory
armada-bus
agent-critic
agent-curator
agent-ethics
agent-synth
agent-self
agent-srt
agent-indexer
```

## Exempel på conductor-frågor

```
# Systemöverblick
get_agent_graph()

# En specifik nod
get_node_status("trustplane-gateway")

# Vad är trasigt?
get_blocked_nodes()

# Kommunikationsflödet
get_edges()
```

## Verifiering

```bash
# 1. Starta gateway
uvicorn enterprise.app:app --port 8788

# 2. Testa graph_server direkt
python3 mcp/graph_server.py

# 3. Stoppa gateway → trustplane-gateway.status = "error"
#    get_blocked_nodes() ska returnera trustplane-gateway

# 4. Kör en /save → session-memory.metrics.entries ökar
#    get_node_status("session-memory") visar ny räkning
```

## Nodstatus — datakällor

| Nod | Källa |
|-----|-------|
| `trustplane-gateway` | HTTP GET `/healthz` + `/v1/providers/health` |
| `token-compressor` | `/tmp/b76_compress.log` |
| `session-memory` | `/tmp/b76_save.log` + SQLite `~/.local/share/b76/sessions/traces.sqlite3` |
| `armada-bus` | `/tmp/b76_armada_bus.json` + `/tmp/b76_armada_bus.log` |
| `agent-*` | `psutil` — är processen aktiv? |
| `conductor` | Alltid active (Claude76 själv) |
