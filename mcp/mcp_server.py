#!/usr/bin/env python3
"""
mcp_server.py — MCP server propio (Model Context Protocol, stdio).

Implementa JSON-RPC 2.0 sobre stdin/stdout:
  initialize · notifications/initialized · tools/list · tools/call · ping

Las 10 tools viven en tools_impl.py (compartidas con el Space y el puente HTTP):
  wiki_resumen · clima · monedas · traducir · calculadora ·
  convertir_unidades · hora_en · curiosidad · chiste · dado

Usarlo en cualquier cliente MCP:

    "mcpServers": {
      "reachy-mcp": { "command": "python", "args": ["<ruta>/mcp_server.py"] }
    }
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools_impl import TOOLS, call_tool  # noqa: E402

PROTOCOL_VERSION = "2025-06-18"
SERVER_NAME = "reachy-mcp"
SERVER_VERSION = "1.1.0"


def send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def reply(req_id, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    send(msg)


def handle(msg: dict) -> None:
    method = msg.get("method")
    req_id = msg.get("id")

    if method == "initialize":
        reply(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        })
    elif method == "notifications/initialized":
        pass  # notificación: sin respuesta
    elif method == "ping":
        reply(req_id, {})
    elif method == "tools/list":
        reply(req_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        args = params.get("arguments") or {}
        try:
            text = call_tool(name, args)
            reply(req_id, {"content": [{"type": "text", "text": text}], "isError": False})
        except Exception as e:                              # noqa: BLE001
            reply(req_id, {"content": [{"type": "text", "text": f"error: {e}"}], "isError": True})
    elif method == "resources/list":
        reply(req_id, {"resources": []})
    elif method == "prompts/list":
        reply(req_id, {"prompts": []})
    elif req_id is not None:
        reply(req_id, error={"code": -32601, "message": f"método no soportado: {method}"})


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict):
            handle(msg)


if __name__ == "__main__":
    main()
