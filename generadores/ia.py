"""Integración con Gemini para generar contenido pedagógico SENA.

Los prompts son editables por el usuario desde la app (se guardan en data/prompts.json).
También acepta 'instrucciones_extra' por llamada para afinar sin editar el prompt base.
"""
import json
import re
from pathlib import Path
from typing import Optional

try:
    import google.generativeai as genai
    GEMINI_DISPONIBLE = True
except ImportError:
    GEMINI_DISPONIBLE = False


# ============ PROMPTS POR DEFECTO ============
# El usuario puede sobreescribirlos desde la app en "🎨 Prompts de la IA".
# Los placeholders {variable} se reemplazan con los datos de la guía en tiempo real.

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


PROMPTS_DEFAULT = {
    "system": SYSTEM_PROMPT_DEFAULT,
    "presentacion": PROMPT_PRESENTACION_DEFAULT,
    "actividad": PROMPT_ACTIVIDAD_DEFAULT,
    "glosario": PROMPT_GLOSARIO_DEFAULT,
    "referentes": PROMPT_REFERENTES_DEFAULT,
}


# ============ GESTIÓN DE PROMPTS PERSONALIZADOS ============
def cargar_prompts(prompts_file: Path) -> dict:
    """Carga los prompts del usuario. Cualquier prompt no editado usa el default."""
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
    """Restablece un prompt específico a su valor por defecto."""
    prompts = cargar_prompts(prompts_file)
    prompts[clave] = PROMPTS_DEFAULT[clave]
    guardar_prompts(prompts_file, prompts)
    return prompts


# ============ CLIENTE GEMINI ============
class GeminiCliente:
    """Cliente Gemini con prompts editables e instrucciones extra por llamada."""

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
        """Genera TODO el contenido de una vez.
        instrucciones_extra puede ser un dict con keys 'presentacion', '3.1', '3.2', '3.3', '3.4',
        'glosario', 'referentes' — cada valor es una instrucción extra opcional."""
        extra = instrucciones_extra or {}
        datos = dict(datos_iniciales)

        datos["presentacion"] = self.generar_presentacion(
            datos, instrucciones_extra=extra.get("presentacion", "")
        )

        actividades = {}
        for key in ["3.1", "3.2", "3.3", "3.4"]:
            actividades[key] = self.generar_actividad(
                key, datos, actividades_previas=actividades,
                instrucciones_extra=extra.get(key, "")
            )
        datos["actividades"] = actividades

        datos["glosario"] = self.generar_glosario(
            datos, instrucciones_extra=extra.get("glosario", "")
        )
        datos["referentes"] = self.generar_referentes(
            datos, instrucciones_extra=extra.get("referentes", "")
        )
        return datos

    # ---------- helpers internos ----------
    def _llamar(self, prompt: str) -> str:
        try:
            resp = self.modelo.generate_content(prompt)
            return resp.text.strip()
        except Exception as e:
            raise RuntimeError(f"Error al llamar a Gemini: {e}")

    @staticmethod
    def _aplicar_extra(prompt: str, extra: str) -> str:
        """Añade las instrucciones extra del usuario al final del prompt base."""
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
