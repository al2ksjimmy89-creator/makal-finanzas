"""Pantalla de un mes: Dashboard, PyG, Ventas, Materia Prima, Mano de Obra, Otros gastos y Por pagar."""
from calendar import monthrange
from datetime import date, timedelta

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

def mostrar(con, cliente, periodo, solo_lectura=False):
    """solo_lectura: para el usuario de registro, que solo mira el Dashboard y el PyG."""
    cid = int(cliente["id"])
    corte_auto = calc.dia_corte(periodo)

    corte = st.session_state.get(f"corte_{periodo}", corte_auto) if corte_auto else 0
    r = calc.pyg(con, cid, periodo, corte)
    dm = calc.dias_mes(periodo)
    banner(calc.nombre_mes(periodo), f"{cliente['nombre']} · análisis al día {corte} de {dm}",
           "Utilidad del mes", dinero(r["utilidad_neta"]))

    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    ult = calc.ultimo_dia_con_ventas(con, cid, periodo)
    if corte_auto == 0:
        c1.info("Mes futuro: aún no hay datos para analizar.", icon=":material/event:")
    elif corte_auto < dm and ult and ult.day < corte - 1:
        c1.warning(f"Las raciones están registradas hasta el **{ult:%d/%m}**, pero el análisis va al día "
                   f"**{corte}**. Sueldos y gastos fijos ya cuentan hasta el día {corte}: registra las ventas "
                   f"que faltan para ver la utilidad real.", icon=":material/warning:")
    if corte_auto:
        c2.number_input("Analizar hasta el día", 1, dm, corte_auto, key=f"corte_{periodo}",
                        help=f"Mes cerrado = {dm} (días del mes). Mes en curso = hoy. Todo lo mensual se "
                             "calcula proporcional a este día.")

    pestanas = st.container(key="pestanas")
    if solo_lectura:
        contenido = [(":material/dashboard: Dashboard", lambda: dashboard(con, cliente, periodo, r)),
                     (":material/request_quote: PyG", lambda: pestaña_pyg(con, cliente, periodo, r))]
        clave_tabs = "pestana_lectura"
    else:
        contenido = [(":material/dashboard: Dashboard", lambda: dashboard(con, cliente, periodo, r)),
                     (":material/request_quote: PyG", lambda: pestaña_pyg(con, cliente, periodo, r)),
                     (":material/restaurant: Ventas", lambda: pestaña_ventas(con, cid, periodo)),
                     (":material/shopping_basket: Materia prima", lambda: pestaña_materia_prima(con, cid, periodo, r)),
                     (":material/groups: Mano de obra", lambda: pestaña_mano_obra(con, cid, periodo, r)),
                     (":material/receipt_long: Otros gastos", lambda: pestaña_otros_gastos(con, cid, periodo, r)),
                     (":material/credit_card: Por pagar", lambda: pestaña_por_pagar(con, cid))]
        clave_tabs = "pestana_mes"
    # solo se arma la pestaña que está abierta: en el celular carga mucho más rápido
    tabs = pestanas.tabs([t for t, _ in contenido], key=clave_tabs, on_change="rerun")
    for tab, (_, armar) in zip(tabs, contenido):
        if tab.open:
            with tab:
                armar()


# ================================================================ dashboard

