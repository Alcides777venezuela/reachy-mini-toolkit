#!/usr/bin/env python3
"""
ui_check.py — Verificación real de la UI con Chrome DevTools Protocol.

Lanza Edge headless con remote-debugging, se conecta por CDP, navega a la consola y:
  · captura errores de consola y excepciones
  · lee el estado real (status, nº de opciones, readyState del WebSocket)
  · simula el envío de un mensaje y comprueba la respuesta

Uso:  python ui_check.py [url]
"""

import asyncio
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8090/"


def find_edge():
    for p in (
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    ):
        import pathlib
        if pathlib.Path(p).is_file():
            return p
    raise SystemExit("no encuentro Edge/Chrome")


def cdp_http(path):
    with urllib.request.urlopen(f"http://127.0.0.1:9222{path}", timeout=10) as r:
        return json.load(r)


async def main():
    edge = find_edge()
    profile = tempfile.mkdtemp(prefix="ui_check_")
    proc = subprocess.Popen(
        [edge, "--headless=new", "--disable-gpu", "--no-first-run",
         "--remote-debugging-port=9222", f"--user-data-dir={profile}",
         "--window-size=1280,900", "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(30):
            try:
                cdp_http("/json/version")
                break
            except Exception:
                time.sleep(0.3)
        tabs = cdp_http("/json/list")
        page = next((t for t in tabs if t.get("type") == "page"), None)
        if page is None:
            raise SystemExit("sin pestaña")
        ws_url = page["webSocketDebuggerUrl"]

        errors = []
        logs = []
        async with websockets.connect(ws_url, max_size=16 * 1024 * 1024) as ws:
            next_id = 0

            async def cmd(method, params=None):
                nonlocal next_id
                next_id += 1
                await ws.send(json.dumps({"id": next_id, "method": method, "params": params or {}}))
                while True:
                    msg = json.loads(await ws.recv())
                    if msg.get("id") == next_id:
                        return msg
                    ev = msg.get("method", "")
                    if ev == "Runtime.exceptionThrown":
                        errors.append(json.dumps(msg["params"], ensure_ascii=False)[:300])
                    elif ev == "Runtime.consoleAPICalled":
                        logs.append(" ".join(str(a.get("value", "")) for a in msg["params"].get("args", []))[:200])
                    elif ev == "Log.entryAdded":
                        e = msg["params"]["entry"]
                        logs.append(f"{e.get('level')}: {e.get('text')}")

            await cmd("Runtime.enable")
            await cmd("Log.enable")
            await cmd("Page.enable")
            await cmd("Page.navigate", {"url": URL})
            await asyncio.sleep(6)

            async def evaluate(expr):
                r = await cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
                return (r.get("result", {}).get("result") or {}).get("value")

            estado = await evaluate("document.getElementById('status').textContent")
            opciones = await evaluate("document.querySelectorAll('#personality option').length")
            wsready = await evaluate("typeof ws !== 'undefined' && ws ? ws.readyState : -1")
            mic = await evaluate("!!document.getElementById('mic')")
            send_disabled = await evaluate("document.getElementById('send').disabled")

            print("== UI ==")
            print("  estado      :", estado)
            print("  personalidades:", opciones)
            print("  ws.readyState:", wsready, "(1=abierto)")
            print("  botón mic   :", mic)
            print("  send.disabled:", send_disabled)
            print("== consola del navegador ==")
            for l in logs[-8:]:
                print("  ", l)
            if errors:
                print("== EXCEPCIONES ==")
                for e in errors:
                    print("  ", e)
            else:
                print("  (sin excepciones)")

            # probar el BOTÓN DE VOZ (dispositivo falso de Chrome)
            await evaluate("document.getElementById('mic').click()")
            await asyncio.sleep(2.5)
            mic_status = await evaluate("document.getElementById('status').textContent")
            mic_class = await evaluate("document.getElementById('mic').className")
            grabando = await evaluate("typeof recording !== 'undefined' && recording")
            print("\n== micrófono ==")
            print("  status   :", mic_status)
            print("  clase    :", mic_class)
            print("  recording:", grabando)
            await evaluate("document.getElementById('mic').click()")
            await asyncio.sleep(1.0)

            # probar envío de mensaje por la UI
            await evaluate("document.getElementById('inp').value='Hola, preséntate en una frase'")
            await evaluate("document.getElementById('form').requestSubmit()")
            await asyncio.sleep(12)
            burbujas = await evaluate("document.querySelectorAll('#chat .msg').length")
            ultimo = await evaluate("(document.querySelectorAll('#chat .msg')[document.querySelectorAll('#chat .msg').length-1]||{}).textContent||''")
            print("\n== tras enviar ==")
            print("  burbujas:", burbujas)
            print("  última  :", (ultimo or "")[:160])
    finally:
        proc.terminate()


if __name__ == "__main__":
    asyncio.run(main())

