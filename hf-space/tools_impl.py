#!/usr/bin/env python3
"""
tools_impl.py — Implementación compartida de las tools del MCP (10 tools).

La usan:
  · mcp/mcp_server.py   (servidor MCP stdio)
  · mcp/mcp_http.py     (puente HTTP para la consola)
  · hf-space/app.py     (Space de Hugging Face publicado)

Solo stdlib: corre igual en Windows, Linux y en el Space.
"""

import ast
import base64
import json
import math
import operator
import os
import pathlib
import random
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

UA = {"User-Agent": "reachy-mcp/1.1 (demo)"}

CURIOSIDADES = [
    "Los pulpos tienen tres corazones y sangre azul.",
    "Un rayo es unas cinco veces más caliente que la superficie del Sol.",
    "Los plátanos son técnicamente bayas, y las fresas no lo son.",
    "La miel nunca caduca: se ha encontrado comestible en tumbas egipcias.",
    "Los astronautas crecen hasta 5 cm en el espacio por falta de gravedad.",
    "El corazón de un colibrí late más de 1.000 veces por minuto.",
    "Venus gira al revés: allí el Sol sale por el oeste.",
    "Las hormigas no tienen pulmones; respiran por espiráculos.",
    "El sonido no viaja en el espacio: nadie te oiría gritar.",
    "Los gatos pasan el 70 % de su vida durmiendo.",
    "Un día en Mercurio dura 59 días terrestres, pero un año solo 88.",
    "El tiburón de Groenlandia puede vivir más de 400 años.",
]

CHISTES = [
    "¿Qué le dice un bit a otro? Nos vemos en el bus.",
    "¿Por qué los programadores confunden Halloween con Navidad? Porque OCT 31 = DEC 25.",
    "Un robot entra a un bar. El camarero: «¿Qué le pongo?» El robot: «Carga, por favor.»",
    "¿Cómo se despiden dos ordenadores? «Te dejo, que tengo que procesar algo.»",
    "Mi wifi y yo tenemos una relación abierta: se conecta con todos.",
    "¿Qué hace una abeja en el gimnasio? ¡Zum-baaa!",
]

WEATHER_CODES = {
    0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado",
    45: "niebla", 48: "niebla con escarcha", 51: "llovizna ligera", 53: "llovizna",
    55: "llovizna intensa", 61: "lluvia ligera", 63: "lluvia", 65: "lluvia fuerte",
    71: "nieve ligera", 73: "nieve", 75: "nieve fuerte", 80: "chubascos",
    81: "chubascos fuertes", 82: "chubascos torrenciales", 95: "tormenta",
    96: "tormenta con granizo", 99: "tormenta fuerte con granizo",
}


def _get_json(url: str, params: dict | None = None, timeout: int = 20):
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


# ── 1. Wikipedia ─────────────────────────────────────────────────────────────
def wiki_resumen(tema: str) -> str:
    """Resumen de Wikipedia en español sobre un tema.

    Devuelve la introducción del artículo para el tema pedido.
    """
    tema = str(tema or "").strip()
    if not tema:
        return "Necesito un tema para buscar en Wikipedia."
    try:
        data = _get_json("https://es.wikipedia.org/w/api.php", {
            "action": "query", "format": "json", "prop": "extracts",
            "exintro": 1, "explaintext": 1, "redirects": 1, "titles": tema,
        })
    except Exception as e:                                  # noqa: BLE001
        return f"No pude consultar Wikipedia ({type(e).__name__})."
    pages = (data.get("query") or {}).get("pages") or {}
    page = next(iter(pages.values()), {})
    if "missing" in page:
        return f"No encontré un artículo de Wikipedia para «{tema}»."
    extract = " ".join((page.get("extract") or "").split())
    if not extract:
        return f"Wikipedia no tiene resumen para «{tema}»."
    return f"{page.get('title', tema)}: {extract[:700]}"


