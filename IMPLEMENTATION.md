# Implementation Guide

How to adapt Conductor-Graph-MCP to your own agent stack.

---

## Prerequisites

- Python 3.10+
- An MCP-compatible host (Claude Code, or any MCP client)
- Your agents running as processes, HTTP services, or writing log files

## 1. Install

```bash
git clone https://github.com/base76-research-lab/conductor-graph-mcp.git
cd conductor-graph-mcp
pip install -r requirements.txt
```

## 2. Understand the structure

The server defines three primitives:

```python
NodeStatus   # id, type, status, last_seen, metrics, model
Edge         # from_node, to_node, type, last_active
GraphSnapshot  # timestamp, nodes, edges, summary
```

Each node has one of four statuses: `active | idle | blocked | error`

Node types: `conductor | gateway | agent | utility | store | bus`

---

## 3. Map your system to nodes

Open `graph_server.py` and locate the `AGENT_SCRIPTS` dict and the five collector functions. Replace them with your own agents and services.

### Example: replacing the agent list

```python
# Default (CognOS armada)
AGENT_SCRIPTS = {
    "agent-critic":  "b76_agent_critic.py",
    "agent-curator": "b76_agent_curator.py",
    ...
}

# Your stack
AGENT_SCRIPTS = {
    "summarizer":  "my_summarizer_agent.py",
    "classifier":  "my_classifier_agent.py",
    "retriever":   "my_rag_retriever.py",
}
```

`_collect_agents()` checks if these script names appear in running process cmdlines via `psutil`. No changes needed there.

---

## 4. Add your own collectors

Each collector is an `async def` that returns a `NodeStatus`. Pattern:

```python
async def _collect_my_service() -> NodeStatus:
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:9000/health")
            r.raise_for_status()
            data = r.json()
            return NodeStatus(
                id="my-service",
                type="gateway",
                status="active" if data["ok"] else "idle",
                last_seen=_now_iso(),
                metrics={"requests": data.get("total_requests", 0)},
            )
    except Exception:
        return NodeStatus(id="my-service", type="gateway", status="error")
```

Then register it in `_build_graph()`:

```python
async def _build_graph() -> GraphSnapshot:
    gateway_task    = asyncio.create_task(_collect_gateway())
    my_service_task = asyncio.create_task(_collect_my_service())   # ← add
    agents_task     = asyncio.create_task(_collect_agents())

    gateway, my_service, agent_nodes = await asyncio.gather(
        gateway_task, my_service_task, agents_task
    )

    all_nodes = [conductor, gateway, my_service] + agent_nodes
    ...
```

All collectors run in parallel — adding more does not slow things down.

---

## 5. Define your edges

Edges describe communication flow. Edit `_build_edges()`:

```python
def _build_edges(nodes: list[NodeStatus]) -> list[Edge]:
    return [
        Edge("conductor",   "my-service",  "verify"),
        Edge("my-service",  "summarizer",  "route"),
        Edge("my-service",  "classifier",  "route"),
        Edge("summarizer",  "my-store",    "store"),
    ]
```

Edge types are free-form strings. Common conventions: `verify`, `escalate`, `route`, `store`, `compress`.

---

## 6. Read log files

If your services write structured logs, parse them in a collector:

```python
MY_LOG = Path("/tmp/my_service.log")

async def _collect_from_log() -> NodeStatus:
    if not MY_LOG.exists():
        return NodeStatus(id="log-service", type="utility", status="idle")
    text = MY_LOG.read_text()
    m = re.search(r"processed (\d+) items", text)
    return NodeStatus(
        id="log-service",
        type="utility",
        status="active",
        metrics={"items": int(m.group(1)) if m else 0},
    )
```

---

## 7. Register in Claude Code

Add to `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "my-graph": {
      "command": "python3",
      "args": ["/path/to/conductor-graph-mcp/graph_server.py"],
      "env": {
        "COGNOS_BASE_URL": "http://127.0.0.1:YOUR_PORT",
        "COGNOS_API_KEY": "your-key-or-empty"
      }
    }
  }
}
```

Restart Claude Code. The four tools are now available to your conductor.

---

## 8. Call it

```
get_agent_graph()           → full snapshot of all nodes and edges
get_node_status("my-node")  → single node details
get_edges()                 → communication flow only
get_blocked_nodes()         → what is broken right now?
```

---

## Minimal example (3 nodes, no gateway)

If you have no HTTP gateway and just want to track local agent processes:

```python
AGENT_SCRIPTS = {
    "worker-a": "worker_a.py",
    "worker-b": "worker_b.py",
}

async def _build_graph() -> GraphSnapshot:
    agents_task = asyncio.create_task(_collect_agents())
    agent_nodes = await agents_task

    conductor = NodeStatus(
        id="conductor", type="conductor", status="active",
        last_seen=_now_iso(), metrics={}
    )

    all_nodes = [conductor] + agent_nodes
    edges = [
        Edge("conductor", "worker-a", "route"),
        Edge("conductor", "worker-b", "route"),
    ]
    return GraphSnapshot(
        timestamp=_now_iso(),
        nodes=all_nodes,
        edges=edges,
        summary=_build_summary(all_nodes),
    )
```

Delete the unused collectors. That's it.

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| All agents `idle` | psutil not finding processes | Check that script names in `AGENT_SCRIPTS` match actual cmdline |
| Gateway always `error` | Service not running | Start service or remove that collector |
| `psutil` import error | Not installed | `pip install psutil` |
| MCP server not appearing | settings.json syntax error | Validate JSON, restart Claude Code |
