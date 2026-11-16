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
import hashlib
import json
import os
import pathlib
import random
import re
import subprocess
import sys
import tempfile

import urllib.error
import urllib.request

MCP_DIR = pathlib.Path(__file__).resolve().parent / "mcp"
sys.path.insert(0, str(MCP_DIR))
import tools_impl as T  # noqa: E402

ASR_MODEL = "openai/whisper-large-v3-turbo"
# Qwen: TTFT ~0.42 s · Kimi: ~0.70 s · Gemma: ~13 s (descartado como fallback)
LLM_MODELOS = ["Qwen/Qwen3.8-27B", "moonshotai/Kimi-K3"]
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

# Frase corta que se dice mientras las tools trabajan (latencia percibida ↓)
RELLENO = {
    "default": "Un momento…",
    "mars_rover": "Hold on…",
    "noir_detective": "One moment, kid…",
}


def frase_relleno(persona: str = "default") -> str:
    return RELLENO.get(persona, RELLENO["default"])


def calentar_cache() -> None:
    """Pre-sintetiza y guarda en caché las frases de relleno y saludos (arranque)."""
    for persona, frase in RELLENO.items():
        try:
            sintetizar(frase, VOZ_PERSONA.get(persona, VOZ_DEFECTO))
        except Exception:  # noqa: BLE001
            pass
    for frase in ("Hola, soy Reachy Mini.", "Listo.", "Claro que sí."):
        try:
            sintetizar(frase, VOZ_DEFECTO)
        except Exception:  # noqa: BLE001
            pass


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
    """Texto → WAV mono, con CACHÉ en disco.

    Motor: **Piper** local si el modelo está disponible (~0.6 s/frase, sin red),
    si no, **edge-tts** (~1.3 s/frase, requiere red). Seleccionable con REACHY_TTS.
    """
    texto = (texto or "").strip()
    if not texto:
        return b""
    motor = (os.getenv("REACHY_TTS") or "piper").strip().lower()
    ruta = _cache_path(texto, f"{motor}|{voz}")
    if ruta.is_file():
        try:
            return ruta.read_bytes()
        except OSError:
            pass
    data = b""
    if motor == "piper":
        try:
            data = _sintetizar_piper(texto, voz)
        except Exception:  # noqa: BLE001
            data = b""
    if not data:
        data = asyncio.run(_tts_async(texto, voz))
    if data:
        try:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            ruta.write_bytes(data)
            _limpiar_cache()
        except OSError:
            pass
    return data


# ── TTS local con Piper (rápido en CPU, sin red) ────────────────────────────
MODELOS_DIR = pathlib.Path(os.getenv("REACHY_MODELS") or (pathlib.Path.home() / "reachy_models"))
PIPER_ES = MODELOS_DIR / "es_ES-davefx-medium.onnx"
PIPER_EN = MODELOS_DIR / "en_US-lessac-medium.onnx"
_piper_voces: dict[str, object] = {}


def piper_disponible() -> bool:
    return PIPER_ES.is_file()


def _piper_para(voz: str):
    """Devuelve la PiperVoice según el idioma de la voz pedida (es-*/en-*)."""
    from piper import PiperVoice

    idioma = "en" if str(voz).lower().startswith("en") else "es"
    modelo = PIPER_EN if idioma == "en" else PIPER_ES
    if not modelo.is_file():
        modelo = PIPER_ES
    clave = str(modelo)
    if clave not in _piper_voces:
        _piper_voces[clave] = PiperVoice.load(clave)
    return _piper_voces[clave]


def _sintetizar_piper(texto: str, voz: str) -> bytes:
    import io
    import wave

    v = _piper_para(voz)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        v.synthesize_wav(texto, w)
    return buf.getvalue()


def calentar_tts() -> None:
    """Carga el modelo Piper y pre-sintetiza (en caché) rellenos y saludos."""
    try:
        if piper_disponible():
            _sintetizar_piper("calentando", "es-ES-AlvaroNeural")
    except Exception:  # noqa: BLE001
        pass
    calentar_cache()


# ── Caché de TTS ────────────────────────────────────────────────────────────
CACHE_DIR = pathlib.Path(os.getenv("REACHY_TTS_CACHE") or (pathlib.Path.home() / "reachy_tts_cache"))
CACHE_MAX = 400


def _cache_path(texto: str, voz: str) -> pathlib.Path:
    key = hashlib.sha256(f"{voz}|{texto}".encode("utf-8")).hexdigest()[:32]
    return CACHE_DIR / f"{key}.wav"


