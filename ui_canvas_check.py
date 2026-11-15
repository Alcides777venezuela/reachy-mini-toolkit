#!/usr/bin/env python3
"""
ui_canvas_check.py — Verifica el LIENZO de escritura ✍️ en un navegador real (CDP).

1. Abre la consola, espera a "lista"
2. Pulsa ✍️ (abre el panel)
3. Dibuja trazos con eventos de ratón sobre el canvas
4. Comprueba que hay pixeles dibujados
5. Pulsa "Enviar al robot" y espera la respuesta (el LLM debe leer la escritura)

Uso:  python ui_canvas_check.py [url]
"""

import asyncio
import json
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090/"


def find_browser():
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ):
        if pathlib.Path(p).is_file():
            return p
    raise SystemExit("no encuentro Edge/Chrome")


def cdp(path):
    with urllib.request.urlopen(f"http://127.0.0.1:9333{path}", timeout=10) as r:
        return json.load(r)


async def main():
    proc = subprocess.Popen(
        [find_browser(), "--headless=new", "--disable-gpu", "--no-first-run",
         "--remote-debugging-port=9333",
         f"--user-data-dir={tempfile.mkdtemp(prefix='cvtest_')}",
         "--window-size=1280,900", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(40):
            try:
                cdp("/json/version")
                break
            except Exception:
                time.sleep(0.3)

        page = next((t for t in cdp("/json/list") if t.get("type") == "page"), None)
        ws_url = page["webSocketDebuggerUrl"]
        errores = []

        async with websockets.connect(ws_url, max_size=32 * 1024 * 1024) as ws:
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

            # esperar conexión lista
            for _ in range(40):
                st = await js("document.getElementById('status').textContent")
                if st and st.startswith("lista"):
                    break
                await asyncio.sleep(0.5)
            print("[1] consola:", st)

            # abrir panel
            await js("document.getElementById('draw').click()")
            await asyncio.sleep(0.5)
            abierto = await js("document.getElementById('drawPanel').classList.contains('on')")
            print("[2] panel abierto:", abierto)

            # coordenadas del canvas
            rect = await js("(function(){const r=document.getElementById('canvas').getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height};})()")
            print("[3] canvas rect:", rect)

            # escribir texto real con una fuente tipo manuscrita (simula escritura a mano)
            await js("""(function(){
                const c=document.getElementById('canvas'),x=c.getContext('2d');
                x.fillStyle='#fff'; x.fillRect(0,0,c.width,c.height);
                x.fillStyle='#111'; x.font='110px "Segoe Script", "Comic Sans MS", cursive';
                x.fillText('Reachy 2026', 120, 260);
                x.font='64px "Segoe Script", cursive';
                x.fillText('voz + vision + escritura', 150, 400);
            })()""")
            await asyncio.sleep(0.3)

            # (también probamos trazos con ratón)
            puntos = []
            base_x, base_y = rect["x"] + 40, rect["y"] + 40
            # línea vertical
            for i in range(12):
                puntos.append((base_x, base_y + i * 8))
            # bucle
            for i in range(10):
                puntos.append((base_x + 10 + i * 5, base_y + 10 + i * 4))
            # pata
            for i in range(10):
                puntos.append((base_x + 10 + i * 6, base_y + 60 + i * 5))

            await cmd("Input.dispatchMouseEvent", {"type": "mousePressed", "x": puntos[0][0], "y": puntos[0][1],
                                                   "button": "left", "clickCount": 1})
            for x, y in puntos:
                await cmd("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y, "button": "left"})
                await asyncio.sleep(0.01)
            await cmd("Input.dispatchMouseEvent", {"type": "mouseReleased", "x": puntos[-1][0],
                                                   "y": puntos[-1][1], "button": "left", "clickCount": 1})

            tinta = await js("""(function(){
                const c=document.getElementById('canvas'),x=c.getContext('2d');
                const d=x.getImageData(0,0,c.width,c.height).data;let n=0;
                for(let i=0;i<d.length;i+=4){ if(d[i]<200||d[i+1]<200||d[i+2]<200) n++; }
                return n;})()""")
            print("[4] pixeles con tinta:", tinta)

            # enviar al robot
            await js("document.getElementById('sendDraw').click()")
            print("[5] enviado; esperando respuesta del LLM…")

            respuesta = ""
            for _ in range(60):
                await asyncio.sleep(1)
                txt = await js("(document.querySelectorAll('#chat .msg')[document.querySelectorAll('#chat .msg').length-1]||{}).textContent||''")
                if "tool(s)" in (txt or ""):
                    respuesta = txt
                    break
            print("[6] respuesta:", (respuesta or "")[:300])
            print("    excepciones:", errores or "ninguna")
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())


