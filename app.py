"""
Generador de Guías de Aprendizaje SENA — ProfeNaturales
Aplicativo Streamlit que:
  - Lee competencias desde Excel (subido o desde Google Drive)
  - Guarda RAPs transcritos para reutilizarlos después
  - Genera Guía del Aprendiz, Guía del Instructor y Rúbricas de Evaluación
    en formato oficial GFPI-F-135
"""
import io
import json
import re
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from generadores.guia_aprendizaje import generar_guia_aprendizaje
from generadores.guia_instructor import generar_guia_instructor
from generadores.rubricas import generar_rubricas


# ============ CONFIG ============
st.set_page_config(
    page_title="Generador Guías SENA — ProfeNaturales",
    page_icon="📘",
    layout="wide",
)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
RAPS_FILE = DATA_DIR / "raps_guardados.json"
GUIAS_FILE = DATA_DIR / "guias_guardadas.json"


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


def cargar_guias():
    return cargar_json(GUIAS_FILE, [])


def guardar_guias(lista):
    guardar_json(GUIAS_FILE, lista)


# ============ LECTURA DE COMPETENCIAS ============
@st.cache_data(ttl=300)
def leer_excel_bytes(contenido: bytes) -> dict:
    """Lee todas las hojas del Excel y devuelve dict {nombre_hoja: DataFrame}."""
    return pd.read_excel(io.BytesIO(contenido), sheet_name=None)


def descargar_desde_drive(url_o_id: str) -> bytes:
    """Descarga un archivo público de Google Drive."""
    m = re.search(r"/d/([a-zA-Z0-9_-]+)", url_o_id)
    file_id = m.group(1) if m else url_o_id.strip()
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.content


# ============ ESTADO ============
def init_state():
    if "hojas" not in st.session_state:
        st.session_state.hojas = None
    if "mapeo" not in st.session_state:
        st.session_state.mapeo = {}
    if "raps_guardados" not in st.session_state:
        st.session_state.raps_guardados = cargar_raps()
    if "form_data" not in st.session_state:
        st.session_state.form_data = {}


init_state()


