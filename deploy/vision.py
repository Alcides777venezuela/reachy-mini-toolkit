#!/usr/bin/env python3
"""
vision.py — OCR y descripción de imágenes con la HF Inference API (router).

Vía correcta en 2026: **chat completions multimodales**
`https://router.huggingface.co/v1/chat/completions` con un VLM (imagen como data URI).
El antiguo endpoint por bytes (`/hf-inference/models/...`) ya no sirve modelos de imagen.

Token: `HF_TOKEN` o `~/.cache/huggingface/token` con permiso de Inference Providers.
Modelos de respaldo: Qwen3.8-27B → gemma-4-31B-it → Kimi-K3 (los tres verificados).

Uso:
  from vision import ocr, caption
  ocr(png_bytes)      → "texto reconocido"
  caption(png_bytes)  → "descripción breve"
"""

import base64
import json
import os
import pathlib
import urllib.request

ROUTER_CHAT = "https://router.huggingface.co/v1/chat/completions"
MODELOS = [
    "Qwen/Qwen3.8-27B",
    "google/gemma-4-31B-it",
    "moonshotai/Kimi-K3",
]
MAX_BYTES = 8 * 1024 * 1024

PROMPT_OCR = (
    "Transcribe EXACTAMENTE todo el texto visible en la imagen, respetando saltos de "
    "línea y mayúsculas. Si no hay texto, responde únicamente: (sin texto)."
)
PROMPT_CAPTION = (
    "Describe en una sola frase breve qué se ve en la imagen. Responde solo la "
    "descripción, sin introducción."
)


class VisionError(RuntimeError):
    """Error controlado con mensaje apto para mostrar al usuario."""


def _token() -> str:
    t = (os.getenv("HF_TOKEN") or "").strip()
    if t:
        return t
    for p in (
        pathlib.Path.home() / ".cache" / "huggingface" / "token",
        pathlib.Path.home() / ".huggingface" / "token",
    ):
        if p.is_file():
            return p.read_text().strip()
    raise VisionError(
        "Falta token HF. Guárdalo en HF_TOKEN o en ~/.cache/huggingface/token "
        "(necesita permiso «Make calls to Inference Providers»)."
    )


def _mime(image: bytes) -> str:
    if image[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if image[:2] == b"\xff\xd8":
        return "image/jpeg"
    if image[:4] == b"RIFF" and image[8:12] == b"WEBP":
        return "image/webp"
    if image[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"


def _chat(prompt: str, image: bytes) -> str:
    if not image:
        raise VisionError("Imagen vacía.")
    if len(image) > MAX_BYTES:
        raise VisionError(f"Imagen demasiado grande ({len(image) / 1e6:.1f} MB > 8 MB).")
    token = _token()
    data_uri = f"data:{_mime(image)};base64,{base64.b64encode(image).decode()}"
    last_error = None
    for modelo in MODELOS:
        body = {
            "model": modelo,
            "messages": [{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": data_uri}},
            ]}],
            "max_tokens": 400,
            "temperature": 0.2,
        }
        req = urllib.request.Request(
            ROUTER_CHAT,
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
            last_error = f"{modelo}: respuesta vacía"
        except urllib.error.HTTPError as e:
            body_txt = ""
            try:
                body_txt = e.read()[:200].decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                pass
            if e.code in (401, 403):
                raise VisionError(
                    f"Token sin permiso de Inference Providers (HTTP {e.code}). "
                    "Crea uno con «Make calls to Inference Providers» en "
                    "https://huggingface.co/settings/tokens."
                ) from e
            last_error = f"{modelo}: HTTP {e.code} {body_txt}"
        except urllib.error.URLError as e:
            last_error = f"{modelo}: {e.reason}"
    raise VisionError(f"Ningún modelo de visión respondió. Último error: {last_error}")


def ocr(image: bytes) -> str:
    """Devuelve el texto reconocido en la imagen."""
    out = _chat(PROMPT_OCR, image)
    if out.strip().lower().startswith("(sin texto"):
        return "(sin texto detectado)"
    return out


def caption(image: bytes) -> str:
    """Devuelve una descripción breve de la imagen."""
    return _chat(PROMPT_CAPTION, image)
