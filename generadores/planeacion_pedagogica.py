"""Planeación Pedagógica — formato oficial GFPI-F-134 (v05) del SENA.

POR QUÉ ESTE MOTOR NO USA openpyxl PARA GUARDAR
-----------------------------------------------
El formato GFPI-F-134 es auditado (fuentes, tamaños, bordes, anchos, clasificación de la
información). Al guardar con openpyxl se PIERDEN piezas oficiales de la plantilla:
  * el logo SENA del encabezado de impresión (&G, dibujo VML),
  * el cuadro de texto con la "x" que marca la clasificación "Pública",
  * las casillas de clasificación (imágenes del drawing),
  * extensiones del libro y configuración de impresora.

Por eso aquí se trabaja directamente sobre el paquete .xlsx (ZIP): se copia TODO tal cual
y solo se reescribe el XML de la hoja "FASE" (celdas de datos + celdas combinadas + altura
de filas). Cada celda nueva reutiliza el índice de estilo (s="…") EXACTO que usa la
plantilla oficial en esa columna, así que fuente, tamaño, negrita, alineación y bordes son
los del formato — no se "imitan", son los mismos.

MODELO DE DATOS (compatible hacia atrás)
----------------------------------------
datos = {
  "fecha_elaboracion": "2026-09-30",
  "programa", "modalidad", "codigo_programa", "proyecto_formativo", "codigo_proyecto",
  "equipo_curricular"  (uno o varios nombres, uno por línea),
  "regional_centro",
  "filas": [                       # 1 elemento = 1 competencia dentro de una fase/actividad
     {"fase", "actividad_proyecto", "competencia",
      # ► Modo recomendado (igual a la planeación de referencia): detalle POR RAP
      "raps_detalle": [
         {"rap", "saberes_conceptos", "saberes_proceso", "criterios_evaluacion",
          "actividades_aprendizaje", "horas_directas", "horas_independientes",
          "descripcion_evidencia", "estrategias_didacticas", "ambiente", "materiales",
          "instructores", "observaciones"}, ...],
      # ► Modo heredado: "raps" (1 por línea) + los campos anteriores a nivel competencia.
      #   En ese caso las columnas E–P se combinan verticalmente dentro de la competencia.
     }, ...]
}
Si un RAP no trae un campo, hereda el valor de la competencia.

REGLAS DE COMBINACIÓN (idénticas a la referencia)
- D (RAP): nunca se combina — 1 fila Excel por RAP.
- C (Competencia): se combina en todas las filas de sus RAP.
- A (Fase) y B (Actividad de proyecto): se combinan entre filas consecutivas con el mismo
  texto (una actividad puede agrupar varias competencias).
- E–P: por RAP (modo recomendado) o combinadas por competencia (modo heredado).
"""
from __future__ import annotations

import re
import shutil
import tempfile
import zipfile
from datetime import date, datetime
from pathlib import Path
from xml.sax.saxutils import escape

TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "GFPI-F-134.xlsx"
HOJA_FASE = "xl/worksheets/sheet2.xml"          # hoja "FASE" de la plantilla oficial

FILA_INICIO = 18                                  # primera fila de datos (bajo los títulos 16-17)
COLUMNAS = "ABCDEFGHIJKLMNOP"

# Campo → columna (encabezados oficiales filas 16-17)
CAMPOS = {
    "A": "fase", "B": "actividad_proyecto", "C": "competencia", "D": "rap",
    "E": "saberes_conceptos", "F": "saberes_proceso", "G": "criterios_evaluacion",
    "H": "actividades_aprendizaje", "I": "horas_directas", "J": "horas_independientes",
    "K": "descripcion_evidencia", "L": "estrategias_didacticas", "M": "ambiente",
    "N": "materiales", "O": "instructores", "P": "observaciones",
}
CAMPOS_POR_RAP = [CAMPOS[c] for c in "EFGHIJKLMNOP"]
NUMERICOS = {"horas_directas", "horas_independientes"}

# Índices de estilo (cellXfs) tomados de la planeación oficial diligenciada (fila 18).
#   A: Calibri 11 centrado · B: Calibri 11 centrado+ajuste · C/D: Calibri 10 NEGRITA centrado
#   E–G: Calibri 10 NEGRITA arriba-izq · H,K–O: Calibri 10 arriba · I/J: Calibri 10 arriba
#   P: Calibri 10 arriba con borde medio derecho (cierre del cuadro).
ESTILO_DATO = {"A": 135, "B": 136, "C": 129, "D": 133, "E": 127, "F": 127, "G": 127,
               "H": 134, "I": 4, "J": 4, "K": 134, "L": 134, "M": 134, "N": 134,
               "O": 134, "P": 148}
