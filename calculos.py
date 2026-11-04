"""Cálculos del PyG, rol de pagos y resúmenes.

Regla general: cada mes se analiza con sus días reales (octubre 31, noviembre 30, febrero 28/29).
- Mes cerrado: día de corte = último día del mes.
- Mes en curso: día de corte = día de hoy.
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


def dias_mes(periodo):
    """Días que tiene el mes (28 a 31). Es la base para todo lo proporcional."""
    a, m = map(int, periodo.split("-"))
    return monthrange(a, m)[1]


def dia_corte(periodo, hoy=None):
    hoy = hoy or db.hoy()
    a, m = map(int, periodo.split("-"))
    if (a, m) < (hoy.year, hoy.month):
        return dias_mes(periodo)
    if (a, m) == (hoy.year, hoy.month):
        return hoy.day
    return 0


def _indice_dia(fecha_txt, periodo, si_antes, si_despues):
    """Posición (1..días del mes) de una fecha dentro del mes."""
    if not fecha_txt:
        return None
    f = date.fromisoformat(fecha_txt[:10])
    a, m = map(int, periodo.split("-"))
    if (f.year, f.month) < (a, m):
        return si_antes
    if (f.year, f.month) > (a, m):
        return si_despues
    return f.day


# ---------------------------------------------------------------- rol de pagos

def rol_cerrado(con, cliente_id, periodo):
    return db.valor(con, "SELECT 1 FROM roles_cerrados WHERE cliente_id=? AND periodo=?",
                    (cliente_id, periodo)) is not None


def cerrar_rol(con, cliente_id, periodo):
    """Congela el rol del mes: guarda días, sueldo, bono y descuento de cada persona que trabajó,
    y los días que tuvo el mes (base del cálculo proporcional)."""
    base = dias_mes(periodo)
    rol = rol_de_pagos(con, cliente_id, periodo, base)
    for _, f in rol.iterrows():
        con.execute("""INSERT INTO novedades_rol (empleado_id, periodo, dias, extras, sueldo, bono, descuento)
                       VALUES (?,?,?,?,?,?,?) ON CONFLICT(empleado_id, periodo) DO UPDATE SET
                       dias=excluded.dias, sueldo=excluded.sueldo, bono=excluded.bono,
                       descuento=excluded.descuento""",
                    (int(f["empleado_id"]), periodo, f["Días"], f["Extras"], f["Sueldo"], f["Bono"],
                     f["Descuentos"]))
    con.execute("""INSERT INTO roles_cerrados (cliente_id, periodo, fecha_cierre, dias_base) VALUES (?,?,?,?)
                   ON CONFLICT (cliente_id, periodo) DO UPDATE SET fecha_cierre=excluded.fecha_cierre,
                   dias_base=excluded.dias_base""", (cliente_id, periodo, db.hoy().isoformat(), base))
    con.commit()


def base_dias_rol(con, cliente_id, periodo):
    """Días con que se prorratea el rol: los del mes; en un mes que se cerró con la regla anterior
    (sin días guardados) se respetan los 30 de entonces para no cambiar meses pasados."""
    if rol_cerrado(con, cliente_id, periodo):
        guardado = db.valor(con, "SELECT dias_base FROM roles_cerrados WHERE cliente_id=? AND periodo=?",
                            (cliente_id, periodo))
        return float(guardado) if guardado else 30.0
    return float(dias_mes(periodo))


def reabrir_rol(con, cliente_id, periodo):
    con.execute("DELETE FROM roles_cerrados WHERE cliente_id=? AND periodo=?", (cliente_id, periodo))
    con.commit()


def rol_de_pagos(con, cliente_id, periodo, corte):
    p = {k: db.parametro(con, k) for k in ("sbu", "iess_patronal", "iess_personal", "fondos_reserva")}
    base = base_dias_rol(con, cliente_id, periodo)
    dm = dias_mes(periodo)
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
        fin = _indice_dia(salida, periodo, None, dm) if salida else dm
        dias_auto = 0.0 if ini is None or fin is None else max(0.0, min(fin, corte) - ini + 1)
        if not salida and pd.notna(e["activo"]) and not e["activo"]:
            dias_auto = 0.0  # inactivo sin fecha de salida: solo cuenta si se le escriben días

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
        descuento_manual = de_novedad("descuento")  # escrito directo en la tabla de nómina
        if descuento_manual is not None:
            cuotas_mes = [("Descuento del mes", descuento_manual)] if descuento_manual else []
            descuento_total = descuento_manual

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
# Días que cubre un pedido si el proveedor no tiene otro valor configurado
COBERTURA_BODEGA = {"Pan": 1, "Pulpas": 14}


def inicio_semana_consumo(d):
    """Jueves en que empieza la semana de consumo de una fecha (semanas de jueves a miércoles)."""
    return d - timedelta(days=(d.weekday() - 3) % 7)


def semana_de_compra(d):
    """Los pedidos de martes y miércoles se consumen desde el jueves siguiente."""
    if d.weekday() in (1, 2):
        return d + timedelta(days=3 - d.weekday())
    return inicio_semana_consumo(d)


def ventana_consumo(d, cobertura):
    """Días en que se consume una compra hecha el día d.
    - Cobertura 1 (pan): el mismo día.
    - Pedido de martes o miércoles: desde el jueves siguiente.
    - Compra de otro día (local, eventual): desde ese mismo día.
    Termina el miércoles de la semana de consumo (o de la segunda semana si cubre 14 días)."""
    if cobertura <= 1:
        return d, d
    ini = d + timedelta(days=3 - d.weekday()) if d.weekday() in (1, 2) else d
    fin = inicio_semana_consumo(ini) + timedelta(days=int(cobertura) - 1)
    return ini, max(fin, ini)


def primer_periodo(con, cliente_id):
    return db.valor(con, "SELECT MIN(periodo) FROM raciones WHERE cliente_id=?", (cliente_id,))


def dias_periodo(con, cliente_id, periodo):
    """Primer y último día que pertenecen al mes. El primer mes de un cliente incluye los días
    anteriores en que ya se atendió (ej. abril empezó el 28 de marzo)."""
    a, m = map(int, periodo.split("-"))
    ini, fin = date(a, m, 1), date(a, m, monthrange(a, m)[1])
    if periodo == primer_periodo(con, cliente_id):
        antes = db.valor(con, "SELECT MIN(fecha) FROM raciones WHERE cliente_id=? AND periodo=?",
                         (cliente_id, periodo))
        if antes:
            ini = min(ini, date.fromisoformat(antes[:10]))
    return ini, fin


def periodo_de_dia(con, cliente_id, d):
    p = db.periodo_de(d.year, d.month)
    primero = primer_periodo(con, cliente_id)
    return max(p, primero) if primero else p


def reparto_mp(con, cliente_id, desde, hasta):
    """Reparte cada compra de materia prima en sus días de consumo, en proporción a las raciones
    servidas cada día. Devuelve una fila por compra y día dentro de [desde, hasta]:
    gasto_id, periodo (en que se registró la compra), fecha_compra, dia, bodega, proveedor, monto.
    La suma de una compra en todos sus días es siempre su valor completo: nada queda fuera."""
    margen = 20  # una compra de 15 días hecha hasta 20 días antes todavía se consume en el rango
    # sin proveedor en una bodega de un solo proveedor activo (ej. desechables): se usan sus días
    compras = db.df(con, """SELECT g.id, g.periodo, g.fecha, g.monto, c.nombre AS bodega, p.nombre AS proveedor,
                                   COALESCE(p.dias_cobertura,
                                     (SELECT MAX(u.dias_cobertura) FROM proveedores u WHERE u.categoria_id=g.categoria_id
                                        AND u.activo=1 AND g.proveedor_id IS NULL
                                        AND (SELECT COUNT(*) FROM proveedores v WHERE v.categoria_id=g.categoria_id
                                             AND v.activo=1)=1)) AS dias_cobertura
                            FROM gastos g JOIN categorias c ON c.id=g.categoria_id
                            LEFT JOIN proveedores p ON p.id=g.proveedor_id
                            WHERE g.cliente_id=? AND c.seccion=? AND COALESCE(g.monto,0)<>0
                              AND COALESCE(g.fecha, g.periodo || '-01') BETWEEN ? AND ?""",
                    (cliente_id, db.MP, (desde - timedelta(days=margen)).isoformat(), hasta.isoformat()))
    rac = db.df(con, """SELECT fecha, SUM(cantidad) AS n FROM raciones WHERE cliente_id=? AND fecha BETWEEN ? AND ?
                        GROUP BY fecha""", (cliente_id, (desde - timedelta(days=margen + 14)).isoformat(),
                                            (hasta + timedelta(days=margen)).isoformat()))
    servidas = {date.fromisoformat(f[:10]): float(n or 0) for f, n in zip(rac["fecha"], rac["n"])}
    frontera = db.valor(con, "SELECT MAX(fecha) FROM raciones WHERE cliente_id=? AND cantidad>0", (cliente_id,))
    frontera = date.fromisoformat(frontera[:10]) if frontera else None
    inicio_op = db.valor(con, "SELECT MIN(fecha) FROM raciones WHERE cliente_id=?", (cliente_id,))
    inicio_op = date.fromisoformat(inicio_op[:10]) if inicio_op else None
    recientes = [v for d, v in servidas.items() if v > 0 and frontera and d > frontera - timedelta(days=14)]
    promedio = sum(recientes) / len(recientes) if recientes else 1.0

    filas = []
    for _, c in compras.iterrows():
        d = date.fromisoformat((c["fecha"] or f"{c['periodo']}-01")[:10])
        cob = db.limpio(c["dias_cobertura"])
        cob = int(cob) if cob is not None else COBERTURA_BODEGA.get(c["bodega"], 7)
        ini, fin = ventana_consumo(d, cob)
        dias = [ini + timedelta(days=i) for i in range((fin - ini).days + 1)]
        # días aún sin registrar (después del último día con raciones): se estima con el promedio
        conocidos = [servidas.get(x, 0.0) for x in dias if frontera and x <= frontera and servidas.get(x, 0) > 0]
        estimado = sum(conocidos) / len(conocidos) if conocidos else promedio
        pesos = [servidas.get(x, 0.0) if frontera and x <= frontera else estimado for x in dias]
        total = sum(pesos)
        if total <= 0:
            pesos, total = [1.0] * len(dias), float(len(dias))
        for x, w in zip(dias, pesos):
            if not w:
                continue
            dia = max(x, inicio_op) if inicio_op else x  # antes de empezar el contrato: al primer día
            if desde <= dia <= hasta:
                filas.append({"gasto_id": int(c["id"]), "periodo": c["periodo"], "fecha_compra": d, "dia": dia,
                              "bodega": c["bodega"], "proveedor": db.limpio(c["proveedor"]) or "Sin proveedor",
                              "monto": float(c["monto"]) * w / total})
    return pd.DataFrame(filas, columns=["gasto_id", "periodo", "fecha_compra", "dia", "bodega", "proveedor",
                                        "monto"])


def consumo_mp_mes(con, cliente_id, periodo, corte):
    """Materia prima consumida en el mes hasta el día de corte, y el cuadre con lo registrado."""
    ini, fin = dias_periodo(con, cliente_id, periodo)
    a, m = map(int, periodo.split("-"))
    hasta = min(fin, date(a, m, max(int(corte), 1)))
    rep = reparto_mp(con, cliente_id, ini, fin + timedelta(days=20))
    en_mes = rep[(rep["dia"] >= ini) & (rep["dia"] <= hasta)]
    propias = rep[rep["periodo"] == periodo]
    registrado = float(db.valor(con, """SELECT COALESCE(SUM(g.monto),0) FROM gastos g JOIN categorias c
                                        ON c.id=g.categoria_id WHERE g.cliente_id=? AND g.periodo=? AND c.seccion=?""",
                                (cliente_id, periodo, db.MP), 0.0))
    cuadre = {
        "registrado": registrado,
        "viene_anterior": float(en_mes.loc[en_mes["periodo"] != periodo, "monto"].sum()),
        "pasa_siguiente": float(propias.loc[propias["dia"] > fin, "monto"].sum()),
        "por_consumir": float(propias.loc[(propias["dia"] > hasta) & (propias["dia"] <= fin), "monto"].sum()),
        "consumo": float(en_mes["monto"].sum()),
        "hasta": hasta,
    }
    # lo registrado antes del primer día del rango (fecha de factura vieja) también se cuenta en el mes
    cuadre["otros"] = cuadre["consumo"] - (cuadre["registrado"] + cuadre["viene_anterior"]
                                           - cuadre["pasa_siguiente"] - cuadre["por_consumir"])
    return en_mes.groupby("bodega")["monto"].sum().to_dict(), cuadre, en_mes


def _ventas_por_dia(con, cliente_id, ini, fin, periodo):
    """Venta de cada día: raciones + ventas adicionales; el pago mensual fijo (instructores) se reparte
    por igual entre los días del mes."""
    v = db.df(con, """SELECT fecha, SUM(monto) AS venta FROM (
                        SELECT fecha, cantidad*precio AS monto FROM raciones WHERE cliente_id=? AND periodo=?
                        UNION ALL SELECT fecha, monto FROM ventas_extra WHERE cliente_id=? AND periodo=?) AS v
                      GROUP BY fecha""", (cliente_id, periodo, cliente_id, periodo))
    por_dia = {date.fromisoformat(f[:10]): float(x or 0) for f, x in zip(v["fecha"], v["venta"]) if f}
    sin_fecha = float(v.loc[v["fecha"].isna(), "venta"].sum()) if len(v) else 0.0
    mensual = float(db.valor(con, "SELECT COALESCE(SUM(monto),0) FROM ventas_mensuales WHERE cliente_id=? "
                                  "AND periodo=?", (cliente_id, periodo), 0.0)) + sin_fecha
    n = (fin - ini).days + 1
    return {ini + timedelta(days=i): por_dia.get(ini + timedelta(days=i), 0.0) + mensual / n for i in range(n)}


def semanas_consumo(con, cliente_id, periodo, pct_mp, corte=None):
    """Cuadre por días de consumo (jueves a miércoles), recortado a los días del mes: si la semana
    empieza en un mes y termina en otro, cada mes ve solo sus días, con su venta y su parte proporcional
    de la materia prima. Las semanas del mes suman exactamente el consumo del mes."""
    ini, fin = dias_periodo(con, cliente_id, periodo)
    corte = dia_corte(periodo) if corte is None else corte
    if not corte:
        return pd.DataFrame()
    a, m = map(int, periodo.split("-"))
    hasta = min(fin, date(a, m, max(int(corte), 1)))
    _, _, rep = consumo_mp_mes(con, cliente_id, periodo, corte)
    ventas_dia = _ventas_por_dia(con, cliente_id, ini, fin, periodo)
    rep = rep.assign(semana=[inicio_semana_consumo(d) for d in rep["dia"]])
    filas = []
    s = inicio_semana_consumo(ini)
    while s <= hasta:
        d0, d1 = max(s, ini), min(s + timedelta(days=6), hasta)
        r = rep[rep["semana"] == s]
        n_dias = (d1 - d0).days + 1
        etiqueta = f"{DIAS_CORTOS[d0.weekday()]} {d0:%d/%m} – {DIAS_CORTOS[d1.weekday()]} {d1:%d/%m}"
        fila = {"inicio": s, "fin": s + timedelta(days=6), "desde": d0, "hasta": d1, "Semana": etiqueta,
                "Días": f"{n_dias} de 7" if n_dias < 7 else "7",
                "etiqueta": etiqueta.replace(" – ", "<br>"),
                "Ventas": sum(v for d, v in ventas_dia.items() if d0 <= d <= d1)}
        for bodega, monto in r.groupby("bodega")["monto"].sum().items():
            fila[bodega] = float(monto)
        fila["Consumo MP"] = float(r["monto"].sum())
        filas.append(fila)
        s += timedelta(days=7)
    t = pd.DataFrame(filas).fillna(0.0)
    if len(t):
        t["Presupuesto"] = t["Ventas"] * pct_mp
        t["Diferencia"] = t["Presupuesto"] - t["Consumo MP"]
        t["% de ventas"] = [pct(c, v) for c, v in zip(t["Consumo MP"], t["Ventas"])]
    return t


def control_pedidos(con, cliente_id, periodo):
    """Para cada semana de consumo que toca el mes: qué proveedores esperados tienen su pedido.
    Un pedido de 15 días cubre también la semana siguiente. Proveedores sin grupo = eventuales."""
    ini, fin = dias_periodo(con, cliente_id, periodo)
    semanas = []
    s = inicio_semana_consumo(ini)
    while s <= fin:
        semanas.append(s)
        s += timedelta(days=7)
    rep = reparto_mp(con, cliente_id, semanas[0], semanas[-1] + timedelta(days=6))
    provs = db.df(con, """SELECT p.nombre, p.grupo_control, c.nombre AS bodega, c.orden FROM proveedores p
                          LEFT JOIN categorias c ON c.id=p.categoria_id
                          WHERE c.seccion=? AND p.grupo_control IS NOT NULL AND p.grupo_control<>''""", (db.MP,))
    grupo_de = dict(zip(provs["nombre"], provs["grupo_control"]))
    # compras sin proveedor en bodegas de un solo proveedor (desechables, pulpas, pan) cuentan para él
    unico = {b: g.iloc[0] for b, g in provs.groupby("bodega")["grupo_control"] if g.nunique() == 1
             and b in ("Desechables", "Pulpas", "Pan")}

    def grupo(prov, bodega):
        if prov == "Sin proveedor" and bodega in unico:
            return unico[bodega]
        return grupo_de.get(prov, "Eventuales / compras locales")
    rep = rep.assign(semana=[inicio_semana_consumo(d) for d in rep["dia"]],
                     grupo=[grupo(p, b) for p, b in zip(rep["proveedor"], rep["bodega"])],
                     semana_pedido=[semana_de_compra(d) for d in rep["fecha_compra"]])
    orden = (provs.sort_values(["orden", "grupo_control"]).drop_duplicates("grupo_control")
             [["grupo_control", "bodega"]].values.tolist())
    hoy = db.hoy()
    filas = []
    for grupo, bodega in [*orden, ["Eventuales / compras locales", "Varias"]]:
        fila = {"Bodega": bodega, "Proveedor / grupo": grupo}
        for s in semanas:
            r = rep[(rep["grupo"] == grupo) & (rep["semana"] == s)]
            propio = r.loc[r["semana_pedido"] == s, "monto"].sum()
            col = f"Jue {s:%d/%m}"
            if len(r) and propio > 0.005:
                fila[col] = f"✅ {r['monto'].sum():,.2f}"
            elif len(r):
                fila[col] = f"🔁 {r['monto'].sum():,.2f}"  # cubierto por un pedido anterior (15 días)
            elif grupo.startswith("Eventuales"):
                fila[col] = "—"
            elif s - timedelta(days=2) > hoy:
                fila[col] = "⏳"  # todavía no llega el día de pedido
            else:
                fila[col] = "🔴 falta"
        filas.append(fila)
    return pd.DataFrame(filas), semanas


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
    reg["fijo_prorrateado"] = reg["mensual"] * corte / dias_mes(periodo)
    base = reg["registrado"].astype(float)
    if mp_por_consumo(con) and corte:
        # materia prima: lo consumido en los días del mes (reparto proporcional), no lo comprado
        consumo, _, _ = consumo_mp_mes(con, cliente_id, periodo, corte)
        es_mp = reg["seccion"] == db.MP
        base = base.where(~es_mp, reg["nombre"].map(consumo).fillna(0.0))
    reg["monto"] = base + reg["fijo_prorrateado"]
    return reg


def mp_por_consumo(con):
    """1 = la materia prima del PyG es la consumida en el mes (reparto por días); 0 = lo registrado."""
    return bool(db.parametro(con, "mp_por_consumo", 1))


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
    """Proyección lineal al último día del mes a partir del día de corte."""
    if not r["corte"]:
        return None
    f = dias_mes(r["periodo"]) / r["corte"]
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
    return [p for p in db.df(con, sql, params)["periodo"]]


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
        t["Mes cerrado"] = [c >= dias_mes(p) for c, p in zip(t["corte"], t["Periodo"])]
    return t
