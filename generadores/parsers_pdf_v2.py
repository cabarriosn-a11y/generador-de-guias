"""Parsers v2 (coordenadas y líneas de tabla) para los PDF oficiales de SOFIA Plus.

- parsear_tabla_proyecto(): sección 3 del Reporte de Proyecto Formativo (GFPI-F-016). Usa
  las líneas de la tabla para separar celdas (el texto plano mezcla columnas) y une filas
  partidas entre páginas.
- parsear_diseno(): Informe de Programa de Formación Titulada. Une renglones partidos con
  reglas de verbo (RAP/criterios/procesos) y de ancho real (saberes), y quita encabezados
  y pies de página repetidos.
Ambas reciben una ruta o un objeto tipo archivo (BytesIO).
Validado 2026-10-01 con Integración de Operaciones Logísticas 137136 v1 y el proyecto
2343435: 74/74 RAP del proyecto coinciden con el diseño; 1344 h lectivas.
"""
import re, collections, unicodedata
import pdfplumber
"""(Proyecto) Parser v2 del Reporte de Proyecto Formativo (GFPI-F-016): usa las LÍNEAS de la tabla
(no el texto plano) para separar celdas, y une filas partidas entre páginas."""

RE_COD = re.compile(r"^(\d{5,9})\s*-\s*(.+)$", re.S)
def limpia(t): return re.sub(r"\s+", " ", (t or "")).strip()
def parsear_tabla_proyecto(ruta):
    """Una fila de la tabla 3 = un RAP. Reglas:
    - Fila con código de RAP ("514293 - ...") → RAP nuevo.
    - Primera fila de una página SIN código → es la cola de la fila anterior (se partió
      entre páginas): su texto se pega a la fila previa.
    - Fila sin código a mitad de página con texto de RAP → RAP nuevo sin código (no se pierde).
    - Fase, actividad o competencia vacías (celdas combinadas en otros reportes) se
      rellenan con el valor de la fila anterior."""
    filas, en_tabla = [], False
    with pdfplumber.open(ruta) as pdf:
        for pg in pdf.pages:
            # la tabla 3 termina en "3.5 Organización", "4. Rubros" o "5. Equipo": recortar ahí
            corte = None
            for m in pg.search(r"3\.5\s+Organizaci|[45]\.\s*Rubros|[45]\.\s*Equipo que", regex=True):
                corte = m["top"] if corte is None else min(corte, m["top"])
            zona = pg.crop((0, 0, pg.width, corte)) if corte else pg
            primera_de_pagina = True
            for t in zona.extract_tables():
                if not t or len(t[0]) != 4: continue
                for r in t:
                    c = [limpia(x) for x in r]
                    if c[0].startswith("3.1.") or c[0].startswith("3. Planeación"):
                        en_tabla = True; continue
                    if re.match(r"^[45]\.\s", c[0]): en_tabla = False
                    if not en_tabla or not any(c): continue
                    tiene_codigo = bool(RE_COD.match(c[2]))
                    es_cola = filas and not tiene_codigo and (primera_de_pagina or not c[2])
                    primera_de_pagina = False
                    if es_cola:
                        prev = filas[-1]
                        for k in range(4):
                            if c[k] and not prev[k].endswith(c[k]): prev[k] = (prev[k] + " " + c[k]).strip()
                        continue
                    if filas:
                        for k in (0, 1, 3):
                            if not c[k]: c[k] = filas[-1][k]
                    filas.append(c)
    out = []
    for f, act, rap, comp in filas:
        mr, mc = RE_COD.match(rap), RE_COD.match(comp)
        out.append({"fase": f, "actividad": act,
                    "rap_codigo": mr.group(1) if mr else "", "rap": limpia(mr.group(2)) if mr else rap,
                    "comp_codigo": mc.group(1) if mc else "", "competencia": limpia(mc.group(2)) if mc else comp})
    return out


"""Parser v2 del Informe de Programa de Formación Titulada (diseño curricular SENA).
Trabaja con las COORDENADAS de cada renglón para saber si un ítem continúa en el renglón
siguiente (corte por ancho de columna) y elimina encabezados/pies de página repetidos."""


MARGEN_DER = 582          # borde derecho útil de la columna de texto (pt)
CHAR_PT = 6.2             # ancho medio de un carácter en mayúscula Arial 8 (pt)
RE_INF = re.compile(r"^[A-ZÁÉÍÓÚÑ]{3,}(AR|ER|IR)(SE|LO|LA|LOS|LAS)?[.,:]?$")

def sin_tildes(t):
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")

