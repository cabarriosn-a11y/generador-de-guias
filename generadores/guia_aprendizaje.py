"""Guía de Aprendizaje del Aprendiz — formato oficial GFPI-F-135 (V04) del SENA.

DILIGENCIA LA PLANTILLA OFICIAL EN SU SITIO (no la redibuja)
------------------------------------------------------------
La versión anterior vaciaba el cuerpo de la plantilla y lo reconstruía con viñetas escritas
a mano ("•  "), tablas con fondo oscuro y letra gris: nada de eso es el formato auditado.

Ahora:
  * Cada valor se escribe DETRÁS de su rótulo oficial, heredando la fuente del rótulo
    (Calibri 12 en identificación; estilo Normal en las actividades).
  * Las listas usan las VIÑETAS REALES de Word definidas en la propia plantilla
    (misma numeración que "Resultados de Aprendizaje" y la sección 2).
  * Las filas de las tablas 4 y 7 se CLONAN de la fila vacía oficial (bordes, anchos y
    sombreado intactos).
  * Encabezado, pie (GFPI-F-135 V04), logo, márgenes y tamaño carta no se tocan.
  * Los textos guía de la plantilla ("Motivar hacia la actividad…", "Construya o cite…")
    son instrucciones para quien diligencia: se reemplazan por el contenido real.

La firma de la función y la estructura de `datos` no cambian (compatibles con app.py).
"""
from __future__ import annotations

import re
import shutil
import unicodedata
from copy import deepcopy

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .utils_docx import TEMPLATE_PATH


# ─────────────────────────────── utilidades XML ───────────────────────────────
def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t or "")
    t = "".join(ch for ch in t if unicodedata.category(ch) != "Mn")
    return re.sub(r"\s+", " ", t).strip().lower()


def _rpr_de(paragraph: Paragraph, quitar_negrita=True):
    """rPr del último run con texto del párrafo (formato del rótulo oficial)."""
    runs = [r for r in paragraph.runs if r.text.strip()] or paragraph.runs
    if not runs or runs[-1]._r.rPr is None:
        return None
    rpr = deepcopy(runs[-1]._r.rPr)
    if quitar_negrita:
        for tag in ("w:b", "w:bCs"):
            for el in rpr.findall(qn(tag)):
                rpr.remove(el)
    return rpr


def _asegurar_fuente(rpr, tam_pt=None, quitar_color=False):
    """Garantiza Calibri (la letra del formato) aunque el rótulo herede la fuente del tema,
    y opcionalmente quita el color (p. ej. el blanco de los encabezados oscuros)."""
    from docx.oxml import OxmlElement
    if rpr is None:
        rpr = OxmlElement("w:rPr")
    f = rpr.find(qn("w:rFonts"))
    if f is None:
        f = OxmlElement("w:rFonts")
        rpr.insert(0, f)
    for att in ("w:ascii", "w:hAnsi", "w:cs"):
        if f.get(qn(att)) is None:
            f.set(qn(att), "Calibri")
    if tam_pt and rpr.find(qn("w:sz")) is None:
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), str(int(tam_pt * 2)))
        rpr.append(sz)
    if quitar_color:
        for tag in ("w:color", "w:shd", "w:highlight"):
            for el in rpr.findall(qn(tag)):
                rpr.remove(el)
    return rpr


def _run(paragraph: Paragraph, texto: str, rpr=None, negrita=None):
    rpr = _asegurar_fuente(deepcopy(rpr) if rpr is not None else None)
    r = paragraph.add_run(texto)
    if rpr is not None:
        if r._r.rPr is not None:
            r._r.remove(r._r.rPr)
        r._r.insert(0, deepcopy(rpr))
    if negrita is not None:
        r.bold = negrita
    return r


def _vaciar(paragraph: Paragraph):
    for r in list(paragraph._p):
        if r.tag in (qn("w:r"), qn("w:hyperlink"), qn("w:ins")):
            paragraph._p.remove(r)


