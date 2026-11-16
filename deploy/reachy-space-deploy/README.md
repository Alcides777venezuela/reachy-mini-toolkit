---
title: Reachy Web Console
emoji: 🕹️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
tags:
  - reachy-mini
  - mcp
  - voice
---

# 🕹️ Reachy Web Console (en la web)

Consola web del robot Reachy Mini con **voz 🎤 · visión 📷 · escritura ✍️** y **26 tools MCP**:

- **Modo HF realtime** (voz premium, requiere el asignador de Pollen)
- **Modo local** (Whisper + Qwen con tools + TTS local Piper), sin asignador

Desplegada como Space Docker. Necesita el secret `HF_TOKEN` con permiso de
*Inference Providers* (ya configurado).

Enlace del MCP de tools: <https://huggingface.co/spaces/Alcides777/reachy-mcp-tool>

