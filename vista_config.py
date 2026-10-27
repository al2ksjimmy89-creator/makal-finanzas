"""Configuración: clientes, proveedores, categorías, gastos fijos, parámetros, importación y usuario."""
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import streamlit as st

import calculos as calc
import db
from ui_comun import banner, descargar_excel
from vista_mes import _guardado, _version

NUEVO = "➕ Crear cliente nuevo"


def mostrar(con, usuario):
    banner("Configuración", "Clientes, proveedores, usuarios y parámetros")
    tabs = st.container(key="pestanas").tabs([
        ":material/apartment: Clientes", ":material/local_shipping: Proveedores", ":material/category: Categorías",
        ":material/autorenew: Gastos fijos", ":material/tune: Parámetros", ":material/upload_file: Importar Excel",
        ":material/group: Usuarios", ":material/smartphone: Acceso desde el celular",
        ":material/lock: Mi contraseña y respaldos"])
    with tabs[0]:
        clientes(con)
    with tabs[1]:
        proveedores(con)
    with tabs[2]:
        categorias(con)
    with tabs[3]:
        gastos_fijos(con)
    with tabs[4]:
        parametros(con)
    with tabs[5]:
        importar(con)
    with tabs[6]:
        usuarios(con, usuario)
    with tabs[7]:
        acceso_celular(con)
    with tabs[8]:
        usuario_y_respaldos(con, usuario)


# ---------------------------------------------------------------- usuarios y acceso

def usuarios(con, usuario_actual):
    lista = db.df(con, "SELECT usuario, COALESCE(rol,'admin') AS rol FROM usuarios ORDER BY usuario")
    lista["Rol"] = lista["rol"].map(db.ROLES)
    st.dataframe(lista[["usuario", "Rol"]], hide_index=True, width="stretch", alt="Usuarios del sistema",
                 column_config={"usuario": "Usuario"})
    st.caption("**Registro**: entra directo a la pantalla Registrar (compras, raciones y ventas). Ideal para el "
               "celular. **Administrador**: ve y edita todo.")
    with st.form("nuevo_usuario", clear_on_submit=True):
        st.markdown("**Agregar usuario**")
        c1, c2 = st.columns(2)
        nuevo = c1.text_input("Usuario")
        rol = c2.selectbox("Rol", list(db.ROLES), format_func=db.ROLES.get, index=1)
        clave = c1.text_input("Contraseña (mínimo 6 caracteres)", type="password")
        repetir = c2.text_input("Repetir contraseña", type="password")
        if st.form_submit_button("Crear usuario", icon=":material/person_add:", type="primary"):
            if not nuevo.strip() or len(clave) < 6:
                st.error("Escribe un usuario y una contraseña de al menos 6 caracteres.")
            elif clave != repetir:
                st.error("Las contraseñas no coinciden.")
            elif db.valor(con, "SELECT 1 FROM usuarios WHERE lower(usuario)=lower(?)", (nuevo.strip(),)):
                st.error("Ese usuario ya existe.")
            else:
                db.crear_usuario(con, nuevo, clave, rol)
                _guardado("usuarios", f"Usuario {nuevo} creado ✔")
    otros = [u for u in lista["usuario"] if u != usuario_actual]
    if otros:
        with st.expander("Cambiar contraseña o eliminar a otro usuario", icon=":material/manage_accounts:"):
            quien = st.selectbox("Usuario", otros, key="adm_quien")
            nueva = st.text_input("Nueva contraseña", type="password", key="adm_clave")
            c1, c2 = st.columns(2)
            if c1.button("Cambiar contraseña", key="adm_cambiar") and len(nueva) >= 6:
                db.cambiar_clave(con, quien, nueva)
                _guardado("usuarios", f"Contraseña de {quien} cambiada ✔")
            if c2.button("Eliminar usuario", key="adm_borrar", icon=":material/person_remove:"):
                con.execute("DELETE FROM usuarios WHERE usuario=?", (quien,))
                con.commit()
                _guardado("usuarios", f"Usuario {quien} eliminado")


