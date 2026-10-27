"""Pantalla de un mes: Dashboard, PyG, Ventas, Materia Prima, Mano de Obra, Otros gastos y Por pagar."""
from calendar import monthrange
from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import calculos as calc
import db
from ui_comun import (CIAN, COLORES_BODEGA, GRIS, NEGRO, PALETA, ROSA, VERDE, banner, descargar_excel, dinero,
                      dona, estilo_figura, md, porcentaje, tabla_pyg_html, tarjeta)

DINERO = st.column_config.NumberColumn(format="$%.2f", min_value=0.0)


def _version(clave):
    """Número que cambia al guardar, para que las tablas editables se recarguen limpias."""
    return st.session_state.get(f"v_{clave}", 0)


def _guardado(clave, mensaje="Guardado ✔"):
    st.session_state[f"v_{clave}"] = _version(clave) + 1
    st.session_state["aviso"] = mensaje
    st.rerun()


def _fecha_defecto(periodo):
    a, m = map(int, periodo.split("-"))
    hoy = db.hoy()
    return hoy if (hoy.year, hoy.month) == (a, m) else date(a, m, monthrange(a, m)[1])


def _a_fecha(serie):
    return pd.to_datetime(serie, errors="coerce").dt.date


# ================================================================ entrada principal

def mostrar(con, cliente, periodo):
    cid = int(cliente["id"])
    corte_auto = calc.dia_corte(periodo)

    corte = st.session_state.get(f"corte_{periodo}", corte_auto) if corte_auto else 0
    r = calc.pyg(con, cid, periodo, corte)
    banner(calc.nombre_mes(periodo), f"{cliente['nombre']} · análisis al día {corte} de 30",
           "Utilidad del mes", dinero(r["utilidad_neta"]))

    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    ult = calc.ultimo_dia_con_ventas(con, cid, periodo)
    if corte_auto == 0:
        c1.info("Mes futuro: aún no hay datos para analizar.", icon=":material/event:")
    elif corte_auto < 30 and ult and min(ult.day, 30) < corte - 1:
        c1.warning(f"Las raciones están registradas hasta el **{ult:%d/%m}**, pero el análisis va al día "
                   f"**{corte}**. Sueldos y gastos fijos ya cuentan hasta el día {corte}: registra las ventas "
                   f"que faltan para ver la utilidad real.", icon=":material/warning:")
    if corte_auto:
        c2.number_input("Analizar hasta el día", 1, 30, corte_auto, key=f"corte_{periodo}",
                        help="Mes cerrado = 30. Mes en curso = hoy. Todo lo mensual se calcula "
                             "proporcional a este día.")

    pestanas = st.container(key="pestanas")
    tabs = pestanas.tabs([":material/dashboard: Dashboard", ":material/request_quote: PyG",
                          ":material/restaurant: Ventas", ":material/shopping_basket: Materia prima",
                          ":material/groups: Mano de obra", ":material/receipt_long: Otros gastos",
                          ":material/credit_card: Por pagar"])
    with tabs[0]:
        dashboard(con, cliente, periodo, r)
    with tabs[1]:
        pestaña_pyg(con, cliente, periodo, r)
    with tabs[2]:
        pestaña_ventas(con, cid, periodo)
    with tabs[3]:
        pestaña_materia_prima(con, cid, periodo, r)
    with tabs[4]:
        pestaña_mano_obra(con, cid, periodo, r)
    with tabs[5]:
        pestaña_otros_gastos(con, cid, periodo, r)
    with tabs[6]:
        pestaña_por_pagar(con, cid)


# ================================================================ dashboard

