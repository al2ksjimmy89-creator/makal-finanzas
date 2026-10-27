"""Resumen total: une el PyG de todos los meses y muestra totales, promedios y evolución."""
import plotly.graph_objects as go
import streamlit as st

import calculos as calc
import db
from ui_comun import CIAN, NEGRO, ROSA, banner, descargar_excel, dinero, estilo_figura, porcentaje, tarjeta

COLUMNAS = ["Ventas", "Materia Prima", "Mano de Obra", "Costos Indirectos", "Total Costos", "Financiamiento",
            "Utilidad Neta"]


def mostrar(con, cliente, anio):
    todos = cliente is None
    nombre = "Todos los clientes" if todos else cliente["nombre"]
    ids = list(db.clientes(con)["id"]) if todos else [int(cliente["id"])]
    periodos = sorted({p for cid in ids for p in calc.periodos_con_datos(con, cid) if p.startswith(str(anio))})
    t = calc.resumen_meses(con, ids, periodos)
    if t.empty:
        banner(f"Resumen total {anio}", nombre)
        st.info("Todavía no hay datos para este año.")
        return

    cerrados = t[t["Mes cerrado"]]
    meta = 0.20 if todos else (cliente["meta_utilidad"] or 0)
    ventas, utilidad = t["Ventas"].sum(), t["Utilidad Neta"].sum()
    costos = (t["Total Costos"] + t["Financiamiento"]).sum()
    banner(f"Resumen total {anio}", f"{nombre} · {len(t)} meses", "Utilidad acumulada", dinero(utilidad, 0))

    c = st.columns(4)
    tarjeta(c[0], "Ventas acumuladas", dinero(ventas, 0), f"{len(t)} meses", "cian")
    tarjeta(c[1], "Costos acumulados", dinero(costos, 0), porcentaje(calc.pct(costos, ventas)) + " de ventas", "rosa")
    prom_u = cerrados["Utilidad Neta"].mean() if len(cerrados) else 0
    prom_v = cerrados["Ventas"].mean() if len(cerrados) else 0
    tarjeta(c[2], "Utilidad promedio / mes", dinero(prom_u, 0), f"ventas {dinero(prom_v, 0)} / mes (meses cerrados)",
            "negro")
    margen_prom = calc.pct(cerrados["Utilidad Neta"].sum(), cerrados["Ventas"].sum()) if len(cerrados) else 0
    tarjeta(c[3], "Margen promedio", porcentaje(margen_prom), f"meta {porcentaje(meta)}", "blanco",
            margen_prom - meta)

    meses = [calc.MESES[int(p[5:]) - 1][:3] + ("*" if not cer else "") for p, cer in zip(t["Periodo"], t["Mes cerrado"])]
    with st.container(border=True, key="caja_r_meses"):
        fig = go.Figure()
        fig.add_bar(x=meses, y=t["Ventas"], name="Ventas", marker_color=CIAN)
        fig.add_bar(x=meses, y=t["Total Costos"] + t["Financiamiento"], name="Costos", marker_color=ROSA)
        fig.add_scatter(x=meses, y=t["Utilidad Neta"], name="Utilidad", mode="lines+markers+text",
                        text=[dinero(v, 0) for v in t["Utilidad Neta"]], textposition="top center",
                        line=dict(color=NEGRO, width=3, shape="spline"), marker=dict(size=9))
        fig.update_layout(title="Ventas, costos y utilidad por mes", barmode="group")
        st.plotly_chart(estilo_figura(fig, 380), width="stretch")

    g1, g2 = st.columns(2)
    with g1.container(border=True, key="caja_r_margen"):
        fig = go.Figure()
        fig.add_scatter(x=meses, y=t["Margen"] * 100, name="Margen %", mode="lines+markers", fill="tozeroy",
                        line=dict(color=CIAN, width=3, shape="spline"), fillcolor="rgba(20,194,236,.15)")
        fig.add_scatter(x=meses, y=[meta * 100] * len(t), name="Meta", line=dict(color=ROSA, dash="dash"))
        fig = estilo_figura(fig.update_layout(title="Margen de utilidad (%)"))
        fig.update_yaxes(tickprefix=None, ticksuffix="%")
        st.plotly_chart(fig, width="stretch")
    with g2.container(border=True, key="caja_r_costos"):
        fig = go.Figure()
        for col, color in (("Materia Prima", CIAN), ("Mano de Obra", ROSA), ("Costos Indirectos", NEGRO)):
            fig.add_bar(x=meses, y=[calc.pct(v, s) * 100 for v, s in zip(t[col], t["Ventas"])], name=col,
                        marker_color=color)
        fig = estilo_figura(fig.update_layout(title="Costos como % de ventas", barmode="stack"))
        fig.update_yaxes(tickprefix=None, ticksuffix="%")
        st.plotly_chart(fig, width="stretch")

    with st.container(border=True, key="caja_r_acum"):
        fig = go.Figure()
        acumulado = t["Utilidad Neta"].cumsum()
        fig.add_scatter(x=meses, y=acumulado, fill="tozeroy", name="Utilidad acumulada", mode="lines+markers",
                        line=dict(color=CIAN if acumulado.iloc[-1] >= 0 else ROSA, width=3, shape="spline"),
                        fillcolor="rgba(20,194,236,.18)")
        fig.update_layout(title="Cómo va el negocio: utilidad acumulada a la fecha")
        st.plotly_chart(estilo_figura(fig, 320, False), width="stretch")

    st.markdown("**PyG mes a mes**")
    tabla = t[["Mes"] + COLUMNAS + ["Margen"]].copy()
    total = {"Mes": "TOTAL", **{c: t[c].sum() for c in COLUMNAS}, "Margen": calc.pct(utilidad, ventas)}
    prom = {"Mes": "PROMEDIO (meses cerrados)", **{c: cerrados[c].mean() if len(cerrados) else 0 for c in COLUMNAS},
            "Margen": margen_prom}
    tabla.loc[len(tabla)] = total
    tabla.loc[len(tabla)] = prom
    vista = tabla.copy()
    for c in COLUMNAS:
        vista[c] = vista[c].map(dinero)
    vista["Margen"] = vista["Margen"].map(porcentaje)
    st.dataframe(vista, hide_index=True, width="stretch")
    st.caption(r"El mes marcado con \* está en curso: se calcula al día de hoy y no entra en los promedios.")
    descargar_excel({"Resumen": tabla}, f"Resumen_{anio}_{nombre}.xlsx".replace(" ", "_"))