ESTILO_CUBIERTA_A = 141     # celdas cubiertas de la columna A (borde medio izquierdo)
# Fila en blanco + fila de cierre (borde medio inferior), como en la plantilla oficial.
ESTILO_BLANCO = {"A": 141, "B": 142, **{c: 143 for c in "CDEFG"},
                 **{c: 4 for c in "HIJKLMNO"}, "P": 24}
ESTILO_CIERRE = {"A": 145, "B": 146, **{c: 147 for c in "CDEFG"},
                 **{c: 25 for c in "HIJKLMNO"}, "P": 26}

# Anchos oficiales (unidades Excel) — SOLO para estimar alturas; la plantilla no se toca.
ANCHO = {"A": 18, "B": 18, "C": 18.45, "D": 35.45, "E": 35.45, "F": 35.45, "G": 35.45,
         "H": 25.36, "I": 25.36, "J": 26, "K": 26, "L": 22.45, "M": 11.45, "N": 16,
         "O": 19.45, "P": 21.18}
PT_LINEA = {"A": 14.5, "B": 14.5}                 # Calibri 11
PT_LINEA_DEF = 13.2                               # Calibri 10
ALTO_MIN, ALTO_MAX = 30.0, 409.0                  # 409 = máximo que admite Excel


# ─────────────────────────────── utilidades de texto ───────────────────────────────
def _txt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return "\n".join(str(x).strip() for x in v if str(x).strip())
    return str(v).strip()