def dashboard(con, cliente, periodo, r):
    tv = r["total_ventas"]
    meta = cliente["meta_utilidad"] or 0
    ppto = db.presupuesto(con, int(cliente["id"]))
    margen = calc.pct(r["utilidad_neta"], tv)

    costos = r["costos"] + r["total_fin"]
    c = st.columns(4)
    tarjeta(c[0], "Ventas", dinero(tv), f"al día {r['corte']} de 30", "cian")
    tarjeta(c[1], "Costos", dinero(costos), porcentaje(calc.pct(costos, tv)) + " de las ventas", "rosa")
    tarjeta(c[2], "Utilidad", dinero(r["utilidad_neta"]), f"meta {dinero(tv * meta, 0)}", "negro")
    tarjeta(c[3], "Margen", porcentaje(margen), f"meta {porcentaje(meta)} " + ("✔" if margen >= meta else "✖"),
            "blanco", margen - meta)
    c = st.columns(4)
    for col, nombre, monto, clave in ((c[0], "Materia prima", r["total_mp"], "Materia Prima"),
                                      (c[1], "Mano de obra", r["total_mo"], "Mano de Obra")):
        real, limite = calc.pct(monto, tv), ppto.get(clave)
        nota = f"{porcentaje(real)} de ventas" + (f" · presup. {porcentaje(limite)}" if limite else "")
        tarjeta(col, nombre, dinero(monto), nota, "blanco", (limite - real) if limite else None)
    tarjeta(c[2], "Costos indirectos", dinero(r["indirectos"]),
            porcentaje(calc.pct(r["indirectos"], tv)) + " de ventas", "blanco")
    proy = calc.proyeccion(r)
    if proy and r["corte"] < 30:
        tarjeta(c[3], "Proyección al día 30", dinero(proy["utilidad"]),
                f"ventas {dinero(proy['ventas'], 0)} si sigue igual", "blanco", proy["utilidad"])
    else:
        tarjeta(c[3], "Financiamiento", dinero(r["total_fin"]), "abonos / cuotas del mes", "blanco")

    g1, g2 = st.columns([3, 2])
    diario = db.df(con, """SELECT fecha, SUM(cantidad*precio) AS venta FROM raciones
                           WHERE cliente_id=? AND periodo=? GROUP BY fecha ORDER BY fecha""",
                   (int(cliente["id"]), periodo))
    compras = db.df(con, """SELECT g.fecha, SUM(g.monto) AS compra FROM gastos g JOIN categorias c
                            ON c.id=g.categoria_id WHERE g.cliente_id=? AND g.periodo=? AND c.seccion='MP'
                            GROUP BY g.fecha""", (int(cliente["id"]), periodo))
    with g1.container(border=True, key="caja_d_diario"):
        fig = go.Figure()
        if len(diario):
            fig.add_scatter(x=diario["fecha"], y=diario["venta"], name="Ventas del día", fill="tozeroy",
                            line=dict(color=CIAN, width=3, shape="spline"), fillcolor="rgba(20,194,236,.15)")
        if len(compras):
            fig.add_scatter(x=compras["fecha"], y=compras["compra"], name="Compras de materia prima",
                            mode="lines+markers", line=dict(color=ROSA, width=2.5, shape="spline"))
        st.plotly_chart(estilo_figura(fig.update_layout(title="Ventas y compras por día")), width="stretch")
    with g2.container(border=True, key="caja_d_dona"):
        st.plotly_chart(dona(["Materia prima", "Mano de obra", "Indirectos"],
                             [r["total_mp"], r["total_mo"], r["indirectos"]], "Distribución de costos"),
                        width="stretch")

    g1, g2 = st.columns([2, 3])
    with g1.container(border=True, key="caja_d_resumen"):
        fig = go.Figure(go.Bar(x=["Ventas", "Costos", "Utilidad"], y=[tv, costos, r["utilidad_neta"]],
                               marker_color=[CIAN, ROSA, NEGRO if r["utilidad_neta"] >= 0 else ROSA],
                               text=[dinero(v, 0) for v in (tv, costos, r["utilidad_neta"])], textposition="outside",
                               name="Monto"))
        fig.add_scatter(x=["Ventas", "Costos", "Utilidad"], y=[tv * meta] * 3, mode="lines",
                        line=dict(color=GRIS, dash="dash"), name=f"Meta utilidad ({porcentaje(meta)})")
        st.plotly_chart(estilo_figura(fig.update_layout(title="Resumen financiero")), width="stretch")
    mp = r["categorias"][r["categorias"]["seccion"] == db.MP]
    pct_mp = ppto.get("Materia Prima", 0)
    if len(mp):
        presup = [tv * pct_mp * ppto.get(n, 0) for n in mp["nombre"]]
        with g2.container(border=True, key="caja_d_mp"):
            fig = go.Figure()
            fig.add_bar(y=mp["nombre"], x=presup, orientation="h", name="Presupuesto", marker_color="#DDE3EA")
            fig.add_bar(y=mp["nombre"], x=mp["monto"], orientation="h", name="Real",
                        marker_color=[ROSA if real > p > 0 else CIAN for real, p in zip(mp["monto"], presup)],
                        text=[dinero(v, 0) for v in mp["monto"]], textposition="outside")
            fig.update_layout(title="Materia prima por bodega: real vs presupuesto", barmode="group")
            fig = estilo_figura(fig)
            fig.update_yaxes(tickprefix=None)
            fig.update_xaxes(tickprefix="$")
            st.plotly_chart(fig, width="stretch")

    rac = calc.raciones_por_servicio(con, int(cliente["id"]), periodo)
    if len(rac):
        with st.container(border=True, key="caja_d_raciones"):
            fig = go.Figure()
            for i, (grupo, d) in enumerate(rac.groupby("grupo")):
                fig.add_bar(x=d["servicio"], y=d["cantidad"], name=grupo, marker_color=PALETA[i % len(PALETA)],
                            text=d["cantidad"].map("{:,.0f}".format), textposition="outside")
            fig = estilo_figura(fig.update_layout(title="Raciones servidas en el mes"), 300)
            fig.update_yaxes(tickprefix=None)
            st.plotly_chart(fig, width="stretch")


# ================================================================ PyG

def pestaña_pyg(con, cliente, periodo, r):
    ppto = db.presupuesto(con, int(cliente["id"]))
    t = calc.tabla_pyg(r)
    pres = {"Total Materia Prima": ppto.get("Materia Prima"), "Total Mano de Obra": ppto.get("Mano de Obra")}
    for n in r["categorias"][r["categorias"]["seccion"] == db.MP]["nombre"]:
        if ppto.get(n) is not None and ppto.get("Materia Prima"):
            pres[n] = ppto[n] * ppto["Materia Prima"]
    if cliente["meta_utilidad"]:
        pres["UTILIDAD FINAL NETA"] = cliente["meta_utilidad"]
    st.html(tabla_pyg_html(t, pres))
    st.caption(f"Análisis al día {r['corte']} de 30. Sueldos y gastos fijos proporcionales al día de corte. "
               "La columna Presupuesto es el % sobre ventas asignado al cliente.")
    exportar = t[t["Monto"].notna()][["Concepto", "Monto", "% Ventas"]]
    descargar_excel({"PyG": exportar, "Rol de pagos": r["rol"].drop(columns=["empleado_id"], errors="ignore")},
                    f"PyG_{cliente['nombre']}_{periodo}.xlsx".replace(" ", "_"))


# ================================================================ ventas

def pestaña_ventas(con, cid, periodo):
    lineas = calc.ventas(con, cid, periodo)
    if lineas:
        c = st.columns(len(lineas) + 1)
        for col, (concepto, monto) in zip(c, lineas):
            col.metric(concepto, dinero(monto))
        c[-1].metric("TOTAL VENTAS", dinero(sum(m for _, m in lineas)))

    servicios = db.df(con, "SELECT * FROM servicios_cliente WHERE cliente_id=? AND activo=1 ORDER BY grupo, orden",
                      (cid,))
    if servicios.empty:
        st.info("Este cliente no tiene servicios configurados. Ve a ⚙️ Configuración → Clientes.")
    for grupo, serv in servicios.groupby("grupo", sort=False):
        with st.expander(f"Raciones diarias · {grupo}", expanded=True):
            editor_raciones(con, cid, periodo, grupo, serv)

    personas = db.df(con, "SELECT * FROM personas_mensuales WHERE cliente_id=? AND activo=1 ORDER BY grupo, id",
                     (cid,))
    for grupo, pers in personas.groupby("grupo", sort=False):
        with st.expander(f"Pago mensual fijo · {grupo} (se registra a fin de mes)"):
            editor_mensuales(con, cid, periodo, pers)

    with st.expander("Ventas adicionales · personal externo, eventos extras", expanded=True):
        editor_ventas_extra(con, cid, periodo)


