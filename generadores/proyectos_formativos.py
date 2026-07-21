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

    # Fases válidas
    fases_validas = {"ANÁLISIS", "PLANEACIÓN", "EJECUCIÓN", "EVALUACIÓN",
                     "ANALISIS", "PLANEACION", "EJECUCION", "EVALUACION"}

    # Estrategia: partir el texto en bloques que empiezan con FASE
    # y contienen ACTIVIDAD + RAP + COMPETENCIA
    # Usamos regex de "look-behind" y "look-ahead" con fases

    # Regex para encontrar cada fila de la tabla:
    # (FASE) (ACTIVIDAD - texto en mayúsculas) (código_rap - texto_rap) (código_competencia - texto_competencia)
    patron_fila = re.compile(
        r"(?P<fase>ANÁLISIS|PLANEACIÓN|EJECUCIÓN|EVALUACIÓN|ANALISIS|PLANEACION|EJECUCION|EVALUACION)"
        r"\s+"
        r"(?P<actividad>.+?)"
        r"\s+"
        r"(?P<codigo_rap>\d{6})\s*-\s*"
        r"(?P<nombre_rap>.+?)"
        r"\s+"
        r"(?P<codigo_comp>\d{9})\s*-\s*"
        r"(?P<nombre_comp>.+?)"
        r"(?=(?:ANÁLISIS|PLANEACIÓN|EJECUCIÓN|EVALUACIÓN|ANALISIS|PLANEACION|EJECUCION|EVALUACION|\Z|3\.5|3\.6|3\.7|4\.|5\.))",
        re.DOTALL
    )

    filas = []
    for m in patron_fila.finditer(seccion):
        fase = m.group("fase").strip()
        actividad = _limpiar(m.group("actividad"))
        codigo_rap = m.group("codigo_rap").strip()
        nombre_rap = _limpiar(m.group("nombre_rap"))
        codigo_comp = m.group("codigo_comp").strip()
        nombre_comp = _limpiar(m.group("nombre_comp"))

        # Filtrar líneas basura de página / encabezado
        if any(basura in actividad for basura in ["Página", "GFPI-", "SERVICIO NACIONAL", "Modelo de Mejora"]):
            # Intentar limpiar
            actividad = re.sub(r"Página\s+\d+\s+de\s*\d+.*?GFPI[^\n]*", "", actividad)
            actividad = re.sub(r"SERVICIO NACIONAL[^\n]*", "", actividad)
            actividad = _limpiar(actividad)

        # Normalizar fase (todas con tilde)
        fase = _normalizar_fase(fase)

        filas.append({
            "fase": fase,
            "actividad": actividad,
            "codigo_rap": codigo_rap,
            "nombre_rap": nombre_rap,
            "codigo_competencia": codigo_comp,
            "nombre_competencia": nombre_comp,
        })

    return filas


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

    # Ordenar fases en el orden estándar del SENA
    orden_fases = {"ANÁLISIS": 1, "PLANEACIÓN": 2, "EJECUCIÓN": 3, "EVALUACIÓN": 4}
    fases_lista.sort(key=lambda f: orden_fases.get(f["nombre"], 99))

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
