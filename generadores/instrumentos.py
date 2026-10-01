"""Instrumentos de evaluación a partir de una GUÍA DE APRENDIZAJE ya generada.

La guía (JSON guardado junto al Word) trae la trazabilidad: fase, actividad del proyecto,
RAP, actividad de aprendizaje, evidencia y criterios de evaluación (del diseño curricular).
Con eso se arman:
- Lista de chequeo (desempeño / producto): indicadores observables ligados a los criterios.
- Rúbrica analítica de 4 niveles (producto): un criterio por fila, verbatim del diseño.
- Cuestionario (conocimiento): preguntas de selección múltiple con clave para el instructor.

Los instrumentos NO tienen formato institucional: se entregan en un Word propio con la línea
gráfica LogiLab SENA (verde #39A900). El juicio es SENA: Aprobado / No aprobado.
"""
from __future__ import annotations

import re
import unicodedata

from docx import Document
from docx.enum.section import WD_ORIENT
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

VERDE = "39A900"
VERDE_CLARO = "E8F5E0"
GRIS = "F2F2F2"
OSCURO = RGBColor(0x1F, 0x2D, 0x1A)

TIPOS = {
    "lista_chequeo": "Lista de chequeo",
    "rubrica": "Rúbrica analítica",
    "cuestionario": "Cuestionario",
}
NIVELES = [("excelente", "Excelente", 4), ("bueno", "Bueno", 3),
           ("aceptable", "Aceptable", 2), ("por_mejorar", "Por mejorar", 1)]
REGLA_DEFECTO = {
    "lista_chequeo": "Aprobado: cumple TODOS los indicadores. No aprobado: falta al menos uno.",
    "rubrica": "Aprobado: todos los criterios en nivel Aceptable o superior. No aprobado: algún criterio en «Por mejorar».",
    "cuestionario": "Aprobado: mínimo el 70 % de respuestas correctas. No aprobado: menos del 70 %.",
}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


# ─────────────────────────────── evidencias de la guía ───────────────────────────────
_RE_TIPO = re.compile(r"evidencias?\s+de\s+(conocimiento|desempe[nñ]o|producto)\s*[:.\-–]?\s*", re.I)


def tipo_evidencia(texto: str) -> str:
    n = _norm(texto)
    if re.search(r"conocimiento|cuestionario|prueba escrita|examen|test", n):
        return "conocimiento"
    if re.search(r"producto|informe|documento|entregable|plan |formato|matriz|propuesta|ficha|presentacion", n):
        return "producto"
    return "desempeno"


def partir_evidencia(texto: str) -> list[tuple[str, str]]:
    """'Evidencia de conocimiento: X. Evidencia de producto: Y' → [(conocimiento, X), (producto, Y)]."""
    texto = str(texto or "").strip()
    marcas = list(_RE_TIPO.finditer(texto))
    if not marcas:
        return [(tipo_evidencia(texto), texto)] if texto else []
    salida = []
    for i, m in enumerate(marcas):
        fin = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        cuerpo = texto[m.end():fin].strip(" .;\n")
        if cuerpo:
            salida.append(("desempeno" if _norm(m.group(1)).startswith("desempe") else _norm(m.group(1)), cuerpo))
    return salida


def instrumento_sugerido(tipo: str) -> str:
    return {"conocimiento": "cuestionario", "producto": "rubrica"}.get(tipo, "lista_chequeo")


def _criterios_lista(c) -> list[str]:
    if isinstance(c, list):
        return [str(x).strip() for x in c if str(x).strip()]
    return [x.strip() for x in re.split(r"\n\s*\n|\n", str(c or "")) if x.strip()]


