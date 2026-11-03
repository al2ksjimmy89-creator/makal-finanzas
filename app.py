"""MAKAL Catering & Eventos · Sistema de finanzas.

Para abrir: doble clic en "Abrir MAKAL Finanzas.bat" (en la carpeta del sistema).
Desde el celular: abrir en el navegador la dirección que se muestra en Configuración → Acceso desde el celular.
"""
from datetime import date

import streamlit as st

import calculos as calc
import db
import logo
import vista_config
import vista_mes
import vista_registro
import vista_resumen
from ui_comun import aplicar_estilo

st.set_page_config(page_title="MAKAL Finanzas", page_icon=":material/restaurant:", layout="wide",
                   initial_sidebar_state="auto")
aplicar_estilo()


@st.cache_resource
def preparar_base():
    """Una sola vez al arrancar el servidor: crea/actualiza tablas y hace el respaldo del día."""
    db.inicializar().close()
    db.respaldo_diario()
    return True


preparar_base()
@st.cache_resource
def conexion_nube():
    """En la nube todos comparten UNA conexión (Supabase gratis permite pocas a la vez)."""
    return db.conectar()


if db.url_nube():
    con = conexion_nube()
    if not db.conexion_viva(con):  # se cortó por inactividad: se abre otra
        conexion_nube.clear()
        con = conexion_nube()
else:
    # archivo local: cada persona conectada tiene su propia conexión
    if "con" not in st.session_state:
        st.session_state["con"] = db.conectar()
    con = st.session_state["con"]


# ---------------------------------------------------------------- acceso

COOKIE = "makal_sesion"


def escribir_cookie(valor, dias):
    """Guarda (o borra, con dias=0) la cookie de sesión en este navegador."""
    st.html(f"""<script>
        (function() {{
          var seg = location.protocol === "https:" ? "; Secure" : "";
          var c = "{COOKIE}={valor}; Max-Age={dias * 86400}; Path=/; SameSite=Lax" + seg;
          document.cookie = c;
          try {{ window.parent.document.cookie = c; }} catch (e) {{}}
        }})();
        </script>""", unsafe_allow_javascript=True, width=1)


def recuperar_sesion():
    """Si este dispositivo tiene una sesión recordada y vigente, entra sin pedir contraseña.
    El código llega por la cookie (en la computadora) o, en la nube, el navegador lo pasa una sola vez
    en la dirección (?s=...) porque el servidor de Streamlit no entrega las cookies a la app."""
    desde_url = st.query_params.get("s")
    if desde_url:
        st.query_params.clear()  # no dejar el código a la vista en la dirección
    if "usuario" in st.session_state or st.session_state.get("salio"):
        return
    token = desde_url
    if not token:
        try:
            token = st.context.cookies.get(COOKIE)
        except Exception:  # noqa: BLE001
            token = None
    u = db.usuario_de_sesion(con, token)
    if u:
        st.session_state.update(usuario=u, rol=db.rol_de(con, u), token_sesion=token)
    elif desde_url:
        st.session_state["borrar_cookie"] = True  # código vencido o inválido: se olvida
    else:
        st.session_state["intentar_cookie"] = True


def enviar_cookie_al_servidor():
    """En la pantalla de acceso: si el navegador tiene una sesión recordada, recarga una vez con ?s=código."""
    st.html(f"""<script>
        (function() {{
          var m = document.cookie.match(/(?:^|; ){COOKIE}=([^;]+)/);
          if (!m) return;
          var w = window.top || window;
          try {{ if (w.location.search.indexOf("s=") >= 0) return;
                 w.location.replace(w.location.pathname + "?s=" + encodeURIComponent(m[1])); }}
          catch (e) {{ location.replace(location.pathname + "?s=" + encodeURIComponent(m[1])); }}
        }})();
        </script>""", unsafe_allow_javascript=True, width=1)


def pantalla_acceso():
    _, centro, _ = st.columns([1, 1.3, 1])
    with centro:
        st.html(f"""<div class="mk-banner" style="justify-content:center;text-align:center">
                   <div><img src="data:image/png;base64,{logo.BLANCO_B64}" alt="MAKAL" style="height:110px">
                   <div class="s">Catering & Eventos · Finanzas</div></div></div>""")
        if not db.hay_usuarios(con):
            st.info("Primera vez: crea tu usuario de administrador.", icon=":material/person_add:")
            with st.form("crear"):
                usuario = st.text_input("Usuario")
                clave = st.text_input("Contraseña (mínimo 6 caracteres)", type="password")
                repetir = st.text_input("Repetir contraseña", type="password")
                if st.form_submit_button("Crear usuario", type="primary", width="stretch"):
                    if not usuario.strip() or len(clave) < 6:
                        st.error("Escribe un usuario y una contraseña de al menos 6 caracteres.")
                    elif clave != repetir:
                        st.error("Las contraseñas no coinciden.")
                    else:
                        db.crear_usuario(con, usuario, clave, "admin")
                        st.session_state.update(usuario=usuario.strip(), rol="admin")
                        st.rerun()
        else:
            with st.form("entrar"):
                usuario = st.text_input("Usuario")
                clave = st.text_input("Contraseña", type="password")
                recordar = st.checkbox("Mantener sesión iniciada en este dispositivo", value=True,
                                       help=f"No vuelve a pedir la contraseña durante {db.DIAS_SESION} días en "
                                            "este celular o computadora. No lo marques en equipos ajenos.")
                if st.form_submit_button("Entrar", type="primary", width="stretch", icon=":material/login:"):
                    if db.verificar_usuario(con, usuario, clave):
                        u = usuario.strip()
                        st.session_state.update(usuario=u, rol=db.rol_de(con, u))
                        st.session_state.pop("salio", None)
                        if recordar:
                            token = db.crear_sesion(con, u)
                            st.session_state.update(token_sesion=token, cookie_pendiente=token)
                        st.rerun()
                    else:
                        st.error("Usuario o contraseña incorrectos.")


