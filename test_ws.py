#!/usr/bin/env python3
"""
test_ws.py — Cliente de prueba de la consola web (sin navegador).

Conecta al WebSocket local, envía un mensaje y valida el ciclo completo:
ready → tool calls → transcript → audio (WAV base64) → turn_done.

Uso:  python test_ws.py [personality] [pregunta]
"""

import asyncio
import base64
import json
import sys
import time

import websockets

URL = "ws://127.0.0.1:8090/ws/chat"


async def probe(personality: str, question: str, timeout: float = 120.0):
    url = f"{URL}?personality={personality}&voice="
    print(f"\n=== WS {url}")
    async with websockets.connect(url, open_timeout=20) as ws:
        first = json.loads(await ws.recv())
        print(f"  server: {first.get('type')} — {first.get('text') or first.get('session_id') or ''}")
        if first.get("type") == "status":
            ready = json.loads(await ws.recv())
            print(f"  server: ready → session={ready.get('session_id')} persona={ready.get('personality')} voz={ready.get('voice')}")
        t0 = time.time()
        await ws.send(json.dumps({"type": "user_text", "text": question}))
        print(f"  → «{question}»")
        while True:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
            m = json.loads(raw)
            t = m.get("type")
            if t == "transcript_delta":
                continue
            if t == "tool_call":
                print(f"  🛠️  {m['name'].split('__')[-1]}  {m['args']}")
            elif t == "tool_result":
                print(f"      ↳ {m['result'][:150]}")
            elif t == "turn_done":
                audio = m.get("audio")
                n = len(base64.b64decode(audio)) if audio else 0
                print(f"  🔊 «{m['transcript']}»")
                print(f"     tools={m['tools']} | wav={n} bytes ({n / 32000.0:.1f}s) | "
                      f"1er audio={m.get('latency_s')}s | total={time.time() - t0:.2f}s")
                return m
            elif t == "error":
                print(f"  ⚠️  {m.get('message')}")
                return m


async def main():
    personality = sys.argv[1] if len(sys.argv) > 1 else "default"
    question = sys.argv[2] if len(sys.argv) > 2 else "Hola, ¿quién eres? Dime tu nombre y una frase."
    r = await probe(personality, question)
    return 0 if r and r.get("type") == "turn_done" else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
