#!/usr/bin/env python3
"""
test_vision_llm.py — El LLM usa las TOOLS de visión/OCR (no endpoints directos).

Flujo:
  1. sube una imagen a la consola (/api/vision/upload) → URL local
  2. abre el WebSocket de chat y pide analizar esa URL
  3. verifica que el modelo llamó a `ocr_imagen` / `describir_imagen` y respondió

Uso:  python test_vision_llm.py [ruta_imagen]
"""

import asyncio
import base64
import json
import pathlib
import sys
import time
import urllib.request

import websockets

RUTA_DEFECTO = pathlib.Path.home() / "OneDrive" / "deepseek" / "investigacion-hf" / "test_ocr.png"
WS_URL = "ws://127.0.0.1:8090/ws/chat?personality=default&voice="


def subir_imagen(ruta: pathlib.Path) -> str:
    b64 = base64.b64encode(ruta.read_bytes()).decode()
    req = urllib.request.Request(
        "http://127.0.0.1:8090/api/vision/upload",
        data=json.dumps({"image": b64}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        d = json.load(r)
    if not d.get("ok"):
        raise RuntimeError(d.get("error"))
    return d["url"]


async def probar(url: str, pregunta: str):
    async with websockets.connect(WS_URL, open_timeout=30) as ws:
        msg = json.loads(await ws.recv())
        if msg.get("type") == "status":
            msg = json.loads(await ws.recv())
        print(f"[ready] session={msg.get('session_id')}")
        texto = f"{pregunta} La imagen está en: {url}"
        print(f"[→] «{texto}»")
        t0 = time.time()
        await ws.send(json.dumps({"type": "user_text", "text": texto}))

        tools = []
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=180))
            t = m.get("type")
            if t == "tool_call":
                tools.append(m["name"])
                print(f"  🛠️ {m['name'].split('__')[-1]} {m['args'][:100]}")
            elif t == "tool_result":
                print(f"      ↳ {m['result'][:160]}")
            elif t == "user_transcript":
                print(f"  🎤 {m.get('text')}")
            elif t == "turn_done":
                print(f"[4] 🔊 «{m.get('transcript')}»")
                print(f"    tools={[x.split('__')[-1] for x in m.get('tools', [])]} | "
                      f"total={time.time() - t0:.2f}s")
                return m.get("tools", [])


if __name__ == "__main__":
    ruta = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else RUTA_DEFECTO
    if not ruta.is_file():
        raise SystemExit(f"no existe la imagen: {ruta}")
    print(f"[1] imagen: {ruta}")
    url = subir_imagen(ruta)
    print(f"[2] subida → {url}")
    pregunta = "Analiza la imagen: dime qué es y transcribe exactamente el texto que tenga."
    asyncio.run(asyncio.wait_for(probar(url, pregunta), timeout=300))
