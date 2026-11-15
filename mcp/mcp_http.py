#!/usr/bin/env python3
"""
mcp_http.py — Puente HTTP estilo Gradio para el MCP propio.

Expone los endpoints que la consola web (y cualquier cliente Gradio-MCP) espera:
  GET  /gradio_api/mcp/schema          → lista de tools con meta.endpoint_name
  POST /gradio_api/call/<fn>           → {"event_id": "..."}   (body: {"data": [...]})
  GET  /gradio_api/call/<fn>/<event_id> → SSE "event: complete\\ndata: [resultado]"
  GET  /health                         → ok

Ejecutar:  python mcp_http.py     →  http://127.0.0.1:8091
"""

import json
import sys
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from tools_impl import ARGS_MAP, TOOLS, call_tool  # noqa: E402

HOST, PORT = "127.0.0.1", 8091
EVENTS: dict[str, list] = {}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _json(self, obj, status=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _sse(self, text: str, status=200):
        body = text.encode()
        self.send_response(status)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/health":
            return self._json({"ok": True})
        if path == "/gradio_api/mcp/schema":
            return self._json([{
                "name": f"reachy_mcp_{t['name']}",
                "description": t["description"],
                "inputSchema": t["inputSchema"],
                "meta": {"mcp_type": "tool", "endpoint_name": t["name"]},
            } for t in TOOLS])
        if path.startswith("/gradio_api/call/"):
            parts = path.strip("/").split("/")
            if len(parts) == 4:
                _fn, ev = parts[2], parts[3]
                result = EVENTS.pop(ev, None)
                if result is None:
                    return self._sse('event: error\ndata: {"error": "evento desconocido"}\n', 404)
                return self._sse(f"event: complete\ndata: {json.dumps(result, ensure_ascii=False)}\n")
        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = self.path.split("?")[0]
        if path.startswith("/gradio_api/call/"):
            parts = path.strip("/").split("/")
            fn = parts[2]
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                data = body.get("data") or []
            except Exception:                               # noqa: BLE001
                return self._json({"error": "bad json"}, 400)
            params = ARGS_MAP.get(fn)
            if params is None:
                return self._json({"error": f"función desconocida: {fn}"}, 404)
            args = {p: (data[i] if i < len(data) else d) for i, (p, d) in enumerate(params)}
            out = call_tool(fn, args)
            ev = uuid.uuid4().hex
            EVENTS[ev] = [out]
            return self._json({"event_id": ev})
        return self._json({"error": "not found"}, 404)


def main():
    print(f"🔌 MCP HTTP bridge → http://{HOST}:{PORT}/gradio_api/mcp/schema")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
