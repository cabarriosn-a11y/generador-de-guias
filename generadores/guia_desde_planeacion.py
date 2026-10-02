"""Puente PLANEACIÓN PEDAGÓGICA (GFPI-F-134) → GUÍA DE APRENDIZAJE (GFPI-F-135).

La guía no se inventa: hereda de la planeación todo lo que ya está decidido
(programa, proyecto, fase, actividad de proyecto, competencia, RAP, actividades de
aprendizaje V+O+C, evidencias, criterios, horas, ambiente y materiales). Lo único que se
diseña aquí es CÓMO se desarrolla cada momento de la guía (3.1 a 3.4), apoyado en el
Atlas didáctico de 100 técnicas (UnADM, adaptado a los 4 momentos de la guía SENA).

Funciones puras (sin Streamlit), para poder probarlas y reutilizarlas en el HTML.
"""
from __future__ import annotations

import json
import math
import re
import unicodedata
from pathlib import Path

ATLAS_PATH = Path(__file__).parent.parent / "recursos" / "atlas_tecnicas_100.json"

MOMENTOS = {
    "3.1": {"letra": "R", "nombre": "Reflexión inicial",
            "proposito": "Suscitar interés y problematizar una situación del contexto; reconocer la "
                         "necesidad de aprender. No se exige dominio técnico ni se califican opiniones."},
    "3.2": {"letra": "C", "nombre": "Contextualización e identificación de conocimientos",
            "proposito": "Reconocer saberes previos, condiciones del contexto y brechas de aprendizaje "
                         "(autodiagnóstico y metacognición)."},
    "3.3": {"letra": "A", "nombre": "Apropiación",
            "proposito": "Construir conceptos, procedimientos y actitudes mediante estudio, práctica "
                         "acompañada y retroalimentación."},
    "3.4": {"letra": "T", "nombre": "Transferencia del conocimiento",
            "proposito": "Aplicar lo aprendido a una situación nueva del contexto productivo, justificar "
                         "decisiones y verificar resultados."},
}
PESO_HORAS = {"3.1": 10, "3.2": 15, "3.3": 45, "3.4": 30}     # % sugerido; el instructor ajusta

REFERENCIA_ATLAS = ("Universidad Abierta y a Distancia de México. (s. f.). 100 técnicas didácticas de "
                    "enseñanza y aprendizaje. https://100tecnicasdidacticas.unadmexico.mx/")
REFERENCIA_G060 = ("Servicio Nacional de Aprendizaje SENA. (2023). Guía de desarrollo curricular "
                   "(GFPI-G-060 V01). SENA.")


# ─────────────────────────────── utilidades ───────────────────────────────
def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


_STOP = set("de la el los las y o en con para por segun del al a que su sus se un una como entre "
            "sobre mediante acuerdo cuenta teniendo tipos concepto organizacion empresa procesos "
            "proceso establecidos aplicando utilizando".split())


def _palabras(t: str) -> set:
    return {w[:6] for w in re.findall(r"[a-zñ]{4,}", _norm(t)) if w not in _STOP}


def repartir(total: int, pesos: list) -> list:
    """Enteros que suman exacto `total`, proporcionales a `pesos` (mayor residuo)."""
    total, s = int(total or 0), sum(pesos) or 1
    exactos = [total * p / s for p in pesos]
    base = [int(x) for x in exactos]
    for i in sorted(range(len(pesos)), key=lambda k: exactos[k] - base[k], reverse=True)[:total - sum(base)]:
        base[i] += 1
    return base


# ─────────────────────────────── Atlas ───────────────────────────────
def cargar_atlas(ruta: Path | None = None) -> list:
    try:
        return json.loads(Path(ruta or ATLAS_PATH).read_text(encoding="utf-8"))
    except Exception:
        return []


# Verbo del RAP → categoría cognitiva del atlas (la del atlas es de la fuente UnADM)
_VERBO_CATEGORIA = {
    "Analizar": ("diagnostic", "analiz", "evalu", "valor", "verific", "inspeccion", "compar", "interpret",
                 "determin", "identific", "diferenci"),
    "Construir": ("elabor", "dise", "formul", "estructur", "constru", "propon", "plane", "proyect",
                  "crear", "desarroll"),
    "Aplicar": ("aplic", "oper", "ejecut", "realiz", "utiliz", "maniobr", "prepar", "almacen", "despach",
                "recib", "control", "registr", "program", "conserv", "atend", "ubic", "manipul", "alist",
                "consolid", "formaliz", "mantener", "establec", "calcul", "solucion", "practic", "implement"),
    "Explicar": ("explic", "describ", "comunic", "argument", "present", "informar", "report"),
    "Recordar": ("reconoc", "nombr", "list", "defin", "recorda"),
    "Sintetizar": ("sintetiz", "resum", "integr", "consolid", "organiz"),
}


