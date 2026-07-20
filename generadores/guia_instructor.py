"""Genera la Guía del Instructor (complemento didáctico a la Guía del Aprendiz)."""
from .utils_docx import (
    clone_template, add_heading, add_sub, add_field,
    add_text, add_bullet, make_table, set_run
)


def generar_guia_instructor(datos: dict, ruta_salida: str) -> str:
    """
    Usa los mismos datos que la Guía del Aprendiz, pero agrega:
      - orientaciones didácticas por actividad (auto o desde datos['orientaciones'])
      - respuestas esperadas
      - errores comunes de los aprendices
      - tips de manejo del grupo
    """
    doc = clone_template(ruta_salida)

    # Marca del documento
    add_heading(doc, "GUÍA DEL INSTRUCTOR", size=14, space_before=0, space_after=4)
    add_text(doc, "Documento de uso interno — complemento didáctico de la Guía del Aprendiz.",
             italic=True, size=10)

    # ===== Identificación breve =====
    add_heading(doc, "1. IDENTIFICACIÓN")
    add_field(doc, "Programa:", datos.get("programa", ""))
    add_field(doc, "Código:", datos.get("codigo_programa", ""))
    add_field(doc, "Proyecto Formativo:", datos.get("proyecto_formativo", ""))
    add_field(doc, "Fase:", datos.get("fase_proyecto", ""))
    add_field(doc, "Competencia:", datos.get("competencia", ""))
    add_field(doc, "Duración:", datos.get("duracion", ""))

    # ===== Orientaciones generales =====
    add_heading(doc, "2. ORIENTACIONES GENERALES PARA EL INSTRUCTOR")
    orient_gral = datos.get("orientaciones_generales") or (
        "Esta guía se desarrolla combinando trabajo presencial y autónomo del aprendiz. "
        "Como instructor, su rol principal es de facilitador: plantea la situación real, "
        "moviliza las ideas previas del grupo antes de introducir el concepto físico, "
        "acompaña la resolución de ejercicios sin dar directamente las respuestas, "
        "y cierra cada sesión conectando el aprendizaje con el proyecto formativo. "
        "Recuerde que los aprendices trabajan mejor cuando el ejemplo viene de su propio contexto laboral."
    )
    add_text(doc, orient_gral)

    add_sub(doc, "Perfil esperado del aprendiz al finalizar")
    perfil = datos.get("perfil_egreso") or (
        "El aprendiz identifica los principios físicos presentes en operaciones logísticas reales, "
        "resuelve problemas cuantitativos aplicando fórmulas básicas con procedimiento y unidades, "
        "y propone al menos una mejora concreta a un proceso productivo."
    )
    add_text(doc, perfil)

    # ===== Desarrollo por actividades =====
    add_heading(doc, "3. DESARROLLO DIDÁCTICO POR ACTIVIDAD")

    subtitulos = {
        "3.1": "3.1 Reflexión inicial",
        "3.2": "3.2 Contextualización",
        "3.3": "3.3 Apropiación",
        "3.4": "3.4 Transferencia",
    }
    actividades = datos.get("actividades", {})
    orientaciones = datos.get("orientaciones", {})

    for key in ["3.1", "3.2", "3.3", "3.4"]:
        add_sub(doc, subtitulos[key])
        act = actividades.get(key, {})
        add_field(doc, "Descripción resumida:", act.get("descripcion", ""))
        add_field(doc, "Duración:", act.get("duracion", ""))

        orient = orientaciones.get(key, {})

        # Momento a momento
        p = doc.add_paragraph()
        r = p.add_run("Momento a momento (sugerido):")
        set_run(r, bold=True)
        momentos = orient.get("momentos") or _momentos_default(key)
        for m in momentos:
            add_bullet(doc, m)

        # Preguntas orientadoras
        preguntas = orient.get("preguntas") or _preguntas_default(key)
        if preguntas:
            p = doc.add_paragraph()
            r = p.add_run("Preguntas orientadoras para el grupo:")
            set_run(r, bold=True)
            for q in preguntas:
                add_bullet(doc, q)

        # Respuestas esperadas
        respuestas = orient.get("respuestas") or _respuestas_default(key)
        if respuestas:
            p = doc.add_paragraph()
            r = p.add_run("Respuestas esperadas / puntos clave:")
            set_run(r, bold=True)
            for resp in respuestas:
                add_bullet(doc, resp)

        # Errores comunes
        errores = orient.get("errores") or _errores_default(key)
        if errores:
            p = doc.add_paragraph()
            r = p.add_run("Errores comunes de los aprendices:")
            set_run(r, bold=True)
            for e in errores:
                add_bullet(doc, e)

        # Tips de manejo del grupo
        tips = orient.get("tips") or _tips_default(key)
        if tips:
            p = doc.add_paragraph()
            r = p.add_run("Recomendaciones de manejo del grupo:")
            set_run(r, bold=True)
            for t in tips:
                add_bullet(doc, t)

    # ===== Evaluación =====
    add_heading(doc, "4. EVALUACIÓN Y RETROALIMENTACIÓN")
    add_text(doc,
             "Las rúbricas específicas de cada actividad se encuentran en el documento adjunto "
             "'Rúbricas de Evaluación'. Aplíquelas al momento de recibir cada evidencia y "
             "conserve el registro en el formato del portafolio del aprendiz.")

    add_sub(doc, "Criterios generales para todo el proceso")
    add_bullet(doc, "Cumplimiento del cronograma y de los tiempos asignados por actividad.")
    add_bullet(doc, "Calidad técnica de las evidencias entregadas (procedimiento, unidades, coherencia).")
    add_bullet(doc, "Aplicabilidad al contexto del proyecto formativo.")
    add_bullet(doc, "Actitud y trabajo colaborativo durante las sesiones presenciales.")

    # ===== Control =====
    add_heading(doc, "5. CONTROL DEL DOCUMENTO")
    make_table(doc, [
        ["", "Nombre", "Cargo", "Dependencia", "Fecha"],
        ["Autor(es)", datos.get("autor_nombre", ""), datos.get("autor_cargo", "Instructor"),
         datos.get("autor_dependencia", "Centro de Formación SENA"), datos.get("autor_fecha", "")],
    ], widths_cm=[2.0, 3.5, 2.8, 3.5, 2.4])

    doc.save(ruta_salida)
    return ruta_salida