# ── 2. Clima (Open-Meteo, gratis sin key) ────────────────────────────────────
def clima(ciudad: str) -> str:
    """Clima actual y pronóstico de hoy para una ciudad.

    Usa Open-Meteo (geocodificación + forecast), dato real en tiempo real.
    """
    ciudad = str(ciudad or "").strip()
    if not ciudad:
        return "Necesito una ciudad. Ej: «Caracas»."
    try:
        geo = _get_json("https://geocoding-api.open-meteo.com/v1/search",
                        {"name": ciudad, "count": 1, "language": "es"})
    except Exception as e:                                  # noqa: BLE001
        return f"No pude geocodificar «{ciudad}» ({type(e).__name__})."
    results = geo.get("results") or []
    if not results:
        return f"No encontré la ciudad «{ciudad}»."
    g = results[0]
    lat, lon = g["latitude"], g["longitude"]
    lugar = ", ".join(x for x in [g.get("name"), g.get("admin1"), g.get("country")] if x)
    try:
        fc = _get_json("https://api.open-meteo.com/v1/forecast", {
            "latitude": lat, "longitude": lon,
            "current": "temperature_2m,relative_humidity_2m,weather_code,wind_speed_10m",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "auto", "forecast_days": 1,
        })
    except Exception as e:                                  # noqa: BLE001
        return f"No pude obtener el clima de {lugar} ({type(e).__name__})."
    cur = fc.get("current") or {}
    day = (fc.get("daily") or {})
    desc = WEATHER_CODES.get(int(cur.get("weather_code", 0)), "sin datos")
    tmax = (day.get("temperature_2m_max") or [None])[0]
    tmin = (day.get("temperature_2m_min") or [None])[0]
    rain = (day.get("precipitation_probability_max") or [None])[0]
    return (f"{lugar}: {desc}, {cur.get('temperature_2m')}°C ahora "
            f"(máx {tmax}°C / mín {tmin}°C), humedad {cur.get('relative_humidity_2m')}%, "
            f"viento {cur.get('wind_speed_10m')} km/h, lluvia {rain}%.")


# ── 3. Monedas (Frankfurter / BCE, gratis sin key) ───────────────────────────
def monedas(desde: str, hacia: str, cantidad: float = 1) -> str:
    """Convierte un importe entre monedas con tipos de cambio del BCE.

    Ej: desde="USD", hacia="EUR", cantidad=100.
    """
    desde = str(desde or "USD").strip().upper()
    hacia = str(hacia or "EUR").strip().upper()
    try:
        cantidad = float(str(cantidad).replace(",", "."))
    except Exception:                                       # noqa: BLE001
        cantidad = 1.0
    if desde == hacia:
        return f"{cantidad:g} {desde} = {cantidad:g} {hacia} (misma moneda)."
    try:
        d = _get_json(f"https://api.frankfurter.app/latest",
                      {"from": desde, "to": hacia})
        rate = (d.get("rates") or {}).get(hacia)
        if rate is None:
            return f"No pude convertir {desde} → {hacia} (moneda no soportada o API caída)."
        total = cantidad * rate
        return f"{cantidad:g} {desde} = {total:,.2f} {hacia} (1 {desde} = {rate} {hacia}, BCE {d.get('date')})."
    except Exception as e:                                  # noqa: BLE001
        return f"No pude consultar el tipo de cambio ({type(e).__name__})."


# ── 4. Traducción (MyMemory, gratis sin key) ─────────────────────────────────
def traducir(texto: str, destino: str = "en", origen: str = "es") -> str:
    """Traduce un texto a otro idioma.

    Ej: texto="hola mundo", origen="es", destino="en".
    """
    texto = str(texto or "").strip()
    if not texto:
        return "Necesito un texto para traducir."
    origen = str(origen or "es").strip().lower()[:2]
    destino = str(destino or "en").strip().lower()[:2]
    if origen == destino:
        return texto
    try:
        d = _get_json("https://api.mymemory.translated.net/get",
                      {"q": texto, "langpair": f"{origen}|{destino}"})
        tr = ((d.get("responseData") or {}).get("translatedText") or "").strip()
        if not tr:
            return "No pude traducir ese texto."
        return tr
    except Exception as e:                                  # noqa: BLE001
        return f"No pude traducir ({type(e).__name__})."


# ── 5. Calculadora segura (AST, sin eval) ────────────────────────────────────
_BINOPS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
}
_UNOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def calculadora(expresion: str) -> str:
    """Calcula una expresión aritmética de forma segura.

    Ej: "12*7", "2**10", "(5+3)/2".
    """
    expr = str(expresion or "").strip().replace(",", ".")
    if not expr:
        return "Necesito una expresión, ej. «12*7»."

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            r = _BINOPS[type(node.op)](ev(node.left), ev(node.right))
            if isinstance(r, float) and (r != r or r in (float("inf"), float("-inf"))):
                raise ValueError("indefinido")
            return r
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNOPS:
            return _UNOPS[type(node.op)](ev(node.operand))
        raise ValueError("operación no permitida")

    try:
        result = ev(ast.parse(expr, mode="eval"))
        if isinstance(result, float) and result.is_integer():
            result = int(result)
        return f"{expr} = {result}"
    except Exception:                                       # noqa: BLE001
        return f"No pude calcular «{expr}». Usa solo números y + - * / % ** ( ) "


