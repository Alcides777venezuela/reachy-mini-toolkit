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

# 🔌 Reachy MCP Tool — 26 herramientas para tu robot

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
| `clasificacion(liga)` | Tabla de posiciones | ESPN |
| `sismos(min_magnitud)` | Sismos de la última semana | USGS |
| `calidad_aire(ciudad)` | AQI, PM2.5, PM10 | Open-Meteo Air Quality |
| `receta(plato)` | Ingredientes y pasos | TheMealDB |
| `foto_mascota(animal)` | URL de foto de perro/gato | Dog CEO / Cataas |
| `leer_web(url)` | Texto visible de una web | HTTP directo |
| `calculadora(expresion)` | Aritmética segura (AST) | local |
| `convertir_unidades(valor, desde, hacia)` | C°/F°/K°, km/mi, kg/lb, l/gal | local |
| `hora_en(zona)` | Hora en zona IANA | local (tzdata) |
| `curiosidad()` | Dato curioso | local |
| `chiste()` | Chiste corto | local |
| `dado(caras)` | Tirar un dado | local |
| **`ocr_imagen(imagen)`** | Transcribe el texto de una imagen | VLM (Qwen3.8-27B) |
| **`describir_imagen(imagen)`** | Describe una imagen en una frase | VLM |
| **`preguntar_imagen(imagen, pregunta)`** | Responde preguntas sobre una imagen | VLM |
| **`escribir_nota(titulo, contenido)`** | Escribe una nota/documento en disco | local |
| **`leer_nota(titulo)`** | Lee una nota guardada | local |
| **`listar_notas()`** | Lista notas con fecha y tamaño | local |
| **`borrar_nota(titulo)`** | Borra una nota | local |

> Las tools de visión aceptan una **URL http(s)** o **base64**. En el Space necesitan el
> secret `HF_TOKEN` (con permiso de Inference Providers) — ya configurado.
> Las notas se guardan en el disco del Space (efímero); en local persisten en `~/reachy_notas`.

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
