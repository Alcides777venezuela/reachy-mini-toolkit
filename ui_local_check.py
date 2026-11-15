#!/usr/bin/env python3
"""
ui_local_check.py — Verifica la UI en MODO LOCAL (sin HF realtime) por CDP.

1. abre la consola
2. cambia el selector de modo a "local"
3. envía un texto
4. comprueba que llega respuesta con tools (sin usar el asignador de HF)

Uso:  python ui_local_check.py
"""

import asyncio
import json
import pathlib
import subprocess
import tempfile
import time
import urllib.request

import websockets

URL = "http://127.0.0.1:8090/"
PUERTO_CDP = 9344


def browser():
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ):
        if pathlib.Path(p).is_file():
            return p
    raise SystemExit("no encuentro Edge")


def http(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PUERTO_CDP}{path}", timeout=10) as r:
        return json.load(r)


async def main():
    proc = subprocess.Popen(
        [browser(), "--headless=new", "--disable-gpu", "--no-first-run",
         f"--remote-debugging-port={PUERTO_CDP}",
         f"--user-data-dir={tempfile.mkdtemp(prefix='localchk_')}",
         "--window-size=1280,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            try:
                http("/json/version")
                break
            except Exception:
                time.sleep(0.3)
        page = next((t for t in http("/json/list") if t.get("type") == "page"), None)
        errores = []
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=32 * 1024 * 1024) as ws:
            nid = 0

            async def cmd(method, params=None):
                nonlocal nid
                nid += 1
                await ws.send(json.dumps({"id": nid, "method": method, "params": params or {}}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == nid:
                        return m
                    if m.get("method") == "Runtime.exceptionThrown":
                        errores.append(json.dumps(m["params"])[:200])

            async def js(expr):
                r = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
                return (r.get("result", {}).get("result") or {}).get("value")

            await cmd("Runtime.enable")
            await cmd("Page.enable")
            await cmd("Page.navigate", {"url": URL})
            await asyncio.sleep(3)

            # cambiar a modo local
            await js("(function(){const s=document.getElementById('mode');s.value='local';s.dispatchEvent(new Event('change'));})()")
            await asyncio.sleep(1.5)
            print("[1] modo:", await js("document.getElementById('mode').value"),
                  "| estado:", await js("document.getElementById('status').textContent"))

            # enviar mensaje
            await js("document.getElementById('inp').value='¿Qué hora es en Madrid? Dime también un chiste.'")
            await js("document.getElementById('form').requestSubmit()")
            print("[2] enviado, esperando respuesta local…")

            respuesta = ""
            for _ in range(90):
                await asyncio.sleep(1)
                txt = await js("(document.querySelectorAll('#chat .msg')[document.querySelectorAll('#chat .msg').length-1]||{}).textContent||''")
                if "tool(s)" in (txt or ""):
                    respuesta = txt
                    break
            print("[3] respuesta:", (respuesta or "")[:220])
            print("    modo final:", await js("document.getElementById('mode').value"))
            print("    excepciones:", errores or "ninguna")
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