def _ip_local():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # no envía nada; solo sirve para saber la IP de la red de la casa
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def acceso_celular(con):
    if db.es_nube(con):
        st.success("El sistema está en la nube: funciona desde cualquier celular o computadora con internet, "
                   "aunque tu computadora esté apagada.", icon=":material/cloud_done:")
        if st.context.url:
            st.code(st.context.url.split("?")[0], language=None)
        st.caption("Abre esa dirección en el celular y usa *Agregar a pantalla de inicio* en el menú del "
                   "navegador para tenerla como una app.")
        return
    ip = _ip_local()
    puerto = st.get_option("server.port")
    st.markdown("**En la casa (misma red Wi-Fi que esta computadora)**")
    if ip:
        st.code(f"http://{ip}:{puerto}", language=None)
        st.caption("Abre esa dirección en el navegador del celular y guárdala en la pantalla de inicio "
                   "(menú del navegador → *Agregar a pantalla de inicio*) para usarla como una app.")
    else:
        st.warning("No se encontró la red de esta computadora. Revisa que esté conectada al Wi-Fi.")
    st.markdown("""**Condiciones**
- Esta computadora debe estar **encendida y con el sistema abierto** (ventana negra de *Abrir MAKAL Finanzas*).
- La primera vez, Windows pregunta si permite que *Python* use la red: elige **Redes privadas → Permitir**.
- Si la IP cambia (por ejemplo, al reiniciar el router), vuelve a mirar la dirección aquí.

**Fuera de la casa (datos móviles u otra red)**
Instala la app gratuita **Tailscale** en esta computadora y en los celulares, con la misma cuenta. Tailscale crea
una conexión privada y cifrada entre tus equipos sin abrir nada a internet. Luego se entra con la dirección de
Tailscale de esta computadora (por ejemplo `http://100.x.x.x:8501`), con el mismo usuario y contraseña.""")


# ---------------------------------------------------------------- clientes