# ── 6. Conversión de unidades ────────────────────────────────────────────────
def convertir_unidades(valor: float, desde: str, hacia: str) -> str:
    """Convierte entre unidades comunes.

    Temperatura: c/f/k. Longitud: km/m/cm/mi/ft. Masa: kg/g/lb.
    """
    try:
        v = float(str(valor).replace(",", "."))
    except Exception:                                       # noqa: BLE001
        return "El valor debe ser un número."
    desde = str(desde or "").strip().lower()
    hacia = str(hacia or "").strip().lower()
    tabla = {
        ("c", "f"): lambda x: x * 9 / 5 + 32,
        ("f", "c"): lambda x: (x - 32) * 5 / 9,
        ("c", "k"): lambda x: x + 273.15,
        ("k", "c"): lambda x: x - 273.15,
        ("f", "k"): lambda x: (x - 32) * 5 / 9 + 273.15,
        ("k", "f"): lambda x: (x - 273.15) * 9 / 5 + 32,
        ("km", "m"): lambda x: x * 1000, ("m", "km"): lambda x: x / 1000,
        ("km", "mi"): lambda x: x * 0.621371, ("mi", "km"): lambda x: x / 0.621371,
        ("m", "ft"): lambda x: x * 3.28084, ("ft", "m"): lambda x: x / 3.28084,
        ("cm", "in"): lambda x: x / 2.54, ("in", "cm"): lambda x: x * 2.54,
        ("kg", "lb"): lambda x: x * 2.20462, ("lb", "kg"): lambda x: x / 2.20462,
        ("kg", "g"): lambda x: x * 1000, ("g", "kg"): lambda x: x / 1000,
        ("l", "gal"): lambda x: x * 0.264172, ("gal", "l"): lambda x: x / 0.264172,
    }
    fn = tabla.get((desde, hacia))
    if not fn:
        return f"No sé convertir de {desde} a {hacia}. Prueba: c/f, km/mi, kg/lb, l/gal."
    return f"{v:g} {desde} = {fn(v):,.2f} {hacia}"


# ── 7. Hora en zona horaria ─────────────────────────────────────────────────
def hora_en(zona: str) -> str:
    """Hora actual en una zona horaria IANA.

    Ej: America/Caracas, Europe/Madrid, Asia/Tokyo.
    """
    zona = str(zona or "").strip() or "America/Caracas"
    try:
        now = datetime.now(ZoneInfo(zona))
    except Exception:                                       # noqa: BLE001
        return f"Zona horaria desconocida: «{zona}». Usa nombres IANA (ej. Europe/Madrid)."
    return f"{zona}: {now.strftime('%Y-%m-%d %H:%M')} ({now.tzname()})"


# ── 8. Curiosidad ───────────────────────────────────────────────────────────
def curiosidad() -> str:
    """Devuelve una curiosidad aleatoria y sorprendente."""
    return random.choice(CURIOSIDADES)


# ── 9. Chiste ───────────────────────────────────────────────────────────────
def chiste() -> str:
    """Cuenta un chiste corto (geek y ligero)."""
    return random.choice(CHISTES)


# ── 10. Dado ────────────────────────────────────────────────────────────────
def dado(caras: int = 6) -> str:
    """Tira un dado de N caras (por defecto 6)."""
    try:
        n = int(float(str(caras)))
    except Exception:                                       # noqa: BLE001
        n = 6
    n = max(2, min(n, 100))
    return f"🎲 Ha salido un {random.randint(1, n)} (dado de {n} caras)."


# ── 11. Noticias en vivo (Google News RSS) ─────────────────────────────────
def noticias(tema: str = "") -> str:
    """Últimas noticias de Google News sobre un tema (o titulares generales).

    Devuelve hasta 5 titulares con su fecha.
    """
    tema = str(tema or "").strip()
    if tema:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(tema)
               + "&hl=es&gl=ES&ceid=ES:es")
    else:
        url = "https://news.google.com/rss?hl=es&gl=ES&ceid=ES:es"
    try:
        req = urllib.request.Request(url, headers=UA)
        with urllib.request.urlopen(req, timeout=20) as r:
            xml = r.read()
    except Exception as e:                                  # noqa: BLE001
        return f"No pude leer las noticias ({type(e).__name__})."
    import xml.etree.ElementTree as ET

    try:
        root = ET.fromstring(xml)
    except Exception:                                       # noqa: BLE001
        return "Las noticias llegaron en un formato inesperado."
    items = root.findall(".//item")[:5]
    if not items:
        return "No encontré noticias para esa búsqueda."
    lineas = []
    for it in items:
        titulo = (it.findtext("title") or "").strip()
        pub = (it.findtext("pubDate") or "").strip()
        fecha = pub[5:16] if len(pub) > 16 else ""
        lineas.append(f"• {titulo}" + (f" ({fecha})" if fecha else ""))
    cabecera = f"Noticias sobre «{tema}»:" if tema else "Titulares ahora:"
    return cabecera + "\n" + "\n".join(lineas)


