"""Genera el Plan de Trabajo individual del aprendiz en PDF.

Incluye:
  - Datos del aprendiz (nombre, correo, ficha, programa)
  - Competencia y proyecto formativo
  - Cronograma de actividades con fechas de entrega y checkbox "Entregado"
  - Firma manuscrita simulada del instructor (fuente Great Vibes)
  - Línea de firma del aprendiz
"""
from datetime import datetime, date, timedelta
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
    Flowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT


class CasillaVacia(Flowable):
    """Dibuja un cuadrado vacío (checkbox) del tamaño indicado."""
    def __init__(self, size=14):
        super().__init__()
        self.size = size
        self.width = size
        self.height = size

    def draw(self):
        from reportlab.lib import colors as _colors
        self.canv.setStrokeColor(_colors.HexColor("#2C2C2C"))
        self.canv.setLineWidth(1.2)
        self.canv.rect(0, 0, self.size, self.size)

# Paleta print-safe
DARK = colors.HexColor("#2C2C2C")
MID = colors.HexColor("#D0D0D0")
LIGHT = colors.HexColor("#F0F0F0")
WHITE = colors.white

# Ruta a la fuente de firma
FONT_PATH = Path(__file__).parent.parent / "templates" / "fonts" / "GreatVibes-Regular.ttf"

# Registrar la fuente una sola vez
_FONT_REGISTERED = False
def _asegurar_fuente_firma():
    global _FONT_REGISTERED
    if not _FONT_REGISTERED and FONT_PATH.exists():
        try:
            pdfmetrics.registerFont(TTFont("Firma", str(FONT_PATH)))
            _FONT_REGISTERED = True
        except Exception:
            pass
    return _FONT_REGISTERED


def calcular_cronograma(actividades: dict, fecha_inicio: date, horas_por_dia: float = 2.0) -> list:
    """Dado el dict de actividades (con 'duracion' en horas), calcula fecha_entrega para cada una.

    Retorna: lista de dicts con: numero, titulo, descripcion, horas, fecha_inicio, fecha_entrega
    """
    titulos = {
        "3.1": "Actividad 3.1 · Reflexión inicial",
        "3.2": "Actividad 3.2 · Contextualización",
        "3.3": "Actividad 3.3 · Apropiación",
        "3.4": "Actividad 3.4 · Transferencia",
    }
    resultado = []
    fecha_actual = fecha_inicio
    for key in ["3.1", "3.2", "3.3", "3.4"]:
        act = actividades.get(key, {})
        # Extraer horas de la duración (busca primer número entero)
        import re
        dur_str = act.get("duracion", "1 hora")
        m = re.search(r"(\d+(?:\.\d+)?)", dur_str)
        horas = float(m.group(1)) if m else 2.0
        # Días que tarda esta actividad (basado en horas y horas_por_dia)
        dias = max(1, int(round(horas / horas_por_dia)))
        fecha_entrega = _sumar_dias_habiles(fecha_actual, dias)
        resultado.append({
            "numero": key,
            "titulo": titulos.get(key, key),
            "descripcion": act.get("descripcion", "")[:180] + ("..." if len(act.get("descripcion", "")) > 180 else ""),
            "horas": horas,
            "fecha_inicio": fecha_actual,
            "fecha_entrega": fecha_entrega,
        })
        # Siguiente actividad empieza al día hábil siguiente
        fecha_actual = _sumar_dias_habiles(fecha_entrega, 1)
    return resultado


def calcular_cronograma_por_rango(actividades: dict, fecha_inicio: date, fecha_final: date) -> list:
    """Asigna la MISMA fecha_inicio y fecha_final a todas las actividades.
    Útil cuando el instructor define el rango completo de la etapa lectiva.

    Retorna: lista de dicts con la misma estructura que calcular_cronograma().
    """
    titulos = {
        "3.1": "Actividad 3.1 · Reflexión inicial",
        "3.2": "Actividad 3.2 · Contextualización",
        "3.3": "Actividad 3.3 · Apropiación",
        "3.4": "Actividad 3.4 · Transferencia",
    }
    resultado = []
    for key in ["3.1", "3.2", "3.3", "3.4"]:
        act = actividades.get(key, {})
        desc = act.get("descripcion", "")
        resultado.append({
            "numero": key,
            "titulo": titulos.get(key, key),
            "descripcion": desc[:180] + ("..." if len(desc) > 180 else ""),
            "horas": 0,  # ya no aplica en este modo
            "fecha_inicio": fecha_inicio,
            "fecha_entrega": fecha_final,
        })
    return resultado


