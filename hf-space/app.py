"""
Reachy MCP Tool — Space de Hugging Face (con UI).

Expone 14 herramientas como MCP (Gradio `mcp_server=True`) y como UI navegable
(una pestaña por herramienta), para que el Reachy Mini Conversation App
o cualquier cliente MCP las descubra y ejecute.
"""

import gradio as gr

from tools_impl import (
    ARGS_MAP,
    DISPATCH,
    TOOLS,
    calculadora,
    chiste,
    clima,
    convertir_unidades,
    cripto,
    curiosidad,
    dado,
    deportes,
    hora_en,
    monedas,
    noticias,
    sismos,
    traducir,
    wiki_resumen,
)

CATALOGO = "\n".join(
    f"| `{t['name']}` | {t['description']} |" for t in TOOLS
)


def _inputs(name: str):
    comps = []
    for param, default in ARGS_MAP.get(name, []):
        if isinstance(default, bool):
            comps.append(gr.Checkbox(value=default, label=param))
        elif isinstance(default, (int, float)):
            comps.append(gr.Number(value=default, label=param))
        else:
            comps.append(gr.Textbox(value=str(default or ""), label=param))
    return comps


with gr.Blocks(title="Reachy MCP Tool", theme=gr.themes.Soft()) as demo:
    gr.Markdown(
        """
# 🔌 Reachy MCP Tool

**14 herramientas MCP** para el [Reachy Mini Conversation App](https://huggingface.co/spaces/pollen-robotics/reachy_mini_conversation_app)
y cualquier cliente MCP. Prueba cada tool en su pestaña —
o conéctala como MCP en:

`schema:` https://alcides777-reachy-mcp-tool.hf.space/gradio_api/mcp/schema

```bash
# en el robot
reachy-mini-conversation-app tool-spaces add Alcides777/reachy-mcp-tool
```
        """
    )
    gr.Markdown("| Tool | Qué hace |\n|---|---|\n" + CATALOGO)

    with gr.Tabs():
        for _nombre, _fn in DISPATCH.items():
            with gr.Tab(_nombre):
                _ins = _inputs(_nombre)
                if _ins:
                    gr.Interface(fn=_fn, inputs=_ins, outputs="text",
                                 api_name=_nombre, description=_fn.__doc__)
                else:
                    gr.Interface(fn=_fn, inputs=None, outputs="text",
                                 api_name=_nombre, description=_fn.__doc__)

    gr.Markdown(
        "> Datos en vivo: Open-Meteo (clima), Frankfurter/BCE (monedas), "
        "Google News (noticias), CoinGecko (cripto), ESPN (deportes), "
        "USGS (sismos), Wikipedia ES y MyMemory (traducciones). Sin API keys."
    )

if __name__ == "__main__":
    demo.launch(mcp_server=True)
