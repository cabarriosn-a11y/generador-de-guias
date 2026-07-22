"""
Lee PDFs de proyectos formativos SENA (formato GFPI-F-016) y los estructura
para que la app los pueda usar como fuente de dropdowns cascada:
Proyecto → Fase → Actividad → Competencia → RAPs.

TODO SE HACE LOCALMENTE — no consume tokens de IA.
"""
import json
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

from pypdf import PdfReader


# ============ EXTRACCIÓN DE TEXTO ============
def extraer_texto_pdf(pdf_bytes: bytes) -> str:
    """Extrae todo el texto del PDF."""
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join([page.extract_text() for page in reader.pages])


# ============ PARSEO DE INFORMACIÓN BÁSICA ============
def parsear_info_basica(texto: str) -> dict:
    """Extrae la sección 1 - Información básica del proyecto."""
    info = {}

    # Los códigos vienen ANTES de sus etiquetas en el texto extraído por pypdf.
    # Patrón real: "2785526 122901Código del Programa SOFIA: Versión del Programa: 1 5Fichas asociadas:"
    # Estrategia: buscar los números que preceden a las etiquetas.
    m = re.search(r"(\d{7,})\s+(\d{6})Código del Programa SOFIA:", texto)
    if m:
        info["codigo_proyecto_sofia"] = m.group(1)
        info["codigo_programa_sofia"] = m.group(2)
    else:
        # Fallback: buscar por separado
        m = re.search(r"Código Proyecto SOFIA:\s*\n?\s*(?:1\.\s*Información[^\n]*\n)?\s*(\d{6,})", texto)
        if m: info["codigo_proyecto_sofia"] = m.group(1)

    # Versión y fichas: patrón "Versión del Programa: 1 5Fichas asociadas:"
    m = re.search(r"Versión del Programa:\s*(\d+)\s+(\d+)Fichas asociadas", texto)
    if m:
        info["version_programa"] = m.group(1)
        info["fichas_asociadas"] = m.group(2)

    # Centro y regional
    m = re.search(r"1\.1\s*Centro de Formación:?\s*(.+?)\s*1\.2", texto, re.DOTALL)
    if m: info["centro_formacion"] = re.sub(r'\s+', ' ', m.group(1)).strip()

    m = re.search(r"1\.2\s*Regional:?\s*(.+?)(?=\n|1\.3)", texto)
    if m: info["regional"] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # Nombre proyecto
    m = re.search(r"1\.3\s*Nombre del proyecto:?\s*(.+?)(?=1\.4)", texto, re.DOTALL)
    if m: info["nombre_proyecto"] = re.sub(r'\s+', ' ', m.group(1)).strip()

    # Programa formación
    m = re.search(r"1\.4\s*Programa de Formación[^:]*:?\s*(.+?)(?=1\.5)", texto, re.DOTALL)
    if m:
        prog = re.sub(r'\s+', ' ', m.group(1)).strip().rstrip('.')
        info["programa_formacion"] = prog

    # Tiempo
    m = re.search(r"Tiempo estimado[^:]*\(meses\)[^\d]*(\d+)", texto)
    if m: info["tiempo_meses"] = m.group(1)

    return info