# ── 12. Cripto en vivo (CoinGecko) ──────────────────────────────────────────
_CRIPTO_IDS = {
    "btc": "bitcoin", "bitcoin": "bitcoin", "eth": "ethereum", "ethereum": "ethereum",
    "sol": "solana", "solana": "solana", "doge": "dogecoin", "dogecoin": "dogecoin",
    "ada": "cardano", "cardano": "cardano", "xrp": "ripple", "ripple": "ripple",
    "bnb": "binancecoin", "ton": "the-open-network", "trx": "tron", "tron": "tron",
    "dot": "polkadot", "polkadot": "polkadot", "ltc": "litecoin", "litecoin": "litecoin",
}


def cripto(moneda: str = "bitcoin") -> str:
    """Precio actual de una criptomoneda en USD y EUR con variación 24h (CoinGecko)."""
    clave = str(moneda or "bitcoin").strip().lower()
    cid = _CRIPTO_IDS.get(clave, clave)
    try:
        d = _get_json("https://api.coingecko.com/api/v3/simple/price",
                      {"ids": cid, "vs_currencies": "usd,eur", "include_24hr_change": "true"})
    except Exception as e:                                  # noqa: BLE001
        return f"No pude consultar CoinGecko ({type(e).__name__})."
    if not d:
        return f"No encontré la criptomoneda «{moneda}»."
    v = next(iter(d.values()))
    cambio = v.get("usd_24h_change")
    trend = ""
    if isinstance(cambio, (int, float)):
        trend = f" ({cambio:+.2f}% 24h)"
    return (f"{cid}: {v.get('usd'):,} USD · {v.get('eur'):,} EUR{trend}"
            if isinstance(v.get("usd"), (int, float)) else f"{cid}: sin datos")


# ── 13. Deportes en vivo (ESPN) ─────────────────────────────────────────────
_LIGAS = {
    "laliga": "soccer/esp.1", "españa": "soccer/esp.1", "esp.1": "soccer/esp.1",
    "premier": "soccer/eng.1", "inglaterra": "soccer/eng.1", "eng.1": "soccer/eng.1",
    "seriea": "soccer/ita.1", "italia": "soccer/ita.1", "ita.1": "soccer/ita.1",
    "bundesliga": "soccer/ger.1", "alemania": "soccer/ger.1",
    "ligue1": "soccer/fra.1", "francia": "soccer/fra.1",
    "champions": "soccer/uefa.champions", "ucl": "soccer/uefa.champions",
    "mls": "soccer/usa.1", "nba": "basketball/nba", "nfl": "football/nfl", "mlb": "baseball/mlb",
}


