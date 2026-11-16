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

from datetime import datetime

from datetime import datetime

MCP_DIR = pathlib.Path(__file__).resolve().parent / "mcp"
sys.path.insert(0, str(MCP_DIR))
import tools_impl as T  # noqa: E402

ASR_MODEL = "openai/whisper-large-v3-turbo"
# Qwen: TTFT ~0.42 s · Kimi: ~0.70 s · Gemma: ~13 s (descartado como fallback)
LLM_MODELOS = ["Qwen/Qwen3.8-27B", "moonshotai/Kimi-K3"]
VOZ_DEFECTO = "es-ES-AlvaroNeural"

# ── Registro de voces locales (Piper) ───────────────────────────────────────
VOCES_PIPER: dict[str, dict] = {
    "dave":      {"label": "Dave · España (hombre)",      "modelo": "es_ES-davefx-medium"},
    "sharvard0": {"label": "Sharvard · España (voz A)",   "modelo": "es_ES-sharvard-medium", "speaker": 0},
    "sharvard1": {"label": "Sharvard · España (voz B)",   "modelo": "es_ES-sharvard-medium", "speaker": 1},
    "ald":       {"label": "Aldo · México (hombre)",      "modelo": "es_MX-ald-medium"},
    "claude":    {"label": "Claude · México (mujer)",     "modelo": "es_MX-claude-high"},
    "lessac":    {"label": "Lessac · EE.UU. (inglés)",    "modelo": "en_US-lessac-medium"},
}

# Voz local por defecto de cada personalidad
VOZ_PIPER_PERSONA = {
    "default": "dave",
    "chef": "claude",
    "profe": "sharvard0",
    "cuentista": "sharvard1",
    "cientifico": "ald",
    "viajero": "dave",
    "periodista": "ald",
}

# Voz de edge-tts / HF realtime por personalidad (respaldo)
VOZ_PERSONA = {
    "default": "es-ES-AlvaroNeural",
    "chef": "es-MX-DaliaNeural",
    "profe": "es-ES-ElviraNeural",
    "cuentista": "es-ES-ElviraNeural",
    "cientifico": "es-ES-AlvaroNeural",
    "viajero": "es-MX-JorgeNeural",
    "periodista": "es-MX-JorgeNeural",
}

ROUTER_ASR = "https://router.huggingface.co/hf-inference/models/"
ROUTER_CHAT = "https://router.huggingface.co/v1/chat/completions"

_COHERENCIA = (
    " Sé coherente y factual: no inventes datos, cifras ni nombres. Si no sabes algo, "
    "dilo claramente. Responde en español, breve y ordenado."
)

INSTRUCCIONES = {
    "default": (
        "Eres Reachy Mini, un robot de escritorio alegre y conciso. Responde en español, "
        "máximo dos frases. Usa SIEMPRE las tools cuando te pidan datos concretos "
        "(clima, hora, noticias, imágenes, notas…)." + _COHERENCIA
    ),
    "chef": (
        "Eres un chef simpático y algo exagerado. Das consejos de cocina y recetas en "
        "español, con entusiasmo y algún secreto culinario. Respuestas breves. "
        "No inventes ingredientes reales que no existan ni tiempos absurdos." + _COHERENCIA
    ),
    "profe": (
        "Eres un profesor paciente y claro. Explicas en español con ejemplos sencillos y "
        "preguntas de repaso. Respuestas breves y didácticas." + _COHERENCIA
    ),
    "cuentista": (
        "Eres un narrador de cuentos. Inventas historias breves (4 a 6 frases) con inicio, "
        "nudo y final, en español, con tono cálido. Si piden un tema, inclúyelo. "
        "No mezcles personas reales con hechos inventados." + _COHERENCIA
    ),
    "cientifico": (
        "Eres un divulgador científico. Explicas con claridad y precisión, en español, "
        "en máximo tres frases, con analogías sencillas. Si necesitas datos actuales, usa "
        "las tools." + _COHERENCIA
    ),
    "viajero": (
        "Eres un asistente de viajes práctico. Para datos reales usa las tools: "
        "clima(ciudad), monedas(desde,hacia), hora_en(zona). Da consejos concretos y breves "
        "en español. No inventes horarios, precios ni distancias." + _COHERENCIA
    ),
    "periodista": (
        "Eres un periodista breve y claro. Para actualidad usa la tool noticias(tema) y cita "
        "la fecha o la fuente que devuelve. Máximo tres frases en español. Si la tool no "
        "devuelve nada, dilo; no inventes titulares." + _COHERENCIA
    ),
}

