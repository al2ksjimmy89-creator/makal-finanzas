"""Estilos, formatos y gráficos compartidos por todas las pantallas.

Diseño inspirado en el Finance Pro: barra superior en degradé verde azulado a vino, menú lateral oscuro,
fondo claro y tarjetas cian (ventas), rosa (costos) y negras (resultado).
"""
import io
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

CIAN = "#14C2EC"
ROSA = "#FF2E74"
NEGRO = "#1D1D21"
VERDE = "#1FB57A"
AMBAR = "#F5A524"
GRIS = "#9AA1AC"
VIOLETA = "#8B5CF6"
PALETA = [CIAN, ROSA, NEGRO, AMBAR, VIOLETA, VERDE, "#0E7C8C", GRIS]
COLORES_BODEGA = {"Vegetales": VERDE, "Abastos": AMBAR, "Proteínas": ROSA, "Desechables": GRIS,
                  "Pulpas": VIOLETA, "Pan": "#C68A4E"}

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES_MIN = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
             "noviembre", "diciembre"]

CSS = f"""
<style>
/* Barra superior */
.mk-banner {{display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px;
  background:linear-gradient(100deg,#0B4A55 0%,#123A4C 45%,#4A0F2E 80%,#6D0E2C 100%);
  border-radius:18px; padding:16px 22px; color:#fff; margin-bottom:14px;
  box-shadow:0 6px 18px rgba(16,24,40,.18);}}
.mk-banner .t {{font-size:1.45rem; font-weight:700; line-height:1.1; letter-spacing:.01em}}
.mk-banner .s {{font-size:.85rem; opacity:.8; margin-top:3px}}
.mk-banner .kpi {{background:#1D1D21; border-radius:12px; padding:6px 18px; text-align:center; min-width:180px}}
.mk-banner .kpi .l {{font-size:.66rem; letter-spacing:.22em; text-transform:uppercase; opacity:.85}}
.mk-banner .kpi .v {{font-size:1.45rem; font-weight:700}}
.mk-banner .f {{font-size:.85rem; opacity:.9; text-align:right}}
/* Tarjetas */
.mk-card {{border-radius:18px; padding:14px 18px; height:100%; min-height:112px;
  box-shadow:0 4px 14px rgba(16,24,40,.08); background:#fff; color:{NEGRO}; margin-bottom:6px}}
.mk-card .l {{font-size:.72rem; letter-spacing:.16em; text-transform:uppercase; opacity:.85}}
.mk-card .v {{font-size:1.6rem; font-weight:700; margin-top:4px; white-space:nowrap}}
.mk-card .n {{font-size:.8rem; margin-top:2px; opacity:.85}}
.mk-card.cian {{background:linear-gradient(135deg,#22D3F5,#0BA9D3); color:#fff}}
.mk-card.rosa {{background:linear-gradient(135deg,#FF4D8A,#F0145A); color:#fff}}
.mk-card.negro {{background:{NEGRO}; color:#fff}}
.mk-card.blanco .v.pos {{color:{VERDE}}} .mk-card.blanco .v.neg {{color:{ROSA}}}
/* Contenedores de gráficos y formularios */
[class*="st-key-caja"] {{background:#fff; border-radius:18px !important; border:none !important;
  box-shadow:0 4px 14px rgba(16,24,40,.08);}}
/* Pestañas tipo píldora */
.st-key-pestanas [role="tablist"] {{gap:8px; flex-wrap:wrap; border:none; box-shadow:none; padding-bottom:4px}}
.st-key-pestanas [role="tablist"]::after, .st-key-pestanas [role="tablist"]::before {{display:none}}
.st-key-pestanas [role="tab"] {{background:#fff; border-radius:999px !important; padding:7px 16px !important;
  box-shadow:0 2px 8px rgba(16,24,40,.08); border:none !important}}
.st-key-pestanas [role="tab"][aria-selected="true"] {{background:{NEGRO}; color:#fff !important}}
.st-key-pestanas [role="tab"][aria-selected="true"] * {{color:#fff !important}}
.st-key-pestanas [role="tab"]::after {{display:none}}
/* Encabezado del menú lateral */
.mk-side {{text-align:center; padding:6px 0 4px}}
.mk-side .logo {{width:64px; height:64px; border-radius:50%; margin:0 auto 6px;
  background:linear-gradient(135deg,{CIAN},{ROSA}); display:flex; align-items:center; justify-content:center;
  font-size:1.8rem; font-weight:800; color:#fff}}
.mk-side .n {{font-weight:700; letter-spacing:.12em}}
.mk-side .u {{font-size:.8rem; opacity:.75}}
/* Tabla PyG */
.pyg {{width:100%; border-collapse:collapse; font-size:.92rem; background:#fff; border-radius:14px; overflow:hidden}}
.pyg td {{padding:6px 12px; border-bottom:1px solid #EEF0F3}}
.pyg td.num {{text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap}}
.pyg tr.cab td {{background:{NEGRO}; color:#fff; font-weight:700; font-size:.78rem; letter-spacing:.1em}}
.pyg tr.seccion td {{background:#E8F8FD; color:#0B7FA0; font-weight:700; padding-top:10px}}
.pyg tr.sub td {{color:#4B5563; font-weight:600; padding-left:18px}}
.pyg tr.detalle td:first-child {{padding-left:34px; color:#374151}}
.pyg tr.subtotal td {{font-weight:600; border-top:1px solid #D9DEE5}}
.pyg tr.total td {{font-weight:700; background:#F4F6F9}}
.pyg tr.final td {{font-weight:800; font-size:1.05rem; background:{NEGRO}; color:{CIAN}}}
.negativo {{color:{ROSA} !important}}
/* Celular */
@media (max-width: 640px) {{
  .mk-banner {{padding:12px 14px}} .mk-banner .t {{font-size:1.15rem}} .mk-banner .f {{display:none}}
  .mk-banner .kpi {{width:100%}} .mk-card .v {{font-size:1.3rem}} .pyg {{font-size:.8rem}}
  .pyg td {{padding:5px 6px}} .pyg tr.detalle td:first-child {{padding-left:14px}}
}}
</style>
"""


