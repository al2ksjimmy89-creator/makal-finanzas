"""Registro rápido, pensado para el celular: compras/gastos, raciones del día y ventas adicionales.

El mes (periodo) se toma de la fecha que se elige, así lo registrado aparece solo en el mes correcto.
"""
from datetime import date

import pandas as pd
import streamlit as st

import db
from ui_comun import banner, dinero, md
from vista_mes import _guardado, _version

COMPRA, RACIONES, VENTA = "Compra / gasto", "Raciones del día", "Venta adicional"


def _periodo(fecha):
    return f"{fecha.year:04d}-{fecha.month:02d}"


def mostrar(con, cliente, usuario):
    cid = int(cliente["id"])
    banner("Registrar", f"{cliente['nombre']} · {usuario}")
    tipo = st.segmented_control("¿Qué vas a registrar?", [COMPRA, RACIONES, VENTA], default=COMPRA,
                                key="reg_tipo", width="stretch", required=True)
    with st.container(border=True, key="caja_registro"):
        if tipo == COMPRA:
            registrar_compra(con, cid, usuario)
        elif tipo == RACIONES:
            registrar_raciones(con, cid, usuario)
        else:
            registrar_venta(con, cid, usuario)
    ultimos_registros(con, cid, usuario)


def registrar_compra(con, cid, usuario):
    cats = db.categorias(con)
    bodega = st.selectbox("Bodega", cats["nombre"], key="rc_bodega")
    cat = cats[cats["nombre"] == bodega].iloc[0]
    provs = db.df(con, "SELECT id, nombre, producto FROM proveedores WHERE activo=1 AND categoria_id=? ORDER BY nombre",
                  (int(cat["id"]),))
    etiquetas = {int(i): f"{n} · {p}" if p else n for i, n, p in zip(provs["id"], provs["nombre"], provs["producto"])}
    prov_id = st.selectbox("Proveedor", list(etiquetas) + [None], key=f"rc_prov_{bodega}",
                           format_func=lambda i: etiquetas.get(i, "Sin proveedor / compra local"))
    fecha = st.date_input("Fecha", db.hoy(), format="DD/MM/YYYY", key="rc_fecha")
    v = _version("registro")
    if pd.notna(cat["precio_defecto"]):
        c1, c2 = st.columns(2)
        cantidad = c1.number_input(f"Cantidad ({cat['unidad'] or 'unidades'})", 0.0, step=1.0, key=f"rc_cant_{v}")
        precio = c2.number_input("Precio unitario", 0.0, value=float(cat["precio_defecto"]), step=0.01,
                                 format="%.3f", key=f"rc_pu_{bodega}_{v}")
        monto = cantidad * precio
        st.markdown(md(f"**Valor: {dinero(monto)}**"))
    else:
        cantidad = precio = None
        monto = st.number_input("Valor ($)", 0.0, step=1.0, format="%.2f", key=f"rc_valor_{v}")
    factura = st.text_input("N° de factura (opcional)", key=f"rc_fact_{v}")
    detalle = st.text_input("Detalle (opcional)", key=f"rc_det_{v}", placeholder="Ej.: 2 quintales de papa")
    pagado = st.toggle("Ya está pagado", key=f"rc_pag_{v}")
    if st.button("Guardar compra", icon=":material/check_circle:", type="primary", width="stretch"):
        if not monto:
            st.error("Escribe el valor (o la cantidad).")
            return
        con.execute("""INSERT INTO gastos (cliente_id, periodo, fecha, categoria_id, proveedor_id, detalle, cantidad,
                       precio_unit, monto, n_factura, pagado, registrado_por) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (cid, _periodo(fecha), fecha.isoformat(), int(cat["id"]), prov_id, detalle or None, cantidad,
                     precio, monto, factura or None, int(pagado), usuario))
        con.commit()
        _guardado("registro", f"Compra de {dinero(monto)} guardada ✔")


def registrar_raciones(con, cid, usuario):
    fecha = st.date_input("Fecha", db.hoy(), format="DD/MM/YYYY", key="rr_fecha")
    periodo = _periodo(fecha)
    serv = db.df(con, "SELECT * FROM servicios_cliente WHERE cliente_id=? AND activo=1 ORDER BY grupo, orden",
                 (cid,))
    if serv.empty:
        st.info("Este cliente no tiene servicios configurados.")
        return
    actuales = db.df(con, "SELECT grupo, servicio, cantidad FROM raciones WHERE cliente_id=? AND periodo=? AND fecha=?",
                     (cid, periodo, fecha.isoformat()))
    actual = {(g, s): c for g, s, c in actuales.itertuples(index=False)}
    if len(actuales):
        st.caption("Este día ya tiene raciones registradas: al guardar se reemplazan con estos números.")
    valores = {}
    v = _version("registro")
    for grupo, g in serv.groupby("grupo", sort=False):
        st.markdown(f"**{grupo}**")
        cols = st.columns(len(g))
        for col, (_, s) in zip(cols, g.iterrows()):
            valores[(grupo, s["servicio"], s["precio"])] = col.number_input(
                s["servicio"], 0, step=1, value=int(actual.get((grupo, s["servicio"]), 0)),
                key=f"rr_{grupo}_{s['servicio']}_{fecha}_{v}")
    total = sum(c * p for (_, _, p), c in valores.items())
    st.markdown(md(f"**Venta del día: {dinero(total)}**"))
    if st.button("Guardar raciones", icon=":material/check_circle:", type="primary", width="stretch"):
        for (grupo, servicio, precio), cant in valores.items():
            if cant:
                con.execute("""INSERT INTO raciones (cliente_id, periodo, fecha, grupo, servicio, cantidad, precio,
                               registrado_por) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(cliente_id, periodo, fecha, grupo,
                               servicio) DO UPDATE SET cantidad=excluded.cantidad,
                               registrado_por=excluded.registrado_por""",
                            (cid, periodo, fecha.isoformat(), grupo, servicio, cant, precio, usuario))
            else:
                con.execute("DELETE FROM raciones WHERE cliente_id=? AND periodo=? AND fecha=? AND grupo=? AND "
                            "servicio=?", (cid, periodo, fecha.isoformat(), grupo, servicio))
        con.commit()
        _guardado("registro", f"Raciones del {fecha:%d/%m} guardadas ✔")


def registrar_venta(con, cid, usuario):
    fecha = st.date_input("Fecha", db.hoy(), format="DD/MM/YYYY", key="rv_fecha")
    tipo = st.selectbox("Tipo", db.TIPOS_VENTA_EXTRA, key="rv_tipo")
    v = _version("registro")
    detalle = st.text_input("Detalle (persona o evento)", key=f"rv_det_{v}")
    monto = st.number_input("Valor ($)", 0.0, step=1.0, format="%.2f", key=f"rv_monto_{v}")
    forma = st.selectbox("Forma de pago", db.FORMAS_PAGO, key="rv_forma")
    if st.button("Guardar venta", icon=":material/check_circle:", type="primary", width="stretch"):
        if not monto:
            st.error("Escribe el valor.")
            return
        con.execute("""INSERT INTO ventas_extra (cliente_id, periodo, fecha, tipo, detalle, monto, forma_pago, cobrado,
                       registrado_por) VALUES (?,?,?,?,?,?,?,1,?)""",
                    (cid, _periodo(fecha), fecha.isoformat(), tipo, detalle or None, monto, forma, usuario))
        con.commit()
        _guardado("registro", f"Venta de {dinero(monto)} guardada ✔")


def ultimos_registros(con, cid, usuario):
    st.markdown("**Últimas compras registradas**")
    datos = db.df(con, """SELECT g.id, g.fecha AS "Fecha", c.nombre AS "Bodega",
                          COALESCE(p.nombre,'—') AS "Proveedor", g.monto AS "Valor",
                          CASE g.pagado WHEN 1 THEN 'Sí' ELSE 'No' END AS "Pagado",
                          COALESCE(g.registrado_por,'') AS "Por"
                          FROM gastos g JOIN categorias c ON c.id=g.categoria_id
                          LEFT JOIN proveedores p ON p.id=g.proveedor_id
                          WHERE g.cliente_id=? ORDER BY g.id DESC LIMIT 8""", (cid,))
    datos["Fecha"] = pd.to_datetime(datos["Fecha"]).dt.date
    st.dataframe(datos.drop(columns=["id"]), hide_index=True, width="stretch", alt="Últimas compras registradas",
                 column_config={"Valor": st.column_config.NumberColumn(format="$%.2f"),
                                "Fecha": st.column_config.DateColumn(format="DD/MM")})
    mias = datos[datos["Por"] == usuario]
    if len(mias):
        with st.expander("¿Te equivocaste? Borrar una compra que registraste", icon=":material/delete:"):
            etiquetas = {f.id: f"{f.Fecha:%d/%m} · {f.Bodega} · {f.Proveedor} · {dinero(f.Valor)}"
                         for f in mias.itertuples()}
            elegido = st.selectbox("Compra", list(etiquetas), key="borrar_sel", format_func=etiquetas.get)
            if st.button("Borrar esta compra", icon=":material/delete:", key="borrar_btn"):
                con.execute("DELETE FROM gastos WHERE id=? AND registrado_por=?", (int(elegido), usuario))
                con.commit()
                _guardado("registro", "Compra borrada")
