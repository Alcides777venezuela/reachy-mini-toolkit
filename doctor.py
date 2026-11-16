#!/usr/bin/env python3
"""
doctor.py — Chequeo de salud de todo el stack Reachy Mini.

Verifica: servicios locales, token HF, router (LLM/ASR), TTS (Piper/edge), tools,
Space publicado, caché y notas. Imprime un informe con ✅ / ⚠️ / ❌.

Uso:  python doctor.py
"""

import json
import os
import pathlib
import socket
import time
import urllib.request

OK, WARN, BAD = "✅", "⚠️", "❌"
filas: list[tuple[str, str, str]] = []


def añadir(nombre: str, estado: str, detalle: str = "") -> None:
    filas.append((nombre, estado, detalle))


def puerto_abierto(p: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", p)) == 0


def http_json(url: str, timeout: int = 25):
    req = urllib.request.Request(url, headers={"User-Agent": "reachy-doctor"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, json.load(r)


def main() -> None:
    t0 = time.time()

    # ── Servicios locales ────────────────────────────────────────────────
    for nombre, p in [("Consola web", 8090), ("Puente MCP", 8091),
                      ("Daemon del robot", 8000), ("App Reachy (UI)", 7860)]:
        añadir(nombre, OK if puerto_abierto(p) else BAD, f"puerto {p}")

    # ── Token HF ─────────────────────────────────────────────────────────
    token = ""
    for p in (pathlib.Path.home() / ".cache" / "huggingface" / "token",
              pathlib.Path.home() / ".huggingface" / "token"):
        if p.is_file():
            token = p.read_text().strip()
            break
    token = token or (os.getenv("HF_TOKEN") or "")
    if token:
        try:
            req = urllib.request.Request("https://huggingface.co/api/whoami-v2",
                                         headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=20) as r:
                d = json.load(r)
            añadir("Token HF", OK, f"{d.get('name')} (pro={d.get('isPro')})")
        except Exception as e:  # noqa: BLE001
            añadir("Token HF", BAD, f"{type(e).__name__}")
    else:
        añadir("Token HF", BAD, "no encontrado")

    # ── Router HF: LLM ───────────────────────────────────────────────────
    if token:
        try:
            t = time.time()
            body = {"model": "Qwen/Qwen3.8-27B",
                    "messages": [{"role": "user", "content": "di ok"}],
                    "max_tokens": 5}
            req = urllib.request.Request(
                "https://router.huggingface.co/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=60) as r:
                json.load(r)
            añadir("LLM (HF router)", OK, f"Qwen3.8-27B · {time.time() - t:.2f}s")
        except Exception as e:  # noqa: BLE001
            añadir("LLM (HF router)", BAD, f"{type(e).__name__}: {str(e)[:60]}")

    # ── TTS local (Piper) ────────────────────────────────────────────────
    try:
        import local_pipeline as LP

        if LP.piper_disponible():
            LP._sintetizar_piper("calentando", "es-ES-AlvaroNeural")   # carga del modelo
            t = time.time()
            wav = LP._sintetizar_piper("prueba de voz", "es-ES-AlvaroNeural")
            añadir("TTS Piper (local)", OK, f"{len(wav)}B en {time.time() - t:.2f}s (caliente)")
        else:
            añadir("TTS Piper (local)", WARN, f"modelo no encontrado en {LP.MODELOS_DIR}")
    except Exception as e:  # noqa: BLE001
        añadir("TTS Piper (local)", BAD, f"{type(e).__name__}: {str(e)[:50]}")

    # ── Caché TTS / notas ────────────────────────────────────────────────
    try:
        import local_pipeline as LP

        est = LP.cache_estado()
        añadir("Caché TTS", OK, f"{est['archivos']} archivos · {est['mb']} MB")
    except Exception:  # noqa: BLE001
        pass
    try:
        import sys

        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "mcp"))
        import tools_impl as T

        notas = T.listar_notas()
        n = notas.count("•")
        añadir("Notas guardadas", OK, f"{n} notas" if n else "sin notas")
        añadir("Tools del MCP", OK, f"{len(T.TOOLS)} tools")
    except Exception as e:  # noqa: BLE001
        añadir("Tools del MCP", BAD, str(e)[:60])

    # ── Puente MCP local ─────────────────────────────────────────────────
    try:
        st, data = http_json("http://127.0.0.1:8091/gradio_api/mcp/schema", timeout=10)
        añadir("Puente MCP (schema)", OK if st == 200 else WARN, f"{len(data)} tools")
    except Exception as e:  # noqa: BLE001
        añadir("Puente MCP (schema)", BAD, str(e)[:50])

    # ── Space publicado ──────────────────────────────────────────────────
    try:
        st, data = http_json("https://alcides777-reachy-mcp-tool.hf.space/gradio_api/mcp/schema", 60)
        añadir("Space HF (MCP)", OK if st == 200 else WARN, f"{len(data)} tools · despierto")
    except Exception as e:  # noqa: BLE001
        añadir("Space HF (MCP)", WARN, f"{type(e).__name__} (¿dormido? keepalive 12 h)")

    # ── Informe ──────────────────────────────────────────────────────────
    print()
    print("=" * 66)
    print(" 🩺 DOCTOR — Reachy Mini Toolkit")
    print("=" * 66)
    for nombre, estado, detalle in filas:
        print(f" {estado}  {nombre:<24} {detalle}")
    malos = sum(1 for _, e, _ in filas if e == BAD)
    avisos = sum(1 for _, e, _ in filas if e == WARN)
    print("-" * 66)
    print(f" {len(filas)} comprobaciones · {malos} fallos · {avisos} avisos · "
          f"{time.time() - t0:.1f}s")
    if malos:
        print("\n Sugerencias:")
        print("  · Consola/puente: python server.py  /  python mcp\\mcp_http.py")
        print("  · App: acceso directo 'Reachy Mini (App)'  ·  Daemon: run-simulado.ps1")
    print()


if __name__ == "__main__":
    main()