# ============ PARSEO DE LA TABLA DE PLANEACIÓN (SECCIÓN 3) ============
def parsear_tabla_planeacion(texto: str) -> list:
    """Extrae la tabla 3 con FASE, ACTIVIDAD, RAP, COMPETENCIA de cada fila.

    Retorna una lista de dicts: [{fase, actividad, codigo_rap, nombre_rap,
    codigo_competencia, nombre_competencia}, ...]
    """
    # Encontrar la sección 3
    inicio = texto.find("3. Planeación del proyecto")
    if inicio == -1:
        inicio = 0

    # Encontrar fin: cualquiera de estos marcadores
    fin_marcadores = [
        "3.5 Organización del proyecto",
        "3.7. Recursos",
        "3.7 Recursos",
        "4. Rubros",
        "5. Equipo",
    ]
    fin = len(texto)
    for marcador in fin_marcadores:
        p = texto.find(marcador, inicio + 100)
        if p != -1 and p < fin:
            fin = p

    seccion = texto[inicio:fin]

    # ★ ESTRATEGIA DINÁMICA (funciona con cualquier programa SENA):
    # Cada fila del PDF tiene esta estructura:
    #   FASE (línea corta en mayúsculas)
    #   ACTIVIDAD (varias líneas en mayúsculas)
    #   codigo_RAP - texto RAP (varias líneas)
    #   codigo_competencia - texto competencia (varias líneas)
    #
    # Para cada par (RAP + competencia), buscamos hacia atrás la fase (línea corta
    # en mayúsculas) y todo lo que hay entre la fase y el RAP es la actividad.

    patron_rap_comp = re.compile(
        r"(?P<codigo_rap>\d{6})\s*-\s*"
        r"(?P<nombre_rap>.+?)"
        r"\s+"
        r"(?P<codigo_comp>\d{9})\s*-\s*"
        r"(?P<nombre_comp>.+?)"
        r"(?=\d{6}\s*-|\Z|3\.5\s|3\.6\s|3\.7|4\.\s*Rubros|5\.\s*Equipo)",
        re.DOTALL
    )

    filas = []

    # Para la primera fila, el contexto es todo lo que hay ANTES del primer match
    matches = list(patron_rap_comp.finditer(seccion))
    if not matches:
        return []

    contexto_inicial = seccion[:matches[0].start()]
    fase_actual, actividad_actual = _detectar_fase_y_actividad(contexto_inicial)

    for i, m in enumerate(matches):
        codigo_rap = m.group("codigo_rap").strip()
        nombre_rap = _limpiar(m.group("nombre_rap"))
        codigo_comp = m.group("codigo_comp").strip()
        nombre_comp_raw = m.group("nombre_comp")

        # Del final del nombre_comp capturado, separar la fase+actividad de la SIGUIENTE fila
        nombre_comp_limpio, fase_sig, actividad_sig = _separar_fase_del_final(nombre_comp_raw)

        # Guardar la fila actual
        filas.append({
            "fase": fase_actual,
            "actividad": actividad_actual,
            "codigo_rap": codigo_rap,
            "nombre_rap": nombre_rap,
            "codigo_competencia": codigo_comp,
            "nombre_competencia": _limpiar(nombre_comp_limpio),
        })

        # Actualizar fase/actividad para la siguiente iteración
        if fase_sig:
            fase_actual = fase_sig
        if actividad_sig:
            actividad_actual = actividad_sig

    return filas


def _es_nombre_fase_tipico(linea: str) -> bool:
    """True si la línea coincide con un nombre típico de fase SENA.
    Maneja prefijos numéricos como '1. ANÁLISIS', '2. PLANEACIÓN', etc.
    """
    # Normalizar: mayúsculas, sin tildes, sin espacios ni prefijos numéricos
    norm = linea.upper().strip().rstrip('.').rstrip(':').strip()
    # Quitar prefijo tipo "1.", "2)", "3-"
    norm = re.sub(r"^\d+[\.\)\-]\s*", "", norm).strip()
    # Quitar tildes (todas las variantes, incluyendo ANALISÍS mal escrito)
    norm_sin_tildes = (norm.replace("Á", "A").replace("É", "E").replace("Í", "I")
                          .replace("Ó", "O").replace("Ú", "U").replace("Ñ", "N"))
    # Diccionario de nombres típicos SENA
    fases_tipicas = {
        "ANALISIS", "PLANEACION", "PLANEAR",
        "EJECUCION", "EJECUTAR",
        "EVALUACION", "EVALUAR",
        "DISENO", "DIAGNOSTICO", "DEFINICION",
        "IDENTIFICACION", "IMPLEMENTACION",
        "VERIFICACION", "DESARROLLO",
        "CONCEPTUALIZACION", "ORGANIZACION",
        "FORMULACION", "PROGRAMACION",
        "OPERACION", "CONTROL",
        "REVISION", "SEGUIMIENTO",
    }
    return norm_sin_tildes in fases_tipicas


# Palabras que SUELEN ser continuación (no fases) — para evitar falsos positivos
_PALABRAS_NO_FASE = {
    "ORGANIZACIÓN", "ORGANIZACION",
    "EMPRESA", "ENTIDAD",
    "SECTOR", "CONTEXTO",
    "NORMATIVA", "POLÍTICA", "POLITICA",
    "TECNOLOGÍA", "TECNOLOGIA",
    "INSTITUCIÓN", "INSTITUCION",
    "COMUNIDAD", "SOCIEDAD",
    "TÉCNICOS", "TECNICOS", "SOFTWARE",
    "VIGENTE", "SOCIAL", "PRODUCTIVO",
    "AMBIENTAL", "LABORAL",
}


