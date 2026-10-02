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
                         "(autodiagnóstico y metacognición). Es GENERAL: enmarca el concepto global de "
                         "TODA la competencia, no de una sola actividad."},
    "3.3": {"letra": "A", "nombre": "Apropiación",
            "proposito": "Construir conceptos, procedimientos y actitudes mediante estudio, práctica "
                         "acompañada y retroalimentación. Se organiza en 3.3.1, 3.3.2… una por cada "
                         "actividad de aprendizaje de la planeación (tal cual), con su evidencia y, si "
                         "hace falta, sub-evidencias para saberes que no encajan en la evidencia principal."},
    "3.4": {"letra": "T", "nombre": "Transferencia del conocimiento",
            "proposito": "Actividad INTEGRADORA del aprendiz (estudio de caso, proyecto, simulación…) "
                         "que demuestre lo aprendido en el transcurso de TODA la competencia: aplicar a una "
                         "situación nueva del contexto productivo, justificar decisiones y verificar resultados."},
}
PESO_HORAS = {"3.1": 10, "3.2": 15, "3.3": 45, "3.4": 30}     # (antiguo; ya no se usa por defecto)
HORAS_MAX = {"3.1": 1, "3.4": 2}          # regla SENA: reflexión máx. 1 h, transferencia máx. 2 h
HORAS_32 = 2                              # conocimientos previos (general): sugerido, el instructor ajusta


def horas_por_momento(total: int, aas: list) -> tuple:
    """3.1 = 1 h, 3.2 = 2 h, 3.4 = 2 h y TODO lo demás a 3.3, repartido entre las AA según las horas
    que cada una tiene en la planeación. Devuelve ({momento: horas}, [horas de cada AA])."""
    total = int(total or 0)
    h31 = min(HORAS_MAX["3.1"], total)
    h34 = min(HORAS_MAX["3.4"], max(total - h31, 0))
    h32 = min(HORAS_32, max(total - h31 - h34, 0))
    h33 = max(total - h31 - h32 - h34, 0)
    pesos = [max(int(a.get("horas_directas") or 0) + int(a.get("horas_independientes") or 0), 1) for a in aas] or [1]
    return {"3.1": h31, "3.2": h32, "3.3": h33, "3.4": h34}, repartir(h33, pesos)

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
                    "saberes": [x.strip() for c in ("saberes_conceptos", "saberes_proceso")
                                for x in re.split(r"\n\s*\n|\n", str(d.get(c, "") or "")) if x.strip()],
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
    """Organización SENA: TODAS las AA de la planeación van en 3.3 (3.3.1, 3.3.2…), tal cual.
    3.4 Transferencia es una actividad integradora propia de toda la competencia."""
    return {"3.3": list(bl["aas"]), "3.4": []}


# ─────────────────────────────── 3.3 apropiación: AA + evidencia + sub-evidencias ───────────────────────────────
def saberes_sueltos(aa: dict, umbral: float = 0.12) -> list:
    """Saberes del RAP de la AA que casi no tienen relación con la actividad ni con su evidencia:
    candidatos a sub-evidencia (recomendación de los capacitadores SENA)."""
    base = _palabras(aa.get("actividad", "") + " " + aa.get("evidencia", ""))
    sueltos = []
    for x in aa.get("saberes") or []:
        w = _palabras(x)
        af = len(w & base) / math.sqrt(len(w) * len(base)) if w and base else 0
        if af < umbral:
            sueltos.append(x)
    return sueltos


def subevidencia_plantilla(saberes: list) -> str:
    temas = "; ".join(x.rstrip(". ").capitalize() for x in saberes[:4])
    return (f"Evidencia de conocimiento: elaborar una ficha explicativa o mapa conceptual sobre: {temas}, "
            "con un ejemplo aplicado al proyecto formativo.")


def descripcion_evidencia_plantilla(aa: dict) -> str:
    return ("Desarrolle la actividad en equipo y, al finalizar, entregue lo solicitado en la evidencia: "
            "documento o soporte organizado, con portada, desarrollo y conclusiones, relacionado con el "
            "proyecto formativo. Socialice los resultados y atienda la retroalimentación del instructor.")


def numerar_subs(i: int, subs: list) -> list:
    """[(numero, texto, saberes)] → '3.3.{i}.{j}'."""
    return [(f"3.3.{i}.{j}", s.get("texto", "").strip(), s.get("saberes") or [])
            for j, s in enumerate([x for x in subs if str(x.get("texto", "")).strip()], 1)]


def _con_numero(texto: str, numero: str) -> str:
    """'Evidencia de conocimiento: X' → 'Evidencia de conocimiento (3.3.1.1): X' (o la prefija)."""
    m = re.match(r"\s*(evidencias?\s+de\s+(?:conocimiento|desempe[nñ]o|producto))\s*[:.\-–]?\s*", texto, re.I)
    if m:
        return f"{m.group(1)} ({numero}): {texto[m.end():].strip()}"
    return f"Evidencia de conocimiento ({numero}): {texto.strip()}"


