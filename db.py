"""Base de datos de MAKAL.

Funciona con dos motores:
- Supabase (PostgreSQL en la nube): cuando hay una dirección de base en los "secrets"
  ([database] url = "postgresql://...") o en la variable MAKAL_DATABASE_URL. Es lo que se usa en internet.
- SQLite (un archivo, datos/makal.db): si no hay dirección. Sirve para usar el sistema sin internet.
Las consultas se escriben una sola vez (con ?) y valen para los dos.
"""
import os
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import bcrypt
import pandas as pd

CARPETA_APP = Path(__file__).resolve().parent
RUTA_DB = Path(os.environ.get("MAKAL_DB", CARPETA_APP / "datos" / "makal.db"))
CARPETA_RESPALDOS = RUTA_DB.parent.parent / "respaldos" if RUTA_DB.parent.name == "datos" else RUTA_DB.parent / "respaldos"
ZONA = ZoneInfo("America/Guayaquil")


def hoy():
    """Fecha de hoy en Ecuador (el servidor en la nube usa otra hora)."""
    return datetime.now(ZONA).date()


def url_nube():
    """Dirección de Supabase, o None para usar el archivo SQLite local."""
    if os.environ.get("MAKAL_DB"):  # se pidió explícitamente un archivo (pruebas)
        return None
    if os.environ.get("MAKAL_DATABASE_URL"):
        return os.environ["MAKAL_DATABASE_URL"]
    try:
        import streamlit as st
        url = st.secrets["database"]["url"]
    except Exception:  # sin archivo de secrets o sin la clave
        return None
    return None if "PEGA_AQUI" in url else url

# Secciones del PyG
MP, IND, MANT, FIN = "MP", "IND", "MANT", "FIN"
NOMBRE_SECCION = {
    MP: "511 · Materia Prima",
    IND: "522 · Costos Generales",
    MANT: "524 · Mantenimiento Operaciones",
    FIN: "Financiamiento (inversión / préstamos)",
}

