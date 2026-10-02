"""Integración con Gemini para generar contenido pedagógico SENA.

Prompts editables por el usuario (data/prompts.json).
Instrucciones extras por llamada para afinar sin editar el prompt base.
Pausa automática entre llamadas para respetar el rate limit gratuito.
"""
import json
import re
import time
from pathlib import Path
from typing import Optional

# SDK oficial vigente: google-genai (`from google import genai`). El paquete anterior
# google-generativeai quedó sin soporte; se usa solo como respaldo si el nuevo no está.
try:
    from google import genai as genai_nuevo
    from google.genai import types as genai_types
    SDK_NUEVO = True
except ImportError:
    SDK_NUEVO = False
try:
    import warnings as _w
    with _w.catch_warnings():
        _w.simplefilter("ignore")
        import google.generativeai as genai
    SDK_VIEJO = True
except ImportError:
    SDK_VIEJO = False
GEMINI_DISPONIBLE = SDK_NUEVO or SDK_VIEJO


# ============ RATE LIMITING ============
PAUSAS_POR_MODELO = {
    "gemini-2.5-flash": 7,
    "gemini-flash-latest": 7,
    "gemini-3-flash": 13,
    "gemini-3.5-flash": 13,
    "gemini-3.1-flash-lite": 5,
}
PAUSA_DEFAULT = 8


# ============ PROMPTS POR DEFECTO ============
SYSTEM_PROMPT_DEFAULT = """Eres instructor experto en diseño curricular y pedagogía del SENA (Colombia), y conoces la Guía de Desarrollo Curricular GFPI-G-060.
Ayudas a diseñar planeaciones pedagógicas (GFPI-F-134) y guías de aprendizaje (GFPI-F-135).

Reglas obligatorias:
1. El contexto lo dan el PROGRAMA y el PROYECTO FORMATIVO que se te entregan. Contextualiza solo con eso: no traigas empresas, sectores ni casos que no aparezcan en esos datos, y no inventes empresas ficticias.
2. Lenguaje claro y concreto, adecuado al nivel del programa (técnico o tecnólogo).
3. Actividades de aprendizaje con la estructura VERBO (infinitivo) + OBJETO + CONDICIÓN (V+O+C): una sola oración, concisa y precisa.
4. Saberes y criterios de evaluación NUNCA se redactan: vienen del diseño curricular.
5. Ambiente de formación: el que indique el instructor (por defecto, Polivalente).
6. Materiales de formación: SOLO consumibles (marcadores, papel, papelógrafos, cinta, fotocopias, etc.). Nunca software, equipos ni plataformas.
7. Cuando se te pida un campo específico, responde SOLO con el contenido de ese campo, sin encabezados ni etiquetas.

Responde SIEMPRE en español colombiano."""


PROMPT_PRESENTACION_DEFAULT = """Escribe la PRESENTACIÓN motivadora al aprendiz para esta guía (2 a 3 párrafos, tono cercano):

Programa: {programa}
Proyecto formativo: {proyecto_formativo}
Competencia: {competencia}
Duración: {duracion}
RAPs de la competencia:
{raps_formateados}

La presentación debe:
- Ubicar al aprendiz en el contexto real del proyecto formativo
- Explicar POR QUÉ importa este conocimiento en su futuro trabajo
- Motivar el compromiso con las actividades sin ser paternalista
- NO incluir títulos ni encabezados, solo el texto corrido de los párrafos
- Separar párrafos con una línea en blanco"""


PROMPT_ACTIVIDAD_DEFAULT = """Diseña la ACTIVIDAD {key} de esta guía SENA:

Fase de la guía: {titulo_fase}

Programa: {programa}
Proyecto formativo: {proyecto_formativo}
Competencia: {competencia}
RAPs:
{raps_formateados}
{contexto_previo}

Genera los siguientes 8 campos, respondiendo ÚNICAMENTE en formato JSON válido (sin markdown, sin ```json):
{{
  "descripcion": "descripción detallada de la actividad, mínimo 3 oraciones, incluir qué hace el aprendiz paso a paso",
  "ambiente": "ambiente físico requerido (aula, computadores, taller, etc.)",
  "estrategias": "estrategias didácticas activas (lluvia de ideas, ABP, simulación, etc.)",
  "materiales": "materiales de formación necesarios",
  "apoyo": "material de apoyo específico (presentaciones, simuladores, videos, guías)",
  "evidencias": "evidencias de aprendizaje que produce el aprendiz (solo para 3.3 y 3.4, vacío en 3.1 y 3.2)",
  "instrumentos": "instrumentos de evaluación (rúbrica, lista de chequeo) — solo para 3.3 y 3.4",
  "duracion": "duración en horas"
}}

Reglas:
- Todo debe ser específico al contexto del proyecto formativo
- Para actividad 3.3: incluir ejercicios cuantitativos con datos realistas del sector
- Para actividad 3.4: la evidencia debe ser un producto individual del aprendiz
- Si el campo evidencias/instrumentos no aplica (actividades 3.1 y 3.2), déjalos como string vacío
- Nivel básico de los aprendices — instrucciones claras, paso a paso"""


PROMPT_GLOSARIO_DEFAULT = """Genera un GLOSARIO técnico de {n_terminos} términos clave para esta guía SENA:

Competencia: {competencia}
Presentación: {presentacion_corta}
Actividades:
{actividades_resumen}

Responde ÚNICAMENTE en JSON válido (sin markdown):
[
  ["Término (unidad):", "Definición corta y clara"],
  ["Otro término:", "Definición..."]
]

Reglas:
- Los términos deben ser los conceptos clave que el aprendiz DEBE conocer
- Definiciones en lenguaje sencillo, máximo 2 oraciones
- Incluir unidades del SI cuando aplique (kg, N, m/s², etc.)
- Ordenar del más fundamental al más específico"""


PROMPT_REFERENTES_DEFAULT = """Genera 5-6 REFERENTES BIBLIOGRÁFICOS para esta guía SENA:

Competencia: {competencia}
Programa: {programa}

Responde ÚNICAMENTE en JSON válido (sin markdown), un array de strings:
["Referencia 1 completa", "Referencia 2 completa", ...]

Incluye:
- Al menos 1 libro clásico del área (Serway, Hewitt, o similar según la competencia)
- Al menos 1 recurso web gratuito (PhET Simulations, Phyphox, o similar)
- SENA (guía curricular de la competencia o SOFIA Plus)
- Otros referentes verificables

Formato APA simplificado."""