def _clonar_despues(ref: Paragraph, base: Paragraph | None = None) -> Paragraph:
    """Inserta después de `ref` un párrafo con las propiedades (estilo, sangría,
    numeración) de `base` (por defecto `ref`) y sin texto."""
    base = base or ref
    nuevo = deepcopy(base._p)
    for hijo in list(nuevo):
        if hijo.tag != qn("w:pPr"):
            nuevo.remove(hijo)
    ref._p.addnext(nuevo)
    return Paragraph(nuevo, ref._parent)


def _quitar_numeracion(p: Paragraph):
    ppr = p._p.pPr
    if ppr is not None:
        for n in ppr.findall(qn("w:numPr")):
            ppr.remove(n)


def _nivel(p: Paragraph, ilvl: int):
    ppr = p._p.get_or_add_pPr()
    num = ppr.find(qn("w:numPr"))
    if num is None:
        return
    lv = num.find(qn("w:ilvl"))
    if lv is None:
        lv = num.makeelement(qn("w:ilvl"), {})
        num.insert(0, lv)
    lv.set(qn("w:val"), str(ilvl))


def _eliminar(p: Paragraph):
    p._p.getparent().remove(p._p)


ES_VINETA = re.compile(r"^\s*(?:[-•*▪►✓]|\d+[.)])\s+")


def _run_marcado(p: Paragraph, texto: str, rpr):
    """Escribe `texto` respetando **negrita** (solo para títulos 3.3.1, 3.3.2…; misma fuente y tamaño)."""
    partes = texto.split("**")
    for k, parte in enumerate(partes):
        if parte:
            _run(p, parte, rpr, negrita=True if k % 2 == 1 else None)


def _escribir_valor(etiqueta: Paragraph, valor, parrafo_vineta: Paragraph | None) -> Paragraph:
    """Escribe `valor` detrás del rótulo. Línea 1 en el mismo párrafo; las siguientes en
    párrafos clonados (con viñeta real de Word si la línea empieza con -, •, 1., …).
    Devuelve el último párrafo escrito."""
    lineas = [l.rstrip() for l in str(valor or "").replace("\r", "").split("\n")]
    while lineas and not lineas[-1].strip():
        lineas.pop()
    rpr = _rpr_de(etiqueta)
    texto_rotulo = etiqueta.text
    if lineas and texto_rotulo and not texto_rotulo.endswith((" ", "\t")):
        _run(etiqueta, " ", rpr)
    ultimo = etiqueta
    for k, linea in enumerate(lineas):
        if k == 0 and not ES_VINETA.match(linea):
            _run_marcado(etiqueta, linea.strip(), rpr)
            continue
        if not linea.strip():
            continue
        if ES_VINETA.match(linea) and parrafo_vineta is not None:
            p = _clonar_despues(ultimo, parrafo_vineta)
            _run_marcado(p, ES_VINETA.sub("", linea).strip(), rpr)
        else:
            p = _clonar_despues(ultimo, etiqueta)
            _quitar_numeracion(p)
            _run_marcado(p, linea.strip(), rpr)
        ultimo = p
    return ultimo


def _llenar_fila(fila, valores, rpr=None):
    for celda, valor in zip(fila.cells, valores):
        p = celda.paragraphs[0]
        _vaciar(p)
        for extra in celda.paragraphs[1:]:
            _eliminar(extra)
        lineas = [l for l in str(valor or "").split("\n")]
        for k, l in enumerate(lineas):
            r = _run(p, l, rpr, negrita=False)
            if k < len(lineas) - 1:
                r.add_break()


def _llenar_tabla(tabla, filas: list[list], idx_plantilla=1):
    """Clona la fila vacía oficial `idx_plantilla` por cada fila de datos."""
    if not filas:
        return
    tr_base = tabla.rows[idx_plantilla]._tr
    # formato de letra: el del encabezado de la tabla sin negrita
    rpr = None
    enc = tabla.rows[0].cells[0].paragraphs[0]
    if enc.runs:
        rpr = _asegurar_fuente(_rpr_de(enc), quitar_color=True)
    ancla = tr_base
    for n, valores in enumerate(filas):
        tr = tr_base if n == 0 else deepcopy(tr_base)
        if n:
            ancla.addnext(tr)
            ancla = tr
        from docx.table import _Row
        _llenar_fila(_Row(tr, tabla), valores, rpr)


