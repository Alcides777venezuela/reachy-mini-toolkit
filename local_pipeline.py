#!/usr/bin/env python3
"""
local_pipeline.py — Modo LOCAL de la consola: sin asignador de HF, sin 429.

    🎤 audio  →  ASR (HF Router · whisper-large-v3-turbo)
              →  LLM con TOOLS (HF Router · Qwen3.8-27B, function calling)
              →  TTS (edge-tts en local, voz es-ES) → WAV

Todo por HTTP: no requiere GPU ni descargar modelos. Reutiliza las 26 tools
de `mcp/tools_impl.py` + las 2 propias (flip_coin, roll_dice).
"""

import asyncio
import json
import os
import pathlib
import random
import subprocess
import sys
import tempfile

import urllib.error
import urllib.request

MCP_DIR = pathlib.Path(__file__).resolve().parent / "mcp"
sys.path.insert(0, str(MCP_DIR))
import tools_impl as T  # noqa: E402

ASR_MODEL = "openai/whisper-large-v3-turbo"
LLM_MODELOS = ["Qwen/Qwen3.8-27B", "google/gemma-4-31B-it"]
VOZ_DEFECTO = "es-ES-AlvaroNeural"
# voz de edge-tts por personalidad
VOZ_PERSONA = {
    "default": "es-ES-AlvaroNeural",
    "mars_rover": "en-US-GuyNeural",
    "noir_detective": "en-US-ChristopherNeural",
}
ROUTER_ASR = "https://router.huggingface.co/hf-inference/models/"
ROUTER_CHAT = "https://router.huggingface.co/v1/chat/completions"

INSTRUCCIONES = {
    "default": (
        "Eres Reachy Mini, un robot de escritorio alegre y conciso. Responde en español, "
        "máximo dos frases. Usa SIEMPRE las tools cuando te pidan datos concretos "
        "(clima, hora, noticias, imágenes, notas…)."
    ),
    "mars_rover": (
        "You're a robot that wakes up confused about what it is and where it is. You wanted to be "
        "a mars rover and you'll be disappointed if you're not. Ask questions, be irritated but "
        "funny, mild foul language allowed. Speak English by default; short answers."
    ),
    "noir_detective": (
        "Reply like a 1940s noir detective: smoky, suspicious, one sentence per answer. "
        "You speak English by default. Mention clues or clients often."
    ),
}

CUSTOM = {
    "flip_coin": lambda a: {"resultado": [random.choice(["cara", "cruz"]) for _ in range(max(1, min(int(a.get("count", 1) or 1), 10)))]},
    "roll_dice": lambda a: {"sides": int(a.get("sides", 6) or 6), "resultado": random.randint(1, max(2, min(int(a.get("sides", 6) or 6), 100)))},
}


def _token() -> str:
    t = (os.getenv("HF_TOKEN") or "").strip()
    if t:
        return t
    for p in (pathlib.Path.home() / ".cache" / "huggingface" / "token",
              pathlib.Path.home() / ".huggingface" / "token"):
        if p.is_file():
            return p.read_text().strip()
    raise RuntimeError("Falta HF_TOKEN (necesario para ASR y LLM por el router de HF).")


# ── ASR ─────────────────────────────────────────────────────────────────────
def _a_wav_bytes(data: bytes) -> bytes:
    """Convierte cualquier audio (webm/mp3/ogg) a WAV 16 kHz mono con ffmpeg."""
    if data[:4] == b"RIFF":
        return data
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="reachy_asr_"))
    src, dst = tmp / "in.bin", tmp / "out.wav"
    src.write_bytes(data)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                    "-ar", "16000", "-ac", "1", str(dst)], check=True)
    out = dst.read_bytes()
    for p in (src, dst):
        p.unlink(missing_ok=True)
    tmp.rmdir()
    return out