def evidencias_de_guia(guia: dict) -> list[dict]:
    """Lista plana de evidencias evaluables de la guía, cada una con su contexto."""
    base = guia.get("_evidencias")
    if not base:                                        # guías antiguas: desde la tabla 4
        base = []
        for fila in (guia.get("evidencias_tabla") or [])[1:]:
            if len(fila) >= 5:
                base.append({"fase": fila[0], "actividad_proyecto": fila[1], "rap": "",
                             "actividad": fila[2], "evidencia": fila[3], "criterios": fila[4]})
    items = []
    for e in base:
        for tipo, txt in partir_evidencia(e.get("evidencia", "")):
            items.append({
                "id": len(items), "tipo": tipo, "evidencia": txt,
                "fase": e.get("fase", ""), "actividad_proyecto": e.get("actividad_proyecto", ""),
                "rap": e.get("rap", ""), "actividad": e.get("actividad", ""),
                "criterios": _criterios_lista(e.get("criterios")),
                "instrumento": instrumento_sugerido(tipo),
            })
    return items


# ─────────────────────────────── contenido sin IA (plantilla) ───────────────────────────────
def _quitar_verbo_3p(c: str) -> str:
    c = c.rstrip(". ")
    if not c.isupper():
        return c
    # diseños en MAYÚSCULA → oración, conservando siglas (SST, NTC, ISO, EPP…)
    siglas = {"ISO", "NTC", "SENA", "PHVA", "EPP", "TIC", "DIAN", "RUT"}
    pal = [w if (w in siglas or (len(w) > 1 and not re.search(r"[AEIOUÁÉÍÓÚ]", w))) else w.lower() for w in c.split(" ")]
    t = " ".join(pal)
    return t[:1].upper() + t[1:]


def lista_base(item: dict) -> list[dict]:
    """Indicadores = criterios del diseño (verbatim), uno por fila."""
    crit = item.get("criterios") or [f"Entrega la evidencia: {item['evidencia']}"]
    return [{"indicador": _quitar_verbo_3p(c), "criterio": c} for c in crit]


def rubrica_base(item: dict) -> list[dict]:
    """Sin IA: criterio verbatim del diseño + descriptores graduados genéricos (cortos)."""
    return [{
        "criterio": c,
        "excelente": "Cumple el criterio de forma completa, precisa y argumentada; aporta valor adicional al proyecto.",
        "bueno": "Cumple el criterio de forma completa y correcta; quedan detalles menores por ajustar.",
        "aceptable": "Cumple lo mínimo exigido por el criterio, con apoyo del instructor.",
        "por_mejorar": "No evidencia el criterio; requiere plan de mejoramiento.",
    } for c in (item.get("criterios") or [item["evidencia"]])]


def cuestionario_base(item: dict, saberes: list[str], n: int = 5) -> list[dict]:
    """Sin IA solo se pueden proponer preguntas abiertas a partir de los saberes del diseño."""
    fuentes = [s for s in saberes if s] or item.get("criterios") or [item["evidencia"]]
    preguntas = []
    for s in fuentes[:n]:
        preguntas.append({"enunciado": f"Explica con tus palabras y con un ejemplo del proyecto: {s.rstrip('.')}.",
                          "a": "", "b": "", "c": "", "d": "", "correcta": "",
                          "justificacion": "Respuesta abierta: valora la precisión conceptual y la aplicación al contexto."})
    return preguntas


def contenido_base(item: dict, instrumento: str, saberes: list[str]) -> list[dict]:
    if instrumento == "rubrica":
        return rubrica_base(item)
    if instrumento == "cuestionario":
        return cuestionario_base(item, saberes)
    return lista_base(item)


# ─────────────────────────────── Word (línea LogiLab SENA) ───────────────────────────────
def _sombrear(celda, hex_color):
    tcPr = celda._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), hex_color)
    tcPr.append(shd)


def _bordes(tabla, color="9BBB8A"):
    tblPr = tabla._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for lado in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{lado}")
        e.set(qn("w:val"), "single"); e.set(qn("w:sz"), "4"); e.set(qn("w:color"), color)
        b.append(e)
    tblPr.append(b)


def _anchos(tabla, anchos):
    """Anchos fijos (Word y LibreOffice): sin autoajuste, con tblGrid y ancho por celda."""
    tabla.autofit = False
    tblPr = tabla._tbl.tblPr
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); tblPr.append(lay)
    for j, w in enumerate(anchos):
        tabla.columns[j].width = Cm(w)
        for c in tabla.columns[j].cells:
            c.width = Cm(w)