def categoria_de_rap(rap: str) -> str:
    v = _norm((rap.split(" - ", 1)[-1] if " - " in rap else rap).split()[0] if rap.strip() else "")
    for cat, raices in _VERBO_CATEGORIA.items():
        if any(v.startswith(r) for r in raices):
            return cat
    return ""


# Técnicas de práctica (taller, demostración, simulación, examen práctico, juego de roles,
# estudio de casos, juego de negocios): preferidas cuando la evidencia es de desempeño.
PRACTICAS = {56, 35, 99, 41, 45, 66, 71}


def sugerir_tecnicas(atlas: list, momento: str, contexto: str, raps: list | None = None,
                     evidencias: str = "", n: int = 6, excluir: set | None = None) -> list:
    """Técnicas del atlas ordenadas por pertinencia para un momento de la guía:
    momento recomendado (peso fuerte) + categoría cognitiva del verbo del RAP + afinidad de
    palabras con RAP/actividades + afinidad de la evidencia orientadora con la evidencia
    de la planeación. Devuelve [(puntaje, técnica)]."""
    letra = MOMENTOS[momento]["letra"]
    cats = {categoria_de_rap(r) for r in (raps or [])} - {""}
    ctx = _palabras(contexto)
    ev = _palabras(evidencias)
    excluir = excluir or set()
    desempeno = "desempe" in _norm(evidencias) or "Aplicar" in cats
    puntuadas = []
    for t in atlas:
        if t["id"] in excluir:
            continue
        p = 0.0
        p += 3.0 if t["moment"] == letra else 0.0
        if momento in ("3.3", "3.4") and t["category"] in cats:
            p += 1.5
        if momento in ("3.3", "3.4") and desempeno and t["id"] in PRACTICAS:
            p += 1.5                                  # el RAP pide HACER: técnicas de práctica
        texto_t = _palabras(" ".join([t["name"], t["description"], t["example"]]))
        if ctx and texto_t:
            p += 2.0 * len(ctx & texto_t) / math.sqrt(len(ctx) * len(texto_t))
        if ev:
            te = _palabras(t["evidence"] + " " + t["name"])
            if te:
                p += 1.0 * len(ev & te) / math.sqrt(len(ev) * len(te))
        puntuadas.append((round(p, 3), t))
    puntuadas.sort(key=lambda x: (-x[0], x[1]["id"]))
    return puntuadas[:n]


# ─────────────────────────────── planeación → bloques ───────────────────────────────
def bloques_de_planeacion(plan: dict) -> list:
    """Cada fila de la planeación (competencia × fase × actividad de proyecto) es un candidato
    a guía. Se aplana con sus RAP y actividades de aprendizaje (AA)."""
    bloques = []
    for b, fila in enumerate(plan.get("filas", []) or []):
        raps, aas, criterios, sab_c, sab_p = [], [], [], [], []
        for j, d in enumerate(fila.get("raps_detalle") or []):
            raps.append(d.get("rap", ""))
            for campo, lista in (("criterios_evaluacion", criterios), ("saberes_conceptos", sab_c),
                                 ("saberes_proceso", sab_p)):
                for x in re.split(r"\n\s*\n|\n", str(d.get(campo, "") or "")):
                    if x.strip() and x.strip() not in lista:
                        lista.append(x.strip())
            for a in (d.get("actividades") or [d]):
                aas.append({
                    "rap_idx": j, "rap": d.get("rap", ""),
                    "fase": fila.get("fase", ""), "actividad_proyecto": fila.get("actividad_proyecto", ""),
                    "actividad": str(a.get("actividades_aprendizaje", "") or "").strip(),
                    "evidencia": str(a.get("descripcion_evidencia", "") or "").strip(),
                    "estrategias": str(a.get("estrategias_didacticas", "") or "").strip(),
                    "horas_directas": int(a.get("horas_directas") or 0),
                    "horas_independientes": int(a.get("horas_independientes") or 0),
                    "criterios": str(d.get("criterios_evaluacion", "") or "").strip(),
                })
        if not raps:
            raps = [r for r in str(fila.get("raps", "")).splitlines() if r.strip()]
        horas = sum(a["horas_directas"] + a["horas_independientes"] for a in aas) or \
            int(fila.get("horas_directas") or 0) + int(fila.get("horas_independientes") or 0)
        bloques.append({
            "indice": b, "fase": fila.get("fase", ""), "actividad_proyecto": fila.get("actividad_proyecto", ""),
            "competencia": fila.get("competencia", ""), "raps": raps, "aas": aas, "horas": horas,
            "criterios": criterios, "saberes_conceptos": sab_c, "saberes_proceso": sab_p,
            "ambiente": fila.get("ambiente") or "Polivalente",
            "materiales": fila.get("materiales") or "Marcadores borrables, papel bond, papelógrafos",
        })
    return bloques


