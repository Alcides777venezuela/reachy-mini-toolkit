#!/usr/bin/env python3
"""
ui_stop_check.py — Verifica el barge-in / botón ⏹ (detener voz) en la UI.

Comprueba: el botón existe y está oculto; aparece mientras "suena"; al pulsarlo
se oculta y deja la burbuja "⏹ (interrumpido)".

Uso:  python ui_stop_check.py
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
PORT = 9366


def browser():
    for p in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"):
        if pathlib.Path(p).is_file():
            return p
    raise SystemExit("no encuentro Edge")


def http(path):
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}{path}", timeout=10) as r:
        return json.load(r)


async def main():
    proc = subprocess.Popen(
        [browser(), "--headless=new", "--disable-gpu", "--no-first-run",
         f"--remote-debugging-port={PORT}",
         f"--user-data-dir={tempfile.mkdtemp(prefix='stopchk_')}",
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
        async with websockets.connect(page["webSocketDebuggerUrl"], max_size=2 ** 25) as ws:
            nid = 0

            async def cmd(method, params=None):
                nonlocal nid
                nid += 1
                await ws.send(json.dumps({"id": nid, "method": method, "params": params or {}}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get("id") == nid:
                        return m

            async def js(expr):
                r = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
                return (r.get("result", {}).get("result") or {}).get("value")

            await cmd("Runtime.enable")
            await cmd("Page.enable")
            await cmd("Page.navigate", {"url": URL})
            await asyncio.sleep(3)

            print("[1] botón ⏹ existe:", await js("!!document.getElementById('stop')"))
            print("[2] oculto al inicio:", await js("getComputedStyle(document.getElementById('stop')).display"))
            await js("sonandoAudio = true; audioActual = null; actualizarBotonParar();")
            print("[3] visible mientras suena:", await js("getComputedStyle(document.getElementById('stop')).display"))
            await js("document.getElementById('stop').click()")
            await asyncio.sleep(0.3)
            print("[4] oculto tras parar:", await js("getComputedStyle(document.getElementById('stop')).display"))
            print("[5] burbuja:", await js("(document.querySelectorAll('#chat .msg')[document.querySelectorAll('#chat .msg').length-1]||{}).textContent||''"))
            # tecla Escape
            await js("sonandoAudio = true; actualizarBotonParar();")
            await cmd("Input.dispatchKeyEvent", {"type": "keyDown", "key": "Escape", "code": "Escape", "windowsVirtualKeyCode": 27})
            await asyncio.sleep(0.3)
            print("[6] tras Escape:", await js("getComputedStyle(document.getElementById('stop')).display"))
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())
