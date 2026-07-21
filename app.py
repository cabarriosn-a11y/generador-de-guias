"""
Generador de Guías de Aprendizaje SENA — 
Con integración de IA (Gemini) para generar contenido automáticamente.
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
from generadores.ia import (
    GeminiCliente, GEMINI_DISPONIBLE,
    PROMPTS_DEFAULT, cargar_prompts, guardar_prompts, restablecer_prompt,
)


# ============ CONFIG ============
st.set_page_config(
    page_title="Generador Guías SENA — Instrcutor Sena",
    page_icon="📘",
    layout="wide",
)

DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
RAPS_FILE = DATA_DIR / "raps_guardados.json"
GUIAS_FILE = DATA_DIR / "guias_guardadas.json"
CONFIG_FILE = DATA_DIR / "config.json"
PROMPTS_FILE = DATA_DIR / "prompts.json"


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


def cargar_config():
    return cargar_json(CONFIG_FILE, {})


def guardar_config(cfg):
    guardar_json(CONFIG_FILE, cfg)


# ============ IA ============
MODELOS_DISPONIBLES = [
    "gemini-2.5-flash",         # Estable, rápido, gratis (10 RPM, 250 RPD) — RECOMENDADO
    "gemini-flash-latest",      # Alias al último Flash estable de Google
    "gemini-3-flash",           # Más nuevo, calidad superior, cuota reducida
    "gemini-3.1-flash-lite",    # Cuota más alta pero menos capaz
]
MODELO_DEFAULT = "gemini-2.5-flash"


def obtener_cliente_ia():
    cfg = cargar_config()
    api_key = cfg.get("gemini_api_key", "").strip()
    if not api_key:
        return None
    modelo = cfg.get("modelo", MODELO_DEFAULT)
    # Si el modelo guardado ya no está en la lista de disponibles (obsoleto),
    # cambiar automáticamente al default y guardarlo
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


# ============ ESTADO ============
def init_state():
    if "hojas" not in st.session_state:
        st.session_state.hojas = None
    if "mapeo" not in st.session_state:
        st.session_state.mapeo = {}
    if "raps_guardados" not in st.session_state:
        st.session_state.raps_guardados = cargar_raps()


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


# ============ SECCIÓN: PROMPTS DE LA IA ============
def seccion_prompts():
    st.header("🎨 Prompts de la IA")
    st.markdown("""
Aquí puedes editar los **prompts base** que la IA usa para generar cada tipo de contenido.
Se guardan permanentemente y aplican a todas las futuras guías.

💡 **Tip**: Si solo quieres cambiar algo puntual para UNA guía (ej: "hazla más corta"), es mejor usar
los cuadros de **"Instrucciones extras"** que aparecen junto a cada botón 🤖 en la sección de nueva guía.

**Variables disponibles** (se reemplazan solas al usar la IA):
- `{programa}`, `{codigo_programa}`, `{proyecto_formativo}`, `{competencia}`, `{duracion}`
- `{raps_formateados}` — la lista de RAPs ya en formato bullet
- Solo en actividad: `{key}` (3.1, 3.2...), `{titulo_fase}`, `{contexto_previo}`
- Solo en glosario: `{n_terminos}`, `{presentacion_corta}`, `{actividades_resumen}`
""")

    prompts = cargar_prompts(PROMPTS_FILE)

    etiquetas = {
        "system": ("🧭 Instrucción de sistema (personalidad y reglas)",
                   "Define QUIÉN es la IA y CÓMO se comporta en todas las llamadas."),
        "presentacion": ("📄 Prompt de Presentación",
                         "Genera los 2-3 párrafos de bienvenida al aprendiz."),
        "actividad": ("📝 Prompt de Actividad (3.1, 3.2, 3.3, 3.4)",
                      "Genera todos los campos de UNA actividad (mismo prompt para las 4)."),
        "glosario": ("📚 Prompt de Glosario",
                     "Genera la lista de términos clave con sus definiciones."),
        "referentes": ("🔗 Prompt de Referentes bibliográficos",
                       "Genera la lista de fuentes bibliográficas."),
    }

    for clave, (titulo, descripcion) in etiquetas.items():
        with st.expander(titulo, expanded=False):
            st.caption(descripcion)
            nuevo_valor = st.text_area(
                f"Contenido del prompt", value=prompts.get(clave, PROMPTS_DEFAULT[clave]),
                height=300, key=f"prompt_edit_{clave}",
                label_visibility="collapsed",
            )
            col1, col2, col3 = st.columns([1, 1, 3])
            with col1:
                if st.button("💾 Guardar", key=f"save_{clave}", type="primary"):
                    prompts[clave] = nuevo_valor
                    guardar_prompts(PROMPTS_FILE, prompts)
                    st.success("✅ Prompt guardado.")
                    st.rerun()
            with col2:
                if st.button("↩️ Restablecer", key=f"reset_{clave}"):
                    prompts = restablecer_prompt(PROMPTS_FILE, clave)
                    st.success("✅ Prompt restablecido al original.")
                    st.rerun()


# ============ SECCIÓN: CONFIGURAR IA ============
def seccion_configurar_ia():
    st.header("🤖 Configurar IA (Gemini)")

    if not GEMINI_DISPONIBLE:
        st.error("⚠️ La librería `google-generativeai` no está instalada.")
        st.code("pip install google-generativeai")
        return

    st.markdown("""