def renglones(ruta):
    """Todas las líneas del PDF con x0/x1, sin encabezados ni pies repetidos."""
    lineas, cuenta = [], collections.Counter()
    with pdfplumber.open(ruta) as pdf:
        for n, pg in enumerate(pdf.pages):
            for l in pg.extract_text_lines():
                t = l["text"].strip()
                ch = l.get("chars", [])
                # ancho REAL de la primera palabra (para saber si cabía en el renglón anterior)
                ch = [c for c in ch if c["text"].strip()]          # pdfplumber puede omitir espacios
                k = min(len(t.split()[0]) if t else 0, len(ch))
                w1 = (ch[k - 1]["x1"] - ch[0]["x0"]) if k else 0
                lineas.append({"p": n, "t": t, "x0": l["x0"], "x1": l["x1"], "w1": w1})
                cuenta[t] += 1
    npag = n + 1
    repetidas = {t for t, c in cuenta.items() if c >= npag * 0.6}
    return [l for l in lineas if l["t"] not in repetidas
            and not re.search(r"\d{2}/\d{2}/\d{2}\s+\d{1,2}:\d{2}\s+Página \d+ de \d+", l["t"])]

NO_VERBO = {"EMPRESA", "NORMATIVA", "CARGA", "POLÍTICA", "POLITICA", "MERCANCÍA", "NORMA", "NORMAS",
            "CLIENTE", "CLIENTES", "ENTREGA", "ENERGÍA", "MATERIA", "PRODUCTIVA", "TÉCNICA", "TECNICA",
            "EMPRESAS", "ORGANIZACIÓN", "DE", "LA", "LAS", "LOS", "EL", "Y", "EN", "CON", "QUE", "PARA",
            "SEGÚN", "DEL", "AL", "A", "O", "SU", "SUS", "SE", "ESTE", "ESTA", "VIGENTE", "INTERNA",
            "EXTERNA", "LOGÍSTICA", "LOGISTICA", "ZONA", "ZONAS", "TAREA", "TAREAS", "VIDA", "FORMA",
            "PERSONA", "INDUSTRIA", "PLANTA", "RUTA", "RUTAS", "DEMANDA", "OFERTA", "CULTURA", "LENGUA"}
RE_3P = re.compile(r"^[A-ZÁÉÍÓÚÑ]{3,}(A|E|AN|EN)$")

def _es_verbo(palabra, tipo, vocab):
    w = sin_tildes(palabra.upper().strip(".,:;\"'"))
    if tipo in ("rap", "proceso") and RE_INF.match(w):
        return True
    if palabra.upper() in vocab:
        return True
    if tipo in ("criterio", "proceso") and RE_3P.match(w) and w not in {sin_tildes(x) for x in NO_VERBO}:
        return True
    return False

def unir_items(lineas, vocab, tipo):
    """Une renglones partidos.
    - Si el renglón anterior terminó claramente antes del borde (x1 < 470 pt) → ítem nuevo.
    - RAP, saberes de proceso y criterios: en zona ambigua, es ítem nuevo SOLO si arranca con
      verbo (infinitivo para RAP/proceso; 3.ª persona para criterios). El ancho no basta porque
      SOFIA corta por número de caracteres, no por geometría.
    - Saberes del saber (sin verbo): continúa si la primera palabra no cabía en el renglón previo."""
    items = []
    for l in lineas:
        t = l["t"]
        if not t:
            continue
        primera = t.split()[0]
        if items:
            prev = items[-1]
            termino = prev["x1"] < 470
            if tipo == "saber":
                nuevo = (termino or prev["x1"] + 2.5 + l.get("w1", 40) <= MARGEN_DER
                         or prev["t"].endswith(".")
                         or bool(re.match(r"^[A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ ,/()-]{2,45}:", t)))   # "CONCEPTO: ..."
                # una línea que arranca con artículo/conector y viene de un renglón lleno es cola
                if nuevo and not termino and not prev["t"].endswith(".") and \
                        primera.upper().strip("(") in {"DE", "DEL", "LA", "LAS", "LOS", "EL", "Y", "E", "O",
                                                       "EN", "CON", "PARA", "POR", "SEGÚN", "A", "AL", "SU", "SUS"}:
                    nuevo = False
            else:
                # un ítem con verbo siempre tiene al menos 2 palabras ("GEOMÉTRICA" sola es cola)
                nuevo = (len(t.split()) >= 2 and _es_verbo(primera, tipo, vocab)) or \
                        (termino and prev["t"].rstrip().endswith((".", ")")))
            if not nuevo:
                prev["t"] += " " + t
                prev["x1"] = l["x1"]
                continue
        items.append({"t": t, "x1": l["x1"]})
    out = []
    for i in items:
        t = re.sub(r"\s+", " ", i["t"]).strip()
        # ítems pegados sin salto en el PDF: "...PRODUCTIVO.INTERPRETA CAMBIOS..."
        partes = re.split(r"(?<=[A-ZÁÉÍÓÚÑ]\.)(?=[A-ZÁÉÍÓÚÑ]{4,}\s)", t)
        if len(partes) > 1 and all(_es_verbo(x.split()[0], tipo, vocab) for x in partes[1:]):
            out += [x.strip() for x in partes]
        else:
            out.append(t)
    return out

