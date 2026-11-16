#!/usr/bin/env python3
"""
Reachy Mini Web Console — proyecto real.

Una consola web que habla con el MISMO backend realtime que usa el robot:
  · Asigna sesión real en el endpoint del Reachy Mini Conversation App
  · WebSocket OpenAI-Realtime (texto → voz TTS + transcript)
  · Personalidades reales del repo (default / mars_rover / noir_detective)
  · Tool-loop real: 5 Tool Spaces MCP + 2 tools propias del proyecto

Ejecutar:  python server.py        →  http://127.0.0.1:8090
"""

import asyncio
import base64
import contextlib
import io
import json
import os
import pathlib
import random
import sys
import wave

# Consola/redirecciones de Windows (cp1252) no soportan emojis → forzar UTF-8
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                                       # noqa: BLE001
        pass

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from openai import AsyncOpenAI

APP_DIR = pathlib.Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"

ALLOCATOR_URL = "https://pollen-robotics-reachy-mini-realtime-url.hf.space/session"
HOST = os.getenv("REACHY_HOST", "127.0.0.1")
try:
    PORT = int(os.getenv("REACHY_PORT", "8090"))
except ValueError:
    PORT = 8090

# ── Tool Spaces reales del app ────────────────────────────────────────────────
MCP_TOOLS = {
    "pollen_robotics_reachy_mini_weather_tool__get_weather": {
        "space": "pollen-robotics/reachy-mini-weather-tool", "fn": "get_weather",
        "params": [("location", "")],
        "desc": "Get today's weather for a place: conditions, high/low, rain chance.",
    },
    "pollen_robotics_reachy_mini_time_tool__get_time": {
        "space": "pollen-robotics/reachy-mini-time-tool", "fn": "get_time",
        "params": [("timezone", ""), ("compare_timezone", "")],
        "desc": "Current date/time for an IANA timezone, optionally compared with another.",
    },
    "pollen_robotics_reachy_mini_search_tool__search_web": {
        "space": "pollen-robotics/reachy-mini-search-tool", "fn": "search_web",
        "params": [("query", ""), ("max_results", 5)],
        "desc": "Search the web and return a short list of results (title, snippet, url).",
    },
    "pollen_robotics_reachy_mini_knowledge_tool__get_info": {
        "space": "pollen-robotics/reachy-mini-knowledge-tool", "fn": "get_info",
        "params": [("topic", "")],
        "desc": "Info about a Pollen Robotics product or company: capabilities, versions, prices.",
    },
    "pollen_robotics_reachy_mini_knowledge_tool__search_docs": {
        "space": "pollen-robotics/reachy-mini-knowledge-tool", "fn": "search_docs",
        "params": [("query", "")],
        "desc": "Search the Reachy Mini FAQ and troubleshooting docs.",
    },
    # ── Nuestro MCP publicado en Hugging Face (10 tools) ─────────────────────
    #    Space: https://huggingface.co/spaces/Alcides777/reachy-mcp-tool
    "reachy_mcp__wiki_resumen": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "wiki_resumen",
        "params": [("tema", "")],
        "desc": "Resumen real de Wikipedia en español sobre un tema.",
    },
    "reachy_mcp__clima": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "clima",
        "params": [("ciudad", "")],
        "desc": "Clima actual y pronóstico de hoy en una ciudad (Open-Meteo real).",
    },
    "reachy_mcp__monedas": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "monedas",
        "params": [("desde", "USD"), ("hacia", "EUR"), ("cantidad", 1.0)],
        "desc": "Convierte importes entre monedas con tipos de cambio del BCE.",
    },
    "reachy_mcp__traducir": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "traducir",
        "params": [("texto", ""), ("destino", "en"), ("origen", "es")],
        "desc": "Traduce un texto a otro idioma.",
    },
    "reachy_mcp__calculadora": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "calculadora",
        "params": [("expresion", "")],
        "desc": "Calcula una expresión aritmética de forma segura.",
    },
    "reachy_mcp__convertir_unidades": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "convertir_unidades",
        "params": [("valor", 0.0), ("desde", "c"), ("hacia", "f")],
        "desc": "Convierte temperatura, longitud, masa o volumen.",
    },
    "reachy_mcp__hora_en": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "hora_en",
        "params": [("zona", "")],
        "desc": "Hora actual en una zona horaria IANA.",
    },
    "reachy_mcp__curiosidad": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "curiosidad",
        "params": [],
        "desc": "Devuelve una curiosidad aleatoria y sorprendente.",
    },
    "reachy_mcp__chiste": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "chiste",
        "params": [],
        "desc": "Cuenta un chiste corto.",
    },
    "reachy_mcp__dado": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "dado",
        "params": [("caras", 6)],
        "desc": "Tira un dado de N caras.",
    },
    "reachy_mcp__noticias": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "noticias",
        "params": [("tema", "")],
        "desc": "Últimas noticias en vivo (Google News) sobre un tema o titulares generales.",
    },
    "reachy_mcp__cripto": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "cripto",
        "params": [("moneda", "bitcoin")],
        "desc": "Precio de una criptomoneda en USD/EUR con variación 24h (CoinGecko).",
    },
    "reachy_mcp__deportes": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "deportes",
        "params": [("liga", "laliga")],
        "desc": "Marcadores de hoy en una liga (ESPN): laliga, premier, nba, nfl…",
    },
    "reachy_mcp__sismos": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "sismos",
        "params": [("min_magnitud", 4.0)],
        "desc": "Sismos recientes con magnitud ≥ umbral (USGS, última semana).",
    },
    # ── Visión / OCR (vía puente local, necesita token de Inference) ─────────
    "reachy_mcp__ocr_imagen": {
        "base": "http://127.0.0.1:8091", "fn": "ocr_imagen",
        "params": [("imagen", "")],
        "desc": "Extrae el texto de una imagen (URL http(s) o base64) usando un VLM.",
    },
    "reachy_mcp__describir_imagen": {
        "base": "http://127.0.0.1:8091", "fn": "describir_imagen",
        "params": [("imagen", "")],
        "desc": "Describe en una frase qué se ve en una imagen (URL http(s) o base64).",
    },
    "reachy_mcp__preguntar_imagen": {
        "base": "http://127.0.0.1:8091", "fn": "preguntar_imagen",
        "params": [("imagen", ""), ("pregunta", "")],
        "desc": "Responde una pregunta sobre una imagen (URL http(s) o base64).",
    },
    # ── Más datos en vivo (v1.4) ────────────────────────────────────────────
    "reachy_mcp__calidad_aire": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "calidad_aire",
        "params": [("ciudad", "")],
        "desc": "Calidad del aire actual (AQI, PM2.5, PM10) de una ciudad.",
    },
    "reachy_mcp__receta": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "receta",
        "params": [("plato", "")],
        "desc": "Busca una receta con ingredientes y pasos.",
    },
    "reachy_mcp__foto_mascota": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "foto_mascota",
        "params": [("animal", "perro")],
        "desc": "URL de una foto aleatoria de perro o gato (para las tools de visión).",
    },
    "reachy_mcp__leer_web": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "leer_web",
        "params": [("url", "")],
        "desc": "Lee una página web y devuelve su texto visible.",
    },
    "reachy_mcp__clasificacion": {
        "space": "Alcides777/reachy-mcp-tool", "fn": "clasificacion",
        "params": [("liga", "laliga")],
        "desc": "Clasificación de una liga de fútbol (laliga, premier, seriea…).",
    },
    # ── Escritura (notas): vía puente local para que persistan en tu equipo ─
    "reachy_mcp__escribir_nota": {
        "base": "http://127.0.0.1:8091", "fn": "escribir_nota",
        "params": [("titulo", ""), ("contenido", "")],
        "desc": "Escribe una nota/documento en disco y devuelve la ruta.",
    },
    "reachy_mcp__leer_nota": {
        "base": "http://127.0.0.1:8091", "fn": "leer_nota",
        "params": [("titulo", "")],
        "desc": "Lee una nota guardada por su título.",
    },
    "reachy_mcp__listar_notas": {
        "base": "http://127.0.0.1:8091", "fn": "listar_notas",
        "params": [],
        "desc": "Lista las notas guardadas con tamaño y fecha.",
    },
    "reachy_mcp__borrar_nota": {
        "base": "http://127.0.0.1:8091", "fn": "borrar_nota",
        "params": [("titulo", "")],
        "desc": "Borra una nota guardada por su título.",
    },
}