def clientes(con):
    lista = db.clientes(con)
    opciones = [NUEVO] + list(lista["nombre"])
    elegido = st.selectbox("Cliente", opciones, index=1 if len(lista) else 0)
    c = lista[lista["nombre"] == elegido].iloc[0] if elegido != NUEVO else None

    with st.form(f"cliente_{elegido}"):
        st.markdown("**Datos del cliente**")
        a, b = st.columns(2)
        nombre = a.text_input("Nombre *", c["nombre"] if c is not None else "")
        ruc = b.text_input("RUC", (c["ruc"] or "") if c is not None else "")
        contacto = a.text_input("Contacto", (c["contacto"] or "") if c is not None else "")
        personas = b.number_input("Número de personas en nómina", 0, 500,
                                  int(c["personas_nomina"] or 0) if c is not None else 0)
        ini = a.date_input("Inicio del contrato", date.fromisoformat(c["fecha_inicio"]) if c is not None and
                           c["fecha_inicio"] else None, format="DD/MM/YYYY")
        fin = b.date_input("Fin del contrato", date.fromisoformat(c["fecha_fin"]) if c is not None and
                           c["fecha_fin"] else None, format="DD/MM/YYYY")
        meta = a.number_input("Meta de utilidad (%)", 0.0, 100.0,
                              float((c["meta_utilidad"] or 0) * 100) if c is not None else 20.0, step=1.0)
        activo = b.checkbox("Activo", bool(c["activo"]) if c is not None else True)
        notas = st.text_area("Notas", (c["notas"] or "") if c is not None else "")
        if st.form_submit_button("💾 Guardar cliente", type="primary") and nombre.strip():
            valores = (nombre.strip(), ruc or None, contacto or None, db.a_texto_fecha(ini), db.a_texto_fecha(fin),
                       personas, meta / 100, int(activo), notas or None)
            if c is None:
                con.execute("""INSERT INTO clientes (nombre, ruc, contacto, fecha_inicio, fecha_fin, personas_nomina,
                               meta_utilidad, activo, notas) VALUES (?,?,?,?,?,?,?,?,?)""", valores)
            else:
                con.execute("""UPDATE clientes SET nombre=?, ruc=?, contacto=?, fecha_inicio=?, fecha_fin=?,
                               personas_nomina=?, meta_utilidad=?, activo=?, notas=? WHERE id=?""",
                            (*valores, int(c["id"])))
            con.commit()
            _guardado("clientes", f"Cliente {nombre} guardado ✔")

    if c is None:
        st.info("Guarda el cliente para poder agregar sus servicios, precios y presupuesto.")
        return
    cid = int(c["id"])

    st.markdown("**Servicios y precios de venta**")
    st.caption("Grupo = tipo de comensal (ej. Aspirantes, Personal administrativo). Servicio = Desayuno, "
               "Refrigerio, Almuerzo, Merienda… Cada combinación aparece como columna en Ventas.")
    serv = db.df(con, "SELECT id, grupo, servicio, precio, orden, activo FROM servicios_cliente WHERE cliente_id=? "
                      "ORDER BY grupo, orden", (cid,))
    serv["activo"] = serv["activo"].fillna(1).astype(bool)
    clave = f"serv_{cid}"
    ed = st.data_editor(serv, hide_index=True, width="stretch", num_rows="dynamic",
                        key=f"{clave}_{_version(clave)}", column_config={
                            "id": None, "grupo": st.column_config.TextColumn("Grupo", required=True,
                                                                             default="Aspirantes"),
                            "servicio": st.column_config.SelectboxColumn(
                                "Servicio", required=True,
                                options=["Desayuno", "Refrigerio", "Almuerzo", "Merienda", "Cena", "Box lunch"]),
                            "precio": st.column_config.NumberColumn("Precio", format="$%.2f", min_value=0.0),
                            "orden": st.column_config.NumberColumn("Orden", step=1, default=0),
                            "activo": st.column_config.CheckboxColumn("Activo", default=True)})
    if st.button("💾 Guardar servicios", key=f"g_{clave}"):
        db.guardar_editor(con, "servicios_cliente", ed.assign(activo=ed["activo"].fillna(True).astype(int)),
                          serv["id"].tolist(), ["grupo", "servicio", "precio", "orden", "activo"],
                          {"cliente_id": cid}, lambda d: d["grupo"] and d["servicio"])
        _guardado(clave)

    st.markdown("**Personas con pago mensual fijo** (ej. Instructores)")
    pers = db.df(con, "SELECT id, grupo, nombre, grado, valor_mensual, activo FROM personas_mensuales "
                      "WHERE cliente_id=? ORDER BY grupo, id", (cid,))
    pers["activo"] = pers["activo"].fillna(1).astype(bool)
    clave = f"pers_{cid}"
    ed = st.data_editor(pers, hide_index=True, width="stretch", num_rows="dynamic",
                        key=f"{clave}_{_version(clave)}", column_config={
                            "id": None, "grupo": st.column_config.TextColumn("Grupo", default="Instructores"),
                            "nombre": st.column_config.TextColumn("Nombre", required=True), "grado": "Grado",
                            "valor_mensual": st.column_config.NumberColumn("Valor fijo mensual", format="$%.2f"),
                            "activo": st.column_config.CheckboxColumn("Activo", default=True)})
    if st.button("💾 Guardar personas", key=f"g_{clave}"):
        db.guardar_editor(con, "personas_mensuales", ed.assign(activo=ed["activo"].fillna(True).astype(int)),
                          pers["id"].tolist(), ["grupo", "nombre", "grado", "valor_mensual", "activo"],
                          {"cliente_id": cid}, lambda d: d["nombre"])
        _guardado(clave)

    st.markdown("**Presupuesto (% sobre ventas)**")
    ppto = db.presupuesto(con, cid)
    a, b = st.columns(2)
    nuevo = {"Materia Prima": a.number_input("Materia prima total (%)", 0.0, 100.0,
                                             ppto.get("Materia Prima", 0.45) * 100, key=f"pmp_{cid}") / 100,
             "Mano de Obra": b.number_input("Mano de obra total (%)", 0.0, 100.0,
                                            ppto.get("Mano de Obra", 0.35) * 100, key=f"pmo_{cid}") / 100}
    st.caption("Reparto de la materia prima (debe sumar 100%):")
    mp = db.categorias(con, [db.MP])
    cols = st.columns(len(mp))
    for col, n in zip(cols, mp["nombre"]):
        nuevo[n] = col.number_input(f"{n} (%)", 0.0, 100.0, ppto.get(n, 0.0) * 100, key=f"p_{n}_{cid}") / 100
    suma = sum(nuevo[n] for n in mp["nombre"])
    (st.success if abs(suma - 1) < 0.001 else st.warning)(f"Reparto de materia prima: {suma * 100:.1f}%")
    if st.button("💾 Guardar presupuesto", key=f"g_ppto_{cid}"):
        db.guardar_presupuesto(con, cid, nuevo)
        _guardado(f"ppto_{cid}")