def _es_probable_fase(linea: str) -> bool:
    """True si la línea es una fase (por heurística estricta)."""
    linea = linea.strip()
    palabras = linea.split()
    # Debe ser corta, mayoritariamente en mayúsculas
    if not (1 <= len(palabras) <= 4 and len(linea) <= 30 and _es_mayus(linea)):
        return False
    # No debe tener códigos largos
    if re.search(r"\d{4,}", linea):
        return False
    # Filtrar: si termina en punto y NO tiene prefijo numérico → probablemente es final
    # de una frase, no fase
    if linea.rstrip().endswith(".") and not re.match(r"^\d+[\.\)\-]\s*[A-ZÁÉÍÓÚÑ]", linea):
        return False
    # Extraer la palabra clave (sin prefijo numérico ni puntos)
    palabra_clave = re.sub(r"^\d+[\.\)\-]\s*", "", linea.upper().rstrip('.').rstrip(':')).strip()
    # Filtrar palabras que son continuación de frases
    if palabra_clave in _PALABRAS_NO_FASE:
        return False
    # Prioridad 1: coincide con diccionario típico → es fase
    if _es_nombre_fase_tipico(linea):
        return True
    # Prioridad 2 (fallback): una sola palabra ≥4 chars y no está en exclusiones
    if len(palabras) == 1 and len(palabra_clave) >= 4:
        return True
    return False


def _separar_fase_del_final(nombre_comp_raw: str):
    """Del final del nombre_comp capturado, separar la fase+actividad de la siguiente fila.
    Retorna (nombre_comp_real, fase_siguiente, actividad_siguiente).
    """
    if not nombre_comp_raw:
        return "", None, None

    lineas = [l.strip() for l in nombre_comp_raw.split("\n") if l.strip()]
    lineas = [l for l in lineas if not _es_basura(l)]
    if not lineas:
        return "", None, None

    # Buscar de atrás hacia adelante la ÚLTIMA fase real (según _es_probable_fase)
    idx_fase = -1
    for i in range(len(lineas) - 1, -1, -1):
        if _es_probable_fase(lineas[i]):
            idx_fase = i
            break

    if idx_fase == -1:
        return " ".join(lineas), None, None

    # nombre_comp real: líneas antes de la fase
    nombre_comp_real = " ".join(lineas[:idx_fase])
    fase_siguiente = lineas[idx_fase]
    actividad_siguiente = _limpiar(" ".join(lineas[idx_fase + 1:]))
    if len(actividad_siguiente) < 20:
        actividad_siguiente = None
    return nombre_comp_real, fase_siguiente, actividad_siguiente


def _detectar_fase_y_actividad(contexto: str):
    """Detecta (fase, actividad) en el texto que aparece justo antes del primer RAP."""
    if not contexto or not contexto.strip():
        return None, None

    contexto_limpio = _limpiar_basura_pdf(contexto)
    lineas = [l.strip() for l in contexto_limpio.split("\n") if l.strip()]
    lineas = [l for l in lineas if not _es_basura(l)]
    if not lineas:
        return None, None

    fase = None
    idx_fase = -1
    for i, linea in enumerate(lineas):
        if _es_probable_fase(linea):
            fase = linea
            idx_fase = i
            break

    # Fallback: intentar separar "FASE" pegada al inicio de la actividad
    if fase is None and lineas:
        primera = lineas[0]
        m = re.match(r"^([A-ZÁÉÍÓÚÑ]{4,20})([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{20,})$", primera)
        if m:
            posible_fase = m.group(1)
            if _es_probable_fase(posible_fase):
                fase = posible_fase
                resto = m.group(2) + " " + " ".join(lineas[1:])
                actividad = _limpiar(resto)
                return fase, actividad if len(actividad) > 30 else None

    if idx_fase >= 0:
        candidato = " ".join(lineas[idx_fase + 1:])
    else:
        candidato = " ".join(lineas)
    actividad = _limpiar(candidato)
    if len(actividad) < 30:
        actividad = None

    return fase, actividad


def _es_mayus(texto: str) -> bool:
    """True si el texto está mayoritariamente en mayúsculas."""
    letras = [c for c in texto if c.isalpha()]
    if not letras:
        return False
    mayus = sum(1 for c in letras if c.isupper())
    return mayus / len(letras) > 0.8


def _es_basura(linea: str) -> bool:
    """Detecta líneas de encabezado, pie de página, etc."""
    basura_patrones = [
        "Página", "GFPI-", "SERVICIO NACIONAL", "Modelo de Mejora",
        "Sistema Integrado de Gestión",
        "Procedimiento Ejecución de la Formación",
        "PROYECTO FORMATIVO",
        "3.1. Fases", "3.2. Actividades",
        "3.3. Resultados", "3.4. Competencia",
        "Fases del Proyecto", "Actividades del Proyecto",
        "Resultados de Aprendizaje",
        "Competencia Asociada",
    ]
    return any(p in linea for p in basura_patrones)