def deportes(liga: str = "laliga") -> str:
    """Marcadores y próximos partidos de una liga (ESPN).

    Ligas: laliga, premier, seriea, bundesliga, ligue1, champions, mls, nba, nfl, mlb.
    """
    clave = str(liga or "laliga").strip().lower()
    path = _LIGAS.get(clave)
    if not path:
        return f"No conozco la liga «{liga}». Prueba: {', '.join(sorted(set(_LIGAS)))}."
    try:
        d = _get_json(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard")
    except Exception as e:                                  # noqa: BLE001
        return f"No pude consultar ESPN ({type(e).__name__})."
    eventos = d.get("events") or []
    if not eventos:
        return "No hay eventos de esa liga en este momento."
    lineas = []
    for ev in eventos[:5]:
        comp = (ev.get("competitions") or [{}])[0]
        equipos = []
        for c in comp.get("competitors") or []:
            team = c.get("team") or {}
            nombre = team.get("displayName") or team.get("name") or "?"
            score = c.get("score")
            equipos.append(f"{nombre} {score}" if score not in (None, "") else nombre)
        estado = ((comp.get("status") or {}).get("type") or {}).get("shortDetail") or "?"
        lineas.append(f"• {' vs '.join(equipos)} — {estado}")
    nombre_liga = ((d.get("leagues") or [{}])[0]).get("name") or clave
    return f"{nombre_liga}:\n" + "\n".join(lineas)


# ── 14. Sismos en vivo (USGS) ───────────────────────────────────────────────
def sismos(min_magnitud: float = 4.0) -> str:
    """Sismos recientes con magnitud ≥ umbral (USGS, última semana)."""
    try:
        umbral = float(str(min_magnitud or 4.0).replace(",", "."))
    except Exception:                                       # noqa: BLE001
        umbral = 4.0
    try:
        d = _get_json("https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/2.5_week.geojson")
    except Exception as e:                                  # noqa: BLE001
        return f"No pude consultar USGS ({type(e).__name__})."
    filas = []
    for f in d.get("features") or []:
        p = f.get("properties") or {}
        mag = p.get("mag")
        if isinstance(mag, (int, float)) and mag >= umbral:
            filas.append((mag, p.get("place") or "?"))
    filas.sort(reverse=True)
    if not filas:
        return f"No hubo sismos de magnitud ≥ {umbral:g} en la última semana."
    lineas = [f"• M{mag:.1f} — {place}" for mag, place in filas[:6]]
    return f"Sismos ≥ M{umbral:g} (última semana, USGS):\n" + "\n".join(lineas)


# ── 15-17. Visión / OCR (HF Inference API: chat completions multimodal) ─────
_VISION_MODELOS = ["Qwen/Qwen3.8-27B", "google/gemma-4-31B-it", "moonshotai/Kimi-K3"]
_ROUTER_CHAT = "https://router.huggingface.co/v1/chat/completions"
_PROMPT_OCR = (
    "Transcribe EXACTAMENTE todo el texto visible en la imagen, respetando saltos de "
    "línea y mayúsculas. Si no hay texto, responde únicamente: (sin texto)."
)
_PROMPT_DESC = (
    "Describe en una sola frase breve qué se ve en la imagen. Responde solo la "
    "descripción, sin introducción."
)


def _hf_token() -> str:
    t = (os.getenv("HF_TOKEN") or "").strip()
    if t:
        return t
    for p in (
        pathlib.Path.home() / ".cache" / "huggingface" / "token",
        pathlib.Path.home() / ".huggingface" / "token",
    ):
        if p.is_file():
            return p.read_text().strip()
    raise ValueError(
        "Falta HF_TOKEN con permiso de Inference Providers (para visión)."
    )


def _cargar_imagen(imagen: str) -> bytes:
    """Acepta una URL http(s) o base64 (con o sin prefijo data:)."""
    s = str(imagen or "").strip()
    if not s:
        raise ValueError("Falta la imagen (URL o base64).")
    if s.startswith(("http://", "https://")):
        req = urllib.request.Request(s, headers={"User-Agent": "reachy-mcp/1.2"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read(8 * 1024 * 1024 + 1)
        if len(data) > 8 * 1024 * 1024:
            raise ValueError("La imagen supera 8 MB.")
        return data
    if s.startswith("data:"):
        s = s.split(",", 1)[1]
    return base64.b64decode(s)


def _mime_imagen(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/png"


def _vision_chat(prompt: str, imagen: str, max_tokens: int = 400) -> str:
    data = _cargar_imagen(imagen)
    token = _hf_token()
    uri = f"data:{_mime_imagen(data)};base64,{base64.b64encode(data).decode()}"
    ultimo = None
    for modelo in _VISION_MODELOS:
        body = {
            "model": modelo,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": uri}},
            ]}],
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            _ROUTER_CHAT,
            data=json.dumps(body).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.load(r)
            out = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
            out = str(out).strip()
            if out:
                return out
            ultimo = f"{modelo}: respuesta vacía"
        except urllib.error.HTTPError as e:
            body_txt = ""
            try:
                body_txt = e.read()[:200].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            if e.code in (401, 403):
                raise ValueError(
                    "Token sin permiso de Inference Providers. Crea uno con "
                    "«Make calls to Inference Providers» y guárdalo en HF_TOKEN."
                )
            ultimo = f"{modelo}: HTTP {e.code} {body_txt}"
        except urllib.error.URLError as e:
            ultimo = f"{modelo}: {e.reason}"
    raise ValueError(f"Ningún modelo de visión respondió. Último error: {ultimo}")


def ocr_imagen(imagen: str) -> str:
    """Extrae el texto de una imagen (URL http(s) o base64) usando un VLM.

    Devuelve el texto reconocido, o "(sin texto)" si la imagen no tiene texto.
    """
    out = _vision_chat(_PROMPT_OCR, imagen)
    if out.strip().lower().startswith("(sin texto"):
        return "(sin texto detectado)"
    return out


def describir_imagen(imagen: str) -> str:
    """Describe en una frase qué se ve en una imagen (URL http(s) o base64)."""
    return _vision_chat(_PROMPT_DESC, imagen)


def preguntar_imagen(imagen: str, pregunta: str) -> str:
    """Responde una pregunta sobre una imagen (URL http(s) o base64).

    Ej: imagen="https://…/foto.jpg", pregunta="¿cuántas personas hay?"
    """
    pregunta = str(pregunta or "").strip() or "¿Qué se ve en la imagen?"
    return _vision_chat(pregunta, imagen)


# ── 18-22. Más datos en vivo ───────────────────────────────────────────────
def calidad_aire(ciudad: str) -> str:
    """Calidad del aire actual (AQI, PM2.5, PM10) de una ciudad (Open-Meteo)."""
    ciudad = str(ciudad or "").strip()
    if not ciudad:
        return "Necesito una ciudad. Ej: «Caracas»."
    try:
        geo = _get_json("https://geocoding-api.open-meteo.com/v1/search",
                        {"name": ciudad, "count": 1, "language": "es"})
    except Exception as e:                                  # noqa: BLE001
        return f"No pude geocodificar «{ciudad}» ({type(e).__name__})."
    results = geo.get("results") or []
    if not results:
        return f"No encontré la ciudad «{ciudad}»."
    g = results[0]
    lugar = ", ".join(x for x in [g.get("name"), g.get("country")] if x)
    try:
        aq = _get_json("https://air-quality-api.open-meteo.com/v1/air-quality", {
            "latitude": g["latitude"], "longitude": g["longitude"],
            "current": "pm10,pm2_5,european_aqi,us_aqi",
        })
    except Exception as e:                                  # noqa: BLE001
        return f"No pude obtener la calidad del aire de {lugar} ({type(e).__name__})."
    cur = aq.get("current") or {}
    aqi = cur.get("european_aqi")
    nivel = ""
    if isinstance(aqi, (int, float)):
        if aqi <= 20:
            nivel = " (buena)"
        elif aqi <= 40:
            nivel = " (aceptable)"
        elif aqi <= 60:
            nivel = " (moderada)"
        elif aqi <= 80:
            nivel = " (mala)"
        else:
            nivel = " (muy mala)"
    return (f"{lugar}: AQI europeo {aqi}{nivel} · US AQI {cur.get('us_aqi')} · "
            f"PM2.5 {cur.get('pm2_5')} µg/m³ · PM10 {cur.get('pm10')} µg/m³.")


def receta(plato: str) -> str:
    """Busca una receta y devuelve ingredientes y pasos (TheMealDB)."""
    plato = str(plato or "").strip()
    if not plato:
        return "Dime qué plato buscas. Ej: «paella»."
    try:
        d = _get_json("https://www.themealdb.com/api/json/v1/1/search.php",
                      {"s": urllib.parse.quote(plato)})
    except Exception as e:                                  # noqa: BLE001
        return f"No pude consultar las recetas ({type(e).__name__})."
    meals = d.get("meals") or []
    if not meals:
        return f"No encontré recetas para «{plato}»."
    m = meals[0]
    ing = []
    for i in range(1, 21):
        nombre = (m.get(f"strIngredient{i}") or "").strip()
        medida = (m.get(f"strMeasure{i}") or "").strip()
        if nombre:
            ing.append(f"{nombre} ({medida})" if medida else nombre)
    pasos = " ".join((m.get("strInstructions") or "").split())[:600]
    return (f"{m.get('strMeal')} — {m.get('strArea')} / {m.get('strCategory')}\n"
            f"Ingredientes: {', '.join(ing[:12])}\n"
            f"Pasos: {pasos}…")


def foto_mascota(animal: str = "perro") -> str:
    """Devuelve la URL de una foto aleatoria de perro o gato (úsala con las tools de visión)."""
    animal = str(animal or "perro").strip().lower()
    try:
        if animal.startswith("gat") or animal.startswith("cat"):
            d = _get_json("https://cataas.com/cat?json=true")
            url = d.get("url") or (f"https://cataas.com/cat/{d.get('id')}" if d.get("id") else "")
            if not url:
                return "No pude obtener una foto de gato."
            return f"Gato: {url}"
        d = _get_json("https://dog.ceo/api/breeds/image/random")
        url = d.get("message") or ""
        if not url:
            return "No pude obtener una foto de perro."
        return f"Perro: {url}"
    except Exception as e:                                  # noqa: BLE001
        return f"No pude obtener la foto ({type(e).__name__})."


def leer_web(url: str) -> str:
    """Lee una página web y devuelve su texto visible (sin HTML)."""
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        return "Pásame una URL http(s) válida."
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
            "Accept": "text/html,application/xhtml+xml",
        })
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read(1024 * 1024)
            charset = r.headers.get_content_charset() or "utf-8"
    except Exception as e:                                  # noqa: BLE001
        return f"No pude leer la página ({type(e).__name__}). Algunos sitios bloquean lectores automáticos."
    import html as _html
    from html.parser import HTMLParser

    class _Texto(HTMLParser):
        def __init__(self):
            super().__init__()
            self.partes: list[str] = []
            self.saltar = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript"):
                self.saltar += 1

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript") and self.saltar:
                self.saltar -= 1

        def handle_data(self, data):
            if not self.saltar:
                texto = data.strip()
                if texto:
                    self.partes.append(texto)

    parser = _Texto()
    try:
        parser.feed(raw.decode(charset, "replace"))
    except Exception:                                       # noqa: BLE001
        parser.feed(raw.decode("utf-8", "replace"))
    texto = " ".join(" ".join(parser.partes).split())
    if not texto:
        return "(la página no tiene texto visible)"
    return texto[:3000] + ("…" if len(texto) > 3000 else "")