CUSTOM = {
    "flip_coin": lambda a: {"resultado": [random.choice(["cara", "cruz"]) for _ in range(max(1, min(int(a.get("count", 1) or 1), 10)))]},
    "roll_dice": lambda a: {"sides": int(a.get("sides", 6) or 6), "resultado": random.randint(1, max(2, min(int(a.get("sides", 6) or 6), 100)))},
    "recordar": lambda a: memoria_recordar(a.get("dato", "")),
    "olvidar": lambda a: memoria_olvidar(a.get("dato", "")),
}

# ── MEMORIA: conversación (corto plazo) + datos persistentes (largo plazo) ──
MEM_DIR = pathlib.Path(os.getenv("REACHY_MEMORIA") or (pathlib.Path.home() / "reachy_memoria"))
HISTORIAL_MAX = 12        # mensajes que se envían al modelo
LARGO_PLAZO_MAX = 40      # datos persistidos


def _archivo_historial(sid: str) -> pathlib.Path:
    limpio = re.sub(r"[^A-Za-z0-9_-]", "", str(sid or ""))[:40] or "default"
    return MEM_DIR / f"conv_{limpio}.json"


def cargar_historial(sid: str) -> list[dict]:
    try:
        ruta = _archivo_historial(sid)
        if ruta.is_file():
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(datos, list):
                return datos[-HISTORIAL_MAX:]
    except Exception:  # noqa: BLE001
        pass
    return []