def evidencia_completa(aa: dict, i: int, subs: list) -> str:
    """Evidencia de la AA (planeación, tal cual) + sus sub-evidencias numeradas."""
    lineas = [aa.get("evidencia", "").strip()]
    lineas += [_con_numero(t, n) for n, t, _ in numerar_subs(i, subs)]
    return "\n".join(x for x in lineas if x)


def apropiacion_texto(aas: list, detalle: dict) -> str:
    """Descripción de 3.3: 3.3.1, 3.3.2… = AA de la planeación tal cual + evidencia +
    descripción de la evidencia + sub-evidencias."""
    bloques = []
    for i, aa in enumerate(aas, 1):
        d = detalle.get(i - 1, {}) if isinstance(detalle, dict) else {}
        lineas = [f"**3.3.{i} Actividad de aprendizaje:** {aa.get('actividad', '').strip()}"]
        if aa.get("evidencia"):
            lineas.append(f"**Evidencia:** {aa['evidencia'].strip()}")
        desc = str(d.get("desc_evidencia", "") or "").strip() or descripcion_evidencia_plantilla(aa)
        lineas.append(f"**Descripción de la evidencia:** {desc}")
        for n, t, sab in numerar_subs(i, d.get("subs") or []):
            lineas.append(f"**Sub-evidencia {n}:** {t}")
        if d.get("horas"):
            lineas.append(f"**Duración:** {d['horas']} horas")
        bloques.append("\n".join(lineas))
    return "\n" + "\n".join(bloques)        # 3.3.1 empieza en su propio párrafo, debajo del rótulo


# ─────────────────────────────── bibliografía real desde el diseño ───────────────────────────────
_RE_NORMA = re.compile(r"\b(LEY|RESOLUCI[OÓ]N|DECRETO|NTC|GTC|ISO|CIRCULAR)\s*(?:N[°º.O]*\s*)?"
                       r"(\d[\d.\-:]*)(?:\s*(?:/|DE|DEL)\s*(\d{4}))?", re.I)
_EMISOR = {"NTC": "Instituto Colombiano de Normas Técnicas y Certificación [ICONTEC]",
           "GTC": "Instituto Colombiano de Normas Técnicas y Certificación [ICONTEC]",
           "ISO": "Organización Internacional de Normalización [ISO]"}


def normas_del_diseno(textos: list) -> list:
    """Leyes, resoluciones, decretos y normas técnicas que el DISEÑO CURRICULAR cita en los saberes.
    Son reales porque vienen del propio diseño; se devuelven como referentes (APA simplificado)."""
    vistas, refs = set(), []
    for t in textos:
        for m in _RE_NORMA.finditer(str(t)):
            tipo = m.group(1).upper().replace("RESOLUCION", "RESOLUCIÓN")
            num, anio = m.group(2).strip(".-:"), m.group(3)
            if tipo in ("ISO",) and ":" in num:
                num, anio = num.split(":")[0], anio or num.split(":")[1]
            clave = (tipo, num)
            if clave in vistas or len(num) < 2:
                continue
            vistas.add(clave)
            nombre = tipo.capitalize() if tipo not in _EMISOR else tipo
            fecha = anio or "s. f."
            emisor = _EMISOR.get(tipo, "Colombia")
            titulo = f"{nombre} {num}" + (f" de {anio}" if anio and tipo not in _EMISOR else (f":{anio}" if anio else ""))
            refs.append({"apa": f"{emisor}. ({fecha}). {titulo}.", "url": "", "tema": t[:80],
                         "fuente": "Diseño curricular"})
    return refs