def editor_raciones(con, cid, periodo, grupo, serv):
    a, m = map(int, periodo.split("-"))
    existentes = db.df(con, """SELECT fecha, servicio, cantidad, precio FROM raciones
                               WHERE cliente_id=? AND periodo=? AND grupo=?""", (cid, periodo, grupo))
    fechas = sorted({date(a, m, d) for d in range(1, monthrange(a, m)[1] + 1)} |
                    {date.fromisoformat(f) for f in existentes["fecha"]})
    nombres = list(serv["servicio"])
    tabla = pd.DataFrame({"Fecha": fechas})
    for s in nombres:
        mapa = existentes[existentes["servicio"] == s].set_index("fecha")["cantidad"].to_dict()
        tabla[s] = [mapa.get(f.isoformat(), 0) for f in fechas]
    precios = dict(zip(serv["servicio"], serv["precio"]))
    st.caption(md("Precios: " + " · ".join(f"{s} {dinero(p)}" for s, p in precios.items())))
    clave = f"rac_{cid}_{periodo}_{grupo}"
    editado = st.data_editor(
        tabla, hide_index=True, width="stretch", height=420, key=f"{clave}_{_version(clave)}",
        column_config={"Fecha": st.column_config.DateColumn(disabled=True, format="DD/MM/YYYY"),
                       **{s: st.column_config.NumberColumn(min_value=0, step=1, format="%d") for s in nombres}})
    totales = {s: editado[s].sum() for s in nombres}
    st.write(md(" · ".join(f"**{s}:** {totales[s]:,.0f} = {dinero(totales[s] * precios[s])}" for s in nombres)))
    if st.button("💾 Guardar raciones", key=f"g_{clave}"):
        anteriores = {(f, s): p for f, s, p in existentes[["fecha", "servicio", "precio"]].itertuples(index=False)}
        for _, fila in editado.iterrows():
            f = fila["Fecha"].isoformat()
            for s in nombres:
                cant = float(fila[s] or 0)
                if cant:
                    precio = anteriores.get((f, s), precios[s])  # se respeta el precio con que se registró
                    con.execute("""INSERT INTO raciones (cliente_id, periodo, fecha, grupo, servicio, cantidad, precio)
                                   VALUES (?,?,?,?,?,?,?) ON CONFLICT(cliente_id, periodo, fecha, grupo, servicio)
                                   DO UPDATE SET cantidad=excluded.cantidad""",
                                (cid, periodo, f, grupo, s, cant, precio))
                else:
                    con.execute("""DELETE FROM raciones WHERE cliente_id=? AND periodo=? AND fecha=? AND grupo=?
                                   AND servicio=?""", (cid, periodo, f, grupo, s))
        con.commit()
        _guardado(clave)


def editor_mensuales(con, cid, periodo, pers):
    actuales = db.df(con, "SELECT persona_id, monto FROM ventas_mensuales WHERE periodo=? AND cliente_id=?",
                     (periodo, cid)).set_index("persona_id")["monto"].to_dict()
    clave = f"men_{cid}_{periodo}_{pers['grupo'].iloc[0]}"
    if st.button("Llenar con el valor fijo de cada persona", key=f"llenar_{clave}"):
        st.session_state[f"lleno_{clave}"] = True
        st.session_state[f"v_{clave}"] = _version(clave) + 1
    lleno = st.session_state.get(f"lleno_{clave}", False)
    tabla = pd.DataFrame({
        "persona_id": pers["id"], "Nombre": pers["nombre"], "Grado": pers["grado"],
        "Valor fijo": pers["valor_mensual"],
        "Monto del mes": [actuales.get(i, v if lleno else 0.0) for i, v in zip(pers["id"], pers["valor_mensual"])],
    })
    editado = st.data_editor(tabla, hide_index=True, width="stretch", key=f"{clave}_{_version(clave)}",
                             column_config={"persona_id": None, "Nombre": st.column_config.TextColumn(disabled=True),
                                            "Grado": st.column_config.TextColumn(disabled=True),
                                            "Valor fijo": st.column_config.NumberColumn(format="$%.2f", disabled=True),
                                            "Monto del mes": DINERO})
    st.write(md(f"**Total del mes:** {dinero(editado['Monto del mes'].sum())}"))
    if st.button("💾 Guardar pagos mensuales", key=f"g_{clave}"):
        for _, f in editado.iterrows():
            if f["Monto del mes"]:
                con.execute("""INSERT INTO ventas_mensuales (cliente_id, periodo, persona_id, monto) VALUES (?,?,?,?)
                               ON CONFLICT(periodo, persona_id) DO UPDATE SET monto=excluded.monto""",
                            (cid, periodo, int(f["persona_id"]), float(f["Monto del mes"])))
            else:
                con.execute("DELETE FROM ventas_mensuales WHERE periodo=? AND persona_id=?",
                            (periodo, int(f["persona_id"])))
        con.commit()
        st.session_state.pop(f"lleno_{clave}", None)
        _guardado(clave)


