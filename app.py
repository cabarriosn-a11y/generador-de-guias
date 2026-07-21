"""
Generador de Guías de Aprendizaje SENA — ProfeNaturales
Con integración de IA (Gemini) para generar contenido automáticamente.

Cambios importantes vs versión anterior:
  - Descarga persistente de guías generadas (usa session_state + disco).
  - Sección "Guías guardadas" ahora tiene botones de descarga por cada guía.
  - Lector de Excel detecta automáticamente columnas RAP1, RAP2, RAP3, RAP4.
  - Al seleccionar una competencia del Excel, se pre-llenan RAPs y código de programa.
  - Código de la competencia es opcional.
  - Botón para descargar plantilla de Excel de ejemplo.
"""
import io
import json
import re
import tempfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from generadores.guia_aprendizaje import generar_guia_aprendizaje
from generadores.guia_instructor import generar_guia_instructor
from generadores.rubricas import generar_rubricas
from generadores.plan_trabajo import (
    generar_plan_trabajo, calcular_cronograma,
    calcular_cronograma_por_rango, contar_dias_habiles,
)
from generadores.excel_portafolio import generar_excel_portafolio
from generadores.email_sender import (
    enviar_correo, probar_conexion, plantilla_correo_plan_trabajo
)
from generadores.planeacion_pedagogica import generar_planeacion
from generadores.proyectos_formativos import (
    procesar_pdf as procesar_pdf_proyecto,
    cargar_proyectos, agregar_o_actualizar_proyecto, eliminar_proyecto,
)
from generadores.ia import (
    GeminiCliente, GEMINI_DISPONIBLE,
    PROMPTS_DEFAULT, cargar_prompts, guardar_prompts, restablecer_prompt,
)


# ============ CONFIG ============
st.set_page_config(
    page_title="Generador Guías SENA — ProfeNaturales",
    page_icon="📘",
    layout="wide",
)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
GUIAS_DIR = DATA_DIR / "guias_generadas"
GUIAS_DIR.mkdir(exist_ok=True)

RAPS_FILE = DATA_DIR / "raps_guardados.json"
GUIAS_FILE = DATA_DIR / "guias_guardadas.json"
CONFIG_FILE = DATA_DIR / "config.json"
PROMPTS_FILE = DATA_DIR / "prompts.json"

# Planes de trabajo
PLANES_DIR = DATA_DIR / "planes_trabajo"
PLANES_DIR.mkdir(exist_ok=True)
APRENDICES_FILE = DATA_DIR / "aprendices.json"

# Planeaciones pedagógicas
PLANEACIONES_DIR = DATA_DIR / "planeaciones"
PLANEACIONES_DIR.mkdir(exist_ok=True)

# Proyectos formativos parseados desde PDFs
PROYECTOS_FILE = DATA_DIR / "proyectos_formativos.json"


# ============ RATE LIMITING VISUALES ============
MODELOS_DISPONIBLES = [
    "gemini-2.5-flash",
    "gemini-flash-latest",
    "gemini-3-flash",
    "gemini-3.1-flash-lite",
]
MODELO_DEFAULT = "gemini-2.5-flash"


# ============ PERSISTENCIA ============
def cargar_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return default
    return default


def guardar_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def cargar_raps():
    return cargar_json(RAPS_FILE, {})


def guardar_raps(raps):
    guardar_json(RAPS_FILE, raps)


def cargar_guias_historial():
    return cargar_json(GUIAS_FILE, [])


def guardar_guias_historial(lista):
    guardar_json(GUIAS_FILE, lista)


def cargar_config():
    return cargar_json(CONFIG_FILE, {})


def guardar_config(cfg):
    guardar_json(CONFIG_FILE, cfg)


# ============ IA ============
def obtener_cliente_ia():
    cfg = cargar_config()
    api_key = cfg.get("gemini_api_key", "").strip()
    if not api_key:
        return None
    modelo = cfg.get("modelo", MODELO_DEFAULT)
    if modelo not in MODELOS_DISPONIBLES:
        modelo = MODELO_DEFAULT
        cfg["modelo"] = MODELO_DEFAULT
        guardar_config(cfg)
    try:
        prompts = cargar_prompts(PROMPTS_FILE)
        return GeminiCliente(api_key, modelo=modelo, prompts=prompts)
    except Exception as e:
        st.error(f"Error inicializando IA: {e}")
        return None


def datos_desde_form():
    """Recolecta el estado actual del formulario para pasarlo a la IA."""
    return {
        "programa": st.session_state.get("form_programa", ""),
        "codigo_programa": st.session_state.get("form_codigo_prog", ""),
        "proyecto_formativo": st.session_state.get("form_proyecto", ""),
        "fase_proyecto": st.session_state.get("form_fase", "Planeación"),
        "actividad_proyecto": st.session_state.get("form_actividad_proyecto", ""),
        "competencia": st.session_state.get("form_competencia", ""),
        "raps": [st.session_state.get(f"rap_{i}", "") for i in range(10) if st.session_state.get(f"rap_{i}", "").strip()],
        "duracion": st.session_state.get("form_duracion", ""),
        "presentacion": st.session_state.get("form_presentacion", ""),
        "actividades": {
            k: {
                "descripcion": st.session_state.get(f"desc_{k}", ""),
                "ambiente": st.session_state.get(f"amb_{k}", ""),
                "estrategias": st.session_state.get(f"est_{k}", ""),
                "materiales": st.session_state.get(f"mat_{k}", ""),
                "apoyo": st.session_state.get(f"apo_{k}", ""),
                "evidencias": st.session_state.get(f"ev_{k}", ""),
                "instrumentos": st.session_state.get(f"ins_{k}", ""),
                "duracion": st.session_state.get(f"dur_{k}", ""),
            }
            for k in ["3.1", "3.2", "3.3", "3.4"]
        },
    }


def aplicar_actividad_a_form(key: str, act: dict):
    campos = {"descripcion": "desc", "ambiente": "amb", "estrategias": "est",
              "materiales": "mat", "apoyo": "apo", "evidencias": "ev",
              "instrumentos": "ins", "duracion": "dur"}
    for k_dato, k_form in campos.items():
        if k_dato in act:
            st.session_state[f"{k_form}_{key}"] = str(act[k_dato])


# ============ LECTURA DE COMPETENCIAS ============
@st.cache_data(ttl=300)
def leer_excel_bytes(contenido: bytes) -> dict:
    return pd.read_excel(io.BytesIO(contenido), sheet_name=None)


def descargar_desde_drive(url_o_id: str) -> bytes:
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url_o_id)
    file_id = m.group(1) if m else url_o_id.strip()
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content


def detectar_columnas_rap(df) -> list:
    """Detecta automáticamente las columnas RAP1, RAP2, RAP3... en el DataFrame."""
    cols_rap = []
    for col in df.columns:
        col_normalizada = str(col).strip().upper().replace(" ", "")
        if re.match(r"^RAP[\s]?\d+$", col_normalizada) or re.match(r"^RAP\d+$", col_normalizada):
            cols_rap.append(col)
    # ordenarlas por número
    def num_rap(c):
        m = re.search(r"\d+", str(c))
        return int(m.group()) if m else 99
    return sorted(cols_rap, key=num_rap)


def obtener_datos_competencia(df, col_prog, col_comp, valor_programa, valor_competencia,
                              col_cod_prog=None, col_cod_comp=None, cols_rap=None):
    """Devuelve dict con los datos de la fila donde coincidan programa y competencia."""
    if not (col_prog and col_comp and valor_programa and valor_competencia):
        return {}
    if col_prog not in df.columns or col_comp not in df.columns:
        return {}
    fila = df[(df[col_prog].astype(str) == str(valor_programa)) &
              (df[col_comp].astype(str) == str(valor_competencia))]
    if fila.empty:
        return {}
    row = fila.iloc[0]
    datos = {}
    if col_cod_prog and col_cod_prog in df.columns:
        val = row.get(col_cod_prog)
        datos["codigo_programa"] = str(val) if pd.notna(val) else ""
    if col_cod_comp and col_cod_comp in df.columns:
        val = row.get(col_cod_comp)
        datos["codigo_competencia"] = str(val) if pd.notna(val) else ""
    if cols_rap:
        raps = []
        for c in cols_rap:
            val = row.get(c)
            if pd.notna(val) and str(val).strip():
                raps.append(str(val).strip())
        datos["raps"] = raps
    return datos


