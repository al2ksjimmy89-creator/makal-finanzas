"""Cálculos del PyG, rol de pagos y resúmenes.

Regla general: todos los meses se analizan con 30 días.
- Mes cerrado: día de corte = 30.
- Mes en curso: día de corte = día de hoy (máximo 30).
Ventas y compras se toman tal como se registraron. Lo que es "por mes"
(sueldos, bonos, gastos fijos) se calcula proporcional al día de corte.
"""
from calendar import monthrange
from datetime import date, timedelta

import pandas as pd

import db

MESES = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]


def nombre_mes(periodo):
    a, m = map(int, periodo.split("-"))
    return f"{MESES[m - 1]} {a}"


def dia_corte(periodo, hoy=None):
    hoy = hoy or db.hoy()
    a, m = map(int, periodo.split("-"))
    if (a, m) < (hoy.year, hoy.month):
        return 30
    if (a, m) == (hoy.year, hoy.month):
        return min(hoy.day, 30)
    return 0


def _indice_dia(fecha_txt, periodo, si_antes, si_despues):
    """Posición (1..30) de una fecha dentro del mes, en base 30."""
    if not fecha_txt:
        return None
    f = date.fromisoformat(fecha_txt[:10])
    a, m = map(int, periodo.split("-"))
    if (f.year, f.month) < (a, m):
        return si_antes
    if (f.year, f.month) > (a, m):
        return si_despues
    return min(f.day, 30)


# ---------------------------------------------------------------- rol de pagos

def rol_cerrado(con, cliente_id, periodo):
    return db.valor(con, "SELECT 1 FROM roles_cerrados WHERE cliente_id=? AND periodo=?",
                    (cliente_id, periodo)) is not None


def cerrar_rol(con, cliente_id, periodo):
    """Congela el rol del mes: guarda días, sueldo y bono de cada persona que trabajó."""
    rol = rol_de_pagos(con, cliente_id, periodo, 30)
    for _, f in rol.iterrows():
        con.execute("""INSERT INTO novedades_rol (empleado_id, periodo, dias, extras, sueldo, bono)
                       VALUES (?,?,?,?,?,?) ON CONFLICT(empleado_id, periodo) DO UPDATE SET
                       dias=excluded.dias, sueldo=excluded.sueldo, bono=excluded.bono""",
                    (int(f["empleado_id"]), periodo, f["Días"], f["Extras"], f["Sueldo"], f["Bono"]))
    con.execute("""INSERT INTO roles_cerrados VALUES (?,?,?) ON CONFLICT (cliente_id, periodo)
                   DO UPDATE SET fecha_cierre=excluded.fecha_cierre""", (cliente_id, periodo, db.hoy().isoformat()))
    con.commit()


def reabrir_rol(con, cliente_id, periodo):
    con.execute("DELETE FROM roles_cerrados WHERE cliente_id=? AND periodo=?", (cliente_id, periodo))
    con.commit()