def _esc(t) -> str:
    import html
    return html.escape(str(t or ""), quote=False)


def actividades_de_guia(guia: dict, incluir_transferencia: bool = True) -> list:
    """Actividades de aprendizaje de una guía generada desde la planeación (3.3.1, 3.3.2… tal cual)
    con su evidencia y sus horas; opcionalmente la actividad integradora 3.4."""
    salida = []
    for e in guia.get("_evidencias") or []:
        if e.get("integradora") and not incluir_transferencia:
            continue
        num = e.get("momento", "")
        salida.append({
            "numero": num,
            "titulo": (f"{num} Actividad de transferencia" if e.get("integradora")
                       else f"{num} Actividad de aprendizaje"),
            "descripcion": e.get("actividad", ""),
            "evidencia": e.get("evidencia", ""),
            "horas": float(e.get("horas") or 0),
        })
    return salida


def cronograma_desde_guia(actividades: list, fecha_inicio: date, fecha_final: date,
                          modo: str = "horas") -> list:
    """Fechas para cada actividad de aprendizaje dentro del rango.
    modo 'horas': una tras otra, con días hábiles proporcionales a las horas de cada AA.
    modo 'rango': todas con el mismo inicio y la misma entrega."""
    dias = []
    d = fecha_inicio
    while d <= fecha_final:
        if d.weekday() < 5:
            dias.append(d)
        d += timedelta(days=1)
    n = len(actividades)
    if modo == "rango" or not dias or len(dias) < n:
        return [{**a, "fecha_inicio": fecha_inicio, "fecha_entrega": fecha_final} for a in actividades]
    pesos = [max(a.get("horas") or 0, 1) for a in actividades]
    libres, tot = len(dias) - n, sum(pesos)
    extra = [libres * p / tot for p in pesos]
    asign = [1 + int(x) for x in extra]
    resto = len(dias) - sum(asign)
    for k in sorted(range(n), key=lambda k: -(extra[k] - int(extra[k])))[:resto]:
        asign[k] += 1
    salida, pos = [], 0
    for a, c in zip(actividades, asign):
        salida.append({**a, "fecha_inicio": dias[pos], "fecha_entrega": dias[pos + c - 1]})
        pos += c
    return salida


def contar_dias_habiles(inicio: date, fin: date) -> int:
    """Cuenta los días hábiles (lunes a viernes) entre dos fechas, inclusive."""
    if fin < inicio:
        return 0
    dias = 0
    actual = inicio
    while actual <= fin:
        if actual.weekday() < 5:  # 0-4 = lunes a viernes
            dias += 1
        actual += timedelta(days=1)
    return dias


def _sumar_dias_habiles(desde: date, dias: int) -> date:
    """Suma días hábiles (excluye sábados y domingos)."""
    resultado = desde
    agregados = 0
    while agregados < dias:
        resultado += timedelta(days=1)
        if resultado.weekday() < 5:  # 0-4 = lunes a viernes
            agregados += 1
    return resultado