def clasificacion(liga: str = "laliga") -> str:
    """Clasificación actual de una liga (ESPN).

    Ligas: laliga, premier, seriea, bundesliga, ligue1, mls.
    """
    clave = str(liga or "laliga").strip().lower()
    path = _LIGAS.get(clave)
    if not path or not path.startswith("soccer/"):
        return f"No tengo clasificación para «{liga}». Prueba: laliga, premier, seriea, bundesliga, ligue1, mls."
    try:
        d = _get_json(f"https://site.api.espn.com/apis/v2/sports/{path}/standings")
    except Exception as e:                                  # noqa: BLE001
        return f"No pude consultar la clasificación ({type(e).__name__})."
    # estructura: children[0].standings.entries[]
    try:
        child = (d.get("children") or [{}])[0]
        entries = ((child.get("standings") or {}).get("entries") or [])
    except Exception:                                       # noqa: BLE001
        return "El formato de la clasificación no es el esperado."
    if not entries:
        return "No hay clasificación disponible ahora mismo."

    filas = []
    for e in entries:
        team = (e.get("team") or {}).get("displayName") or "?"
        stats = {s.get("name"): s.get("value") for s in (e.get("stats") or [])}
        puntos = stats.get("points")
        rank = stats.get("rank")
        filas.append((rank if isinstance(rank, (int, float)) else 999,
                      points := (puntos if isinstance(puntos, (int, float)) else 0), team))
    filas.sort(key=lambda x: x[0])
    lineas = []
    for _rank, pts, team in filas[:10]:
        if isinstance(pts, float) and pts.is_integer():
            pts = int(pts)
        lineas.append(f"• {team}: {pts} pts")
    nombre = child.get("name") or clave
    return f"Clasificación {nombre}:\n" + "\n".join(lineas)