def rol_de_pagos(con, cliente_id, periodo, corte):
    p = {k: db.parametro(con, k) for k in ("dias_base", "sbu", "iess_patronal", "iess_personal", "fondos_reserva")}
    base = p["dias_base"] or 30
    emp = db.df(con, "SELECT * FROM empleados WHERE cliente_id=? ORDER BY activo DESC, id", (cliente_id,))
    nov = db.df(con, "SELECT * FROM novedades_rol WHERE periodo=?", (periodo,)).set_index("empleado_id")
    cerrado = rol_cerrado(con, cliente_id, periodo)
    if cerrado:
        emp = emp[emp["id"].isin(nov.index)]
    desc = db.df(con, """SELECT d.* FROM descuentos d JOIN empleados e ON e.id=d.empleado_id
                         WHERE e.cliente_id=?""", (cliente_id,))
    a, m = map(int, periodo.split("-"))
    inicio_mes = date(a, m, 1)

    filas = []
    for _, e in emp.iterrows():
        ingreso, salida = db.limpio(e["fecha_ingreso"]), db.limpio(e["fecha_salida"])
        # None = no trabajó este mes (ingresó después o salió antes)
        ini = _indice_dia(ingreso, periodo, 1, None) if ingreso else 1
        fin = _indice_dia(salida, periodo, None, 30) if salida else 30
        dias_auto = 0.0 if ini is None or fin is None else max(0.0, min(fin, corte) - ini + 1)

        n = nov.loc[e["id"]] if e["id"] in nov.index else None

        def de_novedad(campo):
            return float(n[campo]) if n is not None and pd.notna(n[campo]) else None

        dias = de_novedad("dias") if de_novedad("dias") is not None else dias_auto
        extras = de_novedad("extras") or 0.0
        sueldo = de_novedad("sueldo") if de_novedad("sueldo") is not None else (e["sueldo"] or 0)
        bono_fijo = de_novedad("bono")  # bono ya pagado en un mes cerrado (no se prorratea)

        # Descuentos: solo bajan lo que se paga al trabajador. No cambian el costo del PyG
        # (lo que la empresa compró por él ya está en Gastos varios).
        cuotas_mes = []
        for _, d in desc[desc["empleado_id"] == e["id"]].iterrows():
            cuotas = max(int(d["cuotas"] or 1), 1)
            for i in range(cuotas):
                if db.sumar_meses(d["periodo_inicio"], i) == periodo:
                    detalle = d["motivo"] or d["tipo"]
                    if cuotas > 1:
                        detalle += f" (cuota {i + 1} de {cuotas})"
                    cuotas_mes.append((detalle, d["monto_total"] / cuotas))
        descuento_total = sum(v for _, v in cuotas_mes)

        if dias <= 0 and extras == 0 and descuento_total == 0:
            continue

        prop = dias / base
        sueldo_p = sueldo * prop
        bono_p = bono_fijo if bono_fijo is not None else (e["bono"] or 0) * prop
        gravable = sueldo_p + extras
        iess = d13 = d14 = vac = fondos = iess_personal = 0.0
        if e["tipo_contrato"] == "Relación de dependencia":
            iess = gravable * p["iess_patronal"]
            iess_personal = gravable * p["iess_personal"]
            d13 = gravable / 12
            d14 = p["sbu"] / 12 * prop
            vac = sueldo_p / 24
            if ingreso and (inicio_mes - date.fromisoformat(ingreso[:10])).days >= 365:
                fondos = gravable * p["fondos_reserva"]

        devengado = sueldo_p + bono_p + extras
        filas.append({
            "empleado_id": e["id"], "Nombre": e["nombre"], "Cargo": e["cargo"], "Cédula": e["cedula"],
            "Contrato": e["tipo_contrato"], "Sueldo": sueldo, "Días": round(dias, 2),
            "Sueldo proporcional": sueldo_p, "Bono": bono_p, "Extras": extras,
            "Aporte patronal": iess, "Décimos": d13 + d14, "Vacaciones": vac, "Fondos reserva": fondos,
            "IESS personal": iess_personal, "Descuentos": descuento_total,
            "Costo empresa": devengado + iess + d13 + d14 + vac + fondos,
            "Neto a pagar": devengado - iess_personal - descuento_total,
            "detalle_descuentos": cuotas_mes,
        })
    return pd.DataFrame(filas)


# ---------------------------------------------------------------- semanas de consumo (jueves a miércoles)

DIAS_CORTOS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]


def inicio_semana_consumo(d):
    """Jueves en que empieza la semana de consumo de una fecha (semanas de jueves a miércoles)."""
    return d - timedelta(days=(d.weekday() - 3) % 7)


def semana_de_compra(d):
    """Los pedidos de martes y miércoles se consumen desde el jueves siguiente."""
    if d.weekday() in (1, 2):
        return d + timedelta(days=3 - d.weekday())
    return inicio_semana_consumo(d)