def generar_plan_trabajo(datos_aprendiz: dict, datos_guia: dict, cronograma: list,
                        instructor: dict, ruta_salida: str) -> str:
    """Genera el PDF del Plan de Trabajo.

    datos_aprendiz: {nombre, apellidos, correo, ficha, programa}
    datos_guia: {programa, competencia, proyecto_formativo, fase}
    cronograma: lista devuelta por calcular_cronograma()
    instructor: {nombre, cargo}
    """
    _asegurar_fuente_firma()

    doc = SimpleDocTemplate(
        ruta_salida,
        pagesize=letter,
        leftMargin=1.8*cm, rightMargin=1.8*cm,
        topMargin=1.2*cm, bottomMargin=1.2*cm,
        title=f"Plan de Trabajo - {datos_aprendiz.get('nombre', '')}",
    )

    styles = getSampleStyleSheet()
    story = []

    # Estilos personalizados
    st_titulo = ParagraphStyle("Titulo", parent=styles["Heading1"],
                                fontSize=18, textColor=DARK, alignment=TA_CENTER,
                                spaceAfter=6, spaceBefore=0)
    st_subtitulo = ParagraphStyle("Subtitulo", parent=styles["Heading2"],
                                   fontSize=11, textColor=DARK, alignment=TA_CENTER,
                                   spaceAfter=14)
    st_seccion = ParagraphStyle("Seccion", parent=styles["Heading3"],
                                 fontSize=12, textColor=DARK, spaceAfter=6, spaceBefore=12)
    st_normal = ParagraphStyle("Normal2", parent=styles["Normal"],
                                fontSize=10, textColor=DARK, spaceAfter=4)

    # ---- Encabezado institucional ----
    story.append(Paragraph("SERVICIO NACIONAL DE APRENDIZAJE — SENA", st_subtitulo))
    story.append(Paragraph("PLAN DE TRABAJO INDIVIDUAL DEL APRENDIZ", st_titulo))
    story.append(Spacer(1, 0.4*cm))

    # ---- Datos del aprendiz ----
    story.append(Paragraph("<b>1. Datos del Aprendiz</b>", st_seccion))
    nombre_completo = f"{datos_aprendiz.get('nombre', '')} {datos_aprendiz.get('apellidos', '')}".strip()
    tabla_datos = Table([
        ["Nombre completo:", nombre_completo],
        ["Correo electrónico:", datos_aprendiz.get("correo", "")],
        ["Número de ficha:", str(datos_aprendiz.get("ficha", ""))],
        ["Programa de formación:", datos_aprendiz.get("programa", "") or datos_guia.get("programa", "")],
    ], colWidths=[5*cm, 12*cm])
    tabla_datos.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("TEXTCOLOR", (0, 0), (-1, -1), DARK),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.4, MID),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tabla_datos)

    # ---- Competencia y proyecto ----
    story.append(Paragraph("<b>2. Competencia y Proyecto</b>", st_seccion))
    st_val = ParagraphStyle("val", parent=styles["Normal"], fontSize=9, textColor=DARK, leading=11)
    tabla_comp = Table([
        ["Competencia:", Paragraph(_esc(datos_guia.get("competencia", "")), st_val)],
        ["Proyecto formativo:", Paragraph(_esc(datos_guia.get("proyecto_formativo", "")), st_val)],
        ["Fase:", Paragraph(_esc(datos_guia.get("fase_proyecto", "")), st_val)],
    ], colWidths=[5*cm, 12*cm])
    tabla_comp.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 0), (-1, -1), DARK),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (0, -1), LIGHT),
        ("GRID", (0, 0), (-1, -1), 0.4, MID),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(tabla_comp)

    # ---- Cronograma de actividades ----
    story.append(Paragraph("<b>3. Cronograma de Actividades</b>", st_seccion))
    st_cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=8.5,
                             textColor=DARK, leading=11)
    con_evidencia = any(a.get("evidencia") for a in cronograma)
    if con_evidencia:
        # Plan enlazado a la guía: una fila por ACTIVIDAD DE APRENDIZAJE, con su evidencia
        filas = [["Actividad de aprendizaje", "Evidencia", "Inicio", "Entrega", "Entregado"]]
        for act in cronograma:
            tit = f"<b>{act['titulo']}</b>" + (f" ({act['horas']:.0f} h)" if act.get("horas") else "")
            filas.append([
                Paragraph(f"{tit}<br/>{_esc(act['descripcion'])}", st_cell),
                Paragraph(_esc(act.get("evidencia", "")).replace("\n", "<br/>"), st_cell),
                act["fecha_inicio"].strftime("%d/%m/%Y"),
                act["fecha_entrega"].strftime("%d/%m/%Y"),
                CasillaVacia(size=14),
            ])
        anchos = [6.4*cm, 5.0*cm, 1.9*cm, 1.9*cm, 1.8*cm]
    else:
        filas = [["Actividad", "Descripción", "Inicio", "Entrega", "Entregado"]]
        anchos = [3.5*cm, 6.5*cm, 2.2*cm, 2.2*cm, 2.2*cm]
    for act in ([] if con_evidencia else cronograma):
        # Si no hay horas definidas (modo por rango de fechas), omitir "(X h)"
        titulo_display = f"<b>{act['titulo']}</b>"
        if act.get("horas", 0) > 0:
            titulo_display += f"<br/>({act['horas']:.0f} h)"
        filas.append([
            Paragraph(titulo_display, st_cell),
            Paragraph(act["descripcion"], st_cell),
            act["fecha_inicio"].strftime("%d/%m/%Y"),
            act["fecha_entrega"].strftime("%d/%m/%Y"),
            CasillaVacia(size=14),  # Casilla vacía para marcar cuando esté entregado
        ])
    tabla_crono = Table(filas, colWidths=anchos, repeatRows=1)
    tabla_crono.setStyle(TableStyle([
        # Encabezado
        ("BACKGROUND", (0, 0), (-1, 0), DARK),
        ("TEXTCOLOR", (0, 0), (-1, 0), WHITE),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 6),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
        # Filas
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, -1), DARK),
        ("ALIGN", (2, 1), (4, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [WHITE, LIGHT]),
        ("GRID", (0, 0), (-1, -1), 0.4, MID),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 1), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 6),
        # Casilla "Entregado" más grande
        ("FONTSIZE", (4, 1), (4, -1), 14),
    ]))
    story.append(tabla_crono)

    # ---- Compromiso ----
    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph("<b>4. Compromiso del Aprendiz</b>", st_seccion))
    story.append(Paragraph(
        "Como aprendiz SENA, me comprometo a cumplir con las actividades del cronograma "
        "en las fechas establecidas, participar activamente en las sesiones presenciales, "
        "y entregar las evidencias solicitadas conforme a los criterios de evaluación "
        "definidos por el instructor.",
        st_normal
    ))

    # ---- Firmas ----
    story.append(Spacer(1, 0.7*cm))

    # Fecha de emisión
    fecha_emision = date.today().strftime("%d de %B de %Y")
    meses_es = {"January": "enero", "February": "febrero", "March": "marzo",
                "April": "abril", "May": "mayo", "June": "junio",
                "July": "julio", "August": "agosto", "September": "septiembre",
                "October": "octubre", "November": "noviembre", "December": "diciembre"}
    for en, es in meses_es.items():
        fecha_emision = fecha_emision.replace(en, es)

    # Firma del instructor (usa fuente cursiva si está disponible)
    nombre_instructor = instructor.get("nombre", "Instructor SENA")
    cargo_instructor = instructor.get("cargo", "Instructor")

    fuente_firma = "Firma" if _FONT_REGISTERED else "Times-Italic"
    st_firma_cursiva = ParagraphStyle("firma_cursiva", parent=styles["Normal"],
                                       fontName=fuente_firma, fontSize=28,
                                       textColor=DARK, alignment=TA_CENTER,
                                       spaceAfter=0)

    tabla_firmas = Table([
        [
            Paragraph(nombre_instructor, st_firma_cursiva),
            "",
        ],
        [
            Paragraph("_" * 30, ParagraphStyle("linea", parent=styles["Normal"],
                                                alignment=TA_CENTER, fontSize=10)),
            Paragraph("_" * 30, ParagraphStyle("linea2", parent=styles["Normal"],
                                                 alignment=TA_CENTER, fontSize=10)),
        ],
        [
            Paragraph(f"<b>{nombre_instructor}</b><br/>{cargo_instructor}<br/>"
                      f"Centro de Formación SENA",
                      ParagraphStyle("firma_pie", parent=styles["Normal"],
                                     alignment=TA_CENTER, fontSize=9, textColor=DARK)),
            Paragraph(f"<b>{nombre_completo}</b><br/>Aprendiz<br/>"
                      f"Ficha {datos_aprendiz.get('ficha', '')}",
                      ParagraphStyle("firma_pie2", parent=styles["Normal"],
                                     alignment=TA_CENTER, fontSize=9, textColor=DARK)),
        ],
    ], colWidths=[9*cm, 9*cm])
    tabla_firmas.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, 0), 0),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
    ]))
    story.append(tabla_firmas)

    story.append(Spacer(1, 0.5*cm))
    story.append(Paragraph(
        f"<i>Documento emitido el {fecha_emision}</i>",
        ParagraphStyle("pie", parent=styles["Normal"], alignment=TA_CENTER,
                       fontSize=8, textColor=MID)
    ))

    doc.build(story)
    return ruta_salida
