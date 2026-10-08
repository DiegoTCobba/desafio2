"""Motor de demostración de CommunityLab (sin LLM ni nube).

Reproduce el contrato del motor real (repo `desafio`): ingesta → análisis → ruteo condicional →
generación de activos → paquete. El análisis usa heurísticas por palabras clave y los textos salen
de plantillas, así la interfaz funciona sola, sin API key ni credenciales de OCI.
"""
from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable, Optional

VOZ_MARCA_DEFAULT = (
    "Somos la comunidad ONE (Oracle Next Education + Alura). Voz cercana, inspiradora y "
    "profesional. Celebramos el esfuerzo real de las personas, sin exagerar ni prometer empleo. "
    "Tuteamos en español neutro latinoamericano, evitamos jerga corporativa y usamos como "
    "máximo 3 emojis por publicación."
)

CATEGORIAS = {
    "testimonio": "Testimonio / Logro",
    "proyecto_destacado": "Proyecto destacado",
    "pregunta_tecnica": "Pregunta técnica",
    "feedback": "Feedback",
    "debate": "Debate",
    "otro": "Otro",
}
SINONIMOS_TIPO = {
    "testimonio": "testimonio", "logro": "testimonio", "empleo": "testimonio",
    "proyecto": "proyecto_destacado", "entrega_proyecto": "proyecto_destacado",
    "proyecto_destacado": "proyecto_destacado",
    "pregunta": "pregunta_tecnica", "pregunta_tecnica": "pregunta_tecnica", "duda": "pregunta_tecnica",
    "feedback": "feedback", "queja": "feedback", "debate": "debate", "otro": "otro",
}
RUTAS = {
    "caso_exito": "🏆 Caso de éxito",
    "faq": "💡 Tip / FAQ",
    "alerta_apoyo": "🆘 Alerta de apoyo",
    "archivo": "🗂️ Archivo",
}
TIPOS_ACTIVO = {
    "post_linkedin": "LinkedIn",
    "post_x": "X / Twitter",
    "caso_exito": "Caso de éxito",
    "faq": "Tip / FAQ",
    "newsletter": "Newsletter",
    "highlights": "Community Highlights",
}
PALABRAS_ALERTA_DEFAULT = ["abandon", "no puedo mas", "frustr", "me rindo"]
HASHTAGS_BASE_DEFAULT = ["#ComunidadONE", "#TalentosTech"]

ESTADOS_TICKET = ["Pendiente", "En progreso", "Escalado", "Resuelto"]
PRIORIDADES = ["Alta", "Media", "Baja"]
SLA_DEFAULT = {"Alta": 4, "Media": 24, "Baja": 72}  # horas hasta el vencimiento

ORDEN_SENTIMIENTO = ["Altamente Positivo", "Positivo", "Neutral", "Negativo", "Altamente Negativo"]


# ============================================================ utilidades
def _norm(t: str) -> str:
    return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()


def _s(v) -> str:
    if v is None or (isinstance(v, float) and v != v):  # None o NaN
        return ""
    return str(v).strip()


def etiqueta_sentimiento(p: float) -> str:
    if p >= 0.6:
        return "Altamente Positivo"
    if p >= 0.2:
        return "Positivo"
    if p > -0.2:
        return "Neutral"
    if p > -0.6:
        return "Negativo"
    return "Altamente Negativo"


def slug(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(t)).strip("-") or "sin-periodo"


def normalizar_interacciones(raw: list) -> list[dict]:
    items, vistos = [], set()
    for n, it in enumerate(raw or []):
        if not isinstance(it, dict):
            continue
        texto = _s(it.get("texto") or it.get("mensaje") or it.get("text"))
        if not texto:
            continue
        iid = _s(it.get("id")) or f"int-{n + 1:03d}"
        while iid in vistos:
            iid += "b"
        vistos.add(iid)
        items.append({
            "id": iid,
            "autor": _s(it.get("autor") or it.get("author")) or "Anónimo",
            "canal": _s(it.get("canal") or it.get("channel")) or "#general",
            "tipo": _s(it.get("tipo") or it.get("type")),
            "texto": re.sub(r"\s+", " ", texto),
        })
    return items


def leer_lote(obj) -> tuple[Optional[str], Optional[str], list]:
    """Acepta el payload del reto ({origen_comunidad, periodo_referencia, interacciones}) o una lista."""
    if isinstance(obj, list):
        return None, None, obj
    if isinstance(obj, dict):
        return obj.get("origen_comunidad"), obj.get("periodo_referencia"), obj.get("interacciones", [])
    raise ValueError("Formato no reconocido: se espera un objeto con 'interacciones' o una lista")


