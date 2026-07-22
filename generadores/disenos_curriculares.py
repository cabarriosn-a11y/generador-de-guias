"""
Lee PDFs de Diseño Curricular SENA (Informe Programa de Formación Titulada)
y extrae por cada competencia:
- Código norma de competencia laboral
- Nombre de la competencia
- Duración en horas
- Resultados de aprendizaje (RAPs)
- Conocimientos de proceso (verbatim)
- Conocimientos del saber (verbatim)
- Criterios de evaluación (verbatim)

Todo se procesa LOCALMENTE con pypdf, sin consumir tokens de IA.
"""
import json
import re
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader


# ============ EXTRACCIÓN ============
def extraer_texto_pdf(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join([p.extract_text() for p in reader.pages])


# ============ INFO BÁSICA DEL PROGRAMA ============
def parsear_info_programa(texto: str) -> dict:
    """Extrae la sección 1 (info básica del programa)."""
    info = {}

    # Denominación del programa: viene ANTES de "1. INFORMACION BÁSICA DEL PROGRAMA"
    # Patrón: línea en mayúsculas terminada en punto justo antes del marcador
    m = re.search(
        r"DE\s+SOFTWARE\s*\n\s*([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s,\.]+?)\s*\n\s*1\.\s*INFORMACION\s*BÁSICA",
        texto
    )
    if m:
        info["denominacion"] = _limpiar(m.group(1))
    else:
        # Fallback: buscar antes de "1. INFORMACION BÁSICA"
        m = re.search(r"\n([A-ZÁÉÍÓÚÑ][A-ZÁÉÍÓÚÑ\s]{10,})\.?\s*\n1\.\s*INFORMACION\s*BÁSICA", texto)
        if m:
            info["denominacion"] = _limpiar(m.group(1))

    # Código y versión: por el layout de tabla, aparecen desordenados
    # Extraer la región entre "1.2. Código" y "1.4"
    m = re.search(r"1\.2\..*?1\.4", texto, re.DOTALL)
    if m:
        region = m.group(0)
        # Código del programa: 6 dígitos (típico SENA)
        codigos = re.findall(r"\b(\d{6})\b", region)
        if codigos:
            info["codigo_programa"] = codigos[0]
        # Versión: 1-2 dígitos (típico 1, 2, 3...)
        versiones = re.findall(r"\b(\d{1,2})\b", region)
        # Filtrar el código de programa
        versiones = [v for v in versiones if v != info.get("codigo_programa")]
        if versiones:
            info["version_programa"] = versiones[0]

    # Duraciones
    m = re.search(r"Etapa\s*Lectiva:?\s*(\d+)\s*horas", texto)
    if m: info["etapa_lectiva_horas"] = m.group(1)
    m = re.search(r"Etapa\s*Productiva:?\s*(\d+)\s*horas", texto)
    if m: info["etapa_productiva_horas"] = m.group(1)
    # El total viene explícito
    m = re.search(r"Total:\s*(\d{3,5})\s*horas", texto)
    if m: info["total_horas"] = m.group(1)

    # Tipo y título
    m = re.search(r"1\.6\s*Tipo\s*de\s*programa\s*([A-ZÁÉÍÓÚÑ]+)", texto)
    if m: info["tipo_programa"] = m.group(1).strip()
    m = re.search(r"1\.7\s*Título[^\n]*\n[^\n]*\n([A-ZÁÉÍÓÚÑ]{4,})", texto)
    if m:
        info["titulo"] = m.group(1).strip()

    return info


# ============ PARSEO DE COMPETENCIAS ============
def _limpiar(texto: str) -> str:
    if not texto:
        return ""
    # Quitar "Página X de Y" y variantes
    texto = re.sub(r'Página\s+\d+\s*de\s*\d+.*', '', texto)
    texto = re.sub(r'\d{2}/\d{2}/\d{2,4}\s*\d{1,2}:\d{2}', '', texto)
    texto = re.sub(r'\s+', ' ', texto).strip()
    return texto.rstrip('.').strip()


def _extraer_seccion(texto: str, marca_inicio: str, marcas_fin: list) -> str:
    """Extrae el texto entre marca_inicio y la primera marca_fin encontrada."""
    idx_inicio = texto.find(marca_inicio)
    if idx_inicio == -1:
        return ""
    inicio = idx_inicio + len(marca_inicio)
    fin = len(texto)
    for marca_fin in marcas_fin:
        p = texto.find(marca_fin, inicio)
        if p != -1 and p < fin:
            fin = p
    return texto[inicio:fin]


def _limpiar_lista_items(texto: str) -> list:
    """Convierte un bloque de texto en una lista de items limpios (uno por línea).
    Une líneas que quedaron partidas por el ancho de la tabla del PDF.
    """
    if not texto:
        return []
    # Primero limpiar encabezados y basura línea por línea
    lineas_limpias = []
    for linea in texto.split("\n"):
        linea = linea.strip()
        if not linea:
            continue
        # Filtrar encabezados repetidos del PDF
        if any(basura in linea for basura in [
            "LÍNEA TECNOLÓGICA", "RED TECNOLÓGICA", "RED DE CONOCIMIENTO",
            "GESTIÓN DE LA INFORMACIÓN", "SOFTWARE", "Página"
        ]):
            continue
        # Filtrar fechas y numeración de página
        if re.match(r"^\d{2}/\d{2}/\d{2,4}\s*\d{1,2}:\d{2}", linea):
            continue
        if re.match(r"^\d+\s*de\s*\d+$", linea):
            continue
        lineas_limpias.append(linea)

    # Ahora unir líneas que son continuación de la anterior
    # (una línea que empieza en minúscula o con palabras cortas suele ser continuación)
    items = []
    buffer = ""
    for linea in lineas_limpias:
        primera = linea[0] if linea else ""
        # Es continuación si:
        # - Empieza en minúscula
        # - O la línea anterior no terminaba en punto, dos puntos o cifra
        es_continuacion = (
            primera.islower()
            or (buffer and not re.search(r"[.!?)\d]\s*$", buffer))
        )
        if buffer and es_continuacion:
            buffer = buffer + " " + linea
        else:
            if buffer:
                items.append(_limpiar(buffer))
            buffer = linea
    if buffer:
        items.append(_limpiar(buffer))

    # Filtrar items muy cortos
    return [it for it in items if it and len(it) > 5]


def parsear_competencias(texto: str) -> list:
    """Extrae la lista de competencias del PDF (sección 4 repetida)."""
    # Dividir el texto por el marcador "4. CONTENIDOS CURRICULARES DE LA COMPETENCIA"
    # Cada bloque contiene una competencia completa
    partes = re.split(r"4\.\s*CONTENIDOS\s*CURRICULARES\s*DE\s*LA\s*COMPETENCIA", texto)
    # El primer elemento es todo lo anterior al primer marcador — descartar
    bloques = partes[1:]

    competencias = []
    for bloque in bloques:
        comp = _parsear_bloque_competencia(bloque)
        if comp and comp.get("codigo"):
            competencias.append(comp)

    # Deduplicar por código (el mismo bloque puede aparecer 2 veces por saltos de página)
    vistas = {}
    for c in competencias:
        cod = c["codigo"]
        if cod not in vistas:
            vistas[cod] = c
        else:
            # Preferir la versión más completa (con más contenido)
            actual = vistas[cod]
            score_nuevo = _puntuar_completitud(c)
            score_actual = _puntuar_completitud(actual)
            if score_nuevo > score_actual:
                vistas[cod] = c
    return list(vistas.values())


def _puntuar_completitud(comp: dict) -> int:
    score = 0
    for campo in ("nombre", "duracion_horas"):
        if comp.get(campo):
            score += 10
    for campo in ("raps", "conocimientos_proceso", "conocimientos_saber", "criterios_evaluacion"):
        score += len(comp.get(campo, []))
    return score


def _parsear_bloque_competencia(bloque: str) -> dict:
    """Parsea UN bloque de competencia (contenido después del marcador de sección 4)."""
    comp = {}

    # Norma / Unidad de Competencia (4.1) — viene ANTES o DESPUÉS del label
    # Estrategia: buscar entre inicio y "4.2"
    m = re.search(r"^(.+?)4\.1\s*NORMA\s*/\s*UNIDAD\s*DE\s*COMPETENCIA", bloque, re.DOTALL)
    if m:
        comp["norma"] = _limpiar(m.group(1))
    else:
        # A veces el título viene DESPUÉS de "4.1"
        m = re.search(r"4\.1\s*NORMA\s*/\s*UNIDAD\s*DE\s*COMPETENCIA\s*(.+?)4\.2", bloque, re.DOTALL)
        if m:
            comp["norma"] = _limpiar(m.group(1))

    # Código de competencia (4.2) — 6-9 dígitos
    # Puede venir antes o después del label "4.2 CÓDIGO NORMA DE COMPETENCIA LABORAL"
    m = re.search(r"(\d{6,9})\s*4\.2\s*CÓDIGO", bloque)
    if not m:
        m = re.search(r"4\.2\s*CÓDIGO\s*NORMA\s*DE\s*COMPETENCIA\s*LABORAL\s*(\d{6,9})", bloque)
    if m:
        comp["codigo"] = m.group(1)

    # Nombre de la competencia (4.3) — puede venir en varias líneas
    # En algunos layouts, 4.5 aparece ANTES de 4.4, por eso paramos en el primer marcador
    m = re.search(
        r"4\.3\s*NOMBRE\s*DE\s*LA\s*COMPETENCIA\s*(.+?)"
        r"(?=4\.4\s*DURACIÓN|4\.5\s*RESULTADOS)",
        bloque, re.DOTALL
    )
    if m:
        comp["nombre"] = _limpiar(m.group(1))

    # Duración (4.4) — horas
    m = re.search(r"4\.4[^0-9]*(\d+)\s*horas", bloque)
    if m:
        comp["duracion_horas"] = int(m.group(1))

    # RAPs (4.5) — vienen bajo "DENOMINACIÓN" y antes de "4.6"
    seccion_raps = _extraer_seccion(
        bloque, "DENOMINACIÓN",
        ["4.6 CONOCIMIENTOS", "4.6\nCONOCIMIENTOS", "CONOCIMIENTOS DE PROCESO"]
    )
    comp["raps"] = _limpiar_lista_items(seccion_raps)

    # Conocimientos de proceso (4.6.1)
    seccion_proc = _extraer_seccion(
        bloque, "4.6.1 CONOCIMIENTOS DE PROCESO",
        ["4.6.2", "CONOCIMIENTOS DEL SABER"]
    )
    if not seccion_proc:
        seccion_proc = _extraer_seccion(
            bloque, "CONOCIMIENTOS DE PROCESO",
            ["4.6.2", "CONOCIMIENTOS DEL SABER"]
        )
    comp["conocimientos_proceso"] = _limpiar_lista_items(seccion_proc)

    # Conocimientos del saber (4.6.2)
    seccion_saber = _extraer_seccion(
        bloque, "4.6.2 CONOCIMIENTOS DEL SABER",
        ["4.7", "CRITERIOS DE EVALUACIÓN"]
    )
    if not seccion_saber:
        seccion_saber = _extraer_seccion(
            bloque, "CONOCIMIENTOS DEL SABER",
            ["4.7", "CRITERIOS DE EVALUACIÓN"]
        )
    comp["conocimientos_saber"] = _limpiar_lista_items(seccion_saber)

    # Criterios de evaluación (4.7)
    seccion_crit = _extraer_seccion(
        bloque, "4.7 CRITERIOS DE EVALUACIÓN",
        ["4.8", "PERFIL DEL INSTRUCTOR"]
    )
    if not seccion_crit:
        seccion_crit = _extraer_seccion(
            bloque, "CRITERIOS DE EVALUACIÓN",
            ["4.8", "PERFIL DEL INSTRUCTOR"]
        )
    comp["criterios_evaluacion"] = _limpiar_lista_items(seccion_crit)

    return comp


# ============ PROCESAMIENTO COMPLETO ============
def procesar_pdf(pdf_bytes: bytes) -> dict:
    """Procesa un PDF de diseño curricular y devuelve un dict estructurado."""
    texto = extraer_texto_pdf(pdf_bytes)
    info = parsear_info_programa(texto)
    competencias = parsear_competencias(texto)
    return {
        **info,
        "competencias": competencias,
        "total_competencias": len(competencias),
    }


# ============ PERSISTENCIA ============
def cargar_disenos(archivo: Path) -> list:
    if archivo.exists():
        try:
            return json.loads(archivo.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def guardar_disenos(archivo: Path, disenos: list):
    archivo.write_text(json.dumps(disenos, indent=2, ensure_ascii=False), encoding="utf-8")


def agregar_o_actualizar_diseno(archivo: Path, diseno: dict) -> list:
    disenos = cargar_disenos(archivo)
    codigo = diseno.get("codigo_programa", "")
    if codigo:
        for i, d in enumerate(disenos):
            if d.get("codigo_programa") == codigo:
                disenos[i] = diseno
                guardar_disenos(archivo, disenos)
                return disenos
    disenos.append(diseno)
    guardar_disenos(archivo, disenos)
    return disenos


def eliminar_diseno(archivo: Path, codigo_programa: str) -> list:
    disenos = cargar_disenos(archivo)
    disenos = [d for d in disenos if d.get("codigo_programa") != codigo_programa]
    guardar_disenos(archivo, disenos)
    return disenos


def buscar_competencia_por_codigo(codigo: str, archivo: Path) -> dict:
    """Busca en TODOS los diseños guardados una competencia por código.
    Retorna dict con la competencia + info del programa donde está, o {} si no hay coincidencia.
    """
    if not codigo:
        return {}
    codigo = str(codigo).strip()
    disenos = cargar_disenos(archivo)
    for diseno in disenos:
        for comp in diseno.get("competencias", []):
            if comp.get("codigo") == codigo:
                return {
                    "competencia": comp,
                    "programa": diseno.get("denominacion", ""),
                    "codigo_programa": diseno.get("codigo_programa", ""),
                }
    return {}
