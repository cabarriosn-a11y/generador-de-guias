"""Genera la Planeación Pedagógica (formato oficial GFPI-F-134) del SENA.

Estrategia: usa la plantilla oficial GFPI-F-134.xlsx como base y solo llena las celdas
de datos, preservando encabezado institucional, celdas fusionadas y formato oficial.

FORMATO DE FILAS (v2 — una fila por RAP):
La plantilla oficial trae la columna "RESULTADOS DE APRENDIZAJE" pensada para UN RAP por
fila. Cada competencia (3, 4 o 5 RAP típicamente) se reparte aquí en tantas filas de Excel
como RAP tenga. Las columnas que NO cambian por RAP se fusionan verticalmente en una sola
celda combinada que abarca esas filas:

  - COMPETENCIA, Saberes (conceptos/proceso), Criterios de Evaluación, Horas, Actividades
    de Aprendizaje, Evidencia, Estrategias, Ambiente, Materiales, Instructores y
    Observaciones -> se fusionan DENTRO del bloque de su propia competencia.
  - FASE y ACTIVIDAD DE PROYECTO FORMATIVO -> se fusionan igual, pero además ENTRE
    competencias consecutivas si comparten el mismo texto (una fase o actividad puede
    agrupar varias competencias, tal como en el formato oficial impreso).
  - RESULTADOS DE APRENDIZAJE (RAP) -> es la ÚNICA columna que nunca se fusiona: cada RAP
    vive en su propia fila, que es justamente el objetivo de esta reorganización.

La estructura de datos de entrada NO cambia (se sigue editando 1 bloque = 1 competencia
en la UI; "raps" sigue siendo un texto con un RAP por línea). Toda la lógica de reparto y
fusión ocurre aquí, al momento de generar el Excel.

{
  "fecha_elaboracion": "2026-07-21",
  "programa": "Técnico en Integración de Operaciones Logísticas",
  "modalidad": "Presencial",
  "codigo_programa": "137136 - Versión 1",
  "proyecto_formativo": "REGISTRAR...",
  "codigo_proyecto": "PF-2026-001",
  "equipo_curricular": "Carlos Barrios",
  "regional_centro": "Regional Guajira - Centro Industrial y de Energías Alternativas",

  "filas": [
    {
      "fase": "Planear",
      "actividad_proyecto": "Identificar los principios...",
      "competencia": "220201501 - Aplicar conocimientos...",
      "raps": "1. Aplicación...\n2. Organizar...\n3. Verificar...",   # 1 línea = 1 RAP
      "saberes_conceptos": "Fuerza, masa, peso, fricción...",
      "saberes_proceso": "Identificar principios físicos...",
      "criterios_evaluacion": "Identifica los principios físicos...",
      "actividades_aprendizaje": "Guía de aprendizaje S1 RA-01: Leyes de Newton...",
      "horas_directas": 48,
      "horas_independientes": 48,
      "descripcion_evidencia": "Guía resuelta, video experimental, propuesta...",
      "estrategias_didacticas": "ABP, simulación PhET, exposición dialogada...",
      "ambiente": "Aula de sistemas con conexión a internet",
      "materiales": "Computadores, video beam, simuladores PhET",
      "instructores": "Carlos Barrios",
      "observaciones": "",
    }
  ]
}
"""
import shutil
from pathlib import Path
from copy import copy

from openpyxl import load_workbook
from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.drawing.image import Image as ImagenXLSX

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "GFPI-F-134.xlsx"
LOGO_PATH = Path(__file__).parent.parent / "templates" / "logo_sena.png"