# ── Tools PROPIAS de este proyecto (equivalente a un Tool Space propio) ──────
CUSTOM_TOOLS = {
    "flip_coin": {
        "params": [("count", 1)],
        "desc": "Lanza una o más monedas y devuelve cara/cruz.",
        "schema": {"type": "object", "properties": {"count": {"type": "integer", "default": 1}}},
    },
    "roll_dice": {
        "params": [("sides", 6)],
        "desc": "Tira un dado de N caras (por defecto 6).",
        "schema": {"type": "object", "properties": {"sides": {"type": "integer", "default": 6}}},
    },
}


def tool_specs() -> list[dict]:
    def _tipo(default):
        if isinstance(default, bool):
            return "boolean"
        if isinstance(default, int):
            return "integer"
        if isinstance(default, float):
            return "number"
        return "string"

    tools = []
    for name, t in MCP_TOOLS.items():
        props = {}
        for p, d in t["params"]:
            props[p] = {"type": _tipo(d)}
        tools.append({
            "type": "function", "name": name, "description": t["desc"],
            "parameters": {"type": "object", "properties": props},
        })
    for name, t in CUSTOM_TOOLS.items():
        tools.append({
            "type": "function", "name": name, "description": t["desc"],
            "parameters": t["schema"],
        })
    return tools