# ---------------------------------------------------------------- proveedores y categorías

def proveedores(con):
    cats = db.categorias(con)
    datos = db.df(con, """SELECT p.id, c.nombre AS grupo, p.nombre, p.producto, p.telefono, p.notas, p.activo
                          FROM proveedores p LEFT JOIN categorias c ON c.id=p.categoria_id
                          ORDER BY p.activo DESC, c.orden, p.nombre""")
    datos["activo"] = datos["activo"].fillna(1).astype(bool)
    st.caption("Cada proveedor pertenece a una bodega (Abastos, Proteínas, Vegetales, Pan, Desechables, GLP, "
               "Pulpas). Al registrar una compra eliges la bodega y solo aparecen sus proveedores. Los inactivos "
               "son proveedores antiguos: se conservan en las compras pasadas pero no aparecen para registrar.")
    clave = "provs"
    ed = st.data_editor(datos, hide_index=True, width="stretch", num_rows="dynamic",
                        key=f"{clave}_{_version(clave)}", column_config={
                            "id": None,
                            "grupo": st.column_config.SelectboxColumn("Bodega", options=list(cats["nombre"]),
                                                                      required=True),
                            "nombre": st.column_config.TextColumn("Proveedor", required=True),
                            "producto": "Producto", "telefono": "Teléfono", "notas": "Notas",
                            "activo": st.column_config.CheckboxColumn("Activo", default=True)})
    if st.button("Guardar proveedores", icon=":material/save:", key=f"g_{clave}"):
        e = ed.assign(categoria_id=ed["grupo"].map(dict(zip(cats["nombre"], cats["id"]))),
                      activo=ed["activo"].fillna(True).astype(int))
        try:
            db.guardar_editor(con, "proveedores", e, datos["id"].tolist(),
                              ["nombre", "categoria_id", "producto", "telefono", "notas", "activo"],
                              fila_valida=lambda d: d["nombre"])
            _guardado(clave)
        except Exception:
            con.rollback()
            st.error("No se puede borrar un proveedor que ya tiene compras, ni repetir un nombre. "
                     "Para dejar de usarlo, desmarca 'Activo'.")


