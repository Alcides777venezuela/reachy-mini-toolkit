#!/usr/bin/env python3
"""
mcp_selftest.py — Cliente MCP de prueba (protocolo stdio, sin dependencias).

Habla con `mcp_server.py` como lo haría Claude Desktop / DSH / Cursor:
  initialize → initialized → tools/list → tools/call (x3) → fin.

Uso:  python mcp/selftest.py
"""

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVER = HERE / "mcp_server.py"

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class MCPClient:
    def __init__(self, cmd):
        self.p = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1,
        )
        self.next_id = 0

    def rpc(self, method, params=None):
        self.next_id += 1
        msg = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("servidor cerró la conexión")
            resp = json.loads(line)
            if resp.get("id") == self.next_id:
                if "error" in resp:
                    raise RuntimeError(resp["error"])
                return resp["result"]

    def notify(self, method, params=None):
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        self.p.terminate()


def main():
    print("=" * 70)
    print(" MCP SELFTEST — protocolo stdio contra mcp_server.py")
    print("=" * 70)
    c = MCPClient([sys.executable, str(SERVER)])

    init = c.rpc("initialize", {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "mcp-selftest", "version": "1.0"},
    })
    print(f"\n[initialize] server={init['serverInfo']['name']} v{init['serverInfo']['version']} "
          f"proto={init['protocolVersion']}")
    c.notify("notifications/initialized")

    tools = c.rpc("tools/list")["tools"]
    print(f"\n[tools/list] {len(tools)} tools:")
    for t in tools:
        print(f"  • {t['name']:12} — {t['description'][:60]}…")

    print("\n[tools/call]")
    r = c.rpc("tools/call", {"name": "wiki_resumen", "arguments": {"tema": "bambú"}})
    print(f"  wiki_resumen('bambú') →\n    {r['content'][0]['text'][:300]}…")

    r = c.rpc("tools/call", {"name": "curiosidad", "arguments": {}})
    print(f"\n  curiosidad() →\n    {r['content'][0]['text']}")

    r = c.rpc("tools/call", {"name": "hora_en", "arguments": {"zona": "Europe/Madrid"}})
    print(f"\n  hora_en('Europe/Madrid') →\n    {r['content'][0]['text']}")

    c.close()
    print("\n✅ MCP válido: initialize · tools/list · tools/call responden correctamente.")


if __name__ == "__main__":
    main()