def dashboard(con, cliente, periodo, r):
    tv = r["total_ventas"]
    meta = cliente["meta_utilidad"] or 0
    ppto = db.presupuesto(con, int(cliente["id"]))
    margen = calc.pct(r["utilidad_neta"], tv)

    costos = r["costos"] + r["total_fin"]
    c = st.columns(4)
    tarjeta(c[0], "Ventas", dinero(tv), f"al día {r['corte']} de {calc.dias_mes(periodo)}", "cian")
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
    if proy and r["corte"] < calc.dias_mes(periodo):
        tarjeta(c[3], f"Proyección al día {calc.dias_mes(periodo)}", dinero(proy["utilidad"]),
                f"ventas {dinero(proy['ventas'], 0)} si sigue igual", "blanco", proy["utilidad"])
    else:
        tarjeta(c[3], "Financiamiento", dinero(r["total_fin"]), "abonos / cuotas del mes", "blanco")

    g1, g2 = st.columns([3, 2])
    pct_mp = ppto.get("Materia Prima", 0)
    sem = calc.semanas_consumo(con, int(cliente["id"]), periodo, pct_mp, r["corte"])
    with g1.container(border=True, key="caja_d_semanal"):
        if len(sem):
            st.plotly_chart(grafico_ventas_vs_mp(sem, pct_mp, "Semana a semana: ventas vs materia prima"),
                            width="stretch")
            st.caption("Días de consumo de jueves a miércoles: cada pedido se reparte en los días en que se "
                       "consume, según las raciones servidas. Encima de cada barra rosa: % de las ventas.")
        else:
            st.info("Aún no hay ventas ni compras este mes.")
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
    if len(mp):
        presup = [tv * pct_mp * ppto.get(n, 0) for n in mp["nombre"]]
        with g2.container(border=True, key="caja_d_mp"):
            fig = go.Figure()
            fig.add_bar(y=mp["nombre"], x=presup, orientation="h", name="Presupuesto", marker_color="#DDE3EA")
            # barra "Real" siempre del mismo color; si pasa el presupuesto, el texto lo dice en rosa
            fig.add_bar(y=mp["nombre"], x=mp["monto"], orientation="h", name="Real", marker_color=CIAN,
                        text=[dinero(v, 0) + (f"  ▲ {dinero(v - p, 0)}" if v > p > 0 else "")
                              for v, p in zip(mp["monto"], presup)],
                        textposition="outside",
                        textfont=dict(color=[ROSA if v > p > 0 else NEGRO for v, p in zip(mp["monto"], presup)]))
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
    st.caption(f"Análisis al día {r['corte']} de {calc.dias_mes(periodo)}. Sueldos y gastos fijos proporcionales al día de corte. "
               "La columna Presupuesto es el % sobre ventas asignado al cliente.")
    exportar = t[t["Monto"].notna()][["Concepto", "Monto", "% Ventas"]]
    descargar_excel({"PyG": exportar, "Rol de pagos": r["rol"].drop(columns=["empleado_id", "detalle_descuentos"],
                                                                       errors="ignore")},
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

    personas = db.df(con, "SELECT * FROM personas_mensuales WHERE cliente_id=? ORDER BY grupo, activo DESC, id",
                     (cid,))
    for grupo, pers in personas.groupby("grupo", sort=False):
        with st.expander(f"Pago mensual fijo · {grupo} (editar nombres, grados y valores)"):
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
    """Personas con pago mensual fijo (ej. Instructores): se editan nombre, grado y valor aquí mismo,
    se agregan o eliminan filas. Los inactivos quedan al final del cuadro."""
    grupo = pers["grupo"].iloc[0]
    pers = pers.assign(activo=pers["activo"].fillna(1).astype(int)).sort_values(["activo", "id"],
                                                                               ascending=[False, True])
    actuales = db.df(con, "SELECT persona_id, monto FROM ventas_mensuales WHERE periodo=? AND cliente_id=?",
                     (periodo, cid)).set_index("persona_id")["monto"].to_dict()
    clave = f"men_{cid}_{periodo}_{grupo}"
    if st.button("Llenar con el valor fijo de cada persona activa", key=f"llenar_{clave}"):
        st.session_state[f"lleno_{clave}"] = True
        st.session_state[f"v_{clave}"] = _version(clave) + 1
    lleno = st.session_state.get(f"lleno_{clave}", False)
    tabla = pd.DataFrame({
        "persona_id": pers["id"].astype("Int64"), "Nombre": pers["nombre"], "Grado": pers["grado"],
        "Valor fijo": pers["valor_mensual"].astype(float),
        "Monto del mes": [actuales.get(i, v if lleno and a else 0.0)
                          for i, v, a in zip(pers["id"], pers["valor_mensual"], pers["activo"])],
        "Activo": pers["activo"].astype(bool),
    }).reset_index(drop=True)
    editado = st.data_editor(
        tabla, hide_index=True, width="stretch", num_rows="dynamic", key=f"{clave}_{_version(clave)}",
        column_config={"persona_id": None,
                       "Nombre": st.column_config.TextColumn(required=True, pinned=True),
                       "Grado": st.column_config.TextColumn("Grado / rango"),
                       "Valor fijo": st.column_config.NumberColumn(format="$%.2f", min_value=0.0, default=40.0),
                       "Monto del mes": DINERO,
                       "Activo": st.column_config.CheckboxColumn(default=True)})
    st.write(md(f"**Total del mes:** {dinero(editado['Monto del mes'].fillna(0).sum())}"))
    st.caption("Edita nombre, grado o valor directo en la tabla. Para agregar usa la fila vacía del final; para "
               "eliminar selecciona la fila y el basurero (si ya tuvo pagos en otros meses queda inactivo para no "
               "borrar su historial). Los inactivos se ordenan al final.")
    if st.button("💾 Guardar " + grupo.lower(), key=f"g_{clave}"):
        try:
            ids_despues = set()
            for _, f in editado.iterrows():
                nombre = db.limpio(f["Nombre"])
                if not nombre:
                    continue
                datos = (str(nombre).strip(), db.limpio(f["Grado"]), float(db.limpio(f["Valor fijo"]) or 0),
                         int(bool(db.limpio(f["Activo"]) if db.limpio(f["Activo"]) is not None else True)))
                pid = db.limpio(f["persona_id"])
                if pid is None:
                    pid = con.execute("""INSERT INTO personas_mensuales (cliente_id, grupo, nombre, grado,
                                         valor_mensual, activo) VALUES (?,?,?,?,?,?) RETURNING id""",
                                      (cid, grupo, *datos)).fetchone()[0]
                else:
                    pid = int(pid)
                    con.execute("UPDATE personas_mensuales SET nombre=?, grado=?, valor_mensual=?, activo=? "
                                "WHERE id=?", (*datos, pid))
                ids_despues.add(pid)
                monto = float(db.limpio(f["Monto del mes"]) or 0)
                if monto:
                    con.execute("""INSERT INTO ventas_mensuales (cliente_id, periodo, persona_id, monto)
                                   VALUES (?,?,?,?) ON CONFLICT(periodo, persona_id) DO UPDATE SET
                                   monto=excluded.monto""", (cid, periodo, pid, monto))
                else:
                    con.execute("DELETE FROM ventas_mensuales WHERE periodo=? AND persona_id=?", (periodo, pid))
            for pid in set(int(i) for i in pers["id"]) - ids_despues:
                con.execute("DELETE FROM ventas_mensuales WHERE periodo=? AND persona_id=?", (periodo, pid))
                if db.valor(con, "SELECT COUNT(*) FROM ventas_mensuales WHERE persona_id=?", (pid,), 0):
                    con.execute("UPDATE personas_mensuales SET activo=0 WHERE id=?", (pid,))
                else:
                    con.execute("DELETE FROM personas_mensuales WHERE id=?", (pid,))
            con.commit()
        except Exception as error:  # noqa: BLE001
            con.rollback()
            st.error(f"No se guardó: {error}. Revisa que no haya dos personas con el mismo nombre.")
            return
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
    TODOS_PROV = "Todos los proveedores"
    filtro = st.selectbox("Filtrar por proveedor", [TODOS_PROV, *sorted(nombres_prov, key=str.lower)],
                          key=f"filtro_{clave}", help="Muestra solo las compras de ese proveedor y su histórico.")
    completo = datos
    if filtro != TODOS_PROV:
        datos = datos[datos["proveedor"] == filtro].reset_index(drop=True)
        st.caption(md(f"Compras de **{filtro}** este mes: {len(datos)} · {dinero(datos['monto'].fillna(0).sum())}"))
    editado = st.data_editor(
        datos, hide_index=True, width="stretch", num_rows="dynamic", placeholder="",
        height=420 if filtro == TODOS_PROV else min(38 * (len(datos) + 2), 420),
        key=f"{clave}_{filtro}_{_version(clave)}",
        column_config={
            "id": None,
            "fecha": st.column_config.DateColumn("Fecha", default=_fecha_defecto(periodo), format="DD/MM/YYYY"),
            "categoria": st.column_config.SelectboxColumn("Bodega", options=list(cats["nombre"])),
            "proveedor": st.column_config.SelectboxColumn("Proveedor", options=nombres_prov,
                                                          default=None if filtro == TODOS_PROV else filtro),
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
    if filtro != TODOS_PROV:
        historico_proveedor(con, cid, filtro, secciones, periodo)
    return completo


def historico_proveedor(con, cid, proveedor, secciones, periodo):
    """Todo lo registrado a un proveedor (todos los meses): totales a la fecha, por mes y detalle."""
    h = db.df(con, f"""SELECT g.periodo, g.fecha, c.nombre AS bodega, g.detalle, g.cantidad, g.precio_unit, g.monto,
                              g.n_factura, g.pagado
                       FROM gastos g JOIN categorias c ON c.id=g.categoria_id
                       JOIN proveedores p ON p.id=g.proveedor_id
                       WHERE g.cliente_id=? AND p.nombre=? AND c.seccion IN ({','.join('?' * len(secciones))})
                       ORDER BY g.fecha DESC, g.id DESC""", (cid, proveedor, *secciones))
    with st.container(border=True, key=f"caja_hist_{secciones[0]}"):
        st.markdown(f"**Histórico de {proveedor}** · todos los meses registrados")
        if h.empty:
            st.info("Este proveedor aún no tiene compras registradas.", icon=":material/info:")
            return
        h["monto"] = h["monto"].fillna(0)
        h["pagado"] = h["pagado"].fillna(0).astype(bool)
        total, pendiente = h["monto"].sum(), h.loc[~h["pagado"], "monto"].sum()
        meses = h.groupby("periodo")["monto"].sum().sort_index()
        c = st.columns(4)
        tarjeta(c[0], "Total registrado a la fecha", dinero(total), f"{len(h)} compras", "cian")
        tarjeta(c[1], "Este mes", dinero(meses.get(periodo, 0.0)), calc.nombre_mes(periodo), "blanco")
        tarjeta(c[2], "Promedio por mes", dinero(meses.mean()), f"{len(meses)} meses con compras", "blanco")
        tarjeta(c[3], "Pendiente de pago", dinero(pendiente), "facturas sin pagar", "rosa" if pendiente else "negro")
        st.write("")
        fig = go.Figure(go.Bar(x=[calc.nombre_mes(p) for p in meses.index], y=meses.values, marker_color=CIAN,
                               text=[dinero(v, 0) for v in meses.values], textposition="outside"))
        st.plotly_chart(estilo_figura(fig.update_layout(title=f"Compras a {proveedor} por mes"), 280, False),
                        width="stretch")
        h["mes"] = [calc.nombre_mes(p) for p in h["periodo"]]
        h["fecha"] = _a_fecha(h["fecha"])
        st.dataframe(h[["fecha", "mes", "bodega", "detalle", "cantidad", "precio_unit", "monto", "n_factura",
                        "pagado"]], hide_index=True, width="stretch", height=min(38 * (len(h) + 1), 420),
                     column_config={
                         "fecha": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY", pinned=True),
                         "mes": "Mes", "bodega": "Bodega", "detalle": "Detalle",
                         "cantidad": st.column_config.NumberColumn("Cant."),
                         "precio_unit": st.column_config.NumberColumn("P. unit.", format="$%.3f"),
                         "monto": st.column_config.NumberColumn("Valor", format="$%.2f"),
                         "n_factura": "N° factura", "pagado": st.column_config.CheckboxColumn("Pagado")})
        hoja = "".join(ch for ch in proveedor if ch not in '[]:*?/\\')[:31] or "Historico"
        descargar_excel({hoja: h.drop(columns=["periodo"])},
                        f"Historico_{proveedor}.xlsx".replace(" ", "_"), "Descargar histórico en Excel")


ICONOS_BODEGA = {"Vegetales": ":material/eco:", "Abastos": ":material/inventory_2:",
                 "Proteínas": ":material/set_meal:", "Desechables": ":material/takeout_dining:",
                 "Pulpas": ":material/blender:", "Pan": ":material/bakery_dining:",
                 "Combustible / Gas (GLP)": ":material/propane_tank:"}


def grafico_ventas_vs_mp(sem, pct_mp, titulo):
    """Por semana de consumo: ventas (cian) y compras de materia prima (rosa), con el % que representa
    la materia prima sobre las ventas y la línea del presupuesto."""
    fig = go.Figure()
    fig.add_bar(x=sem["etiqueta"], y=sem["Ventas"], name="Ventas", marker_color=CIAN,
                text=[dinero(v, 0) for v in sem["Ventas"]], textposition="inside", insidetextanchor="end",
                textfont=dict(color="white"))
    fig.add_bar(x=sem["etiqueta"], y=sem["Consumo MP"], name="Materia prima", marker_color=ROSA,
                text=[f"<b>{porcentaje(p)}</b>" if v else "" for p, v in zip(sem["% de ventas"], sem["Ventas"])],
                textposition="outside")
    fig.add_scatter(x=sem["etiqueta"], y=sem["Presupuesto"], name=f"Presupuesto MP ({porcentaje(pct_mp)} de ventas)",
                    mode="lines+markers", line=dict(color=NEGRO, width=2, dash="dot"), marker=dict(size=7))
    fig.update_layout(title=titulo, barmode="group")
    return estilo_figura(fig, 360)


def grafico_compras_semana(sem, pct_mp):
    """Compras de materia prima por semana de consumo, apiladas por bodega, con el total encima
    (en rosa si pasa el presupuesto) y la línea del presupuesto. Debajo, el acumulado."""
    bodegas = [b for b in COLORES_BODEGA if b in sem.columns]
    fig = go.Figure()
    for b in bodegas:
        fig.add_bar(x=sem["etiqueta"], y=sem[b], name=b, marker_color=COLORES_BODEGA[b])
    exc = [c > p > 0 for c, p in zip(sem["Consumo MP"], sem["Presupuesto"])]
    fig.add_scatter(x=sem["etiqueta"], y=sem["Consumo MP"], mode="text", showlegend=False, hoverinfo="skip",
                    text=[f"<b>{dinero(v, 0)}</b>" for v in sem["Consumo MP"]], textposition="top center",
                    textfont=dict(color=[ROSA if e else NEGRO for e in exc], size=13))
    fig.add_scatter(x=sem["etiqueta"], y=sem["Presupuesto"], name=f"Presupuesto ({porcentaje(pct_mp)} de ventas)",
                    mode="lines+markers", line=dict(color=NEGRO, width=3, dash="dot"),
                    marker=dict(size=9, color=[ROSA if e else CIAN for e in exc], line=dict(color="white", width=2)))
    tope = max(sem["Consumo MP"].max(), sem["Presupuesto"].max()) or 1
    fig.update_layout(title="Consumo de materia prima por días de consumo (jueves a miércoles)", barmode="stack",
                      yaxis_range=[0, tope * 1.2])
    with st.container(border=True, key="caja_g_semana"):
        st.plotly_chart(estilo_figura(fig, 400), width="stretch")
        st.caption("Cada semana va de jueves a miércoles. Los pedidos de martes y miércoles se reparten en los "
                   "días de jueves a miércoles según las raciones servidas cada día (pulpas: 15 días; pan: el mismo "
                   "día). Si la semana cruza de mes, cada mes ve solo sus días. Total en rosa = se consumió más de "
                   "lo presupuestado para lo vendido esos días.")

    fig = go.Figure()
    fig.add_scatter(x=sem["etiqueta"], y=sem["Presupuesto"].cumsum(), name="Presupuesto acumulado", fill="tozeroy",
                    line=dict(color=CIAN, width=3, shape="spline"), fillcolor="rgba(20,194,236,.12)")
    fig.add_scatter(x=sem["etiqueta"], y=sem["Consumo MP"].cumsum(), name="Consumo acumulado",
                    mode="lines+markers+text", line=dict(color=ROSA, width=3, shape="spline"),
                    text=[dinero(v, 0) for v in sem["Consumo MP"].cumsum()], textposition="top left")
    fig.update_layout(title="Acumulado: consumo vs presupuesto")
    with st.container(border=True, key="caja_g_acum"):
        st.plotly_chart(estilo_figura(fig, 320), width="stretch")


def tabla_semanal(sem):
    bodegas = [b for b in COLORES_BODEGA if b in sem.columns]
    t = sem[["Semana", "Días", "Ventas", *bodegas, "Consumo MP", "Presupuesto", "Diferencia", "% de ventas"]]
    formatos = {c: dinero for c in ["Ventas", *bodegas, "Consumo MP", "Presupuesto", "Diferencia"]}
    formatos["% de ventas"] = porcentaje
    estilo = (t.style
              .format(formatos)
              .map(lambda v: f"color: {ROSA}; font-weight: 700" if v < 0 else f"color: {VERDE}",
                   subset=["Diferencia"])
              .set_properties(subset=["Consumo MP"], **{"font-weight": "700"}))
    with st.container(border=True, key="caja_t_semanal"):
        st.markdown("**Cuadre semanal de materia prima · días de consumo**")
        st.dataframe(estilo, hide_index=True, width="stretch", alt="Cuadre semanal de materia prima",
                     column_config={"Semana": st.column_config.TextColumn(pinned=True)})
        st.caption("Ventas y consumo de los días de cada semana que caen en este mes. Diferencia = presupuesto − "
                   "consumo. En rosa: esos días se consumió más de lo presupuestado.")


def cuadre_consumo(con, cid, periodo, r):
    """Cómo se pasa de las compras registradas en el mes a la materia prima consumida en sus días."""
    _, c, _ = calc.consumo_mp_mes(con, cid, periodo, r["corte"])
    usa = calc.mp_por_consumo(con)
    filas = [("Compras registradas en el mes", c["registrado"]),
             ("+ Viene de compras de otros meses (consumido en estos días)", c["viene_anterior"]),
             ("− Pasa al mes siguiente (se consume en sus días)", -c["pasa_siguiente"])]
    if c["por_consumir"] > 0.005:
        filas.append((f"− Aún por consumir (días después del {c['hasta']:%d/%m})", -c["por_consumir"]))
    if abs(c["otros"]) > 0.005:
        filas.append(("± Compras con fecha fuera del rango del mes", c["otros"]))
    filas.append(("= Materia prima consumida en el mes", c["consumo"]))
    with st.expander(f"Cuadre: compras registradas {md(dinero(c['registrado']))} → consumo del mes "
                     f"{md(dinero(c['consumo']))}", icon=":material/balance:"):
        cuerpo = "".join(
            f"<tr><td style='padding:4px 8px'>{'<b>' + t + '</b>' if t.startswith('=') else t}</td>"
            f"<td style='padding:4px 8px;text-align:right'>{'<b>' + dinero(v) + '</b>' if t.startswith('=') else dinero(v)}"
            f"</td></tr>" for t, v in filas)
        st.html(f"<table style='width:100%;border-collapse:collapse;font-size:15px'>{cuerpo}</table>")
        st.caption(("El PyG y el presupuesto usan la **materia prima consumida**: " if usa else
                    "El PyG usa las **compras registradas** (parámetro mp_por_consumo = 0). ") +
                   "cada compra se reparte en sus días de consumo (jueves a miércoles; pulpas 15 días; pan el "
                   "mismo día) según las raciones servidas. Ninguna compra se pierde: lo que no se consume este "
                   "mes aparece en el siguiente.")


def control_semanal(con, cid, periodo):
    tabla, _ = calc.control_pedidos(con, cid, periodo)
    if tabla.empty:
        return
    with st.container(border=True, key="caja_control_pedidos"):
        st.markdown("**Control semanal de pedidos** · ¿cada semana de consumo tiene su pedido?")
        semanas = [c for c in tabla.columns if c.startswith("Jue")]

        def color(v):
            if isinstance(v, str) and v.startswith("🔴"):
                return f"color: {ROSA}; font-weight: 700; background-color: #FDECF2"
            if isinstance(v, str) and v.startswith(("✅", "🔁")):
                return f"color: {VERDE}"
            return f"color: {GRIS}"
        st.dataframe(tabla.style.map(color, subset=semanas), hide_index=True, width="stretch",
                     column_config={"Proveedor / grupo": st.column_config.TextColumn(pinned=True)})
        st.caption("Columnas = semanas de consumo (de ese jueves al miércoles siguiente). ✅ pedido para esa semana "
                   "(valor consumido esos días) · 🔁 cubierto por un pedido anterior de 15 días · 🔴 falta registrar "
                   "· ⏳ aún no llega el día de pedido. Los grupos y días de cada proveedor se ajustan en "
                   "Configuración → Proveedores.")


def pestaña_materia_prima(con, cid, periodo, r):
    ppto = db.presupuesto(con, cid)
    pct_mp = ppto.get("Materia Prima", 0.45)
    mp = r["categorias"][r["categorias"]["seccion"] == db.MP]
    base = r["total_ventas"] * pct_mp
    sem = calc.semanas_consumo(con, cid, periodo, pct_mp, r["corte"])
    with st.container(horizontal=True):
        for _, f in mp.iterrows():
            limite = base * ppto.get(f["nombre"], 0)
            dif = limite - f["monto"]
            st.metric(f["nombre"], dinero(f["monto"], 0),
                      f"{'quedan' if dif >= 0 else 'excede'} {dinero(abs(dif), 0)}" if limite else None,
                      delta_color="normal" if dif >= 0 else "inverse", delta_arrow="off", border=True,
                      icon=ICONOS_BODEGA.get(f["nombre"]),
                      help=f"Presupuesto del mes: {dinero(limite)} ({porcentaje(ppto.get(f['nombre'], 0))} de la "
                           f"materia prima).")
        st.metric("Total materia prima", dinero(r["total_mp"], 0), f"presupuesto {dinero(base, 0)}",
                  delta_color="off", delta_arrow="off", border=True, icon=":material/shopping_basket:")

    cuadre_consumo(con, cid, periodo, r)

    clave = f"mp_{cid}_{periodo}"
    form_registro_gasto(con, cid, periodo, [db.MP], clave, "Registrar compra")
    datos = editor_gastos(con, cid, periodo, [db.MP], clave, [db.MP])

    if len(sem):
        tabla_semanal(sem)
        grafico_compras_semana(sem, pct_mp)
    control_semanal(con, cid, periodo)
    if len(datos):
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
                st.metric(f["nombre"], dinero(f["monto"]), border=True, icon=ICONOS_BODEGA.get(f["nombre"]))
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

# Columnas de la tabla de nómina -> campo en la base.
# Datos de la persona (valen para todos los meses):
CAMPOS_EMPLEADO = {"Nombre": "nombre", "Cargo": "cargo", "Cédula": "cedula", "Sueldo": "sueldo",
                   "Bono mov. mensual": "bono", "Ingreso": "fecha_ingreso", "Salida": "fecha_salida",
                   "Contrato": "tipo_contrato", "Activo": "activo"}
# Novedades de este mes:
CAMPOS_MES = {"Días Lab.": "dias", "Otros pagos": "extras", "Descuento": "descuento",
              "Observación": "observacion"}
COLS_CALCULADAS = ["Total gasto (PyG)", "Valor a recibir"]


def tabla_nomina(con, cid, periodo, rol):
    """Una fila por colaborador del mes: activos primero y los inactivos al final."""
    emp = db.df(con, "SELECT * FROM empleados WHERE cliente_id=? ORDER BY activo DESC, id", (cid,))
    calc_por_id = rol.set_index("empleado_id") if len(rol) else pd.DataFrame()
    nov = db.df(con, "SELECT empleado_id, observacion FROM novedades_rol WHERE periodo=?",
                (periodo,)).set_index("empleado_id")["observacion"].to_dict()
    # se muestran: los que tienen valores este mes + (si el rol está abierto) los activos que ya habían
    # ingresado, aunque todavía no sumen días
    fin_mes = f"{periodo}-{calc.dias_mes(periodo):02d}"
    vigentes = (emp["activo"].fillna(1) == 1) & (emp["fecha_ingreso"].fillna("").str[:10] <= fin_mes)
    if calc.rol_cerrado(con, cid, periodo):
        vigentes = vigentes & False
    emp = emp[emp["id"].isin(calc_por_id.index) | vigentes]
    filas = []
    for _, e in emp.iterrows():
        c = calc_por_id.loc[e["id"]] if e["id"] in calc_por_id.index else None
        filas.append({
            "empleado_id": int(e["id"]), "Nombre": e["nombre"], "Cargo": e["cargo"], "Cédula": e["cedula"],
            "Sueldo": float(c["Sueldo"]) if c is not None else float(e["sueldo"] or 0),
            "Días Lab.": float(c["Días"]) if c is not None else 0.0,
            "Bono mov. mensual": float(e["bono"] or 0),
            "Otros pagos": float(c["Extras"]) if c is not None else 0.0,
            "Ingreso": e["fecha_ingreso"], "Salida": e["fecha_salida"],
            "Descuento": float(c["Descuentos"]) if c is not None else 0.0,
            "Total gasto (PyG)": float(c["Costo empresa"]) if c is not None else 0.0,
            "Valor a recibir": float(c["Neto a pagar"]) if c is not None else 0.0,
            "Contrato": e["tipo_contrato"] or db.TIPOS_CONTRATO[0],
            "Activo": bool(e["activo"] if pd.notna(e["activo"]) else 1),
            "Observación": nov.get(e["id"]),
        })
    t = pd.DataFrame(filas, columns=["empleado_id", *CAMPOS_EMPLEADO, *CAMPOS_MES, *COLS_CALCULADAS])
    t = t.sort_values("Activo", ascending=False, kind="stable").reset_index(drop=True)
    for c in ("Ingreso", "Salida"):
        t[c] = _a_fecha(t[c])
    for c in ("Nombre", "Cargo", "Cédula", "Observación"):
        t[c] = t[c].astype("string")
    t.insert(1, "Nº", range(1, len(t) + 1))
    return t


def _valor_campo(campo, v):
    v = db.limpio(v)
    if campo in ("fecha_ingreso", "fecha_salida"):
        return db.a_texto_fecha(v)
    if campo == "activo":
        return 1 if v is None else int(bool(v))
    if campo in ("sueldo", "bono"):
        return float(v or 0)
    if campo == "extras":
        return float(v or 0)
    return v


def _guardar_novedad(con, eid, periodo, campos):
    """Escribe solo los campos del mes que cambiaron; si la fila queda vacía se borra."""
    if not campos:
        return
    cols = list(campos)
    con.execute(f"""INSERT INTO novedades_rol (empleado_id, periodo, {', '.join(cols)})
                    VALUES (?,?,{','.join('?' * len(cols))}) ON CONFLICT(empleado_id, periodo) DO UPDATE SET
                    {', '.join(f'{c}=excluded.{c}' for c in cols)}""", (eid, periodo, *campos.values()))
    con.execute("""DELETE FROM novedades_rol WHERE empleado_id=? AND periodo=? AND dias IS NULL
                   AND COALESCE(extras,0)=0 AND descuento IS NULL AND observacion IS NULL
                   AND sueldo IS NULL AND bono IS NULL""", (eid, periodo))


def _quitar_empleado(con, cid, eid, periodo):
    """Eliminar de la nómina. Si nunca tuvo historial se borra; si ya aparece en otros meses
    o tiene descuentos, se desactiva y deja de contar desde este mes (los meses pasados no cambian)."""
    otros = db.valor(con, "SELECT COUNT(*) FROM novedades_rol WHERE empleado_id=? AND periodo<>?",
                     (eid, periodo), 0)
    desc = db.valor(con, "SELECT COUNT(*) FROM descuentos WHERE empleado_id=?", (eid,), 0)
    a, m = map(int, periodo.split("-"))
    ingreso = db.valor(con, "SELECT fecha_ingreso FROM empleados WHERE id=?", (eid,))
    trabajo_antes = bool(ingreso) and ingreso[:7] < periodo
    con.execute("DELETE FROM novedades_rol WHERE empleado_id=? AND periodo=?", (eid, periodo))
    if not otros and not desc and not trabajo_antes:
        con.execute("DELETE FROM empleados WHERE id=? AND cliente_id=?", (eid, cid))
    else:
        fin_mes_anterior = (date(a, m, 1) - timedelta(days=1)).isoformat()
        con.execute("""UPDATE empleados SET activo=0,
                       fecha_salida=CASE WHEN fecha_salida IS NULL OR fecha_salida>=? THEN ? ELSE fecha_salida END
                       WHERE id=?""", (date(a, m, 1).isoformat(), fin_mes_anterior, eid))


def _guardar_cambios_nomina(con, cid, periodo, tabla, clave_widget, clave):
    """Se ejecuta apenas se edita una celda: guarda y la tabla se recalcula (como en Excel)."""
    cambios = st.session_state.get(clave_widget) or {}
    editadas, nuevas, borradas = (cambios.get("edited_rows", {}), cambios.get("added_rows", []),
                                  cambios.get("deleted_rows", []))
    if any(not db.limpio(f.get("Nombre")) for f in nuevas):
        return  # fila nueva sin nombre todavía: se espera a que la completen
    a, m = map(int, periodo.split("-"))
    try:
        for pos, campos in editadas.items():
            eid = int(tabla.iloc[int(pos)]["empleado_id"])
            emp = {CAMPOS_EMPLEADO[c]: _valor_campo(CAMPOS_EMPLEADO[c], v) for c, v in campos.items()
                   if c in CAMPOS_EMPLEADO}
            if "nombre" in emp and not emp["nombre"]:
                emp.pop("nombre")
            if emp:
                con.execute(f"UPDATE empleados SET {', '.join(f'{k}=?' for k in emp)} WHERE id=?",
                            (*emp.values(), eid))
            _guardar_novedad(con, eid, periodo, {CAMPOS_MES[c]: _valor_campo(CAMPOS_MES[c], v)
                                                 for c, v in campos.items() if c in CAMPOS_MES})
        for f in nuevas:
            emp = {campo: _valor_campo(campo, f.get(col)) for col, campo in CAMPOS_EMPLEADO.items()}
            emp["fecha_ingreso"] = emp["fecha_ingreso"] or date(a, m, 1).isoformat()
            emp["tipo_contrato"] = emp["tipo_contrato"] or db.TIPOS_CONTRATO[0]
            eid = con.execute(f"""INSERT INTO empleados (cliente_id, {', '.join(emp)})
                                  VALUES (?,{','.join('?' * len(emp))}) RETURNING id""",
                              (cid, *emp.values())).fetchone()[0]
            _guardar_novedad(con, eid, periodo, {CAMPOS_MES[c]: _valor_campo(CAMPOS_MES[c], v)
                                                 for c, v in f.items() if c in CAMPOS_MES and db.limpio(v)})
        for pos in borradas:
            _quitar_empleado(con, cid, int(tabla.iloc[int(pos)]["empleado_id"]), periodo)
        con.commit()
    except Exception as error:  # noqa: BLE001 - se muestra al usuario y no se pierde nada guardado antes
        con.rollback()
        st.session_state["error_nomina"] = str(error)
    st.session_state[f"v_{clave}"] = _version(clave) + 1
    st.session_state["aviso"] = "Nómina actualizada ✔"


def editor_nomina(con, cid, periodo, rol, cerrado):
    tabla = tabla_nomina(con, cid, periodo, rol)
    dm = calc.dias_mes(periodo)
    clave = f"nomina_{cid}_{periodo}"
    clave_widget = f"{clave}_{_version(clave)}"
    if "error_nomina" in st.session_state:
        st.error("No se pudo guardar el último cambio: " + st.session_state.pop("error_nomina"))
    st.data_editor(
        tabla, hide_index=True, width="stretch", key=clave_widget, placeholder="", disabled=True if cerrado else
        ["Nº", *COLS_CALCULADAS], num_rows="fixed" if cerrado else "dynamic",
        on_change=None if cerrado else _guardar_cambios_nomina,
        args=None if cerrado else (con, cid, periodo, tabla, clave_widget, clave),
        column_order=["Nº", "Nombre", "Cargo", "Cédula", "Sueldo", "Días Lab.", "Bono mov. mensual",
                      "Otros pagos", "Ingreso", "Salida", "Descuento", *COLS_CALCULADAS, "Contrato", "Activo",
                      "Observación"],
        column_config={
            "empleado_id": None,
            "Nº": st.column_config.NumberColumn(width=40, pinned=True),
            "Nombre": st.column_config.TextColumn(required=True, pinned=True, width="medium"),
            "Cargo": st.column_config.TextColumn(),
            "Cédula": st.column_config.TextColumn(),
            "Sueldo": st.column_config.NumberColumn("Sueldo", format="$%.2f", min_value=0.0,
                                                    help="Sueldo mensual completo"),
            "Días Lab.": st.column_config.NumberColumn(
                f"Días Lab. (de {dm})", min_value=0.0, max_value=float(dm), step=0.5, format="%g",
                help=f"Días trabajados. Se calcula solo desde la fecha de ingreso hasta el día {dm} o la "
                     "salida; escribe otro número si faltó o trabajó distinto. Bórralo para volver a automático."),
            "Bono mov. mensual": st.column_config.NumberColumn(format="$%.2f", min_value=0.0,
                                                               help="Bono mensual completo; se paga "
                                                                    "proporcional a los días."),
            "Otros pagos": st.column_config.NumberColumn(format="$%.2f", min_value=0.0,
                                                         help="Horas extras u otro pago fijo de este mes"),
            "Ingreso": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Salida": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "Descuento": st.column_config.NumberColumn(format="$%.2f", min_value=0.0,
                                                       help="Adelantos o descuentos del mes. Solo baja el "
                                                            "valor a recibir, no el PyG."),
            "Total gasto (PyG)": st.column_config.NumberColumn(format="$%.2f",
                                                               help="Lo que suma al PyG del mes"),
            "Valor a recibir": st.column_config.NumberColumn(format="$%.2f",
                                                             help="Lo que se deposita a la persona"),
            "Contrato": st.column_config.SelectboxColumn(options=db.TIPOS_CONTRATO, required=True,
                                                         default=db.TIPOS_CONTRATO[0]),
            "Activo": st.column_config.CheckboxColumn(default=True),
            "Observación": st.column_config.TextColumn(),
        })
    tot = tabla[COLS_CALCULADAS + ["Descuento"]].sum()
    st.html(f"""<div style="display:flex;flex-wrap:wrap;gap:6px 28px;justify-content:flex-end;
                padding:8px 14px;border-radius:8px;background:#E8F8FD;font-size:15px">
                <b style="margin-right:auto">TOTAL MANO DE OBRA</b>
                <span>Total gasto (PyG): <b>{dinero(tot['Total gasto (PyG)'])}</b></span>
                <span>Descuentos: <b>{dinero(tot['Descuento'])}</b></span>
                <span>Valor a recibir: <b>{dinero(tot['Valor a recibir'])}</b></span></div>""")
    if cerrado:
        st.caption("Rol cerrado: la tabla queda bloqueada. Reábrelo para editar.")
    else:
        st.caption(f"Edita directo en la tabla: cada cambio se guarda solo y recalcula. Mes de **{dm} días**: "
                   "Total gasto = sueldo × días ÷ días del mes + bono proporcional + otros pagos (+ beneficios de "
                   "ley si es relación de dependencia). Para agregar a alguien usa la fila vacía del final; para "
                   "eliminar, selecciona la fila y usa el ícono de basurero (si ya trabajó meses anteriores, "
                   "queda inactivo y deja de contar desde este mes). Los inactivos se ordenan al final.")


def descargas_rol(con, cid, periodo, rol):
    """Roles de pago individuales en PDF para enviar a cada colaborador."""
    import rol_pdf
    if not len(rol):
        return
    with st.container(border=True, key="caja_roles_pdf"):
        st.markdown("**Roles de pago individuales**")
        st.caption("Un PDF por colaborador con el detalle de su pago, para enviarle por WhatsApp o correo.")
        cliente = db.valor(con, "SELECT nombre FROM clientes WHERE id=?", (cid,))
        st.download_button("Descargar todos (ZIP)", rol_pdf.zip_roles(rol, periodo, cliente), type="primary",
                           file_name=f"Roles_{periodo}.zip", mime="application/zip", icon=":material/folder_zip:",
                           key=f"zip_{periodo}")
        with st.expander("Descargar uno por uno"):
            for _, f in rol.iterrows():
                c1, c2 = st.columns([3, 1], vertical_alignment="center")
                c1.write(md(f"{f['Nombre']} · neto {dinero(f['Neto a pagar'])}"))
                c2.download_button("PDF", rol_pdf.pdf_rol(f, periodo, cliente), icon=":material/picture_as_pdf:",
                                   file_name=rol_pdf.nombre_archivo(f, periodo), mime="application/pdf",
                                   key=f"pdf_{periodo}_{f['empleado_id']}")


def pestaña_mano_obra(con, cid, periodo, r):
    rol = r["rol"]
    cerrado = calc.rol_cerrado(con, cid, periodo)
    dm = calc.dias_mes(periodo)
    ppto = db.presupuesto(con, cid)
    limite = r["total_ventas"] * ppto.get("Mano de Obra", 0)
    neto = rol["Neto a pagar"].sum() if len(rol) else 0
    c = st.columns(4)
    tarjeta(c[0], "Total gasto (PyG)", dinero(r["total_mo"]), f"al día {r['corte']} de {dm}", "rosa")
    tarjeta(c[1], "Presupuesto", dinero(limite), porcentaje(ppto.get("Mano de Obra")) + " de ventas", "cian")
    tarjeta(c[2], "Diferencia", dinero(limite - r["total_mo"]), "a favor" if limite >= r["total_mo"] else "excedido",
            "blanco", limite - r["total_mo"])
    tarjeta(c[3], "Valor a recibir", dinero(neto), "a depositar al personal", "negro")
    st.write("")

    if cerrado:
        st.success("Rol de este mes **cerrado**: se usan los días y sueldos guardados al cerrarlo.",
                   icon=":material/lock:")
    elif r["corte"] < dm:
        st.info(f"Mes en curso: los días automáticos van hasta el día **{r['corte']}**. Al cerrar el rol se "
                f"calculan los {dm} días del mes.", icon=":material/info:")
    editor_nomina(con, cid, periodo, rol, cerrado)

    st.divider()
    if cerrado:
        descargas_rol(con, cid, periodo, rol)
        if st.button("Reabrir rol de este mes", icon=":material/lock_open:"):
            calc.reabrir_rol(con, cid, periodo)
            _guardado(f"mo_{cid}", "Rol reabierto")
    else:
        st.write(f"Al terminar el mes, **cierra el rol**: guarda una foto de días, sueldos y descuentos con el "
                 f"**valor a recibir** de cada persona (lo que hay que depositar), así un aumento futuro no cambia "
                 f"meses pasados.")
        if st.button(f"🔒 Cerrar rol de {calc.nombre_mes(periodo)}", disabled=calc.dia_corte(periodo) < dm,
                     help="Se habilita cuando el mes terminó."):
            calc.cerrar_rol(con, cid, periodo)
            _guardado(f"mo_{cid}", "Rol cerrado ✔")


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