def categorias(con):
    datos = db.df(con, "SELECT id, nombre, seccion, precio_defecto, unidad, orden, activo FROM categorias ORDER BY orden")
    datos["activo"] = datos["activo"].fillna(1).astype(bool)
    st.caption("Sección: MP = Materia prima · IND = Costos generales · MANT = Mantenimiento · "
               "FIN = Financiamiento (abonos a inversión, cuotas de préstamo; va debajo de la utilidad operativa).")
    clave = "cats"
    ed = st.data_editor(datos, hide_index=True, width="stretch", num_rows="dynamic",
                        key=f"{clave}_{_version(clave)}", column_config={
                            "id": None, "nombre": st.column_config.TextColumn("Categoría", required=True),
                            "seccion": st.column_config.SelectboxColumn("Sección", options=[db.MP, db.IND, db.MANT,
                                                                                            db.FIN], required=True),
                            "precio_defecto": st.column_config.NumberColumn("Precio por defecto", format="$%.3f"),
                            "unidad": "Unidad", "orden": st.column_config.NumberColumn("Orden", step=1),
                            "activo": st.column_config.CheckboxColumn("Activo", default=True)})
    if st.button("💾 Guardar categorías", key=f"g_{clave}"):
        try:
            db.guardar_editor(con, "categorias", ed.assign(activo=ed["activo"].fillna(True).astype(int)),
                              datos["id"].tolist(), ["nombre", "seccion", "precio_defecto", "unidad", "orden", "activo"],
                              fila_valida=lambda d: d["nombre"] and d["seccion"])
            _guardado(clave)
        except Exception:
            con.rollback()
            st.error("No se puede borrar una categoría que ya tiene gastos. Desmárcala como 'Activo' en su lugar.")


def gastos_fijos(con):
    lista = db.clientes(con)
    if lista.empty:
        st.info("Primero crea un cliente.")
        return
    nombre = st.selectbox("Cliente", lista["nombre"], key="gf_cliente")
    cid = int(lista.loc[lista["nombre"] == nombre, "id"].iloc[0])
    cats = db.categorias(con, [db.IND, db.MANT, db.FIN])
    datos = db.df(con, """SELECT g.id, c.nombre AS categoria, g.detalle, g.monto_mensual, g.desde, g.hasta, g.activo
                          FROM gastos_fijos g JOIN categorias c ON c.id=g.categoria_id WHERE g.cliente_id=?""", (cid,))
    datos["activo"] = datos["activo"].fillna(1).astype(bool)
    st.caption("Gastos que se repiten cada mes con el mismo valor: arriendo, TV/Internet, control de plagas, cuota "
               "de préstamo. Se suman solos a cada mes, proporcionales al día de corte. "
               "Desde / Hasta en formato AAAA-MM (Hasta vacío = sin fin).")
    clave = f"gf_{cid}"
    hoy = db.hoy()
    ed = st.data_editor(datos, hide_index=True, width="stretch", num_rows="dynamic",
                        key=f"{clave}_{_version(clave)}", column_config={
                            "id": None,
                            "categoria": st.column_config.SelectboxColumn("Categoría", options=list(cats["nombre"]),
                                                                          required=True),
                            "detalle": "Detalle",
                            "monto_mensual": st.column_config.NumberColumn("Valor mensual", format="$%.2f"),
                            "desde": st.column_config.TextColumn("Desde", default=f"{hoy:%Y-%m}",
                                                                 validate=r"^\d{4}-\d{2}$"),
                            "hasta": st.column_config.TextColumn("Hasta", validate=r"^(\d{4}-\d{2})?$"),
                            "activo": st.column_config.CheckboxColumn("Activo", default=True)})
    if st.button("💾 Guardar gastos fijos", key=f"g_{clave}"):
        e = ed.assign(categoria_id=ed["categoria"].map(dict(zip(cats["nombre"], cats["id"]))),
                      activo=ed["activo"].fillna(True).astype(int))
        db.guardar_editor(con, "gastos_fijos", e, datos["id"].tolist(),
                          ["categoria_id", "detalle", "monto_mensual", "desde", "hasta", "activo"],
                          {"cliente_id": cid}, lambda d: d["categoria_id"] and d["monto_mensual"])
        _guardado(clave)