def _limpiar_basura_pdf(texto: str) -> str:
    """Elimina líneas basura del texto (encabezados repetidos, pies de página)."""
    lineas_limpias = []
    for linea in texto.split("\n"):
        if not _es_basura(linea):
            # También filtrar fechas y numeración
            if re.match(r"^\d{2}/\d{2}/\d{2,4}\s*\d{1,2}:\d{2}", linea.strip()):
                continue
            lineas_limpias.append(linea)
    return "\n".join(lineas_limpias)


def _limpiar(texto: str) -> str:
    """Colapsa espacios múltiples y elimina saltos de línea excesivos."""
    if not texto:
        return ""
    texto = re.sub(r'\s+', ' ', texto).strip()
    # Quitar guiones sueltos al final
    texto = re.sub(r'\s*-\s*$', '', texto)
    return texto


def _normalizar_fase(fase: str) -> str:
    """Normaliza fase para que siempre lleve tilde en la forma canónica."""
    mapeo = {
        "ANALISIS": "ANÁLISIS", "ANÁLISIS": "ANÁLISIS",
        "PLANEACION": "PLANEACIÓN", "PLANEACIÓN": "PLANEACIÓN",
        "EJECUCION": "EJECUCIÓN", "EJECUCIÓN": "EJECUCIÓN",
        "EVALUACION": "EVALUACIÓN", "EVALUACIÓN": "EVALUACIÓN",
    }
    return mapeo.get(fase.upper(), fase)


# ============ ESTRUCTURACIÓN JERÁRQUICA ============
def _normalizar_actividad(nombre: str) -> str:
    """Normaliza el nombre de una actividad para agrupar variantes iguales."""
    if not nombre:
        return ""
    s = re.sub(r'\s+', ' ', nombre).strip().upper()
    s = s.rstrip('.')
    return s


def _agrupar_actividades_similares(filas: list) -> dict:
    """Agrupa actividades que son la misma pero con pequeñas diferencias de
    formato (variaciones del extractor de PDF). Retorna dict:
    normalizado → nombre_canónico (el más largo/completo).
    """
    # Extraer todos los nombres únicos por fase
    actividades_por_fase = {}
    for fila in filas:
        f = fila["fase"]
        if f not in actividades_por_fase:
            actividades_por_fase[f] = set()
        actividades_por_fase[f].add(fila["actividad"])

    # Para cada fase, agrupar actividades por prefijo de 40 chars
    mapa = {}  # (fase, actividad_normalizada) → nombre_canónico
    for fase, actividades in actividades_por_fase.items():
        # Agrupar por prefijo
        grupos = {}
        for act in actividades:
            norm = _normalizar_actividad(act)
            if len(norm) < 20:
                continue
            # Usar los primeros 50 caracteres como clave de agrupación
            clave_grupo = norm[:50]
            if clave_grupo not in grupos:
                grupos[clave_grupo] = []
            grupos[clave_grupo].append(act)

        # Elegir la variante más larga como canónica para cada grupo
        for clave, variantes in grupos.items():
            canonica = max(variantes, key=len)
            for variante in variantes:
                mapa[(fase, _normalizar_actividad(variante))] = canonica

    return mapa