def _texto(celda, texto, negrita=False, tam=9, color=None, centro=False):
    celda.text = ""
    p = celda.paragraphs[0]
    p.paragraph_format.space_after = Pt(0)
    if centro:
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = p.add_run(str(texto or ""))
    r.bold = negrita; r.font.size = Pt(tam)
    if color:
        r.font.color.rgb = color


def _tabla(doc, filas, anchos, encabezado=True, tam=9):
    t = doc.add_table(rows=len(filas), cols=len(filas[0]))
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    _bordes(t)
    for i, fila in enumerate(filas):
        for j, v in enumerate(fila):
            c = t.cell(i, j)
            if encabezado and i == 0:
                _texto(c, v, True, tam, RGBColor(0xFF, 0xFF, 0xFF), True)
                _sombrear(c, VERDE)
            else:
                _texto(c, v, tam=tam)
    _anchos(t, anchos)
    return t


def _titulo(doc, texto, tam=12):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(10); p.paragraph_format.space_after = Pt(4)
    r = p.add_run(texto); r.bold = True; r.font.size = Pt(tam)
    r.font.color.rgb = RGBColor(0x39, 0xA9, 0x00)
    return p


def _identificacion(doc, guia, item, nombre_inst):
    filas = [
        ("Programa de formación", f"{guia.get('programa', '')} {('(' + guia['codigo_programa'] + ')') if guia.get('codigo_programa') else ''}"),
        ("Proyecto formativo", guia.get("proyecto_formativo", "")),
        ("Fase / actividad del proyecto", f"{item['fase']} · {item['actividad_proyecto']}"),
        ("Competencia", guia.get("competencia", "")),
        ("Resultado de aprendizaje", item.get("rap", "") or "; ".join(guia.get("raps", []))),
        ("Actividad de aprendizaje", item.get("actividad", "")),
        ("Evidencia", f"{item['tipo'].replace('desempeno', 'desempeño').capitalize()}: {item['evidencia']}"),
        ("Instrumento", nombre_inst),
        ("Aprendiz / ficha", "______________________________   Ficha: ____________"),
        ("Fecha", "____ / ____ / ________"),
    ]
    t = doc.add_table(rows=len(filas), cols=2)
    _bordes(t)
    for i, (k, v) in enumerate(filas):
        _texto(t.cell(i, 0), k, True, 9); _sombrear(t.cell(i, 0), VERDE_CLARO)
        _texto(t.cell(i, 1), v, tam=9)
    _anchos(t, [5, 19.3])


def _juicio(doc, regla):
    _titulo(doc, "Juicio de evaluación", 10)
    t = doc.add_table(rows=2, cols=3)
    _bordes(t)
    for j, v in enumerate(("☐ APROBADO", "☐ NO APROBADO", "Observaciones / plan de mejoramiento")):
        _texto(t.cell(0, j), v, True, 9, centro=True); _sombrear(t.cell(0, j), VERDE_CLARO)
    _texto(t.cell(1, 2), "\n\n")
    _anchos(t, [4, 4, 16.3])
    p = doc.add_paragraph(); r = p.add_run("Regla: " + regla); r.italic = True; r.font.size = Pt(8)
    f = doc.add_table(rows=1, cols=2)
    _texto(f.cell(0, 0), "\n\n______________________________\nFirma del instructor", tam=9, centro=True)
    _texto(f.cell(0, 1), "\n\n______________________________\nFirma del aprendiz", tam=9, centro=True)
    _anchos(f, [12.15, 12.15])


def _pie(doc):
    for s in doc.sections:
        p = s.footer.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run("LogiLab SENA · Instrumentos de evaluación · By Carlos Barrios · Instructor")
        r.font.size = Pt(8); r.font.color.rgb = RGBColor(0x39, 0xA9, 0x00)