def guardar_historial(sid: str, mensajes: list[dict]) -> None:
    try:
        MEM_DIR.mkdir(parents=True, exist_ok=True)
        _archivo_historial(sid).write_text(
            json.dumps(mensajes[-HISTORIAL_MAX:], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except OSError:
        pass


def _archivo_largo() -> pathlib.Path:
    return MEM_DIR / "largo_plazo.json"


def cargar_largo_plazo() -> list[dict]:
    try:
        ruta = _archivo_largo()
        if ruta.is_file():
            datos = json.loads(ruta.read_text(encoding="utf-8"))
            if isinstance(datos, list):
                return datos
    except Exception:  # noqa: BLE001
        pass
    return []


def _guardar_largo_plazo(datos: list[dict]) -> None:
    try:
        MEM_DIR.mkdir(parents=True, exist_ok=True)
        _archivo_largo().write_text(
            json.dumps(datos[-LARGO_PLAZO_MAX:], ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
    except OSError:
        pass


def memoria_recordar(dato: str) -> str:
    """Guarda un dato en la memoria persistente (nickname, gustos, hechos…)."""
    dato = str(dato or "").strip()
    if not dato:
        return "Necesito el dato a recordar."
    datos = cargar_largo_plazo()
    if any(d.get("dato", "").lower() == dato.lower() for d in datos):
        return f"Ya lo tenía apuntado: {dato}"
    datos.append({"dato": dato, "ts": datetime.now().strftime("%Y-%m-%d %H:%M")})
    _guardar_largo_plazo(datos)
    return f"Recordado: {dato}"


def memoria_olvidar(dato: str) -> str:
    dato = str(dato or "").strip().lower()
    datos = cargar_largo_plazo()
    antes = len(datos)
    datos = [d for d in datos if dato not in d.get("dato", "").lower()]
    if len(datos) == antes:
        return f"No tenía nada apuntado sobre «{dato}»."
    _guardar_largo_plazo(datos)
    return f"Olvidado lo relacionado con «{dato}» ({antes - len(datos)} datos)."


def memoria_resumen() -> dict:
    """Estado de la memoria (para la UI)."""
    try:
        convs = [p.stem for p in MEM_DIR.glob("conv_*.json")] if MEM_DIR.is_dir() else []
    except OSError:
        convs = []
    return {
        "datos_largo_plazo": [d.get("dato") for d in cargar_largo_plazo()],
        "conversaciones": len(convs),
        "dir": str(MEM_DIR),
    }


def borrar_memoria(sid: str | None = None) -> str:
    """Borra la conversación (si se da sid) y/o los datos de largo plazo."""
    borrados = 0
    try:
        if sid:
            ruta = _archivo_historial(sid)
            if ruta.is_file():
                ruta.unlink()
                borrados += 1
        else:
            for p in MEM_DIR.glob("conv_*.json"):
                p.unlink()
                borrados += 1
        largo = _archivo_largo()
        if largo.is_file():
            largo.unlink()
    except OSError:
        pass
    return f"Memoria borrada ({borrados} conversación(es) + datos persistentes)."


def _system_prompt(persona: str) -> str:
    base = INSTRUCCIONES.get(persona, INSTRUCCIONES["default"])
    datos = cargar_largo_plazo()
    if datos:
        lista = "\n".join(f"- {d.get('dato')}" for d in datos[-12:])
        base += f"\n\nDatos que recuerdas del usuario (memoria persistente):\n{lista}"
    return base

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
    tools.append({"type": "function", "function": {
        "name": "recordar",
        "description": "Guarda un dato del usuario en la memoria PERSISTENTE (nombre, gustos, "
                       "preferencias, hechos importantes). Úsalo cuando te cuenten algo que debas "
                       "recordar en conversaciones futuras.",
        "parameters": {"type": "object", "properties": {"dato": {"type": "string"}},
                       "required": ["dato"]}}})
    tools.append({"type": "function", "function": {
        "name": "olvidar",
        "description": "Borra de la memoria persistente los datos que contengan ese texto.",
        "parameters": {"type": "object", "properties": {"dato": {"type": "string"}},
                       "required": ["dato"]}}})
    return tools


def _ejecutar_tool(nombre: str, args: dict):
    if nombre in CUSTOM:
        return CUSTOM[nombre](args)
    return T.call_tool(nombre, args)


def _chat(messages: list[dict], tools: list[dict] | None = None) -> dict:
    ultimo = None
    for modelo in LLM_MODELOS:
        body = {"model": modelo, "messages": messages, "max_tokens": 600, "temperature": 0.3}
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


def responder(texto: str, persona: str = "default", max_rondas: int = 4, sid: str = "default") -> dict:
    """Texto → (respuesta, tools usadas) con bucle de function calling y MEMORIA."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("texto vacío")
    historial = cargar_historial(sid)
    messages = [
        {"role": "system", "content": _system_prompt(persona)},
        *historial,
        {"role": "user", "content": texto},
    ]
    usadas: list[str] = []
    respuesta = ""
    for _ in range(max_rondas):
        d = _chat(messages, tools=_tools_spec())
        msg = (d.get("choices") or [{}])[0].get("message") or {}
        tcs = msg.get("tool_calls") or []
        if not tcs:
            respuesta = (msg.get("content") or "").strip()
            guardar_historial(sid, historial + [
                {"role": "user", "content": texto},
                {"role": "assistant", "content": respuesta},
            ])
            return {"reply": respuesta, "tools": usadas}
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


def voces_disponibles() -> list[dict]:
    """Voces Piper instaladas (para el selector de la UI)."""
    salida = []
    for clave, info in VOCES_PIPER.items():
        if (MODELOS_DIR / f"{info['modelo']}.onnx").is_file():
            salida.append({"key": clave, "label": info["label"]})
    return salida


def voz_piper_persona(persona: str) -> str:
    return VOZ_PIPER_PERSONA.get(persona, VOZ_PIPER_PERSONA["default"])


def _piper_para(voz: str):
    """Devuelve (PiperVoice, speaker_id) según la clave de voz o una voz edge-tts."""
    from piper import PiperVoice

    info = VOCES_PIPER.get(voz)
    if info is None:
        # compatibilidad: nombre de voz edge-tts → voz Piper equivalente
        idioma_es = not str(voz).lower().startswith("en")
        info = VOCES_PIPER["dave" if idioma_es else "lessac"]
    modelo = MODELOS_DIR / f"{info['modelo']}.onnx"
    if not modelo.is_file():
        modelo = PIPER_ES
    clave = str(modelo)
    if clave not in _piper_voces:
        _piper_voces[clave] = PiperVoice.load(clave)
    return _piper_voces[clave], info.get("speaker")


def _sintetizar_piper(texto: str, voz: str) -> bytes:
    import io
    import wave

    from piper import SynthesisConfig

    voice, speaker = _piper_para(voz)
    cfg = SynthesisConfig(speaker_id=speaker) if speaker is not None else None
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        if cfg is None:
            voice.synthesize_wav(texto, w)
        else:
            voice.synthesize_wav(texto, w, syn_config=cfg)
    return buf.getvalue()


def calentar_tts() -> None:
    """Carga el modelo Piper y pre-sintetiza (en caché) rellenos y saludos."""
    try:
        if piper_disponible():
            _sintetizar_piper("calentando", "es-ES-AlvaroNeural")
    except Exception:  # noqa: BLE001
        pass
    calentar_cache()


def descargar_modelos_piper() -> None:
    """Descarga las voces Piper que falten (útil en el contenedor del Space)."""
    bases = {
        "es_ES-davefx-medium": "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/davefx/medium/es_ES-davefx-medium",
        "es_ES-sharvard-medium": "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium/es_ES-sharvard-medium",
        "es_MX-ald-medium": "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_MX/ald/medium/es_MX-ald-medium",
        "es_MX-claude-high": "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_MX/claude/high/es_MX-claude-high",
        "en_US-lessac-medium": "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium/en_US-lessac-medium",
    }
    MODELOS_DIR.mkdir(parents=True, exist_ok=True)
    for nombre, base in bases.items():
        for ext in (".onnx", ".onnx.json"):
            destino = MODELOS_DIR / f"{nombre}{ext}"
            if destino.is_file():
                continue
            try:
                req = urllib.request.Request(f"{base}{ext}",
                                             headers={"User-Agent": "reachy-web-console"})
                with urllib.request.urlopen(req, timeout=300) as r, open(destino, "wb") as f:
                    while True:
                        trozo = r.read(1 << 20)
                        if not trozo:
                            break
                        f.write(trozo)
            except Exception:  # noqa: BLE001
                destino.unlink(missing_ok=True)


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
                "temperature": 0.3, "stream": True}
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


def responder_stream(texto: str, persona: str = "default", max_rondas: int = 4, sid: str = "default"):
    """Generador: emite {"type":"texto"} por fragmento, {"type":"tool"} y {"type":"final"}.

    Mantiene MEMORIA: carga el historial previo de la conversación (sid) y lo guarda al final.
    """
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("texto vacío")
    historial = cargar_historial(sid)
    messages = [
        {"role": "system", "content": _system_prompt(persona)},
        *historial,
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
        guardar_historial(sid, historial + [
            {"role": "user", "content": texto},
            {"role": "assistant", "content": respuesta},
        ])
        yield {"type": "final", "reply": respuesta, "tools": usadas}
        return
    yield {"type": "final", "reply": "", "tools": usadas}


