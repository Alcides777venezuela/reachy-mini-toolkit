#!/usr/bin/env python3
"""
robot_sim.py — Simula lo que hará el ROBOT al instalar nuestro Space.

Replica la ruta EXACTA del app (mcp_client.RemoteMcpToolClient, mcp>=2.0):
  transport = streamable_http_client("https://<space>.hf.space/gradio_api/mcp/")
  async with Client(transport) as client:
      tools = await client.list_tools()
      res   = await client.call_tool(nombre, args)

También imprime el nombre LOCAL que generará el app (`alias__tool`), limpiando el
prefijo redundante del Space, como hace tool_spaces._clean_space_tool_name.

Uso:  python robot_sim.py [owner/space]
"""

import asyncio
import re
import sys

from mcp import Client
from mcp.client.streamable_http import streamable_http_client

SLUG = sys.argv[1] if len(sys.argv) > 1 else "Alcides777/reachy-mcp-tool"
URL = f"https://{SLUG.replace('/', '-').lower()}.hf.space/gradio_api/mcp/"
ALIAS = re.sub(r"[^A-Za-z0-9_]+", "_", SLUG).strip("_").lower()
SPACE_NAME = re.sub(r"[^A-Za-z0-9_]+", "_", SLUG.split("/", 1)[1]).strip("_")


def local_tool_name(remote: str) -> str:
    """Misma limpieza que el app: alias__<nombre sin prefijo del space>."""
    name = re.sub(r"[^A-Za-z0-9_]+", "_", remote).strip("_")
    name = re.sub(r"_+", "_", name)
    prefix = f"{SPACE_NAME}_"
    if name.startswith(prefix):
        name = name[len(prefix):]
    return f"{ALIAS}__{name or remote}"


def texto_de(res) -> str:
    partes = []
    for c in getattr(res, "content", []) or []:
        if getattr(c, "type", "") == "text":
            partes.append(getattr(c, "text", ""))
    return "\n".join(p for p in partes if p)


async def main():
    print(f"[1] endpoint : {URL}")
    transport = streamable_http_client(URL)
    async with Client(transport) as client:
        tools = await client.list_tools()
        lista = getattr(tools, "tools", tools)
        print(f"[2] list_tools → {len(lista)} tools")
        for t in lista:
            print(f"    - {t.name:38} → {local_tool_name(t.name)}")

        print("\n[3] call_tool('reachy_mcp_tool_clima', {'ciudad': 'Caracas'}) — nombre remoto real")
        res = await client.call_tool("reachy_mcp_tool_clima", {"ciudad": "Caracas"})
        print("    resultado:", texto_de(res)[:200])
        print("    isError  :", getattr(res, "isError", getattr(res, "is_error", None)))

        print("\n[4] call_tool('describir_imagen', URL pública) — tool de visión")
        try:
            res2 = await client.call_tool(
                "reachy_mcp_tool_describir_imagen",
                {"imagen": "https://huggingface.co/datasets/huggingface/documentation-images/resolve/main/cats.png"},
            )
            print("    resultado:", texto_de(res2)[:200])
        except Exception as e:
            print("    visión error:", type(e).__name__, str(e)[:150])


if __name__ == "__main__":
    asyncio.run(asyncio.wait_for(main(), timeout=240))

