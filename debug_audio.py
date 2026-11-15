#!/usr/bin/env python3
"""
debug_audio.py — Diagnóstico del camino de VOZ (backend directo, sin consola).

Prueba las dos configuraciones de input audio:
  · server_vad    (modo del robot: el servidor segmenta y responde solo)
  · manual commit (push-to-talk)

Muestra TODOS los tipos de evento recibidos para ver si llega la transcripción.

Uso:  python debug_audio.py            (server_vad)
      python debug_audio.py commit     (commit manual)
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

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / 'reachy-ejemplo'))
import realtime_chat as rc   # reutiliza asignador + parse + escritura WAV
from openai import AsyncOpenAI

VOZ = "es-ES-AlvaroNeural"


async def generar_pcm(texto: str) -> bytes:
    tmp = pathlib.Path(tempfile.gettempdir())
    mp3, pcm = tmp / "dbg.mp3", tmp / "dbg.pcm"
    await edge_tts.Communicate(texto, VOZ).save(str(mp3))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                    "-f", "s16le", "-ac", "1", "-ar", "16000", str(pcm)], check=True)
    return pcm.read_bytes()


async def probar(modo: str, texto: str):
    pcm = await generar_pcm(texto)
    print(f"[audio] {len(pcm)} bytes = {len(pcm)/32000:.2f}s  modo={modo}")

    tok = rc.get_token()
    alloc = rc.allocate_session(tok)
    base_url, ws_url, query = rc.parse_connect_url(alloc["connect_url"])
    client = AsyncOpenAI(api_key=tok, base_url=base_url, websocket_base_url=ws_url)

    input_cfg = {
        "format": {"type": "audio/pcm", "rate": None},
        "transcription": {"model": "gpt-4o-transcribe", "language": "es"},
    }
    if modo == "server_vad":
        input_cfg["turn_detection"] = {"type": "server_vad", "interrupt_response": True}
    else:
        input_cfg["turn_detection"] = None

    transcript_user = None
    respuesta = []
    tipos = {}

    async with client.realtime.connect(extra_query=query) as conn:
        await conn.session.update(session={
            "type": "realtime",
            "instructions": "Eres Reachy Mini. Responde en español, breve. Usa tools si hace falta.",
            "audio": {"input": input_cfg, "output": {"voice": "Aiden"}},
        })
        print("[conn] sesión configurada")

        async def enviar():
            CH = 3200                      # 100 ms
            for i in range(0, len(pcm), CH):
                await conn.input_audio_buffer.append(audio=base64.b64encode(pcm[i:i+CH]).decode())
                await asyncio.sleep(0.1)   # ritmo real
            if modo == "commit":
                await conn.input_audio_buffer.commit()
                await conn.response.create()
                print("[audio] commit + response.create")

        tarea = asyncio.create_task(enviar())
        t0 = time.time()
        try:
            async for ev in conn:
                et = ev.type
                tipos[et] = tipos.get(et, 0) + 1
                if et == "conversation.item.input_audio_transcription.completed":
                    transcript_user = ev.transcript
                    print(f"  🎤 STT → «{transcript_user}»")
                elif et == "conversation.item.input_audio_transcription.delta":
                    pass
                elif et == "response.output_audio_transcript.delta":
                    respuesta.append(ev.delta or "")
                elif et == "response.done":
                    print("  ✅ response.done")
                    break
                elif et == "error":
                    err = getattr(ev, "error", None)
                    print(f"  ⚠️ error {getattr(err,'code','')}: {getattr(err,'message',err)}")
                if time.time() - t0 > 90:
                    print("  ⏱ timeout"); break
        finally:
            tarea.cancel()
    print("\n[eventos]")
    for k, v in sorted(tipos.items()):
        print(f"   {v:3}× {k}")
    print(f"\n[resultado] STT={transcript_user!r}")
    print(f"[resultado] respuesta={''.join(respuesta)[:200]!r}")


if __name__ == "__main__":
    modo = sys.argv[1] if len(sys.argv) > 1 and sys.argv[1] in ("server_vad", "commit") else "server_vad"
    texto = " ".join(sys.argv[2:]) or "Hola Reachy, dime qué tiempo hace en Caracas."
    asyncio.run(asyncio.wait_for(probar(modo, texto), timeout=150))