def bloque_competencia_completa(bloques: list) -> dict:
    """Une todos los bloques (fases) de la competencia en UNA guía con todos sus RAP.
    Cada actividad de aprendizaje conserva su fase y actividad de proyecto (tabla 4)."""
    fases = list(dict.fromkeys(b["fase"] for b in bloques if b["fase"]))
    acts = list(dict.fromkeys(b["actividad_proyecto"] for b in bloques if b["actividad_proyecto"]))
    unir = lambda campo: list(dict.fromkeys(x for b in bloques for x in b[campo]))
    return {
        "indice": "todas", "fase": " / ".join(fases), "actividad_proyecto": "\n".join(acts),
        "competencia": bloques[0]["competencia"] if bloques else "",
        "raps": unir("raps"), "aas": [a for b in bloques for a in b["aas"]],
        "horas": sum(b["horas"] for b in bloques), "criterios": unir("criterios"),
        "saberes_conceptos": unir("saberes_conceptos"), "saberes_proceso": unir("saberes_proceso"),
        "ambiente": bloques[0]["ambiente"] if bloques else "Polivalente",
        "materiales": bloques[0]["materiales"] if bloques else "",
    }


def etiqueta_bloque(bl: dict) -> str:
    return (f"{bl['fase']} · {bl['competencia'][:55]} · {len(bl['raps'])} RAP · "
            f"{len(bl['aas'])} AA · {bl['horas']} h")


def instrumento_para(evidencia: str) -> str:
    """Técnica e instrumento de evaluación según el tipo de evidencia (SENA). La misma regla
    usa la sección de instrumentos, así la guía y los instrumentos nunca se contradicen."""
    from .instrumentos import instrumentos_de_evidencia
    return instrumentos_de_evidencia(evidencia)


def aas_por_momento(bl: dict) -> dict:
    """Las AA de la planeación son el eje de 3.3 y 3.4: con 1 AA, ambas la desarrollan
    (apropiación y luego transferencia); con varias, la última va a transferencia."""
    aas = bl["aas"]
    if len(aas) <= 1:
        return {"3.3": aas, "3.4": aas}
    return {"3.3": aas[:-1], "3.4": aas[-1:]}


# ─────────────────────────────── redacción sin IA (respaldo) ───────────────────────────────
def descripcion_plantilla(momento: str, tecnica: dict | None, bl: dict, aas: list) -> str:
    """Texto base cuando no hay IA: técnica del atlas + actividades V+O+C de la planeación."""
    lineas = []
    if tecnica:
        lineas.append(f"Técnica: {tecnica['name']}. {tecnica['description']}")
    if momento == "3.1":
        lineas.append("Responda de forma individual y luego socialice en plenaria: ¿qué situaciones de "
                      f"su contexto se relacionan con «{bl['actividad_proyecto'][:90].lower()}»? "
                      "¿Qué le gustaría aprender para resolverlas?")
    elif momento == "3.2":
        lineas.append("Identifique lo que ya sabe y lo que necesita aprender sobre los siguientes temas:")
        lineas += [f"- {x}" for x in (bl["saberes_conceptos"][:5] or bl["raps"][:3])]
    else:
        lineas.append("Desarrolle las siguientes actividades de aprendizaje:")
        lineas += [f"- {x}" for x in dict.fromkeys(a["actividad"] for a in aas if a["actividad"])]
    # (el ejemplo del atlas es de otro oficio: no se copia a la guía, solo orienta a la IA)
    return "\n".join(lineas)


def presentacion_plantilla(plan: dict, bl: dict) -> str:
    """Presentación base (sin IA) a partir de la planeación."""
    raps = "; ".join(r.split(" - ", 1)[-1].strip(" .").capitalize() for r in bl["raps"][:3])
    return (f"Apreciado aprendiz: esta guía orienta el desarrollo de la actividad de proyecto "
            f"«{bl['actividad_proyecto'].capitalize()}», en la fase {bl['fase'].lower()} del proyecto "
            f"formativo, como parte de la competencia {bl['competencia']}.\n\n"
            f"Al finalizar estará en capacidad de: {raps}. Para lograrlo trabajará de manera individual y "
            f"en equipo, relacionará sus saberes previos con los nuevos y construirá las evidencias que "
            f"darán cuenta de su aprendizaje durante {bl['horas']} horas de formación.")


