"""Genera el documento de Rúbricas de Evaluación (una rúbrica por cada actividad 3.1–3.4)."""
from .utils_docx import (
    clone_template, add_heading, add_sub, add_field,
    add_text, add_bullet, make_table
)


def generar_rubricas(datos: dict, ruta_salida: str) -> str:
    """
    Genera un docx con las rúbricas de evaluación por actividad.
    Espera datos con:
      programa, codigo_programa, competencia, raps
      actividades (dict con 3.1..3.4)
      rubricas (dict opcional con criterios personalizados por actividad)
    """
    doc = clone_template(ruta_salida)

    add_heading(doc, "RÚBRICAS DE EVALUACIÓN", size=14, space_before=0, space_after=4)
    add_text(doc, "Instrumentos de evaluación por actividad — anexo a la Guía de Aprendizaje.",
             italic=True, size=10)

    # Identificación breve
    add_heading(doc, "IDENTIFICACIÓN")
    add_field(doc, "Programa:", datos.get("programa", ""))
    add_field(doc, "Código:", datos.get("codigo_programa", ""))
    add_field(doc, "Competencia:", datos.get("competencia", ""))

    # Escala general
    add_heading(doc, "ESCALA DE VALORACIÓN")
    add_text(doc,
             "Cada criterio se evalúa en cuatro niveles: EXCELENTE (4 pts), BUENO (3 pts), "
             "ACEPTABLE (2 pts), REQUIERE MEJORA (1 pt). El puntaje total de cada actividad "
             "se convierte a la escala institucional (aprobado/no aprobado).")

    # Rúbricas por actividad
    titulos = {
        "3.1": "RÚBRICA — Actividad 3.1 · Reflexión inicial",
        "3.2": "RÚBRICA — Actividad 3.2 · Contextualización",
        "3.3": "RÚBRICA — Actividad 3.3 · Apropiación",
        "3.4": "RÚBRICA — Actividad 3.4 · Transferencia",
    }
    actividades = datos.get("actividades", {})
    rubricas_custom = datos.get("rubricas", {})

    for key in ["3.1", "3.2", "3.3", "3.4"]:
        add_heading(doc, titulos[key])
        act = actividades.get(key, {})
        if act.get("descripcion"):
            add_field(doc, "Actividad evaluada:", act.get("descripcion", "")[:200] + "...")
        if act.get("evidencias"):
            add_field(doc, "Evidencia:", act["evidencias"])

        criterios = rubricas_custom.get(key) or _criterios_default(key)
        _render_rubrica(doc, criterios)

        # Espacio para observaciones y firma
        add_sub(doc, "Observaciones del instructor")
        make_table(doc, [["Comentarios / retroalimentación al aprendiz"], [" " * 200]],
                   widths_cm=[16.0])

        make_table(doc, [
            ["Aprendiz", "Firma aprendiz", "Instructor", "Firma instructor", "Fecha"],
            ["", "", "", "", ""]
        ], widths_cm=[3.5, 3.0, 3.5, 3.0, 3.0])

    doc.save(ruta_salida)
    return ruta_salida


def _render_rubrica(doc, criterios):
    """
    criterios: list de dicts con:
      { 'criterio': str, 'excelente': str, 'bueno': str, 'aceptable': str, 'mejora': str }
    """
    encabezado = ["Criterio", "Excelente (4)", "Bueno (3)", "Aceptable (2)", "Requiere mejora (1)"]
    rows = [encabezado]
    for c in criterios:
        rows.append([
            c.get("criterio", ""),
            c.get("excelente", ""),
            c.get("bueno", ""),
            c.get("aceptable", ""),
            c.get("mejora", ""),
        ])
    make_table(doc, rows, widths_cm=[3.5, 3.3, 3.3, 3.3, 3.6])