# ── Personalidades (las de default son del repo; mars_rover/noir son reales) ─
_COHERENCIA = (
    " Sé coherente y factual: no inventes datos, cifras ni nombres. Si no sabes algo, "
    "dilo claramente. Responde en español, breve y ordenado."
)

PERSONALITIES = {
    "default": {
        "label": "Reachy (asistente)",
        "voice": "Aiden",
        "piper": "dave",
        "instructions": (
            "Eres Reachy Mini, un robot de escritorio alegre y conciso."
            " Responde en español, máximo dos frases. Usa las tools cuando te pidan "
            "datos concretos (clima, hora, búsqueda, información del producto)." + _COHERENCIA
        ),
    },
    "chef": {
        "label": "Chef (cocina)",
        "voice": "Serena",
        "piper": "claude",
        "instructions": (
            "Eres un chef simpático y algo exagerado. Das consejos de cocina y recetas en "
            "español, con entusiasmo y algún secreto culinario. Respuestas breves."
            " No inventes ingredientes reales que no existan ni tiempos absurdos." + _COHERENCIA
        ),
    },
    "profe": {
        "label": "Profe (enseña)",
        "voice": "Vivian",
        "piper": "sharvard0",
        "instructions": (
            "Eres un profesor paciente y claro. Explicas en español con ejemplos sencillos y "
            "preguntas de repaso. Respuestas breves y didácticas." + _COHERENCIA
        ),
    },
    "cuentista": {
        "label": "Cuentista (historias)",
        "voice": "Ono_Anna",
        "piper": "sharvard1",
        "instructions": (
            "Eres un narrador de cuentos. Inventas historias breves (4 a 6 frases) con inicio, "
            "nudo y final, en español, con tono cálido. Si piden un tema, inclúyelo. "
            "No mezcles personas reales con hechos inventados." + _COHERENCIA
        ),
    },
    "cientifico": {
        "label": "Científico (divulga)",
        "voice": "Eric",
        "piper": "ald",
        "instructions": (
            "Eres un divulgador científico. Explicas con claridad y precisión, en español, "
            "en máximo tres frases, con analogías sencillas. Si necesitas datos actuales, "
            "usa las tools." + _COHERENCIA
        ),
    },
    "viajero": {
        "label": "Viajero (planifica)",
        "voice": "Ryan",
        "piper": "dave",
        "instructions": (
            "Eres un asistente de viajes práctico. Para datos reales usa las tools: "
            "clima(ciudad), monedas(desde,hacia), hora_en(zona). Da consejos concretos y "
            "breves en español. No inventes horarios, precios ni distancias." + _COHERENCIA
        ),
    },
    "periodista": {
        "label": "Periodista (noticias)",
        "voice": "Dylan",
        "piper": "ald",
        "instructions": (
            "Eres un periodista breve y claro. Para actualidad usa la tool noticias(tema) y "
            "cita la fecha o la fuente que devuelve. Máximo tres frases en español. "
            "Si la tool no devuelve nada, dilo; no inventes titulares." + _COHERENCIA
        ),
    },
}


def get_token() -> str:
    token = (os.getenv("HF_TOKEN") or "").strip()
    if token:
        return token
    for p in (
        pathlib.Path.home() / ".cache" / "huggingface" / "token",
        pathlib.Path.home() / ".huggingface" / "token",
    ):
        if p.is_file():
            return p.read_text().strip()
    raise RuntimeError("Sin token HF: exporta HF_TOKEN o haz `hf auth login`.")


def allocate_session(token: str) -> dict:
    r = httpx.post(
        ALLOCATOR_URL,
        headers={
            "User-Agent": "reachy-mini-web-console",
            "X-Reachy-Mini-Authorization": f"Bearer {token}",
        },
        json={},
        timeout=20.0,
    )
    r.raise_for_status()
    return r.json()