# ── Registro MCP: metadata + despacho + argumentos ──────────────────────────
def _schema(props: dict | None = None, required: list[str] | None = None) -> dict:
    s = {"type": "object", "properties": props or {}}
    if required:
        s["required"] = required
    return s


TOOLS = [
    {"name": "wiki_resumen", "description": "Resumen de Wikipedia en español sobre un tema. "
     "Úsala cuando pregunte qué es algo o quién es alguien.",
     "inputSchema": _schema({"tema": {"type": "string"}}, ["tema"])},
    {"name": "clima", "description": "Clima actual y pronóstico de hoy en una ciudad "
     "(dato real vía Open-Meteo). Úsala para preguntas del tiempo.",
     "inputSchema": _schema({"ciudad": {"type": "string"}}, ["ciudad"])},
    {"name": "monedas", "description": "Convierte importes entre monedas con tipos del BCE.",
     "inputSchema": _schema({"desde": {"type": "string"}, "hacia": {"type": "string"},
                             "cantidad": {"type": "number", "default": 1}}, ["desde", "hacia"])},
    {"name": "traducir", "description": "Traduce un texto a otro idioma (es→en por defecto).",
     "inputSchema": _schema({"texto": {"type": "string"}, "destino": {"type": "string", "default": "en"},
                             "origen": {"type": "string", "default": "es"}}, ["texto"])},
    {"name": "calculadora", "description": "Calcula una expresión aritmética de forma segura.",
     "inputSchema": _schema({"expresion": {"type": "string"}}, ["expresion"])},
    {"name": "convertir_unidades", "description": "Convierte temperatura, longitud, masa o volumen.",
     "inputSchema": _schema({"valor": {"type": "number"}, "desde": {"type": "string"},
                             "hacia": {"type": "string"}}, ["valor", "desde", "hacia"])},
    {"name": "hora_en", "description": "Hora actual en una zona horaria IANA.",
     "inputSchema": _schema({"zona": {"type": "string"}}, ["zona"])},
    {"name": "curiosidad", "description": "Devuelve una curiosidad aleatoria y sorprendente.",
     "inputSchema": _schema()},
    {"name": "chiste", "description": "Cuenta un chiste corto.",
     "inputSchema": _schema()},
    {"name": "dado", "description": "Tira un dado de N caras (por defecto 6).",
     "inputSchema": _schema({"caras": {"type": "integer", "default": 6}})},
    {"name": "noticias", "description": "Últimas noticias en vivo (Google News) sobre un tema "
     "o los titulares generales si no se indica tema.",
     "inputSchema": _schema({"tema": {"type": "string", "default": ""}})},
    {"name": "cripto", "description": "Precio actual de una criptomoneda en USD/EUR con "
     "variación 24h (CoinGecko). Ej: bitcoin, eth, solana.",
     "inputSchema": _schema({"moneda": {"type": "string", "default": "bitcoin"}})},
    {"name": "deportes", "description": "Marcadores de hoy en una liga (ESPN): laliga, premier, "
     "seriea, bundesliga, ligue1, champions, mls, nba, nfl, mlb.",
     "inputSchema": _schema({"liga": {"type": "string", "default": "laliga"}})},
    {"name": "sismos", "description": "Sismos recientes con magnitud ≥ umbral (USGS, última semana).",
     "inputSchema": _schema({"min_magnitud": {"type": "number", "default": 4.0}})},
    {"name": "ocr_imagen", "description": "Extrae el texto de una imagen (URL http(s) o base64) "
     "usando un modelo de visión. Úsala para leer documentos, tickets o capturas.",
     "inputSchema": _schema({"imagen": {"type": "string"}}, ["imagen"])},
    {"name": "describir_imagen", "description": "Describe en una frase qué se ve en una imagen "
     "(URL http(s) o base64).",
     "inputSchema": _schema({"imagen": {"type": "string"}}, ["imagen"])},
    {"name": "preguntar_imagen", "description": "Responde una pregunta sobre una imagen "
     "(URL http(s) o base64). Ej: ¿cuántas personas hay?",
     "inputSchema": _schema({"imagen": {"type": "string"}, "pregunta": {"type": "string"}},
                            ["imagen", "pregunta"])},
    {"name": "calidad_aire", "description": "Calidad del aire actual (AQI, PM2.5, PM10) de una "
     "ciudad (Open-Meteo).",
     "inputSchema": _schema({"ciudad": {"type": "string"}}, ["ciudad"])},
    {"name": "receta", "description": "Busca una receta con ingredientes y pasos (TheMealDB).",
     "inputSchema": _schema({"plato": {"type": "string"}}, ["plato"])},
    {"name": "foto_mascota", "description": "URL de una foto aleatoria de perro o gato "
     "(puedes pasársela a las tools de visión para describirla).",
     "inputSchema": _schema({"animal": {"type": "string", "default": "perro"}})},
    {"name": "leer_web", "description": "Lee una página web y devuelve su texto visible (sin HTML).",
     "inputSchema": _schema({"url": {"type": "string"}}, ["url"])},
    {"name": "clasificacion", "description": "Clasificación de una liga de fútbol (ESPN): "
     "laliga, premier, seriea, bundesliga, ligue1, mls.",
     "inputSchema": _schema({"liga": {"type": "string", "default": "laliga"}})},
]

