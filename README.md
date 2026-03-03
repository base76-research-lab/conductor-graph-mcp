# Conductor Graph MCP Server

![Conductor-Graph-MCP](logo.png)

An MCP server that exposes a CognOS agent system as a machine-readable JSON graph. The conductor (Claude) calls a single tool and gets an immediate full system snapshot.

Built on the **FNC architecture**: **Field** (agents) → **Node** (processing) → **Cockpit** (oversight)

---

## Installation

```bash
# From PyPI (recommended)
pip install conductor-graph-mcp

# Or from source
git clone https://github.com/base76-research-lab/conductor-graph-mcp
cd conductor-graph-mcp
pip install -e .
```

## Usage with Claude Code

Add to `~/.claude/settings.json` under `mcpServers`:

```json
{
  "mcpServers": {
    "cognos-graph": {
      "command": "python3",
      "args": ["-m", "conductor_graph_mcp"],
      "env": {
        "COGNOS_BASE_URL": "http://127.0.0.1:8788",
        "COGNOS_API_KEY": "your-key"
      }
    }
  }
}
```

Or with `uvx`:

```json
{
  "mcpServers": {
    "cognos-graph": {
      "command": "uvx",
      "args": ["conductor-graph-mcp"],
      "env": {
        "COGNOS_BASE_URL": "http://127.0.0.1:8788",
        "COGNOS_API_KEY": "your-key"
      }
    }
  }
}
```

Restart Claude Code — the server activates automatically.

> **Note:** Requires MCP SDK ≥ 1.0 (`mcp` on PyPI).

---

## Tools

| Tool | Description |
|------|-------------|
| `get_agent_graph` | Full graph — nodes + edges + summary |
| `get_node_status(node_id)` | Live status for a specific node |
| `get_edges` | Only edges (communication flow) |
| `get_blocked_nodes` | Shortcut: what is broken right now? |

---

## Known Node IDs

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

## Examples

```
get_agent_graph()                        # Full system overview
get_node_status("trustplane-gateway")    # One specific node
get_blocked_nodes()                      # What is broken?
get_edges()                              # Communication flow
```

---

## Node Status — Data Sources

| Node | Source |
|------|--------|
| `trustplane-gateway` | HTTP GET `/healthz` + `/v1/providers/health` |
| `token-compressor` | `/tmp/b76_compress.log` |
| `session-memory` | `/tmp/b76_save.log` + SQLite `traces.sqlite3` |
| `armada-bus` | `/tmp/b76_armada_bus.json` + `/tmp/b76_armada_bus.log` |
| `agent-*` | `psutil` — is the process running? |
| `conductor` | Always `active` (the conductor itself) |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `COGNOS_BASE_URL` | `http://127.0.0.1:8788` | TrustPlane gateway URL |
| `COGNOS_API_KEY` | _(empty)_ | API key for gateway auth |

---

## Verification

```bash
# Test that the server starts
python3 -m conductor_graph_mcp

# Stop the gateway → trustplane-gateway.status = "error"
# get_blocked_nodes() should return trustplane-gateway

# Run a /save → session-memory.metrics.entries increases
# get_node_status("session-memory") shows new count
```

---

## License

MIT — Base76 Research Lab
