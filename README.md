# CognOS Graph MCP Server

![Conductor-Graph-MCP](logo.png)

Fristående MCP-server som exponerar hela CognOS-armadan som en
maskinläsbar JSON-graf. Conductor (Claude76) anropar ett verktyg och
får hela systembilden direkt.

FNC-arkitektur: **Field** (agenter) → **Node** (bearbetning) → **Cockpit** (oversight)

---

## Installation

```bash
git clone https://github.com/base76-research-lab/conductor-graph-mcp
cd conductor-graph-mcp

# Använd en virtualenv (rekommenderat)
pip install -r requirements.txt
```

## Registrering i Claude Code

Lägg till i `~/.claude/settings.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "cognos-graph": {
      "command": "python3",
      "args": ["/path/to/conductor-graph-mcp/graph_server.py"],
      "env": {
        "COGNOS_BASE_URL": "http://127.0.0.1:8788",
        "COGNOS_API_KEY": "your-key"
      }
    }
  }
}
```

Starta om Claude Code — servern aktiveras automatiskt.

> **Obs:** Kräver MCP SDK ≥ 1.0 (`mcp` på PyPI).

---

## Verktyg

| Verktyg | Beskrivning |
|---------|-------------|
| `get_agent_graph` | Hela grafen — noder + kanter + summary |
| `get_node_status(node_id)` | Status för en specifik nod |
| `get_edges` | Bara kanterna (kommunikationsflödet) |
| `get_blocked_nodes` | Shortcut: vad är blockerat just nu? |

---

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

---

## Exempel

```
get_agent_graph()                        # Systemöverblick
get_node_status("trustplane-gateway")    # En specifik nod
get_blocked_nodes()                      # Vad är trasigt?
get_edges()                              # Kommunikationsflödet
```

---

## Nodstatus — datakällor

| Nod | Källa |
|-----|-------|
| `trustplane-gateway` | HTTP GET `/healthz` + `/v1/providers/health` |
| `token-compressor` | `/tmp/b76_compress.log` |
| `session-memory` | `/tmp/b76_save.log` + SQLite `traces.sqlite3` |
| `armada-bus` | `/tmp/b76_armada_bus.json` + `/tmp/b76_armada_bus.log` |
| `agent-*` | `psutil` — är processen aktiv? |
| `conductor` | Alltid `active` (Claude76 själv) |

---

## Verifiering

```bash
# Testa att servern startar
python3 graph_server.py

# Stoppa gateway → trustplane-gateway.status = "error"
# get_blocked_nodes() ska returnera trustplane-gateway

# Kör en /save → session-memory.metrics.entries ökar
# get_node_status("session-memory") visar ny räkning
```