# NUEVO: Prompt para planeación pedagógica (formato GFPI-F-134)
PROMPT_PLANEACION_DEFAULT = """Eres un experto en pedagogía SENA. Diseña los campos técnicos de UNA fila de la PLANEACIÓN PEDAGÓGICA (formato oficial GFPI-F-134) para la competencia indicada, en el contexto del proyecto formativo dado.

DATOS DE ENTRADA:
- Programa: {programa}
- Fase del proyecto: {fase}
- Proyecto formativo: {proyecto_formativo}
- Actividad del proyecto formativo: {actividad_proyecto}
- Competencia: {competencia}
- Resultados de aprendizaje asociados:
{raps_formateados}

TAREA CRÍTICA: Responde ÚNICAMENTE con un objeto JSON válido. Sin markdown, sin ```json, sin explicaciones antes ni después. Solo el objeto JSON.

FORMATO EXACTO DEL JSON A DEVOLVER (todos los campos son OBLIGATORIOS y deben tener contenido concreto, NUNCA vacíos):

{{
  "saberes_conceptos": "3-5 conceptos y principios que el aprendiz debe saber, separados por comas. Ejemplo: 'Fuerza, masa, peso, fricción, Leyes de Newton, Sistema Internacional de Unidades'",
  "saberes_proceso": "3-5 habilidades y procesos que el aprendiz debe saber HACER, separadas por comas. Ejemplo: 'Identificar principios físicos en operaciones logísticas, aplicar fórmulas F=m·a, analizar cambios físicos en procesos productivos'",
  "criterios_evaluacion": "3-5 criterios de evaluación concretos y medibles. Cada criterio empieza con verbo en tercera persona. Ejemplo: 'Identifica principios físicos en situaciones reales del sector productivo. Resuelve ejercicios cuantitativos aplicando F=m·a con procedimiento y unidades correctas. Propone acciones de mejora aplicables al contexto del proyecto formativo'",
  "actividades_aprendizaje": "UNA oración V+O+C: verbo en infinitivo + objeto + condición (15 a 35 palabras).",
  "descripcion_evidencia": "Descripción concreta de las evidencias que produce el aprendiz. Ejemplo: 'Guía autónoma resuelta con procedimiento completo, quiz completado con puntaje mínimo del 80%, video experimental de 3-5 minutos, propuesta escrita de mejora aplicable al contexto RA-04'",
  "estrategias_didacticas": "Estrategias didácticas activas. Ejemplo: 'Aprendizaje Basado en Problemas (ABP), simulación PhET, exposición dialogada, aprendizaje experiencial'",
  "ambiente": "Polivalente",
  "materiales": "SOLO consumibles. Ejemplo: 'Marcadores borrables, papel bond, papelógrafos, cinta'",
  "horas_directas": 48,
  "horas_independientes": 48
}}

REGLAS OBLIGATORIAS:
1. Todos los 10 campos deben tener contenido concreto y no vacío
2. Los ejemplos deben estar contextualizados al programa y proyecto formativo dados
3. horas_directas y horas_independientes son números enteros, no strings
4. No uses comillas dobles anidadas sin escapar en los valores string
5. Devuelve SOLO el JSON, nada más"""


# Prompt POR RAP para la planeación pedagógica GFPI-F-134 (una fila Excel = un RAP)
PROMPT_PLANEACION_RAP_DEFAULT = """Eres experto en diseño curricular y pedagogía del SENA (Colombia). Diligencia la fila de la PLANEACIÓN PEDAGÓGICA (formato GFPI-F-134) correspondiente a UN resultado de aprendizaje.

CONTEXTO:
- Programa: {programa}
- Proyecto formativo: {proyecto_formativo}
- Fase: {fase}
- Actividad del proyecto: {actividad_proyecto}
- Competencia: {competencia}
- RESULTADO DE APRENDIZAJE A PLANEAR: {rap}
- Otros RAP de la misma competencia (NO los desarrolles aquí): {otros_raps}
{bloque_oficial}
Responde ÚNICAMENTE con un objeto JSON válido (sin markdown ni texto adicional):
{{
  "saberes_conceptos": ["..."],
  "saberes_proceso": ["..."],
  "criterios_evaluacion": ["..."],
  "actividades": [
    {{
      "actividades_aprendizaje": "UNA oración V+O+C: VERBO en infinitivo + OBJETO + CONDICIÓN (15 a 35 palabras). Ej.: 'Clasificar los inventarios de la bodega según el método ABC y las políticas de la organización.'",
      "descripcion_evidencia": "Inicia con 'Evidencia de Conocimiento:', 'Evidencia de Desempeño:' o 'Evidencia de Producto:' (puede combinar) y describe el entregable verificable (25-50 palabras).",
      "estrategias_didacticas": "1 o 2 estrategias activas con el formato 'Nombre: cómo se aplica (individual o en equipo).' (ABP, estudio de caso, juego de roles, aula invertida, simulación, proyecto, etc.)",
      "materiales": "SOLO consumibles separados por comas (marcadores, papel bond, papelógrafos, cinta, fotocopias…). Nada de software ni equipos."
    }}
  ]
}}

REGLAS:
1. {regla_saberes}
2. La actividad y la evidencia deben desarrollar SOLO este RAP y ser coherentes con la actividad del proyecto.
3. Contextualiza SOLO con el programa y el proyecto formativo dados; no traigas empresas ni casos externos y no inventes empresas ficticias.
4. No incluyas horas ni ambiente: los define el instructor (ambiente: Polivalente).
5. "actividades" debe tener EXACTAMENTE {n_aa} actividad(es) de aprendizaje para este RAP, cada una en forma V+O+C (GFPI-G-060). Si son varias, que sean distintas y cubran las áreas de desarrollo cognitiva (saber), procedimental (hacer) y valorativa-actitudinal (ser), cada una con su propia evidencia."""


PROMPTS_DEFAULT = {
    "system": SYSTEM_PROMPT_DEFAULT,
    "presentacion": PROMPT_PRESENTACION_DEFAULT,
    "actividad": PROMPT_ACTIVIDAD_DEFAULT,
    "glosario": PROMPT_GLOSARIO_DEFAULT,
    "referentes": PROMPT_REFERENTES_DEFAULT,
    "planeacion": PROMPT_PLANEACION_DEFAULT,
    "planeacion_rap": PROMPT_PLANEACION_RAP_DEFAULT,
}


NO_CONSUMIBLES = ("software", "computador", "portátil", "portatil", "video beam", "videobeam",
                  "proyector", "televisor", "tablet", "celular", "impresora", "simulador", "plataforma",
                  "internet", "erp", "aplicativo", "app ", "programa ", "licencia", "equipo de cómputo",
                  "herramienta digital", "excel", "power bi", "wms")


def solo_consumibles(texto: str) -> str:
    """Materiales de formación = solo consumibles. Quita software, equipos y plataformas."""
    partes = [x.strip() for x in re.split(r"[,;\n]+", str(texto or "")) if x.strip()]
    ok = [x for x in partes if not any(t in (x.lower() + " ") for t in NO_CONSUMIBLES)]
    return ", ".join(ok)


EMPRESAS_EXTERNAS = ("cerrejón", "cerrejon", "carbones del", "drummond", "ecopetrol", "puerto brisa",
                     "empresas mineras", "empresa minera", "sector minero")


def problemas_voc(texto: str, contexto: str = "") -> list:
    """Revisa que una actividad de aprendizaje cumpla V+O+C (GFPI-G-060) y no traiga
    empresas que no estén en el programa / proyecto formativo."""
    t = str(texto or "").strip()
    probs = []
    if not t:
        return ["vacía"]
    palabras = t.split()
    primera = re.sub(r"[^a-záéíóúñ]", "", palabras[0].lower())
    if not re.search(r"(ar|er|ir)$", primera):
        probs.append("no inicia con verbo en infinitivo")
    if len(palabras) > 40:
        probs.append(f"muy larga ({len(palabras)} palabras; máximo 40)")
    if len([x for x in re.split(r"(?<=[.!?])\s+", t) if x.strip()]) > 1:
        probs.append("tiene más de una oración")
    if re.search(r"\busted\b|\bustedes\b|\btú\b", t.lower()):
        probs.append("habla al aprendiz (usted/tú)")
    ctx = str(contexto or "").lower()
    for e in EMPRESAS_EXTERNAS:
        if e in t.lower() and e not in ctx:
            probs.append(f"menciona «{e}», que no está en el programa ni en el proyecto")
    return probs