def estructurar_proyecto(info_basica: dict, filas: list) -> dict:
    """Convierte las filas planas en una estructura jerárquica:
    Proyecto → Fases → Actividades → Competencias → RAPs
    """
    # Sanitizar filas: reemplazar fases None/vacías por "SIN FASE"
    for fila in filas:
        if not fila.get("fase") or not str(fila.get("fase", "")).strip():
            fila["fase"] = "SIN FASE"
        else:
            # Asegurar que sea string
            fila["fase"] = str(fila["fase"]).strip()

    # Encontrar forma canónica de cada actividad por fase
    canon = _agrupar_actividades_similares(filas)

    # Agrupar por fase → actividad_canónica → competencia → RAPs
    fases = {}
    for fila in filas:
        f = fila["fase"]
        a_norm = _normalizar_actividad(fila["actividad"])
        a_canon = canon.get((f, a_norm), fila["actividad"])
        cc = fila["codigo_competencia"]
        nc = fila["nombre_competencia"]

        # Limpiar el nombre de la competencia (quitar "Página X" si quedó pegado)
        nc = re.sub(r'\s+Página\s+\d+\s+de\s*\d+.*$', '', nc, flags=re.DOTALL).strip()
        nc = re.sub(r'\s+GFPI-[\w\s]*$', '', nc).strip()

        clave_canon = _normalizar_actividad(a_canon)

        if f not in fases:
            fases[f] = {"actividades": {}}
        if clave_canon not in fases[f]["actividades"]:
            fases[f]["actividades"][clave_canon] = {
                "nombre": a_canon,
                "competencias": {},
            }
        if cc not in fases[f]["actividades"][clave_canon]["competencias"]:
            fases[f]["actividades"][clave_canon]["competencias"][cc] = {
                "nombre": nc,
                "raps": [],
            }
        raps = fases[f]["actividades"][clave_canon]["competencias"][cc]["raps"]
        if not any(r["codigo"] == fila["codigo_rap"] for r in raps):
            raps.append({
                "codigo": fila["codigo_rap"],
                "nombre": re.sub(r'\s+', ' ', fila["nombre_rap"]).strip(),
            })

    # Convertir a listas
    fases_lista = []
    for nombre_fase, datos in fases.items():
        actividades_lista = []
        for _, datos_act in datos["actividades"].items():
            competencias_lista = []
            for cod_comp, datos_comp in datos_act["competencias"].items():
                competencias_lista.append({
                    "codigo": cod_comp,
                    "nombre": datos_comp["nombre"],
                    "raps": datos_comp["raps"],
                })
            actividades_lista.append({
                "nombre": datos_act["nombre"],
                "competencias": competencias_lista,
            })
        fases_lista.append({
            "nombre": nombre_fase,
            "actividades": actividades_lista,
        })

    # Preservar el orden en que las fases aparecieron en el PDF (usando el primer índice de cada fase)
    orden_aparicion = {}
    for i, f in enumerate(filas):
        nombre_fase = f["fase"]
        if nombre_fase and nombre_fase not in orden_aparicion:
            orden_aparicion[nombre_fase] = i
    # Ordenar la lista de fases según su primera aparición
    fases_lista.sort(key=lambda f: orden_aparicion.get(f["nombre"], 99))

    # Consolidar todas las competencias del proyecto (para acceso rápido)
    todas_competencias = {}
    for fila in filas:
        cc = fila["codigo_competencia"]
        nc = re.sub(r'\s+Página\s+\d+.*$', '', fila["nombre_competencia"], flags=re.DOTALL).strip()
        nc = re.sub(r'\s+GFPI-[\w\s]*$', '', nc).strip()
        if cc not in todas_competencias:
            todas_competencias[cc] = {
                "codigo": cc,
                "nombre": nc,
                "raps": [],
            }
        raps = todas_competencias[cc]["raps"]
        if not any(r["codigo"] == fila["codigo_rap"] for r in raps):
            raps.append({
                "codigo": fila["codigo_rap"],
                "nombre": re.sub(r'\s+', ' ', fila["nombre_rap"]).strip(),
            })

    return {
        **info_basica,
        "fases": fases_lista,
        "competencias_agrupadas": list(todas_competencias.values()),
        "total_filas": len(filas),
    }


# ============ PROCESAMIENTO COMPLETO ============
def procesar_pdf(pdf_bytes: bytes) -> dict:
    """Procesa un PDF completo y devuelve el proyecto estructurado."""
    texto = extraer_texto_pdf(pdf_bytes)
    info = parsear_info_basica(texto)
    filas = parsear_tabla_planeacion(texto)
    proyecto = estructurar_proyecto(info, filas)
    return proyecto


# ============ PERSISTENCIA ============
def cargar_proyectos(archivo: Path) -> list:
    """Carga la lista de proyectos guardados."""
    if archivo.exists():
        try:
            return json.loads(archivo.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def guardar_proyectos(archivo: Path, proyectos: list):
    """Guarda la lista de proyectos."""
    archivo.write_text(json.dumps(proyectos, indent=2, ensure_ascii=False), encoding="utf-8")


def agregar_o_actualizar_proyecto(archivo: Path, proyecto: dict) -> list:
    """Agrega o actualiza (por código) un proyecto en la lista."""
    proyectos = cargar_proyectos(archivo)
    codigo = proyecto.get("codigo_proyecto_sofia", "")
    if codigo:
        # Buscar si ya existe
        for i, p in enumerate(proyectos):
            if p.get("codigo_proyecto_sofia") == codigo:
                proyectos[i] = proyecto
                guardar_proyectos(archivo, proyectos)
                return proyectos
    # Si no existe, agregar
    proyectos.append(proyecto)
    guardar_proyectos(archivo, proyectos)
    return proyectos


def eliminar_proyecto(archivo: Path, codigo_proyecto: str) -> list:
    """Elimina un proyecto por código."""
    proyectos = cargar_proyectos(archivo)
    proyectos = [p for p in proyectos if p.get("codigo_proyecto_sofia") != codigo_proyecto]
    guardar_proyectos(archivo, proyectos)
    return proyectos