# ---- valores por defecto usados si el usuario no llena orientaciones ----
def _momentos_default(key):
    base = {
        "3.1": [
            "Inicio (10 min): saludo, encuadre, presentación del proyecto formativo.",
            "Desarrollo (35 min): presentación de la situación real, preguntas al grupo, lluvia de ideas en el tablero.",
            "Cierre (15 min): recopilación de ideas, anticipación del contenido de la siguiente sesión.",
        ],
        "3.2": [
            "Inicio (5 min): retomar las ideas del cierre anterior.",
            "Desarrollo (40 min): exposición dialogada del concepto clave con pausas activas.",
            "Cierre (15 min): identificación grupal de ejemplos del propio contexto de los aprendices.",
        ],
        "3.3": [
            "Bloque 1 (60 min): trabajo individual con el quiz interactivo o guía autónoma.",
            "Bloque 2 (90 min): resolución de ejercicios cuantitativos con acompañamiento del instructor.",
            "Bloque 3 (90 min): socialización de resultados y aclaración de dudas.",
        ],
        "3.4": [
            "El instructor entrega instrucciones claras del reto en la sesión anterior.",
            "El aprendiz trabaja de forma autónoma en casa o su sitio de trabajo.",
            "En la siguiente sesión presencial se socializan las evidencias producidas.",
        ],
    }
    return base.get(key, [])


def _preguntas_default(key):
    base = {
        "3.1": [
            "¿Han visto esta situación en su propio trabajo? ¿Qué hicieron?",
            "¿Qué creen que causa lo que se observa?",
            "¿Cómo lo resolverían ustedes desde su experiencia?",
        ],
        "3.2": [
            "¿Con qué otro proceso de su trabajo pueden relacionar este concepto?",
            "¿Qué unidades se usan en el sector?",
            "¿Qué pasaría si cambiamos una variable del proceso?",
        ],
        "3.3": [
            "Antes de calcular, ¿qué respuesta esperas? ¿grande o pequeña?",
            "¿Las unidades del resultado tienen sentido?",
            "Si el resultado fuera distinto, ¿qué habría cambiado en la situación?",
        ],
        "3.4": [
            "¿Cómo se relaciona lo que grabaste con tu área de trabajo real?",
            "¿Qué mejora concreta propones tú?",
            "¿Qué necesitarías para implementarla?",
        ],
    }
    return base.get(key, [])


def _respuestas_default(key):
    base = {
        "3.1": [
            "El objetivo NO es que respondan bien; es que expresen sus ideas previas para trabajar sobre ellas.",
            "Anote en el tablero las ideas, incluso las incorrectas — se retoman al final de la competencia.",
        ],
        "3.2": [
            "Los conceptos clave deben quedar escritos en el tablero o en la presentación para consulta posterior.",
            "Verifique que todos los aprendices logran dar al menos un ejemplo propio antes de avanzar.",
        ],
        "3.3": [
            "En los ejercicios de F=m·a: verificar que despejan bien la variable buscada y que usan unidades SI.",
            "Los aprendices deben mostrar procedimiento paso a paso, no solo resultado.",
        ],
        "3.4": [
            "La propuesta de mejora debe ser CONCRETA (con acciones específicas) y ANCLADA a un proceso real.",
            "Descartar propuestas genéricas tipo 'mejorar la comunicación' sin especificidad técnica.",
        ],
    }
    return base.get(key, [])


def _errores_default(key):
    base = {
        "3.1": [
            "Los aprendices tienden a dar respuestas 'esperadas' en vez de las suyas propias. Insista en la experiencia real.",
        ],
        "3.2": [
            "Confusión entre masa (kg, no cambia) y peso (N, sí cambia con la gravedad). Enfatice esto varias veces.",
            "Uso incorrecto de unidades (mezclar g con kg, o m con cm).",
        ],
        "3.3": [
            "Aplican mecánicamente la fórmula sin verificar que las unidades sean coherentes.",
            "Olvidan convertir unidades antes del cálculo.",
            "Dan el resultado sin analizar si tiene sentido físico.",
        ],
        "3.4": [
            "Confunden 'demostrar' la ley con 'hablar' de la ley. El video debe MOSTRAR el fenómeno.",
            "Entregan video muy largo (más de 5 min) o muy corto (menos de 2 min).",
        ],
    }
    return base.get(key, [])


def _tips_default(key):
    base = {
        "3.1": [
            "Escuche a los aprendices que trabajan en logística real — sus aportes son valiosos para todo el grupo.",
        ],
        "3.2": [
            "Cada 20 minutos haga una pausa activa: pregunta rápida o ejemplo del contexto.",
        ],
        "3.3": [
            "Si un aprendiz termina antes, pídale que ayude a un compañero (aprendizaje entre pares).",
            "Camine por el ambiente supervisando el progreso individual.",
        ],
        "3.4": [
            "Recuerde que la evidencia individual permite evaluar los aportes reales de cada aprendiz.",
        ],
    }
    return base.get(key, [])
