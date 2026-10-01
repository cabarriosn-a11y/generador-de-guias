"""Redistribución de saberes y criterios del DISEÑO CURRICULAR entre los RAP de una competencia.

Regla de oro del SENA: los saberes (conceptos y proceso) y los criterios de evaluación
NO se inventan. Vienen del diseño curricular a nivel de COMPETENCIA, y en la planeación
se reparten entre sus RAP según el tema de cada uno (p. ej. un RAP de inventarios se
queda con los saberes de inventarios).

Este módulo:
- `distribuir_por_palabras()`: reparto SIN IA, por afinidad de palabras clave (funciona
  sin conexión y sirve de respaldo).
- `consolidar()`: valida una asignación (de la IA o manual) que viene por ÍNDICES — así es
  imposible inventar texto —, descarta índices inválidos y garantiza COBERTURA: ningún ítem
  del diseño queda sin RAP (los huérfanos van al RAP más afín).
- `a_texto()`: convierte los índices al texto verbatim del diseño, en el orden del diseño.
"""
from __future__ import annotations

import math
import re
import unicodedata

LISTAS = ("conceptos", "proceso", "criterios")

_STOP = set("""de la el los las y o u en con para por segun según del al a que su sus se un una
unos unas como entre sobre ante bajo desde hasta hacia sin tras mediante acuerdo cuenta teniendo
tipos tipo concepto conceptos caracteristicas características definicion definición clases
segun acorde acordes principios normas norma politicas políticas organizacion organización empresa
empresas procesos proceso procedimientos procedimiento establecidos establecidas aplicando
utilizando teniendo realizar aplicar identificar elaborar determinar""".split())


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _raiz(p: str) -> str:
    """Raíz muy simple (6 letras) para que 'inventario', 'inventarios', 'inventariar' casen."""
    return p[:6]


def palabras(texto: str) -> set[str]:
    return {_raiz(w) for w in re.findall(r"[a-zñ]{4,}", _norm(texto)) if w not in _STOP}


def _afinidad(item: str, rap: str) -> float:
    a, b = palabras(item), palabras(rap)
    if not a or not b:
        return 0.0
    return len(a & b) / math.sqrt(len(a) * len(b))


def distribuir_por_palabras(raps: list[str], listas: dict[str, list[str]]) -> list[dict[str, list[int]]]:
    """Cada ítem va al RAP con más palabras clave en común (y también a otros RAP casi
    tan afines). Los ítems sin ninguna coincidencia se reparten de forma equilibrada."""
    asign = [{k: [] for k in LISTAS} for _ in raps]
    for k in LISTAS:
        huerfanos = []
        for idx, item in enumerate(listas.get(k, [])):
            puntos = [_afinidad(item, r) for r in raps]
            mejor = max(puntos) if puntos else 0
            if mejor <= 0:
                huerfanos.append(idx)
                continue
            for j, p in enumerate(puntos):
                if p >= mejor * 0.9:                 # empates muy cercanos: también a ese RAP
                    asign[j][k].append(idx)
        for idx in huerfanos:                         # equilibrar: al RAP con menos ítems
            j = min(range(len(raps)), key=lambda r: len(asign[r][k]))
            asign[j][k].append(idx)
    return asign


def consolidar(asign_ia, raps: list[str], listas: dict[str, list[str]]) -> tuple[list[dict], dict]:
    """Valida la asignación por índices y asegura que TODO ítem del diseño quede en algún RAP.
    Devuelve (asignación, informe)."""
    n = len(raps)
    asign = [{k: [] for k in LISTAS} for _ in range(n)]
    invalidos = 0
    for entrada in (asign_ia or []):
        if not isinstance(entrada, dict):
            continue
        try:
            j = int(entrada.get("rap", 0)) - 1
        except (TypeError, ValueError):
            continue
        if not 0 <= j < n:
            continue
        for k in LISTAS:
            total = len(listas.get(k, []))
            for x in entrada.get(k, []) or []:
                try:
                    idx = int(x) - 1
                except (TypeError, ValueError):
                    invalidos += 1
                    continue
                if 0 <= idx < total and idx not in asign[j][k]:
                    asign[j][k].append(idx)
                else:
                    invalidos += 1
    # cobertura: huérfanos al RAP más afín (o al que tenga menos ítems)
    respaldo = distribuir_por_palabras(raps, listas)
    agregados = 0
    for k in LISTAS:
        usados = {i for a in asign for i in a[k]}
        for idx in range(len(listas.get(k, []))):
            if idx in usados:
                continue
            destinos = [j for j in range(n) if idx in respaldo[j][k]] or \
                       [min(range(n), key=lambda r: len(asign[r][k]))]
            asign[destinos[0]][k].append(idx)
            agregados += 1
    # mínimos: cada RAP con al menos 1 criterio y 1 saber (se COMPARTE el ítem más afín;
    # no se le quita a otro RAP)
    for j in range(n):
        for k, alternativas in (("criterios", ("criterios",)), ("saber", ("conceptos", "proceso"))):
            if any(asign[j][x] for x in alternativas):
                continue
            mejor = None
            for x in alternativas:
                for idx, item in enumerate(listas.get(x, [])):
                    p = _afinidad(item, raps[j])
                    if mejor is None or p > mejor[0]:
                        mejor = (p, x, idx)
            if mejor:
                asign[j][mejor[1]].append(mejor[2])
                agregados += 1
    for a in asign:
        for k in LISTAS:
            a[k] = sorted(set(a[k]))
    return asign, {"invalidos": invalidos, "huerfanos_reubicados": agregados}


def a_texto(asign_rap: dict[str, list[int]], listas: dict[str, list[str]]) -> dict[str, str]:
    """Índices → texto verbatim del diseño (uno por párrafo, como en el formato oficial)."""
    campo = {"conceptos": "saberes_conceptos", "proceso": "saberes_proceso",
             "criterios": "criterios_evaluacion"}
    return {campo[k]: "\n\n".join(listas[k][i] for i in asign_rap.get(k, []) if i < len(listas.get(k, [])))
            for k in LISTAS}