def aplicar_estilo():
    st.html(CSS)


def dinero(v, decimales=2):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    signo = "-" if v < 0 else ""
    return f"{signo}${abs(v):,.{decimales}f}"


def porcentaje(v):
    return "—" if v is None else f"{v * 100:.1f}%"


def md(texto):
    """Evita que Streamlit tome los signos $ como fórmulas matemáticas."""
    return str(texto).replace("$", "\\$")


def html(texto):
    return str(texto).replace("$", "&#36;")


def fecha_larga(d=None):
    import db
    d = d or db.hoy()
    return f"{DIAS[d.weekday()]}, {d.day} de {MESES_MIN[d.month - 1]} de {d.year}"


def banner(titulo, subtitulo, etiqueta_kpi=None, valor_kpi=None):
    kpi = (f"<div class='kpi'><div class='l'>{etiqueta_kpi}</div><div class='v'>{html(valor_kpi)}</div></div>"
           if etiqueta_kpi else "")
    st.html(f"""<div class="mk-banner"><div><div class="t">{titulo}</div><div class="s">{subtitulo}</div></div>
                {kpi}<div class="f">{fecha_larga()}</div></div>""")


def tarjeta(col, etiqueta, valor, nota="", estilo="blanco", signo=None):
    """estilo: cian (ventas), rosa (costos), negro (resultado), blanco (neutral; signo pos/neg colorea el valor)."""
    clase_valor = "" if signo is None else ("pos" if signo >= 0 else "neg")
    col.html(f"""<div class="mk-card {estilo}"><div class="l">{etiqueta}</div>
                 <div class="v {clase_valor}">{html(valor)}</div><div class="n">{html(nota)}</div></div>""")


def estilo_figura(fig, alto=340, leyenda=True):
    fig.update_layout(
        height=alto, margin=dict(l=8, r=8, t=48, b=8), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font=dict(color="#4B5563", size=12), colorway=PALETA,
        title_font=dict(size=15, color=NEGRO), barcornerradius=6, bargap=.28,
        legend=dict(orientation="h", yanchor="top", y=-0.14, x=0) if leyenda else None, showlegend=leyenda,
        hoverlabel=dict(bgcolor="#fff", font_color=NEGRO),
    )
    fig.update_xaxes(gridcolor="#EEF0F3", zeroline=False, showline=False)
    fig.update_yaxes(gridcolor="#EEF0F3", zeroline=False, tickprefix="$", separatethousands=True)
    return fig


def dona(etiquetas, valores, titulo, alto=320, colores=(CIAN, ROSA, NEGRO, AMBAR)):
    fig = go.Figure(go.Pie(labels=etiquetas, values=valores, hole=.68, sort=False,
                           marker=dict(colors=list(colores), line=dict(color="#fff", width=3)),
                           textinfo="percent", textfont=dict(color="#fff", size=13),
                           hovertemplate="%{label}<br>$%{value:,.2f}<extra></extra>"))
    fig.update_layout(title=titulo, annotations=[dict(text=f"<b>{dinero(sum(valores), 0)}</b><br>total",
                                                      showarrow=False, font=dict(size=15, color=NEGRO))])
    fig = estilo_figura(fig, alto)
    fig.update_yaxes(tickprefix=None)
    return fig


def tabla_pyg_html(t, presupuestos=None):
    presupuestos = presupuestos or {}
    filas = []
    for _, f in t.iterrows():
        monto = "" if pd.isna(f["Monto"]) else dinero(f["Monto"])
        pct = "" if pd.isna(f["Monto"]) else porcentaje(f["% Ventas"])
        ppto = presupuestos.get(f["Concepto"])
        ppto_txt = porcentaje(ppto) if ppto is not None else ""
        neg = " negativo" if not pd.isna(f["Monto"]) and f["Monto"] < 0 else ""
        filas.append(f"<tr class='{f['nivel']}'><td>{f['Concepto']}</td><td class='num{neg}'>{monto}</td>"
                     f"<td class='num'>{pct}</td><td class='num'>{ppto_txt}</td></tr>")
    return html("<table class='pyg'><tr class='cab'><td>CONCEPTO</td><td class='num'>MONTO</td>"
                "<td class='num'>% VENTAS</td><td class='num'>PRESUP.</td></tr>" + "".join(filas) + "</table>")


def descargar_excel(hojas: dict, nombre_archivo, etiqueta="Descargar en Excel"):
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as w:
        for nombre, d in hojas.items():
            d.to_excel(w, sheet_name=nombre[:31], index=False)
    st.download_button(etiqueta, buffer.getvalue(), file_name=nombre_archivo, icon=":material/download:",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
