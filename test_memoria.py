#!/usr/bin/env python3
"""
test_memoria.py — Comprueba la MEMORIA (corto plazo + persistente) del modo local.

1. Turno 1: se presenta ("me llamo … y me gusta …")
2. Turno 2: pregunta su nombre  → debe recordarlo (historial)
3. Muestra el estado de /api/memoria
4. Borra la memoria y repite la pregunta → ya no debe saberlo

Uso:  python test_memoria.py
"""

import json
import sys

import httpx

BASE = "http://127.0.0.1:8090"
SID = "test-memoria-python"


def turno(c: httpx.Client, texto: str) -> str:
    with c.stream("POST", BASE + "/api/local/turn/stream",
                  json={"text": texto, "persona": "default", "sid": SID}) as r:
        r.raise_for_status()
        reply = ""
        for linea in r.iter_lines():
            if linea.startswith("data: ") and '"done"' in linea:
                reply = json.loads(linea[6:]).get("reply") or ""
        return reply


def main():
    with httpx.Client(timeout=180) as c:
        print("[1] presentación")
        r1 = turno(c, "Hola, me llamo Alcides y me gusta el café con leche. Guárdalo.")
        print("   →", r1[:150])

        print("\n[2] pregunta de memoria (mismo sid)")
        r2 = turno(c, "¿Cómo me llamo y qué me gusta?")
        print("   →", r2[:200])
        ok_nombre = "alcides" in r2.lower()
        print("   ¿recuerda el nombre?:", "✅ SÍ" if ok_nombre else "❌ NO")

        info = c.get(BASE + "/api/memoria", params={"sid": SID}).json()
        print("\n[3] estado de memoria")
        print("   mensajes en historial:", len(info.get("historial", [])))
        print("   datos persistentes:", info.get("resumen", {}).get("datos_largo_plazo"))

        print("\n[4] borrar memoria y volver a preguntar")
        print("  ", c.delete(BASE + "/api/memoria", params={"sid": SID}).json().get("result"))
        r3 = turno(c, "¿Cómo me llamo?")
        print("   →", r3[:150])
        ok_borrado = "alcides" not in r3.lower()
        print("   ¿ya no lo recuerda?:", "✅ SÍ" if ok_borrado else "⚠️ lo sigue sabiendo")


if __name__ == "__main__":
    main()