def editor_ventas_extra(con, cid, periodo):
    datos = db.df(con, """SELECT id, fecha, tipo, detalle, monto, forma_pago, cobrado FROM ventas_extra
                          WHERE cliente_id=? AND periodo=? ORDER BY fecha, id""", (cid, periodo))
    datos["fecha"] = _a_fecha(datos["fecha"])
    datos["cobrado"] = datos["cobrado"].fillna(1).astype(bool)
    clave = f"vex_{cid}_{periodo}"
    editado = st.data_editor(
        datos, hide_index=True, width="stretch", num_rows="dynamic", key=f"{clave}_{_version(clave)}",
        column_config={
            "id": None,
            "fecha": st.column_config.DateColumn("Fecha", default=_fecha_defecto(periodo), format="DD/MM/YYYY"),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=db.TIPOS_VENTA_EXTRA, required=True,
                                                     default="Personal externo"),
            "detalle": st.column_config.TextColumn("Detalle (persona / evento)"),
            "monto": st.column_config.NumberColumn("Monto", format="$%.2f", min_value=0.0),
            "forma_pago": st.column_config.SelectboxColumn("Forma de pago", options=db.FORMAS_PAGO),
            "cobrado": st.column_config.CheckboxColumn("Cobrado", default=True),
        })
    st.write(md(f"**Total ventas adicionales:** {dinero(editado['monto'].fillna(0).sum())}"))
    if st.button("💾 Guardar ventas adicionales", key=f"g_{clave}"):
        editado = editado.assign(fecha=editado["fecha"].map(db.a_texto_fecha),
                                 cobrado=editado["cobrado"].fillna(True).astype(int))
        db.guardar_editor(con, "ventas_extra", editado, datos["id"].tolist(),
                          ["fecha", "tipo", "detalle", "monto", "forma_pago", "cobrado"],
                          {"cliente_id": cid, "periodo": periodo}, lambda d: d["monto"] and d["tipo"])
        _guardado(clave)


# ================================================================ gastos (materia prima y otros)