# ============ ESTADO ============
def init_state():
    defaults = {
        "hojas": None,
        "mapeo": {},
        "raps_guardados": cargar_raps(),
        "ultimos_archivos": {},  # {tipo: path} de archivos generados en la última corrida
        "competencia_seleccionada_key": None,  # para saber si cambió y auto-llenar
        "planeacion_filas": None,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v


init_state()


# ============ SIDEBAR ============
with st.sidebar:
    st.markdown("### 📘 ProfeNaturales SENA")
    st.markdown("**Generador con IA (Gemini)**")
    st.markdown("---")
    seccion = st.radio(
        "Navegación",
        ["🆕 Nueva guía", "📋 Planes de Trabajo", "🗓️ Planeación Pedagógica",
         "📄 Proyectos Formativos",
         "🤖 Configurar IA", "✉️ Configurar correo",
         "🎨 Prompts de la IA", "⚙️ Cargar competencias",
         "💾 Guías guardadas", "📚 RAPs guardados", "ℹ️ Ayuda"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    cfg = cargar_config()
    if cfg.get("gemini_api_key"):
        st.success("🤖 IA configurada")
    else:
        st.warning("⚠️ IA sin configurar")
    st.caption("Datos guardados en `data/`.")


# ============ HELPER: GENERAR EXCEL DE PLANTILLA ============
def excel_plantilla_bytes() -> bytes:
    """Genera un Excel de plantilla con la estructura correcta para el instructor."""
    data = {
        "Programa": [
            "Técnico en Integración de Operaciones Logísticas",
            "Técnico en Cocina",
            "Técnico en Seguridad Digital",
            "Tecnólogo en Gestión Documental",
            "Técnico en Programación de Software",
        ],
        "Codigo Programa": ["137136", "227501", "228120", "228101", "228106"],
        "Competencia": [
            "Aplicar conocimientos de las ciencias naturales de acuerdo con situaciones del contexto productivo y social",
            "Aplicar conocimientos de matemáticas en procesos de cocina",
            "Aplicar conocimientos de las ciencias naturales en seguridad electrónica",
            "Procesar la información de acuerdo con las necesidades organizacionales",
            "Aplicar la lógica matemática en el desarrollo de software",
        ],
        "Codigo Competencia": ["220201501", "220201502", "220201501", "210301027", "220201503"],
        "RAP1": [
            "APLICACIÓN DE CONOCIMIENTOS DE LAS CIENCIAS NATURALES DE ACUERDO CON SITUACIONES DEL CONTEXTO PRODUCTIVO Y SOCIAL",
            "Realizar cálculos de proporciones para preparaciones culinarias",
            "Identificar principios físicos aplicados a sistemas de seguridad",
            "Clasificar documentos según normas archivísticas",
            "Aplicar operadores lógicos en algoritmos básicos",
        ],
        "RAP2": [
            "ORGANIZAR PROCESO PRODUCTIVO DE FORMA ORDENADA Y SISTEMÁTICA SEGÚN LOS CAMBIOS FÍSICOS QUE OCURREN EN EL CONTEXTO",
            "Aplicar unidades de medida en recetas estandarizadas",
            "Calcular potencias eléctricas en cámaras de vigilancia",
            "Digitalizar documentos usando herramientas ofimáticas",
            "Diseñar diagramas de flujo con estructuras condicionales",
        ],
        "RAP3": [
            "INTERPRETAR LOS CAMBIOS QUE SE PRESENTAN EN LOS CUERPOS SEGÚN LOS PRINCIPIOS Y LEYES",
            "Ajustar recetas según número de porciones",
            "Verificar transformaciones de energía en sistemas de vigilancia",
            "Aplicar tablas de retención documental",
            "Implementar ciclos en programas sencillos",
        ],
        "RAP4": [
            "PROPONER ACCIONES DE MEJORA EN SU CONTEXTO DE ACUERDO CON PRINCIPIOS FÍSICOS",
            "Optimizar costos de recetas mediante cálculos matemáticos",
            "Proponer mejoras energéticas en sistemas de seguridad",
            "Proponer mejoras al sistema de gestión documental",
            "Depurar código aplicando lógica matemática",
        ],
    }
    df = pd.DataFrame(data)
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Competencias", index=False)
    return buf.getvalue()


# ============ SECCIÓN: CARGAR COMPETENCIAS ============
def seccion_cargar_competencias():
    st.header("⚙️ Cargar archivo de competencias")

    with st.expander("📋 ¿Cómo debe estar estructurado mi Excel?", expanded=True):
        st.markdown("""
El Excel debe tener **una fila por cada competencia** (no una fila por RAP).

**Columnas requeridas:**
| Programa | Codigo Programa | Competencia | Codigo Competencia | RAP1 | RAP2 | RAP3 | RAP4 |
|----------|-----------------|-------------|--------------------|------|------|------|------|
| Técnico en Logística | 137136 | Aplicar conocimientos... | 220201501 | (texto RAP 1) | (texto RAP 2) | (texto RAP 3) | (texto RAP 4) |

**Notas:**
- Los nombres exactos de las columnas no importan — la app te deja mapearlas después.
- La columna **Codigo Competencia** es opcional.
- Si una competencia tiene solo 3 RAPs, deja **RAP4** vacío.
- Si tiene más de 4, agrega **RAP5, RAP6**, etc. La app los detecta automáticamente.
        """)
        st.download_button(
            label="⬇️ Descargar plantilla Excel de ejemplo",
            data=excel_plantilla_bytes(),
            file_name="plantilla_competencias_ProfeNaturales.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    st.markdown("---")
    tab1, tab2 = st.tabs(["📤 Subir Excel", "🔗 Desde Google Drive"])

    with tab1:
        archivo = st.file_uploader("Selecciona tu Excel (.xlsx)", type=["xlsx"])
        if archivo:
            try:
                hojas = leer_excel_bytes(archivo.getvalue())
                st.session_state.hojas = hojas
                st.success(f"✅ {len(hojas)} hoja(s) cargada(s): {', '.join(hojas.keys())}")
            except Exception as e:
                st.error(f"Error: {e}")

    with tab2:
        url = st.text_input("URL de Google Drive (compartida como pública)",
                            placeholder="https://drive.google.com/file/d/XXX/view")
        if st.button("Descargar") and url:
            try:
                with st.spinner("Descargando..."):
                    contenido = descargar_desde_drive(url)
                hojas = leer_excel_bytes(contenido)
                st.session_state.hojas = hojas
                st.success(f"✅ Cargado. {len(hojas)} hoja(s)")
            except Exception as e:
                st.error(f"Error: {e}")

    if st.session_state.hojas:
        st.markdown("---")
        st.subheader("Vista previa")
        for nombre, df in st.session_state.hojas.items():
            with st.expander(f"Hoja: {nombre} ({len(df)} filas)"):
                st.dataframe(df.head(10), use_container_width=True)

        st.markdown("---")
        st.subheader("🎯 Mapeo de columnas")
        st.caption("Indica qué columna del Excel corresponde a cada campo. Se guarda para próximas veces.")

        nombre_hoja = st.selectbox("Hoja a usar", list(st.session_state.hojas.keys()))
        df = st.session_state.hojas[nombre_hoja]
        cols = [""] + list(df.columns)

        # Detección automática de columnas RAP
        cols_rap_detectadas = detectar_columnas_rap(df)
        if cols_rap_detectadas:
            st.info(f"🎉 Detecté automáticamente **{len(cols_rap_detectadas)}** columnas de RAP: "
                    f"{', '.join(str(c) for c in cols_rap_detectadas)}")

        c1, c2 = st.columns(2)
        with c1:
            col_prog = st.selectbox("Columna → Programa", cols, key="col_prog",
                                    index=cols.index("Programa") if "Programa" in cols else 0)
            col_cod_prog = st.selectbox("Columna → Código Programa", cols, key="col_cod_prog",
                                        index=cols.index("Codigo Programa") if "Codigo Programa" in cols else 0)
            col_comp = st.selectbox("Columna → Competencia", cols, key="col_comp",
                                    index=cols.index("Competencia") if "Competencia" in cols else 0)
        with c2:
            col_cod_comp = st.selectbox("Columna → Código Competencia (opcional)", cols, key="col_cod_comp",
                                        index=cols.index("Codigo Competencia") if "Codigo Competencia" in cols else 0)

        st.session_state.mapeo = {
            "hoja": nombre_hoja,
            "programa": col_prog,
            "codigo_programa": col_cod_prog,
            "competencia": col_comp,
            "codigo_competencia": col_cod_comp,
            "cols_rap": cols_rap_detectadas,
        }

        if col_prog and col_comp and cols_rap_detectadas:
            st.success("✅ Mapeo listo. Ahora ve a **🆕 Nueva guía**.")


# ============ SECCIÓN: NUEVA GUÍA ============
def seccion_nueva_guia():
    st.header("🆕 Nueva Guía de Aprendizaje")

    cli_ia = obtener_cliente_ia()
    if cli_ia is None:
        st.info("💡 **Tip:** Configura la IA en **🤖 Configurar IA** para generar contenido automáticamente. "
                "Sin IA, puedes llenar todo manualmente.")

    # ---- Botón mágico: generar TODO con IA ----
    gen_todo = False
    extras_todo = {}
    if cli_ia:
        st.markdown("### ⚡ Generar TODO con IA")
        st.caption("Llena solo los datos básicos (programa, competencia, RAPs) y la IA generará todo.")

        with st.expander("💬 Instrucciones extras para la IA (opcional)"):
            st.caption("Estas instrucciones se agregan al prompt base solo para esta generación.")
            col_a, col_b = st.columns(2)
            with col_a:
                extras_todo["presentacion"] = st.text_input("Para la Presentación:", key="extra_all_pres",
                                                            placeholder="Ej: más profesional, corta y breve")
                extras_todo["3.1"] = st.text_input("Para la Actividad 3.1:", key="extra_all_31",
                                                   placeholder="Ej: usar dinámica grupal")
                extras_todo["3.2"] = st.text_input("Para la Actividad 3.2:", key="extra_all_32",
                                                   placeholder="Ej: incluir video de YouTube")
                extras_todo["glosario"] = st.text_input("Para el Glosario:", key="extra_all_glo",
                                                        placeholder="Ej: 10 términos, no 8")
            with col_b:
                extras_todo["3.3"] = st.text_input("Para la Actividad 3.3:", key="extra_all_33",
                                                   placeholder="Ej: agregar ejercicios de peso muerto")
                extras_todo["3.4"] = st.text_input("Para la Actividad 3.4:", key="extra_all_34",
                                                   placeholder="Ej: entrega escrita en vez de video")
                extras_todo["referentes"] = st.text_input("Para los Referentes:", key="extra_all_ref",
                                                          placeholder="Ej: incluir norma ISO 9001")

        gen_todo = st.button("🪄 Generar todo el contenido de la guía",
                             type="primary", use_container_width=True)

    # ---- CARGAR DESDE PROYECTO FORMATIVO (nuevo) ----
    proyectos_disponibles = cargar_proyectos(PROYECTOS_FILE)
    if proyectos_disponibles:
        st.markdown("---")
        st.subheader("📄 Cargar datos desde Proyecto Formativo (opcional)")
        st.caption("Si tienes proyectos formativos cargados, puedes seleccionar uno "
                   "para auto-llenar programa, fase, actividad, competencia y RAPs.")

        with st.expander("🔽 Seleccionar desde Proyecto Formativo", expanded=False):
            seleccion = selector_cascada_proyecto(key_prefix="ng")
            if seleccion.get("competencia") and st.button(
                "✅ Aplicar selección al formulario", use_container_width=True):
                proy = seleccion["proyecto"]
                comp = seleccion["competencia"]
                st.session_state.form_programa = proy.get("programa_formacion", "")
                st.session_state.form_codigo_prog = proy.get("codigo_programa_sofia", "")
                st.session_state.form_proyecto = proy.get("nombre_proyecto", "")
                st.session_state.form_fase = seleccion["fase"]["nombre"]
                st.session_state.form_actividad_proyecto = seleccion["actividad"]["nombre"]
                st.session_state.form_competencia_sel = comp["nombre"]
                st.session_state.form_codigo_comp = comp["codigo"]
                # Cargar RAPs
                for i, rap in enumerate(seleccion["raps"]):
                    st.session_state[f"rap_{i}"] = f"{rap['codigo']} - {rap['nombre']}"
                st.session_state.n_raps_detectados = len(seleccion["raps"])
                st.success("✅ Datos aplicados al formulario. Revísalo abajo.")
                st.rerun()

    # ---- PASO 1: Programa y competencia ----
    st.subheader("Paso 1 · Programa y competencia")

    tiene_excel = bool(st.session_state.hojas and st.session_state.mapeo.get("programa")
                       and st.session_state.mapeo.get("competencia"))
    datos_precargados = {}

    if tiene_excel:
        st.info("📊 Datos cargados desde tu Excel. Al seleccionar una competencia, "
                "se auto-llenan los RAPs y el código del programa.")
        df = st.session_state.hojas[st.session_state.mapeo["hoja"]]
        mapeo = st.session_state.mapeo
        col_prog = mapeo["programa"]
        col_comp = mapeo["competencia"]

        # Filtrar valores únicos
        programas_disponibles = [""] + sorted(df[col_prog].dropna().astype(str).unique().tolist()) if col_prog in df.columns else [""]

        col1, col2 = st.columns(2)
        with col1:
            programa_sel = st.selectbox("Programa de formación", programas_disponibles, key="form_programa")

        # Competencias filtradas por programa seleccionado
        if programa_sel and col_comp in df.columns:
            competencias_del_programa = df[df[col_prog].astype(str) == programa_sel][col_comp].dropna().astype(str).unique().tolist()
            competencias_disponibles = [""] + sorted(competencias_del_programa)
        else:
            competencias_disponibles = [""]
        with col2:
            competencia_sel = st.selectbox("Competencia", competencias_disponibles, key="form_competencia_sel")

        # Si cambió la selección, buscar datos y auto-llenar
        clave_actual = f"{programa_sel}||{competencia_sel}"
        if clave_actual and clave_actual != st.session_state.competencia_seleccionada_key:
            datos_precargados = obtener_datos_competencia(
                df, col_prog, col_comp, programa_sel, competencia_sel,
                col_cod_prog=mapeo.get("codigo_programa"),
                col_cod_comp=mapeo.get("codigo_competencia"),
                cols_rap=mapeo.get("cols_rap", []),
            )
            st.session_state.competencia_seleccionada_key = clave_actual
            # Guardar en session_state para que persista
            if "codigo_programa" in datos_precargados:
                st.session_state.form_codigo_prog = datos_precargados["codigo_programa"]
            if "codigo_competencia" in datos_precargados:
                st.session_state.form_codigo_comp = datos_precargados["codigo_competencia"]
            if "raps" in datos_precargados:
                for i, rap in enumerate(datos_precargados["raps"]):
                    st.session_state[f"rap_{i}"] = rap
                st.session_state.n_raps_detectados = len(datos_precargados["raps"])
                st.rerun()
    else:
        st.warning("⚠️ Aún no has cargado un Excel de competencias. "
                   "Ve a **⚙️ Cargar competencias** primero (o llena manualmente).")
        col1, col2 = st.columns(2)
        with col1:
            programa_sel = st.text_input("Programa de formación", key="form_programa")
        with col2:
            competencia_sel = st.text_input("Competencia", key="form_competencia_sel")

    # Código del programa y código de competencia
    col1, col2 = st.columns(2)
    with col1:
        codigo_prog = st.text_input("Código del programa", key="form_codigo_prog")
    with col2:
        codigo_comp = st.text_input("Código de la competencia (opcional)", key="form_codigo_comp")

    # Construir el string "competencia" completo
    if codigo_comp and competencia_sel:
        competencia_completa = f"{codigo_comp} — {competencia_sel}"
    else:
        competencia_completa = competencia_sel
    st.session_state.form_competencia = competencia_completa

    # ---- PASO 2: Proyecto formativo ----
    st.subheader("Paso 2 · Proyecto formativo")
    col1, col2 = st.columns([3, 1])
    with col1:
        proyecto = st.text_area("Nombre del proyecto formativo", height=80, key="form_proyecto")
    with col2:
        fase = st.text_input(
            "Fase del proyecto",
            value=st.session_state.get("form_fase", "Planeación"),
            key="form_fase",
            help="Escribe el nombre de la fase tal como aparece en tu proyecto formativo. "
                 "Ej: ANÁLISIS, PLANEACIÓN, PLANEAR, DISEÑO, EJECUCIÓN, EVALUACIÓN."
        )
    actividad_proyecto = st.text_area("Actividad del proyecto formativo", height=70,
                                      key="form_actividad_proyecto")

    # ---- PASO 3: RAPs ----
    st.subheader("Paso 3 · Resultados de Aprendizaje (RAP)")

    # Determinar cuántos RAPs mostrar
    n_raps_default = st.session_state.get("n_raps_detectados", 4)
    if datos_precargados.get("raps"):
        n_raps_default = len(datos_precargados["raps"])

    n_raps = st.number_input("¿Cuántos RAP tiene esta competencia?", 1, 10, value=n_raps_default)
    raps_input = []
    for i in range(n_raps):
        rap = st.text_area(f"RAP {i+1}", height=60, key=f"rap_{i}")
        raps_input.append(rap.strip())

    guardar_estos = st.checkbox("💾 Guardar estos RAP para la competencia (para reutilizar)", value=True)

    # ---- PASO 4: Datos de la guía ----
    st.subheader("Paso 4 · Datos de esta guía")
    col1, col2 = st.columns(2)
    with col1:
        duracion = st.text_input("Duración total", key="form_duracion",
                                 value="8 horas (4 h directas + 4 h autónomas)")
        rap_focal = st.selectbox("¿Qué RAP trabaja principalmente esta guía?",
                                 ["Todos"] + [f"RAP {i+1}" for i in range(n_raps)])
    with col2:
        autor = st.text_input("Autor (instructor)",
                              value=cfg.get("smtp_nombre") or cfg.get("autor_default", "Carlos"))
        fecha_str = st.date_input("Fecha", value=date.today()).isoformat()

    # -- Ejecutar "Generar TODO" si se pulsó --
    if gen_todo:
        if not (programa_sel and competencia_completa and any(raps_input)):
            st.error("Para generar todo, llena al menos: programa, competencia y RAPs.")
        else:
            datos_ini = {
                "programa": programa_sel, "codigo_programa": codigo_prog,
                "proyecto_formativo": proyecto, "fase_proyecto": fase,
                "actividad_proyecto": actividad_proyecto,
                "competencia": competencia_completa, "raps": [r for r in raps_input if r],
                "duracion": duracion,
            }
            with st.spinner("🪄 La IA está diseñando toda tu guía... (30-90 segundos)"):
                try:
                    resultado = cli_ia.generar_todo(datos_ini, instrucciones_extra=extras_todo)
                    st.session_state.form_presentacion = resultado.get("presentacion", "")
                    for k, act in resultado.get("actividades", {}).items():
                        aplicar_actividad_a_form(k, act)
                    st.session_state.form_glosario = "\n".join(
                        f"{t} | {d}" for t, d in resultado.get("glosario", [])
                    )
                    st.session_state.form_referentes = "\n".join(resultado.get("referentes", []))
                    st.success("✅ Contenido generado. Revisa y ajusta lo que necesites.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al generar: {e}")

    # ---- Presentación ----
    st.markdown("---")
    st.subheader("Paso 5 · Presentación")
    if cli_ia:
        col_btn, col_extra = st.columns([1, 2])
        with col_btn:
            gen_pres_btn = st.button("🤖 Generar presentación con IA",
                                     key="gen_pres", use_container_width=True)
        with col_extra:
            extra_pres = st.text_input("💬 Instrucción extra (opcional):", key="extra_pres",
                                       placeholder="Ej: más profesional, corta y breve",
                                       label_visibility="collapsed")
        if gen_pres_btn:
            datos_actuales = datos_desde_form()
            with st.spinner("Generando..."):
                try:
                    st.session_state.form_presentacion = cli_ia.generar_presentacion(
                        datos_actuales, instrucciones_extra=extra_pres)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

    presentacion = st.text_area(
        "Presentación al aprendiz (2–3 párrafos)",
        height=180, key="form_presentacion",
        placeholder="Apreciado aprendiz, sea bienvenido..."
    )

    # ---- PASO 6: Actividades ----
    st.subheader("Paso 6 · Actividades de aprendizaje")
    labels = {
        "3.1": "3.1 Reflexión inicial",
        "3.2": "3.2 Contextualización",
        "3.3": "3.3 Apropiación",
        "3.4": "3.4 Transferencia",
    }
    actividades = {}
    for key, label in labels.items():
        with st.expander(f"📝 {label}", expanded=(key == "3.1")):
            if cli_ia:
                col_btn, col_extra = st.columns([1, 2])
                with col_btn:
                    gen_act_btn = st.button(f"🤖 Generar {key} con IA", key=f"gen_{key}",
                                            use_container_width=True)
                with col_extra:
                    extra_act = st.text_input(f"💬 Instrucción extra ({key}):", key=f"extra_{key}",
                                              placeholder="Ej: hacer más práctica",
                                              label_visibility="collapsed")
                if gen_act_btn:
                    datos_actuales = datos_desde_form()
                    with st.spinner(f"Diseñando actividad {key}..."):
                        try:
                            act_gen = cli_ia.generar_actividad(
                                key, datos_actuales,
                                actividades_previas=datos_actuales.get("actividades", {}),
                                instrucciones_extra=extra_act,
                            )
                            aplicar_actividad_a_form(key, act_gen)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")

            actividades[key] = {
                "descripcion": st.text_area(f"Descripción ({key})", height=100, key=f"desc_{key}"),
                "ambiente": st.text_input(f"Ambiente ({key})", key=f"amb_{key}"),
                "estrategias": st.text_input(f"Estrategias ({key})", key=f"est_{key}"),
                "materiales": st.text_input(f"Materiales ({key})", key=f"mat_{key}"),
                "apoyo": st.text_area(f"Material de apoyo ({key})", height=60, key=f"apo_{key}"),
                "evidencias": st.text_area(f"Evidencias ({key})", height=60, key=f"ev_{key}")
                                            if key in ("3.3", "3.4") else "",
                "instrumentos": st.text_input(f"Instrumentos de evaluación ({key})", key=f"ins_{key}")
                                              if key in ("3.3", "3.4") else "",
                "duracion": st.text_input(f"Duración ({key})", key=f"dur_{key}"),
            }

    # ---- PASO 7: Glosario y referentes ----
    st.subheader("Paso 7 · Glosario y referentes")
    col_a, col_b = st.columns(2)
    with col_a:
        if cli_ia:
            gen_glo_btn = st.button("🤖 Generar glosario con IA",
                                    key="gen_glo", use_container_width=True)
            extra_glo = st.text_input("💬 Instrucción extra (glosario):", key="extra_glo",
                                      placeholder="Ej: 10 términos",
                                      label_visibility="collapsed")
            if gen_glo_btn:
                datos_actuales = datos_desde_form()
                datos_actuales["actividades"] = actividades
                with st.spinner("Generando glosario..."):
                    try:
                        glosa = cli_ia.generar_glosario(datos_actuales, instrucciones_extra=extra_glo)
                        st.session_state.form_glosario = "\n".join(f"{t} | {d}" for t, d in glosa)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        glosario_raw = st.text_area(
            "Glosario (formato `término | definición`, uno por línea)",
            height=200, key="form_glosario",
            placeholder="Fuerza (F) | Interacción capaz de modificar el estado de movimiento...",
        )

    with col_b:
        if cli_ia:
            gen_ref_btn = st.button("🤖 Generar referentes con IA",
                                    key="gen_ref", use_container_width=True)
            extra_ref = st.text_input("💬 Instrucción extra (referentes):", key="extra_ref",
                                      placeholder="Ej: incluir norma ICONTEC",
                                      label_visibility="collapsed")
            if gen_ref_btn:
                datos_actuales = datos_desde_form()
                with st.spinner("Generando referentes..."):
                    try:
                        refs = cli_ia.generar_referentes(datos_actuales, instrucciones_extra=extra_ref)
                        st.session_state.form_referentes = "\n".join(refs)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

        referentes_raw = st.text_area(
            "Referentes bibliográficos (uno por línea)",
            height=200, key="form_referentes",
        )

    st.markdown("---")

    # ---- GENERAR DOCUMENTOS ----
    st.subheader("🚀 Generar los 3 documentos")
    generar_btn = st.button("🎯 Generar Guía del Aprendiz + Guía del Instructor + Rúbricas",
                            type="primary", use_container_width=True)

    if generar_btn:
        if not programa_sel or not competencia_completa:
            st.error("Programa y competencia son obligatorios.")
        else:
            _generar_los_tres_documentos(
                programa_sel, codigo_prog, proyecto, fase, actividad_proyecto,
                competencia_completa, raps_input, duracion, presentacion,
                actividades, glosario_raw, referentes_raw, autor, fecha_str,
                codigo_comp, rap_focal, guardar_estos,
            )

    # ---- MOSTRAR ARCHIVOS GENERADOS (persistentes) ----
    if st.session_state.get("ultimos_archivos"):
        st.markdown("---")
        st.success("✅ Documentos generados. Descarga cada uno abajo:")
        _render_botones_descarga(st.session_state.ultimos_archivos)


def _generar_los_tres_documentos(programa, codigo_prog, proyecto, fase, actividad_proyecto,
                                 competencia, raps_input, duracion, presentacion,
                                 actividades, glosario_raw, referentes_raw, autor, fecha_str,
                                 codigo_comp, rap_focal, guardar_estos):
    """Genera los 3 archivos, los guarda en disco y en session_state."""
    if guardar_estos:
        codigo_comp_key = codigo_comp or _extraer_codigo(competencia)
        if codigo_comp_key:
            st.session_state.raps_guardados[codigo_comp_key] = [r for r in raps_input if r]
            guardar_raps(st.session_state.raps_guardados)

    glosario = []
    for linea in glosario_raw.splitlines():
        if "|" in linea:
            partes = linea.split("|", 1)
            glosario.append((partes[0].strip(), partes[1].strip()))
    referentes = [r.strip() for r in referentes_raw.splitlines() if r.strip()]

    datos = {
        "programa": programa, "codigo_programa": codigo_prog,
        "proyecto_formativo": proyecto, "fase_proyecto": fase,
        "actividad_proyecto": actividad_proyecto, "competencia": competencia,
        "raps": [r for r in raps_input if r], "duracion": duracion,
        "presentacion": presentacion, "actividades": actividades,
        "evidencias_tabla": _armar_tabla_evidencias(actividades, fase),
        "glosario": glosario, "referentes": referentes,
        "autor_nombre": autor, "autor_cargo": "Instructor",
        "autor_dependencia": "Centro de Formación SENA", "autor_fecha": fecha_str,
    }

    # Guardar en carpeta persistente
    safe_prog = re.sub(r"[^\w\-]", "_", programa)[:40]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = f"{safe_prog}_{fecha_str}_{timestamp}"

    try:
        p_aprendiz = str(GUIAS_DIR / f"{prefix}_Guia_Aprendiz.docx")
        p_instructor = str(GUIAS_DIR / f"{prefix}_Guia_Instructor.docx")
        p_rubricas = str(GUIAS_DIR / f"{prefix}_Rubricas.docx")

        with st.spinner("Generando documentos..."):
            generar_guia_aprendizaje(datos, p_aprendiz)
            generar_guia_instructor(datos, p_instructor)
            generar_rubricas(datos, p_rubricas)

        # Guardar los paths en session_state para que persistan al re-ejecutar
        st.session_state.ultimos_archivos = {
            "aprendiz": p_aprendiz,
            "instructor": p_instructor,
            "rubricas": p_rubricas,
        }

        # Historial - guardar TODOS los datos para que el Plan de Trabajo los tenga
        guias = cargar_guias_historial()
        guias.append({
            "fecha": fecha_str,
            "timestamp": timestamp,
            "programa": programa,
            "codigo_programa": codigo_prog,
            "proyecto_formativo": proyecto,
            "actividad_proyecto": actividad_proyecto,
            "competencia": competencia,
            "codigo_competencia": codigo_comp,
            "fase": fase,
            "rap_focal": rap_focal,
            "autor": autor,
            "archivo_aprendiz": p_aprendiz,
            "archivo_instructor": p_instructor,
            "archivo_rubricas": p_rubricas,
            "raps": [r for r in raps_input if r],
        })
        guardar_guias_historial(guias)

    except Exception as e:
        st.error(f"Error: {e}")
        st.exception(e)


def _render_botones_descarga(archivos: dict):
    """Muestra 3 botones de descarga leyendo desde disco."""
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    c1, c2, c3 = st.columns(3)
    with c1:
        _boton_descarga(archivos.get("aprendiz"), "📥 Guía del Aprendiz", mime)
    with c2:
        _boton_descarga(archivos.get("instructor"), "📥 Guía del Instructor", mime)
    with c3:
        _boton_descarga(archivos.get("rubricas"), "📥 Rúbricas", mime)


def _boton_descarga(path: str, label: str, mime: str, key_extra: str = ""):
    if not path:
        return
    p = Path(path)
    if not p.exists():
        st.warning(f"Archivo no encontrado: {p.name}")
        return
    with open(p, "rb") as f:
        st.download_button(label, f.read(), file_name=p.name, mime=mime,
                           use_container_width=True, key=f"dl_{key_extra}_{p.name}")


# ============ SECCIÓN: GUÍAS GUARDADAS ============
def seccion_guias_guardadas():
    st.header("💾 Guías generadas")
    guias = cargar_guias_historial()
    if not guias:
        st.info("Aún no has generado ninguna guía.")
        return

    st.caption(f"Total: {len(guias)} guía(s) generada(s).")
    mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    # Mostrar de la más reciente a la más antigua
    for idx, guia in enumerate(reversed(guias)):
        original_idx = len(guias) - 1 - idx
        with st.expander(
            f"📘 {guia.get('programa', 'Sin programa')} — {guia.get('fecha', '')}",
            expanded=(idx == 0)
        ):
            col_info, col_del = st.columns([4, 1])
            with col_info:
                st.markdown(f"**Competencia:** {guia.get('competencia', '')}")
                st.markdown(f"**Fase:** {guia.get('fase', '')} · **RAP focal:** {guia.get('rap_focal', '')}")
                st.markdown(f"**Autor:** {guia.get('autor', '')} · **Fecha:** {guia.get('fecha', '')}")
            with col_del:
                if st.button("🗑️", key=f"del_guia_{original_idx}", help="Eliminar del historial"):
                    guias_actualizadas = cargar_guias_historial()
                    if original_idx < len(guias_actualizadas):
                        # Intentar borrar los archivos físicos también
                        for k in ("archivo_aprendiz", "archivo_instructor", "archivo_rubricas"):
                            p = guias_actualizadas[original_idx].get(k)
                            if p:
                                try:
                                    Path(p).unlink(missing_ok=True)
                                except Exception:
                                    pass
                        guias_actualizadas.pop(original_idx)
                        guardar_guias_historial(guias_actualizadas)
                        st.rerun()

            st.markdown("**Descargar:**")
            c1, c2, c3 = st.columns(3)
            with c1:
                _boton_descarga(guia.get("archivo_aprendiz"), "📥 Aprendiz", mime,
                                key_extra=f"guia{original_idx}_ap")
            with c2:
                _boton_descarga(guia.get("archivo_instructor"), "📥 Instructor", mime,
                                key_extra=f"guia{original_idx}_in")
            with c3:
                _boton_descarga(guia.get("archivo_rubricas"), "📥 Rúbricas", mime,
                                key_extra=f"guia{original_idx}_ru")


# ============ SECCIÓN: RAPS GUARDADOS ============
def seccion_raps():
    st.header("📚 RAPs guardados por competencia")
    raps = cargar_raps()
    if not raps:
        st.info("Aún no has guardado RAPs. Se guardan automáticamente al generar tu primera guía.")
        return
    for codigo, lista in list(raps.items()):
        with st.expander(f"Competencia {codigo} — {len(lista)} RAP"):
            for i, r in enumerate(lista, 1):
                st.markdown(f"**{i}.** {r}")
            if st.button(f"🗑️ Eliminar", key=f"del_{codigo}"):
                del raps[codigo]
                guardar_raps(raps)
                st.session_state.raps_guardados = raps
                st.rerun()


# ============ SECCIÓN: CONFIGURAR CORREO (SMTP) ============
def seccion_configurar_correo():
    st.header("✉️ Configurar correo (Gmail)")

    st.markdown("""
Para que la app pueda enviar correos a los aprendices, necesita usar tu cuenta de Gmail.

### 🔐 Paso 1: Activar Verificación en 2 pasos
1. Ve a **[myaccount.google.com/security](https://myaccount.google.com/security)**
2. Activa **"Verificación en 2 pasos"** si aún no la tienes
   (es requisito de Google para poder crear contraseñas de aplicación)

### 🔑 Paso 2: Crear contraseña de aplicación
1. Ve a **[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)**
2. En "Nombre de la app" escribe: **Generador Guías SENA**
3. Click en **Crear**
4. Google te muestra una contraseña de **16 caracteres** (ej: `abcd efgh ijkl mnop`)
5. Cópiala tal cual y pégala abajo

**Importante:** esa contraseña de 16 caracteres NO es tu contraseña de Gmail normal. Es una contraseña especial solo para esta app.
""")

    cfg = cargar_config()
    with st.form("form_correo"):
        remitente = st.text_input("Tu correo Gmail",
                                   value=cfg.get("smtp_remitente", ""),
                                   placeholder="cabarriosn@gmail.com")
        contrasena = st.text_input("Contraseña de aplicación (16 caracteres)",
                                    value=cfg.get("smtp_contrasena", ""),
                                    type="password",
                                    placeholder="abcd efgh ijkl mnop")
        nombre_remitente = st.text_input("Tu nombre (cómo aparecerá en el correo)",
                                          value=cfg.get("smtp_nombre",
                                                        cfg.get("autor_default", "Instructor SENA")))

        col1, col2 = st.columns(2)
        with col1:
            guardar_btn = st.form_submit_button("💾 Guardar", type="primary", use_container_width=True)
        with col2:
            probar_btn = st.form_submit_button("🧪 Probar conexión", use_container_width=True)

    if guardar_btn:
        cfg["smtp_remitente"] = remitente.strip()
        cfg["smtp_contrasena"] = contrasena.strip()
        cfg["smtp_nombre"] = nombre_remitente.strip()
        guardar_config(cfg)
        st.success("✅ Configuración de correo guardada.")

    if probar_btn:
        if not remitente or not contrasena:
            st.error("Ingresa correo y contraseña primero.")
        else:
            with st.spinner("Probando conexión..."):
                ok, mensaje = probar_conexion(remitente.strip(), contrasena.strip())
            if ok:
                st.success(f"✅ {mensaje}")
            else:
                st.error(f"❌ {mensaje}")


# ============ SECCIÓN: PLANES DE TRABAJO ============
def seccion_planes_trabajo():
    st.header("📋 Planes de Trabajo Individuales")
    st.caption("Genera un PDF personalizado para cada aprendiz y envíalo por correo.")

    tabs = st.tabs(["1️⃣ Aprendices", "2️⃣ Guía y cronograma", "3️⃣ Generar y enviar"])

    # ---- TAB 1: Cargar aprendices ----
    with tabs[0]:
        _tab_aprendices()

    # ---- TAB 2: Seleccionar guía y cronograma ----
    with tabs[1]:
        _tab_guia_cronograma()

    # ---- TAB 3: Generar y enviar ----
    with tabs[2]:
        _tab_generar_enviar()


def _tab_aprendices():
    st.subheader("Cargar lista de aprendices")

    with st.expander("📋 ¿Cómo debe estar mi Excel de aprendices?", expanded=True):
        st.markdown("""
El Excel debe tener **una fila por aprendiz** con estas columnas:

| Nombre | Apellidos | Correo | Ficha | Programa |
|--------|-----------|--------|-------|----------|
| Juan Camilo | Pérez Rodríguez | juan@correo.com | 3125874 | Técnico en Logística |

**Notas:**
- Los nombres de columnas no importan — te dejamos mapearlas.
- Si tienes una sola columna "Nombre completo", también se puede.
- Puedes filtrar por ficha después.
        """)
        # Botón de descarga de plantilla
        st.download_button(
            "⬇️ Descargar plantilla Excel de aprendices",
            data=_excel_plantilla_aprendices(),
            file_name="plantilla_aprendices.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )

    archivo = st.file_uploader("Sube tu Excel de aprendices (.xlsx)",
                                type=["xlsx"], key="upload_aprendices")
    if archivo:
        try:
            hojas = leer_excel_bytes(archivo.getvalue())
            hoja = st.selectbox("Hoja", list(hojas.keys()), key="hoja_apr")
            df = hojas[hoja]
            st.dataframe(df.head(10), use_container_width=True)

            st.subheader("Mapeo de columnas")
            cols = [""] + list(df.columns)

            def _default(nombres):
                for n in nombres:
                    for c in cols:
                        if str(c).strip().lower() == n.lower():
                            return cols.index(c)
                return 0

            c1, c2 = st.columns(2)
            with c1:
                col_nombre = st.selectbox("Columna → Nombre(s)", cols,
                                           index=_default(["Nombre", "Nombres", "Nombre completo"]),
                                           key="col_nom")
                col_apellidos = st.selectbox("Columna → Apellidos (opcional si Nombre trae ambos)",
                                              cols,
                                              index=_default(["Apellidos", "Apellido"]),
                                              key="col_ap")
                col_correo = st.selectbox("Columna → Correo",
                                           cols,
                                           index=_default(["Correo", "Email", "E-mail", "Correo electrónico"]),
                                           key="col_cor")
            with c2:
                col_ficha = st.selectbox("Columna → Ficha",
                                          cols,
                                          index=_default(["Ficha", "Numero de ficha", "Número de ficha", "N° Ficha"]),
                                          key="col_fic")
                col_programa = st.selectbox("Columna → Programa (opcional)",
                                             cols,
                                             index=_default(["Programa", "Programa de formación"]),
                                             key="col_prog_apr")

            if col_nombre and col_correo and col_ficha:
                # Extraer aprendices
                aprendices = []
                for _, row in df.iterrows():
                    nombre = str(row[col_nombre]) if pd.notna(row[col_nombre]) else ""
                    apellidos = str(row[col_apellidos]) if col_apellidos and pd.notna(row.get(col_apellidos)) else ""
                    correo = str(row[col_correo]) if pd.notna(row[col_correo]) else ""
                    ficha = str(row[col_ficha]) if pd.notna(row[col_ficha]) else ""
                    programa = str(row[col_programa]) if col_programa and pd.notna(row.get(col_programa)) else ""
                    if nombre and correo:
                        aprendices.append({
                            "nombre": nombre.strip(),
                            "apellidos": apellidos.strip(),
                            "correo": correo.strip(),
                            "ficha": ficha.strip(),
                            "programa": programa.strip(),
                        })

                st.success(f"✅ Detecté {len(aprendices)} aprendice(s) válidos.")

                # Filtrar por ficha
                fichas_disponibles = sorted(set(a["ficha"] for a in aprendices if a["ficha"]))
                fichas_seleccionadas = st.multiselect(
                    "Filtrar por ficha (deja vacío para incluir todas)",
                    fichas_disponibles,
                    default=[],
                )
                if fichas_seleccionadas:
                    aprendices = [a for a in aprendices if a["ficha"] in fichas_seleccionadas]

                st.session_state.aprendices_cargados = aprendices
                guardar_json(APRENDICES_FILE, aprendices)
                st.info(f"📌 {len(aprendices)} aprendices listos para el plan de trabajo.")
        except Exception as e:
            st.error(f"Error al leer Excel: {e}")

    # Mostrar aprendices cargados
    if st.session_state.get("aprendices_cargados"):
        aprendices = st.session_state.aprendices_cargados
        st.markdown(f"### Aprendices cargados: {len(aprendices)}")
        st.dataframe(pd.DataFrame(aprendices), use_container_width=True)


def _tab_guia_cronograma():
    st.subheader("Selecciona la guía y define el cronograma")

    guias = cargar_guias_historial()
    if not guias:
        st.warning("⚠️ Primero genera al menos una guía en **🆕 Nueva guía**.")
        return

    # Selector de guía
    opciones_guias = []
    for i, g in enumerate(reversed(guias)):
        opciones_guias.append(f"{g.get('fecha', '')} · {g.get('programa', '')[:50]}")

    idx = st.selectbox("Guía a asignar", range(len(opciones_guias)),
                        format_func=lambda i: opciones_guias[i])
    guia_seleccionada = list(reversed(guias))[idx]
    st.session_state.plan_guia = guia_seleccionada

    st.markdown(f"**Competencia:** {guia_seleccionada.get('competencia', '')}")
    st.markdown(f"**Fase:** {guia_seleccionada.get('fase', '')}")

    # ---- CRONOGRAMA POR RANGO DE FECHAS ----
    st.subheader("📅 Fechas del cronograma")
    st.caption(
        "Todas las 4 actividades tendrán la MISMA fecha de inicio y la MISMA fecha final. "
        "Los aprendices deben cumplirlas dentro de este rango de tiempo."
    )

    col1, col2 = st.columns(2)
    with col1:
        fecha_inicio = st.date_input(
            "Fecha de inicio",
            value=st.session_state.get("plan_fecha_inicio_val", date.today()),
            key="plan_fecha_inicio",
            help="Día en que arrancan las actividades para todos los aprendices.",
        )
    with col2:
        fecha_final = st.date_input(
            "Fecha final (entrega)",
            value=st.session_state.get("plan_fecha_final_val",
                                       date.today().replace(month=min(date.today().month+2, 12))),
            key="plan_fecha_final",
            help="Fecha límite de entrega de todas las actividades.",
        )

    # Validación básica
    if fecha_final < fecha_inicio:
        st.error("⚠️ La fecha final no puede ser anterior a la fecha de inicio.")
        return

    # Contar días hábiles del rango como información al instructor
    dias_habiles = contar_dias_habiles(fecha_inicio, fecha_final)
    dias_totales = (fecha_final - fecha_inicio).days + 1
    fin_de_semana = dias_totales - dias_habiles

    col_a, col_b, col_c = st.columns(3)
    col_a.metric("Días totales", dias_totales)
    col_b.metric("Días hábiles (L–V)", dias_habiles)
    col_c.metric("Fines de semana", fin_de_semana)

    # ---- Descripciones de actividades ----
    st.subheader("📝 Descripción de cada actividad")
    st.caption("Estas descripciones aparecen en el PDF del plan de trabajo de cada aprendiz.")

    actividades_input = {}
    with st.expander("Actividad 3.1 · Reflexión inicial", expanded=False):
        actividades_input["3.1"] = {
            "duracion": "",  # ya no se usa
            "descripcion": st.text_area(
                "Descripción 3.1", height=80, key="desc_apr_31",
                value="Reflexión inicial sobre la situación real del contexto productivo.",
            ),
        }
    with st.expander("Actividad 3.2 · Contextualización", expanded=False):
        actividades_input["3.2"] = {
            "duracion": "",
            "descripcion": st.text_area(
                "Descripción 3.2", height=80, key="desc_apr_32",
                value="Contextualización mediante la introducción del concepto clave.",
            ),
        }
    with st.expander("Actividad 3.3 · Apropiación", expanded=False):
        actividades_input["3.3"] = {
            "duracion": "",
            "descripcion": st.text_area(
                "Descripción 3.3", height=80, key="desc_apr_33",
                value="Apropiación mediante ejercicios prácticos y simuladores.",
            ),
        }
    with st.expander("Actividad 3.4 · Transferencia", expanded=False):
        actividades_input["3.4"] = {
            "duracion": "",
            "descripcion": st.text_area(
                "Descripción 3.4", height=80, key="desc_apr_34",
                value="Transferencia del conocimiento al contexto laboral real, evidencia individual.",
            ),
        }

    # ---- Vista previa del cronograma ----
    if st.button("🔍 Vista previa del cronograma", use_container_width=True):
        crono = calcular_cronograma_por_rango(actividades_input, fecha_inicio, fecha_final)
        df_preview = pd.DataFrame([
            {
                "Actividad": c["titulo"],
                "Descripción": c["descripcion"][:60] + "...",
                "Inicio": c["fecha_inicio"].strftime("%d/%m/%Y"),
                "Entrega": c["fecha_entrega"].strftime("%d/%m/%Y"),
            }
            for c in crono
        ])
        st.dataframe(df_preview, use_container_width=True, hide_index=True)
        st.info(f"📌 Las 4 actividades comparten el mismo rango: "
                f"del **{fecha_inicio.strftime('%d/%m/%Y')}** al **{fecha_final.strftime('%d/%m/%Y')}** "
                f"({dias_habiles} días hábiles).")

    # Guardar en session_state
    st.session_state.plan_actividades = actividades_input
    st.session_state.plan_fecha_inicio_val = fecha_inicio
    st.session_state.plan_fecha_final_val = fecha_final
    st.session_state.plan_modo_cronograma = "rango"


def _tab_generar_enviar():
    st.subheader("Generar PDFs y enviar por correo")

    if not st.session_state.get("aprendices_cargados"):
        st.warning("⚠️ Primero carga los aprendices en la pestaña 1️⃣.")
        return
    if not st.session_state.get("plan_guia"):
        st.warning("⚠️ Primero selecciona una guía en la pestaña 2️⃣.")
        return

    aprendices = st.session_state.aprendices_cargados
    guia = st.session_state.plan_guia
    actividades = st.session_state.get("plan_actividades", {})
    fecha_inicio = st.session_state.get("plan_fecha_inicio_val", date.today())
    fecha_final = st.session_state.get("plan_fecha_final_val", date.today())

    cfg = cargar_config()
    correo_configurado = bool(cfg.get("smtp_remitente") and cfg.get("smtp_contrasena"))

    # Info
    col1, col2, col3 = st.columns(3)
    col1.metric("Aprendices", len(aprendices))
    col2.metric("Guía", guia.get("fase", ""))
    col3.metric("Correo listo", "✅ Sí" if correo_configurado else "❌ No")

    if not correo_configurado:
        st.warning("Para enviar correos, configúralo primero en **✉️ Configurar correo**. "
                   "Igual puedes generar los PDFs y bajarlos.")

    st.markdown("---")

    modo = st.radio("¿Qué quieres hacer?",
                    ["📄 Solo generar los PDFs (para descargar/enviar manual)",
                     "📄+✉️ Generar PDFs y enviar automáticamente por correo"],
                    disabled=not correo_configurado if False else False)

    enviar = "enviar" in modo
    if enviar and not correo_configurado:
        st.error("No puedes enviar sin configurar el correo primero.")
        return

    # Filtro final: elegir a quiénes se genera/envía
    nombres_completos = [f"{a['nombre']} {a['apellidos']}".strip() for a in aprendices]
    seleccionados_idx = st.multiselect(
        "Aprendices a incluir (deja vacío para TODOS)",
        range(len(aprendices)),
        format_func=lambda i: f"{nombres_completos[i]} · {aprendices[i]['correo']} · Ficha {aprendices[i]['ficha']}",
    )
    if not seleccionados_idx:
        seleccionados_idx = list(range(len(aprendices)))

    aprendices_a_procesar = [aprendices[i] for i in seleccionados_idx]

    st.markdown("---")

    if st.button(f"🚀 Procesar {len(aprendices_a_procesar)} aprendices",
                 type="primary", use_container_width=True):
        _procesar_planes(aprendices_a_procesar, guia, actividades, fecha_inicio,
                         fecha_final, enviar, cfg)

    # Mostrar resultados si existen
    if st.session_state.get("planes_generados"):
        st.markdown("---")
        st.subheader("📄 Resultados")
        _mostrar_resultados_planes()


def _procesar_planes(aprendices, guia, actividades, fecha_inicio, fecha_final, enviar, cfg):
    """Genera un PDF por aprendiz, envía correo si aplica, y consolida en Excel."""
    from datetime import datetime as dt

    datos_guia = {
        "programa": guia.get("programa", ""),
        "competencia": guia.get("competencia", ""),
        "proyecto_formativo": guia.get("proyecto_formativo", ""),
        "fase_proyecto": guia.get("fase", ""),
    }
    instructor = {
        "nombre": cfg.get("smtp_nombre") or cfg.get("autor_default", "Instructor SENA"),
        "cargo": "Instructor",
    }

    barra_progreso = st.progress(0.0)
    log_placeholder = st.empty()
    log = []

    # Nuevo: cronograma por rango de fechas (todas las actividades misma fecha)
    cronograma = calcular_cronograma_por_rango(actividades, fecha_inicio, fecha_final)

    planes_generados = []
    total = len(aprendices)
    exitosos = 0
    fallidos_correo = 0

    for i, apr in enumerate(aprendices, start=1):
        try:
            nombre_completo = f"{apr['nombre']} {apr['apellidos']}".strip()
            safe_name = re.sub(r"[^\w]", "_", nombre_completo)[:40]
            timestamp = dt.now().strftime("%Y%m%d_%H%M%S")
            ruta_pdf = str(PLANES_DIR / f"Plan_{safe_name}_{apr['ficha']}_{timestamp}.pdf")

            # 1. Generar PDF
            generar_plan_trabajo(apr, datos_guia, cronograma, instructor, ruta_pdf)
            log.append(f"✅ PDF generado: {nombre_completo}")

            # 2. Enviar correo si aplica
            correo_enviado = False
            fecha_envio = ""
            error_envio = ""
            if enviar:
                try:
                    cuerpo = plantilla_correo_plan_trabajo(
                        nombre_completo, instructor["nombre"],
                        datos_guia["programa"], datos_guia["competencia"]
                    )
                    enviar_correo(
                        remitente=cfg["smtp_remitente"],
                        contrasena_app=cfg["smtp_contrasena"],
                        destinatario=apr["correo"],
                        asunto=f"Plan de Trabajo — {datos_guia['competencia'][:60]}",
                        cuerpo_html=cuerpo,
                        adjuntos=[ruta_pdf],
                        nombre_remitente=cfg.get("smtp_nombre", instructor["nombre"]),
                    )
                    correo_enviado = True
                    fecha_envio = dt.now().strftime("%d/%m/%Y %H:%M")
                    log.append(f"✉️ Correo enviado a: {apr['correo']}")
                except Exception as e:
                    fallidos_correo += 1
                    error_envio = str(e)
                    log.append(f"❌ Error correo {apr['correo']}: {e}")

            planes_generados.append({
                "datos_aprendiz": apr,
                "cronograma": cronograma,
                "archivo_pdf": ruta_pdf,
                "correo_enviado": correo_enviado,
                "fecha_envio": fecha_envio,
                "error_envio": error_envio,
            })
            exitosos += 1

        except Exception as e:
            log.append(f"❌ Error con {apr.get('nombre', '?')}: {e}")

        barra_progreso.progress(i / total)
        log_placeholder.text("\n".join(log[-8:]))

    # Consolidar Excel del portafolio
    timestamp_final = dt.now().strftime("%Y%m%d_%H%M%S")
    ruta_excel = str(PLANES_DIR / f"Portafolio_planes_{timestamp_final}.xlsx")
    try:
        generar_excel_portafolio(planes_generados, datos_guia, instructor, ruta_excel)
        log.append(f"📊 Excel consolidado generado.")
    except Exception as e:
        log.append(f"❌ Error generando Excel: {e}")
        ruta_excel = None

    log_placeholder.text("\n".join(log[-15:]))

    st.session_state.planes_generados = {
        "planes": planes_generados,
        "excel": ruta_excel,
        "exitosos": exitosos,
        "fallidos_correo": fallidos_correo,
        "enviado": enviar,
    }

    st.success(f"✅ {exitosos}/{total} planes generados. "
               f"{'Correos enviados: ' + str(exitosos - fallidos_correo) if enviar else ''}")


def _mostrar_resultados_planes():
    resultado = st.session_state.planes_generados

    # Botón para descargar Excel consolidado
    if resultado.get("excel") and Path(resultado["excel"]).exists():
        st.markdown("### 📊 Excel consolidado (para tu portafolio)")
        with open(resultado["excel"], "rb") as f:
            st.download_button(
                "⬇️ Descargar Excel consolidado",
                f.read(),
                file_name=Path(resultado["excel"]).name,
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )

    st.markdown(f"### 📄 PDFs generados ({len(resultado['planes'])})")
    for i, plan in enumerate(resultado["planes"]):
        apr = plan["datos_aprendiz"]
        nombre = f"{apr['nombre']} {apr['apellidos']}".strip()
        etiqueta_correo = "✅ Enviado" if plan["correo_enviado"] else \
                           ("⏳ Pendiente" if not resultado.get("enviado") else "❌ Falló")
        with st.expander(f"{nombre} · Ficha {apr['ficha']} · {etiqueta_correo}"):
            st.write(f"**Correo:** {apr['correo']}")
            if plan.get("fecha_envio"):
                st.write(f"**Enviado:** {plan['fecha_envio']}")
            if plan.get("error_envio"):
                st.error(f"Error: {plan['error_envio']}")
            if Path(plan["archivo_pdf"]).exists():
                with open(plan["archivo_pdf"], "rb") as f:
                    st.download_button(
                        "⬇️ Descargar PDF",
                        f.read(),
                        file_name=Path(plan["archivo_pdf"]).name,
                        mime="application/pdf",
                        key=f"dl_plan_{i}",
                    )


def _excel_plantilla_aprendices() -> bytes:
    """Genera un Excel de plantilla para el listado de aprendices."""
    df = pd.DataFrame({
        "Nombre": ["Juan Camilo", "María Fernanda", "Andrés Felipe"],
        "Apellidos": ["Pérez Rodríguez", "Gómez Torres", "Ramírez Blanco"],
        "Correo": ["juan.perez@correo.com", "maria.gomez@correo.com", "andres.ramirez@correo.com"],
        "Ficha": ["3125874", "3125874", "3125875"],
        "Programa": [
            "Técnico en Integración de Operaciones Logísticas",
            "Técnico en Integración de Operaciones Logísticas",
            "Técnico en Integración de Operaciones Logísticas",
        ],
    })
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Aprendices", index=False)
    return buf.getvalue()


# ============ SECCIÓN: CONFIGURAR IA ============
def seccion_configurar_ia():
    st.header("🤖 Configurar IA (Gemini)")

    if not GEMINI_DISPONIBLE:
        st.error("⚠️ La librería `google-generativeai` no está instalada.")
        st.code("pip install google-generativeai")
        return

    st.markdown("""
### Cómo obtener tu API key (2 minutos, gratis)
1. Ve a **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)**
2. Inicia sesión con tu cuenta Google
3. Click en **"Crear clave de API"**
4. Copia el texto que empieza con `AIza...`
5. Pégalo abajo y guarda
""")

    cfg = cargar_config()
    api_key_actual = cfg.get("gemini_api_key", "")

    with st.form("form_ia"):
        api_key = st.text_input("API key de Gemini", value=api_key_actual,
                                type="password", placeholder="AIzaSy...")
        modelo_actual = cfg.get("modelo", MODELO_DEFAULT)
        if modelo_actual not in MODELOS_DISPONIBLES:
            modelo_actual = MODELO_DEFAULT
        modelo = st.selectbox("Modelo", MODELOS_DISPONIBLES,
                              index=MODELOS_DISPONIBLES.index(modelo_actual))

        autor_default = st.text_input("Tu nombre (aparece como autor en las guías)",
                                      value=cfg.get("autor_default", "Carlos"))

        col1, col2 = st.columns(2)
        with col1:
            guardar_btn = st.form_submit_button("💾 Guardar", type="primary", use_container_width=True)
        with col2:
            probar_btn = st.form_submit_button("🧪 Probar conexión", use_container_width=True)

    if guardar_btn:
        cfg["gemini_api_key"] = api_key.strip()
        cfg["modelo"] = modelo
        cfg["autor_default"] = autor_default
        guardar_config(cfg)
        st.success("✅ Configuración guardada.")
        st.rerun()

    if probar_btn:
        if not api_key.strip():
            st.error("Ingresa una API key primero.")
        else:
            try:
                cli = GeminiCliente(api_key.strip(), modelo=modelo)
                resp = cli._llamar("Responde solo con: FUNCIONA")
                if "FUNCIONA" in resp.upper():
                    st.success(f"✅ Conexión OK. Modelo: {modelo}.")
                else:
                    st.warning(f"Conexión OK, respuesta inesperada: {resp[:200]}")
            except Exception as e:
                st.error(f"❌ Error: {e}")


# ============ SECCIÓN: PROMPTS DE LA IA ============
def seccion_prompts():
    st.header("🎨 Prompts de la IA")
    st.markdown("""
Edita los **prompts base** que la IA usa para generar cada tipo de contenido.
Se guardan permanentemente y aplican a todas las futuras guías.

💡 **Tip**: Para cambios puntuales de UNA sola guía, usa los cuadros de
**"Instrucciones extras"** en la sección de nueva guía.

**Variables disponibles:**
- `{programa}`, `{codigo_programa}`, `{proyecto_formativo}`, `{competencia}`, `{duracion}`
- `{raps_formateados}`
- Solo en actividad: `{key}`, `{titulo_fase}`, `{contexto_previo}`
- Solo en glosario: `{n_terminos}`, `{presentacion_corta}`, `{actividades_resumen}`
""")

    prompts = cargar_prompts(PROMPTS_FILE)
    etiquetas = {
        "system": ("🧭 Instrucción de sistema (personalidad y reglas)",
                   "Define QUIÉN es la IA y CÓMO se comporta."),
        "presentacion": ("📄 Prompt de Presentación",
                         "Genera los párrafos de bienvenida al aprendiz."),
        "actividad": ("📝 Prompt de Actividad (3.1, 3.2, 3.3, 3.4)",
                      "Genera todos los campos de UNA actividad."),
        "glosario": ("📚 Prompt de Glosario",
                     "Genera la lista de términos clave."),
        "referentes": ("🔗 Prompt de Referentes bibliográficos",
                       "Genera la lista de fuentes bibliográficas."),
        "planeacion": ("🗓️ Prompt de Planeación Pedagógica",
                       "Genera saberes, criterios de evaluación y campos técnicos del formato GFPI-F-134."),
    }

    for clave, (titulo, descripcion) in etiquetas.items():
        with st.expander(titulo, expanded=False):
            st.caption(descripcion)
            nuevo_valor = st.text_area(
                "Contenido del prompt",
                value=prompts.get(clave, PROMPTS_DEFAULT[clave]),
                height=300, key=f"prompt_edit_{clave}",
                label_visibility="collapsed",
            )
            col1, col2, _ = st.columns([1, 1, 3])
            with col1:
                if st.button("💾 Guardar", key=f"save_{clave}", type="primary"):
                    prompts[clave] = nuevo_valor
                    guardar_prompts(PROMPTS_FILE, prompts)
                    st.success("✅ Prompt guardado.")
                    st.rerun()
            with col2:
                if st.button("↩️ Restablecer", key=f"reset_{clave}"):
                    restablecer_prompt(PROMPTS_FILE, clave)
                    st.success("✅ Restablecido.")
                    st.rerun()


# ============ SECCIÓN: AYUDA ============
def seccion_ayuda():
    st.header("ℹ️ Ayuda")
    st.markdown("""
### 🎯 Flujo recomendado

1. **🤖 Configurar IA** → API key gratis de Gemini
2. **✉️ Configurar correo** → Gmail + tu nombre (aparece como firma en el PDF)
3. **📄 Proyectos Formativos** (NUEVO) → sube el PDF del reporte GFPI-F-016 de cada programa
4. **🆕 Nueva guía** → genera Guía Aprendiz + Instructor + Rúbricas
5. **📋 Planes de Trabajo** → PDF individual por aprendiz + envío correo
6. **🗓️ Planeación Pedagógica** → formato oficial GFPI-F-134 (Excel)

### 📄 Documentos que genera la app
- Guía del Aprendiz, Guía del Instructor, Rúbricas (formato GFPI-F-135)
- Plan de Trabajo individual del aprendiz (PDF con firma cursiva)
- Excel consolidado del portafolio del instructor
- Planeación Pedagógica (formato oficial GFPI-F-134)

### 📄 Proyectos Formativos (nuevo)

Sube el PDF del reporte del proyecto formativo (GFPI-F-016). La app extrae automáticamente:
- Información básica (código SOFIA, programa, fichas, tiempo)
- Fases del proyecto (Análisis, Planeación, Ejecución, Evaluación)
- Actividad principal de cada fase
- Todas las competencias con sus RAPs

Luego en **🆕 Nueva guía** y **🗓️ Planeación Pedagógica** aparece un selector cascada:
**Proyecto → Fase → Actividad → Competencia** que auto-llena todo el formulario.

**El PDF se procesa localmente con `pypdf`, NO consume tokens de IA.**
""")


# ============ SECCIÓN: PLANEACIÓN PEDAGÓGICA ============
def seccion_planeacion_pedagogica():
    st.header("🗓️ Planeación Pedagógica (GFPI-F-134)")
    st.caption("Genera el formato oficial de planeación por fase del proyecto formativo. "
               "Cada fase puede contener múltiples competencias.")

    # ---- Cargar desde Proyecto Formativo (opcional) ----
    proyectos_disponibles = cargar_proyectos(PROYECTOS_FILE)
    if proyectos_disponibles:
        with st.expander("📄 Cargar datos desde Proyecto Formativo (opcional)", expanded=False):
            st.caption("Selecciona un proyecto formativo para autocompletar datos generales "
                       "y también generar automáticamente las filas por competencia de la fase.")
            proyectos_lista = ["— Ninguno —"] + [
                f"[{p.get('codigo_proyecto_sofia', '?')}] {p.get('programa_formacion', '')[:60]}"
                for p in proyectos_disponibles
            ]
            idx_p = st.selectbox("Proyecto formativo", range(len(proyectos_lista)),
                                  format_func=lambda i: proyectos_lista[i], key="pln_proy_sel")
            if idx_p > 0:
                proy_sel = proyectos_disponibles[idx_p - 1]

                fases_disponibles = ["— Ninguna —"] + [f["nombre"] for f in proy_sel.get("fases", [])]
                idx_f = st.selectbox("Fase a autocompletar", range(len(fases_disponibles)),
                                      format_func=lambda i: fases_disponibles[i], key="pln_fase_sel")

                if idx_f > 0:
                    fase_sel = proy_sel["fases"][idx_f - 1]
                    total_comp = sum(len(a.get("competencias", []))
                                     for a in fase_sel.get("actividades", []))
                    st.info(f"Al aplicar, se autocompletan los datos generales del proyecto y se "
                            f"generarán **{total_comp} filas** (una por competencia de la fase).")

                    if st.button("✅ Aplicar y generar filas automáticas",
                                 type="primary", use_container_width=True):
                        # Autocompletar datos generales
                        st.session_state.plan_programa = proy_sel.get("programa_formacion", "")
                        st.session_state.plan_cod_prog = f"{proy_sel.get('codigo_programa_sofia', '')} - Versión {proy_sel.get('version_programa', '1')}"
                        st.session_state.plan_proy = proy_sel.get("nombre_proyecto", "")
                        st.session_state.plan_cod_proy = proy_sel.get("codigo_proyecto_sofia", "")
                        # Generar filas
                        nuevas_filas = []
                        for act in fase_sel.get("actividades", []):
                            for comp in act.get("competencias", []):
                                raps_texto = "\n".join(
                                    f"{r['codigo']} - {r['nombre']}" for r in comp.get("raps", [])
                                )
                                nuevas_filas.append({
                                    "fase": fase_sel["nombre"],
                                    "actividad_proyecto": act["nombre"],
                                    "competencia": f"{comp['codigo']} - {comp['nombre']}",
                                    "raps": raps_texto,
                                    "saberes_conceptos": "",
                                    "saberes_proceso": "",
                                    "criterios_evaluacion": "",
                                    "actividades_aprendizaje": "",
                                    "horas_directas": 48,
                                    "horas_independientes": 48,
                                    "descripcion_evidencia": "",
                                    "estrategias_didacticas": "",
                                    "ambiente": "",
                                    "materiales": "",
                                    "instructores": "",
                                    "observaciones": "",
                                })
                        # Limpiar TODAS las session_state keys de widgets de filas viejas
                        # para que los widgets se recreen con los valores de las nuevas filas
                        prefijos_widgets = (
                            "pln_fase_", "pln_act_", "pln_comp_", "pln_raps_",
                            "pln_hd_", "pln_hi_",
                            "pln_saberes_conceptos_", "pln_saberes_proceso_",
                            "pln_criterios_evaluacion_", "pln_actividades_aprendizaje_",
                            "pln_descripcion_evidencia_", "pln_estrategias_didacticas_",
                            "pln_ambiente_", "pln_materiales_", "pln_ins_", "pln_obs_",
                        )
                        keys_a_limpiar = [
                            k for k in list(st.session_state.keys())
                            if any(k.startswith(p) for p in prefijos_widgets)
                        ]
                        for k in keys_a_limpiar:
                            st.session_state.pop(k, None)

                        st.session_state.planeacion_filas = nuevas_filas
                        st.success(f"✅ Datos aplicados. Se generaron {len(nuevas_filas)} filas. "
                                   "Ahora puedes generar los campos técnicos con la IA.")
                        st.rerun()

    st.subheader("1. Datos generales")
    cfg = cargar_config()
    col1, col2 = st.columns(2)
    with col1:
        fecha_elab = st.date_input("Fecha de elaboración", value=date.today(),
                                    key="plan_fecha").isoformat()
        programa = st.text_input("Denominación del Programa",
                                  value="Técnico en Integración de Operaciones Logísticas",
                                  key="plan_programa")
        modalidad = st.selectbox("Modalidad", ["Presencial", "Virtual", "A distancia", "Mixta"],
                                  key="plan_modalidad")
        codigo_programa = st.text_input("Código y versión del Programa",
                                         value="137136 - Versión 1", key="plan_cod_prog")
    with col2:
        proyecto = st.text_area("Nombre del Proyecto Formativo", height=100, key="plan_proy",
                                 value="REGISTRAR EL DESARROLLO DE LAS OPERACIONES DE TRANSPORTE, "
                                       "ALMACENAMIENTO, DISTRIBUCIÓN, MANEJO Y CONTROL DE INVENTARIOS "
                                       "EN EL DEPARTAMENTO DE MANTENIMIENTO DE LA EMPRESA "
                                       "CARBONES DEL CERREJÓN LIMITED")
        codigo_proy = st.text_input("Código del Proyecto",
                                     value="PF-CERREJON-2026-01", key="plan_cod_proy")
        equipo = st.text_input("Equipo Curricular",
                                value=cfg.get("smtp_nombre") or cfg.get("autor_default", "Carlos Barrios"),
                                key="plan_equipo")
        regional = st.text_input("Regional y Centro de Formación",
                                  value="Regional Guajira - Centro Industrial y de Energías Alternativas",
                                  key="plan_regional")

    st.subheader("2. Filas de la tabla (una por competencia)")
    st.caption("Cada fila es una competencia dentro de una fase. Puedes tener varias "
               "competencias en la misma fase, o repartirlas entre fases distintas.")

    if not st.session_state.get("planeacion_filas"):
        st.session_state.planeacion_filas = [_fila_planeacion_vacia()]

    cli_ia = obtener_cliente_ia()

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("➕ Agregar fila", use_container_width=True):
            st.session_state.planeacion_filas.append(_fila_planeacion_vacia())
            st.rerun()
    with col_b:
        if st.button("🗑️ Eliminar última fila", use_container_width=True,
                     disabled=len(st.session_state.planeacion_filas) <= 1):
            st.session_state.planeacion_filas.pop()
            st.rerun()

    filas_editadas = []
    for i, fila in enumerate(st.session_state.planeacion_filas):
        with st.expander(f"📋 Fila {i+1} — {fila.get('competencia', 'Nueva competencia')[:60]}",
                         expanded=(i == 0)):
            c1, c2 = st.columns(2)
            with c1:
                fase = st.text_input(
                    "Fase",
                    value=str(fila.get("fase", "")),
                    key=f"pln_fase_{i}",
                    help="Escribe el nombre exacto de la fase como aparece en tu proyecto formativo. "
                         "Ej: ANÁLISIS, PLANEACIÓN, PLANEAR, DISEÑO, EJECUCIÓN, EVALUACIÓN, etc."
                )
                actividad_proy = st.text_area("Actividad del Proyecto Formativo",
                    value=fila.get("actividad_proyecto", ""), height=80, key=f"pln_act_{i}")
                competencia = st.text_area("Competencia (código + nombre)",
                    value=fila.get("competencia", ""), height=80, key=f"pln_comp_{i}")
                raps_texto = st.text_area("Resultados de Aprendizaje (uno por línea)",
                    value=fila.get("raps", ""), height=120, key=f"pln_raps_{i}")
            with c2:
                horas_dir = st.number_input("Horas trabajo directo", 0, 200,
                    value=int(fila.get("horas_directas", 48)), key=f"pln_hd_{i}")
                horas_ind = st.number_input("Horas trabajo independiente", 0, 200,
                    value=int(fila.get("horas_independientes", 48)), key=f"pln_hi_{i}")

            if cli_ia:
                col_btn_ia, col_dbg = st.columns([2, 1])
                with col_btn_ia:
                    btn_ia = st.button(f"🤖 Generar campos técnicos con IA (Fila {i+1})",
                                        key=f"pln_ia_{i}", use_container_width=True)
                with col_dbg:
                    ver_debug = st.checkbox("🔍 Ver debug", key=f"pln_debug_{i}", value=False)

                if btn_ia:
                    with st.spinner("La IA está diseñando los campos técnicos... (~15 segundos)"):
                        try:
                            # Buscar guías previas para alineación
                            guias_relacionadas = _buscar_guias_de_competencia(competencia)

                            datos_ia = {
                                "programa": programa, "fase": fase,
                                "proyecto_formativo": proyecto,
                                "actividad_proyecto": actividad_proy,
                                "competencia": competencia,
                                "raps": [r.strip() for r in raps_texto.splitlines() if r.strip()],
                                "guias_relacionadas": guias_relacionadas,
                            }
                            resultado = cli_ia.generar_planeacion(datos_ia)

                            # Guardar la respuesta cruda para debug
                            st.session_state[f"pln_ultimo_resultado_{i}"] = {
                                "resultado": resultado,
                                "guias_usadas": len(guias_relacionadas),
                                "competencia": competencia[:80],
                            }

                            # Aplicar los valores al dict de la fila
                            fila_actual = st.session_state.planeacion_filas[i]
                            campos_ia = ("saberes_conceptos", "saberes_proceso",
                                         "criterios_evaluacion", "actividades_aprendizaje",
                                         "descripcion_evidencia", "estrategias_didacticas",
                                         "ambiente", "materiales")
                            aplicados = []
                            no_aplicados = []
                            if isinstance(resultado, dict):
                                for k in campos_ia:
                                    valor = resultado.get(k, "")
                                    if valor:  # solo aplicar si tiene contenido
                                        fila_actual[k] = str(valor).strip()
                                        aplicados.append(k)
                                    else:
                                        no_aplicados.append(k)
                                # Horas
                                for hkey, jkey in [("horas_directas", "horas_directas"),
                                                    ("horas_independientes", "horas_independientes")]:
                                    v = resultado.get(jkey)
                                    if v not in (None, ""):
                                        try:
                                            fila_actual[hkey] = int(v)
                                            aplicados.append(hkey)
                                        except (ValueError, TypeError):
                                            no_aplicados.append(hkey)
                            else:
                                no_aplicados = list(campos_ia)

                            st.session_state[f"pln_ultimo_resultado_{i}"]["aplicados"] = aplicados
                            st.session_state[f"pln_ultimo_resultado_{i}"]["no_aplicados"] = no_aplicados

                            # Limpiar session_state keys de widgets para forzar re-render con valores nuevos
                            keys_widgets = [
                                f"pln_hd_{i}", f"pln_hi_{i}",
                                f"pln_saberes_conceptos_{i}", f"pln_saberes_proceso_{i}",
                                f"pln_criterios_evaluacion_{i}",
                                f"pln_actividades_aprendizaje_{i}",
                                f"pln_descripcion_evidencia_{i}",
                                f"pln_estrategias_didacticas_{i}",
                                f"pln_ambiente_{i}", f"pln_materiales_{i}",
                            ]
                            for kw in keys_widgets:
                                st.session_state.pop(kw, None)

                            st.rerun()
                        except Exception as e:
                            import traceback
                            st.error(f"❌ Error al llamar la IA: {e}")
                            st.session_state[f"pln_ultimo_resultado_{i}"] = {
                                "error": str(e),
                                "traceback": traceback.format_exc(),
                            }

                # Mostrar resultado de la última llamada (después del rerun)
                if f"pln_ultimo_resultado_{i}" in st.session_state:
                    ultimo = st.session_state[f"pln_ultimo_resultado_{i}"]
                    if "error" in ultimo:
                        with st.expander("❌ Error de la IA - Ver detalles"):
                            st.error(ultimo["error"])
                            st.code(ultimo.get("traceback", ""), language="python")
                    else:
                        aplicados = ultimo.get("aplicados", [])
                        no_aplicados = ultimo.get("no_aplicados", [])
                        if aplicados:
                            msg = f"✅ IA aplicó {len(aplicados)} campo(s)"
                            if ultimo.get("guias_usadas", 0) > 0:
                                msg += f" (con {ultimo['guias_usadas']} guía(s) previa(s) como contexto)"
                            st.success(msg)
                        if no_aplicados:
                            st.warning(f"⚠️ La IA no devolvió estos campos (o venían vacíos): "
                                       f"{', '.join(no_aplicados)}")

                    if ver_debug:
                        with st.expander("🔍 Respuesta cruda de la IA (debug)", expanded=True):
                            resultado = ultimo.get("resultado")
                            if resultado is not None:
                                if isinstance(resultado, dict):
                                    st.json(resultado)
                                else:
                                    st.code(str(resultado)[:2000])
                                    st.warning(f"Tipo recibido: {type(resultado).__name__} (esperaba dict)")
                            st.markdown(f"**Aplicados:** {ultimo.get('aplicados', [])}")
                            st.markdown(f"**No aplicados:** {ultimo.get('no_aplicados', [])}")

            c3, c4 = st.columns(2)
            with c3:
                saberes_c = st.text_area("Saberes de Conceptos y Principios",
                    value=fila.get("saberes_conceptos", ""), height=100,
                    key=f"pln_saberes_conceptos_{i}")
                saberes_p = st.text_area("Saberes de Proceso",
                    value=fila.get("saberes_proceso", ""), height=100,
                    key=f"pln_saberes_proceso_{i}")
                criterios = st.text_area("Criterios de Evaluación",
                    value=fila.get("criterios_evaluacion", ""), height=140,
                    key=f"pln_criterios_evaluacion_{i}")
                actividades_apr = st.text_area("Actividades de Aprendizaje",
                    value=fila.get("actividades_aprendizaje", ""), height=100,
                    key=f"pln_actividades_aprendizaje_{i}")
            with c4:
                evidencia = st.text_area("Descripción de la Evidencia",
                    value=fila.get("descripcion_evidencia", ""), height=100,
                    key=f"pln_descripcion_evidencia_{i}")
                estrategias = st.text_area("Estrategias Didácticas Activas",
                    value=fila.get("estrategias_didacticas", ""), height=100,
                    key=f"pln_estrategias_didacticas_{i}")
                ambiente = st.text_input("Ambiente",
                    value=fila.get("ambiente", ""), key=f"pln_ambiente_{i}")
                materiales = st.text_area("Materiales de Formación",
                    value=fila.get("materiales", ""), height=80, key=f"pln_materiales_{i}")
                instructores = st.text_input("Instructores Responsables",
                    value=fila.get("instructores",
                                   cfg.get("smtp_nombre") or cfg.get("autor_default", "")),
                    key=f"pln_ins_{i}")
                observaciones = st.text_input("Observaciones",
                    value=fila.get("observaciones", ""), key=f"pln_obs_{i}")

            filas_editadas.append({
                "fase": fase, "actividad_proyecto": actividad_proy,
                "competencia": competencia, "raps": raps_texto,
                "saberes_conceptos": saberes_c, "saberes_proceso": saberes_p,
                "criterios_evaluacion": criterios, "actividades_aprendizaje": actividades_apr,
                "horas_directas": horas_dir, "horas_independientes": horas_ind,
                "descripcion_evidencia": evidencia, "estrategias_didacticas": estrategias,
                "ambiente": ambiente, "materiales": materiales,
                "instructores": instructores, "observaciones": observaciones,
            })

    st.session_state.planeacion_filas = filas_editadas
    st.markdown("---")

    if st.button("🚀 Generar Planeación Pedagógica (Excel)",
                  type="primary", use_container_width=True):
        datos = {
            "fecha_elaboracion": fecha_elab, "programa": programa,
            "modalidad": modalidad, "codigo_programa": codigo_programa,
            "proyecto_formativo": proyecto, "codigo_proyecto": codigo_proy,
            "equipo_curricular": equipo, "regional_centro": regional,
            "filas": filas_editadas,
        }
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            safe = re.sub(r"[^\w]", "_", programa)[:30]
            ruta = str(PLANEACIONES_DIR / f"Planeacion_{safe}_{ts}.xlsx")
            with st.spinner("Generando planeación..."):
                generar_planeacion(datos, ruta)
            st.session_state.ultimo_archivo_planeacion = ruta
            st.success("✅ Planeación generada.")
        except Exception as e:
            st.error(f"Error: {e}")
            st.exception(e)

    if st.session_state.get("ultimo_archivo_planeacion"):
        ruta = st.session_state.ultimo_archivo_planeacion
        if Path(ruta).exists():
            with open(ruta, "rb") as f:
                st.download_button("⬇️ Descargar Planeación Pedagógica",
                    f.read(), file_name=Path(ruta).name,
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True)


def _fila_planeacion_vacia():
    return {
        "fase": "", "actividad_proyecto": "", "competencia": "", "raps": "",
        "saberes_conceptos": "", "saberes_proceso": "", "criterios_evaluacion": "",
        "actividades_aprendizaje": "", "horas_directas": 48, "horas_independientes": 48,
        "descripcion_evidencia": "", "estrategias_didacticas": "",
        "ambiente": "", "materiales": "", "instructores": "", "observaciones": "",
    }


# ============ NUEVA SECCIÓN: PROYECTOS FORMATIVOS ============
def seccion_proyectos_formativos():
    st.header("📄 Proyectos Formativos")
    st.caption("Sube el PDF del reporte del proyecto formativo (formato GFPI-F-016 del SENA). "
               "La app extrae automáticamente fases, actividades, competencias y RAPs "
               "para poder usarlos en el resto de módulos.")

    st.info("🔒 **Los PDFs se procesan localmente en el servidor con `pypdf`, "
            "sin consumir tokens de IA.** Solo se guarda la estructura extraída, no el PDF.")

    # ---- Cargar PDF nuevo ----
    st.markdown("---")
    st.subheader("📤 Cargar un proyecto formativo")
    archivo = st.file_uploader("PDF del reporte del proyecto formativo (formato GFPI-F-016)",
                               type=["pdf"], key="pdf_proyecto")
    if archivo is not None:
        try:
            with st.spinner("Procesando PDF..."):
                proyecto = procesar_pdf_proyecto(archivo.getvalue())

            st.success(f"✅ PDF procesado. Se detectaron **{len(proyecto.get('fases', []))} fases**, "
                       f"**{len(proyecto.get('competencias_agrupadas', []))} competencias únicas** "
                       f"y **{proyecto.get('total_filas', 0)} filas** en la tabla de planeación.")

            # Vista previa
            st.markdown("### Vista previa")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**Código Proyecto SOFIA:** {proyecto.get('codigo_proyecto_sofia', 'N/A')}")
                st.markdown(f"**Código Programa SOFIA:** {proyecto.get('codigo_programa_sofia', 'N/A')}")
                st.markdown(f"**Versión:** {proyecto.get('version_programa', 'N/A')}")
                st.markdown(f"**Fichas asociadas:** {proyecto.get('fichas_asociadas', 'N/A')}")
                st.markdown(f"**Tiempo:** {proyecto.get('tiempo_meses', 'N/A')} meses")
            with col2:
                st.markdown(f"**Programa:** {proyecto.get('programa_formacion', '')}")
                st.markdown(f"**Centro:** {proyecto.get('centro_formacion', '')}")
                st.markdown(f"**Regional:** {proyecto.get('regional', '')}")

            st.markdown(f"**Nombre del proyecto:**")
            st.markdown(f"> {proyecto.get('nombre_proyecto', '')}")

            # Preview de fases
            with st.expander("🔍 Ver estructura completa (fases, actividades, competencias, RAPs)"):
                for fase in proyecto.get("fases", []):
                    st.markdown(f"### {fase['nombre']}")
                    for act in fase.get("actividades", []):
                        st.markdown(f"**📌 {act['nombre']}**")
                        for comp in act.get("competencias", []):
                            st.markdown(f"  - `{comp['codigo']}` — {comp['nombre']}")
                            for rap in comp.get("raps", []):
                                st.markdown(f"    - `{rap['codigo']}` — {rap['nombre']}")

            # Botón guardar
            col_a, col_b = st.columns([2, 1])
            with col_a:
                if st.button("💾 Guardar proyecto formativo en la app",
                             type="primary", use_container_width=True):
                    agregar_o_actualizar_proyecto(PROYECTOS_FILE, proyecto)
                    st.success("✅ Proyecto guardado. Ya puedes usarlo en Nueva Guía y Planeación Pedagógica.")
                    st.rerun()
        except Exception as e:
            st.error(f"Error procesando el PDF: {e}")
            st.exception(e)

    # ---- Proyectos guardados ----
    st.markdown("---")
    st.subheader("💾 Proyectos formativos guardados")
    proyectos = cargar_proyectos(PROYECTOS_FILE)
    if not proyectos:
        st.info("Aún no has cargado ningún proyecto formativo. Sube el PDF arriba.")
        return

    for i, proy in enumerate(proyectos):
        with st.expander(
            f"📘 [{proy.get('codigo_proyecto_sofia', '?')}] {proy.get('nombre_proyecto', 'Sin nombre')[:80]}",
            expanded=False
        ):
            c1, c2 = st.columns([4, 1])
            with c1:
                st.markdown(f"**Programa:** {proy.get('programa_formacion', '')}")
                st.markdown(f"**Código Programa SOFIA:** {proy.get('codigo_programa_sofia', '')}  ·  "
                            f"**Versión:** {proy.get('version_programa', '')}  ·  "
                            f"**Duración:** {proy.get('tiempo_meses', '')} meses")
                st.markdown(f"**Fases:** {len(proy.get('fases', []))}  ·  "
                            f"**Competencias:** {len(proy.get('competencias_agrupadas', []))}  ·  "
                            f"**Total filas:** {proy.get('total_filas', 0)}")
            with c2:
                if st.button("🗑️ Eliminar", key=f"del_proy_{i}"):
                    eliminar_proyecto(PROYECTOS_FILE, proy.get("codigo_proyecto_sofia", ""))
                    st.rerun()


# ============ HELPERS DE PROYECTOS FORMATIVOS ============
def obtener_proyecto_por_codigo(codigo: str) -> dict:
    """Retorna el proyecto formativo por código SOFIA, o dict vacío."""
    proyectos = cargar_proyectos(PROYECTOS_FILE)
    for p in proyectos:
        if p.get("codigo_proyecto_sofia") == codigo:
            return p
    return {}


def selector_cascada_proyecto(key_prefix: str = "sel"):
    """Widget de dropdowns cascada: Proyecto → Fase → Actividad → Competencia.
    Retorna un dict con los valores seleccionados y los RAPs de la competencia.
    """
    proyectos = cargar_proyectos(PROYECTOS_FILE)
    if not proyectos:
        st.warning("⚠️ No hay proyectos formativos cargados. Ve a **📄 Proyectos Formativos** primero.")
        return {}

    # Selector de proyecto
    opciones_proy = ["— Seleccionar proyecto —"] + [
        f"[{p.get('codigo_proyecto_sofia', '?')}] {p.get('programa_formacion', '')[:50]}"
        for p in proyectos
    ]
    idx = st.selectbox("📘 Proyecto Formativo", range(len(opciones_proy)),
                        format_func=lambda i: opciones_proy[i], key=f"{key_prefix}_proy")
    if idx == 0:
        return {}
    proyecto = proyectos[idx - 1]

    # Selector de fase
    fases = proyecto.get("fases", [])
    if not fases:
        st.warning("Este proyecto no tiene fases detectadas.")
        return {"proyecto": proyecto}
    opciones_fase = ["— Seleccionar fase —"] + [f["nombre"] for f in fases]
    idx_fase = st.selectbox("📅 Fase del Proyecto", range(len(opciones_fase)),
                             format_func=lambda i: opciones_fase[i], key=f"{key_prefix}_fase")
    if idx_fase == 0:
        return {"proyecto": proyecto}
    fase = fases[idx_fase - 1]

    # Selector de actividad
    actividades = fase.get("actividades", [])
    opciones_act = ["— Seleccionar actividad —"] + [
        (a["nombre"][:100] + "..." if len(a["nombre"]) > 100 else a["nombre"])
        for a in actividades
    ]
    idx_act = st.selectbox("📌 Actividad del Proyecto", range(len(opciones_act)),
                            format_func=lambda i: opciones_act[i], key=f"{key_prefix}_act")
    if idx_act == 0:
        return {"proyecto": proyecto, "fase": fase}
    actividad = actividades[idx_act - 1]

    # Selector de competencia
    competencias = actividad.get("competencias", [])
    opciones_comp = ["— Seleccionar competencia —"] + [
        f"[{c['codigo']}] {c['nombre'][:70]}" for c in competencias
    ]
    idx_comp = st.selectbox("🎯 Competencia", range(len(opciones_comp)),
                             format_func=lambda i: opciones_comp[i], key=f"{key_prefix}_comp")
    if idx_comp == 0:
        return {"proyecto": proyecto, "fase": fase, "actividad": actividad}
    competencia = competencias[idx_comp - 1]

    # Mostrar RAPs asociados
    raps = competencia.get("raps", [])
    if raps:
        st.markdown(f"**RAPs asociados ({len(raps)}):**")
        for rap in raps:
            st.markdown(f"  - `{rap['codigo']}` — {rap['nombre']}")

    return {
        "proyecto": proyecto,
        "fase": fase,
        "actividad": actividad,
        "competencia": competencia,
        "raps": raps,
    }


def _buscar_guias_de_competencia(competencia_texto: str) -> list:
    """Busca en el historial de guías las que corresponden a esta competencia.
    Devuelve lista de resúmenes con fase, RAP focal, actividades.
    """
    if not competencia_texto:
        return []
    # Extraer código de competencia del texto (primeros 9 dígitos)
    m = re.search(r"(\d{6,9})", competencia_texto)
    codigo_buscar = m.group(1) if m else ""
    if not codigo_buscar:
        return []

    guias = cargar_guias_historial()
    coincidencias = []
    for g in guias:
        comp_guia = g.get("competencia", "")
        cod_guia = g.get("codigo_competencia", "")
        if codigo_buscar and (codigo_buscar in comp_guia or codigo_buscar == cod_guia):
            coincidencias.append({
                "fecha": g.get("fecha", ""),
                "fase": g.get("fase", ""),
                "rap_focal": g.get("rap_focal", ""),
                "proyecto_formativo": g.get("proyecto_formativo", ""),
            })
    return coincidencias


# ============ HELPERS ============
def _extraer_codigo(competencia_str: str) -> str:
    m = re.search(r"(\d{6,})", competencia_str)
    return m.group(1) if m else competencia_str[:20]


def _armar_tabla_evidencias(actividades, fase):
    rows = [["Fase del proyecto", "Actividad del proyecto formativo", "Actividad de Aprendizaje",
             "Evidencias de Aprendizaje", "Criterios de Evaluación", "Técnicas e Instrumentos"]]
    for key, titulo in [("3.3", "3.3 Apropiación"), ("3.4", "3.4 Transferencia")]:
        act = actividades.get(key, {})
        if not act.get("descripcion"):
            continue
        rows.append([
            fase,
            (act.get("descripcion", "")[:80] + "...") if len(act.get("descripcion", "")) > 80 else act.get("descripcion", ""),
            titulo,
            act.get("evidencias", ""),
            "Verificar cumplimiento de la evidencia con la rúbrica correspondiente.",
            act.get("instrumentos", "Rúbrica de evaluación · Lista de chequeo"),
        ])
    return rows


# ============ ROUTER ============
if seccion == "🆕 Nueva guía":
    seccion_nueva_guia()
elif seccion == "📋 Planes de Trabajo":
    seccion_planes_trabajo()
elif seccion == "🗓️ Planeación Pedagógica":
    seccion_planeacion_pedagogica()
elif seccion == "📄 Proyectos Formativos":
    seccion_proyectos_formativos()
elif seccion == "🤖 Configurar IA":
    seccion_configurar_ia()
elif seccion == "✉️ Configurar correo":
    seccion_configurar_correo()
elif seccion == "🎨 Prompts de la IA":
    seccion_prompts()
elif seccion == "⚙️ Cargar competencias":
    seccion_cargar_competencias()
elif seccion == "💾 Guías guardadas":
    seccion_guias_guardadas()
elif seccion == "📚 RAPs guardados":
    seccion_raps()
elif seccion == "ℹ️ Ayuda":
    seccion_ayuda()
