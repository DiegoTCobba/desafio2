"""Cliente del workflow de n8n de CommunityLab.

El frontend envía el lote al webhook `POST /communitylab/actividades` y convierte la respuesta
al formato interno de la interfaz. Acepta el contrato del enunciado del reto y variantes comunes:

- `activos_distribucion_generados` con claves en singular (`post_linkedin`, `destaque_newsletter_semanal`,
  `sugerencia_contenido_faq`) o en plural (`posts_linkedin`, …).
- Una lista `activos` con `tipo_activo` = LINKEDIN | NEWSLETTER | FAQ (esquema de base de datos).
- Análisis por interacción opcional en `analisis` o `interacciones_analizadas`.

La credencial del webhook (si la hay) se lee de `.streamlit/secrets.toml` → [n8n] o de variables
de entorno; nunca se muestra en la interfaz.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime

import motor_demo as pl

ETIQUETA_A_PUNTAJE = {"altamente positivo": 0.8, "muy positivo": 0.8, "positivo": 0.4, "neutral": 0.0, "neutro": 0.0,
                      "negativo": -0.4, "altamente negativo": -0.8, "muy negativo": -0.8}
RELEVANCIA_TEXTO = {"alta": 85, "media": 60, "baja": 30}
TIPO_ACTIVO_DB = {"LINKEDIN": "post_linkedin", "X": "post_x", "TWITTER": "post_x", "NEWSLETTER": "newsletter",
                  "FAQ": "faq", "CASO_EXITO": "caso_exito", "HIGHLIGHTS": "highlights"}
CATEGORIA_INSIGHT = {"testimonio": "testimonio", "logro": "testimonio", "proyecto": "proyecto_destacado",
                     "proyecto_destacado": "proyecto_destacado", "pregunta_tecnica": "pregunta_tecnica",
                     "duda": "pregunta_tecnica", "feedback": "feedback", "debate": "debate"}


class ErrorN8N(Exception):
    """Error con un mensaje listo para mostrar en la interfaz."""


# ============================================================ configuración
def credenciales(secrets: dict | None = None) -> dict:
    """URL y cabecera de autenticación desde secrets ([n8n]) o variables de entorno."""
    n8n = dict((secrets or {}).get("n8n", {}))
    return {
        "webhook_url": n8n.get("webhook_url") or os.getenv("N8N_WEBHOOK_URL", ""),
        "header_name": n8n.get("header_name") or os.getenv("N8N_HEADER_NAME", ""),
        "header_value": n8n.get("header_value") or os.getenv("N8N_HEADER_VALUE", ""),
    }


def _cabeceras(cred: dict) -> dict:
    h = {"Content-Type": "application/json", "Accept": "application/json"}
    if cred.get("header_name") and cred.get("header_value"):
        h[cred["header_name"]] = cred["header_value"]
    return h


# ============================================================ red
def construir_payload(origen: str, periodo: str, interacciones: list[dict], opciones: dict) -> dict:
    return {"origen_comunidad": origen, "periodo_referencia": periodo,
            "interacciones": [{k: i.get(k, "") for k in ("autor", "canal", "tipo", "texto")} for i in interacciones],
            "opciones": opciones}


def enviar(url: str, payload: dict, timeout: float = 120, cred: dict | None = None) -> dict:
    if not url:
        raise ErrorN8N("Falta la URL del webhook de n8n. Configúrala en el Panel de control.")
    req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                 headers=_cabeceras(cred or {}), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            cuerpo = r.read().decode("utf-8") or "{}"
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "replace")[:300]
        pistas = {401: "revisa la cabecera de autenticación", 403: "revisa la cabecera de autenticación",
                  404: "¿el workflow está activo y la ruta es /communitylab/actividades?",
                  400: "n8n rechazó el payload (validación)"}
        raise ErrorN8N(f"n8n respondió HTTP {e.code}: {pistas.get(e.code, 'error en el workflow')}. {detalle}") from e
    except (socket.timeout, TimeoutError) as e:
        raise ErrorN8N(f"n8n no respondió en {timeout:.0f} s. Sube el tiempo de espera o revisa el workflow.") from e
    except urllib.error.URLError as e:
        raise ErrorN8N(f"No se pudo conectar con n8n ({e.reason}). ¿Está encendido y la URL es correcta?") from e
    try:
        return json.loads(cuerpo)
    except json.JSONDecodeError as e:
        raise ErrorN8N(f"n8n respondió algo que no es JSON: {cuerpo[:200]}") from e


def probar_conexion(url: str, timeout: float = 10, cred: dict | None = None) -> tuple[bool, str]:
    """Comprueba que la URL responde sin crear un lote: hace un GET, que el webhook POST rechaza."""
    if not url:
        return False, "No hay una URL configurada."
    req = urllib.request.Request(url, headers=_cabeceras(cred or {}), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"n8n responde (HTTP {r.status})."
    except urllib.error.HTTPError as e:
        if e.code in (404, 405):
            return True, (f"El servidor responde (HTTP {e.code} a una petición GET, lo esperado para un webhook POST). "
                          "Si el workflow está activo, el procesamiento funcionará.")
        return False, f"El servidor respondió HTTP {e.code}."
    except (urllib.error.URLError, socket.timeout, TimeoutError) as e:
        return False, f"No se pudo conectar: {getattr(e, 'reason', e)}."


# ============================================================ adaptación de la respuesta
def _como_lista(v) -> list:
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _puntaje(v) -> float:
    if isinstance(v, (int, float)):
        return max(-1.0, min(1.0, float(v)))
    return ETIQUETA_A_PUNTAJE.get(str(v or "").strip().lower(), 0.0)


def _relevancia(v) -> int:
    if isinstance(v, (int, float)):
        return int(max(0, min(100, v if v > 1 else v * 100)))
    return RELEVANCIA_TEXTO.get(str(v or "").strip().lower(), 50)


def _analisis(resp: dict, payload: dict) -> list[dict]:
    filas = resp.get("analisis") or resp.get("interacciones_analizadas") or []
    salida = []
    for n, f in enumerate(filas):
        original = payload["interacciones"][n] if n < len(payload["interacciones"]) else {}
        puntaje = _puntaje(f.get("sentimiento_puntaje", f.get("sentimiento")))
        categoria = CATEGORIA_INSIGHT.get(str(f.get("tipo_insight") or f.get("categoria") or "").lower(), "otro")
        a = {
            "id": str(f.get("id_actividad") or f.get("id") or f"n8n-{n + 1:03d}"),
            "autor": f.get("autor") or original.get("autor", "Anónimo"),
            "canal": f.get("canal") or original.get("canal", ""),
            "tipo": original.get("tipo", ""),
            "texto": f.get("texto") or f.get("contenido") or original.get("texto", ""),
            "sentimiento_puntaje": round(puntaje, 2),
            "categoria": categoria,
            "temas": _como_lista(f.get("temas")) or ["Comunidad general"],
            "relevancia": _relevancia(f.get("relevancia")),
            "cita_destacada": f.get("evidencia_clave") or f.get("cita_destacada") or "",
            "requiere_apoyo": bool(f.get("requiere_apoyo", False)),
            "justificacion": f.get("resumen") or f.get("justificacion") or "Análisis de n8n.",
            "motor": "n8n",
        }
        a["sentimiento"] = pl.etiqueta_sentimiento(a["sentimiento_puntaje"])
        a["ruta"] = f.get("ruta") or pl.enrutar(a, 0.4)
        a["puntaje_relevancia"] = pl.puntaje_relevancia(a)
        salida.append(a)
    return sorted(salida, key=lambda x: x["puntaje_relevancia"], reverse=True)


def _autor_en(texto: str, analisis: list[dict]) -> dict | None:
    return next((a for a in analisis if a["autor"] and a["autor"] in (texto or "")), None)


def _activos(resp: dict, analisis: list[dict], periodo: str, payload: dict) -> list[dict]:
    nuevo = pl.MotorCommunityLab._activo
    ag = resp.get("activos_distribucion_generados") or {}
    salida = []

    def get(*claves):
        out = []
        for c in claves:
            out += _como_lista(ag.get(c))
        return out

    for p in get("post_linkedin", "posts_linkedin"):
        salida.append(nuevo("post_linkedin", p.get("titulo", "Post de LinkedIn"), p.get("copy", ""),
                            p.get("origen", "n8n"), meta={k: p[k] for k in ("canal_recomendado", "potencial_engagement")
                                                          if k in p}))
    for p in get("post_x", "posts_x"):
        salida.append(nuevo("post_x", p.get("titulo", "Post X"), p.get("copy", ""), p.get("origen", "n8n"),
                            meta={"canal_recomendado": p.get("canal_recomendado", "X (Twitter)")}))
    for p in get("caso_exito", "casos_exito"):
        salida.append(nuevo("caso_exito", p.get("titulo", "Caso de éxito"), p.get("ficha") or p.get("contenido", ""),
                            p.get("origen", "n8n")))
    for p in get("destaque_newsletter_semanal"):
        salida.append(nuevo("newsletter", p.get("titular", "Destaque semanal"), p.get("resumen", ""),
                            f"Resumen {periodo}", meta={"seccion": p.get("seccion", "Destaque")}))
    for p in get("community_highlights"):
        salida.append(nuevo("highlights", p.get("titulo", f"Community Highlights · {periodo}"),
                            p.get("markdown") or p.get("contenido", ""), f"Resumen {periodo}"))
    for p in get("sugerencia_contenido_faq", "sugerencias_contenido_faq"):
        salida.append(_faq(nuevo, p, analisis, payload))

    # Esquema de base de datos: activos con tipo_activo LINKEDIN | NEWSLETTER | FAQ
    for fila in resp.get("activos") or []:
        tipo = TIPO_ACTIVO_DB.get(str(fila.get("tipo_activo", "")).upper())
        c = fila.get("contenido") or {}
        if isinstance(c, str):
            try:
                c = json.loads(c)
            except json.JSONDecodeError:
                c = {"copy": c}
        if tipo == "faq":
            salida.append(_faq(nuevo, c, analisis, payload))
        elif tipo == "newsletter":
            salida.append(nuevo("newsletter", c.get("titular", "Destaque semanal"), c.get("resumen", ""),
                                f"Resumen {periodo}", meta={"seccion": c.get("seccion", "Destaque")}))
        elif tipo:
            salida.append(nuevo(tipo, c.get("titulo", tipo), c.get("copy") or c.get("contenido", ""), "n8n"))
        if tipo and fila.get("id_activo") is not None:
            salida[-1]["meta"]["id_activo_db"] = fila["id_activo"]
    return salida


def _faq(nuevo, p: dict, analisis: list[dict], payload: dict) -> dict:
    origen = p.get("origen", "n8n")
    # Sin análisis por interacción, se busca al autor entre los mensajes enviados.
    a = _autor_en(origen, analisis) or _autor_en(origen, payload["interacciones"])
    contenido = p.get("contenido") or p.get("contenido_sugerido") or ""
    if "**Pregunta:**" not in contenido:
        pregunta = (a or {}).get("texto") or origen
        respuesta = contenido or "Pendiente: el bot no tiene una respuesta confiable."
        contenido = f"**Pregunta:** {pregunta}\n\n**Respuesta:** {respuesta}"
    activo = nuevo("faq", p.get("tema") or p.get("titulo", "Tip rápido"), contenido, origen,
                   interaccion_id=(a or {}).get("id"),
                   meta={"status": p.get("status", "listo_para_revision"), "nivel": p.get("nivel", "")})
    if a:
        activo["meta"].update({"autor": a["autor"], "canal": a["canal"]})
    return activo


def a_resultado(resp: dict, payload: dict) -> dict:
    """Convierte la respuesta de n8n al formato que usa la interfaz."""
    estado_lote = str(resp.get("estado_lote") or resp.get("estado") or "").lower()
    if str(resp.get("status", "")).lower() in ("error", "fallido") or estado_lote == "fallido":
        raise ErrorN8N(f"n8n marcó el lote como fallido: {resp.get('mensaje') or resp.get('error') or 'sin detalle'}")

    periodo = resp.get("periodo_referencia") or payload["periodo_referencia"]
    analisis = _analisis(resp, payload)
    rc = resp.get("resumen_comunidad") or resp.get("resumen") or {}
    temas = _como_lista(rc.get("temas_principales"))
    frec = Counter(t for a in analisis for t in a["temas"]) or Counter({t: 1 for t in temas})
    dist = Counter(a["sentimiento"] for a in analisis)
    num = rc.get("puntaje_sentimiento_promedio")
    prom = (round(sum(a["sentimiento_puntaje"] for a in analisis) / len(analisis), 2) if analisis
            else (round(float(num), 2) if isinstance(num, (int, float)) else None))  # None = n8n no envió el dato
    alertas = [{"autor": a["autor"], "canal": a["canal"], "texto": a["texto"], "sentimiento": a["sentimiento"]}
               for a in analisis if a["ruta"] == "alerta_apoyo"]
    resumen = {
        "total_interacciones_procesadas": rc.get("total_interacciones_procesadas") or len(payload["interacciones"]),
        "sentimiento_predominante": rc.get("sentimiento_predominante") or "—",
        "puntaje_sentimiento_promedio": prom,
        "temas_principales": temas or [t for t, _ in frec.most_common(5)],
        "frecuencia_temas": dict(frec.most_common(10)),
        "distribucion_sentimiento": {k: dist.get(k, 0) for k in pl.ORDEN_SENTIMIENTO} if analisis else {},
        "distribucion_categorias": dict(Counter(pl.CATEGORIAS[a["categoria"]] for a in analisis)),
        "distribucion_rutas": dict(Counter(pl.RUTAS[a["ruta"]] for a in analisis)),
        "alertas_apoyo": alertas or _como_lista(rc.get("alertas_apoyo") if isinstance(rc.get("alertas_apoyo"), list) else None),
        "lectura_salud": rc.get("lectura_salud", ""),
    }
    avisos = [str(e) for e in _como_lista(resp.get("errores") or resp.get("advertencias"))]
    if estado_lote == "parcial":
        avisos.insert(0, "n8n procesó el lote de forma parcial: algunos pasos fallaron.")
    if not analisis:
        avisos.append("n8n no devolvió el análisis por interacción; el tablero muestra solo el resumen.")
    return {
        "origen_comunidad": resp.get("origen_comunidad") or payload["origen_comunidad"],
        "periodo_referencia": periodo,
        "generado_en": datetime.now().isoformat(timespec="seconds"),
        "motor": {"modo": "n8n", "modelo": resp.get("modelo") or "n8n",
                  "id_lote": resp.get("id_lote"), "estado_lote": resp.get("estado_lote") or resp.get("estado")},
        "resumen": resumen,
        "analisis": analisis,
        "activos": _activos(resp, analisis, periodo, payload),
        "almacenamiento_oci": resp.get("almacenamiento_oci"),
        "avisos": avisos,
    }


def procesar(payload: dict, url: str, timeout: float = 120, cred: dict | None = None, progreso=None) -> dict:
    log = progreso or (lambda _m: None)
    log(f"📤 Enviando {len(payload['interacciones'])} interacciones al webhook de n8n")
    resp = enviar(url, payload, timeout, cred)
    log(f"📥 Respuesta recibida · lote {resp.get('id_lote', '—')} · estado {resp.get('estado_lote', resp.get('status', '—'))}")
    resultado = a_resultado(resp, payload)
    log(f"🧩 {len(resultado['activos'])} activos y {len(resultado['analisis'])} análisis adaptados para la interfaz")
    return resultado