# ============================================================ heurística (modo demo / respaldo)
POSITIVAS = ["gracias", "agradecid", "feliz", "logre", "logro", "seleccionad", "excelente", "increible",
             "orgull", "genial", "encant", "contrat", "aprob", "funciono", "por fin", "motivad", "util"]
NEGATIVAS = ["frustr", "no puedo", "no entiendo", "dificil", "error", "falla", "pesim", "abandon",
             "atrasad", "confund", "triste", "cansad", "perdid", "no funciona", "no me sale", "nadie responde"]
EMOJIS_POS = ["🚀", "🎉", "🙌", "❤", "👏", "😄", "😊", "🔥", "💪"]
TEMAS = {
    "LangGraph / Agentes": ["langgraph", "nodo", "router", "agente"],
    "LangChain": ["langchain", "chain", "retriever"],
    "RAG / Embeddings": ["rag", "embedding", "vector"],
    "OCI / Oracle Cloud": ["oci", "oracle", "bucket", "always free"],
    "Empleabilidad / Logros": ["seleccionad", "contrat", "empleo", "puesto", "entrevista", "trabajo"],
    "n8n / Automatización": ["n8n", "webhook", "automatiz"],
    "Prompt Engineering": ["prompt", "few-shot", "few shot"],
    "Streamlit / Interfaces": ["streamlit", "gradio", "interfaz"],
    "Python / Datos": ["python", "pandas", "dataset", "notebook"],
    "Motivación / Dificultades": ["dificil", "frustr", "abandon", "atrasad", "cansad"],
}
BASE_RELEVANCIA = {"testimonio": 80, "proyecto_destacado": 75, "pregunta_tecnica": 60,
                   "feedback": 50, "debate": 45, "otro": 25}


def analizar_heuristico(it: dict, palabras_alerta: list[str] | None = None) -> dict:
    t = _norm(it["texto"])
    pos = sum(t.count(w) for w in POSITIVAS) + sum(it["texto"].count(e) for e in EMOJIS_POS) * 0.5
    neg = sum(t.count(w) for w in NEGATIVAS)
    total = pos + neg
    puntaje = 0.0 if total == 0 else (pos - neg) / total * min(1.0, 0.45 + total / 4)

    tipo = SINONIMOS_TIPO.get(_norm(it.get("tipo", "")).replace(" ", "_"))
    if not tipo:
        if any(w in t for w in ["seleccionad", "contrat", "consegui", "aprobe"]):
            tipo = "testimonio"
        elif any(w in t for w in ["mi proyecto", "repo", "entregue", "publique", "demo"]):
            tipo = "proyecto_destacado"
        elif "?" in it["texto"] or "como " in t:
            tipo = "pregunta_tecnica"
        elif neg:
            tipo = "feedback"
        else:
            tipo = "otro"

    temas = [tema for tema, claves in TEMAS.items() if any(c in t for c in claves)][:3] or ["Comunidad general"]
    palabras = len(it["texto"].split())
    relevancia = min(100, int(BASE_RELEVANCIA[tipo] + min(15, palabras / 4) + 10 * abs(puntaje)))
    frases = re.split(r"(?<=[.!?])\s+", it["texto"])
    cita = next((f for f in frases if len(f.split()) >= 5), frases[0])
    cita = " ".join(cita.split()[:25])
    return {
        "sentimiento_puntaje": round(max(-1.0, min(1.0, puntaje)), 2),
        "categoria": tipo,
        "temas": temas,
        "relevancia": relevancia,
        "cita_destacada": cita,
        "requiere_apoyo": any(_norm(w) in t for w in (palabras_alerta or PALABRAS_ALERTA_DEFAULT) if w.strip())
                          or (puntaje <= -0.3 and tipo != "pregunta_tecnica"),
        "justificacion": "Clasificación heurística por palabras clave (motor de demostración).",
        "motor": "heuristico",
    }


def enrutar(a: dict, umbral_exito: float, umbral_alerta: float = -0.4) -> str:
    """Bifurcación condicional del flujo."""
    # Una duda técnica con un "error" no es una alerta: solo si hay señales explícitas de frustración.
    if a["requiere_apoyo"] or (a["sentimiento_puntaje"] <= umbral_alerta and a["categoria"] != "pregunta_tecnica"):
        return "alerta_apoyo"
    if a["categoria"] in ("testimonio", "proyecto_destacado") and a["sentimiento_puntaje"] >= umbral_exito:
        return "caso_exito"
    if a["categoria"] == "pregunta_tecnica":
        return "faq"
    return "archivo"


