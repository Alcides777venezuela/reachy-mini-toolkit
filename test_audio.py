#!/usr/bin/env python3
"""
test_audio.py — Prueba del camino MICRÓFONO: voz real → PCM16 16 kHz → backend.

Genera audio hablado con edge-tts (TTS gratis), lo convierte a PCM16 mono 16 kHz
con ffmpeg y lo envía por el WebSocket de la consola como lo haría el navegador
(trozos {"type":"audio"} + {"type":"commit"}).

Uso:  python test_audio.py "¿Qué tiempo hace en Caracas?"
"""

import asyncio
import base64
import json
import pathlib
import subprocess
import sys
import tempfile
import time

import edge_tts
import websockets

WS_URL = "ws://127.0.0.1:8090/ws/chat?personality=default&voice="
VOZ = "es-ES-AlvaroNeural"      # voz española de edge-tts


async def generar_pcm(texto: str) -> bytes:
    tmp = pathlib.Path(tempfile.gettempdir())
    mp3 = tmp / "test_voz.mp3"
    pcm = tmp / "test_voz.pcm"
    comm = edge_tts.Communicate(texto, VOZ)
    await comm.save(str(mp3))
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
         "-f", "s16le", "-ac", "1", "-ar", "16000", str(pcm)],
        check=True,
    )
    return pcm.read_bytes()


async def probar(texto: str):
    print(f"[1] Sintetizando voz: «{texto}»")
    pcm = await generar_pcm(texto)
    print(f"    PCM16 16 kHz: {len(pcm)} bytes ({len(pcm) / 32000:.2f} s)")

    async with websockets.connect(WS_URL, open_timeout=30) as ws:
        msg = json.loads(await ws.recv())
        if msg.get("type") == "status":
            msg = json.loads(await ws.recv())
        print(f"[2] Conectado: {msg.get('session_id')}")

        # enviar en tiempo real (100 ms por trozo) como el micrófono del navegador;
        # con server_vad el backend detecta el silencio y responde solo
        CHUNK = 3200
        t0 = time.time()
        for i in range(0, len(pcm), CHUNK):
            trozo = pcm[i:i + CHUNK]
            await ws.send(json.dumps({
                "type": "audio",
                "data": base64.b64encode(trozo).decode(),
            }))
            await asyncio.sleep(0.1)
        print(f"    audio enviado en tiempo real ({time.time() - t0:.2f}s) — esperando VAD")

        transcript_user = []
        partes = []
        tools = []
        while True:
            m = json.loads(await asyncio.wait_for(ws.recv(), timeout=120))
            t = m.get("type")
            if t == "user_partial":
                transcript_user.append(m.get("text", ""))
            elif t == "user_transcript":
                print(f"[3] 🎤 STT → «{m.get('text')}»")
            elif t == "tool_call":
                tools.append(m["name"])
                print(f"    🛠️ {m['name'].split('__')[-1]} {m['args']}")
            elif t == "transcript_delta":
                partes.append(m.get("text", ""))
            elif t == "turn_done":
                audio = m.get("audio") or ""
                n = len(base64.b64decode(audio)) if audio else 0
                print(f"[4] 🔊 respuesta: «{m.get('transcript')}»")
                print(f"    tools={m.get('tools')} | audio={n}B ({n/32000:.1f}s) | "
                      f"1er audio={m.get('latency_s')}s")
                return True
            elif t == "error":
                print("[!] error:", m.get("message"))
                return False


if __name__ == "__main__":
    pregunta = " ".join(sys.argv[1:]) or "Hola Reachy, ¿qué tiempo hace en Caracas?"
    ok = asyncio.run(asyncio.wait_for(probar(pregunta), timeout=180))
    print("\nRESULTADO:", "✅ OK" if ok else "❌ FALLÓ")