def parse_connect_url(connect_url: str):
    from urllib.parse import urlsplit, parse_qsl

    p = urlsplit(connect_url)
    path = p.path.rstrip("/")
    has_realtime = path.endswith("/realtime")
    base_path = path[: -len("/realtime")] if has_realtime else path
    http_scheme = "https" if p.scheme in {"wss", "https"} else "http"
    ws_scheme = "wss" if p.scheme in {"wss", "https"} else "ws"
    query = {k: v for k, v in parse_qsl(p.query, keep_blank_values=True) if k != "model"}
    return f"{http_scheme}://{p.netloc}{base_path}", f"{ws_scheme}://{p.netloc}{base_path}", query


def call_mcp_tool(space: str, fn: str, data: list, timeout: float = 90.0, base: str | None = None):
    base_url = (base or f"https://{space.replace('/', '-')}.hf.space").rstrip("/") + "/gradio_api"
    with httpx.Client(timeout=timeout) as c:
        r = c.post(f"{base_url}/call/{fn}", json={"data": data})
        r.raise_for_status()
        ev = r.json()["event_id"]
        r = c.get(f"{base_url}/call/{fn}/{ev}")
        r.raise_for_status()
        for line in r.text.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
    return {"error": "sin datos"}


async def execute_tool(name: str, args: dict):
    """Ejecuta una tool (MCP real, MCP local o propia del proyecto).

    Si el puente local (:8091) no está disponible (p. ej. desplegado en un Space),
    ejecuta la tool en proceso importando tools_impl.
    """
    if name in MCP_TOOLS:
        t = MCP_TOOLS[name]
        data = [args.get(p, d) for p, d in t["params"]]
        base = t.get("base")
        try:
            return await asyncio.to_thread(
                call_mcp_tool, t.get("space", ""), t["fn"], data, 90.0, base
            )
        except Exception:                                   # noqa: BLE001
            if not base:
                raise
            import sys as _sys

            _sys.path.insert(0, str(APP_DIR / "mcp"))
            import tools_impl as _T

            return await asyncio.to_thread(_T.call_tool, t["fn"], args)
    if name == "flip_coin":
        n = int(args.get("count", 1) or 1)
        caras = [random.choice(["cara", "cruz"]) for _ in range(max(1, min(n, 10)))]
        return {"resultado": caras}
    if name == "roll_dice":
        sides = int(args.get("sides", 6) or 6)
        sides = max(2, min(sides, 100))
        return {"sides": sides, "resultado": random.randint(1, sides)}
    return {"error": f"tool desconocida: {name}"}


def pcm_to_wav_b64(pcm: bytes) -> str:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(pcm)
    return base64.b64encode(buf.getvalue()).decode()


class TurnState:
    def __init__(self):
        self.reset_turn()

    def reset_turn(self):
        self.transcript = []
        self.pcm = bytearray()
        self.tools = []
        self.pending = []      # (name, args_json, call_id)
        self.first_audio_at = None
        self.sent_at = None


app = FastAPI(title="Reachy Mini Web Console")

# ── Código de acceso opcional (para desplegar público sin quedar abierto) ────
ACCESS_CODE = (os.getenv("REACHY_ACCESS_CODE") or "").strip()


@app.middleware("http")
async def _gate(request, call_next):
    if not ACCESS_CODE:
        return await call_next(request)
    ruta = request.url.path
    if ruta in ("/", "/api/login", "/favicon.ico") or ruta.startswith("/tmpimg/") or ruta.startswith("/static"):
        return await call_next(request)
    codigo = request.headers.get("x-access-code") or request.cookies.get("reachy_code") or ""
    if codigo != ACCESS_CODE:
        return JSONResponse({"ok": False, "error": "código de acceso requerido"}, status_code=401)
    return await call_next(request)


@app.post("/api/login")
async def api_login(payload: dict):
    codigo = str((payload or {}).get("code") or "").strip()
    if not ACCESS_CODE or codigo == ACCESS_CODE:
        resp = JSONResponse({"ok": True})
        resp.set_cookie("reachy_code", codigo, httponly=True, samesite="lax", max_age=86400 * 30)
        return resp
    return JSONResponse({"ok": False, "error": "código incorrecto"}, status_code=401)


