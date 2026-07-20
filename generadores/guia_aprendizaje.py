"""Genera la Guía de Aprendizaje del Aprendiz (formato GFPI-F-135)."""
from .utils_docx import (
    clone_template, add_heading, add_sub, add_field,
    add_text, add_bullet, make_table
)


def generar_guia_aprendizaje(datos: dict, ruta_salida: str) -> str:
    """
    datos esperados:
      programa: str
      codigo_programa: str
      proyecto_formativo: str
      fase_proyecto: str
      actividad_proyecto: str
      competencia: str  (ej: '220201501 — Aplicar conocimientos...')
      raps: list[str]  (los 4 resultados de aprendizaje textuales)
      duracion: str
      presentacion: str
      actividades: dict con keys '3.1', '3.2', '3.3', '3.4', cada una con:
          descripcion, ambiente, estrategias, materiales, apoyo,
          duracion, evidencias (opcional), instrumentos (opcional)
      evidencias_tabla: list de list (filas para tabla sección 4)
      glosario: list[tuple(termino, definicion)]
      referentes: list[str]
      autor_nombre: str
      autor_cargo: str
      autor_dependencia: str
      autor_fecha: str
    """
    doc = clone_template(ruta_salida)

    # ===== 1. IDENTIFICACIÓN =====
    add_heading(doc, "1. IDENTIFICACIÓN DE LA GUÍA DE APRENDIZAJE")
    add_field(doc, "Denominación del Programa de Formación:", datos.get("programa", ""))
    add_field(doc, "Código del Programa de Formación:", datos.get("codigo_programa", ""))
    add_field(doc, "Nombre del Proyecto Formativo:", datos.get("proyecto_formativo", ""))
    add_field(doc, "Fase del Proyecto:", datos.get("fase_proyecto", ""))
    add_field(doc, "Actividad de Proyecto Formativo:", datos.get("actividad_proyecto", ""))
    add_field(doc, "Competencia:", datos.get("competencia", ""))

    # Resultados de aprendizaje (lista con viñetas)
    raps = datos.get("raps", [])
    p = doc.add_paragraph()
    r = p.add_run("Resultados de Aprendizaje:")
    from .utils_docx import set_run
    set_run(r, bold=True)
    for rap in raps:
        add_bullet(doc, rap)

    add_field(doc, "Duración de la Guía de Aprendizaje:", datos.get("duracion", ""))

    # ===== 2. PRESENTACIÓN =====
    add_heading(doc, "2. PRESENTACIÓN")
    for parrafo in datos.get("presentacion", "").split("\n\n"):
        if parrafo.strip():
            add_text(doc, parrafo.strip())

    # ===== 3. ACTIVIDADES =====
    add_heading(doc, "3. FORMULACIÓN DE LAS ACTIVIDADES DE APRENDIZAJE")

    subtitulos = {
        "3.1": "3.1 Actividades de reflexión inicial",
        "3.2": "3.2 Actividades de contextualización e identificación de conocimientos necesarios para el aprendizaje",
        "3.3": "3.3 Actividades de apropiación (conceptualización y teorización)",
        "3.4": "3.4 Actividades de transferencia del conocimiento",
    }
    actividades = datos.get("actividades", {})
    for key in ["3.1", "3.2", "3.3", "3.4"]:
        add_sub(doc, subtitulos[key])
        act = actividades.get(key, {})
        add_field(doc, "Descripción de la actividad:", act.get("descripcion", ""))
        add_field(doc, "Ambiente requerido:", act.get("ambiente", ""))
        add_field(doc, "Estrategias o técnicas didácticas activas:", act.get("estrategias", ""))
        add_field(doc, "Materiales de formación:", act.get("materiales", ""))
        add_field(doc, "Material de apoyo:", act.get("apoyo", ""))
        if act.get("evidencias"):
            add_field(doc, "Evidencias de aprendizaje:", act["evidencias"])
        if act.get("instrumentos"):
            add_field(doc, "Instrumentos de evaluación:", act["instrumentos"])
        add_field(doc, "Duración de la actividad:", act.get("duracion", ""))

    # ===== 4. EVIDENCIAS =====
    add_heading(doc, "4. PLANTEAMIENTO DE EVIDENCIAS DE APRENDIZAJE PARA LA EVALUACIÓN")
    ev_rows = datos.get("evidencias_tabla", [])
    if ev_rows:
        make_table(doc, ev_rows, widths_cm=[2.2, 3.0, 2.8, 3.0, 3.0, 2.2])

    # ===== 5. GLOSARIO =====
    glosario = datos.get("glosario", [])
    if glosario:
        add_heading(doc, "5. GLOSARIO DE TÉRMINOS")
        for termino, definicion in glosario:
            p = doc.add_paragraph()
            p.paragraph_format.space_after = 3
            r1 = p.add_run(termino + " ")
            set_run(r1, bold=True)
            r2 = p.add_run(definicion)
            set_run(r2)

    # ===== 6. REFERENTES =====
    referentes = datos.get("referentes", [])
    if referentes:
        add_heading(doc, "6. REFERENTES BIBLIOGRÁFICOS")
        for ref in referentes:
            add_bullet(doc, ref)

    # ===== 7. CONTROL DEL DOCUMENTO =====
    add_heading(doc, "7. CONTROL DEL DOCUMENTO")
    make_table(doc, [
        ["", "Nombre", "Cargo", "Dependencia", "Fecha"],
        ["Autor(es)", datos.get("autor_nombre", ""), datos.get("autor_cargo", "Instructor"),
         datos.get("autor_dependencia", "Centro de Formación SENA"), datos.get("autor_fecha", "")],
        ["Revisión", "", "Coordinador Académico", datos.get("autor_dependencia", "Centro de Formación SENA"), ""],
    ], widths_cm=[2.0, 3.5, 2.8, 3.5, 2.4])

    # ===== 8. CONTROL DE CAMBIOS =====
    add_heading(doc, "8. CONTROL DE CAMBIOS")
    add_text(doc, "(Diligenciar únicamente si se realizan ajustes a la guía después de su primera aplicación.)",
             italic=True, size=10)
    make_table(doc, [
        ["", "Nombre", "Cargo", "Dependencia", "Fecha", "Razón del Cambio"],
        ["Autor(es)", "", "", "", "", ""]
    ], widths_cm=[1.6, 3.0, 2.4, 2.6, 2.2, 2.4])

    doc.save(ruta_salida)
    return ruta_salida
