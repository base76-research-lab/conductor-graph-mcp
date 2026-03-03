#!/usr/bin/env python3
"""
CognOS Graph MCP Server — Agentflöde som maskinläsbar graf.

Exponerar hela CognOS-armadan som en strukturerad JSON-graf så att
conductor (Claude76) kan anropa ett verktyg och få hela systembilden direkt.

FNC-arkitektur: Field (agenter) → Node (bearbetning) → Cockpit (oversight)
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from mcp.server import Server
from mcp.types import Tool, TextContent, CallToolResult

# ============================================================================
# Konfiguration
# ============================================================================

COGNOS_BASE_URL = os.getenv("COGNOS_BASE_URL", "http://127.0.0.1:8788")
COGNOS_API_KEY  = os.getenv("COGNOS_API_KEY", "")
REQUEST_TIMEOUT = 5  # kort timeout — vi vill ha snabb snapshot

SAVE_LOG      = Path("/tmp/b76_save.log")
BUS_LOG       = Path("/tmp/b76_armada_bus.log")
COMPRESS_LOG  = Path("/tmp/b76_compressed_prompt.txt")  # output-filen
COMPRESS_STAT = Path("/tmp/b76_compress.log")

DB_PATH = Path.home() / ".local/share/b76/sessions/traces.sqlite3"

AGENT_SCRIPTS = {
    "agent-critic":    "b76_agent_critic.py",
    "agent-curator":   "b76_agent_curator.py",
    "agent-ethics":    "b76_agent_ethics.py",
    "agent-synth":     "b76_agent_synth.py",
    "agent-self":      "b76_agent_self.py",
    "agent-srt":       "b76_agent_srt.py",
    "agent-indexer":   "b76_agent_indexer.py",
}


# ============================================================================
# Datastrukturer
# ============================================================================

@dataclass
class NodeStatus:
    id: str
    type: str                     # gateway | agent | utility | store | bus | conductor
    status: str                   # active | idle | blocked | error
    last_seen: Optional[str] = None
    metrics: dict = field(default_factory=dict)
    model: Optional[str] = None


@dataclass
class Edge:
    from_node: str
    to_node: str
    type: str                     # verify | escalate | route | store | compress
    last_active: Optional[str] = None


@dataclass
class GraphSnapshot:
    timestamp: str
    nodes: list[NodeStatus]
    edges: list[Edge]
    summary: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _node_dict(n: NodeStatus) -> dict:
    d = asdict(n)
    if d["model"] is None:
        del d["model"]
    return d


def _edge_dict(e: Edge) -> dict:
    d = asdict(e)
    d["from"] = d.pop("from_node")
    d["to"]   = d.pop("to_node")
    return d


# ============================================================================
# Collectors
# ============================================================================

async def _collect_gateway() -> NodeStatus:
    """Hämtar status från TrustPlane-gateway via /healthz och /v1/providers/health."""
    headers = {}
    if COGNOS_API_KEY:
        headers["Authorization"] = f"Bearer {COGNOS_API_KEY}"

    metrics: dict = {}
    status = "error"
    last_seen = None

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            # /healthz
            r = await client.get(f"{COGNOS_BASE_URL}/healthz", headers=headers)
            r.raise_for_status()
            data = r.json()
            status = "active" if data.get("status") == "ok" else "idle"
            last_seen = _now_iso()
            metrics["traces_total"] = data.get("traces_total", 0)
            metrics["last_decision"] = data.get("last_decision", "UNKNOWN")
            metrics["last_trust_score"] = data.get("last_trust_score", None)

            # /v1/providers/health
            try:
                rp = await client.get(
                    f"{COGNOS_BASE_URL}/v1/providers/health",
                    headers=headers,
                    timeout=REQUEST_TIMEOUT,
                )
                if rp.status_code == 200:
                    pd = rp.json()
                    metrics["providers"] = pd.get("providers", {})
            except Exception:
                pass

    except Exception:
        status = "error"

    return NodeStatus(
        id="trustplane-gateway",
        type="gateway",
        status=status,
        last_seen=last_seen,
        metrics=metrics,
    )


async def _collect_compressor() -> NodeStatus:
    """Läser /tmp/b76_compress.log för senaste körning."""
    metrics: dict = {}
    status = "idle"
    last_seen = None

    if COMPRESS_STAT.exists():
        try:
            text = COMPRESS_STAT.read_text()
            # Format: [HH:MM:SS] MODE | Nin→Noutt (-saved) | coverage X%
            m = re.search(
                r"\[(\d{2}:\d{2}:\d{2})\]\s*(\w+)\s*\|\s*(\d+)→(\d+)t\s*\(-(\d+)\)",
                text,
            )
            if m:
                status = "idle"  # compress körs on-demand och avslutas
                last_seen = m.group(1)
                metrics["mode"]             = m.group(2)
                metrics["tokens_in"]        = int(m.group(3))
                metrics["tokens_out"]       = int(m.group(4))
                metrics["last_tokens_saved"] = int(m.group(5))
                status = "idle"
        except Exception:
            pass
    elif COMPRESS_LOG.exists():
        # Filen finns → senaste output sparad
        status = "idle"
        last_seen = datetime.fromtimestamp(
            COMPRESS_LOG.stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds")
        metrics["output_bytes"] = COMPRESS_LOG.stat().st_size

    return NodeStatus(
        id="token-compressor",
        type="utility",
        status=status,
        last_seen=last_seen,
        metrics=metrics,
    )


async def _collect_session_memory() -> NodeStatus:
    """Läser /tmp/b76_save.log för senaste save + räknar traces i SQLite."""
    metrics: dict = {}
    status = "idle"
    last_seen = None

    if SAVE_LOG.exists():
        try:
            text = SAVE_LOG.read_text()
            # Format: [HH:MM:SS] Trust: X | Decision: Y | Trace: Z... | Totalt: N traces
            m_time = re.search(r"\[(\d{2}:\d{2}:\d{2})\]", text)
            if m_time:
                last_seen = m_time.group(1)
            m_tot = re.search(r"Totalt:\s*(\d+)\s*traces", text)
            if m_tot:
                metrics["entries"] = int(m_tot.group(1))
            m_dec = re.search(r"Decision:\s*(\w+)", text)
            if m_dec:
                metrics["last_decision"] = m_dec.group(1)
            status = "active" if metrics.get("entries", 0) > 0 else "idle"
        except Exception:
            pass

    # Kontrollera SQLite direkt om vi kan
    if DB_PATH.exists():
        try:
            import sqlite3
            con = sqlite3.connect(str(DB_PATH))
            cur = con.execute("SELECT COUNT(*) FROM traces")
            row = cur.fetchone()
            con.close()
            if row:
                metrics["entries"] = row[0]
                status = "active" if row[0] > 0 else "idle"
        except Exception:
            pass

    return NodeStatus(
        id="session-memory",
        type="store",
        status=status,
        last_seen=last_seen,
        metrics=metrics,
    )


async def _collect_bus() -> NodeStatus:
    """Läser /tmp/b76_armada_bus.log eller bussfilen för status."""
    metrics: dict = {}
    status = "idle"
    last_seen = None

    bus_file = Path("/tmp/b76_armada_bus.json")
    if bus_file.exists():
        try:
            data = json.loads(bus_file.read_text())
            msgs = data if isinstance(data, list) else data.get("messages", [])
            metrics["queued_messages"] = len(msgs)
            status = "active" if msgs else "idle"
            mtime = datetime.fromtimestamp(
                bus_file.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds")
            last_seen = mtime
        except Exception:
            pass
    elif BUS_LOG.exists():
        try:
            lines = BUS_LOG.read_text().splitlines()
            last_seen = datetime.fromtimestamp(
                BUS_LOG.stat().st_mtime, tz=timezone.utc
            ).isoformat(timespec="seconds")
            metrics["log_lines"] = len(lines)
        except Exception:
            pass

    return NodeStatus(
        id="armada-bus",
        type="bus",
        status=status,
        last_seen=last_seen,
        metrics=metrics,
    )


async def _collect_agents() -> list[NodeStatus]:
    """Kontrollerar om agent-processer kör via psutil."""
    try:
        import psutil
    except ImportError:
        # psutil ej installerat — returnera idle för alla
        return [
            NodeStatus(id=agent_id, type="agent", status="idle", metrics={})
            for agent_id in AGENT_SCRIPTS
        ]

    running: set[str] = set()
    for proc in psutil.process_iter(["cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            for agent_id, script in AGENT_SCRIPTS.items():
                if script in cmdline:
                    running.add(agent_id)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

    # Modellmappning från filnamn/kontext
    model_map = {
        "agent-critic":  "phi3.5",
        "agent-curator": "phi3.5",
        "agent-ethics":  "phi3.5",
        "agent-synth":   "phi3.5",
        "agent-self":    "phi3.5",
        "agent-srt":     "phi3.5",
        "agent-indexer": "nomic-embed",
    }

    nodes = []
    for agent_id in AGENT_SCRIPTS:
        nodes.append(NodeStatus(
            id=agent_id,
            type="agent",
            status="active" if agent_id in running else "idle",
            model=model_map.get(agent_id),
            metrics={},
        ))
    return nodes


# ============================================================================
# Graf-byggare
# ============================================================================

def _build_edges(nodes: list[NodeStatus]) -> list[Edge]:
    """Statisk kantkarta för CognOS FNC-flöde."""
    now = _now_iso()

    # Hitta aktiva noder
    active_ids = {n.id for n in nodes if n.status == "active"}

    def last_active(from_id: str, to_id: str) -> Optional[str]:
        if from_id in active_ids or to_id in active_ids:
            return now
        return None

    edges = [
        Edge("conductor", "trustplane-gateway", "verify",
             last_active("conductor", "trustplane-gateway")),
        Edge("conductor", "token-compressor", "compress",
             last_active("conductor", "token-compressor")),
        Edge("conductor", "session-memory", "store",
             last_active("conductor", "session-memory")),
        Edge("conductor", "armada-bus", "route",
             last_active("conductor", "armada-bus")),
        Edge("trustplane-gateway", "agent-critic", "escalate",
             last_active("trustplane-gateway", "agent-critic")),
        Edge("trustplane-gateway", "agent-ethics", "escalate",
             last_active("trustplane-gateway", "agent-ethics")),
        Edge("armada-bus", "agent-critic", "route",
             last_active("armada-bus", "agent-critic")),
        Edge("armada-bus", "agent-curator", "route",
             last_active("armada-bus", "agent-curator")),
        Edge("armada-bus", "agent-synth", "route",
             last_active("armada-bus", "agent-synth")),
        Edge("armada-bus", "agent-self", "route",
             last_active("armada-bus", "agent-self")),
        Edge("armada-bus", "agent-indexer", "route",
             last_active("armada-bus", "agent-indexer")),
        Edge("agent-indexer", "session-memory", "store",
             last_active("agent-indexer", "session-memory")),
        Edge("agent-self", "session-memory", "store",
             last_active("agent-self", "session-memory")),
    ]
    return edges


def _build_summary(nodes: list[NodeStatus]) -> str:
    active  = sum(1 for n in nodes if n.status == "active")
    blocked = sum(1 for n in nodes if n.status == "blocked")
    error   = sum(1 for n in nodes if n.status == "error")
    total   = len(nodes)

    parts = [f"{active}/{total} active nodes"]
    if blocked:
        parts.append(f"{blocked} blocked")
    if error:
        parts.append(f"{error} error")

    return ", ".join(parts)


async def _build_graph() -> GraphSnapshot:
    """Kör alla collectors parallellt och bygger grafen."""
    gateway_task  = asyncio.create_task(_collect_gateway())
    compress_task = asyncio.create_task(_collect_compressor())
    memory_task   = asyncio.create_task(_collect_session_memory())
    bus_task      = asyncio.create_task(_collect_bus())
    agents_task   = asyncio.create_task(_collect_agents())

    gateway, compressor, memory, bus, agent_nodes = await asyncio.gather(
        gateway_task, compress_task, memory_task, bus_task, agents_task
    )

    conductor = NodeStatus(
        id="conductor",
        type="conductor",
        status="active",
        last_seen=_now_iso(),
        metrics={"role": "claude76"},
    )

    all_nodes = [conductor, gateway, compressor, memory, bus] + agent_nodes
    edges     = _build_edges(all_nodes)
    summary   = _build_summary(all_nodes)

    return GraphSnapshot(
        timestamp=_now_iso(),
        nodes=all_nodes,
        edges=edges,
        summary=summary,
    )


# ============================================================================
# MCP Server
# ============================================================================

server = Server("cognos-graph")

GET_AGENT_GRAPH_TOOL = Tool(
    name="get_agent_graph",
    description=(
        "Returnerar hela CognOS-agentgrafen som en strukturerad dict. "
        "Conductor anropar detta för att förstå systemets tillstånd. "
        "Inkluderar alla noder (gateway, agenter, minne, buss) och kanter (kommunikationsflöde)."
    ),
    inputSchema={"type": "object", "properties": {}},
)

GET_NODE_STATUS_TOOL = Tool(
    name="get_node_status",
    description="Returnerar status för en specifik nod i CognOS-grafen.",
    inputSchema={
        "type": "object",
        "properties": {
            "node_id": {
                "type": "string",
                "description": (
                    "Nod-ID, t.ex. 'trustplane-gateway', 'agent-critic', "
                    "'session-memory', 'token-compressor', 'armada-bus', 'conductor'"
                ),
            }
        },
        "required": ["node_id"],
    },
)

GET_EDGES_TOOL = Tool(
    name="get_edges",
    description="Returnerar bara kanterna (kommunikationsflödet) i CognOS-grafen.",
    inputSchema={"type": "object", "properties": {}},
)

GET_BLOCKED_NODES_TOOL = Tool(
    name="get_blocked_nodes",
    description=(
        "Returnerar noder med status 'blocked' eller 'error'. "
        "Snabb shortcut för att se vad som inte fungerar just nu."
    ),
    inputSchema={"type": "object", "properties": {}},
)


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        GET_AGENT_GRAPH_TOOL,
        GET_NODE_STATUS_TOOL,
        GET_EDGES_TOOL,
        GET_BLOCKED_NODES_TOOL,
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> CallToolResult:

    if name == "get_agent_graph":
        snapshot = await _build_graph()
        result = {
            "timestamp": snapshot.timestamp,
            "nodes":     [_node_dict(n) for n in snapshot.nodes],
            "edges":     [_edge_dict(e) for e in snapshot.edges],
            "summary":   snapshot.summary,
        }
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, indent=2))],
            is_error=False,
        )

    elif name == "get_node_status":
        node_id  = arguments.get("node_id", "")
        snapshot = await _build_graph()
        found    = next((n for n in snapshot.nodes if n.id == node_id), None)
        if found:
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(_node_dict(found), indent=2))],
                is_error=False,
            )
        known = [n.id for n in snapshot.nodes]
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps({"error": f"Nod '{node_id}' hittades inte.", "known_nodes": known}),
            )],
            is_error=True,
        )

    elif name == "get_edges":
        snapshot = await _build_graph()
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps(
                    {"timestamp": snapshot.timestamp,
                     "edges": [_edge_dict(e) for e in snapshot.edges]},
                    indent=2,
                ),
            )],
            is_error=False,
        )

    elif name == "get_blocked_nodes":
        snapshot = await _build_graph()
        blocked  = [n for n in snapshot.nodes if n.status in ("blocked", "error")]
        return CallToolResult(
            content=[TextContent(
                type="text",
                text=json.dumps(
                    {
                        "timestamp":     snapshot.timestamp,
                        "blocked_count": len(blocked),
                        "nodes":         [_node_dict(n) for n in blocked],
                        "message":       "Inga blockerade noder." if not blocked
                                         else f"{len(blocked)} nod(er) med problem.",
                    },
                    indent=2,
                ),
            )],
            is_error=False,
        )

    return CallToolResult(
        content=[TextContent(type="text", text=f"Okänt verktyg: {name}")],
        is_error=True,
    )


async def main():
    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