def puntaje_relevancia(a: dict) -> int:
    """Mecanismo de puntuación: 70 % valor comunicacional (LLM) + 30 % intensidad emocional."""
    return round(0.7 * a["relevancia"] + 0.3 * abs(a["sentimiento_puntaje"]) * 100)


HASHTAGS = {
    "LangGraph / Agentes": "#LangGraph", "LangChain": "#LangChain", "RAG / Embeddings": "#RAG",
    "OCI / Oracle Cloud": "#OracleCloud", "Empleabilidad / Logros": "#CarreraTech",
    "n8n / Automatización": "#Automatizacion", "Prompt Engineering": "#PromptEngineering",
    "Streamlit / Interfaces": "#Streamlit", "Python / Datos": "#Python",
}


def _nombre(autor: str) -> str:
    return autor.split()[0] if autor else "nuestra comunidad"


# ============================================================ motor
class MotorCommunityLab:
    def __init__(self, voz_marca: str = VOZ_MARCA_DEFAULT, umbral_exito: float = 0.5, max_por_ruta: int = 3,
                 umbral_alerta: float = -0.4, palabras_alerta: list[str] | None = None,
                 hashtags_base: list[str] | None = None):
        self.voz = voz_marca or VOZ_MARCA_DEFAULT
        self.umbral, self.max_por_ruta = umbral_exito, int(max_por_ruta)
        self.umbral_alerta = umbral_alerta
        self.palabras_alerta = palabras_alerta or PALABRAS_ALERTA_DEFAULT
        self.hashtags_base = hashtags_base if hashtags_base is not None else HASHTAGS_BASE_DEFAULT
        self.avisos: list[str] = []

    # ---------------------------------------------------------------- 1. análisis
    def analizar(self, items: list[dict]) -> list[dict]:
        salida = []
        for it in items:
            a = analizar_heuristico(it, self.palabras_alerta)
            a.update(it)
            a["sentimiento"] = etiqueta_sentimiento(a["sentimiento_puntaje"])
            a["ruta"] = enrutar(a, self.umbral, self.umbral_alerta)
            a["puntaje_relevancia"] = puntaje_relevancia(a)
            salida.append(a)
        return sorted(salida, key=lambda x: x["puntaje_relevancia"], reverse=True)

    # ---------------------------------------------------------------- 2. resumen
    @staticmethod
    def resumir(analisis: list[dict]) -> dict:
        n = len(analisis)
        prom = round(sum(a["sentimiento_puntaje"] for a in analisis) / n, 2) if n else 0.0
        dist = Counter(a["sentimiento"] for a in analisis)
        no_neutros = [(k, v) for k, v in dist.most_common() if k != "Neutral"]
        predominante = no_neutros[0][0] if no_neutros else "Neutral"
        temas = Counter(t for a in analisis for t in a["temas"])
        return {
            "total_interacciones_procesadas": n,
            "sentimiento_predominante": predominante,
            "puntaje_sentimiento_promedio": prom,
            "temas_principales": [t for t, _ in temas.most_common(5)],
            "frecuencia_temas": dict(temas.most_common(10)),
            "distribucion_sentimiento": {k: dist.get(k, 0) for k in ORDEN_SENTIMIENTO},
            "distribucion_categorias": dict(Counter(CATEGORIAS[a["categoria"]] for a in analisis)),
            "distribucion_rutas": dict(Counter(RUTAS[a["ruta"]] for a in analisis)),
            "alertas_apoyo": [
                {"autor": a["autor"], "canal": a["canal"], "texto": a["texto"],
                 "sentimiento": a["sentimiento"]} for a in analisis if a["ruta"] == "alerta_apoyo"
            ],
        }

    # ---------------------------------------------------------------- 3. generación
    @staticmethod
    def _activo(tipo, titulo, contenido, origen, interaccion_id=None, meta=None) -> dict:
        return {"id": uuid.uuid4().hex[:8], "tipo": tipo, "titulo": titulo, "contenido": contenido,
                "original": contenido, "titulo_original": titulo, "origen": origen,
                "interaccion_id": interaccion_id, "meta": meta or {}, "estado": "pendiente"}

    def _gen_exito(self, a: dict) -> list[dict]:
        def plantilla():
            nom = _nombre(a["autor"])
            tags = " ".join(dict.fromkeys([HASHTAGS[t] for t in a["temas"] if t in HASHTAGS] + list(self.hashtags_base)))
            caso = {"titulo": f"Caso de éxito: {a['autor']}",
                    "contexto": f"Compartido en {a['canal']} ({', '.join(a['temas'])}).",
                    "cita": a["cita_destacada"],
                    "resultado": "Logro reportado por el/la estudiante en la comunidad.",
                    "uso_sugerido": "Post de LinkedIn + sección 'Logro de la Semana' del newsletter."}
            li = {"titulo": f"De la comunidad al mercado: la historia de {nom}",
                  "copy": (f"Nada nos da más orgullo que ver a nuestra comunidad crecer 🚀\n\n"
                           f"{a['autor']} compartió en {a['canal']}:\n“{a['cita_destacada']}”\n\n"
                           f"Detrás de cada logro hay horas de práctica, proyectos reales y una comunidad que se apoya. "
                           f"Historias como la de {nom} demuestran que construir es el mejor camino para impulsar una carrera tech.\n\n"
                           f"¡Felicitaciones, {nom}! 👏\n\n{tags}"),
                  "potencial_engagement": "Alto" if a["puntaje_relevancia"] >= 75 else "Medio"}
            x = {"copy": f"🎉 {nom} lo logró: “{' '.join(a['cita_destacada'].split()[:18])}…” Así se construye una carrera tech: con proyectos reales. {(self.hashtags_base or [''])[0]}".strip()}
            return caso, li, x

        caso, li, x = plantilla()
        caso_md = (f"**Contexto:** {caso.get('contexto', '')}\n\n**Cita:** “{caso.get('cita', '')}”\n\n"
                   f"**Resultado:** {caso.get('resultado', '')}\n\n**Uso sugerido:** {caso.get('uso_sugerido', '')}")
        origen = f"{a['autor']} · {a['canal']}"
        return [
            self._activo("caso_exito", caso.get("titulo", f"Caso de éxito: {a['autor']}"), caso_md, origen, a["id"],
                         {"cita": caso.get("cita", "")}),
            self._activo("post_linkedin", li.get("titulo", ""), li.get("copy", ""), origen, a["id"],
                         {"canal_recomendado": "LinkedIn Oficial",
                          "potencial_engagement": li.get("potencial_engagement", "Medio")}),
            self._activo("post_x", f"Post X — {_nombre(a['autor'])}", x.get("copy", ""), origen, a["id"],
                         {"canal_recomendado": "X (Twitter)"}),
        ]

    def _gen_faq(self, a: dict) -> dict:
        def plantilla():
            return {"titulo": f"Tip rápido: {a['temas'][0]}",
                    "pregunta_reformulada": a["texto"],
                    "respuesta_breve": "Borrador pendiente de respuesta técnica de un mentor (motor de demostración).",
                    "pasos": ["Explicar el concepto clave en 2-3 frases",
                              "Mostrar un ejemplo mínimo reproducible",
                              "Enlazar documentación oficial y errores comunes"],
                    "snippet": "", "nivel": "Intermedio", "status": "derivado_a_mentoria"}

        d = plantilla()
        md = f"**Pregunta:** {d.get('pregunta_reformulada', '')}\n\n**Respuesta:** {d.get('respuesta_breve', '')}\n\n"
        pasos = d.get("pasos") or []
        if pasos:
            md += "**Pasos:**\n" + "\n".join(f"{i}. {p}" for i, p in enumerate(pasos, 1)) + "\n\n"
        if d.get("snippet"):
            md += f"```python\n{d['snippet']}\n```\n"
        return self._activo("faq", d.get("titulo", "Tip rápido"), md.strip(), f"{a['autor']} · {a['canal']}", a["id"],
                            {"nivel": d.get("nivel", ""), "status": d.get("status", "listo_para_revision")})

    def _gen_semanal(self, analisis, resumen, periodo) -> tuple[list[dict], str]:
        top = [{"autor": a["autor"], "canal": a["canal"], "ruta": a["ruta"], "cita": a["cita_destacada"],
                "puntaje": a["puntaje_relevancia"]} for a in analisis[:6]]
        metr = {k: resumen[k] for k in ("total_interacciones_procesadas", "sentimiento_predominante",
                                         "puntaje_sentimiento_promedio", "temas_principales")}
        metr["alertas_apoyo"] = len(resumen["alertas_apoyo"])

        def plantilla():
            exito = next((m for m in top if m["ruta"] == "caso_exito"), None)
            duda = next((m for m in top if m["ruta"] == "faq"), None)
            hl = [f"- **{metr['total_interacciones_procesadas']} interacciones** analizadas · sentimiento "
                  f"**{metr['sentimiento_predominante']}** ({metr['puntaje_sentimiento_promedio']:+.2f})",
                  f"- Temas en tendencia: {', '.join(metr['temas_principales'][:3])}"]
            if exito:
                hl.append(f"- 🏆 Logro de la semana: **{exito['autor']}** — “{exito['cita']}”")
            if duda:
                hl.append(f"- 💡 Duda destacada de **{duda['autor']}** en {duda['canal']}")
            if metr["alertas_apoyo"]:
                hl.append(f"- 🆘 {metr['alertas_apoyo']} miembro(s) necesitan acompañamiento")
            nl = ({"seccion": "Logro de la Semana", "titular": f"{exito['autor']} comparte su logro con la comunidad",
                   "resumen": exito["cita"]} if exito else
                  {"seccion": "Pulso de la Comunidad", "titular": f"Semana {periodo}: lo que más conversamos",
                   "resumen": ", ".join(metr["temas_principales"][:3])})
            lectura = (f"La comunidad muestra un sentimiento {metr['sentimiento_predominante'].lower()} "
                       f"con {metr['alertas_apoyo']} alerta(s) de apoyo.")
            return {"lectura_salud": lectura, "newsletter": nl, "highlights_markdown": "\n".join(hl)}

        d = plantilla()
        nl = d.get("newsletter", {})
        activos = [
            self._activo("newsletter", nl.get("titular", "Destaque semanal"), nl.get("resumen", ""),
                         f"Resumen {periodo}", meta={"seccion": nl.get("seccion", "Destaque")}),
            self._activo("highlights", f"Community Highlights · {periodo}", d.get("highlights_markdown", ""),
                         f"Resumen {periodo}"),
        ]
        return activos, d.get("lectura_salud", "")

    # ---------------------------------------------------------------- orquestación
    def procesar(self, payload: dict, progreso: Callable[[str], None] | None = None) -> dict:
        log = progreso or (lambda _m: None)
        origen, periodo, raw = leer_lote(payload)
        origen = payload.get("origen_comunidad", origen) or "Comunidad"
        periodo = payload.get("periodo_referencia", periodo) or datetime.now().strftime("Semana_%V")

        items = normalizar_interacciones(raw)
        if not items:
            raise ValueError("No hay interacciones con texto para procesar.")
        log(f"📥 Ingesta y limpieza: {len(items)} interacciones válidas")

        log("🧠 Analizando sentimiento, temas y relevancia (motor de demostración)")
        analisis = self.analizar(items)
        resumen = self.resumir(analisis)
        rutas = Counter(a["ruta"] for a in analisis)
        log("🔀 Ruteo condicional: " + " · ".join(f"{RUTAS[k]}: {v}" for k, v in rutas.items()))

        activos = []
        for a in [x for x in analisis if x["ruta"] == "caso_exito"][:self.max_por_ruta]:
            log(f"✍️ Caso de éxito + LinkedIn + X para {a['autor']}")
            activos += self._gen_exito(a)
        for a in [x for x in analisis if x["ruta"] == "faq"][:self.max_por_ruta]:
            log(f"💡 Tip/FAQ a partir de la duda de {a['autor']}")
            activos.append(self._gen_faq(a))
        log("📰 Newsletter y Community Highlights")
        semanales, lectura = self._gen_semanal(analisis, resumen, periodo)
        activos += semanales
        resumen["lectura_salud"] = lectura

        return {"origen_comunidad": origen, "periodo_referencia": periodo,
                "generado_en": datetime.now().isoformat(timespec="seconds"),
                "motor": {"modo": "demo", "modelo": "heuristico"},
                "resumen": resumen, "analisis": analisis, "activos": activos, "avisos": self.avisos}