# Mapa de columnas en la tabla (fila 18 en adelante) — coincide 1:1 con los encabezados
# oficiales de la plantilla (fila 16-17 de la hoja "FASE").
COLS_TABLA = {
    "fase":                    1,   # A — FASE DE PROYECTO FORMATIVO
    "actividad_proyecto":      2,   # B — ACTIVIDAD DE PROYECTO FORMATIVO
    "competencia":             3,   # C — COMPETENCIA
    "raps":                    4,   # D — RESULTADOS DE APRENDIZAJE (1 por fila, nunca se fusiona)
    "saberes_conceptos":       5,   # E — SABERES DE CONCEPTOS Y PRINCIPIOS
    "saberes_proceso":         6,   # F — SABERES DE PROCESO
    "criterios_evaluacion":    7,   # G — CRITERIOS DE EVALUACIÓN
    "actividades_aprendizaje": 8,   # H — ACTIVIDADES DE APRENDIZAJE A DESARROLLAR
    "horas_directas":          9,   # I — HORAS TRABAJO DIRECTO
    "horas_independientes":    10,  # J — HORAS TRABAJO INDEPENDIENTE
    "descripcion_evidencia":   11,  # K — DESCRIPCIÓN DE LA EVIDENCIA DE APRENDIZAJE
    "estrategias_didacticas":  12,  # L — ESTRATEGIAS DIDÁCTICAS ACTIVAS
    "ambiente":                13,  # M — AMBIENTE
    "materiales":              14,  # N — MATERIALES DE FORMACIÓN
    "instructores":            15,  # O — INSTRUCTORES RESPONSABLES
    "observaciones":           16,  # P — OBSERVACIONES
}
CAMPO_POR_COL = {v: k for k, v in COLS_TABLA.items()}

COL_RAPS = COLS_TABLA["raps"]
# Fase y Actividad se fusionan también ENTRE competencias consecutivas que coincidan.
COLS_FUSION_CRUZADA = (COLS_TABLA["fase"], COLS_TABLA["actividad_proyecto"])
CAMPOS_FUSION_CRUZADA = {COLS_TABLA["fase"]: "fase", COLS_TABLA["actividad_proyecto"]: "actividad_proyecto"}

FILA_INICIO_TABLA = 18
COLOR_ALT = "F0F0F0"
ALTURA_MIN_FILA = 20
PUNTOS_POR_LINEA = 15

# Anchuras de columna (unidades Excel ~ caracteres). Se reutilizan para estimar cuántas
# líneas necesitará cada celda al hacer wrap_text, y así calcular la altura de fila.
ANCHURAS = {
    1: 12, 2: 25, 3: 22, 4: 30, 5: 22, 6: 22, 7: 26, 8: 26,
    9: 10, 10: 10, 11: 24, 12: 22, 13: 18, 14: 22, 15: 20, 16: 18,
}


def _obtener_estilo_referencia(ws, fila_ref=18):
    """Copia el estilo de la fila de referencia (18) para reutilizarlo en filas nuevas."""
    estilos = {}
    for col_idx in range(1, 17):
        cell = ws.cell(row=fila_ref, column=col_idx)
        estilos[col_idx] = {
            "font": copy(cell.font),
            "alignment": copy(cell.alignment),
            "border": copy(cell.border),
            "fill": copy(cell.fill),
        }
    return estilos


def _aplicar_estilo(cell, estilo, fila_par=False, centrar_vertical=False):
    """Aplica el estilo copiado a la celda: alternado gris por bloque de competencia y
    alineación vertical centrada cuando la celda pertenece a un rango fusionado."""
    cell.font = estilo["font"]
    cell.alignment = Alignment(
        horizontal=estilo["alignment"].horizontal or "left",
        vertical="center" if centrar_vertical else "top",
        wrap_text=True,
    )
    cell.border = estilo["border"]
    if fila_par:
        cell.fill = PatternFill(start_color=COLOR_ALT, end_color=COLOR_ALT, fill_type="solid")
    else:
        cell.fill = PatternFill(fill_type=None)