### ¿Por qué necesitas una API key?
La app usa **Gemini** (Google) para generar el contenido automáticamente. Es **gratis** y **no requiere tarjeta de crédito**.

### Cómo obtener tu API key (2 minutos)
1. Ve a **[aistudio.google.com/apikey](https://aistudio.google.com/apikey)**
2. Inicia sesión con tu cuenta Google
3. Click en **"Crear clave de API"** (o "Create API key")
4. Copia el texto que empieza con `AIza...`
5. Pégalo abajo y guarda

**Es privado**: la key se guarda solo en tu computador (`data/config.json`).
""")

    cfg = cargar_config()
    api_key_actual = cfg.get("gemini_api_key", "")

    with st.form("form_ia"):
        api_key = st.text_input(
            "API key de Gemini",
            value=api_key_actual, type="password", placeholder="AIzaSy...",
            help="La obtienes en aistudio.google.com/apikey"
        )
        modelo_actual = cfg.get("modelo", MODELO_DEFAULT)
        # Si tenía uno obsoleto, mostrar el default
        if modelo_actual not in MODELOS_DISPONIBLES:
            modelo_actual = MODELO_DEFAULT
        modelo = st.selectbox(
            "Modelo",
            MODELOS_DISPONIBLES,
            index=MODELOS_DISPONIBLES.index(modelo_actual),
            help=("Modelos disponibles gratis (julio 2026). "
                  "'gemini-2.5-flash' es el más estable y recomendado. "
                  "'gemini-3-flash' es más nuevo pero con cuota diaria más limitada.")
        )
        col1, col2 = st.columns(2)
        with col1:
            guardar_btn = st.form_submit_button("💾 Guardar", type="primary", use_container_width=True)
        with col2:
            probar_btn = st.form_submit_button("🧪 Probar conexión", use_container_width=True)

    if guardar_btn:
        cfg["gemini_api_key"] = api_key.strip()
        cfg["modelo"] = modelo
        guardar_config(cfg)
        st.success("✅ API key guardada.")
        st.rerun()

    if probar_btn:
        if not api_key.strip():
            st.error("Ingresa una API key primero.")
        else:
            try:
                cli = GeminiCliente(api_key.strip(), modelo=modelo)
                resp = cli._llamar("Responde solo con la palabra: FUNCIONA")
                if "FUNCIONA" in resp.upper():
                    st.success(f"✅ Conexión OK. Modelo: {modelo}.")
                else:
                    st.warning(f"Conexión OK, respuesta inesperada: {resp[:200]}")
            except Exception as e:
                st.error(f"❌ Error: {e}")


# ============ SECCIÓN: CARGAR COMPETENCIAS ============
def seccion_cargar_competencias():
    st.header("⚙️ Cargar archivo de competencias")
    tab1, tab2 = st.tabs(["📤 Subir Excel", "🔗 Desde Google Drive"])

    with tab1:
        archivo = st.file_uploader("Selecciona el Excel (.xlsx)", type=["xlsx"])
        if archivo:
            try:
                hojas = leer_excel_bytes(archivo.getvalue())
                st.session_state.hojas = hojas
                st.success(f"✅ {len(hojas)} hoja(s) cargada(s): {', '.join(hojas.keys())}")
            except Exception as e:
                st.error(f"Error: {e}")

    with tab2:
        url = st.text_input("URL de Google Drive (pública)",
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
        nombre_hoja = st.selectbox("Hoja a usar", list(st.session_state.hojas.keys()))
        df = st.session_state.hojas[nombre_hoja]
        cols = [""] + list(df.columns)
        c1, c2 = st.columns(2)
        with c1:
            col_prog = st.selectbox("Programa", cols, key="col_prog")
            col_cod_prog = st.selectbox("Código Programa", cols, key="col_cod_prog")
            col_comp = st.selectbox("Competencia", cols, key="col_comp")
        with c2:
            col_cod_comp = st.selectbox("Código Competencia", cols, key="col_cod_comp")
            col_rap = st.selectbox("RAP (opcional)", cols, key="col_rap")

        st.session_state.mapeo = {
            "hoja": nombre_hoja, "programa": col_prog, "codigo_programa": col_cod_prog,
            "competencia": col_comp, "codigo_competencia": col_cod_comp, "rap": col_rap,
        }


# ============ SECCIÓN: NUEVA GUÍA ============
def seccion_nueva_guia():
    st.header("🆕 Nueva Guía de Aprendizaje")

    cli_ia = obtener_cliente_ia()
    if cli_ia is None:
        st.info("💡 **Tip:** Configura la IA en **🤖 Configurar IA** para generar contenido automáticamente. Sin IA, puedes llenar todo manualmente.")

    # ---- Botón mágico: generar TODO con IA ----
    gen_todo = False
    extras_todo = {}
    if cli_ia:
        st.markdown("### ⚡ Generar TODO con IA")
        st.caption("Llena solo los datos básicos (programa, competencia, RAPs) y la IA generará todo el contenido.")

        with st.expander("💬 Instrucciones extras para la IA (opcional)"):
            st.caption("Estas instrucciones se AGREGAN al prompt base solo para esta generación. Ejemplos: 'hazlo más corto y profesional', 'enfócate en manejo de inventarios', 'usa ejemplos de bandas transportadoras'.")
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

        gen_todo = st.button("🪄 Generar todo el contenido de la guía", type="primary", use_container_width=True)

    # ---- PASO 1: Programa y competencia ----
    st.subheader("Paso 1 · Programa y competencia")
    col1, col2 = st.columns(2)

    if st.session_state.hojas and st.session_state.mapeo:
        df = st.session_state.hojas[st.session_state.mapeo["hoja"]]
        col_prog = st.session_state.mapeo.get("programa")
        with col1:
            if col_prog and col_prog in df.columns:
                programas_unicos = df[col_prog].dropna().unique().tolist()
                programa_sel = st.selectbox("Programa de formación", [""] + programas_unicos, key="form_programa")
            else:
                programa_sel = st.text_input("Programa de formación", key="form_programa")
        with col2:
            codigo_prog = st.text_input(
                "Código del programa", key="form_codigo_prog",
                value=_lookup(df, col_prog, programa_sel, st.session_state.mapeo.get("codigo_programa")) or ""
            )
    else:
        with col1:
            programa_sel = st.text_input("Programa de formación", key="form_programa",
                                         value="Técnico en Integración de Operaciones Logísticas")
        with col2:
            codigo_prog = st.text_input("Código del programa", key="form_codigo_prog", value="137136")

    competencia = st.text_area(
        "Competencia (código + denominación)", key="form_competencia",
        value="220201501 — Aplicar conocimientos de las ciencias naturales de acuerdo con situaciones del contexto productivo y social.",
        height=70,
    )

    # ---- PASO 2: Proyecto formativo ----
    st.subheader("Paso 2 · Proyecto formativo")
    col1, col2 = st.columns([3, 1])
    with col1:
        proyecto = st.text_area("Nombre del proyecto formativo", height=80, key="form_proyecto",
                                value="REGISTRAR EL DESARROLLO DE LAS OPERACIONES DE TRANSPORTE, ALMACENAMIENTO, DISTRIBUCIÓN, MANEJO Y CONTROL DE INVENTARIOS EN EL DEPARTAMENTO DE MANTENIMIENTO DE LA EMPRESA CARBONES DEL CERREJÓN LIMITED")
    with col2:
        fase = st.selectbox("Fase del proyecto", ["Análisis", "Planear", "Ejecución", "Evaluación"],
                            index=1, key="form_fase")
    actividad_proyecto = st.text_area("Actividad del proyecto formativo", height=70, key="form_actividad_proyecto",
                                      value="Identificar los principios y leyes de la física presentes en el transporte, almacenamiento y manejo de carga en el entorno logístico portuario del Caribe colombiano.")

    # ---- PASO 3: RAPs ----
    st.subheader("Paso 3 · Resultados de Aprendizaje (RAP)")
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

    # ---- PASO 4: Datos de la guía ----
    st.subheader("Paso 4 · Datos de esta guía")
    col1, col2 = st.columns(2)
    with col1:
        duracion = st.text_input("Duración total", key="form_duracion",
                                 value="8 horas (4 h directas + 4 h autónomas)")
        rap_focal = st.selectbox("¿Qué RAP trabaja principalmente esta guía?",
                                 ["Todos"] + [f"RAP {i+1}" for i in range(n_raps)])
    with col2:
        autor = st.text_input("Autor (instructor)", value="Carlos")
        fecha_str = st.date_input("Fecha", value=date.today()).isoformat()

    # -- Ejecutar "Generar TODO" si se pulsó --
    if gen_todo:
        if not (programa_sel and competencia and any(raps_input)):
            st.error("Para generar todo, llena al menos: programa, competencia y RAPs.")
        else:
            datos_ini = {
                "programa": programa_sel, "codigo_programa": codigo_prog,
                "proyecto_formativo": proyecto, "fase_proyecto": fase,
                "actividad_proyecto": actividad_proyecto,
                "competencia": competencia, "raps": [r for r in raps_input if r],
                "duracion": duracion,
            }
            with st.spinner("🪄 La IA está diseñando toda tu guía... (30-60 segundos)"):
                try:
                    resultado = cli_ia.generar_todo(datos_ini, instrucciones_extra=extras_todo)
                    st.session_state.form_presentacion = resultado.get("presentacion", "")
                    for k, act in resultado.get("actividades", {}).items():
                        aplicar_actividad_a_form(k, act)
                    st.session_state.form_glosario = "\n".join(
                        f"{t} | {d}" for t, d in resultado.get("glosario", [])
                    )
                    st.session_state.form_referentes = "\n".join(resultado.get("referentes", []))
                    st.success("✅ Contenido generado. Revisa cada sección y ajusta lo que necesites.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al generar: {e}")

    # ---- Presentación ----
    st.markdown("---")
    st.subheader("Paso 5 · Presentación")
    if cli_ia:
        col_btn, col_extra = st.columns([1, 2])
        with col_btn:
            gen_pres_btn = st.button("🤖 Generar presentación con IA", key="gen_pres", use_container_width=True)
        with col_extra:
            extra_pres = st.text_input("💬 Instrucción extra (opcional):", key="extra_pres",
                                       placeholder="Ej: más profesional, corta y breve",
                                       label_visibility="collapsed")
        if gen_pres_btn:
            datos_actuales = datos_desde_form()
            with st.spinner("Generando..."):
                try:
                    st.session_state.form_presentacion = cli_ia.generar_presentacion(
                        datos_actuales, instrucciones_extra=extra_pres
                    )
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
                    gen_act_btn = st.button(f"🤖 Generar {key} con IA", key=f"gen_{key}", use_container_width=True)
                with col_extra:
                    extra_act = st.text_input(f"💬 Instrucción extra ({key}):", key=f"extra_{key}",
                                              placeholder="Ej: hacer más práctica, agregar cálculo específico",
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
                "evidencias": st.text_area(f"Evidencias ({key})",
                                           height=60, key=f"ev_{key}") if key in ("3.3", "3.4") else "",
                "instrumentos": st.text_input(f"Instrumentos de evaluación ({key})",
                                              key=f"ins_{key}") if key in ("3.3", "3.4") else "",
                "duracion": st.text_input(f"Duración ({key})", key=f"dur_{key}"),
            }

    # ---- PASO 7: Glosario y referentes ----
    st.subheader("Paso 7 · Glosario y referentes")

    col_a, col_b = st.columns(2)
    with col_a:
        if cli_ia:
            gen_glo_btn = st.button("🤖 Generar glosario con IA", key="gen_glo", use_container_width=True)
            extra_glo = st.text_input("💬 Instrucción extra (glosario):", key="extra_glo",
                                      placeholder="Ej: 10 términos, incluir jerga del sector minero",
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
            gen_ref_btn = st.button("🤖 Generar referentes con IA", key="gen_ref", use_container_width=True)
            extra_ref = st.text_input("💬 Instrucción extra (referentes):", key="extra_ref",
                                      placeholder="Ej: incluir norma técnica ICONTEC",
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
    if st.button("🎯 Generar Guía del Aprendiz + Guía del Instructor + Rúbricas",
                 type="primary", use_container_width=True):
        if not programa_sel or not competencia:
            st.error("Programa y competencia son obligatorios.")
            return

        if guardar_estos and codigo_comp:
            st.session_state.raps_guardados[codigo_comp] = [r for r in raps_input if r]
            guardar_raps(st.session_state.raps_guardados)

        glosario = []
        for linea in glosario_raw.splitlines():
            if "|" in linea:
                partes = linea.split("|", 1)
                glosario.append((partes[0].strip(), partes[1].strip()))
        referentes = [r.strip() for r in referentes_raw.splitlines() if r.strip()]

        datos = {
            "programa": programa_sel, "codigo_programa": codigo_prog,
            "proyecto_formativo": proyecto, "fase_proyecto": fase,
            "actividad_proyecto": actividad_proyecto, "competencia": competencia,
            "raps": [r for r in raps_input if r], "duracion": duracion,
            "presentacion": presentacion, "actividades": actividades,
            "evidencias_tabla": _armar_tabla_evidencias(actividades, fase),
            "glosario": glosario, "referentes": referentes,
            "autor_nombre": autor, "autor_cargo": "Instructor",
            "autor_dependencia": "Centro de Formación SENA", "autor_fecha": fecha_str,
        }

        tmpdir = tempfile.mkdtemp()
        safe_prog = re.sub(r"[^\w\-]", "_", programa_sel)[:40]
        prefix = f"{safe_prog}_{fecha_str}"
        try:
            p_aprendiz = f"{tmpdir}/{prefix}_Guia_Aprendiz.docx"
            p_instructor = f"{tmpdir}/{prefix}_Guia_Instructor.docx"
            p_rubricas = f"{tmpdir}/{prefix}_Rubricas.docx"

            with st.spinner("Generando documentos..."):
                generar_guia_aprendizaje(datos, p_aprendiz)
                generar_guia_instructor(datos, p_instructor)
                generar_rubricas(datos, p_rubricas)

            st.success("✅ Los 3 documentos están listos. Descarga abajo:")
            c1, c2, c3 = st.columns(3)
            mime = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            with c1:
                with open(p_aprendiz, "rb") as f:
                    st.download_button("📥 Guía del Aprendiz", f, file_name=Path(p_aprendiz).name,
                                       mime=mime, use_container_width=True)
            with c2:
                with open(p_instructor, "rb") as f:
                    st.download_button("📥 Guía del Instructor", f, file_name=Path(p_instructor).name,
                                       mime=mime, use_container_width=True)
            with c3:
                with open(p_rubricas, "rb") as f:
                    st.download_button("📥 Rúbricas", f, file_name=Path(p_rubricas).name,
                                       mime=mime, use_container_width=True)

            guias = cargar_guias()
            guias.append({
                "fecha": fecha_str, "programa": programa_sel,
                "competencia": codigo_comp, "fase": fase,
                "rap_focal": rap_focal, "autor": autor,
            })
            guardar_guias(guias)
        except Exception as e:
            st.error(f"Error: {e}")
            st.exception(e)


# ============ OTRAS SECCIONES ============
def seccion_guias_guardadas():
    st.header("💾 Guías generadas")
    guias = cargar_guias()
    if not guias:
        st.info("Aún no has generado ninguna guía.")
        return
    df = pd.DataFrame(guias)
    st.dataframe(df, use_container_width=True)


def seccion_raps():
    st.header("📚 RAPs guardados por competencia")
    raps = cargar_raps()
    if not raps:
        st.info("Aún no has guardado RAPs.")
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


def seccion_ayuda():
    st.header("ℹ️ Ayuda")
    st.markdown("""
### 🎯 Flujo recomendado (con IA)

1. **🤖 Configurar IA**: pega tu API key gratis de Gemini (ver instrucciones en esa sección).
2. **⚙️ Cargar competencias**: sube tu Excel una sola vez.
3. **🆕 Nueva guía**:
   - Llena los datos básicos (programa, competencia, RAPs)
   - Click en **🪄 Generar todo con IA** — la IA propone presentación, actividades, glosario y referentes
   - Revisa y ajusta cada sección (los botones 🤖 en cada sección te dejan regenerar solo esa parte)
   - Click en **🎯 Generar los 3 documentos**

### 🤖 Sobre Gemini
- Capa gratuita permanente: ~10 requests/minuto, 500/día — más que suficiente.
- Obtén tu key en [aistudio.google.com/apikey](https://aistudio.google.com/apikey) (2 minutos, sin tarjeta).
- Los prompts están optimizados para SENA, nivel básico, contexto colombiano.

### 📄 Documentos generados
Los 3 documentos usan la plantilla oficial GFPI-F-135 (con logo, código y versión SENA).
""")


# ============ HELPERS ============
def _extraer_codigo(competencia_str: str) -> str:
    m = re.search(r"(\d{6,})", competencia_str)
    return m.group(1) if m else competencia_str[:20]


def _lookup(df, col_key, valor_key, col_valor):
    if not (col_key and col_valor and valor_key):
        return ""
    if col_key not in df.columns or col_valor not in df.columns:
        return ""
    fila = df[df[col_key] == valor_key]
    if fila.empty:
        return ""
    return str(fila.iloc[0][col_valor])


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