def recortar_voc(texto: str, contexto: str = "") -> str:
    """Último recurso: primera oración, sin los incisos que nombran empresas ajenas al
    programa/proyecto y con máximo ~40 palabras (cortando en una coma)."""
    t = re.split(r"(?<=[.!?])\s+", str(texto or "").strip())[0].rstrip(". ")
    ctx = str(contexto or "").lower()
    partes = [x for x in t.split(",") if not any(e in x.lower() and e not in ctx for e in EMPRESAS_EXTERNAS)]
    t = ",".join(partes).strip(" ,")
    while len(t.split()) > 40 and "," in t:
        t = t.rsplit(",", 1)[0]
    return t.strip(" ,") + "."

# ============ GESTIÓN DE PROMPTS PERSONALIZADOS ============
_MARCAS_PROMPT_VIEJO = ("como anclaje real", "ProfeNaturales SENA")


def cargar_prompts(prompts_file: Path) -> dict:
    if prompts_file.exists():
        try:
            custom = json.loads(prompts_file.read_text(encoding="utf-8"))
            # el prompt de sistema anterior anclaba todo a una empresa: se reemplaza por el nuevo
            if any(m in str(custom.get("system", "")) for m in _MARCAS_PROMPT_VIEJO):
                custom.pop("system", None)
            # La página de prompts guarda TODO el diccionario: así quedaban congeladas versiones
            # viejas (párrafos largos, empresa fija). Para planeación se exige la versión V+O+C.
            for clave in ("system", "planeacion_rap", "planeacion"):
                if clave in custom and "V+O+C" not in str(custom[clave]):
                    custom.pop(clave, None)
            return {**PROMPTS_DEFAULT, **custom}
        except Exception:
            pass
    return dict(PROMPTS_DEFAULT)


def guardar_prompts(prompts_file: Path, prompts: dict):
    prompts_file.write_text(json.dumps(prompts, indent=2, ensure_ascii=False), encoding="utf-8")


def restablecer_prompt(prompts_file: Path, clave: str) -> dict:
    prompts = cargar_prompts(prompts_file)
    prompts[clave] = PROMPTS_DEFAULT[clave]
    guardar_prompts(prompts_file, prompts)
    return prompts


