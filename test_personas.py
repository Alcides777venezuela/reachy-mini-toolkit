#!/usr/bin/env python3
"""
test_personas.py — Verifica que cada personalidad responda en español y con su voz.

Recorre las personalidades del modo local, pide un turno corto y muestra:
  · respuesta (para comprobar el idioma/estilo)
  · bytes de audio (para comprobar que la voz cambia)

Uso:  python test_personas.py
"""

import base64
import json
import sys

import httpx

BASE = "http://127.0.0.1:8090"
PREGUNTAS = {
    "default": "Preséntate en una frase.",
    "mars_rover": "¿Qué eres y dónde estamos?",
    "noir_detective": "¿Quién eres, extraño?",
    "chef": "Dame un consejo rápido de cocina.",
    "profe": "Explícame en una frase qué es la fotosíntesis.",
}


def turno(persona: str, texto: str) -> dict:
    salida = {"reply": "", "audio": 0, "voz": None}
    with httpx.Client(timeout=180) as c:
        with c.stream("POST", BASE + "/api/local/turn/stream",
                      json={"text": texto, "persona": persona}) as r:
            r.raise_for_status()
            for linea in r.iter_lines():
                if not linea.startswith("data: "):
                    continue
                m = json.loads(linea[6:])
                if m.get("type") == "sentence":
                    salida["audio"] += len(base64.b64decode(m.get("audio") or ""))
                elif m.get("type") == "done":
                    salida["reply"] = m.get("reply") or ""
    return salida


def main():
    print(f"{'personalidad':<16} {'audio':>8}  respuesta")
    print("-" * 78)
    for persona, pregunta in PREGUNTAS.items():
        try:
            r = turno(persona, pregunta)
            print(f"{persona:<16} {r['audio']:>8}B  {r['reply'][:110]}")
        except Exception as e:  # noqa: BLE001
            print(f"{persona:<16} ERROR {type(e).__name__}: {str(e)[:60]}")


if __name__ == "__main__":
    main()