TIPOS_CONTRATO = ["Prestación de servicios", "Relación de dependencia"]
TIPOS_DESCUENTO = ["Adelanto de sueldo", "Descuento por dotación / compras", "Otro descuento"]
TIPOS_VENTA_EXTRA = ["Personal externo", "Evento extra", "Otra venta"]
FORMAS_PAGO = ["Transferencia", "Efectivo", "Tarjeta", "Crédito"]

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    usuario TEXT UNIQUE NOT NULL,
    clave_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS parametros (
    clave TEXT PRIMARY KEY,
    valor REAL NOT NULL,
    descripcion TEXT
);
CREATE TABLE IF NOT EXISTS clientes (
    id INTEGER PRIMARY KEY,
    nombre TEXT UNIQUE NOT NULL,
    ruc TEXT,
    contacto TEXT,
    fecha_inicio TEXT,
    fecha_fin TEXT,
    personas_nomina INTEGER DEFAULT 0,
    meta_utilidad REAL DEFAULT 0.20,
    activo INTEGER DEFAULT 1,
    notas TEXT
);
-- Servicios que se venden a cada cliente y su precio (por grupo de comensales)
CREATE TABLE IF NOT EXISTS servicios_cliente (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    grupo TEXT NOT NULL,              -- ej. Aspirantes
    servicio TEXT NOT NULL,           -- ej. Desayuno
    precio REAL NOT NULL DEFAULT 0,
    orden INTEGER DEFAULT 0,
    activo INTEGER DEFAULT 1,
    UNIQUE (cliente_id, grupo, servicio)
);
-- Personas que pagan un valor fijo al mes (ej. Instructores)
CREATE TABLE IF NOT EXISTS personas_mensuales (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    grupo TEXT NOT NULL DEFAULT 'Instructores',
    nombre TEXT NOT NULL,
    grado TEXT,
    valor_mensual REAL DEFAULT 0,
    activo INTEGER DEFAULT 1,
    UNIQUE (cliente_id, nombre)
);
CREATE TABLE IF NOT EXISTS raciones (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    periodo TEXT NOT NULL,            -- AAAA-MM: mes al que pertenece
    fecha TEXT NOT NULL,
    grupo TEXT NOT NULL,
    servicio TEXT NOT NULL,
    cantidad REAL NOT NULL DEFAULT 0,
    precio REAL NOT NULL DEFAULT 0,   -- precio vigente al registrar
    UNIQUE (cliente_id, periodo, fecha, grupo, servicio)
);
CREATE TABLE IF NOT EXISTS ventas_mensuales (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    periodo TEXT NOT NULL,
    persona_id INTEGER NOT NULL REFERENCES personas_mensuales(id),
    monto REAL NOT NULL DEFAULT 0,
    UNIQUE (periodo, persona_id)
);
CREATE TABLE IF NOT EXISTS ventas_extra (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    periodo TEXT NOT NULL,
    fecha TEXT,
    tipo TEXT NOT NULL,
    detalle TEXT,
    monto REAL NOT NULL DEFAULT 0,
    forma_pago TEXT,
    cobrado INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY,
    nombre TEXT UNIQUE NOT NULL,
    seccion TEXT NOT NULL,            -- MP, IND, MANT, FIN
    precio_defecto REAL,
    unidad TEXT,
    orden INTEGER DEFAULT 0,
    activo INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY,
    nombre TEXT UNIQUE NOT NULL,
    categoria_id INTEGER REFERENCES categorias(id),
    producto TEXT,
    telefono TEXT,
    notas TEXT,
    activo INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS gastos (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    periodo TEXT NOT NULL,
    fecha TEXT,
    categoria_id INTEGER NOT NULL REFERENCES categorias(id),
    proveedor_id INTEGER REFERENCES proveedores(id),
    detalle TEXT,
    cantidad REAL,
    precio_unit REAL,
    monto REAL NOT NULL DEFAULT 0,
    n_factura TEXT,
    pagado INTEGER DEFAULT 0,
    fecha_pago TEXT
);
-- Gastos que se repiten cada mes (arriendo, TV, cuota de préstamo...). Se prorratean al día de corte.
CREATE TABLE IF NOT EXISTS gastos_fijos (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    categoria_id INTEGER NOT NULL REFERENCES categorias(id),
    detalle TEXT,
    monto_mensual REAL NOT NULL DEFAULT 0,
    desde TEXT,                        -- AAAA-MM
    hasta TEXT,                        -- AAAA-MM (vacío = sin fin)
    activo INTEGER DEFAULT 1
);
CREATE TABLE IF NOT EXISTS presupuesto (
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    concepto TEXT NOT NULL,            -- 'Materia Prima', 'Mano de Obra' o nombre de categoría MP
    pct REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (cliente_id, concepto)
);
CREATE TABLE IF NOT EXISTS empleados (
    id INTEGER PRIMARY KEY,
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    cedula TEXT,
    nombre TEXT NOT NULL,
    cargo TEXT,
    sueldo REAL NOT NULL DEFAULT 0,
    bono REAL DEFAULT 0,
    tipo_contrato TEXT DEFAULT 'Prestación de servicios',
    fecha_ingreso TEXT,
    fecha_salida TEXT,
    activo INTEGER DEFAULT 1
);
-- Novedades del mes por empleado (si no hay, todo se calcula solo)
CREATE TABLE IF NOT EXISTS novedades_rol (
    id INTEGER PRIMARY KEY,
    empleado_id INTEGER NOT NULL REFERENCES empleados(id),
    periodo TEXT NOT NULL,
    dias REAL,                         -- vacío = automático
    extras REAL DEFAULT 0,             -- horas extras u otros pagos
    sueldo REAL,                       -- se llena al cerrar el mes (sueldo de ese mes)
    bono REAL,                         -- se llena al cerrar el mes (bono pagado ese mes)
    observacion TEXT,
    UNIQUE (empleado_id, periodo)
);
-- Roles de pago cerrados: el mes queda congelado con quién trabajó, días y sueldos de ese momento
CREATE TABLE IF NOT EXISTS roles_cerrados (
    cliente_id INTEGER NOT NULL REFERENCES clientes(id),
    periodo TEXT NOT NULL,
    fecha_cierre TEXT,
    PRIMARY KEY (cliente_id, periodo)
);
CREATE TABLE IF NOT EXISTS descuentos (
    id INTEGER PRIMARY KEY,
    empleado_id INTEGER NOT NULL REFERENCES empleados(id),
    periodo_inicio TEXT NOT NULL,      -- AAAA-MM del primer descuento
    tipo TEXT NOT NULL,
    motivo TEXT,
    monto_total REAL NOT NULL DEFAULT 0,
    cuotas INTEGER NOT NULL DEFAULT 1
);
"""

PARAMETROS_INICIALES = [
    ("dias_base", 30, "Días que se consideran por mes (siempre 30)"),
    ("sbu", 482, "Salario básico unificado vigente"),
    ("iess_patronal", 0.1215, "Aporte patronal IESS (solo relación de dependencia)"),
    ("iess_personal", 0.0945, "Aporte personal IESS (se descuenta del neto)"),
    ("fondos_reserva", 0.0833, "Fondos de reserva (desde el año de trabajo)"),
]

CATEGORIAS_INICIALES = [
    # nombre, seccion, precio_defecto, unidad, orden
    ("Vegetales", MP, None, None, 1),
    ("Abastos", MP, None, None, 2),
    ("Proteínas", MP, None, None, 3),
    ("Desechables", MP, None, None, 4),
    ("Pulpas", MP, None, None, 5),
    ("Pan", MP, 0.12, "unidad", 6),
    ("Gastos varios / administrativos", IND, None, None, 10),
    ("Combustible / Gas (GLP)", IND, 3.5, "tanque 15 kg", 11),
    ("Menaje y equipos", IND, None, None, 12),
    ("Internet / TV", IND, None, None, 13),
    ("Control de plagas", IND, None, None, 14),
    ("Uniformes e implementos", IND, None, None, 15),
    ("Arriendo local", IND, None, None, 16),
    ("Transporte", IND, None, None, 17),
    ("Repuestos y mantenimiento", MANT, None, None, 20),
    ("Abono inversión inicial", FIN, None, None, 30),
    ("Cuota préstamo bancario", FIN, None, None, 31),
]


# Cuadro oficial de proveedores: (bodega = categoría, proveedor, producto)
PROVEEDORES_MAKAL = [
    ("Abastos", "Hormiguita", "Condimentos"),
    ("Abastos", "Comercial Hernandez", "Abastos en general"),
    ("Abastos", "San Jose", "Abastos en general"),
    ("Abastos", "Abastos Yepez", "Granos"),
    ("Proteínas", "AVITALSA", "Pollos"),
    ("Proteínas", "Janeth Flores", "Pollos / Res / Lácteos"),
    ("Proteínas", "Tercena Iluman", "Cerdo"),
    ("Proteínas", "TITAN", "Huevos / Lácteos / Varios"),
    ("Vegetales", "Virgiña Quilumbaqui", "Vegetales y frutas"),
    ("Pan", "Oswaldo Farinango", "Panadería"),
    ("Desechables", "Rosa Borja", "Desechables"),
    ("Combustible / Gas (GLP)", "Biron Garcia", "GLP"),
    ("Pulpas", "Fran Fruit", "Pulpas"),
]
# Nombres usados antes -> nombre oficial
NOMBRES_ANTERIORES = {
    "Hernández": "Comercial Hernandez", "Janeth": "Janeth Flores", "Iluman": "Tercena Iluman",
    "Virgiña": "Virgiña Quilumbaqui", "Borja Rosa": "Rosa Borja", "Titán": "TITAN", "Avitalsa": "AVITALSA",
    "San José": "San Jose", "Abastos Yépez": "Abastos Yepez",
}


def aplicar_cuadro_proveedores(con):
    """Deja los proveedores como en el cuadro oficial. Los que no están quedan inactivos (se conservan
    en las compras antiguas). Se puede ejecutar varias veces."""
    for viejo, nuevo in NOMBRES_ANTERIORES.items():
        id_viejo = valor(con, "SELECT id FROM proveedores WHERE nombre=?", (viejo,))
        if id_viejo is None:
            continue
        id_nuevo = valor(con, "SELECT id FROM proveedores WHERE nombre=?", (nuevo,))
        if id_nuevo is None:
            con.execute("UPDATE proveedores SET nombre=? WHERE id=?", (nuevo, id_viejo))
        else:
            con.execute("UPDATE gastos SET proveedor_id=? WHERE proveedor_id=?", (id_nuevo, id_viejo))
            con.execute("DELETE FROM proveedores WHERE id=?", (id_viejo,))
    oficiales = []
    for bodega, nombre, producto in PROVEEDORES_MAKAL:
        cat = valor(con, "SELECT id FROM categorias WHERE nombre=?", (bodega,))
        con.execute("""INSERT INTO proveedores (nombre, categoria_id, producto, activo) VALUES (?,?,?,1)
                       ON CONFLICT(nombre) DO UPDATE SET categoria_id=excluded.categoria_id,
                       producto=excluded.producto, activo=1""", (nombre, cat, producto))
        oficiales.append(nombre)
    con.execute(f"UPDATE proveedores SET activo=0 WHERE nombre NOT IN ({','.join('?' * len(oficiales))})", oficiales)
    # Bodegas con un solo proveedor: las compras sin proveedor se le asignan
    for bodega in ("Pan", "Pulpas", "Combustible / Gas (GLP)"):
        unico = con.execute("""SELECT p.id FROM proveedores p JOIN categorias c ON c.id=p.categoria_id
                               WHERE c.nombre=? AND p.activo=1""", (bodega,)).fetchall()
        if len(unico) == 1:
            con.execute("""UPDATE gastos SET proveedor_id=? WHERE proveedor_id IS NULL AND categoria_id=
                           (SELECT id FROM categorias WHERE nombre=?)""", (unico[0][0], bodega))
    con.commit()


class Fila(tuple):
    """Fila que se lee por posición (fila[0]) o por nombre (fila["monto"]), igual que en SQLite."""

    def __new__(cls, nombres, valores):
        obj = super().__new__(cls, valores)
        obj._pos = nombres
        return obj

    def __getitem__(self, clave):
        if isinstance(clave, str):
            return tuple.__getitem__(self, self._pos[clave])
        return tuple.__getitem__(self, clave)

    def keys(self):
        return list(self._pos)


def _fabrica_filas(cursor):
    nombres = {d.name: i for i, d in enumerate(cursor.description or [])}
    return lambda valores: Fila(nombres, valores)


def _a_python(v):
    return v.item() if hasattr(v, "item") else v  # números de numpy/pandas -> Python


class ConexionNube:
    """Conexión a Supabase con la misma forma de uso que sqlite3 (execute con ?, commit, rollback)."""
    es_nube = True

    def __init__(self, url):
        import psycopg
        self._con = psycopg.connect(url, autocommit=True, prepare_threshold=None, connect_timeout=15,
                                    row_factory=_fabrica_filas)

    def execute(self, sql, params=()):
        params = tuple(_a_python(p) for p in params)
        if params:
            sql = sql.replace("%", "%%").replace("?", "%s")
        return self._con.execute(sql, params or None)

    def commit(self):  # cada orden se guarda al instante (autocommit)
        pass

    def rollback(self):
        pass

    def close(self):
        self._con.close()

    @property
    def viva(self):
        return not (self._con.closed or self._con.broken)


def es_nube(con):
    return getattr(con, "es_nube", False)


def conectar():
    url = url_nube()
    if url:
        return ConexionNube(url)
    RUTA_DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(RUTA_DB, check_same_thread=False, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")  # permite que dos personas guarden al mismo tiempo
    return con


def conexion_viva(con):
    """True si la conexión sigue abierta (en la nube se corta tras un rato sin uso)."""
    if es_nube(con):
        if not con.viva:
            return False
        try:
            con.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False
    return True


def _asegurar_columna(con, tabla, columna, tipo):
    if es_nube(con):
        con.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {columna} {tipo}")
    elif columna not in [f[1] for f in con.execute(f"PRAGMA table_info({tabla})")]:
        con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")


def esquema_para(con):
    if not es_nube(con):
        return ESQUEMA
    return ESQUEMA.replace("INTEGER PRIMARY KEY,", "SERIAL PRIMARY KEY,").replace(" REAL", " DOUBLE PRECISION")


def inicializar():
    con = conectar()
    if es_nube(con):
        for orden in esquema_para(con).split(";"):
            if orden.strip():
                con.execute(orden)
        # Supabase publica las tablas por su API web; con RLS activo (sin reglas) nadie entra por ahí.
        # La app se conecta como dueño de las tablas, así que no le afecta.
        for tabla in TABLAS:
            con.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY")
    else:
        con.executescript(ESQUEMA)
    for clave, valor, desc in PARAMETROS_INICIALES:
        con.execute("INSERT INTO parametros VALUES (?,?,?) ON CONFLICT DO NOTHING", (clave, valor, desc))
    for nombre, seccion, precio, unidad, orden in CATEGORIAS_INICIALES:
        con.execute(
            "INSERT INTO categorias (nombre, seccion, precio_defecto, unidad, orden) VALUES (?,?,?,?,?) "
            "ON CONFLICT DO NOTHING",
            (nombre, seccion, precio, unidad, orden),
        )
    # columnas agregadas después de la primera versión
    _asegurar_columna(con, "proveedores", "producto", "TEXT")
    _asegurar_columna(con, "usuarios", "rol", "TEXT DEFAULT 'admin'")
    _asegurar_columna(con, "gastos", "registrado_por", "TEXT")
    _asegurar_columna(con, "ventas_extra", "registrado_por", "TEXT")
    _asegurar_columna(con, "raciones", "registrado_por", "TEXT")
    # el tipo "Recupera gasto" ya no resta del costo: se renombra para que no confunda
    con.execute("UPDATE descuentos SET tipo='Descuento por dotación / compras' "
                "WHERE tipo='Recupera gasto de la empresa'")
    con.commit()
    return con


def respaldo_diario(guardar=30):
    """Copia la base una vez al día a la carpeta respaldos/ y deja solo las últimas `guardar`.
    Solo para el archivo local; en la nube el respaldo se descarga desde Configuración."""
    if url_nube() or not RUTA_DB.exists():
        return
    CARPETA_RESPALDOS.mkdir(parents=True, exist_ok=True)
    destino = CARPETA_RESPALDOS / f"makal_{hoy():%Y-%m-%d}.db"
    if not destino.exists():
        shutil.copy2(RUTA_DB, destino)
    copias = sorted(CARPETA_RESPALDOS.glob("makal_*.db"))
    for viejo in copias[:-guardar]:
        viejo.unlink()


# ---------------------------------------------------------------- utilidades

def df(con, sql, params=()):
    cur = con.execute(sql, params)
    columnas = [d[0] for d in cur.description]
    return pd.DataFrame([tuple(f) for f in cur.fetchall()], columns=columnas)


TABLAS = ["usuarios", "parametros", "clientes", "servicios_cliente", "personas_mensuales", "categorias",
          "proveedores", "empleados", "raciones", "ventas_mensuales", "ventas_extra", "gastos", "gastos_fijos",
          "presupuesto", "novedades_rol", "roles_cerrados", "descuentos"]  # en orden: primero las referenciadas


def exportar_todo(con):
    """Todas las tablas (sin contraseñas) para descargar como respaldo en Excel."""
    hojas = {}
    for t in TABLAS:
        d = df(con, f"SELECT * FROM {t}")
        hojas[t] = d.drop(columns=["clave_hash"], errors="ignore")
    return hojas


def valor(con, sql, params=(), defecto=None):
    fila = con.execute(sql, params).fetchone()
    return fila[0] if fila and fila[0] is not None else defecto


def parametro(con, clave, defecto=0.0):
    return valor(con, "SELECT valor FROM parametros WHERE clave=?", (clave,), defecto)


def periodo_de(anio, mes):
    return f"{anio:04d}-{mes:02d}"


def sumar_meses(periodo, n):
    a, m = map(int, periodo.split("-"))
    total = a * 12 + (m - 1) + n
    return periodo_de(total // 12, total % 12 + 1)


def a_texto_fecha(v):
    """Convierte cualquier fecha (date, datetime, Timestamp, texto) a 'AAAA-MM-DD' o None."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, (datetime, pd.Timestamp)):
        return v.strftime("%Y-%m-%d")
    if isinstance(v, date):
        return v.isoformat()
    texto = str(v).strip()
    return texto[:10] if texto else None


def limpio(v):
    """Convierte valores vacíos de pandas (NaN, NaT, '') a None."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str) and not v.strip():
        return None
    if hasattr(v, "item"):  # tipos numpy
        return v.item()
    return v


# ---------------------------------------------------------------- usuarios

def hay_usuarios(con):
    return valor(con, "SELECT COUNT(*) FROM usuarios", defecto=0) > 0


ROLES = {"admin": "Administrador (ve y edita todo)", "registro": "Registro (solo registra compras y raciones)"}


def crear_usuario(con, usuario, clave, rol="admin"):
    h = bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    con.execute("INSERT INTO usuarios (usuario, clave_hash, rol) VALUES (?,?,?)", (usuario.strip(), h, rol))
    con.commit()


def rol_de(con, usuario):
    return valor(con, "SELECT rol FROM usuarios WHERE usuario=?", (usuario,), "admin")


def cambiar_clave(con, usuario, clave):
    h = bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    con.execute("UPDATE usuarios SET clave_hash=? WHERE usuario=?", (h, usuario))
    con.commit()


def verificar_usuario(con, usuario, clave):
    fila = con.execute("SELECT clave_hash FROM usuarios WHERE usuario=?", (usuario.strip(),)).fetchone()
    return bool(fila) and bcrypt.checkpw(clave.encode("utf-8"), fila[0].encode("utf-8"))


# ---------------------------------------------------------------- catálogos

def clientes(con, solo_activos=False):
    sql = "SELECT * FROM clientes" + (" WHERE activo=1" if solo_activos else "") + " ORDER BY nombre"
    return df(con, sql)


def categorias(con, secciones=None):
    sql = "SELECT * FROM categorias WHERE activo=1"
    params = []
    if secciones:
        sql += f" AND seccion IN ({','.join('?' * len(secciones))})"
        params = list(secciones)
    return df(con, sql + " ORDER BY orden, nombre", params)


def proveedores(con, secciones=None):
    sql = """SELECT p.*, c.nombre AS grupo, c.seccion FROM proveedores p
             LEFT JOIN categorias c ON c.id = p.categoria_id WHERE p.activo=1"""
    params = []
    if secciones:
        sql += f" AND c.seccion IN ({','.join('?' * len(secciones))})"
        params = list(secciones)
    return df(con, sql + " ORDER BY p.nombre", params)


def obtener_o_crear_proveedor(con, nombre, categoria_id=None):
    nombre = nombre.strip()
    fila = con.execute("SELECT id FROM proveedores WHERE lower(nombre)=lower(?)", (nombre,)).fetchone()
    if fila:
        return fila[0]
    return con.execute("INSERT INTO proveedores (nombre, categoria_id) VALUES (?,?) RETURNING id",
                       (nombre, categoria_id)).fetchone()[0]


def presupuesto(con, cliente_id):
    filas = con.execute("SELECT concepto, pct FROM presupuesto WHERE cliente_id=?", (cliente_id,)).fetchall()
    return {f["concepto"]: f["pct"] for f in filas}


def guardar_presupuesto(con, cliente_id, valores: dict):
    for concepto, pct in valores.items():
        con.execute(
            "INSERT INTO presupuesto (cliente_id, concepto, pct) VALUES (?,?,?) "
            "ON CONFLICT(cliente_id, concepto) DO UPDATE SET pct=excluded.pct",
            (cliente_id, concepto, float(pct or 0)),
        )
    con.commit()


def guardar_editor(con, tabla, df_editado, ids_originales, columnas, fijos=None, fila_valida=None):
    """Guarda lo que se editó en una tabla de pantalla (st.data_editor).

    - filas nuevas (sin id) se insertan
    - filas con id se actualizan
    - ids que ya no están se eliminan
    """
    fijos = fijos or {}
    ids_despues = set()
    for _, fila in df_editado.iterrows():
        datos = {c: limpio(fila.get(c)) for c in columnas}
        if fila_valida and not fila_valida(datos):
            continue
        datos.update(fijos)
        id_fila = limpio(fila.get("id"))
        if id_fila is None:
            cols = ", ".join(datos)
            con.execute(f"INSERT INTO {tabla} ({cols}) VALUES ({','.join('?' * len(datos))})", list(datos.values()))
        else:
            ids_despues.add(int(id_fila))
            asignar = ", ".join(f"{c}=?" for c in datos)
            con.execute(f"UPDATE {tabla} SET {asignar} WHERE id=?", [*datos.values(), int(id_fila)])
    for id_borrar in set(ids_originales) - ids_despues:
        con.execute(f"DELETE FROM {tabla} WHERE id=?", (int(id_borrar),))
    con.commit()
