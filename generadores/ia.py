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

try:
    import google.generativeai as genai
    GEMINI_DISPONIBLE = True
except ImportError:
    GEMINI_DISPONIBLE = False


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
SYSTEM_PROMPT_DEFAULT = """Eres ProfeNaturales SENA, instructor experto en ciencias naturales aplicadas al contexto productivo colombiano.
Estás ayudando a diseñar guías de aprendizaje para aprendices SENA de nivel BÁSICO en programas técnicos.

Reglas obligatorias:
1. Los aprendices son de NIVEL BÁSICO. No uses lenguaje académico complejo. Habla como instructor de piso, cercano y motivador.
2. Contextualiza SIEMPRE en escenarios reales del sector productivo colombiano. Cuando el programa sea Logística y se mencione minería, usa Carbones del Cerrejón Limited (La Guajira) como anclaje real.
3. NO uses empresas ficticias si el usuario menciona un contexto real como Cerrejón.
4. Usa datos y unidades del Sistema Internacional. Menciona equipos reales del sector (haul trucks, bandas transportadoras, montacargas, etc.).
5. Estructura tus respuestas para ser DIRECTAMENTE utilizables en una guía SENA GFPI-F-135.
6. Sé específico y concreto — evita frases genéricas tipo "aplicar el conocimiento".
7. Cuando se te pida contenido para un campo específico (descripción, ambiente, materiales, etc.), responde SOLO con el contenido de ese campo, sin encabezados ni etiquetas.

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
PROMPT_PLANEACION_DEFAULT = """Diseña los campos técnicos de la PLANEACIÓN PEDAGÓGICA (formato GFPI-F-134 del SENA) para esta competencia.

Programa: {programa}
Fase del proyecto: {fase}
Proyecto formativo: {proyecto_formativo}
Actividad de proyecto formativo: {actividad_proyecto}
Competencia: {competencia}
Resultados de aprendizaje:
{raps_formateados}

Responde ÚNICAMENTE en JSON válido (sin markdown, sin ```json):
{{
  "saberes_conceptos": "Conceptos y principios que el aprendiz DEBE saber. Lista breve separada por comas.",
  "saberes_proceso": "Habilidades y procesos que el aprendiz DEBE saber HACER. Lista breve separada por comas.",
  "criterios_evaluacion": "Criterios que se usarán para evaluar el aprendizaje. Cada criterio empieza con verbo en tercera persona (identifica, calcula, propone, verifica...). Deben ser CONCRETOS Y MEDIBLES en el contexto del proyecto formativo.",
  "actividades_aprendizaje": "Nombre de las actividades de aprendizaje asociadas a esta competencia (ej: 'Guía S1 RA-01: Leyes de Newton en Cerrejón, Quiz VF, Simulador PhET, Video experimental').",
  "descripcion_evidencia": "Descripción concreta de las evidencias que produce el aprendiz (ej: 'Guía autónoma resuelta, quiz completado con puntaje mínimo, video experimental de 3-5 min, propuesta escrita de mejora').",
  "estrategias_didacticas": "Estrategias didácticas activas a usar. Lista corta (ej: 'ABP, simulación, aprendizaje experiencial, exposición dialogada').",
  "ambiente": "Ambiente físico requerido (ej: 'Aula de sistemas con conexión a internet').",
  "materiales": "Materiales de formación necesarios (ej: 'Computadores, video beam, calculadora, simulador PhET').",
  "horas_directas": 48,
  "horas_independientes": 48
}}

Reglas:
- Todo debe ser específico y coherente con el proyecto formativo
- Los criterios de evaluación deben ser MEDIBLES y anclados al contexto real
- horas_directas y horas_independientes son números enteros (por defecto 48 cada uno para una competencia completa)
- No incluyas comillas dobles anidadas sin escapar dentro de los valores"""


PROMPTS_DEFAULT = {
    "system": SYSTEM_PROMPT_DEFAULT,
    "presentacion": PROMPT_PRESENTACION_DEFAULT,
    "actividad": PROMPT_ACTIVIDAD_DEFAULT,
    "glosario": PROMPT_GLOSARIO_DEFAULT,
    "referentes": PROMPT_REFERENTES_DEFAULT,
    "planeacion": PROMPT_PLANEACION_DEFAULT,
}


# ============ GESTIÓN DE PROMPTS PERSONALIZADOS ============
def cargar_prompts(prompts_file: Path) -> dict:
    if prompts_file.exists():
        try:
            custom = json.loads(prompts_file.read_text(encoding="utf-8"))
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
            raise ImportError("google-generativeai no está instalado. Ejecuta: pip install google-generativeai")
        if not api_key or not api_key.strip():
            raise ValueError("Se requiere una API key de Gemini. Obtenla gratis en https://aistudio.google.com/apikey")

        self.prompts = prompts or dict(PROMPTS_DEFAULT)
        self.modelo_nombre = modelo
        self.pausa_s = PAUSAS_POR_MODELO.get(modelo, PAUSA_DEFAULT)
        self._ultima_llamada_ts = 0.0

        genai.configure(api_key=api_key.strip())
        self.modelo = genai.GenerativeModel(
            model_name=modelo,
            system_instruction=self.prompts.get("system", SYSTEM_PROMPT_DEFAULT),
        )

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
        Opcionalmente: guias_relacionadas (list) - guías ya generadas para esta competencia,
                       para alinear las "actividades_aprendizaje" con lo que ya existe.
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

        # Alineación con guías de aprendizaje ya generadas (si hay)
        guias_prev = datos.get("guias_relacionadas", [])
        if guias_prev:
            contexto_guias = "\n\nCONTEXTO ADICIONAL — GUÍAS DE APRENDIZAJE YA GENERADAS PARA ESTA COMPETENCIA:\n"
            contexto_guias += ("El instructor ya ha diseñado las siguientes guías de aprendizaje "
                               "para esta competencia. Las 'actividades_aprendizaje' y las "
                               "'evidencias' que generes DEBEN estar alineadas con estas guías, "
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

    # ---------- helpers internos ----------
    def _respetar_pausa(self):
        transcurrido = time.time() - self._ultima_llamada_ts
        if transcurrido < self.pausa_s:
            time.sleep(self.pausa_s - transcurrido)

    def _llamar(self, prompt: str, reintentos: int = 2) -> str:
        for intento in range(reintentos + 1):
            self._respetar_pausa()
            try:
                resp = self.modelo.generate_content(prompt)
                self._ultima_llamada_ts = time.time()
                return resp.text.strip()
            except Exception as e:
                self._ultima_llamada_ts = time.time()
                mensaje = str(e)
                if "429" in mensaje or "quota" in mensaje.lower() or "rate" in mensaje.lower():
                    if intento < reintentos:
                        m = re.search(r"retry.*?(\d+)\s*s", mensaje)
                        espera = int(m.group(1)) + 2 if m else 30
                        time.sleep(min(espera, 60))
                        continue
                raise RuntimeError(f"Error al llamar a Gemini: {e}")
        raise RuntimeError("Se agotaron los reintentos por rate limit.")

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
        texto = re.sub(r"^```(?:json)?", "", texto.strip(), flags=re.MULTILINE)
        texto = re.sub(r"```$", "", texto.strip(), flags=re.MULTILINE)
        texto = texto.strip()
        try:
            return json.loads(texto)
        except json.JSONDecodeError:
            m = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", texto)
            if m:
                try:
                    return json.loads(m.group(1))
                except json.JSONDecodeError:
                    pass
            raise RuntimeError(f"No pude parsear la respuesta como JSON. Respuesta recibida:\n{texto[:500]}")