def transferencia_evidencia_plantilla(tecnica: dict | None) -> str:
    nombre = (tecnica or {}).get("name", "estudio de caso").lower()
    return (f"Evidencia de producto: solución integradora ({nombre}) que demuestre lo aprendido en toda la "
            "competencia, con la justificación de las decisiones tomadas.")


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
        lineas.append(f"Antes de iniciar la competencia «{bl['competencia'].split(' - ', 1)[-1].strip().capitalize()}», "
                      "identifique lo que ya sabe y lo que necesita aprender. Responda individualmente y "
                      "socialice en equipo:")
        lineas.append("- ¿Qué entiende por esta competencia y para qué le sirve en su proyecto formativo?")
        lineas += [f"- ¿Qué sabe sobre: {r.split(' - ', 1)[-1].strip().rstrip('.').lower()}?" for r in bl["raps"][:4]]
    elif momento == "3.4":
        lineas.append("Actividad integradora: resuelva en equipo la situación planteada por el instructor, "
                      "aplicando lo aprendido en TODA la competencia:")
        lineas += [f"- {r.split(' - ', 1)[-1].strip().rstrip('.').capitalize()}." for r in bl["raps"]]
        lineas.append("Justifique cada decisión, verifique los resultados y presente la solución en plenaria.")
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
                     autor: dict | None = None, apropiacion: dict | None = None,
                     transferencia: dict | None = None) -> dict:
    """`apropiacion` = {indice_AA: {"desc_evidencia", "subs": [{"texto", "saberes"}]}}
    `transferencia` = {"evidencia", "criterios": [...]} (actividad integradora de 3.4)."""
    """`momentos[k]` = {"tecnicas": [técnica,...], "descripcion", "apoyo", "horas"} para k en 3.1–3.4.
    Devuelve el diccionario que espera generar_guia_aprendizaje (formato GFPI-F-135)."""
    autor = autor or {}
    apropiacion = apropiacion or {}
    transferencia = dict(transferencia or {})
    if not transferencia.get("evidencia"):
        t34 = (momentos.get("3.4", {}).get("tecnicas") or [None])[0]
        transferencia["evidencia"] = transferencia_evidencia_plantilla(t34)
    if not transferencia.get("criterios"):        # por defecto: el primer criterio de cada RAP
        vistos = {}
        for a in bl["aas"]:
            c = [x.strip() for x in re.split(r"\n\s*\n|\n", a["criterios"]) if x.strip()]
            if c and a["rap_idx"] not in vistos:
                vistos[a["rap_idx"]] = c[0]
        transferencia["criterios"] = list(dict.fromkeys(vistos.values()))
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
        if k == "3.3":
            act["descripcion"] = apropiacion_texto(bl["aas"], apropiacion)
            evs = [evidencia_completa(a, i, apropiacion.get(i - 1, {}).get("subs") or [])
                   for i, a in enumerate(bl["aas"], 1)]
            act["evidencias"] = "\n".join(f"3.3.{i}: {e}" for i, e in enumerate(evs, 1) if e)
            act["instrumentos"] = "\n".join(dict.fromkeys(instrumento_para(e) for e in evs if e))
        if k == "3.4" and transferencia.get("evidencia"):
            act["evidencias"] = transferencia["evidencia"]
            act["instrumentos"] = instrumento_para(transferencia["evidencia"])
        actividades[k] = act

    tabla = [["Fase del proyecto formativo", "Actividad del proyecto formativo", "Actividad de Aprendizaje",
              "Evidencias de Aprendizaje", "Criterios de Evaluación", "Técnicas e Instrumentos de Evaluación"]]
    evs_aa = []
    for i, a in enumerate(bl["aas"], 1):
        ev = evidencia_completa(a, i, apropiacion.get(i - 1, {}).get("subs") or [])
        evs_aa.append(ev)
        tabla.append([a.get("fase") or bl["fase"], a.get("actividad_proyecto") or bl["actividad_proyecto"],
                      f"3.3.{i} {a['actividad']}", ev, a["criterios"], instrumento_para(ev)])
    tecs34 = "; ".join(t["name"] for t in (momentos.get("3.4", {}).get("tecnicas") or []))
    tabla.append([bl["fase"], bl["actividad_proyecto"],
                  "3.4 Actividad de transferencia (integradora de la competencia)" + (f": {tecs34}" if tecs34 else ""),
                  transferencia["evidencia"], "\n".join(transferencia["criterios"]),
                  instrumento_para(transferencia["evidencia"])])

    refs = list(dict.fromkeys(r for r in (referentes or []) if str(r).strip()))

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
        "_evidencias": [{"momento": f"3.3.{i}",
                         "fase": a.get("fase") or bl["fase"],
                         "actividad_proyecto": a.get("actividad_proyecto") or bl["actividad_proyecto"],
                         "rap": a["rap"], "actividad": a["actividad"], "evidencia": evs_aa[i - 1],
                         "saberes": a.get("saberes", []),
                         "sub_saberes": {n: sab for n, _, sab in
                                         numerar_subs(i, apropiacion.get(i - 1, {}).get("subs") or [])},
                         "criterios": [x.strip() for x in re.split(r"\n\s*\n|\n", a["criterios"]) if x.strip()]}
                        for i, a in enumerate(bl["aas"], 1)] + [{
                         "momento": "3.4", "integradora": True, "fase": bl["fase"],
                         "actividad_proyecto": bl["actividad_proyecto"], "rap": "; ".join(bl["raps"]),
                         "actividad": "Actividad de transferencia (integradora)" + (f": {tecs34}" if tecs34 else ""),
                         "evidencia": transferencia["evidencia"], "criterios": transferencia["criterios"]}],
        "_regional_centro": plan.get("regional_centro", ""),
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
    for k, tope in HORAS_MAX.items():
        if int(momentos.get(k, {}).get("horas") or 0) > tope:
            avisos.append(f"{k} {MOMENTOS[k]['nombre']}: máximo {tope} h (lleva "
                          f"{momentos[k]['horas']} h). El fuerte es 3.3.")
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