# ============ CLIENTE GEMINI ============
class GeminiCliente:
    """Cliente Gemini con prompts editables, instrucciones extra y pausas automáticas."""

    TITULOS_FASE = {
        "3.1": "Reflexión inicial (activación de saberes previos, sin dar aún el concepto)",
        "3.2": "Contextualización (introducción del concepto clave con analogías del sector)",
        "3.3": "Apropiación (práctica: quizzes, simuladores, resolución de problemas cuantitativos)",
        "3.4": "Transferencia (aplicación al contexto laboral real del aprendiz, evidencia individual)",
    }

    def __init__(self, api_key: str, modelo: str = "gemini-2.5-flash",
                 prompts: Optional[dict] = None):
        if not GEMINI_DISPONIBLE:
            raise ImportError("Falta la librería de Gemini. Ejecuta: pip install google-genai")
        if not api_key or not api_key.strip():
            raise ValueError("Se requiere una API key de Gemini. Obtenla gratis en https://aistudio.google.com/apikey")

        self.prompts = prompts or dict(PROMPTS_DEFAULT)
        self.modelo_nombre = modelo
        self.pausa_s = PAUSAS_POR_MODELO.get(modelo, PAUSA_DEFAULT)
        self._ultima_llamada_ts = 0.0

        self._system = self.prompts.get("system", SYSTEM_PROMPT_DEFAULT)
        if SDK_NUEVO:
            self._cliente = genai_nuevo.Client(api_key=api_key.strip())
            self.modelo = None
        else:
            genai.configure(api_key=api_key.strip())
            self._cliente = None
            self.modelo = genai.GenerativeModel(model_name=modelo, system_instruction=self._system)

    # ---------- Métodos públicos ----------
    def generar_presentacion(self, datos: dict, instrucciones_extra: str = "") -> str:
        prompt = self.prompts.get("presentacion", PROMPT_PRESENTACION_DEFAULT).format(
            programa=datos.get("programa", ""),
            proyecto_formativo=datos.get("proyecto_formativo", ""),
            competencia=datos.get("competencia", ""),
            duracion=datos.get("duracion", ""),
            raps_formateados=self._formatear_raps(datos.get("raps", [])),
        )
        prompt = self._aplicar_extra(prompt, instrucciones_extra)
        return self._llamar(prompt)

    def generar_actividad(self, key: str, datos: dict,
                          actividades_previas: dict = None,
                          instrucciones_extra: str = "") -> dict:
        contexto_previo = ""
        if actividades_previas:
            for k, v in actividades_previas.items():
                if k != key and isinstance(v, dict) and v.get("descripcion"):
                    contexto_previo += f"\nActividad {k} ya diseñada: {v.get('descripcion', '')[:200]}"

        prompt = self.prompts.get("actividad", PROMPT_ACTIVIDAD_DEFAULT).format(
            key=key,
            titulo_fase=self.TITULOS_FASE.get(key, ""),
            programa=datos.get("programa", ""),
            proyecto_formativo=datos.get("proyecto_formativo", ""),
            competencia=datos.get("competencia", ""),
            raps_formateados=self._formatear_raps(datos.get("raps", [])),
            contexto_previo=contexto_previo,
        )
        prompt = self._aplicar_extra(prompt, instrucciones_extra)
        respuesta = self._llamar(prompt)
        return self._parsear_json(respuesta)

    def generar_glosario(self, datos: dict, n_terminos: int = 8,
                         instrucciones_extra: str = "") -> list:
        prompt = self.prompts.get("glosario", PROMPT_GLOSARIO_DEFAULT).format(
            n_terminos=n_terminos,
            competencia=datos.get("competencia", ""),
            presentacion_corta=datos.get("presentacion", "")[:400],
            actividades_resumen=self._resumir_actividades(datos.get("actividades", {})),
        )
        prompt = self._aplicar_extra(prompt, instrucciones_extra)
        respuesta = self._llamar(prompt)
        data = self._parsear_json(respuesta)
        if isinstance(data, list):
            return [(item[0], item[1]) for item in data if len(item) >= 2]
        return []

    def generar_referentes(self, datos: dict, instrucciones_extra: str = "") -> list:
        prompt = self.prompts.get("referentes", PROMPT_REFERENTES_DEFAULT).format(
            competencia=datos.get("competencia", ""),
            programa=datos.get("programa", ""),
        )
        prompt = self._aplicar_extra(prompt, instrucciones_extra)
        respuesta = self._llamar(prompt)
        data = self._parsear_json(respuesta)
        return data if isinstance(data, list) else []

    def generar_todo(self, datos_iniciales: dict, instrucciones_extra: dict = None) -> dict:
        extra = instrucciones_extra or {}
        datos = dict(datos_iniciales)
        datos["presentacion"] = self.generar_presentacion(
            datos, instrucciones_extra=extra.get("presentacion", ""))
        actividades = {}
        for key in ["3.1", "3.2", "3.3", "3.4"]:
            actividades[key] = self.generar_actividad(
                key, datos, actividades_previas=actividades,
                instrucciones_extra=extra.get(key, ""))
        datos["actividades"] = actividades
        datos["glosario"] = self.generar_glosario(datos, instrucciones_extra=extra.get("glosario", ""))
        datos["referentes"] = self.generar_referentes(datos, instrucciones_extra=extra.get("referentes", ""))
        return datos

    # ---------- NUEVO: Método para planeación pedagógica ----------
    def generar_planeacion(self, datos: dict, instrucciones_extra: str = "") -> dict:
        """Genera los campos técnicos de UNA fila de la planeación pedagógica.
        Recibe: programa, fase, proyecto_formativo, actividad_proyecto, competencia, raps.
        Opcionalmente:
          - guias_relacionadas (list): guías ya generadas para esta competencia
          - saberes_conceptos_oficiales, saberes_proceso_oficiales,
            criterios_evaluacion_oficiales (list): del diseño curricular SENA
        Devuelve dict con: saberes_conceptos, saberes_proceso, criterios_evaluacion,
                          actividades_aprendizaje, descripcion_evidencia, estrategias_didacticas,
                          ambiente, materiales, horas_directas, horas_independientes.
        """
        prompt = self.prompts.get("planeacion", PROMPT_PLANEACION_DEFAULT).format(
            programa=datos.get("programa", ""),
            fase=datos.get("fase", ""),
            proyecto_formativo=datos.get("proyecto_formativo", ""),
            actividad_proyecto=datos.get("actividad_proyecto", ""),
            competencia=datos.get("competencia", ""),
            raps_formateados=self._formatear_raps(datos.get("raps", [])),
        )

        # ★ Si vienen saberes/criterios OFICIALES del diseño curricular, agregarlos como contexto
        # y decirle a la IA que los respete verbatim (no los reinvente)
        saberes_c_of = datos.get("saberes_conceptos_oficiales", [])
        saberes_p_of = datos.get("saberes_proceso_oficiales", [])
        criterios_of = datos.get("criterios_evaluacion_oficiales", [])

        if saberes_c_of or saberes_p_of or criterios_of:
            contexto_oficial = "\n\nCONTEXTO OFICIAL — DISEÑO CURRICULAR SENA:\n"
            contexto_oficial += ("Esta competencia tiene un diseño curricular oficial cargado. "
                                 "Los siguientes campos YA ESTÁN DEFINIDOS por el SENA y NO deben "
                                 "ser inventados. Devuélvelos EXACTAMENTE como aparecen aquí:\n\n")
            if saberes_c_of:
                contexto_oficial += "SABERES DE CONCEPTOS Y PRINCIPIOS (oficial):\n"
                for s in saberes_c_of:
                    contexto_oficial += f"  • {s}\n"
                contexto_oficial += "\n"
            if saberes_p_of:
                contexto_oficial += "SABERES DE PROCESO (oficial):\n"
                for s in saberes_p_of:
                    contexto_oficial += f"  • {s}\n"
                contexto_oficial += "\n"
            if criterios_of:
                contexto_oficial += "CRITERIOS DE EVALUACIÓN (oficial):\n"
                for c in criterios_of:
                    contexto_oficial += f"  • {c}\n"
                contexto_oficial += "\n"
            contexto_oficial += ("Los campos 'saberes_conceptos', 'saberes_proceso' y 'criterios_evaluacion' "
                                 "DEBEN devolverse tal cual aparecen arriba, unidos con saltos de línea "
                                 "y con '• ' al inicio de cada uno. Genera con creatividad los demás "
                                 "campos (actividades_aprendizaje, descripcion_evidencia, estrategias_didacticas, "
                                 "ambiente, materiales) alineándolos con estos saberes oficiales.")
            prompt += contexto_oficial

        # Alineación con guías de aprendizaje ya generadas (si hay)
        guias_prev = datos.get("guias_relacionadas", [])
        if guias_prev:
            contexto_guias = "\n\nCONTEXTO ADICIONAL — GUÍAS DE APRENDIZAJE YA GENERADAS PARA ESTA COMPETENCIA:\n"
            contexto_guias += ("El instructor ya ha diseñado las siguientes guías de aprendizaje "
                               "para esta competencia. Las 'actividades_aprendizaje' y las "
                               "'descripcion_evidencia' que generes DEBEN estar alineadas con estas guías, "
                               "haciendo referencia a las actividades 3.1 (Reflexión), 3.2 "
                               "(Contextualización), 3.3 (Apropiación) y 3.4 (Transferencia) "
                               "que están en cada guía.\n\n")
            for i, g in enumerate(guias_prev, 1):
                contexto_guias += (f"Guía {i}: fase='{g.get('fase', '')}', "
                                   f"RAP focal='{g.get('rap_focal', '')}', "
                                   f"fecha={g.get('fecha', '')}\n")
            contexto_guias += ("\nEn 'actividades_aprendizaje' menciona explícitamente las "
                               "actividades 3.1/3.2/3.3/3.4 de las guías. En 'descripcion_evidencia' "
                               "referencia las evidencias que producen esas guías (guía autónoma "
                               "resuelta, quiz, video experimental, propuesta de mejora).")
            prompt += contexto_guias

        prompt = self._aplicar_extra(prompt, instrucciones_extra)
        respuesta = self._llamar(prompt)
        return self._parsear_json(respuesta)

    # ---------- Redistribución de saberes/criterios del diseño entre RAP (por índices) ----------
    def distribuir_saberes(self, competencia: str, raps: list, listas: dict) -> list:
        """La IA SOLO elige números de las listas oficiales: no puede escribir texto, así que
        no puede inventar. Devuelve la lista cruda [{"rap": n, "conceptos": [..], ...}]."""
        numerar = lambda xs: "\n".join(f"  [{i}] {x}" for i, x in enumerate(xs, 1)) or "  (sin datos)"
        lista_raps = "\n".join(f"  RAP {j}. {r}" for j, r in enumerate(raps, 1))
        prompt = f"""Eres experto en diseño curricular del SENA (Colombia). Debes REDISTRIBUIR entre los
resultados de aprendizaje (RAP) de una competencia los saberes y criterios que YA trae el diseño
curricular oficial. No redactas nada: solo asignas números.

COMPETENCIA: {competencia}

RESULTADOS DE APRENDIZAJE:
{lista_raps}

SABERES DE CONCEPTOS Y PRINCIPIOS (diseño curricular):
{numerar(listas.get("conceptos", []))}

SABERES DE PROCESO (diseño curricular):
{numerar(listas.get("proceso", []))}

CRITERIOS DE EVALUACIÓN (diseño curricular):
{numerar(listas.get("criterios", []))}

REGLAS:
1. Asigna a cada RAP los ítems cuyo TEMA corresponde a ese RAP (p. ej. un RAP de inventarios
   recibe los saberes y criterios de inventarios).
2. TODO ítem de las tres listas debe quedar asignado al menos a un RAP. Un ítem puede ir a
   varios RAP si realmente aplica a ambos, pero evita repetirlo sin necesidad.
3. Cada RAP debe recibir al menos un criterio de evaluación y al menos un saber.
4. Usa SOLO los números de las listas. Prohibido escribir texto o crear ítems.

Responde ÚNICAMENTE con JSON válido, sin markdown:
{{"asignacion": [{{"rap": 1, "conceptos": [1, 4], "proceso": [2], "criterios": [1]}}]}}"""
        res = self._parsear_json(self._llamar(prompt))
        if isinstance(res, dict):
            res = res.get("asignacion", [])
        return res if isinstance(res, list) else []

    # ---------- Planeación POR RAP (GFPI-F-134 según referencia oficial) ----------
    def generar_planeacion_rap(self, datos: dict, instrucciones_extra: str = "") -> dict:
        """Genera los campos de UNA fila de la planeación (un RAP).

        Si llegan saberes/criterios OFICIALES (diseño curricular), la IA solo puede
        SELECCIONAR de esas listas; luego se filtra lo devuelto y se descarta cualquier ítem
        que no coincida textualmente con el oficial (nunca se inventan saberes ni criterios).
        Devuelve dict con listas → ya convertidas a texto con saltos de línea.
        """
        of_c = [x for x in datos.get("saberes_conceptos_oficiales", []) if x]
        of_p = [x for x in datos.get("saberes_proceso_oficiales", []) if x]
        of_cr = [x for x in datos.get("criterios_evaluacion_oficiales", []) if x]
        hay_oficial = bool(of_c or of_p or of_cr)
        asignados = datos.get("saberes_asignados") or {}
        if asignados:
            bloque = ("\nSABERES Y CRITERIOS DEL DISEÑO CURRICULAR YA ASIGNADOS A ESTE RAP "
                      "(base obligatoria de las actividades):\n"
                      f"CONCEPTOS:\n{asignados.get('saberes_conceptos', '') or '(ninguno)'}\n"
                      f"PROCESO:\n{asignados.get('saberes_proceso', '') or '(ninguno)'}\n"
                      f"CRITERIOS:\n{asignados.get('criterios_evaluacion', '') or '(ninguno)'}\n")
            regla = ("Los saberes y criterios ya están definidos (arriba): devuelve "
                     "saberes_conceptos, saberes_proceso y criterios_evaluacion como listas VACÍAS y "
                     "diseña las actividades y evidencias para que cubran esos saberes y criterios.")
        elif hay_oficial:
            numerar = lambda xs: "\n".join(f"  [{i}] {x}" for i, x in enumerate(xs, 1)) or "  (sin datos)"
            bloque = ("\nLISTAS OFICIALES DEL DISEÑO CURRICULAR (SENA). Son de TODA la competencia:\n"
                      f"SABERES DE CONCEPTOS Y PRINCIPIOS:\n{numerar(of_c)}\n"
                      f"SABERES DE PROCESO:\n{numerar(of_p)}\n"
                      f"CRITERIOS DE EVALUACIÓN:\n{numerar(of_cr)}\n")
            regla = ("En saberes_conceptos, saberes_proceso y criterios_evaluacion devuelve SOLO los "
                     "ítems de las listas oficiales que correspondan a ESTE RAP, copiados EXACTAMENTE "
                     "(mismo texto, sin el número). Está PROHIBIDO redactar ítems nuevos.")
        else:
            bloque = ""
            regla = ("NO hay diseño curricular cargado: está PROHIBIDO redactar saberes o criterios. "
                     "Devuelve saberes_conceptos, saberes_proceso y criterios_evaluacion como listas "
                     "VACÍAS y diseña solo las actividades.")
        raps = [r for r in datos.get("raps", []) if r]
        otros = [r for r in raps if r.strip() != datos.get("rap", "").strip()]
        prompt = self.prompts.get("planeacion_rap", PROMPT_PLANEACION_RAP_DEFAULT).format(
            programa=datos.get("programa", ""), proyecto_formativo=datos.get("proyecto_formativo", ""),
            fase=datos.get("fase", ""), actividad_proyecto=datos.get("actividad_proyecto", ""),
            competencia=datos.get("competencia", ""), rap=datos.get("rap", ""),
            otros_raps="; ".join(otros) or "(ninguno)", bloque_oficial=bloque, regla_saberes=regla,
            n_aa=max(1, int(datos.get("n_aa", 1) or 1)))
        prompt = self._aplicar_extra(prompt, instrucciones_extra)
        res = self._parsear_json(self._llamar(prompt))
        if not isinstance(res, dict):
            raise RuntimeError("La IA no devolvió un objeto JSON.")

        contexto_txt = " ".join(str(datos.get(k, "")) for k in
                                ("programa", "proyecto_formativo", "actividad_proyecto", "competencia", "rap"))
        def _fallas(r):
            aas = r.get("actividades") if isinstance(r.get("actividades"), list) else [r]
            out = []
            for n, a in enumerate(aas, 1):
                if isinstance(a, dict):
                    out += [f"actividad {n}: {p}" for p in problemas_voc(a.get("actividades_aprendizaje", ""), contexto_txt)]
            return out
        fallas = _fallas(res)
        if fallas:                                   # 1 reintento diciéndole exactamente qué corregir
            correccion = (prompt + "\n\nTU RESPUESTA ANTERIOR NO CUMPLE:\n- " + "\n- ".join(fallas) +
                          "\nCorrige: cada actividad de aprendizaje es UNA sola oración V+O+C (verbo en "
                          "infinitivo + objeto + condición), máximo 35 palabras, sin hablarle al aprendiz y "
                          "sin empresas que no estén en el programa o en el proyecto formativo. "
                          "Devuelve el JSON completo otra vez.")
            try:
                res2 = self._parsear_json(self._llamar(correccion))
                if isinstance(res2, dict) and len(_fallas(res2)) < len(fallas):
                    res = res2
            except Exception:
                pass

        pares = (("saberes_conceptos", of_c), ("saberes_proceso", of_p), ("criterios_evaluacion", of_cr))
        for campo, oficial in pares:
            items = res.get(campo) or []
            if isinstance(items, str):
                items = [x for x in re.split(r"\n+|•", items) if x.strip()]
            items = [re.sub(r"^\s*(\[\d+\]|\d+[.)-])\s*", "", str(x)).strip(" •-\t") for x in items]
            if asignados:
                items = []                              # ya vienen del diseño: no se tocan
            elif oficial:
                items = self._filtrar_verbatim(items, oficial)
            else:
                items = []                              # sin diseño: nunca se inventan
            res[campo] = "\n\n".join(items)
        # Actividades de aprendizaje (1..N por RAP). Acepta también el formato plano anterior.
        campos_aa = ("actividades_aprendizaje", "descripcion_evidencia", "estrategias_didacticas",
                     "ambiente", "materiales")
        aas = res.get("actividades")
        if not isinstance(aas, list) or not aas:
            aas = [{c: res.get(c, "") for c in campos_aa}]
        limpio = []
        for a in aas:
            if not isinstance(a, dict):
                a = {"actividades_aprendizaje": str(a)}
            limpio.append({c: ("\n".join(a.get(c)) if isinstance(a.get(c), list)
                               else str(a.get(c) or "").strip()) for c in campos_aa})
        for a in limpio:
            if problemas_voc(a.get("actividades_aprendizaje", ""), contexto_txt):
                a["actividades_aprendizaje"] = recortar_voc(a.get("actividades_aprendizaje", ""), contexto_txt)
            a["ambiente"] = ""                       # lo define el instructor (Polivalente)
            a["materiales"] = solo_consumibles(a.get("materiales", ""))
        n_aa = max(1, int(datos.get("n_aa", 1) or 1))
        limpio = (limpio + [dict.fromkeys(campos_aa, "") for _ in range(n_aa)])[:n_aa]
        res["actividades"] = limpio
        for c in campos_aa:                      # compatibilidad: la 1.ª AA también en plano
            res[c] = limpio[0][c]
        res["_oficial"] = hay_oficial
        return res

    @staticmethod
    def _filtrar_verbatim(items: list, oficiales: list) -> list:
        """Mapea cada ítem de la IA al texto OFICIAL exacto (tolerando mayúsculas/espacios/
        puntuación final). Lo que no coincide con ninguno se descarta."""
        norm = lambda t: re.sub(r"[\s.;:,]+", " ", str(t)).strip().upper()
        mapa = {norm(o): o for o in oficiales}
        salida = []
        for it in items:
            k = norm(it)
            elegido = mapa.get(k)
            if not elegido:  # coincidencia por prefijo (IA que recorta el final)
                elegido = next((o for kk, o in mapa.items() if len(k) > 25 and
                                (kk.startswith(k) or k.startswith(kk))), None)
            if elegido and elegido not in salida:
                salida.append(elegido)
        return salida

    # ---------- Guía desde la planeación: redactar un momento con una técnica del atlas ----------
    def redactar_momento(self, momento: str, nombre_momento: str, proposito: str, ctx: dict,
                         tecnicas: list, aas: list, instrucciones_extra: str = "") -> dict:
        """Redacta 'Descripción de la actividad' y 'Material de apoyo' de un momento de la guía
        GFPI-F-135, aplicando la(s) técnica(s) elegida(s) del Atlas y SIN cambiar lo que ya
        fijó la planeación (RAP, actividades V+O+C, evidencias)."""
        bloque_tec = "\n".join(
            f"- {t['name']}: {t['description']} Por qué en este momento: {t['why']} "
            f"Ejemplo orientador (adáptalo, no lo copies): {t['example']} Evidencia orientadora: {t['evidence']}"
            for t in tecnicas) or "- (sin técnica elegida: propón una activa coherente con el propósito)"
        bloque_aa = "\n".join(f"- {a['actividad']} → Evidencia: {a['evidencia']}" for a in aas if a.get("actividad"))
        extra_momento, palabras, campo_ev = "", "80-160", ""
        if momento == "3.2":
            extra_momento = ("ESTE MOMENTO ES GENERAL: enmarca el concepto global de TODA la competencia y de sus "
                             "RAP (no de una actividad puntual). Indaga saberes previos con preguntas abiertas.")
        elif momento == "3.4":
            extra_momento = ("ESTE MOMENTO ES UNA ACTIVIDAD INTEGRADORA DEL APRENDIZ: plantea una situación nueva y "
                             "concreta del contexto del programa (p. ej. un estudio de caso con datos) que obligue a "
                             "aplicar TODOS los RAP listados; el aprendiz debe demostrar lo aprendido en toda la "
                             "competencia, justificar decisiones y entregar una evidencia de producto.")
            palabras = "140-260"
            campo_ev = (',\n  "evidencia": "Evidencia de producto: <qué entrega el aprendiz como resultado de la '
                        'actividad integradora, en una frase>"')
        prompt = f"""Redacta el momento {momento} «{nombre_momento}» de una GUÍA DE APRENDIZAJE SENA (GFPI-F-135).

PROPÓSITO DEL MOMENTO (GFPI-G-060): {proposito}

DATOS DE LA PLANEACIÓN (no los cambies):
- Programa: {ctx.get('programa', '')}
- Proyecto formativo: {ctx.get('proyecto_formativo', '')}
- Fase: {ctx.get('fase', '')} · Actividad del proyecto: {ctx.get('actividad_proyecto', '')}
- Competencia: {ctx.get('competencia', '')}
- Resultados de aprendizaje: {"; ".join(ctx.get('raps', []))}
- Saberes del diseño curricular para estos RAP: {"; ".join(ctx.get('saberes', [])[:12])}
{("- Actividades de aprendizaje de la planeación (V+O+C) que este momento debe desarrollar:" + chr(10) + bloque_aa) if bloque_aa else ""}

TÉCNICA(S) DIDÁCTICA(S) ELEGIDA(S) POR EL INSTRUCTOR (Atlas didáctico, UnADM):
{bloque_tec}

{extra_momento}
Responde ÚNICAMENTE con JSON válido, sin markdown:
{{"descripcion": "Consigna dirigida al aprendiz en pasos numerados (1., 2., 3. ...), {palabras} palabras, que aplica la técnica elegida al contexto del programa y del proyecto; indica si el trabajo es individual o en equipo y qué entrega.",
  "apoyo": "Material de apoyo (lecturas, ejemplos, formatos o casos) en una línea."{campo_ev}}}

REGLAS:
1. Usa SOLO el contexto del programa y del proyecto formativo; no nombres empresas que no aparezcan ahí y no inventes empresas.
2. En 3.3 y 3.4 los pasos deben llevar a las evidencias de la planeación (no inventes otras evidencias).
3. En 3.1 no se califica ni se exige dominio técnico; en 3.2 se reconocen saberes previos.
4. Nada de software ni equipos como requisito: el ambiente es el de la planeación y los materiales son consumibles."""
        prompt = self._aplicar_extra(prompt, instrucciones_extra)
        res = self._parsear_json(self._llamar(prompt))
        if not isinstance(res, dict):
            res = {"descripcion": str(res), "apoyo": ""}
        contexto_txt = " ".join(str(ctx.get(k, "")) for k in ("programa", "proyecto_formativo", "actividad_proyecto"))
        ajenas = [e for e in EMPRESAS_EXTERNAS if e in str(res.get("descripcion", "")).lower()
                  and e not in contexto_txt.lower()]
        if ajenas:
            try:
                res2 = self._parsear_json(self._llamar(
                    prompt + "\n\nTU RESPUESTA ANTERIOR mencionó " + ", ".join(ajenas) +
                    ", que NO están en el programa ni en el proyecto. Reescríbela sin ellas. Devuelve el JSON."))
                if isinstance(res2, dict) and res2.get("descripcion"):
                    res = res2
            except Exception:
                pass
        return {"descripcion": str(res.get("descripcion", "")).strip(),
                "apoyo": str(res.get("apoyo", "")).strip(),
                "evidencia": str(res.get("evidencia", "")).strip()}

    def describir_evidencia(self, aa: dict, ctx: dict, tecnicas: list, instrucciones_extra: str = "") -> str:
        """3.3.x: 'Descripción de la evidencia' de una AA (qué hace y qué entrega el aprendiz).
        La AA y la evidencia vienen de la planeación y NO se cambian."""
        tec = "; ".join(f"{t['name']}: {t['description']}" for t in tecnicas) or "(libre, activa)"
        prompt = f"""Redacta la DESCRIPCIÓN DE LA EVIDENCIA para una actividad de aprendizaje de una guía SENA (momento 3.3 Apropiación).

- Programa: {ctx.get('programa', '')}
- Proyecto formativo: {ctx.get('proyecto_formativo', '')}
- Competencia: {ctx.get('competencia', '')}
- Resultado de aprendizaje: {aa.get('rap', '')}
- Actividad de aprendizaje (planeación, NO la cambies): {aa.get('actividad', '')}
- Evidencia (planeación, NO la cambies): {aa.get('evidencia', '')}
- Saberes del diseño curricular para este RAP: {"; ".join((aa.get('saberes') or [])[:12])}
- Técnica didáctica elegida: {tec}

Responde ÚNICAMENTE con JSON: {{"descripcion": "60-130 palabras dirigidas al aprendiz: cómo desarrollar la actividad con la técnica, qué debe contener la evidencia (partes, formato, extensión), si es individual o en equipo y cómo se socializa."}}
REGLAS: no inventes otras evidencias; usa solo el contexto del programa y del proyecto; no nombres empresas que no aparezcan ahí; nada de software como requisito."""
        prompt = self._aplicar_extra(prompt, instrucciones_extra)
        res = self._parsear_json(self._llamar(prompt))
        return str(res.get("descripcion", "") if isinstance(res, dict) else res).strip()

    # ---------- Bibliografía VERIFICADA (Gemini + búsqueda de Google) ----------
    def buscar_bibliografia(self, ctx: dict, n: int = 6) -> list:
        """Referentes reales sobre los TEMAS de la guía. Gemini busca en Google (grounding) y solo
        se aceptan referencias cuyo sitio aparece entre las fuentes que Google devolvió: si la IA
        escribe una referencia que no salió de la búsqueda, se descarta (no se inventa nada)."""
        if self._cliente is None:
            raise RuntimeError("La búsqueda verificada necesita el SDK google-genai (requirements.txt).")
        temas = "; ".join((ctx.get("saberes") or [])[:15])
        prompt = f"""Busca en Google bibliografía REAL y consultable para una guía de aprendizaje SENA.
- Programa: {ctx.get('programa', '')}
- Competencia: {ctx.get('competencia', '')}
- Resultados de aprendizaje: {"; ".join(ctx.get('raps', []))}
- Temas (saberes del diseño curricular): {temas}

Prioriza: SENA (Biblioteca/Repositorio SENA), ministerios y entidades de Colombia (MinTrabajo, DIAN,
MinTransporte, ICONTEC), universidades y libros con editorial. Devuelve {n} referencias sobre ESOS temas.
Responde ÚNICAMENTE con JSON:
{{"referencias": [{{"apa": "Referencia completa en APA 7 con su URL", "url": "https://...", "tema": "tema que respalda"}}]}}
Incluye SOLO fuentes que encontraste en la búsqueda; no inventes autores, títulos ni enlaces."""
        herramienta = genai_types.Tool(google_search=genai_types.GoogleSearch())
        ultimo_error = None
        for modelo in dict.fromkeys([self.modelo_nombre, *self.MODELOS_RESPALDO]):
            try:
                resp = self._cliente.models.generate_content(
                    model=modelo, contents=prompt,
                    config=genai_types.GenerateContentConfig(tools=[herramienta]))
                break
            except Exception as e:
                ultimo_error = e
                if not re.search(r"503|UNAVAILABLE|overload|404|NOT_FOUND", str(e), re.I):
                    raise
        else:
            raise RuntimeError(f"Gemini no respondió: {ultimo_error}")
        dominios = set()
        for cand in (getattr(resp, "candidates", None) or []):
            gm = getattr(cand, "grounding_metadata", None)
            for ch in (getattr(gm, "grounding_chunks", None) or []):
                web = getattr(ch, "web", None)
                for v in (getattr(web, "title", "") or "", getattr(web, "domain", "") or ""):
                    v = str(v).lower().strip()
                    if "." in v and " " not in v:
                        dominios.add(v.removeprefix("www."))
        if not dominios:
            raise RuntimeError("Google no devolvió fuentes para verificar; no se agregó bibliografía.")
        try:
            datos = self._parsear_json(getattr(resp, "text", "") or "")
        except Exception:
            datos = {}
        refs = datos.get("referencias", []) if isinstance(datos, dict) else (datos or [])
        from urllib.parse import urlparse
        salida = []
        for r in refs:
            if not isinstance(r, dict):
                continue
            url = str(r.get("url", "")).strip()
            host = urlparse(url).netloc.lower().removeprefix("www.")
            if host and any(host == d or host.endswith("." + d) or d.endswith("." + host) for d in dominios):
                apa = str(r.get("apa", "")).strip()
                if url not in apa:
                    apa = f"{apa} {url}".strip()
                salida.append({"apa": apa, "url": url, "tema": str(r.get("tema", "")).strip(),
                               "fuente": "Google (verificada)"})
        return salida

    # ---------- Instrumentos de evaluación desde la guía ----------
    def generar_instrumento(self, tipo: str, item: dict, ctx: dict, n_preguntas: int = 8,
                            instrucciones_extra: str = "") -> list:
        """tipo: lista_chequeo | rubrica | cuestionario. Los criterios del diseño curricular se
        respetan: cada fila se ata a un criterio por ÍNDICE y el texto del criterio se pone
        verbatim desde el diseño (la IA no puede cambiarlo)."""
        crit = item.get("criterios") or []
        lista_c = "\n".join(f"{i + 1}. {c}" for i, c in enumerate(crit)) or "(sin criterios: usa la evidencia)"
        contexto = f"""- Programa: {ctx.get('programa', '')}
- Proyecto formativo: {ctx.get('proyecto_formativo', '')}
- Fase / actividad del proyecto: {item.get('fase', '')} · {item.get('actividad_proyecto', '')}
- Competencia: {ctx.get('competencia', '')}
- Resultado de aprendizaje: {item.get('rap', '')}
- Actividad de aprendizaje (V+O+C): {item.get('actividad', '')}
- Evidencia ({item.get('tipo', '')}): {item.get('evidencia', '')}
- Criterios de evaluación del diseño curricular (numerados):
{lista_c}"""
        if tipo == "cuestionario":
            saberes = "; ".join((item.get("saberes") or ctx.get("saberes") or [])[:20])
            formato = (f'{{"preguntas": [{{"criterio": <número del criterio que evalúa>, "enunciado": "...", "a": "...", "b": "...", "c": "...", "d": "...", '
                       f'"correcta": "a|b|c|d", "justificacion": "por qué es la correcta"}}]}}  '
                       f"→ exactamente {n_preguntas} preguntas de selección múltiple con única respuesta, "
                       f"basadas en estos saberes del diseño curricular: {saberes}. Distractores plausibles, "
                       "sin «todas/ninguna de las anteriores», respuestas correctas repartidas entre a, b, c y d. "
                       "Entre todas las preguntas deben quedar evaluados TODOS los criterios numerados.")
        elif tipo == "rubrica":
            formato = ('{"filas": [{"criterio": <número del criterio>, "excelente": "...", "bueno": "...", '
                       '"aceptable": "...", "por_mejorar": "..."}]}  → UNA fila por cada criterio numerado; '
                       "descriptores observables y graduados (calidad, completitud, autonomía), 15-35 palabras "
                       "cada uno, referidos a la evidencia concreta.")
        else:
            formato = ('{"indicadores": [{"criterio": <número del criterio>, "indicador": "..."}]}  → 1 a 3 '
                       "indicadores OBSERVABLES por criterio (verificables con Sí/No), redactados en tercera "
                       "persona y presente (p. ej. «Identifica…», «Presenta…»), sobre la evidencia concreta. "
                       "NINGÚN criterio numerado puede quedar sin indicador.")
        prompt = f"""Construye un instrumento de evaluación SENA ({tipo.replace('_', ' ')}) para esta evidencia.

{contexto}

Responde ÚNICAMENTE con JSON válido, sin markdown:
{formato}

REGLAS:
1. No inventes criterios: todo se ata a los criterios numerados del diseño curricular.
2. Usa solo el contexto del programa y del proyecto; no nombres empresas que no aparezcan ahí.
3. Lenguaje claro para el aprendiz; nada de software o equipos como requisito."""
        prompt = self._aplicar_extra(prompt, instrucciones_extra)
        res = self._parsear_json(self._llamar(prompt))

        def _idx(v):
            try:
                i = int(v) - 1
                return i if 0 <= i < len(crit) else None
            except (TypeError, ValueError):
                return None

        def vistos_txt(filas):
            return {f["criterio"] for f in filas}

        if tipo == "cuestionario":
            filas = res.get("preguntas", []) if isinstance(res, dict) else res
            salida = []
            for q in filas or []:
                if isinstance(q, dict) and str(q.get("enunciado", "")).strip():
                    salida.append({k: str(q.get(k, "")).strip() for k in
                                   ("enunciado", "a", "b", "c", "d", "correcta", "justificacion")})
                    salida[-1]["correcta"] = salida[-1]["correcta"][:1].lower()
                    i = _idx(q.get("criterio"))
                    salida[-1]["criterio"] = crit[i] if i is not None else ""
            return salida
        if tipo == "rubrica":
            filas = res.get("filas", []) if isinstance(res, dict) else res
            salida, vistos = [], set()
            for f in filas or []:
                i = _idx(f.get("criterio")) if isinstance(f, dict) else None
                if i is None or i in vistos:
                    continue
                vistos.add(i)
                salida.append({"criterio": crit[i], **{k: str(f.get(k, "")).strip() for k in
                                                       ("excelente", "bueno", "aceptable", "por_mejorar")}})
            # criterios que la IA dejó sin fila o niveles vacíos → plantilla (nada queda en blanco)
            from .instrumentos import rubrica_base
            base = {f["criterio"]: f for f in rubrica_base(item)}
            for f in salida:
                for k in ("excelente", "bueno", "aceptable", "por_mejorar"):
                    f[k] = f[k] or base.get(f["criterio"], {}).get(k, "")
            salida += [base[c] for c in crit if c not in vistos_txt(salida) and c in base]
            return sorted(salida, key=lambda x: crit.index(x["criterio"]) if x["criterio"] in crit else 999)
        filas = res.get("indicadores", []) if isinstance(res, dict) else res
        salida = []
        for f in filas or []:
            if isinstance(f, dict) and str(f.get("indicador", "")).strip():
                i = _idx(f.get("criterio"))
                salida.append({"indicador": str(f["indicador"]).strip(),
                               "criterio": crit[i] if i is not None else ""})
        return salida

    # ---------- helpers internos ----------
    def _respetar_pausa(self):
        transcurrido = time.time() - self._ultima_llamada_ts
        if transcurrido < self.pausa_s:
            time.sleep(self.pausa_s - transcurrido)

    # Si el modelo elegido está saturado (503) se prueba con estos, en orden.
    MODELOS_RESPALDO = ("gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite",
                        "gemini-flash-lite-latest")

    def _una_llamada(self, modelo: str, prompt: str) -> str:
        if self._cliente is not None:
            resp = self._cliente.models.generate_content(
                model=modelo, contents=prompt,
                config=genai_types.GenerateContentConfig(system_instruction=self._system))
        else:
            m = self.modelo if modelo == self.modelo_nombre else \
                genai.GenerativeModel(model_name=modelo, system_instruction=self._system)
            resp = m.generate_content(prompt)
        texto = (getattr(resp, "text", None) or "").strip()
        if not texto:
            raise RuntimeError("respuesta vacía (posible bloqueo de seguridad o límite de tokens)")
        return texto

    def _llamar(self, prompt: str, reintentos: int = 3) -> str:
        """Llama a Gemini con reintentos y espera creciente. Si el modelo está saturado
        (503 / UNAVAILABLE / overloaded) cambia a un modelo de respaldo; si es límite de uso
        (429) espera lo que pida Google."""
        modelos = [self.modelo_nombre] + [m for m in self.MODELOS_RESPALDO if m != self.modelo_nombre]
        ultimo_error = None
        idx_modelo = 0
        for intento in range(reintentos + len(modelos)):
            modelo = modelos[min(idx_modelo, len(modelos) - 1)]
            self._respetar_pausa()
            try:
                texto = self._una_llamada(modelo, prompt)
                self._ultima_llamada_ts = time.time()
                self.ultimo_modelo_usado = modelo
                return texto
            except Exception as e:
                self._ultima_llamada_ts = time.time()
                ultimo_error = e
                msg = str(e).lower()
                saturado = any(t in msg for t in ("503", "unavailable", "overloaded", "high demand"))
                limite = any(t in msg for t in ("429", "quota", "resource_exhausted", "rate"))
                no_existe = "404" in msg or "not found" in msg
                if saturado or no_existe:
                    idx_modelo += 1                      # pasar al siguiente modelo
                    if idx_modelo >= len(modelos):
                        idx_modelo = 0
                        time.sleep(min(5 * (intento + 1), 20))
                    continue
                if limite and intento < reintentos:
                    m = re.search(r"retry.*?(\d+(?:\.\d+)?)\s*s", msg)
                    time.sleep(min(float(m.group(1)) + 2 if m else 15 * (intento + 1), 60))
                    continue
                break
        raise RuntimeError(f"Error al llamar a Gemini: {ultimo_error}")

    @staticmethod
    def _aplicar_extra(prompt: str, extra: str) -> str:
        extra = (extra or "").strip()
        if not extra:
            return prompt
        return prompt + f"\n\nINSTRUCCIONES ADICIONALES DEL INSTRUCTOR (tienen prioridad):\n{extra}"

    @staticmethod
    def _formatear_raps(raps: list) -> str:
        if not raps:
            return "(no especificados)"
        return "\n".join(f"  - {r}" for r in raps if r)

    @staticmethod
    def _resumir_actividades(actividades: dict) -> str:
        out = []
        for k, v in actividades.items():
            desc = v.get("descripcion", "")[:150] if isinstance(v, dict) else ""
            if desc:
                out.append(f"  {k}: {desc}")
        return "\n".join(out) if out else "(sin actividades aún)"

    @staticmethod
    def _parsear_json(texto: str):
        if not texto:
            raise RuntimeError("La IA devolvió una respuesta vacía.")

        original = texto
        # Eliminar bloques ```json ... ``` (más robusto)
        texto = texto.strip()
        # Quitar ```json o ``` al inicio
        texto = re.sub(r"^```(?:json|JSON)?\s*", "", texto)
        # Quitar ``` al final
        texto = re.sub(r"\s*```\s*$", "", texto)
        texto = texto.strip()

        # Intento 1: parseo directo
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            pass

        # Intento 2: buscar el primer bloque JSON válido (objeto o array)
        m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", texto)
        if m:
            candidato = m.group(1)
            try:
                return json.loads(candidato)
            except json.JSONDecodeError:
                # Intento 3: limpiar comas colgantes y comentarios
                limpio = re.sub(r",\s*([}\]])", r"\1", candidato)  # comas colgantes
                limpio = re.sub(r"//[^\n]*", "", limpio)  # comentarios de línea
                limpio = re.sub(r"/\*[\s\S]*?\*/", "", limpio)  # comentarios de bloque
                try:
                    return json.loads(limpio)
                except json.JSONDecodeError:
                    pass

        raise RuntimeError(
            f"No pude parsear la respuesta como JSON.\n\n"
            f"--- Respuesta recibida (primeros 800 chars) ---\n{original[:800]}"
        )