def _limpiar_cache() -> None:
    try:
        archivos = sorted(CACHE_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
        for viejo in archivos[CACHE_MAX:]:
            viejo.unlink(missing_ok=True)
    except OSError:
        pass


def cache_estado() -> dict:
    try:
        archivos = list(CACHE_DIR.glob("*.wav"))
        bytes_ = sum(p.stat().st_size for p in archivos)
        return {"archivos": len(archivos), "mb": round(bytes_ / 1e6, 2), "dir": str(CACHE_DIR), "max": CACHE_MAX}
    except OSError:
        return {"archivos": 0, "mb": 0.0, "dir": str(CACHE_DIR), "max": CACHE_MAX}


# ── LLM en streaming + frases ───────────────────────────────────────────────
def _chat_stream(messages: list[dict], tools: list[dict] | None = None):
    """Itera los chunks SSE del LLM (router HF). Reintenta con otro modelo si falla al inicio."""
    ultimo = None
    for modelo in LLM_MODELOS:
        body = {"model": modelo, "messages": messages, "max_tokens": 600,
                "temperature": 0.4, "stream": True}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        req = urllib.request.Request(
            ROUTER_CHAT, data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"},
        )
        emitido = False
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                for raw in r:
                    linea = raw.decode("utf-8", "replace").strip()
                    if not linea.startswith("data: "):
                        continue
                    payload = linea[len("data: "):]
                    if payload.strip() == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload)
                    except Exception:  # noqa: BLE001
                        continue
                    emitido = True
                    yield chunk
            return
        except urllib.error.HTTPError as e:
            if emitido:
                raise
            body_txt = ""
            try:
                body_txt = e.read()[:200].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            ultimo = f"{modelo}: HTTP {e.code} {body_txt}"
        except Exception as e:  # noqa: BLE001
            if emitido:
                raise
            ultimo = f"{modelo}: {type(e).__name__} {e}"
    raise RuntimeError(f"Ningún modelo LLM respondió (stream). Último: {ultimo}")


_SPLIT_FRASES = re.compile(r"(?<=[.!?…])\s+|\n+")


def dividir_frases(texto: str, minimo: int = 12) -> list[str]:
    """Divide un texto en frases aptas para TTS."""
    out: list[str] = []
    for parte in _SPLIT_FRASES.split(texto or ""):
        parte = (parte or "").strip()
        if not parte:
            continue
        if out and len(parte) < minimo:
            out[-1] = (out[-1] + " " + parte).strip()
        else:
            out.append(parte)
    return out


def responder_stream(texto: str, persona: str = "default", max_rondas: int = 4):
    """Generador: emite {"type":"texto"} por fragmento, {"type":"tool"} y {"type":"final"}."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("texto vacío")
    messages = [
        {"role": "system", "content": INSTRUCCIONES.get(persona, INSTRUCCIONES["default"])},
        {"role": "user", "content": texto},
    ]
    usadas: list[str] = []
    for _ in range(max_rondas):
        acumulado: list[str] = []
        tool_acc: dict[int, dict] = {}
        for chunk in _chat_stream(messages, tools=_tools_spec()):
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            frag = delta.get("content")
            if frag:
                acumulado.append(frag)
                yield {"type": "texto", "text": frag}
            for tc in delta.get("tool_calls") or []:
                i = tc.get("index", 0)
                slot = tool_acc.setdefault(i, {"id": "", "name": "", "args": ""})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                if fn.get("name"):
                    slot["name"] = fn["name"]
                if fn.get("arguments"):
                    slot["args"] += fn["arguments"]

        respuesta = "".join(acumulado).strip()
        if tool_acc:
            calls = [tool_acc[k] for k in sorted(tool_acc)]
            messages.append({
                "role": "assistant",
                "content": respuesta,
                "tool_calls": [
                    {"id": c["id"] or f"call_{i}", "type": "function",
                     "function": {"name": c["name"], "arguments": c["args"] or "{}"}}
                    for i, c in enumerate(calls)
                ],
            })

            def _uno(c):
                try:
                    args = json.loads(c["args"] or "{}")
                except Exception:  # noqa: BLE001
                    args = {}
                try:
                    return c, _ejecutar_tool(c["name"], args)
                except Exception as e:  # noqa: BLE001
                    return c, f"error: {e}"

            # ejecutamos las tools EN PARALELO (cada una es I/O de red)
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=min(4, len(calls) or 1)) as pool:
                futuros = [pool.submit(_uno, c) for c in calls]
                for fut in futuros:
                    c, out = fut.result()
                    usadas.append(c["name"])
                    yield {"type": "tool", "name": c["name"]}
                    messages.append({
                        "role": "tool",
                        "tool_call_id": c["id"] or c["name"],
                        "content": str(out)[:4000],
                    })
            continue
        yield {"type": "final", "reply": respuesta, "tools": usadas}
        return
    yield {"type": "final", "reply": "", "tools": usadas}