def semanas_consumo(con, cliente_id, periodo, pct_mp):
    """Semanas de jueves a miércoles que tocan el mes: ventas de esos días, compras de materia prima
    asignadas a la semana en que se consumen (por bodega), y el presupuesto (pct_mp de las ventas)."""
    a, m = map(int, periodo.split("-"))
    primero, ultimo = date(a, m, 1), date(a, m, monthrange(a, m)[1])
    desde, hasta = (primero - timedelta(days=10)).isoformat(), (ultimo + timedelta(days=10)).isoformat()
    compras = db.df(con, """SELECT g.fecha, c.nombre AS bodega, g.monto FROM gastos g
                            JOIN categorias c ON c.id=g.categoria_id
                            WHERE g.cliente_id=? AND c.seccion='MP' AND g.fecha BETWEEN ? AND ?""",
                    (cliente_id, desde, hasta))
    ventas_dia = db.df(con, """SELECT fecha, SUM(monto) AS venta FROM (
                                 SELECT fecha, cantidad*precio AS monto FROM raciones WHERE cliente_id=?
                                 UNION ALL SELECT fecha, monto FROM ventas_extra WHERE cliente_id=?) AS v
                               WHERE fecha BETWEEN ? AND ? GROUP BY fecha""",
                       (cliente_id, cliente_id, desde, hasta))
    compras["semana"] = [semana_de_compra(date.fromisoformat(f[:10])) for f in compras["fecha"]]
    ventas_dia["semana"] = [inicio_semana_consumo(date.fromisoformat(f[:10])) for f in ventas_dia["fecha"]]

    tope = min(ultimo, db.hoy())  # no mostrar semanas que todavía no empiezan
    semanas = sorted({inicio_semana_consumo(primero) + timedelta(days=7 * i) for i in range(6)
                      if inicio_semana_consumo(primero) + timedelta(days=7 * i) <= tope})
    filas = []
    for s in semanas:
        fin = s + timedelta(days=6)
        c = compras[compras["semana"] == s]
        fila = {"inicio": s, "fin": fin,
                "Semana": f"Jue {s:%d/%m} – Mié {fin:%d/%m}",
                "etiqueta": f"Jue {s:%d/%m}<br>Mié {fin:%d/%m}",
                "Ventas": float(ventas_dia.loc[ventas_dia["semana"] == s, "venta"].sum())}
        for bodega, monto in c.groupby("bodega")["monto"].sum().items():
            fila[bodega] = float(monto)
        fila["Compras MP"] = float(c["monto"].sum())
        filas.append(fila)
    t = pd.DataFrame(filas).fillna(0.0)
    if len(t):
        t["Presupuesto"] = t["Ventas"] * pct_mp
        t["Diferencia"] = t["Presupuesto"] - t["Compras MP"]
        t["% de ventas"] = [pct(c, v) for c, v in zip(t["Compras MP"], t["Ventas"])]
    return t


# ---------------------------------------------------------------- ventas

def ventas(con, cliente_id, periodo):
    """Devuelve lista [(concepto, monto)] de ventas del mes."""
    lineas = []
    rac = db.df(con, """SELECT grupo, SUM(cantidad*precio) AS monto FROM raciones
                        WHERE cliente_id=? AND periodo=? GROUP BY grupo ORDER BY grupo""", (cliente_id, periodo))
    for _, r in rac.iterrows():
        lineas.append((f"Ventas {r['grupo']}", r["monto"] or 0))
    men = db.df(con, """SELECT p.grupo, SUM(v.monto) AS monto FROM ventas_mensuales v
                        JOIN personas_mensuales p ON p.id=v.persona_id
                        WHERE v.cliente_id=? AND v.periodo=? GROUP BY p.grupo""", (cliente_id, periodo))
    for _, r in men.iterrows():
        lineas.append((f"Ventas {r['grupo']} (mensual)", r["monto"] or 0))
    ext = db.df(con, """SELECT tipo, SUM(monto) AS monto FROM ventas_extra
                        WHERE cliente_id=? AND periodo=? GROUP BY tipo""", (cliente_id, periodo))
    for _, r in ext.iterrows():
        lineas.append((r["tipo"], r["monto"] or 0))
    return lineas


def raciones_por_servicio(con, cliente_id, periodo):
    return db.df(con, """SELECT grupo, servicio, SUM(cantidad) AS cantidad, SUM(cantidad*precio) AS monto
                         FROM raciones WHERE cliente_id=? AND periodo=? GROUP BY grupo, servicio""",
                 (cliente_id, periodo))


