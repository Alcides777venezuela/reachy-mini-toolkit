#!/usr/bin/env python3
"""
test_web_space.py — Verifica la CONSOLA DESPLEGADA en Hugging Face (Space privado).

Comprueba: HTML, /api/meta, caché y un turno en modo local con streaming (SSE).
Requiere el token HF en la caché (el Space es privado → necesita Authorization).

Uso:  python test_web_space.py
"""

import json
import os
import pathlib
import time

import httpx

token = (pathlib.Path.home() / ".cache" / "huggingface" / "token").read_text().strip()
BASE = (os.getenv("SPACE_URL") or "https://alcides777-reachy-web-console.hf.space").rstrip("/")
H = {"Authorization": f"Bearer {token}", "User-Agent": "reachy-web-test"}


def main():
    print("→", BASE)
    with httpx.Client(timeout=180, headers=H, follow_redirects=True) as c:
        r = c.get(BASE + "/")
        print(f"[1] GET /          → {r.status_code} · {len(r.content)} bytes "
              f"· {'mic' in r.text and 'sí' or 'no'} tiene UI")

        r = c.get(BASE + "/api/meta")
        print(f"[2] /api/meta      → {r.status_code} · {len(r.json().get('tools', []))} tools")

        r = c.get(BASE + "/api/local/cache")
        print(f"[3] /api/local/cache → {r.status_code} · {r.text[:120]}")

        print("[4] turno modo local (streaming SSE)…")
        t0 = time.time()
        primero = None
        frases = 0
        with c.stream("POST", BASE + "/api/local/turn/stream",
                      json={"text": "Dime la hora en Tokio y un chiste.", "persona": "default"}) as r:
            print(f"    HTTP {r.status_code} · {r.headers.get('content-type')}")
            for linea in r.iter_lines():
                if not linea.startswith("data: "):
                    continue
                m = json.loads(linea[6:])
                if m.get("type") == "sentence":
                    frases += 1
                    if primero is None:
                        primero = m.get("t_ms")
                        print(f"    🔊 1ª frase a {primero} ms: «{m.get('text')[:60]}»")
                elif m.get("type") == "tool":
                    print(f"    🛠️ {m.get('name')}")
                elif m.get("type") == "done":
                    print(f"    ✅ reply: «{(m.get('reply') or '')[:140]}»")
                    print(f"    tools={m.get('tools')} · frases={frases} · "
                          f"total={m.get('latency_ms')} ms · 1er audio={m.get('first_audio_ms')} ms")
                elif m.get("type") == "error":
                    print("    ⚠️", m.get("error"))
        print(f"[5] tiempo de la prueba: {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