def parametros(con):
    datos = db.df(con, "SELECT clave, descripcion, valor FROM parametros ORDER BY clave")
    st.caption("Valores para el cálculo de nómina en relación de dependencia (Ecuador). Los porcentajes van en "
               "decimal: 0.1215 = 12.15%.")
    clave = "params"
    ed = st.data_editor(datos, hide_index=True, width="stretch", key=f"{clave}_{_version(clave)}",
                        disabled=["clave", "descripcion"],
                        column_config={"clave": "Parámetro", "descripcion": "Descripción",
                                       "valor": st.column_config.NumberColumn("Valor", format="%.4f")})
    if st.button("💾 Guardar parámetros", key=f"g_{clave}"):
        for _, f in ed.iterrows():
            con.execute("UPDATE parametros SET valor=? WHERE clave=?", (float(f["valor"]), f["clave"]))
        con.commit()
        _guardado(clave)


# ---------------------------------------------------------------- importación

def importar(con):
    from importar_excel import importar_archivo

    st.caption("Sube un PyG mensual en el formato del Excel de la Escuela de Policía. Si el mes ya tenía datos de "
               "ese cliente, se reemplazan.")
    lista = db.clientes(con)
    a, b = st.columns(2)
    nombre = a.selectbox("Cliente", list(lista["nombre"]) + ["(nuevo cliente)"], key="imp_cliente")
    if nombre == "(nuevo cliente)":
        nombre = a.text_input("Nombre del nuevo cliente")
    hoy = db.hoy()
    anio = b.number_input("Año", 2024, 2100, hoy.year, key="imp_anio")
    mes = b.selectbox("Mes", range(1, 13), index=hoy.month - 1, format_func=lambda m: calc.MESES[m - 1],
                      key="imp_mes")
    archivo = st.file_uploader("Archivo Excel (.xlsx)", type=["xlsx"])
    if archivo and nombre and st.button("📥 Importar", type="primary"):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(archivo.getvalue())
        try:
            inf = importar_archivo(con, tmp.name, nombre, db.periodo_de(int(anio), int(mes)))
        except Exception as error:  # el formato del archivo no es el esperado
            con.rollback()
            st.error(f"No se pudo leer el archivo: {error}")
            return
        finally:
            Path(tmp.name).unlink(missing_ok=True)
        filas = [{"Concepto": k, "Excel": inf["excel"].get(k, 0), "App": inf["app"][k]} for k in inf["app"]]
        st.success("Importado. Comparación de totales:")
        st.dataframe(pd.DataFrame(filas), hide_index=True)


# ---------------------------------------------------------------- usuario y respaldos

def usuario_y_respaldos(con, usuario):
    st.markdown(f"**Usuario:** {usuario}")
    with st.form("cambiar_clave"):
        nueva = st.text_input("Nueva contraseña", type="password")
        repetir = st.text_input("Repetir contraseña", type="password")
        if st.form_submit_button("Cambiar contraseña"):
            if len(nueva) < 6:
                st.error("La contraseña debe tener al menos 6 caracteres.")
            elif nueva != repetir:
                st.error("Las contraseñas no coinciden.")
            else:
                db.cambiar_clave(con, usuario, nueva)
                st.success("Contraseña cambiada ✔")

    st.markdown("**Respaldos**")
    if db.es_nube(con):
        st.caption("Los datos están en Supabase (en la nube). Descarga una copia completa en Excel de vez en "
                   "cuando, por ejemplo cada fin de mes, y guárdala en tu computadora o en Google Drive.")
    else:
        st.caption(f"La app guarda una copia automática por día en: `{db.CARPETA_RESPALDOS}` (se conservan 30). "
                   "Para restaurar: cierra la app y copia el respaldo sobre `datos/makal.db`.")
    if st.button("Preparar respaldo completo en Excel", icon=":material/backup:"):
        descargar_excel(db.exportar_todo(con), f"respaldo_makal_{db.hoy():%Y-%m-%d}.xlsx",
                        "Descargar respaldo")