def ultimo_dia_con_ventas(con, cliente_id, periodo):
    f = db.valor(con, """SELECT MAX(fecha) FROM raciones WHERE cliente_id=? AND periodo=? AND cantidad>0""",
                 (cliente_id, periodo))
    return date.fromisoformat(f) if f else None


# ---------------------------------------------------------------- gastos

def gastos_por_categoria(con, cliente_id, periodo, corte):
    """Monto por categoría: gastos registrados + gastos fijos prorrateados al día de corte."""
    reg = db.df(con, """SELECT c.id, c.nombre, c.seccion, c.orden, COALESCE(SUM(g.monto),0) AS registrado
                        FROM categorias c LEFT JOIN gastos g
                          ON g.categoria_id=c.id AND g.cliente_id=? AND g.periodo=?
                        GROUP BY c.id ORDER BY c.orden""", (cliente_id, periodo))
    fij = db.df(con, """SELECT categoria_id AS id, SUM(monto_mensual) AS mensual FROM gastos_fijos
                        WHERE cliente_id=? AND activo=1 AND (desde IS NULL OR desde<=?)
                          AND (hasta IS NULL OR hasta='' OR hasta>=?) GROUP BY categoria_id""",
                 (cliente_id, periodo, periodo))
    reg = reg.merge(fij, on="id", how="left").fillna({"mensual": 0})
    reg["fijo_prorrateado"] = reg["mensual"] * corte / 30
    reg["monto"] = reg["registrado"] + reg["fijo_prorrateado"]
    return reg


# ---------------------------------------------------------------- PyG

def pyg(con, cliente_id, periodo, corte=None):
    corte = dia_corte(periodo) if corte is None else corte
    lin_ventas = ventas(con, cliente_id, periodo)
    total_ventas = sum(m for _, m in lin_ventas)

    cat = gastos_por_categoria(con, cliente_id, periodo, corte)
    por_seccion = {s: cat[cat["seccion"] == s] for s in (db.MP, db.IND, db.MANT, db.FIN)}
    tot = {s: float(d["monto"].sum()) for s, d in por_seccion.items()}

    rol = rol_de_pagos(con, cliente_id, periodo, corte)
    mo = {
        "Sueldos y bonos": float((rol["Sueldo proporcional"] + rol["Bono"] + rol["Extras"]).sum()) if len(rol) else 0.0,
        "Aporte patronal IESS": float(rol["Aporte patronal"].sum()) if len(rol) else 0.0,
        "Beneficios sociales (décimos)": float(rol["Décimos"].sum()) if len(rol) else 0.0,
        "Vacaciones": float(rol["Vacaciones"].sum()) if len(rol) else 0.0,
        "Fondos de reserva": float(rol["Fondos reserva"].sum()) if len(rol) else 0.0,
    }
    total_mo = sum(mo.values())

    directos = tot[db.MP] + total_mo
    indirectos = tot[db.IND] + tot[db.MANT]
    costos = directos + indirectos
    utilidad_operativa = total_ventas - costos
    utilidad_neta = utilidad_operativa - tot[db.FIN]

    return {
        "periodo": periodo, "corte": corte,
        "ventas": lin_ventas, "total_ventas": total_ventas,
        "categorias": cat, "mo": mo, "rol": rol,
        "total_mp": tot[db.MP], "total_mo": total_mo,
        "total_ind": tot[db.IND], "total_mant": tot[db.MANT], "total_fin": tot[db.FIN],
        "directos": directos, "indirectos": indirectos, "costos": costos,
        "utilidad_operativa": utilidad_operativa, "utilidad_neta": utilidad_neta,
    }


def pct(valor, total):
    return valor / total if total and valor is not None else 0.0


def proyeccion(r):
    """Proyección lineal al día 30 a partir del día de corte."""
    if not r["corte"]:
        return None
    f = 30 / r["corte"]
    return {"ventas": r["total_ventas"] * f, "costos": r["costos"] * f,
            "utilidad": r["utilidad_neta"] * f}