# ---- criterios por defecto según fase de la actividad ----
def _criterios_default(key):
    if key == "3.1":
        return [
            {
                "criterio": "Participación en la lluvia de ideas",
                "excelente": "Aporta ideas propias basadas en su experiencia y las argumenta.",
                "bueno": "Aporta ideas propias sin argumentar en profundidad.",
                "aceptable": "Aporta pocas ideas o repite las de otros compañeros.",
                "mejora": "No participa o interrumpe el diálogo del grupo.",
            },
            {
                "criterio": "Conexión con el contexto propio",
                "excelente": "Relaciona claramente la situación con casos vividos en su trabajo.",
                "bueno": "Relaciona con casos generales del sector productivo.",
                "aceptable": "Menciona relación pero de manera superficial.",
                "mejora": "No relaciona la situación con ningún contexto real.",
            },
            {
                "criterio": "Escucha activa y respeto",
                "excelente": "Escucha con atención, respeta turnos y complementa lo dicho por otros.",
                "bueno": "Escucha y respeta turnos.",
                "aceptable": "Escucha pero interrumpe ocasionalmente.",
                "mejora": "No escucha o interrumpe frecuentemente.",
            },
        ]

    if key == "3.2":
        return [
            {
                "criterio": "Comprensión de conceptos clave",
                "excelente": "Explica el concepto con sus palabras y da ejemplos propios.",
                "bueno": "Explica el concepto con sus palabras.",
                "aceptable": "Repite el concepto pero no lo explica.",
                "mejora": "No logra explicar el concepto.",
            },
            {
                "criterio": "Identificación de ejemplos del contexto",
                "excelente": "Identifica varios ejemplos propios y los relaciona con el concepto.",
                "bueno": "Identifica al menos un ejemplo propio correcto.",
                "aceptable": "Identifica un ejemplo pero con confusiones.",
                "mejora": "No identifica ejemplos del contexto.",
            },
            {
                "criterio": "Uso correcto de vocabulario técnico",
                "excelente": "Usa términos técnicos correctamente y con precisión.",
                "bueno": "Usa términos técnicos con algunas imprecisiones menores.",
                "aceptable": "Usa términos técnicos ocasionalmente y con imprecisiones.",
                "mejora": "No usa vocabulario técnico o lo usa incorrectamente.",
            },
        ]

    if key == "3.3":
        return [
            {
                "criterio": "Procedimiento de resolución",
                "excelente": "Muestra procedimiento completo, ordenado y con todos los pasos.",
                "bueno": "Muestra procedimiento con pasos claros, con alguna omisión menor.",
                "aceptable": "Procedimiento incompleto pero con lógica.",
                "mejora": "No muestra procedimiento o es incoherente.",
            },
            {
                "criterio": "Manejo de unidades",
                "excelente": "Todas las unidades del SI son correctas y coherentes.",
                "bueno": "Unidades correctas en el resultado final; error menor en el desarrollo.",
                "aceptable": "Algunas unidades correctas, otras confusas o mezcladas.",
                "mejora": "No usa unidades o las usa incorrectamente.",
            },
            {
                "criterio": "Resultado numérico",
                "excelente": "Resultado correcto con precisión adecuada.",
                "bueno": "Resultado correcto con imprecisión menor de redondeo.",
                "aceptable": "Resultado con error de cálculo pero procedimiento correcto.",
                "mejora": "Resultado incorrecto por errores conceptuales.",
            },
            {
                "criterio": "Interpretación del resultado",
                "excelente": "Interpreta el resultado en el contexto del problema con claridad.",
                "bueno": "Interpreta el resultado de manera general.",
                "aceptable": "Menciona el resultado sin interpretarlo.",
                "mejora": "No interpreta ni menciona el significado del resultado.",
            },
        ]

    if key == "3.4":
        return [
            {
                "criterio": "Explicación del principio físico",
                "excelente": "Explica el principio con claridad, sin errores conceptuales.",
                "bueno": "Explica el principio con imprecisiones menores.",
                "aceptable": "Explicación parcial o con algún error conceptual.",
                "mejora": "No explica o el principio está mal identificado.",
            },
            {
                "criterio": "Coherencia experimento — principio",
                "excelente": "El experimento demuestra claramente el principio explicado.",
                "bueno": "El experimento demuestra el principio con alguna ambigüedad.",
                "aceptable": "El experimento se relaciona parcialmente con el principio.",
                "mejora": "El experimento no se relaciona con el principio.",
            },
            {
                "criterio": "Relación con el contexto laboral",
                "excelente": "Conecta explícitamente el experimento con un proceso real del sector.",
                "bueno": "Menciona la relación con el sector productivo.",
                "aceptable": "Relación mencionada superficialmente.",
                "mejora": "No hay relación con el contexto laboral.",
            },
            {
                "criterio": "Calidad de la producción (video/documento)",
                "excelente": "Audio y video claros, duración adecuada, presentación cuidada.",
                "bueno": "Producción clara con detalles técnicos menores por mejorar.",
                "aceptable": "Producción entendible pero con dificultades técnicas.",
                "mejora": "Producción inentendible o incompleta.",
            },
        ]

    return []