def _num_horas(v) -> str:
    m = re.search(r"\d+(?:[.,]\d+)?", str(v or ""))
    return m.group(0) if m else ""


# ─────────────────────────────── generador ───────────────────────────────
ROTULOS_1 = [
    ("denominacion del programa", "programa"),
    ("codigo del programa", "codigo_programa"),
    ("nombre del proyecto formativo", "proyecto_formativo"),
    ("fase del proyecto", "fase_proyecto"),
    ("actividad de proyecto formativo", "actividad_proyecto"),
    ("competencia", "competencia"),
    ("duracion de la guia", "duracion"),
]
ROTULOS_3 = [
    ("descripcion de la actividad", "descripcion"),
    ("ambiente requerido", "ambiente"),
    ("estrategias o tecnicas", "estrategias"),
    ("materiales de formacion", "materiales"),
    ("material de apoyo", "apoyo"),
    ("evidencias de aprendizaje", "evidencias"),
    ("instrumentos de evaluacion", "instrumentos"),
]


def generar_guia_aprendizaje(datos: dict, ruta_salida: str) -> str:
    shutil.copy(TEMPLATE_PATH, ruta_salida)
    doc = Document(ruta_salida)
    pars = list(doc.paragraphs)
    txt = [_norm(p.text) for p in pars]

    def buscar(prefijo, desde=0):
        for k in range(desde, len(pars)):
            if txt[k].startswith(prefijo):
                return k
        return None

    # ===== 1. IDENTIFICACIÓN =====
    i_raps = buscar("resultados de aprendizaje")
    vineta_1 = pars[i_raps] if i_raps is not None else None
    limite_1 = buscar("2. presentacion") or len(pars)
    for prefijo, clave in ROTULOS_1:
        k = buscar(prefijo)
        if k is None or k >= limite_1:
            continue
        valor = datos.get(clave, "")
        if clave == "duracion":
            h = _num_horas(valor)
            valor = h or valor
        _escribir_valor(pars[k], valor, vineta_1)
    if i_raps is not None:
        ultimo = pars[i_raps]
        for rap in [r for r in datos.get("raps", []) if str(r).strip()]:
            p = _clonar_despues(ultimo, pars[i_raps])
            _nivel(p, 1)                               # sub-viñeta oficial bajo el rótulo
            _run(p, str(rap).strip(), _rpr_de(pars[i_raps]))
            ultimo = p

    # ===== 2. PRESENTACIÓN (reemplaza las 5 viñetas-instrucción de la plantilla) =====
    k2, k3 = buscar("2. presentacion"), buscar("3. formulacion")
    presentacion = [x.strip() for x in re.split(r"\n\s*\n", datos.get("presentacion", "")) if x.strip()]
    if k2 is not None and k3 is not None and presentacion:
        guias = [pars[k] for k in range(k2 + 1, k3) if pars[k].text.strip()]
        base = guias[0] if guias else pars[k2]
        ancla = pars[k2 + 1] if k2 + 1 < k3 else pars[k2]
        for parrafo in presentacion:
            p = _clonar_despues(ancla, base)
            _quitar_numeracion(p)
            p.paragraph_format.alignment = 3            # justificado
            _run(p, parrafo.replace("\n", " "), _rpr_de(base))
            ancla = p
        for g in guias:
            _eliminar(g)

    # ===== 3. ACTIVIDADES 3.1 – 3.4 =====
    pars = list(doc.paragraphs)
    txt = [_norm(p.text) for p in pars]
    vineta_2 = next((p for p in pars if p._p.pPr is not None and p._p.pPr.find(qn("w:numPr")) is not None
                     and _norm(p.text).startswith("descripcion de la(s)")), vineta_1)
    actividades = datos.get("actividades", {})
    inicios = {key: buscar(key + " ") for key in ("3.1", "3.2", "3.3", "3.4")}
    k4 = buscar("4. planteamiento")
    orden = [k for k in ("3.1", "3.2", "3.3", "3.4") if inicios[k] is not None]
    for n, key in enumerate(orden):
        ini = inicios[key]
        fin = inicios[orden[n + 1]] if n + 1 < len(orden) else (k4 or len(pars))
        act = actividades.get(key, {}) or {}
        for k in range(ini + 1, fin):
            t = txt[k]
            if t.startswith("duracion de la actividad"):
                p = pars[k]
                rpr = _rpr_de(p)
                _vaciar(p)
                h = _num_horas(act.get("duracion"))
                _run(p, f"Duración de la actividad: {h} horas." if h else "Duración de la actividad:  horas.", rpr)
                continue
            for prefijo, clave in ROTULOS_3:
                if t.startswith(prefijo) and act.get(clave):
                    if clave == "materiales" and not pars[k].text.rstrip().endswith(":"):
                        _run(pars[k], ":", _rpr_de(pars[k]))
                    _escribir_valor(pars[k], act.get(clave), vineta_2)
                    break

    # ===== 4. TABLA DE EVIDENCIAS =====
    filas_ev = datos.get("evidencias_tabla") or []
    if filas_ev and doc.tables:
        cuerpo = filas_ev[1:] if filas_ev and _norm(str(filas_ev[0][0])).startswith("fase") else filas_ev
        _llenar_tabla(doc.tables[0], [list(f) + [""] * (6 - len(f)) for f in cuerpo])

    # ===== 5. GLOSARIO y 6. REFERENTES =====
    pars = list(doc.paragraphs)
    txt = [_norm(p.text) for p in pars]
    k5, k6, k7 = buscar("5. glosario"), buscar("6. referentes"), buscar("7. control del documento")
    estilo_texto = pars[k6 + 1] if k6 is not None else None      # "Construya o cite…" (12 pt)
    if k5 is not None and datos.get("glosario") and estilo_texto is not None:
        ancla = pars[k5]
        for item in datos["glosario"]:
            termino, definicion = (item if isinstance(item, (list, tuple)) else (item, ""))[:2]
            p = _clonar_despues(ancla, estilo_texto)
            p.paragraph_format.alignment = 3
            rpr = _rpr_de(estilo_texto)
            _run(p, f"{str(termino).strip().rstrip(':')}: ", rpr, negrita=True)
            _run(p, str(definicion).strip(), rpr)
            ancla = p
    if k6 is not None and datos.get("referentes"):
        instr = pars[k6 + 1]
        vacios = [pars[k] for k in range(k6 + 2, k7 or k6 + 2) if not pars[k].text.strip()]
        ancla = instr
        for ref in datos["referentes"]:
            p = _clonar_despues(ancla, vineta_1 or instr)
            _nivel(p, 0)
            _run(p, str(ref).strip(), _rpr_de(vineta_1) if vineta_1 is not None else _rpr_de(instr))
            ancla = p
        _eliminar(instr)                                   # instrucción de la plantilla
        for v in vacios[1:]:                               # deja un solo espacio antes de 7.
            _eliminar(v)

    # ===== 7. CONTROL DEL DOCUMENTO =====
    if len(doc.tables) >= 2:
        fila = doc.tables[1].rows[1]
        valores = [datos.get("autor_nombre", ""), datos.get("autor_cargo", "Instructor"),
                   datos.get("autor_dependencia", ""), datos.get("autor_fecha", "")]
        rpr = _rpr_de(doc.tables[1].rows[0].cells[1].paragraphs[0])
        for celda, v in zip(fila.cells[1:], valores):
            p = celda.paragraphs[0]
            _vaciar(p)
            _run(p, str(v or ""), rpr, negrita=False)

    doc.save(ruta_salida)
    return ruta_salida
