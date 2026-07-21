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
from generadores.ia import (
    GeminiCliente, GEMINI_DISPONIBLE,
    PROMPTS_DEFAULT, cargar_prompts, guardar_prompts, restablecer_prompt,
)


# ============ CONFIG ============
st.set_page_config(
    page_title="Generador Guías SENA — Instructor Sena",
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
        "fase_proyecto": st.session_state.get("form_fase", "Planear"),
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
        ["🆕 Nueva guía", "🤖 Configurar IA", "🎨 Prompts de la IA",
         "⚙️ Cargar competencias",
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
        fase = st.selectbox("Fase del proyecto",
                            ["Análisis", "Planear", "Ejecución", "Evaluación"],
                            index=1, key="form_fase")
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
        autor = st.text_input("Autor (instructor)", value=cfg.get("autor_default", "Carlos"))
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

        # Historial
        guias = cargar_guias_historial()
        guias.append({
            "fecha": fecha_str,
            "timestamp": timestamp,
            "programa": programa,
            "competencia": competencia,
            "fase": fase,
            "rap_focal": rap_focal,
            "autor": autor,
            "archivo_aprendiz": p_aprendiz,
            "archivo_instructor": p_instructor,
            "archivo_rubricas": p_rubricas,
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

1. **🤖 Configurar IA** → pega tu API key gratis de Gemini y tu nombre.
2. **⚙️ Cargar competencias** → sube tu Excel una sola vez.
3. **🆕 Nueva guía**:
   - Selecciona programa → competencia → **RAPs y código se auto-llenan del Excel**
   - Click en **🪄 Generar todo con IA** (arriba de todo)
   - Revisa y ajusta cada sección
   - Click en **🎯 Generar los 3 documentos** → descarga
4. **💾 Guías guardadas** → todas las guías anteriores con botones de descarga.

### 📊 Estructura del Excel

Una fila por competencia. Columnas: `Programa | Codigo Programa | Competencia | Codigo Competencia | RAP1 | RAP2 | RAP3 | RAP4`

Descarga la plantilla de ejemplo desde **⚙️ Cargar competencias**.
""")


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
elif seccion == "🤖 Configurar IA":
    seccion_configurar_ia()
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