# ============================================================ paquete de distribución
def construir_paquete(resultado: dict, activos: list[dict], incluir_pendientes: bool = False,
                      tickets: list[dict] | None = None) -> dict:
    sel = [a for a in activos if a["estado"] == "aprobado" or (incluir_pendientes and a["estado"] == "pendiente")]
    grupos: dict[str, list] = {"posts_linkedin": [], "posts_x": [], "casos_exito": [],
                               "sugerencias_contenido_faq": [], "destaque_newsletter_semanal": [],
                               "community_highlights": []}
    for a in sel:
        base = {"origen": a["origen"], "estado_curaduria": a["estado"]}
        t = a["tipo"]
        if t == "post_linkedin":
            grupos["posts_linkedin"].append({"titulo": a["titulo"], "copy": a["contenido"], **a["meta"], **base})
        elif t == "post_x":
            grupos["posts_x"].append({"copy": a["contenido"], "caracteres": len(a["contenido"]), **a["meta"], **base})
        elif t == "caso_exito":
            grupos["casos_exito"].append({"titulo": a["titulo"], "ficha": a["contenido"], **a["meta"], **base})
        elif t == "faq":
            grupos["sugerencias_contenido_faq"].append({"tema": a["titulo"], "contenido": a["contenido"], **a["meta"], **base})
        elif t == "newsletter":
            grupos["destaque_newsletter_semanal"].append({"seccion": a["meta"].get("seccion", ""), "titular": a["titulo"],
                                                          "resumen": a["contenido"], **base})
        elif t == "highlights":
            grupos["community_highlights"].append({"titulo": a["titulo"], "markdown": a["contenido"], **base})

    r = resultado["resumen"]
    estados = Counter(a["estado"] for a in activos)
    return {
        "status": "exito",
        "origen_comunidad": resultado["origen_comunidad"],
        "periodo_referencia": resultado["periodo_referencia"],
        "generado_en": resultado["generado_en"],
        "motor": resultado["motor"],
        "resumen_comunidad": {
            "total_interacciones_procesadas": r["total_interacciones_procesadas"],
            "sentimiento_predominante": r["sentimiento_predominante"],
            "puntaje_sentimiento_promedio": r["puntaje_sentimiento_promedio"],
            "temas_principales": r["temas_principales"],
            "distribucion_sentimiento": r["distribucion_sentimiento"],
            "alertas_apoyo": len(r["alertas_apoyo"]),
            "lectura_salud": r.get("lectura_salud", ""),
        },
        "momentos_destacados": [
            {"autor": a["autor"], "canal": a["canal"], "ruta": a["ruta"], "puntaje_relevancia": a["puntaje_relevancia"],
             "cita": a["cita_destacada"]} for a in resultado["analisis"][:5]
        ],
        "activos_distribucion_generados": {k: v for k, v in grupos.items() if v},
        "curaduria": {"aprobados": estados.get("aprobado", 0), "rechazados": estados.get("rechazado", 0),
                      "pendientes": estados.get("pendiente", 0)},
        "tickets_soporte": resumen_tickets(tickets or []),
    }


