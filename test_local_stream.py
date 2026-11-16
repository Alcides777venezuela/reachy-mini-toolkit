#!/usr/bin/env python3
"""
test_local_stream.py — Mide el MODO LOCAL con streaming (SSE).

Compara lo que ve el usuario:
  · tiempo hasta el PRIMER audio (frase 1 sintetizada)
  · tiempo total del turno
  · nº de frases y de audio chunks

Uso:  python test_local_stream.py "¿Qué hora es en Tokio? Cuéntame un chiste."
"""

import json
import sys
import time

import httpx

URL = "http://127.0.0.1:8090/api/local/turn/stream"
PREGUNTA = sys.argv[1] if len(sys.argv) > 1 else "¿Qué hora es en Tokio? Cuéntame un chiste."


def main():
    t0 = time.time()
    frases = 0
    audio_bytes = 0
    primero = None
    print(f"→ «{PREGUNTA}»")
    with httpx.Client(timeout=240) as c:
        with c.stream("POST", URL, json={"text": PREGUNTA, "persona": "default"}) as r:
            r.raise_for_status()
            for linea in r.iter_lines():
                if not linea.startswith("data: "):
                    continue
                m = json.loads(linea[6:])
                t = m.get("type")
                if t == "tool":
                    print(f"  🛠️ {m['name']}  (+{time.time() - t0:.2f}s)")
                elif t == "sentence":
                    frases += 1
                    if m.get("audio"):
                        audio_bytes += len(__import__("base64").b64decode(m["audio"]))
                    if primero is None:
                        primero = time.time() - t0
                        print(f"  🔊 1ª frase (+{primero:.2f}s): «{m['text'][:70]}»")
                    else:
                        print(f"  🔊 frase {frases} (+{time.time() - t0:.2f}s): «{m['text'][:50]}»")
                elif t == "done":
                    print(f"\n  reply: «{(m.get('reply') or '')[:160]}»")
                    print(f"  tools={m.get('tools')}")
                    print(f"  total={m.get('latency_ms')} ms · 1er audio={m.get('first_audio_ms')} ms")
                    print(f"  frases={frases} · audio={audio_bytes} bytes ({audio_bytes / 32000:.1f}s)")
                elif t == "error":
                    print("  ⚠️", m.get("error"))


if __name__ == "__main__":
    main()