@app.get("/")
async def index():
    from fastapi import Response

    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return Response(
        content=html,
        media_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@app.get("/api/meta")
async def meta():
    voces_locales = []
    try:
        import local_pipeline as _lp

        voces_locales = _lp.voces_disponibles()
    except Exception:                                       # noqa: BLE001
        pass
    return JSONResponse({
        "personalities": [
            {"key": k, "label": v["label"], "voice": v["voice"], "piper": v.get("piper")}
            for k, v in PERSONALITIES.items()
        ],
        "local_voices": voces_locales,
        "tools": [{"name": n, "desc": t["desc"]} for n, t in {**MCP_TOOLS, **CUSTOM_TOOLS}.items()],
        "mic": True,
        "vision": True,
    })


async def _vision_call(payload: dict, fn_name: str):
    """OCR / caption por HF Inference API (token con permiso de Inference Providers)."""
    import base64 as _b64
    import vision as vision_mod

    b64 = (payload or {}).get("image") or ""
    if not b64:
        return JSONResponse({"ok": False, "error": "Falta la imagen (base64)."}, status_code=400)
    try:
        raw = _b64.b64decode(b64)
    except Exception:                                       # noqa: BLE001
        return JSONResponse({"ok": False, "error": "image no es base64 válido."}, status_code=400)
    try:
        fn = getattr(vision_mod, fn_name)
        out = await asyncio.to_thread(fn, raw)
        return {"ok": True, "result": out}
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": str(e)}


@app.post("/api/vision/ocr")
async def api_vision_ocr(payload: dict):
    return await _vision_call(payload, "ocr")


@app.post("/api/vision/caption")
async def api_vision_caption(payload: dict):
    return await _vision_call(payload, "caption")


# ── Modo LOCAL: ASR (HF router) + LLM con tools (HF router) + TTS (edge-tts) ─
@app.post("/api/local/turn")
async def api_local_turn(payload: dict):
    import base64 as _b64
    import time as _t
    import local_pipeline as LP

    payload = payload or {}
    persona = payload.get("persona") or "default"
    texto = (payload.get("text") or "").strip()
    audio_b64 = payload.get("audio") or ""
    t0 = _t.time()
    transcript = None
    try:
        if audio_b64:
            raw = _b64.b64decode(audio_b64)
            transcript = await asyncio.to_thread(LP.transcribir, raw, "es")
            texto = (transcript or "").strip()
        if not texto:
            return {"ok": False, "error": "No se entendió el audio o no hay texto."}
        out = await asyncio.to_thread(LP.responder, texto, persona)
        voz = (payload.get("voz") or "").strip() or LP.voz_piper_persona(persona)
        wav = await asyncio.to_thread(LP.sintetizar, out["reply"], voz)
        return {
            "ok": True,
            "transcript": transcript,
            "reply": out["reply"],
            "tools": out["tools"],
            "audio": _b64.b64encode(wav).decode() if wav else None,
            "latency_ms": int((_t.time() - t0) * 1000),
        }
    except Exception as e:                                  # noqa: BLE001
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


@app.get("/api/local/cache")
async def api_local_cache():
    import local_pipeline as LP

    return LP.cache_estado()


@app.post("/api/local/turn/stream")
async def api_local_turn_stream(payload: dict):
    """Modo local con STREAMING: frases + TTS por frase (SSE)."""
    import base64 as _b64
    import re as _re
    import threading as _threading
    import time as _t

    from fastapi.responses import StreamingResponse

    import local_pipeline as LP

    payload = payload or {}
    persona = payload.get("persona") or "default"
    texto = (payload.get("text") or "").strip()
    audio_b64 = payload.get("audio") or ""
    voz = (payload.get("voz") or "").strip() or LP.voz_piper_persona(persona)

    def sse(obj: dict) -> str:
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    async def gen():
        t0 = _t.time()
        primero_ms = None
        texto_local = texto
        if audio_b64:
            try:
                raw = _b64.b64decode(audio_b64)
                transcript = await asyncio.to_thread(LP.transcribir, raw, "es")
                yield sse({"type": "transcript", "text": transcript})
                texto_local = (transcript or "").strip()
            except Exception as e:                          # noqa: BLE001
                yield sse({"type": "error", "error": f"ASR: {e}"})
                return
        if not texto_local:
            yield sse({"type": "error", "error": "No se entendió el audio o no hay texto."})
            return

        loop = asyncio.get_running_loop()
        cola: asyncio.Queue = asyncio.Queue()

        def worker():
            try:
                for ev in LP.responder_stream(texto_local, persona):
                    loop.call_soon_threadsafe(cola.put_nowait, ev)
            except Exception as e:                          # noqa: BLE001
                loop.call_soon_threadsafe(cola.put_nowait, {"type": "error", "error": str(e)})
            finally:
                loop.call_soon_threadsafe(cola.put_nowait, {"type": "__end__"})

        _threading.Thread(target=worker, daemon=True).start()

        buffer = ""
        partes: list[str] = []
        tools: list[str] = []
        relleno_enviado = False
        tareas: list[tuple[str, asyncio.Task]] = []   # TTS en paralelo, se emiten en orden

        async def drenar(en_orden: bool = False):
            """Emite los audios ya sintetizados (en orden); si en_orden, espera al primero."""
            nonlocal primero_ms
            while tareas:
                frase, tarea = tareas[0]
                if not tarea.done():
                    if not en_orden:
                        break
                    await asyncio.shield(tarea)
                tareas.pop(0)
                try:
                    audio = tarea.result()
                except Exception:                            # noqa: BLE001
                    audio = b""
                if primero_ms is None:
                    primero_ms = int((_t.time() - t0) * 1000)
                yield sse({
                    "type": "sentence",
                    "text": frase,
                    "audio": _b64.b64encode(audio).decode() if audio else None,
                    "t_ms": int((_t.time() - t0) * 1000),
                })

        while True:
            ev = await cola.get()
            if ev.get("type") == "__end__":
                break
            if ev.get("type") == "error":
                yield sse({"type": "error", "error": ev.get("error")})
                return
            if ev.get("type") == "tool":
                tools.append(ev.get("name", ""))
                if primero_ms is None and not relleno_enviado:
                    # aún no ha sonado nada: decimos una frase corta (está en caché)
                    relleno_enviado = True
                    try:
                        audio = await asyncio.to_thread(
                            LP.sintetizar, LP.frase_relleno(persona), voz)
                    except Exception:                        # noqa: BLE001
                        audio = b""
                    if audio:
                        yield sse({"type": "audio", "audio": _b64.b64encode(audio).decode(),
                                   "filler": LP.frase_relleno(persona)})
                yield sse({"type": "tool", "name": ev.get("name", "")})
                continue
            if ev.get("type") == "texto":
                frag = ev.get("text", "")
                partes.append(frag)
                buffer += frag
                while True:
                    corte = -1
                    for k, ch in enumerate(buffer):
                        if ch in ".!?…" and (k + 1 == len(buffer) or buffer[k + 1].isspace()):
                            corte = k
                            break
                    if corte == -1:
                        break
                    frase = buffer[:corte + 1].strip()
                    buffer = buffer[corte + 1:].lstrip()
                    if len(frase) >= 2:
                        # lanza la síntesis en paralelo y va emitiendo las terminadas
                        tareas.append((frase, asyncio.create_task(
                            asyncio.to_thread(LP.sintetizar, frase, voz))))
                        async for chunk in drenar():
                            yield chunk
                continue
            if ev.get("type") == "final":
                if buffer.strip():
                    frase = buffer.strip()
                    buffer = ""
                    tareas.append((frase, asyncio.create_task(
                        asyncio.to_thread(LP.sintetizar, frase, voz))))
                async for chunk in drenar(en_orden=True):
                    yield chunk
                yield sse({
                    "type": "done",
                    "reply": "".join(partes).strip(),
                    "tools": tools,
                    "latency_ms": int((_t.time() - t0) * 1000),
                    "first_audio_ms": primero_ms,
                })
                return

        async for chunk in drenar(en_orden=True):
            yield chunk
        yield sse({"type": "done", "reply": "".join(partes).strip(), "tools": tools,
                   "latency_ms": int((_t.time() - t0) * 1000), "first_audio_ms": primero_ms})

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── Imágenes temporales para que el LLM pueda usarlas con las tools ─────────
_VISION_IMAGES: dict[str, tuple[bytes, str]] = {}


# ── Control de rate limit del asignador de sesiones (429 behavior_cooldown) ──
class RateLimited(Exception):
    """El asignador de sesiones nos pidió esperar (429)."""

    def __init__(self, retry_after: int):
        super().__init__(f"rate limited, espera {retry_after}s")
        self.retry_after = int(retry_after)


_COOLDOWN_UNTIL = 0.0


def _cooldown_restante() -> int:
    import time as _t

    return max(0, int(_COOLDOWN_UNTIL - _t.time()))


def _allocate_guarded(token: str) -> dict:
    """Asigna sesión respetando el cooldown global (no martillea el endpoint)."""
    global _COOLDOWN_UNTIL
    import time as _t

    restante = _cooldown_restante()
    if restante > 0:
        raise RateLimited(restante)
    try:
        return allocate_session(token)
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            retry = 90
            try:
                retry = int(e.response.json()["detail"]["retry_after_s"])
            except Exception:                               # noqa: BLE001
                ra = e.response.headers.get("retry-after")
                if ra and ra.isdigit():
                    retry = int(ra)
            _COOLDOWN_UNTIL = _t.time() + retry
            raise RateLimited(retry) from e
        raise


@app.post("/api/vision/upload")
async def api_vision_upload(payload: dict):
    import base64 as _b64
    import uuid as _uuid

    b64 = (payload or {}).get("image") or ""
    if not b64:
        return JSONResponse({"ok": False, "error": "Falta la imagen."}, status_code=400)
    try:
        raw = _b64.b64decode(b64)
    except Exception:                                       # noqa: BLE001
        return JSONResponse({"ok": False, "error": "base64 no válido."}, status_code=400)
    if len(raw) > 8 * 1024 * 1024:
        return JSONResponse({"ok": False, "error": "Imagen > 8 MB."}, status_code=400)
    mime = "image/png"
    if raw[:2] == b"\xff\xd8":
        mime = "image/jpeg"
    elif raw[:4] == b"RIFF":
        mime = "image/webp"
    img_id = _uuid.uuid4().hex
    _VISION_IMAGES[img_id] = (raw, mime)
    # URL pública: en un Space de HF usamos SPACE_HOST; en local, 127.0.0.1
    space_host = (os.getenv("SPACE_HOST") or "").strip()
    if space_host:
        base = f"https://{space_host}"
    elif (os.getenv("REACHY_HOST") or "127.0.0.1") in ("0.0.0.0", ""):
        base = f"http://127.0.0.1:{PORT}"
    else:
        base = f"http://{HOST}:{PORT}"
    return {"ok": True, "id": img_id, "url": f"{base}/tmpimg/{img_id}"}


@app.get("/tmpimg/{img_id}")
async def serve_tmpimg(img_id: str):
    from fastapi import Response

    item = _VISION_IMAGES.get(img_id)
    if not item:
        return JSONResponse({"error": "imagen no encontrada"}, status_code=404)
    return Response(content=item[0], media_type=item[1])


async def consume_events(conn, ws: WebSocket, state: TurnState):
    import time as _t
    async for ev in conn:
        et = ev.type
        if et == "input_audio_buffer.speech_started":
            await ws.send_json({"type": "speech_started"})
        elif et == "input_audio_buffer.speech_stopped":
            state.sent_at = _t.time()          # referencia para la latencia del turno de voz
            await ws.send_json({"type": "speech_stopped"})
        elif et == "conversation.item.input_audio_transcription.delta":
            await ws.send_json({"type": "user_partial", "text": ev.delta or ""})
        elif et == "conversation.item.input_audio_transcription.completed":
            await ws.send_json({"type": "user_transcript", "text": ev.transcript or ""})
        elif et == "response.function_call_arguments.done":
            state.pending.append((ev.name, ev.arguments or "{}", ev.call_id))
        elif et == "response.output_audio_transcript.delta":
            state.transcript.append(ev.delta or "")
            await ws.send_json({"type": "transcript_delta", "text": ev.delta or ""})
        elif et == "response.output_audio.delta":
            import time as _t
            if state.first_audio_at is None:
                state.first_audio_at = _t.time()
            state.pcm.extend(base64.b64decode(ev.delta))
        elif et == "response.done":
            if state.pending:
                for name, args_json, call_id in state.pending:
                    state.tools.append(name)
                    await ws.send_json({"type": "tool_call", "name": name, "args": args_json})
                    try:
                        args = json.loads(args_json or "{}")
                        result = await execute_tool(name, args)
                    except Exception as e:                     # noqa: BLE001
                        result = {"error": str(e)}
                    short = json.dumps(result, ensure_ascii=False)
                    await ws.send_json({"type": "tool_result", "name": name, "result": short[:600]})
                    await conn.conversation.item.create(item={
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": short,
                    })
                state.pending.clear()
                await conn.response.create()
            else:
                lat = None
                if state.first_audio_at and state.sent_at:
                    lat = round(state.first_audio_at - state.sent_at, 2)
                await ws.send_json({
                    "type": "turn_done",
                    "transcript": "".join(state.transcript).strip(),
                    "audio": pcm_to_wav_b64(bytes(state.pcm)) if state.pcm else None,
                    "tools": state.tools,
                    "latency_s": lat,
                })
        elif et == "error":
            err = getattr(ev, "error", None)
            await ws.send_json({
                "type": "error",
                "message": f"{getattr(err, 'code', '')}: {getattr(err, 'message', err)}",
            })


@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, personality: str = "default", voice: str | None = None):
    import time as _t

    if ACCESS_CODE and (ws.cookies.get("reachy_code") or "") != ACCESS_CODE:
        await ws.accept()
        await ws.send_json({"type": "error", "message": "código de acceso requerido"})
        await ws.close()
        return

    await ws.accept()
    persona = PERSONALITIES.get(personality, PERSONALITIES["default"])
    voice = voice or persona["voice"]
    state = TurnState()
    try:
        await ws.send_json({"type": "status", "text": "Asignando sesión realtime…"})
        token = get_token()
        try:
            alloc = await asyncio.to_thread(_allocate_guarded, token)
        except RateLimited as e:
            minutos = max(1, round(e.retry_after / 60))
            await ws.send_json({
                "type": "rate_limited",
                "retry_after": e.retry_after,
                "message": (
                    f"El servicio de sesiones de Hugging Face está limitando (429). "
                    f"Espera ~{minutos} min y vuelve a intentar. "
                    "Consejo: no tengas la app y la consola usando sesión a la vez."
                ),
            })
            return
        base_url, ws_url, query = parse_connect_url(alloc["connect_url"])
        client = AsyncOpenAI(api_key=token, base_url=base_url, websocket_base_url=ws_url)

        async with client.realtime.connect(extra_query=query) as conn:
            session_cfg = {
                "type": "realtime",
                "instructions": persona["instructions"],
                "audio": {
                    "input": {
                        "format": {"type": "audio/pcm", "rate": None},
                        "transcription": {"model": "gpt-4o-transcribe", "language": "es"},
                        # modo del robot: el servidor segmenta y responde solo
                        "turn_detection": {"type": "server_vad", "interrupt_response": True},
                    },
                    "output": {
                        "format": {"type": "audio/pcm", "rate": None},
                        "voice": voice,
                    },
                },
                "tools": tool_specs(),
                "tool_choice": "auto",
            }
            try:
                await conn.session.update(session=session_cfg)
            except Exception:
                # backend que no acepta turn_detection=None → sin VAD explícito
                session_cfg["audio"]["input"].pop("turn_detection", None)
                await conn.session.update(session=session_cfg)
            await ws.send_json({
                "type": "ready",
                "session_id": alloc.get("session_id"),
                "personality": personality,
                "voice": voice,
            })
            consumer = asyncio.create_task(consume_events(conn, ws, state))
            try:
                while True:
                    msg = await ws.receive_json()
                    mtype = msg.get("type")

                    if mtype == "user_text":
                        state.reset_turn()
                        state.sent_at = _t.time()
                        await conn.conversation.item.create(item={
                            "type": "message",
                            "role": "user",
                            "content": [{"type": "input_text", "text": msg["text"]}],
                        })
                        await conn.response.create()

                    elif mtype == "audio":
                        # trozos PCM16 16 kHz en base64 (micrófono del navegador)
                        b64 = msg.get("data")
                        if b64:
                            await conn.input_audio_buffer.append(audio=b64)

                    elif mtype == "commit":
                        # con server_vad el commit es automático; se tolera el manual
                        state.reset_turn()
                        state.sent_at = _t.time()
                        with contextlib.suppress(Exception):
                            await conn.input_audio_buffer.commit()
                        with contextlib.suppress(Exception):
                            await ws.send_json({"type": "turn_start", "source": "audio"})
            finally:
                consumer.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await consumer
    except WebSocketDisconnect:
        pass
    except Exception as e:                                  # noqa: BLE001
        with contextlib.suppress(Exception):
            await ws.send_json({"type": "error", "message": f"{type(e).__name__}: {e}"})
    finally:
        with contextlib.suppress(Exception):
            await ws.close()


if __name__ == "__main__":
    import threading

    import uvicorn

    def _calentar():
        try:
            import local_pipeline as _lp

            _lp.descargar_modelos_piper()   # en el Space: baja el modelo la 1ª vez
            _lp.calentar_tts()              # Piper + frases de relleno → TTS instantáneo
        except Exception:                                   # noqa: BLE001
            pass

    threading.Thread(target=_calentar, daemon=True).start()
    print(f"🎙️  Reachy Mini Web Console → http://{HOST}:{PORT}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")