MARCAS = [("4.1 ", "norma"), ("4.2 ", "codigo"), ("4.3 ", "nombre"), ("4.4 ", "duracion"),
          ("4.5 ", "raps"), ("4.6.1", "proceso"), ("4.6.2", "saber"), ("4.6 ", None),
          ("4.7 ", "criterios"), ("4.8 ", "fin")]

MARCAS_2012 = [("1. CONTENIDOS CURRICULARES", "inicio"), ("2. RESULTADOS DE APRENDIZAJE", "raps"),
               ("3.1. CONOCIMIENTOS DE CONCEPTOS", "saber"), ("3.1 CONOCIMIENTOS DE CONCEPTOS", "saber"),
               ("3.2. CONOCIMIENTOS DE PROCESO", "proceso"), ("3.2 CONOCIMIENTOS DE PROCESO", "proceso"),
               ("3. CONOCIMIENTOS", None), ("4. CRITERIOS DE EVALUACI", "criterios"),
               ("5. PERFIL", "fin")]


def _bloques_2012(L, txt):
    """Formato ANTIGUO (JasperReports, ~2012): "1. CONTENIDOS CURRICULARES / 2. RESULTADOS /
    3.1 CONCEPTOS / 3.2 PROCESO / 4. CRITERIOS". El código de cada competencia sale cortado
    en el PDF (8 dígitos, la celda es angosta), así que se completa con la lista
    "COMPETENCIAS A DESARROLLAR" del inicio del documento, en el mismo orden."""
    m = re.search(r"COMPETENCIAS A DESARROLLAR(.*?)1\. CONTENIDOS CURRICULARES", txt, re.S)
    lista = re.findall(r"^\s*(\d{9})\b", m.group(1), re.M) if m else []
    info = {
        "denominacion": (re.search(r"DENOMINACIÓN DEL PROGRAMA\s*\n\s*\d{5,7}\s+(.+)", txt) or [None, ""])[1].strip(),
        "codigo": (re.search(r"CÓDIGO:.*?\n\s*(\d{5,7})\b", txt, re.S) or [None, ""])[1],
        "version": (re.search(r"VERSIÓN:\s*(\d+)", txt) or [None, ""])[1],
        "formato": "2012",
    }
    bloques, actual = [], None
    for l in L:
        if l["t"].startswith("1. CONTENIDOS CURRICULARES"):
            actual = []; bloques.append(actual)
        if actual is not None:
            actual.append(l)
    comps = []
    for i, b in enumerate(bloques):
        secc, cur = collections.defaultdict(list), "inicio"
        for l in b:
            t = l["t"]
            mm = next((k for pre, k in MARCAS_2012 if t.startswith(pre)), "__no__")
            if mm != "__no__":
                cur = mm
                continue
            if cur == "fin":
                break
            if cur:
                secc[cur].append(l)
        cab = secc.get("inicio", [])
        cod_trunco = (re.search(r"^(\d{6,9})", next((x["t"] for x in cab if re.match(r"^\d{6,9}\b", x["t"])), "")) or [None, ""])[1]
        codigo = cod_trunco
        if i < len(lista) and lista[i].startswith(cod_trunco):
            codigo = lista[i]
        else:
            cands = [c for c in lista if c.startswith(cod_trunco)]
            codigo = cands[0] if len(cands) == 1 else cod_trunco
        # nombre: renglones de la columna DENOMINACIÓN (x0 > 170) antes de "DURACIÓN"
        nombre = []
        for x in cab:
            if x["t"].startswith("DURACIÓN"):
                break
            mc = re.match(r"^\d{6,9}\s+\d+\s+(.+)$", x["t"])     # código + versión + nombre en un renglón
            if mc:
                nombre.append(mc.group(1))
            elif x["x0"] > 170 and x["t"] not in ("DENOMINACIÓN",) and not x["t"].startswith("CÓDIGO"):
                nombre.append(x["t"])
        dur = re.search(r"(\d+)\s*horas", " ".join(x["t"] for x in cab))
        nombre = re.sub(r"\s+", " ", " ".join(nombre)).strip()
        comps.append({"codigo": codigo, "nombre": nombre, "norma": nombre,
                      "duracion_horas": int(dur.group(1)) if dur else None,
                      "_secc": {k: [x for x in v if x["t"] not in ("DENOMINACIÓN",)]
                                for k, v in secc.items() if k != "inicio"}})
    return info, comps