def informe_markdown(paquete: dict) -> str:
    r = paquete["resumen_comunidad"]
    ag = paquete["activos_distribucion_generados"]
    md = [f"# CommunityLab · {paquete['origen_comunidad']} · {paquete['periodo_referencia']}",
          f"_Generado: {paquete['generado_en']} · motor: {paquete['motor']['modelo']}_", "",
          "## Salud de la comunidad",
          f"- Interacciones: **{r['total_interacciones_procesadas']}**",
          f"- Sentimiento predominante: **{r['sentimiento_predominante']}**"
          + ("" if r['puntaje_sentimiento_promedio'] is None else f" ({r['puntaje_sentimiento_promedio']:+.2f})"),
          f"- Temas principales: {', '.join(r['temas_principales'])}",
          f"- Alertas de apoyo: {r['alertas_apoyo']}"]
    if r.get("lectura_salud"):
        md += ["", r["lectura_salud"]]
    for p in ag.get("community_highlights", []):
        md += ["", f"## {p['titulo']}", p["markdown"]]
    for p in ag.get("posts_linkedin", []):
        md += ["", f"## LinkedIn · {p['titulo']}", p["copy"]]
    for p in ag.get("posts_x", []):
        md += ["", "## X / Twitter", p["copy"]]
    for p in ag.get("casos_exito", []):
        md += ["", f"## {p['titulo']}", p["ficha"]]
    for p in ag.get("sugerencias_contenido_faq", []):
        md += ["", f"## {p['tema']}", p["contenido"]]
    for p in ag.get("destaque_newsletter_semanal", []):
        md += ["", f"## Newsletter · {p['seccion']}", f"**{p['titular']}**", "", p["resumen"]]
    tk = paquete.get("tickets_soporte") or {}
    if tk.get("total"):
        md += ["", "## Tickets de soporte",
               f"- Total: {tk['total']} · abiertos: {tk['abiertos']} · resueltos: {tk['resueltos']}"]
        md += [f"- **{t['id']}** · {t['prioridad']} · {t['estado']} · {t['autor']}: {t['motivo']}" for t in tk["detalle"]]
    return "\n".join(md) + "\n"