def _lineas(texto: str, col: str) -> int:
    """Líneas visuales estimadas de `texto` con ajuste de texto en la columna `col`."""
    if not texto:
        return 1
    ancho = ANCHO[col]
    total = 0
    for linea in texto.split("\n"):
        if not linea.strip():
            total += 1
            continue
        letras = [ch for ch in linea if ch.isalpha()]
        mayus = sum(ch.isupper() for ch in letras) / max(1, len(letras))
        # Mayúsculas y negrita ocupan más: factor de caracteres por unidad de ancho
        factor = 0.92 if mayus > 0.6 else 1.12
        if col in "CDEFG":
            factor *= 0.95                       # negrita
        cpl = max(4, int(ancho * factor))
        total += -(-len(linea) // cpl)
    return total


def _celda(ref: str, estilo: int, valor=None) -> str:
    if valor is None or valor == "":
        return f'<c r="{ref}" s="{estilo}"/>'
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        return f'<c r="{ref}" s="{estilo}"><v>{valor}</v></c>'
    t = escape(str(valor)).replace("\r", "")
    return f'<c r="{ref}" s="{estilo}" t="inlineStr"><is><t xml:space="preserve">{t}</t></is></c>'


def _num(v):
    try:
        return int(float(str(v).strip()))
    except (ValueError, TypeError):
        return _txt(v)


def _serial_excel(fecha) -> int | str:
    """Fecha → número de serie Excel (la celda E9 oficial tiene formato de fecha)."""
    if isinstance(fecha, (date, datetime)):
        d = fecha if isinstance(fecha, date) else fecha.date()
    else:
        s = _txt(fecha)
        d = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
            try:
                d = datetime.strptime(s, fmt).date()
                break
            except ValueError:
                pass
        if d is None:
            return s
    return (d - date(1899, 12, 30)).days


# ─────────────────────────────── expansión por RAP ───────────────────────────────
CAMPOS_RAP = [CAMPOS[c] for c in "EFG"]              # saberes y criterios: propios del RAP
CAMPOS_AA = [CAMPOS[c] for c in "HIJKLMNOP"]         # propios de cada actividad de aprendizaje


def expandir_filas(filas: list[dict]) -> list[dict]:
    """1 competencia → N RAP → M actividades de aprendizaje (AA). Cada AA es UNA fila de Excel.

    Modo por RAP (recomendado): `raps_detalle[j]` puede traer `actividades` (lista de AA);
    si no la trae, el propio RAP cuenta como una AA (1 AA por RAP, compatible con lo anterior).
    Herencia de valores vacíos: AA → RAP → competencia.
    Modo heredado: `raps` (1 por línea) y todo lo demás a nivel competencia."""
    salida = []
    for b, comp in enumerate(filas or []):
        detalle = comp.get("raps_detalle") or []
        if detalle:
            modo = "por_rap"
            raps = [d if isinstance(d, dict) else {"rap": d} for d in detalle]
        else:
            modo = "heredado"
            lista = [r.strip() for r in _txt(comp.get("raps")).splitlines() if r.strip()]
            raps = [{"rap": r} for r in (lista or [""])]
        for j, rap in enumerate(raps):
            aas = [a for a in (rap.get("actividades") or []) if isinstance(a, dict)] if modo == "por_rap" else []
            for k, aa in enumerate(aas or [{}]):
                reg = {"_bloque": b, "_rap": (b, j), "_aa": k, "_modo": modo,
                       "fase": _txt(comp.get("fase")),
                       "actividad_proyecto": _txt(comp.get("actividad_proyecto")),
                       "competencia": _txt(comp.get("competencia")),
                       "rap": _txt(rap.get("rap") or rap.get("texto") or rap.get("nombre"))}
                for campo in CAMPOS_POR_RAP:
                    if modo == "heredado":
                        v = comp.get(campo)
                    else:
                        fuentes = ([aa] if campo in CAMPOS_AA else []) + [rap, comp]
                        v = next((f.get(campo) for f in fuentes if f.get(campo) not in (None, "")), "")
                    reg[campo] = _num(v) if campo in NUMERICOS and v not in (None, "") else _txt(v)
                salida.append(reg)
    return salida


def _rangos(registros: list[dict]) -> dict[str, list[tuple[int, int]]]:
    """Rangos (índice inicio, índice fin) a combinar por columna.
    A/B: texto igual consecutivo · C: competencia · D–G: RAP (sobre todas sus AA) ·
    H–P: cada AA (modo por RAP) o toda la competencia (modo heredado)."""
    n = len(registros)
    rangos: dict[str, list[tuple[int, int]]] = {c: [] for c in COLUMNAS}

    def agrupar(clave):
        grupos, ini = [], 0
        for i in range(1, n + 1):
            if i == n or clave(i) != clave(ini) or clave(i) is None:
                grupos.append((ini, i - 1))
                ini = i
        return grupos

    for col, campo in (("A", "fase"), ("B", "actividad_proyecto")):
        def k(i, campo=campo):
            v = registros[i][campo].strip().upper()
            return v if v else ("__vacio__", i)
        rangos[col] = agrupar(k)
    rangos["C"] = agrupar(lambda i: registros[i]["_bloque"])
    rangos["D"] = agrupar(lambda i: registros[i]["_rap"])
    for col in "EFG":
        rangos[col] = agrupar(lambda i: ("h", registros[i]["_bloque"])
                              if registros[i]["_modo"] == "heredado" else registros[i]["_rap"])
    for col in "HIJKLMNOP":
        rangos[col] = agrupar(lambda i: ("h", registros[i]["_bloque"])
                              if registros[i]["_modo"] == "heredado" else ("aa", i))
    return rangos


# ─────────────────────────────── núcleo XML ───────────────────────────────
ADVERTENCIAS: list[str] = []       # se llena en cada generación; la UI la muestra


def _ajustar_textos_largos(registros: list[dict], rangos: dict) -> list[str]:
    """Excel no permite filas de más de 409 pt: el texto que no cabe se CORTA al imprimir.
    1º compacta líneas en blanco dobles (el contenido queda íntegro); 2º si aún no cabe,
    registra una advertencia legible para el instructor."""
    avisos = []
    for c in "DEFGHIJKLMNOP":
        pt = PT_LINEA.get(c, PT_LINEA_DEF)
        campo = CAMPOS[c]
        for a, b in rangos[c]:
            cap = ALTO_MAX * (b - a + 1)
            texto = _txt(registros[a][campo])
            if _lineas(texto, c) * pt + 8 <= cap:
                continue
            compacto = re.sub(r"[ \t]+\n", "\n", texto)
            compacto = re.sub(r"\n\s*\n+", "\n", compacto)
            registros[a][campo] = compacto
            if _lineas(compacto, c) * pt + 8 > cap:
                nombre = {"D": "Resultado de aprendizaje", "E": "Saberes de conceptos",
                          "F": "Saberes de proceso", "G": "Criterios de evaluación",
                          "H": "Actividades de aprendizaje", "K": "Evidencia",
                          "L": "Estrategias didácticas"}.get(c, campo)
                rap = _txt(registros[a]["rap"])[:60]
                avisos.append(f"«{nombre}» del RAP «{rap}…» supera el alto máximo de una fila "
                              f"de Excel (409 pt): parte del texto no se verá al imprimir. "
                              f"Resúmalo o divídalo.")
    ADVERTENCIAS.extend(avisos)
    return avisos


def validar_planeacion(datos: dict) -> list[str]:
    """Revisión previa (sin generar archivo): campos obligatorios + textos que no caben."""
    avisos = []
    obligatorios = {"programa": "Denominación del programa", "codigo_programa": "Código y versión",
                    "proyecto_formativo": "Nombre del proyecto", "codigo_proyecto": "Código del proyecto",
                    "equipo_curricular": "Equipo de gestión curricular",
                    "regional_centro": "Regional y centro"}
    for k, nom in obligatorios.items():
        if not _txt(datos.get(k)):
            avisos.append(f"Falta «{nom}» en el encabezado.")
    regs = expandir_filas(datos.get("filas", []))
    for r in regs:
        for campo, nom in (("rap", "RAP"), ("actividades_aprendizaje", "actividad de aprendizaje"),
                           ("descripcion_evidencia", "evidencia"),
                           ("criterios_evaluacion", "criterios de evaluación")):
            if not _txt(r[campo]):
                avisos.append(f"{r['competencia'][:40]}… → falta {nom}"
                              + (f" en RAP «{r['rap'][:40]}…»" if campo != "rap" else "") + ".")
    if regs:
        copia = [dict(r) for r in regs]
        avisos += _ajustar_textos_largos(copia, _rangos(copia))
        ADVERTENCIAS.clear()
    return avisos

def _construir_hoja(xml: str, datos: dict, registros: list[dict]) -> str:
    # 1) Encabezado (valores del bloque de identificación, filas 9-15)
    cab = {
        "E9": _serial_excel(datos.get("fecha_elaboracion") or date.today()),
        "E10": _txt(datos.get("programa")),
        "E11": _txt(datos.get("modalidad") or "PRESENCIAL"),
        "E12": _txt(datos.get("codigo_programa")),
        "E13": _txt(datos.get("proyecto_formativo")),
        "E14": _txt(datos.get("codigo_proyecto")),
        "E15": "Nombres y Apellidos\n" + _txt(datos.get("equipo_curricular")),
        "K15": "Regional y Centro de formación\n" + _txt(datos.get("regional_centro")),
    }

    def reemplazar_celda(m):
        ref, attrs = m.group(1), m.group(2)
        if ref not in cab:
            return m.group(0)
        s = re.search(r's="(\d+)"', attrs)
        return _celda(ref, int(s.group(1)) if s else 0, cab[ref])

    patron_celda = r'<c r="([A-Z]+\d+)"([^>]*?)(?:/>|>.*?</c>)'
    cabecera, resto = xml.split("<sheetData>", 1)
    datos_hoja, cola = resto.split("</sheetData>", 1)
    filas_xml = re.findall(r"<row [^>]*?(?:/>|>.*?</row>)", datos_hoja, re.S)

    conservadas = []
    for fx in filas_xml:
        r = int(re.search(r' r="(\d+)"', fx).group(1))
        if r >= FILA_INICIO:
            continue                              # la tabla se reconstruye completa
        if 9 <= r <= 15:
            fx = re.sub(patron_celda, reemplazar_celda, fx, flags=re.S)
        conservadas.append(fx)

    # 2) Tabla de datos
    n = len(registros)
    rangos = _rangos(registros) if n else {c: [] for c in COLUMNAS}
    inicio_de = {c: {a: b for a, b in rangos[c]} for c in COLUMNAS}   # ini → fin
    cubierta = {c: {i for a, b in rangos[c] for i in range(a + 1, b + 1)} for c in COLUMNAS}
    _ajustar_textos_largos(registros, rangos)

    # Altura: cada fila debe alojar su parte de todos los textos que la cubren
    alto = [ALTO_MIN] * n
    for c in COLUMNAS:
        pt = PT_LINEA.get(c, PT_LINEA_DEF)
        campo = CAMPOS[c]
        for a, b in rangos[c]:
            span = b - a + 1
            req = (_lineas(_txt(registros[a][campo]), c) * pt + 8) / span
            for i in range(a, b + 1):
                alto[i] = max(alto[i], req)
    # Si una celda combinada necesita más de lo que suman sus filas, repartir el faltante
    for c in COLUMNAS:
        pt = PT_LINEA.get(c, PT_LINEA_DEF)
        for a, b in rangos[c]:
            req = _lineas(_txt(registros[a][CAMPOS[c]]), c) * pt + 8
            falta = req - sum(alto[a:b + 1])
            if falta > 0:
                for i in range(a, b + 1):
                    alto[i] += falta / (b - a + 1)
    alto = [min(ALTO_MAX, round(h, 2)) for h in alto]

    nuevas, merges = [], []
    for i, reg in enumerate(registros):
        fila = FILA_INICIO + i
        celdas = []
        for c in COLUMNAS:
            ref = f"{c}{fila}"
            if i in cubierta[c]:
                est = ESTILO_CUBIERTA_A if c == "A" else ESTILO_DATO[c]
                celdas.append(_celda(ref, est))
                continue
            valor = reg[CAMPOS[c]]
            celdas.append(_celda(ref, ESTILO_DATO[c], valor))
            fin = inicio_de[c].get(i, i)
            if fin > i:
                merges.append(f"{c}{fila}:{c}{FILA_INICIO + fin}")
        nuevas.append(f'<row r="{fila}" spans="1:16" ht="{alto[i]}" customHeight="1" '
                      f'x14ac:dyDescent="0.35">{"".join(celdas)}</row>')

    # Fila en blanco (espacio de diligenciamiento) + fila de cierre del cuadro
    f_blanco = FILA_INICIO + n
    f_cierre = f_blanco + 1
    nuevas.append(f'<row r="{f_blanco}" spans="1:16" ht="20.15" customHeight="1" x14ac:dyDescent="0.35">'
                  + "".join(_celda(f"{c}{f_blanco}", ESTILO_BLANCO[c]) for c in COLUMNAS) + "</row>")
    nuevas.append(f'<row r="{f_cierre}" spans="1:16" x14ac:dyDescent="0.35">'
                  + "".join(_celda(f"{c}{f_cierre}", ESTILO_CIERRE[c]) for c in COLUMNAS) + "</row>")

    hoja_datos = "<sheetData>" + "".join(conservadas + nuevas) + "</sheetData>"

    # 3) Celdas combinadas: se conservan las del encabezado (< fila 18) y se agregan las nuevas
    m = re.search(r"<mergeCells[^>]*>(.*?)</mergeCells>", cola, re.S)
    previas = re.findall(r'<mergeCell ref="([^"]+)"/>', m.group(1)) if m else []
    previas = [r for r in previas if int(re.search(r"(\d+)", r).group(1)) < FILA_INICIO]
    todas = previas + merges
    bloque_merge = f'<mergeCells count="{len(todas)}">' + "".join(
        f'<mergeCell ref="{r}"/>' for r in todas) + "</mergeCells>"
    cola = cola[:m.start()] + bloque_merge + cola[m.end():] if m else bloque_merge + cola

    # 4) Dimensión y vista (abrir arriba-izquierda, no donde quedó el último que editó)
    cabecera = re.sub(r'<dimension ref="[^"]+"/>', f'<dimension ref="A1:Y{f_cierre}"/>', cabecera)
    cabecera = re.sub(r'topLeftCell="[A-Z]+\d+"', 'topLeftCell="A1"', cabecera)
    cabecera = re.sub(r'<selection [^>]*/>', '<selection activeCell="A18" sqref="A18"/>', cabecera)
    return cabecera + hoja_datos + cola


def _compactar_shared_strings(archivos: dict[str, bytes]) -> None:
    """Elimina de sharedStrings.xml los textos que ya no usa ninguna hoja (evita que un
    archivo generado arrastre, oculto, el contenido de otra planeación) y renumera."""
    sst = archivos.get("xl/sharedStrings.xml")
    if not sst:
        return
    sst_txt = sst.decode("utf-8")
    items = re.findall(r"<si>.*?</si>|<si/>", sst_txt, re.S)
    hojas = [k for k in archivos if re.match(r"xl/worksheets/sheet\d+\.xml$", k)]
    usados = set()
    pat = re.compile(r'(<c [^>]*t="s"[^>]*><v>)(\d+)(</v>)')
    for h in hojas:
        usados |= {int(x.group(2)) for x in pat.finditer(archivos[h].decode("utf-8"))}
    orden = sorted(usados)
    nuevo = {viejo: i for i, viejo in enumerate(orden)}
    for h in hojas:
        t = archivos[h].decode("utf-8")
        t = pat.sub(lambda x: f"{x.group(1)}{nuevo[int(x.group(2))]}{x.group(3)}", t)
        archivos[h] = t.encode("utf-8")
    cab = sst_txt[:sst_txt.find("<si")] if "<si" in sst_txt else sst_txt.split("</sst>")[0]
    cab = re.sub(r'count="\d+"', f'count="{len(orden)}"', cab)
    cab = re.sub(r'uniqueCount="\d+"', f'uniqueCount="{len(orden)}"', cab)
    archivos["xl/sharedStrings.xml"] = (cab + "".join(items[i] for i in orden) + "</sst>").encode("utf-8")


def _quitar_calc_chain(archivos: dict[str, bytes]) -> None:
    """calcChain apunta a la fórmula =TODAY() de E9 que ahora es una fecha fija; Excel lo
    reconstruye solo. Dejarlo provocaría el aviso de 'reparar archivo'."""
    archivos.pop("xl/calcChain.xml", None)
    ct = archivos["[Content_Types].xml"].decode("utf-8")
    archivos["[Content_Types].xml"] = re.sub(r'<Override[^>]*calcChain[^>]*/>', "", ct).encode("utf-8")
    rels = archivos["xl/_rels/workbook.xml.rels"].decode("utf-8")
    archivos["xl/_rels/workbook.xml.rels"] = re.sub(
        r'<Relationship[^>]*calcChain[^>]*/>', "", rels).encode("utf-8")


def _estilo_fase_con_borde(archivos: dict[str, bytes]) -> None:
    """La celda superior de Fase (xf 135) no trae el borde medio izquierdo que sí tienen las
    demás filas del cuadro (xf 141). Se agrega al final de cellXfs un gemelo de 135 con el
    borde de 141 — mismo tipo de letra/alineación, solo completa el marco del formato."""
    global ESTILO_DATO
    st = archivos["xl/styles.xml"].decode("utf-8")
    m = re.search(r'<cellXfs count="(\d+)">(.*?)</cellXfs>', st, re.S)
    if not m:
        return
    xfs = re.findall(r"<xf [^>]*?(?:/>|>.*?</xf>)", m.group(2), re.S)
    if len(xfs) <= 141:
        return
    borde = re.search(r'borderId="(\d+)"', xfs[141]).group(1)
    gemelo = re.sub(r'borderId="\d+"', f'borderId="{borde}"', xfs[135])
    nuevo_idx = len(xfs)
    bloque = f'<cellXfs count="{nuevo_idx + 1}">{m.group(2)}{gemelo}</cellXfs>'
    archivos["xl/styles.xml"] = (st[:m.start()] + bloque + st[m.end():]).encode("utf-8")
    ESTILO_DATO = {**ESTILO_DATO, "A": nuevo_idx}


def generar_planeacion(datos: dict, ruta_salida: str, plantilla: str | Path | None = None) -> str:
    """Genera el GFPI-F-134 diligenciado en `ruta_salida` a partir de la plantilla oficial."""
    global ESTILO_DATO
    plantilla = Path(plantilla or TEMPLATE_PATH)
    with zipfile.ZipFile(plantilla) as z:
        infos = z.infolist()
        archivos = {i.filename: z.read(i.filename) for i in infos}
    ESTILO_DATO = {**ESTILO_DATO, "A": 135}
    ADVERTENCIAS.clear()
    _estilo_fase_con_borde(archivos)

    registros = expandir_filas(datos.get("filas", []))
    xml = archivos[HOJA_FASE].decode("utf-8")
    archivos[HOJA_FASE] = _construir_hoja(xml, datos, registros).encode("utf-8")
    _compactar_shared_strings(archivos)
    _quitar_calc_chain(archivos)

    tmp = Path(tempfile.mkstemp(suffix=".xlsx")[1])
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        for info in infos:                        # mismo orden de partes que el original
            if info.filename in archivos:
                out.writestr(info.filename, archivos[info.filename])
    shutil.move(str(tmp), ruta_salida)
    return ruta_salida


def resumen_horas(datos: dict) -> dict:
    """Totales para validar contra la duración oficial de cada competencia."""
    tot, vistos = {}, set()
    for reg in expandir_filas(datos.get("filas", [])):
        k = reg["competencia"][:60]
        d = reg["horas_directas"] if isinstance(reg["horas_directas"], int) else 0
        ind = reg["horas_independientes"] if isinstance(reg["horas_independientes"], int) else 0
        if reg["_modo"] == "heredado":          # horas a nivel competencia: contar 1 vez por bloque
            if reg["_bloque"] in vistos:
                continue
            vistos.add(reg["_bloque"])
        t = tot.setdefault(k, {"directas": 0, "independientes": 0})
        t["directas"] += d
        t["independientes"] += ind
    return tot