# ─────────────────────────────── ensamblar la guía ───────────────────────────────
def armar_datos_guia(plan: dict, bl: dict, momentos: dict, presentacion: str = "",
                     glosario: list | None = None, referentes: list | None = None,
                     autor: dict | None = None) -> dict:
    """`momentos[k]` = {"tecnicas": [técnica,...], "descripcion", "apoyo", "horas"} para k en 3.1–3.4.
    Devuelve el diccionario que espera generar_guia_aprendizaje (formato GFPI-F-135)."""
    autor = autor or {}
    reparto = aas_por_momento(bl)
    actividades = {}
    for k in MOMENTOS:
        m = momentos.get(k, {})
        tecs = m.get("tecnicas") or []
        act = {
            "descripcion": m.get("descripcion", ""),
            "ambiente": bl["ambiente"],
            "estrategias": "; ".join(t["name"] for t in tecs) or m.get("estrategias", ""),
            "materiales": bl["materiales"],
            "apoyo": m.get("apoyo", ""),
            "duracion": str(m.get("horas", "")),
        }
        if k in ("3.3", "3.4"):
            aas = reparto[k]
            act["evidencias"] = "\n".join(dict.fromkeys(a["evidencia"] for a in aas if a["evidencia"]))
            act["instrumentos"] = "\n".join(dict.fromkeys(
                instrumento_para(a["evidencia"]) for a in aas if a["evidencia"]))
        actividades[k] = act

    tabla = [["Fase del proyecto formativo", "Actividad del proyecto formativo", "Actividad de Aprendizaje",
              "Evidencias de Aprendizaje", "Criterios de Evaluación", "Técnicas e Instrumentos de Evaluación"]]
    for a in bl["aas"]:
        tabla.append([a.get("fase") or bl["fase"], a.get("actividad_proyecto") or bl["actividad_proyecto"],
                      a["actividad"], a["evidencia"], a["criterios"], instrumento_para(a["evidencia"])])

    refs = list(referentes or [])
    usadas = any(m.get("tecnicas") for m in momentos.values())
    for r in ([REFERENCIA_ATLAS] if usadas else []) + [REFERENCIA_G060]:
        if r not in refs:
            refs.append(r)

    cod = plan.get("codigo_programa", "")
    return {
        "programa": plan.get("programa", ""), "codigo_programa": cod,
        "proyecto_formativo": plan.get("proyecto_formativo", ""),
        "fase_proyecto": bl["fase"], "actividad_proyecto": bl["actividad_proyecto"],
        "competencia": bl["competencia"], "raps": bl["raps"], "duracion": f"{bl['horas']} horas",
        "presentacion": presentacion or presentacion_plantilla(plan, bl), "actividades": actividades, "evidencias_tabla": tabla,
        "glosario": glosario or [], "referentes": refs,
        "autor_nombre": autor.get("nombre", ""), "autor_cargo": autor.get("cargo", "Instructor"),
        "autor_dependencia": autor.get("dependencia", ""), "autor_fecha": autor.get("fecha", ""),
        # trazabilidad (no va al formato): para instrumentos y portafolio
        # evidencias detalladas: de aquí salen los instrumentos de evaluación
        "_evidencias": [{"momento": " y ".join(k for k in ("3.3", "3.4") if any(a is x for x in reparto[k])),
                         "fase": a.get("fase") or bl["fase"],
                         "actividad_proyecto": a.get("actividad_proyecto") or bl["actividad_proyecto"],
                         "rap": a["rap"], "actividad": a["actividad"], "evidencia": a["evidencia"],
                         "criterios": [x.strip() for x in re.split(r"\n\s*\n|\n", a["criterios"]) if x.strip()]}
                        for a in bl["aas"]],
        "_saberes": list(bl.get("saberes_conceptos", [])) + list(bl.get("saberes_proceso", [])),
        "_origen": {"planeacion": plan.get("_id", ""), "bloque": bl["indice"],
                    "tecnicas": {k: [t["id"] for t in (momentos.get(k, {}).get("tecnicas") or [])]
                                 for k in MOMENTOS}},
    }


def validar_guia(bl: dict, momentos: dict) -> list:
    avisos = []
    suma = sum(int(momentos.get(k, {}).get("horas") or 0) for k in MOMENTOS)
    if suma != bl["horas"]:
        avisos.append(f"Las horas de los momentos suman {suma} h y la planeación asigna {bl['horas']} h.")
    for k, info in MOMENTOS.items():
        m = momentos.get(k, {})
        if not str(m.get("descripcion", "")).strip():
            avisos.append(f"{k} {info['nombre']}: sin descripción (al generar se llena con la plantilla; mejor redáctala con IA).")
        if not m.get("tecnicas"):
            avisos.append(f"{k} {info['nombre']}: no tiene técnica didáctica.")
        for t in m.get("tecnicas") or []:
            if t["moment"] != info["letra"]:
                avisos.append(f"{k}: «{t['name']}» se recomienda para otro momento; justifique la "
                              "adaptación (cambie propósito, acompañamiento y evidencia).")
    if not any(a["evidencia"] for a in bl["aas"]):
        avisos.append("La planeación no trae evidencias: complételas allá para que la guía las herede.")
    return avisos