def guardar_paquete(almacen, paquete: dict, resultado: dict) -> dict:
    """Persiste el paquete en OCI Object Storage (o en el respaldo local)."""
    carpeta = f"activos/{datetime.now():%Y}-{slug(paquete['periodo_referencia'])}/{datetime.now():%Y%m%d-%H%M%S}"
    ruta = f"{carpeta}/paquete-distribucion.json"
    paquete = dict(paquete)
    paquete["almacenamiento_oci"] = {"bucket": almacen.bucket, "ruta_objeto": ruta, "destino": almacen.tipo,
                                     "status": "guardado_con_exito"}
    objetos = [
        (ruta, json.dumps(paquete, ensure_ascii=False, indent=2), "application/json"),
        (f"{carpeta}/analisis-interacciones.json",
         json.dumps(resultado["analisis"], ensure_ascii=False, indent=2), "application/json"),
        (f"{carpeta}/informe-comunidad.md", informe_markdown(paquete), "text/markdown"),
    ]
    guardados = [almacen.guardar(n, c, ct) for n, c, ct in objetos]
    ok = all(g["status"] == "guardado_con_exito" for g in guardados)
    if not ok:
        paquete["almacenamiento_oci"]["status"] = "error"
    return {"ok": ok, "carpeta": carpeta, "objetos": guardados, "paquete": paquete}