def _lineas_necesarias(texto, ancho_chars) -> int:
    """Estima cuántas líneas visuales ocupará `texto` con wrap_text en una columna de
    `ancho_chars` caracteres (con margen de seguridad del 15% para no quedarnos cortos)."""
    texto = "" if texto is None else str(texto)
    if not texto:
        return 1
    ancho_efectivo = max(1, int(ancho_chars * 0.85))
    total = 0
    for linea in texto.split("\n"):
        if not linea:
            total += 1
        else:
            total += max(1, -(-len(linea) // ancho_efectivo))  # ceil division
    return total


def _rangos_consecutivos_por_valor(rangos_bloque, filas_originales, campo):
    """Para columnas de fusión cruzada (Fase, Actividad): agrupa bloques de competencia
    CONSECUTIVOS que comparten el mismo valor (normalizado) de `campo`.

    Devuelve {num_fila: (fila_ini_grupo, fila_fin_grupo)} cubriendo TODAS las filas de la
    tabla, listo para consultar directamente por número de fila."""
    bloques_ordenados = sorted(rangos_bloque.items(), key=lambda kv: kv[1][0])
    mapa = {}
    grupo_valor, grupo_ini, grupo_fin, grupo_rangos = None, None, None, []

    def _cerrar_grupo():
        for gi, gf in grupo_rangos:
            for fn in range(gi, gf + 1):
                mapa[fn] = (grupo_ini, grupo_fin)

    for b, (f_ini, f_fin) in bloques_ordenados:
        valor = str(filas_originales[b].get(campo, "")).strip().lower()
        if grupo_valor is not None and valor != "" and valor == grupo_valor:
            grupo_fin = f_fin
            grupo_rangos.append((f_ini, f_fin))
        else:
            if grupo_valor is not None:
                _cerrar_grupo()
            grupo_valor, grupo_ini, grupo_fin, grupo_rangos = valor, f_ini, f_fin, [(f_ini, f_fin)]
    if grupo_valor is not None:
        _cerrar_grupo()
    return mapa


def generar_planeacion(datos: dict, ruta_salida: str) -> str:
    """Genera el archivo de planeación pedagógica llenando la plantilla oficial.

    Reparte cada competencia (cada elemento de datos['filas']) en una fila de Excel POR
    CADA Resultado de Aprendizaje, fusionando verticalmente Competencia y las demás
    columnas que no varían por RAP. Fase y Actividad se fusionan también entre
    competencias consecutivas que comparten el mismo texto.
    """
    shutil.copy(TEMPLATE_PATH, ruta_salida)
    wb = load_workbook(ruta_salida)
    ws = wb["FASE"]

    # ===== FIX: openpyxl no soporta el dibujo VML legado que la plantilla usa para el
    # logo del encabezado de impresión (&G). Al guardar, ese vínculo queda roto y deja
    # texto basura tipo "_x000a_..." visible en la parte superior al imprimir/exportar
    # a PDF (bug preexistente, no depende de las filas/RAPs). Se limpia el texto roto y
    # se reinserta el logo SENA como imagen normal anclada en la misma zona del título,
    # así vuelve a verse tanto en pantalla como al imprimir. =====
    if ws.oddHeader and ws.oddHeader.center:
        ws.oddHeader.center.text = None
    if LOGO_PATH.exists():
        logo = ImagenXLSX(str(LOGO_PATH))
        logo.width, logo.height = 78, 74
        logo.anchor = "G1"
        ws.add_image(logo)

    # ===== CABECERA (columna E porque las celdas están fusionadas E-P) =====
    ws["E9"] = datos.get("fecha_elaboracion", "")
    ws["E10"] = datos.get("programa", "")
    ws["E11"] = datos.get("modalidad", "Presencial")
    ws["E12"] = datos.get("codigo_programa", "")
    ws["E13"] = datos.get("proyecto_formativo", "")
    ws["E14"] = datos.get("codigo_proyecto", "")
    ws["E15"] = datos.get("equipo_curricular", "")
    ws["K15"] = datos.get("regional_centro", "")

    for coord in ["E9", "E10", "E11", "E12", "E13", "E14", "E15", "K15"]:
        celda = ws[coord]
        celda.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        celda.font = Font(name="Calibri", size=10, color="2C2C2C")

    # ===== 1) EXPANDIR: 1 competencia -> N filas (una por RAP) =====
    filas_originales = datos.get("filas", [])
    filas_expandidas = []  # cada item: (bloque_idx, fila_dict_original, texto_de_ESE_rap)
    for bloque_idx, fila in enumerate(filas_originales):
        raps_lista = [r.strip() for r in str(fila.get("raps", "")).splitlines() if r.strip()]
        if not raps_lista:
            raps_lista = [""]  # nunca perder la competencia aunque no tenga RAPs cargados
        for rap_texto in raps_lista:
            filas_expandidas.append((bloque_idx, fila, rap_texto))

    if not filas_expandidas:
        wb.save(ruta_salida)
        return ruta_salida

    estilos_ref = _obtener_estilo_referencia(ws, fila_ref=18)

    # ===== 2) Rango de filas Excel que ocupa cada bloque (competencia) =====
    rangos_bloque = {}
    for i, (bloque_idx, _, _) in enumerate(filas_expandidas):
        num_fila = FILA_INICIO_TABLA + i
        if bloque_idx not in rangos_bloque:
            rangos_bloque[bloque_idx] = [num_fila, num_fila]
        else:
            rangos_bloque[bloque_idx][1] = num_fila
    rangos_bloque = {b: tuple(v) for b, v in rangos_bloque.items()}

    mapa_fusion_cruzada = {
        COLS_TABLA["fase"]: _rangos_consecutivos_por_valor(rangos_bloque, filas_originales, "fase"),
        COLS_TABLA["actividad_proyecto"]: _rangos_consecutivos_por_valor(
            rangos_bloque, filas_originales, "actividad_proyecto"),
    }

    def _rango_de(col, num_fila, bloque_idx):
        if col == COL_RAPS:
            return (num_fila, num_fila)
        if col in mapa_fusion_cruzada:
            return mapa_fusion_cruzada[col].get(num_fila, (num_fila, num_fila))
        return rangos_bloque[bloque_idx]

    # ===== 3) FUSIONAR primero (las celdas cubiertas quedan como MergedCell: hay que
    #          fusionar ANTES de escribir, y luego escribir solo en la esquina superior) =====
    rangos_ya_fusionados = set()
    for i, (bloque_idx, _, _) in enumerate(filas_expandidas):
        num_fila = FILA_INICIO_TABLA + i
        for col in COLS_TABLA.values():
            if col == COL_RAPS:
                continue
            f_ini, f_fin = _rango_de(col, num_fila, bloque_idx)
            clave = (col, f_ini, f_fin)
            if f_fin > f_ini and clave not in rangos_ya_fusionados:
                ws.merge_cells(start_row=f_ini, start_column=col, end_row=f_fin, end_column=col)
                rangos_ya_fusionados.add(clave)

    # ===== 4) ESCRIBIR valores (solo esquina superior-izquierda de cada rango) + estilos
    #          (estilos sí se aplican a TODAS las celdas del rango, cubiertas o no) =====
    for i, (bloque_idx, fila_datos, rap_texto) in enumerate(filas_expandidas):
        num_fila = FILA_INICIO_TABLA + i
        bloque_par = (bloque_idx % 2 == 1)

        for campo, col_idx in COLS_TABLA.items():
            f_ini, f_fin = _rango_de(col_idx, num_fila, bloque_idx)
            cell = ws.cell(row=num_fila, column=col_idx)

            if num_fila == f_ini:
                valor = rap_texto if campo == "raps" else fila_datos.get(campo, "")
                if campo in ("horas_directas", "horas_independientes"):
                    try:
                        cell.value = int(valor) if valor not in ("", None) else 0
                    except (ValueError, TypeError):
                        cell.value = valor
                else:
                    cell.value = str(valor) if valor is not None else ""

            _aplicar_estilo(cell, estilos_ref[col_idx], fila_par=bloque_par,
                             centrar_vertical=(f_fin > f_ini))

    # ===== 5) ALTURAS: cada fila debe tener espacio suficiente para el contenido que le
    #          corresponde (si una celda está fusionada, su contenido se reparte entre
    #          todas las filas del rango) =====
    alturas_lineas = {}
    for col_idx, ancho in ANCHURAS.items():
        campo = CAMPO_POR_COL[col_idx]
        rangos_procesados = set()
        for i, (bloque_idx, fila_datos, rap_texto) in enumerate(filas_expandidas):
            num_fila = FILA_INICIO_TABLA + i
            f_ini, f_fin = _rango_de(col_idx, num_fila, bloque_idx)
            if (f_ini, f_fin) in rangos_procesados:
                continue
            rangos_procesados.add((f_ini, f_fin))
            span = f_fin - f_ini + 1
            valor = rap_texto if campo == "raps" else fila_datos.get(campo, "")
            lineas_totales = _lineas_necesarias(valor, ancho)
            lineas_por_fila = -(-lineas_totales // span)  # ceil
            for fn in range(f_ini, f_fin + 1):
                alturas_lineas[fn] = max(alturas_lineas.get(fn, 0), lineas_por_fila)

    for i in range(len(filas_expandidas)):
        num_fila = FILA_INICIO_TABLA + i
        lineas = alturas_lineas.get(num_fila, 1)
        ws.row_dimensions[num_fila].height = max(ALTURA_MIN_FILA, lineas * PUNTOS_POR_LINEA)

    # ===== 6) Anchuras de columna =====
    for col, ancho in ANCHURAS.items():
        ws.column_dimensions[get_column_letter(col)].width = ancho

    wb.save(ruta_salida)
    return ruta_salida