# argumentos posicionales por función (nombre, default) — para el puente HTTP
ARGS_MAP = {
    "wiki_resumen": [("tema", "")],
    "clima": [("ciudad", "")],
    "monedas": [("desde", "USD"), ("hacia", "EUR"), ("cantidad", 1)],
    "traducir": [("texto", ""), ("destino", "en"), ("origen", "es")],
    "calculadora": [("expresion", "")],
    "convertir_unidades": [("valor", 0), ("desde", "c"), ("hacia", "f")],
    "hora_en": [("zona", "")],
    "curiosidad": [],
    "chiste": [],
    "dado": [("caras", 6)],
    "noticias": [("tema", "")],
    "cripto": [("moneda", "bitcoin")],
    "deportes": [("liga", "laliga")],
    "sismos": [("min_magnitud", 4.0)],
    "ocr_imagen": [("imagen", "")],
    "describir_imagen": [("imagen", "")],
    "preguntar_imagen": [("imagen", ""), ("pregunta", "")],
    "calidad_aire": [("ciudad", "")],
    "receta": [("plato", "")],
    "foto_mascota": [("animal", "perro")],
    "leer_web": [("url", "")],
    "clasificacion": [("liga", "laliga")],
}

DISPATCH = {
    "wiki_resumen": wiki_resumen,
    "clima": clima,
    "monedas": monedas,
    "traducir": traducir,
    "calculadora": calculadora,
    "convertir_unidades": convertir_unidades,
    "hora_en": hora_en,
    "curiosidad": curiosidad,
    "chiste": chiste,
    "dado": dado,
    "noticias": noticias,
    "cripto": cripto,
    "deportes": deportes,
    "sismos": sismos,
    "ocr_imagen": ocr_imagen,
    "describir_imagen": describir_imagen,
    "preguntar_imagen": preguntar_imagen,
    "calidad_aire": calidad_aire,
    "receta": receta,
    "foto_mascota": foto_mascota,
    "leer_web": leer_web,
    "clasificacion": clasificacion,
}


def call_tool(name: str, args: dict) -> str:
    fn = DISPATCH.get(name)
    if fn is None:
        return f"Herramienta desconocida: {name}"
    params = ARGS_MAP.get(name, [])
    kwargs = {}
    for p, d in params:
        val = args.get(p, d)
        kwargs[p] = val
    return fn(**kwargs)