def tabla_pyg(r, meta_ppto=None):
    """PyG como tabla para mostrar: Concepto, Monto, % Ventas, Nivel (para formato)."""
    tv = r["total_ventas"]
    filas = []

    def add(concepto, monto, nivel):
        filas.append({"Concepto": concepto, "Monto": monto, "% Ventas": pct(monto, tv), "nivel": nivel})

    add("INGRESOS / VENTAS", None, "seccion")
    for c, m in r["ventas"]:
        add(c, m, "detalle")
    add("TOTAL VENTAS", tv, "total")

    add("COSTOS DIRECTOS (51)", None, "seccion")
    add(db.NOMBRE_SECCION[db.MP], None, "sub")
    for _, c in r["categorias"][r["categorias"]["seccion"] == db.MP].iterrows():
        add(c["nombre"], c["monto"], "detalle")
    add("Total Materia Prima", r["total_mp"], "subtotal")
    add("513 · Mano de Obra", None, "sub")
    for c, m in r["mo"].items():
        if m or c in ("Sueldos y bonos",):
            add(c, m, "detalle")
    add("Total Mano de Obra", r["total_mo"], "subtotal")
    add("TOTAL COSTOS DIRECTOS", r["directos"], "total")

    add("COSTOS INDIRECTOS (52)", None, "seccion")
    for s, total in ((db.IND, r["total_ind"]), (db.MANT, r["total_mant"])):
        add(db.NOMBRE_SECCION[s], None, "sub")
        for _, c in r["categorias"][r["categorias"]["seccion"] == s].iterrows():
            if c["monto"]:
                add(c["nombre"], c["monto"], "detalle")
        add("Total " + db.NOMBRE_SECCION[s].split("· ")[1], total, "subtotal")
    add("TOTAL COSTOS INDIRECTOS", r["indirectos"], "total")

    add("RESULTADO DEL PERÍODO", None, "seccion")
    add("TOTAL COSTOS OPERACIONALES", r["costos"], "total")
    add("UTILIDAD ANTES DE FINANCIAMIENTO", r["utilidad_operativa"], "total")
    for _, c in r["categorias"][r["categorias"]["seccion"] == db.FIN].iterrows():
        if c["monto"]:
            add(c["nombre"], c["monto"], "detalle")
    add("UTILIDAD FINAL NETA", r["utilidad_neta"], "final")
    return pd.DataFrame(filas)


# ---------------------------------------------------------------- resumen de varios meses

def periodos_con_datos(con, cliente_id=None):
    filtro = "WHERE cliente_id=?" if cliente_id else ""
    params = (cliente_id,) * 4 if cliente_id else ()
    sql = f"""SELECT periodo FROM raciones {filtro} UNION SELECT periodo FROM gastos {filtro}
              UNION SELECT periodo FROM ventas_extra {filtro} UNION SELECT periodo FROM ventas_mensuales {filtro}
              ORDER BY periodo"""
    return [f[0] for f in con.execute(sql, params).fetchall()]


def resumen_meses(con, clientes_ids, periodos):
    filas = []
    for per in periodos:
        acum = None
        for cid in clientes_ids:
            r = pyg(con, cid, per)
            vals = {
                "Ventas": r["total_ventas"], "Materia Prima": r["total_mp"], "Mano de Obra": r["total_mo"],
                "Costos Indirectos": r["indirectos"], "Total Costos": r["costos"],
                "Financiamiento": r["total_fin"], "Utilidad Neta": r["utilidad_neta"], "corte": r["corte"],
            }
            acum = vals if acum is None else {k: acum[k] + vals[k] if k != "corte" else vals[k] for k in vals}
        if acum and (acum["Ventas"] or acum["Total Costos"]):
            filas.append({"Periodo": per, "Mes": nombre_mes(per), **acum})
    t = pd.DataFrame(filas)
    if len(t):
        t["Margen"] = t.apply(lambda f: pct(f["Utilidad Neta"], f["Ventas"]), axis=1)
        t["Mes cerrado"] = t["corte"] >= 30
    return t
