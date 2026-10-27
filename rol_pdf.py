"""Rol de pagos individual en PDF (uno por colaborador) para enviarle el detalle de su pago del mes."""
import io
import unicodedata
import zipfile

from fpdf import FPDF

import calculos as calc
import db
import logo

CIAN = (10, 156, 196)
NEGRO = (29, 29, 33)
GRIS = (110, 117, 128)


def _dinero(v):
    return f"${v:,.2f}"


def nombre_archivo(fila, periodo):
    limpio = unicodedata.normalize("NFKD", str(fila["Nombre"])).encode("ascii", "ignore").decode()
    return f"Rol_{periodo}_{'_'.join(limpio.split())}.pdf"


def _fila(pdf, concepto, valor, negrita=False):
    pdf.set_font("Helvetica", "B" if negrita else "", 10)
    pdf.cell(85, 7, concepto, border="B")
    pdf.cell(35, 7, _dinero(valor), border="B", align="R", new_x="LMARGIN", new_y="NEXT")


def _titulo_seccion(pdf, texto):
    pdf.ln(4)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*CIAN)
    pdf.cell(0, 8, texto, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*NEGRO)


def pdf_rol(f, periodo, cliente):
    """f: una fila del rol de pagos (calculos.rol_de_pagos). Devuelve los bytes del PDF."""
    pdf = FPDF(format=(148, 210))  # A5
    pdf.set_auto_page_break(True, margin=12)
    pdf.set_margins(14, 12, 14)
    pdf.add_page()

    pdf.image(io.BytesIO(logo.oscuro_bytes()), x=14, y=10, h=22)
    pdf.set_xy(34, 12)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*NEGRO)
    pdf.cell(0, 7, "ROL DE PAGOS", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(34)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(*GRIS)
    pdf.cell(0, 5, f"MAKAL Catering & Eventos  ·  {calc.nombre_mes(periodo)}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(34)
    pdf.cell(0, 5, f"Cliente: {cliente}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*NEGRO)
    pdf.ln(6)

    pdf.set_fill_color(232, 248, 253)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 8, f"  {f['Nombre']}", fill=True, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9.5)
    cedula = db.limpio(f.get("Cédula")) or "-"
    pdf.cell(0, 6, f"Cédula: {cedula}    Cargo: {f['Cargo'] or '-'}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Contrato: {f['Contrato']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Días trabajados: {f['Días']:g} de 30    Sueldo mensual: {_dinero(f['Sueldo'])}",
             new_x="LMARGIN", new_y="NEXT")

    _titulo_seccion(pdf, "INGRESOS")
    _fila(pdf, f"Sueldo por {f['Días']:g} días", f["Sueldo proporcional"])
    if f["Bono"]:
        _fila(pdf, "Bono de movilización", f["Bono"])
    if f["Extras"]:
        _fila(pdf, "Horas extras / otros pagos", f["Extras"])
    ingresos = f["Sueldo proporcional"] + f["Bono"] + f["Extras"]
    _fila(pdf, "Total ingresos", ingresos, negrita=True)

    _titulo_seccion(pdf, "DESCUENTOS")
    descuentos = list(f["detalle_descuentos"] or [])
    if f.get("IESS personal", 0):
        descuentos.append(("Aporte personal IESS", f["IESS personal"]))
    if descuentos:
        for concepto, valor in descuentos:
            _fila(pdf, concepto, valor)
    else:
        pdf.set_font("Helvetica", "I", 9.5)
        pdf.cell(0, 7, "Sin descuentos este mes", border="B", new_x="LMARGIN", new_y="NEXT")
    _fila(pdf, "Total descuentos", sum(v for _, v in descuentos), negrita=True)

    pdf.ln(5)
    pdf.set_fill_color(*NEGRO)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 13)
    pdf.cell(80, 11, "  NETO A RECIBIR", fill=True)
    pdf.cell(40, 11, _dinero(f["Neto a pagar"]) + "  ", fill=True, align="R", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*NEGRO)

    pdf.ln(20)
    y = pdf.get_y()
    pdf.line(16, y, 66, y)
    pdf.line(82, y, 132, y)
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_xy(16, y + 1)
    pdf.cell(50, 5, "Recibí conforme", align="C")
    pdf.set_xy(82, y + 1)
    pdf.cell(50, 5, "MAKAL Catering & Eventos", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)
    pdf.set_font("Helvetica", "I", 7.5)
    pdf.set_text_color(*GRIS)
    pdf.cell(0, 4, f"Documento generado el {db.hoy():%d/%m/%Y}", align="C")
    return bytes(pdf.output())


def zip_roles(rol, periodo, cliente):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for _, f in rol.iterrows():
            z.writestr(nombre_archivo(f, periodo), pdf_rol(f, periodo, cliente))
    return buf.getvalue()