def generar_instrumentos_docx(guia: dict, instrumentos: list[dict], ruta: str) -> str:
    """`instrumentos` = [{"item": evidencia, "tipo": lista_chequeo|rubrica|cuestionario,
    "contenido": [...], "regla": str}]. Un instrumento por página; la clave del
    cuestionario va al final, en hoja aparte, solo para el instructor."""
    doc = Document()
    st = doc.styles["Normal"]; st.font.name = "Calibri"; st.font.size = Pt(10)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), "Calibri")
    sec = doc.sections[0]
    sec.orientation = WD_ORIENT.LANDSCAPE
    sec.page_width, sec.page_height = Cm(27.94), Cm(21.59)
    for m in ("left_margin", "right_margin"):
        setattr(sec, m, Cm(1.8))
    sec.top_margin = sec.bottom_margin = Cm(1.5)
    _pie(doc)

    claves = []
    for n, ins in enumerate(instrumentos):
        if n:
            doc.add_page_break()
        item, tipo, cont = ins["item"], ins["tipo"], ins.get("contenido") or []
        nombre = TIPOS.get(tipo, tipo)
        p = doc.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.LEFT
        r = p.add_run(f"INSTRUMENTO DE EVALUACIÓN · {nombre.upper()}"); r.bold = True; r.font.size = Pt(14)
        r.font.color.rgb = RGBColor(0x39, 0xA9, 0x00)
        _identificacion(doc, guia, item, nombre)

        if tipo == "lista_chequeo":
            _titulo(doc, "Indicadores de evaluación", 10)
            filas = [["N.°", "Indicador", "Sí", "No", "Observaciones"]]
            filas += [[str(i + 1), c.get("indicador", ""), "☐", "☐", ""] for i, c in enumerate(cont)]
            _tabla(doc, filas, [1, 15, 1.2, 1.2, 5.9])
        elif tipo == "rubrica":
            _titulo(doc, "Rúbrica analítica (4 niveles)", 10)
            filas = [["Criterio de evaluación"] + [f"{t} ({p})" for _, t, p in NIVELES] + ["Puntaje"]]
            filas += [[c.get("criterio", "")] + [c.get(k, "") for k, _, _ in NIVELES] + [""] for c in cont]
            _tabla(doc, filas, [5, 4.45, 4.45, 4.45, 4.45, 1.5], tam=8)
        else:
            _titulo(doc, "Cuestionario", 10)
            p = doc.add_paragraph("Instrucción: lee cada enunciado y marca con una X la opción correcta. "
                                  "En las preguntas abiertas responde con tus palabras.")
            p.runs[0].font.size = Pt(9)
            for i, q in enumerate(cont):
                pq = doc.add_paragraph(); pq.paragraph_format.space_after = Pt(2)
                rq = pq.add_run(f"{i + 1}. {q.get('enunciado', '')}"); rq.bold = True; rq.font.size = Pt(10)
                ops = [(k, q.get(k, "")) for k in "abcd" if str(q.get(k, "")).strip()]
                if ops:
                    for k, v in ops:
                        po = doc.add_paragraph(f"     ☐ {k}) {v}"); po.paragraph_format.space_after = Pt(0)
                        po.runs[0].font.size = Pt(9.5)
                else:
                    doc.add_paragraph("_" * 120 + "\n" + "_" * 120).runs[0].font.size = Pt(9)
            claves.append((item, cont))
        _juicio(doc, ins.get("regla") or REGLA_DEFECTO.get(tipo, ""))

    for item, cont in claves:
        doc.add_page_break()
        p = doc.add_paragraph(); r = p.add_run("CLAVE DE RESPUESTAS · SOLO PARA EL INSTRUCTOR")
        r.bold = True; r.font.size = Pt(13); r.font.color.rgb = RGBColor(0x39, 0xA9, 0x00)
        doc.add_paragraph(f"Evidencia: {item['evidencia']}").runs[0].font.size = Pt(9)
        filas = [["N.°", "Respuesta correcta", "Justificación"]]
        filas += [[str(i + 1), (q.get("correcta", "") or "Abierta").upper(), q.get("justificacion", "")]
                  for i, q in enumerate(cont)]
        _tabla(doc, filas, [1, 3.5, 19.8])
    doc.save(ruta)
    return ruta