def parsear_diseno(ruta):
    L = renglones(ruta)
    txt = "\n".join(l["t"] for l in L)
    if not any(l["t"].startswith("4.1 NORMA") for l in L) and \
            any(l["t"].startswith("1. CONTENIDOS CURRICULARES") for l in L):
        info, comps = _bloques_2012(L, txt)
        return _finalizar(info, comps)
    info = {
        "denominacion": (re.search(r"1\.1 Denominación\s*(?:del Programa:)?\s*\n?(.*)", txt) or [None, ""])[1].strip(),
        "codigo": (re.search(r"1\.2\.?\s*Código\s+(\d+)", txt) or [None, ""])[1],
        "version": (re.search(r"1\.3\.?\s*Versión\s*\n?\s*(\d+)", txt) or [None, ""])[1],
    }
    # Bloques por competencia (desde "4.1 NORMA" hasta el siguiente)
    bloques, actual = [], None
    for l in L:
        if l["t"].startswith("4.1 NORMA"):
            actual = []; bloques.append(actual)
        if actual is not None:
            actual.append(l)
    comps = []
    for b in bloques:
        secc, cur = collections.defaultdict(list), None
        for l in b:
            t = l["t"]
            m = next((k for pre, k in MARCAS if t.startswith(pre)), "__no__")
            if m != "__no__":
                cur = m
                resto = re.sub(r"^4\.\d(\.\d)?\s*", "", t)
                if cur in ("norma", "nombre"):
                    resto = re.sub(r"^(NORMA / UNIDAD DE|NOMBRE DE LA)\s*", "", resto).strip()
                    if resto: secc[cur].append({**l, "t": resto})
                elif cur in ("codigo", "duracion"):
                    secc[cur].append({**l, "t": resto})
                continue
            if cur == "fin":
                break
            if cur:
                secc[cur].append(l)
        cod = re.search(r"(\d{6,9})", " ".join(x["t"] for x in secc["codigo"]))
        etiqueta = lambda t: re.sub(r"^(COMPETENCIA LABORAL|COMPETENCIA|NOMBRE DE LA)\b\s*", "", t).strip()
        # el nombre va centrado verticalmente: su primer renglón puede quedar ANTES de "4.3"
        previos = [etiqueta(x["t"]) for x in secc["codigo"][1:] if not re.search(r"\d{6}", x["t"])]
        nombre = re.sub(r"\s+", " ", " ".join([t for t in previos if t] +
                                              [etiqueta(x["t"]) for x in secc["nombre"]])).strip()
        norma = re.sub(r"\s+", " ", " ".join(etiqueta(x["t"]) for x in secc["norma"])).strip()
        dur = re.search(r"(\d+)\s*horas", " ".join(x["t"] for x in secc["duracion"] + secc["nombre"]))
        comps.append({"codigo": cod.group(1) if cod else "", "nombre": nombre or norma, "norma": norma,
                      "duracion_horas": int(dur.group(1)) if dur else None,
                      "_secc": {k: [x for x in v if x["t"] not in ("DENOMINACIÓN",)] for k, v in secc.items()}})
    info["formato"] = "2020"
    return _finalizar(info, comps)


def _finalizar(info, comps):
    # Vocabulario de verbos de inicio aprendido del propio documento (renglones que
    # inequívocamente empiezan ítem: el renglón anterior terminó lejos del borde)
    vocab = collections.Counter()
    for c in comps:
        for k in ("raps", "criterios", "proceso"):
            ls = c["_secc"].get(k, [])
            for a, b in zip([None] + ls[:-1], ls):
                if a is None or a["x1"] + 60 < MARGEN_DER - 40:
                    vocab[b["t"].split()[0].upper()] += 1
    vocab = {w for w, n in vocab.items() if n >= 2 and len(w) > 3}
    for c in comps:
        s = c.pop("_secc")
        c["raps"] = unir_items(s.get("raps", []), vocab, "rap")
        c["conocimientos_proceso"] = unir_items(s.get("proceso", []), vocab, "proceso")
        c["conocimientos_saber"] = unir_items(s.get("saber", []), set(), "saber")
        c["criterios_evaluacion"] = unir_items(s.get("criterios", []), vocab, "criterio")
    return {**info, "competencias": comps}

