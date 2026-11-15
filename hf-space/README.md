---
title: Reachy MCP Tool
emoji: 🔌
colorFrom: indigo
colorTo: purple
sdk: gradio
app_file: app.py
pinned: false
tags:
  - reachy-mini-tool
  - mcp
  - tools
---

# 🔌 Reachy MCP Tool — 17 herramientas para tu robot

Tools **MCP** (Gradio `mcp_server=True`) **con UI navegable** (una pestaña por tool),
para el **Reachy Mini Conversation App** o cualquier cliente MCP.

**Schema:** https://alcides777-reachy-mcp-tool.hf.space/gradio_api/mcp/schema

## Catálogo

| Tool | Qué hace | Fuente |
|---|---|---|
| `wiki_resumen(tema)` | Resumen de Wikipedia en español | Wikipedia ES |
| `clima(ciudad)` | Clima actual + pronóstico de hoy | Open-Meteo |
| `monedas(desde, hacia, cantidad)` | Conversión de divisas | Frankfurter/BCE |
| `traducir(texto, destino, origen)` | Traducción de texto | MyMemory |
| `noticias(tema)` | Titulares en vivo | Google News RSS |
| `cripto(moneda)` | Precio USD/EUR + variación 24h | CoinGecko |
| `deportes(liga)` | Marcadores y partidos | ESPN |
| `sismos(min_magnitud)` | Sismos de la última semana | USGS |
| `calculadora(expresion)` | Aritmética segura (AST) | local |
| `convertir_unidades(valor, desde, hacia)` | C°/F°/K°, km/mi, kg/lb, l/gal | local |
| `hora_en(zona)` | Hora en zona IANA | local (tzdata) |
| `curiosidad()` | Dato curioso | local |
| `chiste()` | Chiste corto | local |
| `dado(caras)` | Tirar un dado | local |
| **`ocr_imagen(imagen)`** | Transcribe el texto de una imagen | VLM (Qwen3.8-27B) |
| **`describir_imagen(imagen)`** | Describe una imagen en una frase | VLM |
| **`preguntar_imagen(imagen, pregunta)`** | Responde preguntas sobre una imagen | VLM |

> Las tools de visión aceptan una **URL http(s)** o **base64**. En el Space necesitan el
> secret `HF_TOKEN` (con permiso de Inference Providers) — ya configurado.

## Instalar en el robot

```bash
reachy-mini-conversation-app tool-spaces add Alcides777/reachy-mcp-tool
```

## Prueba rápida

```bash
curl https://alcides777-reachy-mcp-tool.hf.space/gradio_api/mcp/schema
```

Sin API keys: Wikipedia, Open-Meteo, Frankfurter, MyMemory, Google News, CoinGecko,
ESPN y USGS son APIs públicas (con límites de uso anónimo).
