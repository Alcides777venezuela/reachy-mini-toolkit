#!/usr/bin/env python3
"""
test_429.py — Verifica el backoff ante 429 del asignador de sesiones de HF.

Conecta dos veces seguidas al WebSocket de la consola:
  · 1ª conexión  → intenta asignar sesión (puede dar rate_limited y fijar cooldown)
  · 2ª conexión  → debe responder rate_limited SIN llamar a HF (cooldown local)

Uso:  python test_429.py
"""

import asyncio
import json
import time

import websockets

URL = "ws://127.0.0.1:8090/ws/chat?personality=default&voice="


async def intento(n: int):
    t0 = time.time()
    async with websockets.connect(URL, open_timeout=20) as ws:
        while True:
            try:
                m = json.loads(await asyncio.wait_for(ws.recv(), timeout=90))
            except asyncio.TimeoutError:
                print(f"  intento {n}: timeout esperando mensajes")
                return
            t = m.get("type")
            if t == "status":
                continue
            print(f"  intento {n}: {t} (t={time.time() - t0:.2f}s)"
                  + (f" retry_after={m.get('retry_after')}s" if m.get("retry_after") else "")
                  + (f" | {str(m.get('message'))[:80]}" if m.get("message") else ""))
            if t in ("rate_limited", "ready", "error"):
                return


if __name__ == "__main__":
    print("== prueba de backoff 429 ==")
    asyncio.run(intento(1))
    asyncio.run(intento(2))