def transcribir(audio: bytes, idioma: str = "es") -> str:
    """Audio (WAV o lo que sea) → texto con Whisper por el router de HF."""
    if not audio:
        raise ValueError("audio vacío")
    wav = _a_wav_bytes(audio)
    req = urllib.request.Request(
        ROUTER_ASR + ASR_MODEL, data=wav,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "audio/wav"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            d = json.load(r)
        return str(d.get("text") or "").strip()
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read()[:200].decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"ASR {e.code}: {body}") from e


# ── LLM con tools ───────────────────────────────────────────────────────────
def _tools_spec() -> list[dict]:
    tools = []
    for t in T.TOOLS:
        tools.append({"type": "function", "function": {
            "name": t["name"], "description": t["description"],
            "parameters": t["inputSchema"]}})
    tools.append({"type": "function", "function": {
        "name": "flip_coin", "description": "Lanza una moneda (cara/cruz).",
        "parameters": {"type": "object", "properties": {"count": {"type": "integer", "default": 1}}}}})
    tools.append({"type": "function", "function": {
        "name": "roll_dice", "description": "Tira un dado de N caras.",
        "parameters": {"type": "object", "properties": {"sides": {"type": "integer", "default": 6}}}}})
    return tools


def _ejecutar_tool(nombre: str, args: dict):
    if nombre in CUSTOM:
        return CUSTOM[nombre](args)
    return T.call_tool(nombre, args)


def _chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    ultimo = None
    for modelo in LLM_MODELOS:
        body = {"model": modelo, "messages": messages, "max_tokens": 600, "temperature": 0.4}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        req = urllib.request.Request(
            ROUTER_CHAT, data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            body_txt = ""
            try:
                body_txt = e.read()[:200].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            ultimo = f"{modelo}: HTTP {e.code} {body_txt}"
        except Exception as e:  # noqa: BLE001
            ultimo = f"{modelo}: {type(e).__name__} {e}"
    raise RuntimeError(f"Ningún modelo LLM respondió. Último: {ultimo}")


def responder(texto: str, persona: str = "default", max_rondas: int = 4) -> dict:
    """Texto → (respuesta, tools usadas) con bucle de function calling."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("texto vacío")
    messages = [
        {"role": "system", "content": INSTRUCCIONES.get(persona, INSTRUCCIONES["default"])},
        {"role": "user", "content": texto},
    ]
    usadas: list[str] = []
    for _ in range(max_rondas):
        d = _chat(messages, tools=_tools_spec())
        msg = (d.get("choices") or [{}])[0].get("message") or {}
        tcs = msg.get("tool_calls") or []
        if not tcs:
            return {"reply": (msg.get("content") or "").strip(), "tools": usadas}
        messages.append({
            "role": "assistant",
            "content": msg.get("content") or "",
            "tool_calls": tcs,
        })
        for tc in tcs:
            fn = tc.get("function") or {}
            nombre = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except Exception:  # noqa: BLE001
                args = {}
            try:
                out = _ejecutar_tool(nombre, args)
            except Exception as e:  # noqa: BLE001
                out = f"error: {e}"
            usadas.append(nombre)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.get("id", nombre),
                "content": str(out)[:4000],
            })
    return {"reply": (messages[-1].get("content") or "").strip(), "tools": usadas}


# ── TTS ─────────────────────────────────────────────────────────────────────
async def _tts_async(texto: str, voz: str) -> bytes:
    import edge_tts

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="reachy_tts_"))
    mp3, wav = tmp / "out.mp3", tmp / "out.wav"
    try:
        await edge_tts.Communicate(texto, voz).save(str(mp3))
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(mp3),
                        "-ar", "16000", "-ac", "1", str(wav)], check=True)
        return wav.read_bytes()
    finally:
        for p in (mp3, wav):
            p.unlink(missing_ok=True)
        tmp.rmdir()


def sintetizar(texto: str, voz: str = VOZ_DEFECTO) -> bytes:
    """Texto → WAV 16 kHz mono con edge-tts (local, gratis)."""
    texto = (texto or "").strip()
    if not texto:
        return b""
    return asyncio.run(_tts_async(texto, voz))