recuperar_sesion()
intentar = st.session_state.pop("intentar_cookie", False)
if st.session_state.pop("borrar_cookie", False):
    escribir_cookie("", 0)
elif intentar and "usuario" not in st.session_state:
    enviar_cookie_al_servidor()
if "usuario" not in st.session_state:
    pantalla_acceso()
    st.stop()
if "cookie_pendiente" in st.session_state:
    escribir_cookie(st.session_state.pop("cookie_pendiente"), db.DIAS_SESION)

usuario, rol = st.session_state["usuario"], st.session_state.get("rol", "admin")

# ---------------------------------------------------------------- menú lateral

REGISTRAR, RESUMEN, CONFIG = "registrar", "resumen", "config"
TODOS = "Todos los clientes"
hoy = db.hoy()

with st.sidebar:
    st.html(f"""<div class="mk-side"><img class="logo-img" src="data:image/png;base64,{logo.BLANCO_B64}"
                alt="MAKAL"><div class="u">{usuario} · {'Administrador' if rol == 'admin' else 'Registro'}</div></div>""")
    lista = db.clientes(con)
    activos = lista[lista["activo"] == 1]
    nombres = list(activos["nombre"]) + list(lista[lista["activo"] != 1]["nombre"])
    if rol == "admin":
        opciones_cliente = nombres + [TODOS] if nombres else [TODOS]
    else:
        opciones_cliente = list(activos["nombre"])
    if not opciones_cliente:
        st.warning("Aún no hay clientes creados.")
        st.stop()
    cliente_nombre = st.selectbox("Cliente", opciones_cliente, key="cliente")
    cliente = None if cliente_nombre == TODOS else lista[lista["nombre"] == cliente_nombre].iloc[0]

    anios = sorted({hoy.year} | {int(p[:4]) for p in calc.periodos_con_datos(con)}, reverse=True)
    anio = st.selectbox("Año", anios, key="anio")
    con_datos = set(calc.periodos_con_datos(con, int(cliente["id"]) if cliente is not None else None))

    def etiqueta(opcion):
        fijas = {REGISTRAR: ":material/add_circle: Registrar", RESUMEN: ":material/insights: Resumen total",
                 CONFIG: ":material/settings: Configuración"}
        if opcion in fijas:
            return fijas[opcion]
        per = db.periodo_de(anio, opcion)
        color = "orange" if (anio, opcion) == (hoy.year, hoy.month) else ("blue" if per in con_datos else "gray")
        return f":{color}[●] {calc.MESES[opcion - 1]}"

    # el usuario de registro registra y además mira el resumen y el dashboard/PyG de cada mes (sin editar)
    opciones = [REGISTRAR, RESUMEN, *range(1, 13)] + ([CONFIG] if rol == "admin" else [])
    if st.session_state.get("menu") not in opciones:
        st.session_state["menu"] = hoy.month if rol == "admin" else REGISTRAR
    st.radio("Menú", opciones, key="menu", format_func=etiqueta, label_visibility="collapsed")
    st.caption(":orange[●] mes actual · :blue[●] con datos · :gray[●] sin datos")
    eleccion = st.session_state["menu"]

    st.divider()
    if st.button("Cerrar sesión", icon=":material/logout:", width="stretch"):
        db.borrar_sesion(con, st.session_state.get("token_sesion"))
        st.session_state.clear()
        st.session_state.update(salio=True, borrar_cookie=True)
        st.rerun()

if "aviso" in st.session_state:
    st.toast(st.session_state.pop("aviso"), icon=":material/check_circle:")

# ---------------------------------------------------------------- contenido

if eleccion == CONFIG:
    vista_config.mostrar(con, usuario)
elif eleccion == RESUMEN:
    vista_resumen.mostrar(con, cliente, anio)
elif cliente is None:
    st.info("Elige un cliente en el menú de la izquierda. 'Todos los clientes' está disponible en Resumen total.",
            icon=":material/info:")
elif eleccion == REGISTRAR:
    vista_registro.mostrar(con, cliente, usuario)
else:
    vista_mes.mostrar(con, cliente, db.periodo_de(anio, eleccion), solo_lectura=rol != "admin")