# ============ SIDEBAR ============
with st.sidebar:
    st.markdown("### 📘 ProfeNaturales SENA")
    st.markdown("**Generador de Guías y Rúbricas**")
    st.markdown("---")
    seccion = st.radio(
        "Navegación",
        ["🆕 Nueva guía", "💾 Guías guardadas", "📚 RAPs guardados", "⚙️ Cargar competencias", "ℹ️ Ayuda"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    st.caption("Los datos se guardan localmente en la carpeta `data/` del proyecto.")


# ============ SECCIÓN: CARGAR COMPETENCIAS ============
def seccion_cargar_competencias():
    st.header("⚙️ Cargar archivo de competencias")
    st.write("Sube tu Excel de competencias o pega el enlace de Google Drive (debe ser público).")

    tab1, tab2 = st.tabs(["📤 Subir Excel", "🔗 Desde Google Drive"])

    with tab1:
        archivo = st.file_uploader("Selecciona el Excel de competencias (.xlsx)", type=["xlsx"])
        if archivo:
            try:
                hojas = leer_excel_bytes(archivo.getvalue())
                st.session_state.hojas = hojas
                st.success(f"✅ Excel cargado. Contiene {len(hojas)} hoja(s): {', '.join(hojas.keys())}")
            except Exception as e:
                st.error(f"Error al leer el Excel: {e}")

    with tab2:
        url = st.text_input("URL de Google Drive (compartida con 'cualquier persona con el enlace')",
                            placeholder="https://drive.google.com/file/d/XXXXXXX/view?usp=sharing")
        if st.button("Descargar desde Drive") and url:
            try:
                with st.spinner("Descargando..."):
                    contenido = descargar_desde_drive(url)
                hojas = leer_excel_bytes(contenido)
                st.session_state.hojas = hojas
                st.success(f"✅ Excel descargado. Contiene {len(hojas)} hoja(s): {', '.join(hojas.keys())}")
            except Exception as e:
                st.error(f"Error: {e}. Verifica que el enlace sea público.")

    if st.session_state.hojas:
        st.markdown("---")
        st.subheader("Vista previa")
        for nombre, df in st.session_state.hojas.items():
            with st.expander(f"Hoja: {nombre} ({len(df)} filas)"):
                st.dataframe(df.head(10), use_container_width=True)

        st.markdown("---")
        st.subheader("🎯 Mapeo de columnas")
        st.write("Indica cuál columna del Excel corresponde a cada campo. Esto se guarda para próximas veces.")

        nombre_hoja = st.selectbox("Hoja a usar", list(st.session_state.hojas.keys()))
        df = st.session_state.hojas[nombre_hoja]
        cols = [""] + list(df.columns)

        c1, c2 = st.columns(2)
        with c1:
            col_prog = st.selectbox("Columna → Programa", cols, key="col_prog")
            col_cod_prog = st.selectbox("Columna → Código del Programa", cols, key="col_cod_prog")
            col_comp = st.selectbox("Columna → Competencia", cols, key="col_comp")
        with c2:
            col_cod_comp = st.selectbox("Columna → Código Competencia", cols, key="col_cod_comp")
            col_rap = st.selectbox("Columna → RAP (si aplica)", cols, key="col_rap")

        st.session_state.mapeo = {
            "hoja": nombre_hoja,
            "programa": col_prog,
            "codigo_programa": col_cod_prog,
            "competencia": col_comp,
            "codigo_competencia": col_cod_comp,
            "rap": col_rap,
        }


# ============ SECCIÓN: NUEVA GUÍA ============
def seccion_nueva_guia():
    st.header("🆕 Nueva Guía de Aprendizaje")

    if st.session_state.hojas is None or not st.session_state.mapeo:
        st.warning("⚠️ Primero carga tu Excel de competencias en la sección **⚙️ Cargar competencias**.")
        st.info("O ingresa los datos manualmente abajo:")

    # ---- PASO 1: Programa y competencia ----
    st.subheader("Paso 1 · Programa y competencia")
    col1, col2 = st.columns(2)

    if st.session_state.hojas and st.session_state.mapeo:
        df = st.session_state.hojas[st.session_state.mapeo["hoja"]]
        col_prog = st.session_state.mapeo.get("programa")

        with col1:
            if col_prog and col_prog in df.columns:
                programas_unicos = df[col_prog].dropna().unique().tolist()
                programa_sel = st.selectbox("Programa de formación", [""] + programas_unicos)
            else:
                programa_sel = st.text_input("Programa de formación")
        with col2:
            codigo_prog = st.text_input("Código del programa",
                                        value=_lookup(df, col_prog, programa_sel,
                                                      st.session_state.mapeo.get("codigo_programa")))
    else:
        with col1:
            programa_sel = st.text_input("Programa de formación",
                                         value="Técnico en Integración de Operaciones Logísticas")
        with col2:
            codigo_prog = st.text_input("Código del programa", value="137136")

    competencia = st.text_area(
        "Competencia (código + denominación)",
        value="220201501 — Aplicar conocimientos de las ciencias naturales de acuerdo con situaciones del contexto productivo y social.",
        height=70,
    )

    # ---- PASO 2: Proyecto formativo ----
    st.subheader("Paso 2 · Proyecto formativo")
    col1, col2 = st.columns([3, 1])
    with col1:
        proyecto = st.text_area("Nombre del proyecto formativo", height=80,
                                value=st.session_state.form_data.get("proyecto", ""))
    with col2:
        fase = st.selectbox("Fase del proyecto",
                            ["Análisis", "Planear", "Ejecución", "Evaluación"],
                            index=1)
    actividad_proyecto = st.text_area("Actividad del proyecto formativo", height=70,
                                      value=st.session_state.form_data.get("actividad_proyecto", ""))

    # ---- PASO 3: RAPs ----
    st.subheader("Paso 3 · Resultados de Aprendizaje (RAP)")
    st.caption("Transcribe los RAP oficiales. Se guardan por competencia para reutilizarlos en próximas guías.")

    codigo_comp = _extraer_codigo(competencia)
    raps_guardados = st.session_state.raps_guardados.get(codigo_comp, [])

    if raps_guardados:
        st.info(f"📚 Ya tienes {len(raps_guardados)} RAP guardado(s) para la competencia {codigo_comp}.")

    n_raps = st.number_input("¿Cuántos RAP tiene esta competencia?", 1, 10,
                             value=max(len(raps_guardados), 4))

    raps_input = []
    for i in range(n_raps):
        default = raps_guardados[i] if i < len(raps_guardados) else ""
        rap = st.text_area(f"RAP {i+1}", value=default, height=60, key=f"rap_{i}")
        raps_input.append(rap.strip())

    guardar_estos = st.checkbox("💾 Guardar estos RAP para la competencia", value=True)

    # ---- PASO 4: Guía específica ----
    st.subheader("Paso 4 · Datos de esta guía")
    col1, col2 = st.columns(2)
    with col1:
        duracion = st.text_input("Duración total", value="8 horas (4 h directas + 4 h autónomas)")
        rap_focal = st.selectbox("¿Qué RAP trabaja principalmente esta guía?",
                                 ["Todos"] + [f"RAP {i+1}" for i in range(n_raps)])
    with col2:
        autor = st.text_input("Autor (instructor)", value="Carlos")
        fecha_str = st.date_input("Fecha", value=date.today()).isoformat()

    presentacion = st.text_area(
        "Presentación al aprendiz (2–3 párrafos motivadores)",
        height=180,
        value=st.session_state.form_data.get("presentacion", ""),
        placeholder="Apreciado aprendiz, sea bienvenido..."
    )

    # ---- PASO 5: Actividades 3.1 - 3.4 ----
    st.subheader("Paso 5 · Actividades de aprendizaje")
    st.caption("Diligencia cada una de las 4 fases. Los campos vacíos quedan en blanco en la guía.")

    actividades = {}
    labels = {
        "3.1": "3.1 Reflexión inicial",
        "3.2": "3.2 Contextualización",
        "3.3": "3.3 Apropiación",
        "3.4": "3.4 Transferencia",
    }
    for key, label in labels.items():
        with st.expander(f"📝 {label}", expanded=(key == "3.1")):
            actividades[key] = {
                "descripcion": st.text_area(f"Descripción de la actividad ({key})", height=100, key=f"desc_{key}"),
                "ambiente": st.text_input(f"Ambiente requerido ({key})", key=f"amb_{key}"),
                "estrategias": st.text_input(f"Estrategias didácticas ({key})", key=f"est_{key}"),
                "materiales": st.text_input(f"Materiales de formación ({key})", key=f"mat_{key}"),
                "apoyo": st.text_area(f"Material de apoyo ({key})", height=60, key=f"apo_{key}"),
                "evidencias": st.text_area(f"Evidencias de aprendizaje ({key}) — opcional",
                                           height=60, key=f"ev_{key}") if key in ("3.3", "3.4") else "",
                "instrumentos": st.text_input(f"Instrumentos de evaluación ({key})",
                                              key=f"ins_{key}") if key in ("3.3", "3.4") else "",
                "duracion": st.text_input(f"Duración ({key})", key=f"dur_{key}"),
            }

    # ---- PASO 6: Extras ----
    st.subheader("Paso 6 · Contenido complementario")
    col1, col2 = st.columns(2)
    with col1:
        glosario_raw = st.text_area(
            "Glosario (formato `término | definición`, uno por línea)",
            height=180,
            placeholder="Fuerza (F) | Interacción capaz de modificar el estado de movimiento...\nMasa (m) | Cantidad de materia...",
        )
    with col2:
        referentes_raw = st.text_area(
            "Referentes bibliográficos (uno por línea)",
            height=180,
            placeholder="Serway, R. A. Física para ciencias e ingeniería.\nHewitt, P. G. Física Conceptual...",
        )

    st.markdown("---")

    # ---- GENERAR ----
    st.subheader("🚀 Generar documentos")
    st.caption("Se generarán 3 archivos: Guía del Aprendiz, Guía del Instructor y Rúbricas de Evaluación.")

    if st.button("🎯 Generar los 3 documentos", type="primary", use_container_width=True):
        if not programa_sel or not competencia:
            st.error("Programa y competencia son obligatorios.")
            return

        # Guardar RAPs si se marcó
        if guardar_estos and codigo_comp:
            st.session_state.raps_guardados[codigo_comp] = [r for r in raps_input if r]
            guardar_raps(st.session_state.raps_guardados)

        # Parsear glosario
        glosario = []
        for linea in glosario_raw.splitlines():
            if "|" in linea:
                partes = linea.split("|", 1)
                glosario.append((partes[0].strip(), partes[1].strip()))

        # Parsear referentes
        referentes = [r.strip() for r in referentes_raw.splitlines() if r.strip()]

        # Datos consolidados
        datos = {
            "programa": programa_sel,
            "codigo_programa": codigo_prog,
            "proyecto_formativo": proyecto,
            "fase_proyecto": fase,
            "actividad_proyecto": actividad_proyecto,
            "competencia": competencia,
            "raps": [r for r in raps_input if r],
            "duracion": duracion,
            "presentacion": presentacion,
            "actividades": actividades,
            "evidencias_tabla": _armar_tabla_evidencias(actividades, fase),
            "glosario": glosario,
            "referentes": referentes,
            "autor_nombre": autor,
            "autor_cargo": "Instructor",
            "autor_dependencia": "Centro de Formación SENA",
            "autor_fecha": fecha_str,
        }

        # Generar los 3 documentos
        tmpdir = tempfile.mkdtemp()
        safe_prog = re.sub(r"[^\w\-]", "_", programa_sel)[:40]
        prefix = f"{safe_prog}_{fecha_str}"

        try:
            p_aprendiz = f"{tmpdir}/{prefix}_Guia_Aprendiz.docx"
            p_instructor = f"{tmpdir}/{prefix}_Guia_Instructor.docx"
            p_rubricas = f"{tmpdir}/{prefix}_Rubricas.docx"

            with st.spinner("Generando Guía del Aprendiz..."):
                generar_guia_aprendizaje(datos, p_aprendiz)
            with st.spinner("Generando Guía del Instructor..."):
                generar_guia_instructor(datos, p_instructor)
            with st.spinner("Generando Rúbricas..."):
                generar_rubricas(datos, p_rubricas)

            st.success("✅ Documentos generados. Descarga cada uno abajo:")

            c1, c2, c3 = st.columns(3)
            with c1:
                with open(p_aprendiz, "rb") as f:
                    st.download_button("📥 Guía del Aprendiz", f, file_name=Path(p_aprendiz).name,
                                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                       use_container_width=True)
            with c2:
                with open(p_instructor, "rb") as f:
                    st.download_button("📥 Guía del Instructor", f, file_name=Path(p_instructor).name,
                                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                       use_container_width=True)
            with c3:
                with open(p_rubricas, "rb") as f:
                    st.download_button("📥 Rúbricas", f, file_name=Path(p_rubricas).name,
                                       mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                       use_container_width=True)

            # Guardar registro
            guias = cargar_guias()
            guias.append({
                "fecha": fecha_str,
                "programa": programa_sel,
                "competencia": codigo_comp,
                "fase": fase,
                "rap_focal": rap_focal,
                "autor": autor,
            })
            guardar_guias(guias)

        except Exception as e:
            st.error(f"Error al generar los documentos: {e}")
            st.exception(e)


# ============ SECCIÓN: GUÍAS GUARDADAS ============
def seccion_guias_guardadas():
    st.header("💾 Guías generadas")
    guias = cargar_guias()
    if not guias:
        st.info("Aún no has generado ninguna guía.")
        return
    df = pd.DataFrame(guias)
    st.dataframe(df, use_container_width=True)


# ============ SECCIÓN: RAPS GUARDADOS ============
def seccion_raps():
    st.header("📚 RAPs guardados por competencia")
    raps = cargar_raps()
    if not raps:
        st.info("Aún no has guardado RAPs. Se guardan automáticamente al generar tu primera guía.")
        return
    for codigo, lista in raps.items():
        with st.expander(f"Competencia {codigo} — {len(lista)} RAP"):
            for i, r in enumerate(lista, 1):
                st.markdown(f"**{i}.** {r}")
            if st.button(f"🗑️ Eliminar", key=f"del_{codigo}"):
                del raps[codigo]
                guardar_raps(raps)
                st.session_state.raps_guardados = raps
                st.rerun()


# ============ SECCIÓN: AYUDA ============
def seccion_ayuda():
    st.header("ℹ️ Ayuda")
    st.markdown("""
### ¿Qué hace este aplicativo?
Genera automáticamente tres documentos en formato oficial **GFPI-F-135** del SENA:
1. **Guía del Aprendiz** — el documento que reciben los estudiantes.
2. **Guía del Instructor** — orientaciones didácticas, respuestas esperadas, errores comunes.
3. **Rúbricas de Evaluación** — una rúbrica de 4 niveles por cada actividad (3.1 a 3.4).

Todos preservan el encabezado institucional, código, versión y logo del SENA.

### Flujo de trabajo recomendado
1. En **⚙️ Cargar competencias**: sube tu Excel de competencias (o desde Google Drive).
2. En **🆕 Nueva guía**: llena el formulario paso a paso.
3. Descarga los 3 documentos y súbelos a tu portal.

### Sobre los RAPs
Los RAPs (Resultados de Aprendizaje) los transcribes una vez y quedan guardados por código de competencia. La próxima vez que uses la misma competencia, ya aparecerán prellenados.

### Persistencia
Los datos (RAPs, historial de guías) se guardan en la carpeta `data/`. Si vas a desplegar en Streamlit Cloud y quieres persistencia permanente, considera conectar a Google Sheets como backend (avísame para agregar esa integración).
""")


# ============ HELPERS ============
def _extraer_codigo(competencia_str: str) -> str:
    m = re.search(r"(\d{6,})", competencia_str)
    return m.group(1) if m else competencia_str[:20]


def _lookup(df, col_key, valor_key, col_valor):
    """Busca en df la fila donde col_key == valor_key y devuelve col_valor."""
    if not (col_key and col_valor and valor_key):
        return ""
    if col_key not in df.columns or col_valor not in df.columns:
        return ""
    fila = df[df[col_key] == valor_key]
    if fila.empty:
        return ""
    return str(fila.iloc[0][col_valor])


def _armar_tabla_evidencias(actividades, fase):
    """Genera la tabla de la sección 4 automáticamente a partir de las actividades 3.3 y 3.4."""
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
elif seccion == "💾 Guías guardadas":
    seccion_guias_guardadas()
elif seccion == "📚 RAPs guardados":
    seccion_raps()
elif seccion == "⚙️ Cargar competencias":
    seccion_cargar_competencias()
elif seccion == "ℹ️ Ayuda":
    seccion_ayuda()