def form_registro_gasto(con, cid, periodo, secciones, clave, titulo):
    """Registro rápido de una compra: primero la bodega, luego solo los proveedores de esa bodega."""
    cats = db.categorias(con, secciones)
    with st.container(border=True, key=f"caja_reg_{clave}"):
        st.markdown(f"**{titulo}**")
        c1, c2, c3 = st.columns([1.1, 1.4, 1])
        bodega = c1.selectbox("Bodega", cats["nombre"], key=f"reg_bod_{clave}")
        cat = cats[cats["nombre"] == bodega].iloc[0]
        provs = db.df(con, "SELECT id, nombre, producto FROM proveedores WHERE activo=1 AND categoria_id=? "
                           "ORDER BY nombre", (int(cat["id"]),))
        etiquetas = {int(i): f"{n} · {p}" if p else n
                     for i, n, p in zip(provs["id"], provs["nombre"], provs["producto"])}
        opciones = list(etiquetas) + [None]
        prov_id = c2.selectbox("Proveedor", opciones, key=f"reg_prov_{clave}_{bodega}",
                               format_func=lambda i: etiquetas.get(i, "Sin proveedor / compra local"))
        fecha = c3.date_input("Fecha", _fecha_defecto(periodo), format="DD/MM/YYYY", key=f"reg_fecha_{clave}")
        por_cantidad = pd.notna(cat["precio_defecto"])  # Pan, GLP: se registra cantidad x precio
        c1, c2, c3, c4 = st.columns([1, 1, 1.4, .8], vertical_alignment="bottom")
        if por_cantidad:
            cantidad = c1.number_input(f"Cantidad ({cat['unidad'] or 'unidades'})", 0.0, step=1.0,
                                       key=f"reg_cant_{clave}_{bodega}")
            precio = c2.number_input("Precio unitario", 0.0, value=float(cat["precio_defecto"]), step=0.01,
                                     format="%.3f", key=f"reg_pu_{clave}_{bodega}")
            monto = cantidad * precio
            c2.caption(md(f"Valor: {dinero(monto)}"))
        else:
            cantidad = precio = None
            monto = c1.number_input("Valor ($)", 0.0, step=1.0, format="%.2f", key=f"reg_val_{clave}")
            factura = c2.text_input("N° factura", key=f"reg_fac_{clave}")
        detalle = c3.text_input("Detalle (opcional)", key=f"reg_det_{clave}")
        pagado = c4.toggle("Pagado", key=f"reg_pag_{clave}")
        if st.button("Agregar compra", icon=":material/add_circle:", type="primary", key=f"reg_btn_{clave}"):
            if not monto:
                st.error("Escribe el valor de la compra.")
            else:
                con.execute("""INSERT INTO gastos (cliente_id, periodo, fecha, categoria_id, proveedor_id, detalle,
                               cantidad, precio_unit, monto, n_factura, pagado) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                            (cid, periodo, fecha.isoformat(), int(cat["id"]), prov_id, detalle or None, cantidad,
                             precio, monto, None if por_cantidad else (factura or None), int(pagado)))
                con.commit()
                _guardado(clave, f"Compra de {dinero(monto)} agregada ✔")


def editor_gastos(con, cid, periodo, secciones, clave, proveedores_secciones=None):
    cats = db.categorias(con, secciones)
    provs = db.proveedores(con, proveedores_secciones)
    datos = db.df(con, f"""SELECT g.id, g.fecha, c.nombre AS categoria, p.nombre AS proveedor, g.detalle,
                              g.cantidad, g.precio_unit, g.monto, g.n_factura, g.pagado
                           FROM gastos g JOIN categorias c ON c.id=g.categoria_id
                           LEFT JOIN proveedores p ON p.id=g.proveedor_id
                           WHERE g.cliente_id=? AND g.periodo=? AND c.seccion IN ({','.join('?' * len(secciones))})
                           ORDER BY g.fecha, c.orden, g.id""", (cid, periodo, *secciones))
    datos["fecha"] = _a_fecha(datos["fecha"])
    datos["pagado"] = datos["pagado"].fillna(0).astype(bool)
    # proveedores del cuadro + los antiguos que aparezcan en compras ya registradas
    todos = db.df(con, "SELECT id, nombre, categoria_id FROM proveedores")
    nombres_prov = list(provs["nombre"]) + sorted(set(datos["proveedor"].dropna()) - set(provs["nombre"]))
    editado = st.data_editor(
        datos, hide_index=True, width="stretch", num_rows="dynamic", height=420,
        key=f"{clave}_{_version(clave)}",
        column_config={
            "id": None,
            "fecha": st.column_config.DateColumn("Fecha", default=_fecha_defecto(periodo), format="DD/MM/YYYY"),
            "categoria": st.column_config.SelectboxColumn("Bodega", options=list(cats["nombre"])),
            "proveedor": st.column_config.SelectboxColumn("Proveedor", options=nombres_prov),
            "detalle": st.column_config.TextColumn("Detalle"),
            "cantidad": st.column_config.NumberColumn("Cant.", min_value=0.0),
            "precio_unit": st.column_config.NumberColumn("P. unit.", format="$%.3f", min_value=0.0),
            "monto": st.column_config.NumberColumn("Valor", format="$%.2f", min_value=0.0,
                                                   help="Si lo dejas vacío y pones cantidad y precio, se calcula solo."),
            "n_factura": st.column_config.TextColumn("N° factura"),
            "pagado": st.column_config.CheckboxColumn("Pagado", default=False),
        })
    st.caption("Aquí corriges o borras compras ya registradas (para borrar: selecciona la fila a la izquierda y "
               "presiona Supr). Si dejas la bodega vacía, se toma la del proveedor. Luego presiona Guardar cambios.")
    if st.button("Guardar cambios", icon=":material/save:", key=f"g_{clave}"):
        id_cat = dict(zip(cats["nombre"], cats["id"]))
        id_prov = dict(zip(todos["nombre"], todos["id"]))
        bodega_prov = dict(zip(todos["nombre"], todos["categoria_id"]))
        precio_def = dict(zip(cats["nombre"], cats["precio_defecto"]))
        e = editado.copy()
        e["categoria_id"] = [id_cat.get(c) if pd.notna(c) else bodega_prov.get(p)
                             for c, p in zip(e["categoria"], e["proveedor"])]
        e["proveedor_id"] = e["proveedor"].map(id_prov)
        e["precio_unit"] = [p if pd.notna(p) else (precio_def.get(c) if pd.notna(q) and q else None)
                            for p, q, c in zip(e["precio_unit"], e["cantidad"], e["categoria"])]
        e["monto"] = [mo if pd.notna(mo) and mo else (q * p if pd.notna(q) and pd.notna(p) and q and p else None)
                      for mo, q, p in zip(e["monto"], e["cantidad"], e["precio_unit"])]
        e["fecha"] = [db.a_texto_fecha(f) or _fecha_defecto(periodo).isoformat() for f in e["fecha"]]
        e["pagado"] = e["pagado"].fillna(False).astype(int)
        db.guardar_editor(con, "gastos", e, datos["id"].tolist(),
                          ["fecha", "categoria_id", "proveedor_id", "detalle", "cantidad", "precio_unit", "monto",
                           "n_factura", "pagado"],
                          {"cliente_id": cid, "periodo": periodo}, lambda d: d["monto"] and d["categoria_id"])
        _guardado(clave)
    return datos


def _semana_del_mes(fecha, periodo):
    """Semanas fijas del mes: 1-7, 8-14, 15-21, 22-28, 29-31. Fechas de otro mes van a la primera/última."""
    a, m = map(int, periodo.split("-"))
    f = pd.Timestamp(fecha)
    dia = 1 if (f.year, f.month) < (a, m) else (31 if (f.year, f.month) > (a, m) else f.day)
    return min((dia - 1) // 7 + 1, 5)


ETIQUETA_SEMANA = {1: "Sem 1 (1-7)", 2: "Sem 2 (8-14)", 3: "Sem 3 (15-21)", 4: "Sem 4 (22-28)", 5: "Sem 5 (29-31)"}


def grafico_compras_semana(con, cid, periodo, datos, pct_mp):
    """Compras de materia prima por semana (apiladas por bodega) con el total, y la línea del presupuesto
    (pct_mp de las ventas de esa semana). Debajo, el acumulado del mes contra el presupuesto acumulado."""
    d = datos.dropna(subset=["fecha", "monto"]).copy()
    d["sem"] = [_semana_del_mes(f, periodo) for f in d["fecha"]]
    ventas = db.df(con, """SELECT fecha, SUM(monto) AS venta FROM (
                             SELECT fecha, cantidad*precio AS monto FROM raciones WHERE cliente_id=? AND periodo=?
                             UNION ALL SELECT fecha, monto FROM ventas_extra WHERE cliente_id=? AND periodo=?) AS v
                           GROUP BY fecha""", (cid, periodo, cid, periodo))
    ventas["sem"] = [_semana_del_mes(f, periodo) for f in ventas["fecha"]]
    semanas = [s for s in range(1, 6) if s in set(d["sem"]) | set(ventas["sem"])]
    if not semanas:
        return
    x = [ETIQUETA_SEMANA[s] for s in semanas]
    compras = d.groupby("sem")["monto"].sum().reindex(semanas, fill_value=0)
    presup = ventas.groupby("sem")["venta"].sum().reindex(semanas, fill_value=0) * pct_mp

    fig = go.Figure()
    for i, (bodega, g) in enumerate(d.groupby("categoria", sort=False)):
        fig.add_bar(x=x, y=g.groupby("sem")["monto"].sum().reindex(semanas, fill_value=0), name=bodega,
                    marker_color=COLORES_BODEGA.get(bodega, PALETA[i % len(PALETA)]))
    fig.add_scatter(x=x, y=compras, mode="text", text=[f"<b>{dinero(v, 0)}</b>" for v in compras],
                    textposition="top center", showlegend=False, hoverinfo="skip",
                    textfont=dict(color=[ROSA if c > p > 0 else NEGRO for c, p in zip(compras, presup)], size=13))
    fig.add_scatter(x=x, y=presup, name=f"Presupuesto MP ({porcentaje(pct_mp)} de ventas)", mode="lines+markers",
                    line=dict(color=NEGRO, width=3, shape="spline", dash="dot"),
                    marker=dict(size=9, color=[ROSA if c > p > 0 else CIAN for c, p in zip(compras, presup)],
                                line=dict(color="white", width=2)))
    fig.update_layout(title="Compras de materia prima por semana", barmode="stack",
                      yaxis_range=[0, max(compras.max(), presup.max()) * 1.18])
    with st.container(border=True, key="caja_g_semana"):
        st.plotly_chart(estilo_figura(fig, 400), width="stretch")
        excedidas = [ETIQUETA_SEMANA[s] for s, c, p in zip(semanas, compras, presup) if c > p > 0]
        if excedidas:
            st.caption(md(f":red[**Sobre el presupuesto:**] {', '.join(excedidas)}. El total de la semana en rosa "
                          "indica que se compró más del % asignado sobre lo vendido esa semana."))

    acum_c, acum_p = compras.cumsum(), presup.cumsum()
    fig = go.Figure()
    fig.add_scatter(x=x, y=acum_p, name="Presupuesto acumulado", line=dict(color=CIAN, width=3, shape="spline"),
                    fill="tozeroy", fillcolor="rgba(31,200,240,.12)")
    fig.add_scatter(x=x, y=acum_c, name="Compras acumuladas", mode="lines+markers+text",
                    line=dict(color=ROSA, width=3, shape="spline"), text=[dinero(v, 0) for v in acum_c],
                    textposition="top left")
    fig.update_layout(title="Acumulado del mes: compras vs presupuesto")
    with st.container(border=True, key="caja_g_acum"):
        st.plotly_chart(estilo_figura(fig, 320), width="stretch")


def pestaña_materia_prima(con, cid, periodo, r):
    ppto = db.presupuesto(con, cid)
    mp = r["categorias"][r["categorias"]["seccion"] == db.MP]
    base = r["total_ventas"] * ppto.get("Materia Prima", 0)
    with st.container(horizontal=True):
        for _, f in mp.iterrows():
            limite = base * ppto.get(f["nombre"], 0)
            dif = limite - f["monto"]
            st.metric(f["nombre"], dinero(f["monto"], 0),
                      f"{'quedan' if dif >= 0 else 'excede'} {dinero(abs(dif), 0)}" if limite else None,
                      delta_color="normal" if dif >= 0 else "inverse", delta_arrow="off", border=True)
        st.metric("Total materia prima", dinero(r["total_mp"], 0), f"presupuesto {dinero(base, 0)}",
                  delta_color="off", delta_arrow="off", border=True)

    clave = f"mp_{cid}_{periodo}"
    form_registro_gasto(con, cid, periodo, [db.MP], clave, "Registrar compra")
    datos = editor_gastos(con, cid, periodo, [db.MP], clave, [db.MP])

    if len(datos):
        grafico_compras_semana(con, cid, periodo, datos, ppto.get("Materia Prima", 0.45))
        prov = datos.fillna({"proveedor": "Sin proveedor"}).groupby("proveedor")["monto"].sum().sort_values()
        fig = go.Figure(go.Bar(x=prov.values, y=prov.index, orientation="h", marker_color=CIAN,
                               text=[dinero(v, 0) for v in prov.values], textposition="outside"))
        with st.container(border=True, key="caja_g_prov"):
            st.plotly_chart(estilo_figura(fig.update_layout(title="Compras por proveedor"),
                                          max(260, 30 * len(prov)), False), width="stretch")


def pestaña_otros_gastos(con, cid, periodo, r):
    cat = r["categorias"]
    otros = cat[cat["seccion"].isin([db.IND, db.MANT, db.FIN]) & (cat["monto"] != 0)]
    if len(otros):
        with st.container(horizontal=True):
            for _, f in otros.iterrows():
                st.metric(f["nombre"], dinero(f["monto"]), border=True)
    clave = f"og_{cid}_{periodo}"
    form_registro_gasto(con, cid, periodo, [db.IND, db.MANT, db.FIN], clave, "Registrar gasto")
    editor_gastos(con, cid, periodo, [db.IND, db.MANT, db.FIN], clave)
    fijos = cat[cat["fijo_prorrateado"] > 0]
    if len(fijos):
        st.markdown("**Gastos fijos mensuales incluidos (proporcionales al día de corte)**")
        st.dataframe(pd.DataFrame({"Categoría": fijos["nombre"], "Mensual": fijos["mensual"].map(dinero),
                                   f"Al día {r['corte']}": fijos["fijo_prorrateado"].map(dinero)}),
                     hide_index=True, width="stretch")
    st.caption("Los gastos que se repiten cada mes (arriendo, TV, cuota de préstamo) se configuran una sola vez en "
               "⚙️ Configuración → Gastos fijos.")


# ================================================================ mano de obra

def pestaña_mano_obra(con, cid, periodo, r):
    rol = r["rol"]
    cerrado = calc.rol_cerrado(con, cid, periodo)
    ppto = db.presupuesto(con, cid)
    limite = r["total_ventas"] * ppto.get("Mano de Obra", 0)
    c = st.columns(4)
    tarjeta(c[0], "Costo mano de obra", dinero(r["total_mo"]), f"al día {r['corte']}", "rosa")
    tarjeta(c[1], "Presupuesto", dinero(limite), porcentaje(ppto.get("Mano de Obra")) + " de ventas", "cian")
    tarjeta(c[2], "Diferencia", dinero(limite - r["total_mo"]), "a favor" if limite >= r["total_mo"] else "excedido",
            "blanco", limite - r["total_mo"])
    tarjeta(c[3], "Neto a pagar", dinero(rol["Neto a pagar"].sum() if len(rol) else 0), "después de descuentos",
            "negro")
    st.write("")

    if cerrado:
        st.success("🔒 Rol de este mes **cerrado**: se usan los días y sueldos guardados al cerrarlo.")
    if len(rol):
        vista = rol.drop(columns=["empleado_id"])
        st.dataframe(vista, hide_index=True, width="stretch", column_config={
            c: st.column_config.NumberColumn(format="$%.2f") for c in vista.columns
            if c not in ("Nombre", "Cargo", "Contrato", "Días")})

    if not cerrado:
        with st.expander("✏️ Novedades del mes (días distintos, horas extras)"):
            editor_novedades(con, cid, periodo, r["corte"])
    with st.expander("➖ Descuentos y adelantos"):
        editor_descuentos(con, cid, periodo)
    with st.expander("👥 Personal (agregar, editar sueldo, fecha de salida, tipo de contrato)"):
        editor_empleados(con, cid)

    st.divider()
    if cerrado:
        if st.button("🔓 Reabrir rol de este mes"):
            calc.reabrir_rol(con, cid, periodo)
            _guardado(f"mo_{cid}", "Rol reabierto")
    else:
        st.write("Al terminar el mes, **cierra el rol**: guarda una foto de días y sueldos, así un aumento futuro "
                 "no cambia meses pasados.")
        if st.button(f"🔒 Cerrar rol de {calc.nombre_mes(periodo)}", disabled=r["corte"] < 30 and
                     calc.dia_corte(periodo) < 30, help="Se habilita cuando el mes terminó."):
            calc.cerrar_rol(con, cid, periodo)
            _guardado(f"mo_{cid}", "Rol cerrado ✔")


def editor_novedades(con, cid, periodo, corte):
    emp = db.df(con, "SELECT id, nombre, cargo FROM empleados WHERE cliente_id=? AND activo=1 ORDER BY id", (cid,))
    nov = db.df(con, "SELECT * FROM novedades_rol WHERE periodo=?", (periodo,)).set_index("empleado_id")
    tabla = pd.DataFrame({
        "empleado_id": emp["id"], "Nombre": emp["nombre"], "Cargo": emp["cargo"],
        "Días (vacío = automático)": [nov.loc[i, "dias"] if i in nov.index else None for i in emp["id"]],
        "Horas extras / otros pagos": [nov.loc[i, "extras"] if i in nov.index else 0.0 for i in emp["id"]],
        "Observación": [nov.loc[i, "observacion"] if i in nov.index else None for i in emp["id"]],
    })
    clave = f"nov_{cid}_{periodo}"
    st.caption(f"Automático = días desde el ingreso hasta el día {corte} (o hasta la fecha de salida). "
               "Pon un número solo si faltó o trabajó distinto.")
    editado = st.data_editor(tabla, hide_index=True, width="stretch", key=f"{clave}_{_version(clave)}",
                             column_config={"empleado_id": None,
                                            "Nombre": st.column_config.TextColumn(disabled=True),
                                            "Cargo": st.column_config.TextColumn(disabled=True),
                                            "Días (vacío = automático)": st.column_config.NumberColumn(min_value=0,
                                                                                                       max_value=30),
                                            "Horas extras / otros pagos": DINERO})
    if st.button("💾 Guardar novedades", key=f"g_{clave}"):
        for _, f in editado.iterrows():
            dias, extras, obs = (db.limpio(f["Días (vacío = automático)"]), db.limpio(f["Horas extras / otros pagos"]),
                                 db.limpio(f["Observación"]))
            if dias is None and not extras and not obs:
                con.execute("DELETE FROM novedades_rol WHERE empleado_id=? AND periodo=?",
                            (int(f["empleado_id"]), periodo))
            else:
                con.execute("""INSERT INTO novedades_rol (empleado_id, periodo, dias, extras, observacion)
                               VALUES (?,?,?,?,?) ON CONFLICT(empleado_id, periodo) DO UPDATE SET
                               dias=excluded.dias, extras=excluded.extras, observacion=excluded.observacion""",
                            (int(f["empleado_id"]), periodo, dias, extras or 0, obs))
        con.commit()
        _guardado(clave)


def editor_descuentos(con, cid, periodo):
    emp = db.df(con, "SELECT id, nombre, cargo, activo FROM empleados WHERE cliente_id=? ORDER BY activo DESC, nombre",
                (cid,))
    etiqueta = {i: f"{n} ({c})" for i, n, c in zip(emp["id"], emp["nombre"], emp["cargo"])}
    datos = db.df(con, """SELECT d.id, d.empleado_id, d.periodo_inicio, d.tipo, d.motivo, d.monto_total, d.cuotas
                          FROM descuentos d JOIN empleados e ON e.id=d.empleado_id WHERE e.cliente_id=?
                          ORDER BY d.periodo_inicio DESC, d.id""", (cid,))
    datos.insert(1, "Empleado", datos["empleado_id"].map(etiqueta))
    datos = datos.drop(columns=["empleado_id"])
    st.caption("**Adelanto de sueldo**: solo baja lo que se le paga. **Recupera gasto de la empresa** (ej. zapatos "
               "que pagó la empresa y descuenta al trabajador): además resta del costo de mano de obra, para no "
               "contar el gasto dos veces. Un descuento en varias cuotas se reparte solo en los meses siguientes.")
    clave = f"desc_{cid}"
    editado = st.data_editor(
        datos, hide_index=True, width="stretch", num_rows="dynamic", key=f"{clave}_{_version(clave)}",
        column_config={
            "id": None,
            "Empleado": st.column_config.SelectboxColumn(options=list(etiqueta.values()), required=True),
            "periodo_inicio": st.column_config.TextColumn("Desde (AAAA-MM)", default=periodo, required=True,
                                                         validate=r"^\d{4}-\d{2}$"),
            "tipo": st.column_config.SelectboxColumn("Tipo", options=db.TIPOS_DESCUENTO, required=True,
                                                     default=db.TIPOS_DESCUENTO[0]),
            "motivo": st.column_config.TextColumn("Motivo"),
            "monto_total": st.column_config.NumberColumn("Monto total", format="$%.2f", min_value=0.0),
            "cuotas": st.column_config.NumberColumn("Cuotas (meses)", min_value=1, step=1, default=1),
        })
    if st.button("💾 Guardar descuentos", key=f"g_{clave}"):
        inverso = {v: k for k, v in etiqueta.items()}
        e = editado.assign(empleado_id=editado["Empleado"].map(inverso), cuotas=editado["cuotas"].fillna(1))
        db.guardar_editor(con, "descuentos", e, datos["id"].tolist(),
                          ["empleado_id", "periodo_inicio", "tipo", "motivo", "monto_total", "cuotas"],
                          fila_valida=lambda d: d["empleado_id"] and d["monto_total"] and d["periodo_inicio"])
        _guardado(clave)


def editor_empleados(con, cid):
    datos = db.df(con, """SELECT id, cedula, nombre, cargo, sueldo, bono, tipo_contrato, fecha_ingreso, fecha_salida,
                          activo FROM empleados WHERE cliente_id=? ORDER BY activo DESC, id""", (cid,))
    for c in ("fecha_ingreso", "fecha_salida"):
        datos[c] = _a_fecha(datos[c])
    datos["activo"] = datos["activo"].fillna(1).astype(bool)
    clave = f"emp_{cid}"
    editado = st.data_editor(
        datos, hide_index=True, width="stretch", num_rows="dynamic", key=f"{clave}_{_version(clave)}",
        column_config={
            "id": None, "cedula": "Cédula", "nombre": st.column_config.TextColumn("Nombre", required=True),
            "cargo": "Cargo", "sueldo": st.column_config.NumberColumn("Sueldo mensual", format="$%.2f", min_value=0.0),
            "bono": st.column_config.NumberColumn("Bono mensual", format="$%.2f", min_value=0.0, default=0.0),
            "tipo_contrato": st.column_config.SelectboxColumn("Contrato", options=db.TIPOS_CONTRATO,
                                                              default=db.TIPOS_CONTRATO[0], required=True),
            "fecha_ingreso": st.column_config.DateColumn("Ingreso", format="DD/MM/YYYY"),
            "fecha_salida": st.column_config.DateColumn("Salida", format="DD/MM/YYYY"),
            "activo": st.column_config.CheckboxColumn("Activo", default=True),
        })
    st.caption("**Relación de dependencia** suma aporte patronal IESS, décimos, vacaciones y fondos de reserva. "
               "**Prestación de servicios** solo suma sueldo y bono. Al poner fecha de salida, deja de contar "
               "desde ese día.")
    if st.button("💾 Guardar personal", key=f"g_{clave}"):
        e = editado.copy()
        for c in ("fecha_ingreso", "fecha_salida"):
            e[c] = e[c].map(db.a_texto_fecha)
        e["activo"] = e["activo"].fillna(True).astype(int)
        e["bono"] = e["bono"].fillna(0)
        db.guardar_editor(con, "empleados", e, datos["id"].tolist(),
                          ["cedula", "nombre", "cargo", "sueldo", "bono", "tipo_contrato", "fecha_ingreso",
                           "fecha_salida", "activo"], {"cliente_id": cid}, lambda d: d["nombre"])
        _guardado(clave)


# ================================================================ por pagar

def pestaña_por_pagar(con, cid):
    datos = db.df(con, """SELECT g.id, g.periodo, g.fecha, c.nombre AS grupo, p.nombre AS proveedor, g.detalle,
                          g.n_factura, g.monto, g.pagado, g.fecha_pago
                          FROM gastos g JOIN categorias c ON c.id=g.categoria_id
                          LEFT JOIN proveedores p ON p.id=g.proveedor_id
                          WHERE g.cliente_id=? AND g.pagado=0 ORDER BY g.fecha""", (cid,))
    if datos.empty:
        st.success("No hay facturas pendientes de pago. 🎉")
        return
    c = st.columns(3)
    tarjeta(c[0], "Total por pagar", dinero(datos["monto"].sum()), f"{len(datos)} compras", "rosa")
    por_prov = datos.fillna({"proveedor": "Sin proveedor"}).groupby("proveedor")["monto"].sum().sort_values(
        ascending=False)
    tarjeta(c[1], "Mayor deuda", por_prov.index[0], dinero(por_prov.iloc[0]), "negro")
    tarjeta(c[2], "Más antigua", str(datos["fecha"].min()), "", "blanco")
    st.write("")
    datos["fecha"] = _a_fecha(datos["fecha"])
    datos["fecha_pago"] = _a_fecha(datos["fecha_pago"])
    datos["pagado"] = datos["pagado"].astype(bool)
    clave = f"pp_{cid}"
    editado = st.data_editor(
        datos, hide_index=True, width="stretch", key=f"{clave}_{_version(clave)}",
        disabled=["periodo", "fecha", "grupo", "proveedor", "detalle", "n_factura", "monto"],
        column_config={"id": None, "monto": st.column_config.NumberColumn("Valor", format="$%.2f"),
                       "pagado": st.column_config.CheckboxColumn("Pagado ✔"),
                       "fecha_pago": st.column_config.DateColumn("Fecha de pago", format="DD/MM/YYYY")})
    if st.button("💾 Marcar como pagadas", key=f"g_{clave}", type="primary"):
        for _, f in editado[editado["pagado"]].iterrows():
            con.execute("UPDATE gastos SET pagado=1, fecha_pago=? WHERE id=?",
                        (db.a_texto_fecha(f["fecha_pago"]) or db.hoy().isoformat(), int(f["id"])))
        con.commit()
        _guardado(clave)