# ============================================================ opciones del request
TIPOS_POR_OPCION = {
    "generar_linkedin": {"post_linkedin", "post_x", "caso_exito"},
    "generar_newsletter": {"newsletter", "highlights"},
    "generar_faq": {"faq"},
}


def filtrar_por_opciones(activos: list[dict], opciones: dict) -> list[dict]:
    """Deja solo los tipos de activo pedidos en `opciones` (generar_linkedin, generar_newsletter, generar_faq)."""
    excluidos = set()
    for opcion, tipos in TIPOS_POR_OPCION.items():
        if opciones.get(opcion) is False:
            excluidos |= tipos
    return [a for a in activos if a["tipo"] not in excluidos]


# ============================================================ tickets
def _ahora() -> datetime:
    return datetime.now().replace(microsecond=0)


def generar_tickets(resultado: dict, activos: list[dict], sla: dict | None = None,
                    incluir_alertas: bool = True, incluir_derivadas: bool = True,
                    incluir_excedentes: bool = True) -> list[dict]:
    """Crea un ticket por cada consulta que el bot no pudo resolver solo.

    - Alerta de apoyo: un miembro con frustración o riesgo de abandono (prioridad alta).
    - Duda derivada a mentoría: el FAQ generado no tiene una respuesta confiable.
    - Duda sin atender: preguntas que superaron el máximo de mensajes a transformar por ruta.
    """
    sla = {**SLA_DEFAULT, **(sla or {})}
    faq_por_interaccion = {a["interaccion_id"]: a for a in activos if a["tipo"] == "faq"}
    tickets = []
    for a in resultado["analisis"]:
        faq = faq_por_interaccion.get(a["id"])
        if a["ruta"] == "alerta_apoyo" and incluir_alertas:
            tipo, motivo, prioridad = "Apoyo al miembro", "Frustración o riesgo de abandono", "Alta"
        elif a["ruta"] == "faq" and faq and faq["meta"].get("status") == "derivado_a_mentoria" and incluir_derivadas:
            tipo, motivo = "Duda técnica", "El bot no tiene una respuesta confiable"
            prioridad = "Media" if a["puntaje_relevancia"] >= 60 else "Baja"
        elif a["ruta"] == "faq" and not faq and incluir_excedentes:
            tipo, motivo, prioridad = "Duda técnica", "Duda sin atender (superó el máximo por ruta)", "Baja"
        else:
            continue
        creado = _ahora()
        tickets.append({
            "id": "", "relevancia": a["puntaje_relevancia"], "interaccion_id": a["id"], "activo_id": faq["id"] if faq else None,
            "tipo": tipo, "motivo": motivo, "prioridad": prioridad, "estado": "Pendiente",
            "autor": a["autor"], "canal": a["canal"], "mensaje": a["texto"], "temas": a["temas"],
            "asignado_a": "", "respuesta": "",
            "creado_en": creado.isoformat(), "vence_en": (creado + timedelta(hours=sla[prioridad])).isoformat(),
            "resuelto_en": None, "historial": [f"{creado:%H:%M} · creado automáticamente ({motivo.lower()})"],
        })
    ids_analizados = {a["id"] for a in resultado["analisis"]}
    for faq in activos:
        if (faq["tipo"] != "faq" or faq["interaccion_id"] in ids_analizados or not incluir_derivadas
                or faq["meta"].get("status") != "derivado_a_mentoria"):
            continue
        creado = _ahora()
        pregunta = re.search(r"\*\*Pregunta:\*\*\s*(.+?)(\n\n|$)", faq["contenido"], flags=re.S)
        tickets.append({
            "id": "", "relevancia": 0, "interaccion_id": faq["interaccion_id"], "activo_id": faq["id"],
            "tipo": "Duda técnica", "motivo": "El bot no tiene una respuesta confiable", "prioridad": "Media",
            "estado": "Pendiente", "autor": faq["meta"].get("autor") or faq["origen"], "canal": faq["meta"].get("canal", ""),
            "mensaje": pregunta.group(1).strip() if pregunta else faq["titulo"], "temas": [],
            "asignado_a": "", "respuesta": "",
            "creado_en": creado.isoformat(), "vence_en": (creado + timedelta(hours=sla["Media"])).isoformat(),
            "resuelto_en": None, "historial": [f"{creado:%H:%M} · creado automáticamente (derivado a mentoría)"],
        })
    orden = {p: i for i, p in enumerate(PRIORIDADES)}
    tickets.sort(key=lambda t: (orden[t["prioridad"]], -t["relevancia"]))
    for i, t in enumerate(tickets, 1):
        t["id"] = f"TCK-{i:03d}"
    return tickets


def actualizar_ticket(t: dict, estado: str | None = None, asignado_a: str | None = None,
                      respuesta: str | None = None) -> dict:
    """Aplica cambios y deja rastro en el historial."""
    hora = f"{_ahora():%H:%M}"
    if asignado_a is not None and asignado_a != t["asignado_a"]:
        t["asignado_a"] = asignado_a
        t["historial"].append(f"{hora} · asignado a {asignado_a or 'nadie'}")
    if respuesta is not None and respuesta != t["respuesta"]:
        t["respuesta"] = respuesta
        t["historial"].append(f"{hora} · respuesta actualizada")
    if estado and estado != t["estado"]:
        t["historial"].append(f"{hora} · {t['estado']} → {estado}")
        t["estado"] = estado
        t["resuelto_en"] = _ahora().isoformat() if estado == "Resuelto" else None
    return t


def horas_resolucion(t: dict) -> float | None:
    if not t.get("resuelto_en"):
        return None
    return round((datetime.fromisoformat(t["resuelto_en"]) - datetime.fromisoformat(t["creado_en"])).total_seconds() / 3600, 1)


def dentro_de_sla(t: dict) -> bool | None:
    if not t.get("resuelto_en"):
        return None
    return datetime.fromisoformat(t["resuelto_en"]) <= datetime.fromisoformat(t["vence_en"])


def ticket_vencido(t: dict) -> bool:
    return t["estado"] != "Resuelto" and datetime.fromisoformat(t["vence_en"]) < _ahora()


def respuesta_a_faq(activo: dict, respuesta: str) -> dict:
    """Usa la respuesta del equipo en el borrador del FAQ y lo marca listo para revisión."""
    activo["contenido"] = re.sub(r"\*\*Respuesta:\*\*.*?(\n\n|$)", lambda m: f"**Respuesta:** {respuesta}{m.group(1)}",
                                 activo["contenido"], count=1, flags=re.S)
    activo["meta"]["status"] = "listo_para_revision"
    activo["estado"] = "pendiente"
    return activo


def resumen_tickets(tickets: list[dict]) -> dict:
    estados = Counter(t["estado"] for t in tickets)
    return {
        "total": len(tickets),
        "abiertos": len(tickets) - estados.get("Resuelto", 0),
        "resueltos": estados.get("Resuelto", 0),
        "por_estado": dict(estados),
        "detalle": [{k: t[k] for k in ("id", "tipo", "motivo", "prioridad", "estado", "autor", "canal",
                                       "asignado_a", "respuesta", "creado_en", "resuelto_en")} for t in tickets],
    }


# ============================================================ almacenamiento local
class AlmacenLocal:
    """Guarda cada paquete en disco con la misma estructura de carpetas que el bucket de OCI."""
    tipo = "local"

    def __init__(self, bucket: str = "communitylab-activos-marketing", base: str | Path = "salida_local"):
        self.bucket = bucket
        self.raiz = Path(base) / bucket
        self.raiz.mkdir(parents=True, exist_ok=True)

    def guardar(self, nombre, contenido, content_type="application/json"):
        destino = self.raiz / nombre
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(contenido, encoding="utf-8")
        return {"objeto": nombre, "status": "guardado_con_exito"}

    def listar(self, prefijo="activos/"):
        base = self.raiz / prefijo
        if not base.exists():
            return []
        return [{"objeto": str(p.relative_to(self.raiz)).replace("\\", "/"), "tamano_bytes": p.stat().st_size,
                 "creado": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")}
                for p in sorted(base.rglob("*")) if p.is_file()]
