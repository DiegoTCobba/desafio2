"""CommunityLab · Interfaz Streamlit (frontend independiente)
Ingesta → Salud → Curaduría → Tickets → Paquete, más un panel de control para ajustar el sistema.
Protegida con contraseña (acceso.py) y con tema claro u oscuro (.streamlit/config.toml).
Funciona sola con el motor de demostración (motor_demo.py): sin API key ni nube.

Ejecutar:  streamlit run app.py
"""
import copy
import io
import json
from datetime import datetime, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

import acceso
import motor_demo as pl
import n8n_cliente

BASE = Path(__file__).parent
EJEMPLO = BASE / "data" / "interacciones_semana04.json"
COLUMNAS = ["autor", "canal", "tipo", "texto"]
TIPOS_ENTRADA = ["testimonio", "entrega_proyecto", "pregunta_tecnica", "feedback", "debate", "otro"]
COLOR_SENT = {"Altamente Positivo": "#1a9850", "Positivo": "#91cf60", "Neutral": "#b8b8b8",
              "Negativo": "#fc8d59", "Altamente Negativo": "#d73027"}
ICONO_ESTADO = {"pendiente": "🕓 Pendiente", "aprobado": "✅ Aprobado", "rechazado": "⛔ Rechazado"}
ICONO_PRIORIDAD = {"Alta": "🔴 Alta", "Media": "🟠 Media", "Baja": "🟢 Baja"}
ICONO_TICKET = {"Pendiente": "🕓 Pendiente", "En progreso": "🔧 En progreso", "Escalado": "⬆️ Escalado",
                "Resuelto": "✅ Resuelto"}
SIN_ASIGNAR = "Sin asignar"
MOTORES = {"demo": "Demo local (sin conexión)", "n8n": "n8n (webhook)"}
IDIOMAS = {"es": "Español", "pt": "Portugués", "en": "Inglés"}
TONOS = ["inspirador", "profesional", "cercano", "técnico"]
CONFIG_DEFAULT = {
    # Conexión y opciones que viajan en el request (las reglas de IA viven en n8n)
    "motor": "demo",
    "n8n_url": "",
    "n8n_timeout": 120,
    "generar_linkedin": True,
    "generar_newsletter": True,
    "generar_faq": True,
    "idioma": "es",
    "tono": "inspirador",
    # Reglas del motor de demostración (solo se usan sin n8n)
    "voz": pl.VOZ_MARCA_DEFAULT,
    "umbral_exito": 0.4,
    "umbral_alerta": -0.4,
    "max_por_ruta": 3,
    "palabras_alerta": list(pl.PALABRAS_ALERTA_DEFAULT),
    "hashtags_base": list(pl.HASHTAGS_BASE_DEFAULT),
    "limite_x": 280,
    "equipo": ["Mentoría técnica", "Community Manager", "Equipo académico"],
    "sla": dict(pl.SLA_DEFAULT),
    "tickets_alertas": True,
    "tickets_derivadas": True,
    "tickets_excedentes": True,
}

st.set_page_config(page_title="CommunityLab", page_icon="🚀", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.6rem;}
.hero {padding: 1.1rem 1.4rem; border-radius: 14px; margin-bottom: .8rem;
       background: linear-gradient(120deg, #C74634 0%, #7a2a8c 100%); color: #fff;}
.hero h1 {color:#fff; margin:0; font-size:1.9rem;}
.hero p {margin:.25rem 0 0; opacity:.92;}
.chip {display:inline-block; padding:2px 10px; border-radius:999px; font-size:.78rem; font-weight:600;
       margin-right:6px; background:rgba(199,70,52,.12); color:#C74634;}
.muted {color:#8a8a8a; font-size:.85rem;}
[data-testid="stMetricValue"] {font-size: 1.9rem;}
.preview {border:1px solid rgba(128,128,128,.25); border-radius:12px; padding:14px 16px; white-space:pre-wrap;}
</style>
""", unsafe_allow_html=True)

# Nada de la app se dibuja hasta que la contraseña sea correcta.
acceso_cfg = acceso.requerir_ingreso()


# ============================================================ estado
def _secrets() -> dict:
    try:
        return {k: dict(v) for k, v in st.secrets.items() if hasattr(v, "items")}
    except Exception:  # noqa: BLE001  (no existe secrets.toml)
        return {}


CRED_N8N = n8n_cliente.credenciales(_secrets())
if CRED_N8N["webhook_url"]:
    CONFIG_DEFAULT.update(motor="n8n", n8n_url=CRED_N8N["webhook_url"])


def init_state():
    defaults = {"df": None, "df_ver": 0, "origen": "Discord_Grupo_ONE_G10", "periodo": "Semana_04",
                "resultado": None, "activos": [], "guardado": None, "msg_ingesta": None,
                "listado": None, "tickets": [], "ultimo_payload": None, "msg_ticket": None,
                "msg_panel": None, "cfg_ver": 0, "config": copy.deepcopy(CONFIG_DEFAULT)}
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


def _set_lote(origen, periodo, interacciones, msg):
    items = pl.normalizar_interacciones(interacciones)
    if not items:
        st.session_state.msg_ingesta = ("error", "No se encontraron interacciones con texto.")
        return
    st.session_state.df = pd.DataFrame(items)[COLUMNAS]
    st.session_state.df_ver += 1
    if origen:
        st.session_state.origen = origen
    if periodo:
        st.session_state.periodo = periodo
    st.session_state.msg_ingesta = ("success", f"{msg}: {len(items)} interacciones cargadas.")


def cargar_ejemplo():
    o, p, it = pl.leer_lote(json.loads(EJEMPLO.read_text(encoding="utf-8")))
    _set_lote(o, p, it, "Lote de ejemplo")


def cargar_archivo(archivo):
    if archivo is None:
        st.session_state.msg_ingesta = ("warning", "Primero selecciona un archivo.")
        return
    try:
        crudo = archivo.getvalue()
        if archivo.name.lower().endswith(".csv"):
            try:
                df = pd.read_csv(io.BytesIO(crudo))
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(crudo), encoding="latin-1")
            df.columns = [c.strip().lower() for c in df.columns]
            _set_lote(None, None, df.to_dict("records"), f"CSV {archivo.name}")
        else:
            o, p, it = pl.leer_lote(json.loads(crudo.decode("utf-8")))
            _set_lote(o, p, it, f"JSON {archivo.name}")
    except Exception as e:  # noqa: BLE001
        st.session_state.msg_ingesta = ("error", f"No se pudo leer el archivo: {e}")


def cargar_pegado():
    try:
        o, p, it = pl.leer_lote(json.loads(st.session_state.get("json_pegado", "")))
        _set_lote(o, p, it, "JSON pegado")
    except Exception as e:  # noqa: BLE001
        st.session_state.msg_ingesta = ("error", f"JSON inválido: {e}")


def buscar(aid):
    return next(a for a in st.session_state.activos if a["id"] == aid)


def set_estado(aid, estado):
    buscar(aid)["estado"] = estado


def restablecer(aid):
    a = buscar(aid)
    a["contenido"], a["titulo"], a["estado"] = a["original"], a["titulo_original"], "pendiente"
    st.session_state.pop(f"txt_{aid}", None)
    st.session_state.pop(f"tit_{aid}", None)


def aprobar_pendientes():
    for a in st.session_state.activos:
        if a["estado"] == "pendiente":
            a["estado"] = "aprobado"


def reiniciar_curaduria():
    for a in st.session_state.activos:
        a["estado"] = "pendiente"


# ------------------------------------------------------------ procesamiento
def crear_motor():
    c = st.session_state.config
    return pl.MotorCommunityLab(voz_marca=c["voz"], umbral_exito=c["umbral_exito"], max_por_ruta=c["max_por_ruta"],
                                umbral_alerta=c["umbral_alerta"], palabras_alerta=c["palabras_alerta"],
                                hashtags_base=c["hashtags_base"])


def opciones_request():
    c = st.session_state.config
    return {k: c[k] for k in ("generar_linkedin", "generar_newsletter", "generar_faq", "idioma", "tono")}


def ejecutar(payload, progreso=None):
    """Procesa el lote con n8n o con el motor de demostración, según el panel de control."""
    c = st.session_state.config
    payload = {**payload, "opciones": opciones_request()}
    if c["motor"] == "n8n":
        return n8n_cliente.procesar(payload, c["n8n_url"], c["n8n_timeout"], CRED_N8N, progreso), payload
    resultado = crear_motor().procesar(payload, progreso=progreso)
    resultado["activos"] = pl.filtrar_por_opciones(resultado["activos"], payload["opciones"])
    return resultado, payload


def aplicar_resultado(resultado, payload):
    c = st.session_state.config
    for k in [k for k in st.session_state if str(k).startswith(("txt_", "tit_", "tk_"))]:
        del st.session_state[k]
    st.session_state.resultado = resultado
    st.session_state.activos = resultado["activos"]
    st.session_state.tickets = pl.generar_tickets(
        resultado, resultado["activos"], sla=c["sla"], incluir_alertas=c["tickets_alertas"],
        incluir_derivadas=c["tickets_derivadas"], incluir_excedentes=c["tickets_excedentes"])
    st.session_state.ultimo_payload = payload
    st.session_state.guardado = None
    st.session_state.listado = None


# ------------------------------------------------------------ tickets
def buscar_ticket(tid):
    return next(t for t in st.session_state.tickets if t["id"] == tid)


def _leer_widgets_ticket(t):
    asignado = st.session_state.get(f"tk_asig_{t['id']}", t["asignado_a"] or SIN_ASIGNAR)
    return ("" if asignado == SIN_ASIGNAR else asignado), st.session_state.get(f"tk_resp_{t['id']}", t["respuesta"])


def guardar_ticket(tid):
    t = buscar_ticket(tid)
    asignado, respuesta = _leer_widgets_ticket(t)
    estado = st.session_state.get(f"tk_est_{tid}", t["estado"])
    if estado == "Resuelto" and not respuesta.strip():
        st.session_state.msg_ticket = ("warning", f"{tid}: escribe una respuesta antes de marcarlo como resuelto.")
        st.session_state[f"tk_est_{tid}"] = t["estado"]
        return
    if estado == "Pendiente" and asignado and t["estado"] == "Pendiente":
        estado = "En progreso"
    pl.actualizar_ticket(t, estado=estado, asignado_a=asignado, respuesta=respuesta)
    st.session_state[f"tk_est_{tid}"] = t["estado"]
    st.session_state.msg_ticket = ("success", f"{tid} actualizado.")


def resolver_ticket(tid):
    t = buscar_ticket(tid)
    asignado, respuesta = _leer_widgets_ticket(t)
    if not respuesta.strip():
        st.session_state.msg_ticket = ("warning", f"{tid}: escribe una respuesta antes de resolverlo.")
        return
    pl.actualizar_ticket(t, estado="Resuelto", asignado_a=asignado, respuesta=respuesta)
    st.session_state[f"tk_est_{tid}"] = "Resuelto"
    msg = f"{tid} resuelto. Lo encuentras en la bandeja **Resueltos**."
    if t["activo_id"] and st.session_state.get(f"tk_faq_{tid}", True):
        activo = buscar(t["activo_id"])
        pl.respuesta_a_faq(activo, respuesta.strip())
        st.session_state.pop(f"txt_{activo['id']}", None)
        t["historial"].append(f"{datetime.now():%H:%M} · respuesta enviada al FAQ para curaduría")
        msg += " La respuesta pasó al borrador del FAQ en Curaduría."
    st.session_state.msg_ticket = ("success", msg)


def escalar_ticket(tid):
    t = buscar_ticket(tid)
    asignado, respuesta = _leer_widgets_ticket(t)
    pl.actualizar_ticket(t, estado="Escalado", asignado_a=asignado, respuesta=respuesta)
    st.session_state[f"tk_est_{tid}"] = "Escalado"
    st.session_state.msg_ticket = ("info", f"{tid} escalado.")


def reabrir_ticket(tid):
    t = buscar_ticket(tid)
    pl.actualizar_ticket(t, estado="En progreso" if t["asignado_a"] else "Pendiente")
    st.session_state[f"tk_est_{tid}"] = t["estado"]
    st.session_state.msg_ticket = ("info", f"{tid} reabierto: está de nuevo en la bandeja de abiertos.")


def crear_ticket_manual():
    autor = st.session_state.get("nt_autor", "").strip()
    mensaje = st.session_state.get("nt_mensaje", "").strip()
    if not autor or not mensaje:
        st.session_state.msg_ticket = ("warning", "Completa al menos el autor y el mensaje del ticket.")
        return
    prioridad = st.session_state.get("nt_prioridad", "Media")
    ahora = datetime.now().replace(microsecond=0)
    sla = st.session_state.config["sla"]
    nuevo = {
        "id": f"TCK-{len(st.session_state.tickets) + 1:03d}", "relevancia": 0, "interaccion_id": None,
        "activo_id": None, "tipo": st.session_state.get("nt_tipo", "Duda técnica"), "motivo": "Creado manualmente",
        "prioridad": prioridad, "estado": "Pendiente", "autor": autor,
        "canal": st.session_state.get("nt_canal", "").strip() or "#general", "mensaje": mensaje, "temas": [],
        "asignado_a": "", "respuesta": "", "creado_en": ahora.isoformat(),
        "vence_en": (ahora + timedelta(hours=sla[prioridad])).isoformat(), "resuelto_en": None,
        "historial": [f"{ahora:%H:%M} · creado manualmente"],
    }
    st.session_state.tickets.append(nuevo)
    for k in ("nt_autor", "nt_canal", "nt_mensaje"):
        st.session_state[k] = ""
    st.session_state.msg_ticket = ("success", f"{nuevo['id']} creado.")


# ------------------------------------------------------------ panel de control
def _lista(texto, sep=","):
    return [x.strip() for x in texto.replace("\n", sep).split(sep) if x.strip()]


def guardar_config():
    v = st.session_state.cfg_ver
    g = lambda k: st.session_state[f"cfg_{k}_{v}"]  # noqa: E731
    equipo = _lista(g("equipo"), "\n")
    if not equipo:
        st.session_state.msg_panel = ("warning", "El equipo de soporte necesita al menos una persona o área.")
        return
    motor = g("motor")
    url = g("n8n_url").strip()
    if motor == "n8n" and not url.startswith(("http://", "https://")):
        st.session_state.msg_panel = ("warning", "Para usar n8n, pega la URL completa del webhook (http:// o https://).")
        return
    st.session_state.config = {
        "motor": motor, "n8n_url": url, "n8n_timeout": int(g("n8n_timeout")),
        "generar_linkedin": g("generar_linkedin"), "generar_newsletter": g("generar_newsletter"),
        "generar_faq": g("generar_faq"), "idioma": g("idioma"), "tono": g("tono"),
        "voz": g("voz").strip() or pl.VOZ_MARCA_DEFAULT,
        "umbral_exito": g("umbral_exito"), "umbral_alerta": g("umbral_alerta"), "max_por_ruta": int(g("max_por_ruta")),
        "palabras_alerta": _lista(g("palabras_alerta")) or list(pl.PALABRAS_ALERTA_DEFAULT),
        "hashtags_base": [h if h.startswith("#") else f"#{h}" for h in _lista(g("hashtags_base").replace(" ", ","))],
        "limite_x": int(g("limite_x")), "equipo": equipo,
        "sla": {"Alta": int(g("sla_alta")), "Media": int(g("sla_media")), "Baja": int(g("sla_baja"))},
        "tickets_alertas": g("tk_alertas"), "tickets_derivadas": g("tk_derivadas"), "tickets_excedentes": g("tk_excedentes"),
    }
    st.session_state.msg_panel = ("success", "Configuración guardada. Se aplica en el próximo procesamiento.")


def restablecer_config():
    st.session_state.config = copy.deepcopy(CONFIG_DEFAULT)
    st.session_state.cfg_ver += 1
    st.session_state.msg_panel = ("info", "Se restablecieron los valores por defecto.")


def importar_config(archivo):
    if archivo is None:
        st.session_state.msg_panel = ("warning", "Primero selecciona un archivo de configuración.")
        return
    try:
        datos = json.loads(archivo.getvalue().decode("utf-8"))
        desconocidas = set(datos) - set(CONFIG_DEFAULT)
        if desconocidas:
            raise ValueError(f"claves desconocidas: {', '.join(sorted(desconocidas))}")
        nueva = copy.deepcopy(CONFIG_DEFAULT)
        nueva.update(datos)
        st.session_state.config = nueva
        st.session_state.cfg_ver += 1
        st.session_state.msg_panel = ("success", "Configuración importada.")
    except Exception as e:  # noqa: BLE001
        st.session_state.msg_panel = ("error", f"No se pudo importar: {e}")


def reprocesar():
    payload = st.session_state.ultimo_payload
    if payload:
        try:
            resultado, payload = ejecutar({k: v for k, v in payload.items() if k != "opciones"})
        except Exception as e:  # noqa: BLE001
            st.session_state.msg_panel = ("error", f"No se pudo reprocesar: {e}")
            return
        aplicar_resultado(resultado, payload)
        st.session_state.msg_panel = ("success", "Lote reprocesado con la configuración actual.")


def probar_n8n():
    c = st.session_state.config
    ok, msg = n8n_cliente.probar_conexion(c["n8n_url"], cred=CRED_N8N)
    st.session_state.msg_panel = ("success" if ok else "error", msg)


def limpiar_sesion():
    conservar = {k: st.session_state[k] for k in ("config", "cfg_ver", "autenticado", "acceso_ultima_actividad")
                 if k in st.session_state}
    for k in list(st.session_state.keys()):
        del st.session_state[k]
    st.session_state.update(conservar)
    st.session_state.msg_panel = ("info", "Sesión limpia. La configuración se conservó.")


init_state()

# ============================================================ barra lateral
with st.sidebar:
    st.markdown("### 🚀 CommunityLab")
    st.caption("Motor inteligente de transformación y distribución · Hackathon ONE G10")

    cfg = st.session_state.config
    if cfg["motor"] == "n8n":
        st.success("**Conectado a n8n.** El análisis, el ruteo y la generación los hace el workflow.")
    else:
        st.info("**Modo demostración.** El análisis usa heurísticas y plantillas, sin conexión. "
                "Conecta tu workflow de n8n en el **Panel de control**.")

    st.subheader("⚙️ Configuración activa")
    pedidos = [n for k, n in (("generar_linkedin", "LinkedIn"), ("generar_newsletter", "Newsletter"),
                               ("generar_faq", "FAQ")) if cfg[k]]
    st.markdown(f"- Motor: **{MOTORES[cfg['motor']]}**\n"
                f"- Genera: **{', '.join(pedidos) or 'nada'}**\n"
                f"- Idioma y tono: **{IDIOMAS[cfg['idioma']]}**, **{cfg['tono']}**\n"
                f"- Equipo de soporte: **{len(cfg['equipo'])}**")
    st.caption("Cámbiala en la pestaña **⚙️ Panel de control**.")
    abiertos = sum(t["estado"] != "Resuelto" for t in st.session_state.tickets)
    if abiertos:
        st.warning(f"🎫 {abiertos} ticket(s) abierto(s)")

    st.divider()
    if acceso_cfg["demo"]:
        st.caption("⚠️ Usas la contraseña de demostración. Configura la tuya en `.streamlit/secrets.toml`.")
    st.caption(f"🌗 Tema claro u oscuro: menú ⋮ → Settings · la sesión se cierra tras "
               f"{acceso_cfg['minutos']} min sin actividad.")
    st.button("🔒 Cerrar sesión", on_click=acceso.cerrar_sesion, width="stretch")


def almacen_activo():
    return pl.AlmacenLocal("communitylab-activos-marketing", BASE / "salida_local")


# ============================================================ encabezado
st.markdown("""<div class="hero"><h1>🚀 CommunityLab</h1>
<p>Convierte la actividad orgánica de tu comunidad en posts, casos de éxito, FAQs y resúmenes semanales listos para publicar.</p></div>""",
            unsafe_allow_html=True)

res = st.session_state.resultado
activos = st.session_state.activos
n_aprob = sum(a["estado"] == "aprobado" for a in activos)
tickets = st.session_state.tickets
# Etiquetas fijas: si una etiqueta cambia, Streamlit vuelve a la primera pestaña.
tab_in, tab_salud, tab_cur, tab_tk, tab_pkg, tab_cfg = st.tabs([
    "📥 1 · Ingesta", "📊 2 · Salud de la comunidad", "✍️ 3 · Curaduría", "🎫 4 · Tickets", "📦 5 · Paquete",
    "⚙️ Panel de control",
])

# ============================================================ 1 · ingesta
with tab_in:
    c1, c2 = st.columns([2, 1], gap="large")
    with c1:
        fuente = st.radio("Fuente de datos", ["Lote de ejemplo", "Subir JSON / CSV", "Pegar JSON"], horizontal=True)
        if fuente == "Lote de ejemplo":
            st.caption("9 mensajes simulados de un Discord de la comunidad ONE (logros, dudas, proyectos, feedback).")
            st.button("📂 Cargar lote de ejemplo", on_click=cargar_ejemplo)
        elif fuente == "Subir JSON / CSV":
            archivo = st.file_uploader("Archivo", type=["json", "csv"],
                                       help="JSON con el formato del reto o CSV con columnas autor, canal, tipo, texto.")
            st.button("📂 Cargar archivo", on_click=cargar_archivo, args=(archivo,))
        else:
            st.text_area("Payload JSON", key="json_pegado", height=180,
                         placeholder='{"origen_comunidad": "...", "periodo_referencia": "...", "interacciones": [...]}')
            st.button("📂 Cargar JSON", on_click=cargar_pegado)
    with c2:
        st.text_input("Origen de la comunidad", key="origen")
        st.text_input("Período de referencia", key="periodo")

    if st.session_state.msg_ingesta:
        nivel, texto = st.session_state.msg_ingesta
        getattr(st, nivel)(texto)

    editado = None
    if st.session_state.df is not None:
        st.markdown("#### Interacciones del lote")
        st.caption("Puedes editar, agregar o eliminar filas antes de procesar.")
        editado = st.data_editor(
            st.session_state.df, num_rows="dynamic", width="stretch", hide_index=True,
            key=f"editor_{st.session_state.df_ver}",
            column_config={
                "autor": st.column_config.TextColumn("Autor", width="small"),
                "canal": st.column_config.TextColumn("Canal", width="small"),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=TIPOS_ENTRADA, width="small"),
                "texto": st.column_config.TextColumn("Mensaje", width="large"),
            })
    else:
        st.info("Carga un lote para empezar.")

    procesar = st.button("⚡ Procesar lote y generar activos", type="primary",
                         disabled=editado is None or editado.empty)
    if procesar:
        payload = {"origen_comunidad": st.session_state.origen, "periodo_referencia": st.session_state.periodo,
                   "interacciones": editado.to_dict("records")}
        destino = "n8n" if st.session_state.config["motor"] == "n8n" else "el motor de demostración"
        with st.status(f"Procesando lote con {destino}…", expanded=True) as estado:
            try:
                resultado, payload = ejecutar(payload, progreso=estado.write)
            except Exception as e:  # noqa: BLE001
                estado.update(label="Error al procesar", state="error")
                st.error(str(e))
                st.stop()
            estado.update(label=f"Listo: {resultado['resumen']['total_interacciones_procesadas']} interacciones → "
                                f"{len(resultado['activos'])} activos generados", state="complete", expanded=False)
        aplicar_resultado(resultado, payload)
        st.rerun()

    if res:
        for aviso in res.get("avisos", []):
            st.warning(aviso)
        st.success(f"Último procesamiento: {res['generado_en']} · motor {res['motor']['modelo']} · "
                   f"{len(activos)} activos y {len(tickets)} tickets. Revisa las pestañas siguientes.")

# ============================================================ 2 · salud
with tab_salud:
    if not res:
        st.info("Procesa un lote en la pestaña **Ingesta** para ver el tablero.")
    else:
        r = res["resumen"]
        m1, m2, m3, m4 = st.columns([1, 1.8, 1, 1])
        m1.metric("Interacciones", r["total_interacciones_procesadas"])
        m2.metric("Sentimiento predominante", r["sentimiento_predominante"])
        prom = r["puntaje_sentimiento_promedio"]
        m3.metric("Puntaje promedio", "—" if prom is None else f"{prom:+.2f}", help="-1 muy negativo · +1 muy positivo")
        m4.metric("Alertas de apoyo", len(r["alertas_apoyo"]))
        if r.get("lectura_salud"):
            st.info(f"🩺 {r['lectura_salud']}")

        if not res["analisis"]:
            st.info("n8n devolvió solo el resumen del lote, sin el análisis por interacción. Para ver la distribución "
                    "de sentimiento, el mapa de momentos y el ranking, haz que el workflow incluya `analisis` en la "
                    "respuesta (ver README).")
            if r["frecuencia_temas"]:
                st.markdown("##### Temas principales")
                dt = pd.DataFrame([{"tema": k, "n": v} for k, v in r["frecuencia_temas"].items()])
                st.altair_chart(alt.Chart(dt).mark_bar(cornerRadiusEnd=4, color="#7a2a8c").encode(
                    x=alt.X("n:Q", title="Menciones", axis=alt.Axis(tickMinStep=1)),
                    y=alt.Y("tema:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
                    tooltip=["tema", "n"]).properties(height=max(160, 40 * len(dt))), width="stretch")
        else:
            df_an = pd.DataFrame(res["analisis"])
            df_an["ruta_lbl"] = df_an["ruta"].map(pl.RUTAS)
            df_an["categoria_lbl"] = df_an["categoria"].map(pl.CATEGORIAS)
            df_an["temas_txt"] = df_an["temas"].apply(", ".join)

            g1, g2 = st.columns(2, gap="large")
            with g1:
                st.markdown("##### Distribución de sentimiento")
                ds = pd.DataFrame([{"sentimiento": k, "n": v} for k, v in r["distribucion_sentimiento"].items()])
                st.altair_chart(alt.Chart(ds).mark_bar(cornerRadiusEnd=4).encode(
                    x=alt.X("n:Q", title="Interacciones", axis=alt.Axis(tickMinStep=1)),
                    y=alt.Y("sentimiento:N", sort=pl.ORDEN_SENTIMIENTO, title=None, axis=alt.Axis(labelLimit=200)),
                    color=alt.Color("sentimiento:N", scale=alt.Scale(domain=list(COLOR_SENT), range=list(COLOR_SENT.values())),
                                    legend=None),
                    tooltip=["sentimiento", "n"]).properties(height=220), width="stretch")
            with g2:
                st.markdown("##### Temas en tendencia")
                dt = pd.DataFrame([{"tema": k, "n": v} for k, v in r["frecuencia_temas"].items()])
                st.altair_chart(alt.Chart(dt).mark_bar(cornerRadiusEnd=4, color="#7a2a8c").encode(
                    x=alt.X("n:Q", title="Menciones", axis=alt.Axis(tickMinStep=1)),
                    y=alt.Y("tema:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
                    tooltip=["tema", "n"]).properties(height=max(220, 28 * len(dt))),
                    width="stretch")

            g3, g4 = st.columns([3, 2], gap="large")
            with g3:
                st.markdown("##### Mapa de momentos (sentimiento × relevancia)")
                st.altair_chart(alt.Chart(df_an).mark_circle(size=220, opacity=.85).encode(
                    x=alt.X("sentimiento_puntaje:Q", title="Sentimiento", scale=alt.Scale(domain=[-1, 1])),
                    y=alt.Y("puntaje_relevancia:Q", title="Relevancia", scale=alt.Scale(domain=[0, 100])),
                    color=alt.Color("ruta_lbl:N", title="Ruta"),
                    tooltip=["autor", "canal", "ruta_lbl", "puntaje_relevancia", "sentimiento", "texto"]
                ).properties(height=280), width="stretch")
            with g4:
                st.markdown("##### Ruteo del flujo")
                dr = pd.DataFrame([{"ruta": k, "n": v} for k, v in r["distribucion_rutas"].items()])
                st.altair_chart(alt.Chart(dr).mark_arc(innerRadius=55).encode(
                    theta="n:Q", color=alt.Color("ruta:N", title=None, legend=alt.Legend(orient="bottom", columns=2)),
                    tooltip=["ruta", "n"]).properties(height=280), width="stretch")

            st.markdown("##### Ranking de interacciones")
            st.dataframe(
                df_an[["puntaje_relevancia", "autor", "canal", "categoria_lbl", "sentimiento", "sentimiento_puntaje",
                       "ruta_lbl", "temas_txt", "cita_destacada", "justificacion"]],
                hide_index=True, width="stretch",
                column_config={
                    "puntaje_relevancia": st.column_config.ProgressColumn("Relevancia", min_value=0, max_value=100, format="%d"),
                    "autor": "Autor", "canal": "Canal", "categoria_lbl": "Categoría", "sentimiento": "Sentimiento",
                    "sentimiento_puntaje": st.column_config.NumberColumn("Puntaje", format="%+.2f"),
                    "ruta_lbl": "Ruta", "temas_txt": "Temas", "cita_destacada": "Cita destacada",
                    "justificacion": "Justificación"})

            if r["alertas_apoyo"]:
                st.markdown("##### 🆘 Miembros que necesitan apoyo")
                for al in r["alertas_apoyo"]:
                    st.error(f"**{al['autor']}** en `{al['canal']}` · {al['sentimiento']}\n\n> {al['texto']}")

# ============================================================ 3 · curaduría
with tab_cur:
    if not activos:
        st.info("Aún no hay activos generados.")
    else:
        f1, f2, f3, f4 = st.columns([3, 2, 1.2, 1.2])
        tipos_sel = f1.multiselect("Tipo de activo", list(pl.TIPOS_ACTIVO), default=list(pl.TIPOS_ACTIVO),
                                   format_func=pl.TIPOS_ACTIVO.get)
        estado_sel = f2.selectbox("Estado", ["Todos", "pendiente", "aprobado", "rechazado"],
                                  format_func=lambda x: ICONO_ESTADO.get(x, x))
        f3.button("✅ Aprobar pendientes", on_click=aprobar_pendientes, width="stretch")
        f4.button("↺ Reiniciar", on_click=reiniciar_curaduria, width="stretch")

        visibles = [a for a in activos if a["tipo"] in tipos_sel and (estado_sel == "Todos" or a["estado"] == estado_sel)]
        st.progress(n_aprob / len(activos), text=f"{n_aprob} de {len(activos)} activos aprobados")
        st.caption(f"Mostrando {len(visibles)} de {len(activos)} activos · edita el texto directamente; los cambios se guardan al salir del campo.")

        for a in visibles:
            with st.container(border=True):
                h1, h2 = st.columns([5, 1])
                h1.markdown(f"<span class='chip'>{pl.TIPOS_ACTIVO[a['tipo']]}</span>"
                            f"<span class='muted'>Origen: {a['origen']}</span>", unsafe_allow_html=True)
                h2.markdown(f"**{ICONO_ESTADO[a['estado']]}**")

                a["titulo"] = st.text_input("Título", value=a["titulo"], key=f"tit_{a['id']}")
                alto = 120 if a["tipo"] == "post_x" else 240
                a["contenido"] = st.text_area("Contenido", value=a["contenido"], key=f"txt_{a['id']}", height=alto)

                info = []
                if a["tipo"] == "post_x":
                    n = len(a["contenido"])
                    lim = st.session_state.config["limite_x"]
                    info.append(f"{'🔴' if n > lim else '🟢'} {n}/{lim} caracteres")
                elif a["tipo"] == "post_linkedin":
                    info.append(f"{len(a['contenido'])} caracteres · engagement estimado: "
                                f"{a['meta'].get('potencial_engagement', '—')}")
                elif a["tipo"] == "faq":
                    info.append(f"Nivel: {a['meta'].get('nivel', '—')} · status: {a['meta'].get('status', '—')}")
                elif a["tipo"] == "newsletter":
                    info.append(f"Sección: {a['meta'].get('seccion', '—')}")
                if a["contenido"] != a["original"] or a["titulo"] != a["titulo_original"]:
                    info.append("✏️ editado")
                st.caption(" · ".join(info))

                b1, b2, b3, b4 = st.columns([1, 1, 1, 3])
                b1.button("✅ Aprobar", key=f"ap_{a['id']}", on_click=set_estado, args=(a["id"], "aprobado"),
                          disabled=a["estado"] == "aprobado", width="stretch")
                b2.button("⛔ Rechazar", key=f"re_{a['id']}", on_click=set_estado, args=(a["id"], "rechazado"),
                          disabled=a["estado"] == "rechazado", width="stretch")
                b3.button("↩️ Restablecer", key=f"rs_{a['id']}", on_click=restablecer, args=(a["id"],),
                          width="stretch")
                with b4.popover("👁️ Vista previa", width="stretch"):
                    if a["tipo"] in ("post_linkedin", "post_x"):
                        st.markdown(f"**{st.session_state.origen}** · {a['meta'].get('canal_recomendado', '')}")
                        st.markdown(f"<div class='preview'>{a['contenido']}</div>", unsafe_allow_html=True)
                    else:
                        st.markdown(f"### {a['titulo']}")
                        st.markdown(a["contenido"])

# ============================================================ 4 · tickets
with tab_tk:
    if not res:
        st.info("Procesa un lote para ver las consultas que el bot no pudo resolver solo.")
    else:
        cfg = st.session_state.config
        abiertos = [t for t in tickets if t["estado"] != "Resuelto"]
        vencidos = [t for t in abiertos if pl.ticket_vencido(t)]
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Abiertos", len(abiertos))
        k2.metric("Prioridad alta abiertos", sum(t["prioridad"] == "Alta" for t in abiertos))
        k3.metric("Vencidos", len(vencidos), help="Abiertos que ya pasaron su SLA.")
        k4.metric("Resueltos", len(tickets) - len(abiertos))
        if tickets:
            st.progress((len(tickets) - len(abiertos)) / len(tickets),
                        text=f"{len(tickets) - len(abiertos)} de {len(tickets)} tickets resueltos")
        st.caption("Se crea un ticket cuando el bot no puede resolver una consulta solo: miembros que necesitan apoyo, "
                   "dudas sin respuesta confiable y dudas que superaron el máximo por ruta.")

        if st.session_state.msg_ticket:
            nivel, texto = st.session_state.msg_ticket
            getattr(st, nivel)(texto)
            st.session_state.msg_ticket = None

        resueltos = [t for t in tickets if t["estado"] == "Resuelto"]
        bandeja = st.radio("Bandeja", ["Abiertos", "Resueltos", "Todos"], horizontal=True, key="bandeja_tickets",
                           captions=[f"{len(abiertos)} ticket(s)", f"{len(resueltos)} ticket(s)", f"{len(tickets)} ticket(s)"])
        f1, f2, f3 = st.columns(3)
        if bandeja == "Abiertos":
            est_sel = f1.multiselect("Estado", ["Pendiente", "En progreso", "Escalado"],
                                     default=["Pendiente", "En progreso", "Escalado"], format_func=ICONO_TICKET.get)
        else:
            est_sel = ["Resuelto"] if bandeja == "Resueltos" else pl.ESTADOS_TICKET
        pri_sel = f2.multiselect("Prioridad", pl.PRIORIDADES, default=pl.PRIORIDADES, format_func=ICONO_PRIORIDAD.get)
        resp_sel = f3.selectbox("Responsable", ["Todos", SIN_ASIGNAR] + cfg["equipo"])
        visibles = [t for t in tickets if t["estado"] in est_sel and t["prioridad"] in pri_sel
                    and (resp_sel == "Todos" or (t["asignado_a"] or SIN_ASIGNAR) == resp_sel)]

        if bandeja == "Resueltos" and resueltos:
            horas = [pl.horas_resolucion(t) for t in resueltos]
            en_sla = sum(bool(pl.dentro_de_sla(t)) for t in resueltos)
            st.caption(f"Tiempo medio de resolución: **{sum(horas) / len(horas):.1f} h** · "
                       f"**{en_sla} de {len(resueltos)}** dentro del SLA")

        if not tickets:
            st.success("No hay tickets: el bot pudo atender todas las consultas de este lote.")
        elif bandeja == "Resueltos" and not resueltos:
            st.info("Aún no hay tickets resueltos. Cuando resuelvas uno, aparecerá aquí con su respuesta.")
        elif not visibles:
            st.info("Ningún ticket coincide con los filtros.")

        opciones_resp = [SIN_ASIGNAR] + cfg["equipo"]
        for t in visibles:
            tid = t["id"]
            st.session_state.setdefault(f"tk_est_{tid}", t["estado"])
            st.session_state.setdefault(f"tk_asig_{tid}", t["asignado_a"] if t["asignado_a"] in cfg["equipo"] else SIN_ASIGNAR)
            st.session_state.setdefault(f"tk_resp_{tid}", t["respuesta"])
            with st.container(border=True):
                h1, h2 = st.columns([5, 1.4])
                vence = datetime.fromisoformat(t["vence_en"])
                aviso = " · ⏰ **vencido**" if pl.ticket_vencido(t) else (
                    "" if t["estado"] == "Resuelto" else f" · vence {vence:%d/%m %H:%M}")
                h1.markdown(f"**{tid}** · {ICONO_PRIORIDAD[t['prioridad']]} · <span class='chip'>{t['tipo']}</span>"
                            f"<span class='muted'>{t['autor']} · {t['canal']}{aviso}</span>", unsafe_allow_html=True)
                h2.markdown(f"**{ICONO_TICKET[t['estado']]}**")
                st.markdown(f"> {t['mensaje']}")
                st.caption(f"Motivo: {t['motivo']}" + (f" · Temas: {', '.join(t['temas'])}" if t["temas"] else ""))

                resuelto = t["estado"] == "Resuelto"
                if resuelto:
                    st.success(f"**Respuesta** ({t['asignado_a'] or 'sin responsable'}): {t['respuesta']}")
                    sla_ok = pl.dentro_de_sla(t)
                    st.caption(f"Resuelto el {datetime.fromisoformat(t['resuelto_en']):%d/%m %H:%M} · "
                               f"en {pl.horas_resolucion(t)} h · "
                               + ("✅ dentro del SLA" if sla_ok else "⚠️ fuera del SLA"))
                else:
                    c1, c2 = st.columns(2)
                    c1.selectbox("Responsable", opciones_resp, key=f"tk_asig_{tid}")
                    c2.selectbox("Estado", pl.ESTADOS_TICKET, key=f"tk_est_{tid}", format_func=ICONO_TICKET.get)
                    st.text_area("Respuesta al miembro", key=f"tk_resp_{tid}", height=100,
                                 placeholder="Escribe la respuesta o la acción tomada…")
                    if t["activo_id"]:
                        st.checkbox("Usar esta respuesta en el borrador del FAQ", value=True, key=f"tk_faq_{tid}")

                b1, b2, b3, b4 = st.columns([1, 1, 1, 2])
                if resuelto:
                    b1.button("↩️ Reabrir", key=f"tk_reab_{tid}", on_click=reabrir_ticket, args=(tid,), width="stretch")
                else:
                    b1.button("💾 Guardar", key=f"tk_guar_{tid}", on_click=guardar_ticket, args=(tid,), width="stretch")
                    b2.button("✅ Resolver", key=f"tk_res_{tid}", on_click=resolver_ticket, args=(tid,),
                              type="primary", width="stretch")
                    b3.button("⬆️ Escalar", key=f"tk_esc_{tid}", on_click=escalar_ticket, args=(tid,),
                              disabled=t["estado"] == "Escalado", width="stretch")
                with b4.popover("🕘 Historial", width="stretch"):
                    for linea in t["historial"]:
                        st.markdown(f"- {linea}")

        with st.expander("➕ Crear ticket manual"):
            m1, m2 = st.columns(2)
            m1.text_input("Autor", key="nt_autor")
            m2.text_input("Canal", key="nt_canal", placeholder="#general")
            m3, m4 = st.columns(2)
            m3.selectbox("Tipo", ["Duda técnica", "Apoyo al miembro", "Incidencia de contenido", "Otro"], key="nt_tipo")
            m4.selectbox("Prioridad", pl.PRIORIDADES, index=1, key="nt_prioridad", format_func=ICONO_PRIORIDAD.get)
            st.text_area("Mensaje", key="nt_mensaje", height=80)
            st.button("Crear ticket", on_click=crear_ticket_manual)

        if tickets:
            df_tk = pd.DataFrame(pl.resumen_tickets(tickets)["detalle"])
            st.download_button("⬇️ Exportar tickets (CSV)", df_tk.to_csv(index=False).encode("utf-8-sig"),
                               f"tickets-{pl.slug(res['periodo_referencia'])}.csv", "text/csv")

# ============================================================ 5 · paquete
with tab_pkg:
    if not res:
        st.info("Procesa un lote y aprueba activos para armar el paquete de distribución.")
    else:
        incluir = st.toggle("Incluir activos pendientes (no aprobados aún)", value=False)
        paquete = pl.construir_paquete(res, activos, incluir, tickets=tickets)
        cur = paquete["curaduria"]
        n_pkg = sum(len(v) for v in paquete["activos_distribucion_generados"].values())
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Activos en el paquete", n_pkg)
        k2.metric("Aprobados", cur["aprobados"])
        k3.metric("Pendientes", cur["pendientes"])
        k4.metric("Rechazados", cur["rechazados"])

        p1, p2 = st.columns([3, 2], gap="large")
        with p1:
            st.markdown("##### Vista del paquete")
            vista = st.session_state.guardado["paquete"] if st.session_state.guardado else paquete
            st.json(vista, expanded=1)
            d1, d2 = st.columns(2)
            nombre = f"paquete-{pl.slug(res['periodo_referencia'])}"
            d1.download_button("⬇️ Descargar JSON", json.dumps(vista, ensure_ascii=False, indent=2),
                               f"{nombre}.json", "application/json", width="stretch")
            d2.download_button("⬇️ Descargar informe (.md)", pl.informe_markdown(vista), f"{nombre}.md",
                               "text/markdown", width="stretch")
        with p2:
            destino = almacen_activo()
            oci = res.get("almacenamiento_oci") or {}
            if oci:
                (st.success if oci.get("status") == "guardado_con_exito" else st.warning)(
                    f"**n8n ya guardó el paquete del lote en OCI** ({oci.get('status', '—')}): "
                    f"`{oci.get('bucket', '')}/{oci.get('ruta_objeto', '')}`")
            st.markdown("##### Guardar la versión curada")
            st.info(f"Guarda lo aprobado en `salida_local/{destino.bucket}/` con la misma estructura de carpetas "
                    "que el bucket de OCI.")
            if n_pkg == 0:
                st.caption("Aprueba al menos un activo en **Curaduría** (o incluye los pendientes).")
            if st.button("💾 Guardar paquete", type="primary", disabled=n_pkg == 0, width="stretch"):
                with st.spinner("Guardando…"):
                    st.session_state.guardado = pl.guardar_paquete(destino, paquete, res)
                st.session_state.listado = None
                st.rerun()

            g = st.session_state.guardado
            if g:
                (st.success if g["ok"] else st.error)(
                    "Paquete guardado con éxito" if g["ok"] else "Algunos objetos no se pudieron guardar")
                st.dataframe(pd.DataFrame(g["objetos"]), hide_index=True, width="stretch")

            st.markdown("##### Historial de paquetes")
            if st.button("🔄 Ver objetos guardados", width="stretch"):
                try:
                    st.session_state.listado = destino.listar()
                except Exception as e:  # noqa: BLE001
                    st.error(f"No se pudo listar: {e}")
            if st.session_state.listado is not None:
                if st.session_state.listado:
                    st.dataframe(pd.DataFrame(st.session_state.listado), hide_index=True, width="stretch")
                else:
                    st.caption("Aún no hay paquetes guardados.")


# ============================================================ panel de control
with tab_cfg:
    cfg = st.session_state.config
    v = st.session_state.cfg_ver
    st.markdown("#### ⚙️ Panel de control")
    st.caption("La inteligencia vive en el workflow de n8n: análisis, ruteo, generación y guardado en OCI. "
               "Aquí se configura cómo la interfaz se conecta con él, qué le pide y cómo el equipo atiende los tickets.")
    if st.session_state.msg_panel:
        nivel, texto = st.session_state.msg_panel
        getattr(st, nivel)(texto)
        st.session_state.msg_panel = None

    with st.form("form_config"):
        st.markdown("##### 🔌 Conexión con n8n")
        st.radio("Motor de procesamiento", list(MOTORES), index=list(MOTORES).index(cfg["motor"]),
                 format_func=MOTORES.get, horizontal=True, key=f"cfg_motor_{v}")
        n1, n2 = st.columns([4, 1])
        n1.text_input("URL del webhook", cfg["n8n_url"], key=f"cfg_n8n_url_{v}",
                      placeholder="https://tu-n8n/webhook/communitylab/actividades")
        n2.number_input("Tiempo de espera (s)", 10, 600, int(cfg["n8n_timeout"]), key=f"cfg_n8n_timeout_{v}")
        st.caption("🔑 Autenticación del webhook: " + (
            f"cabecera `{CRED_N8N['header_name']}` configurada en secrets." if CRED_N8N["header_name"]
            else "ninguna. Si tu webhook la exige, agrégala en `.streamlit/secrets.toml` → `[n8n]`."))

        st.markdown("##### 📨 Qué se le pide a n8n")
        st.caption("Viaja en `opciones` del request. El workflow decide con ellas qué ramas ejecutar.")
        o1, o2, o3 = st.columns(3)
        o1.checkbox("Generar posts de LinkedIn y X", cfg["generar_linkedin"], key=f"cfg_generar_linkedin_{v}")
        o2.checkbox("Generar destaque de newsletter", cfg["generar_newsletter"], key=f"cfg_generar_newsletter_{v}")
        o3.checkbox("Generar Tips / FAQ", cfg["generar_faq"], key=f"cfg_generar_faq_{v}")
        o4, o5 = st.columns(2)
        o4.selectbox("Idioma", list(IDIOMAS), index=list(IDIOMAS).index(cfg["idioma"]), format_func=IDIOMAS.get,
                     key=f"cfg_idioma_{v}")
        o5.selectbox("Tono", TONOS, index=TONOS.index(cfg["tono"]), key=f"cfg_tono_{v}")

        st.markdown("##### 🎫 Atención de tickets")
        t1, t2 = st.columns([2, 3])
        t1.text_area("Equipo de soporte (uno por línea)", "\n".join(cfg["equipo"]), height=130, key=f"cfg_equipo_{v}")
        with t2:
            s1, s2, s3 = st.columns(3)
            s1.number_input("SLA alta (h)", 1, 720, int(cfg["sla"]["Alta"]), key=f"cfg_sla_alta_{v}")
            s2.number_input("SLA media (h)", 1, 720, int(cfg["sla"]["Media"]), key=f"cfg_sla_media_{v}")
            s3.number_input("SLA baja (h)", 1, 720, int(cfg["sla"]["Baja"]), key=f"cfg_sla_baja_{v}")
            st.checkbox("Crear tickets para alertas de apoyo", cfg["tickets_alertas"], key=f"cfg_tk_alertas_{v}")
            st.checkbox("Crear tickets para dudas que el bot no puede responder", cfg["tickets_derivadas"],
                        key=f"cfg_tk_derivadas_{v}")
            st.checkbox("Crear tickets para dudas que superan el máximo por ruta", cfg["tickets_excedentes"],
                        key=f"cfg_tk_excedentes_{v}")
        st.number_input("Límite de caracteres para X en Curaduría", 100, 4000, int(cfg["limite_x"]),
                        key=f"cfg_limite_x_{v}")

        with st.expander("🧪 Reglas del motor de demostración (solo cuando no se usa n8n)"):
            st.caption("Con n8n, estas reglas viven en el workflow y aquí no tienen efecto.")
            r1, r2, r3 = st.columns(3)
            r1.slider("Sentimiento mínimo para caso de éxito", 0.0, 1.0, float(cfg["umbral_exito"]), 0.05,
                      key=f"cfg_umbral_exito_{v}")
            r2.slider("Sentimiento máximo para alerta de apoyo", -1.0, 0.0, float(cfg["umbral_alerta"]), 0.05,
                      key=f"cfg_umbral_alerta_{v}")
            r3.number_input("Máx. mensajes a transformar por ruta", 1, 20, int(cfg["max_por_ruta"]),
                            key=f"cfg_max_por_ruta_{v}")
            st.text_input("Palabras que disparan una alerta (separadas por coma)", ", ".join(cfg["palabras_alerta"]),
                          key=f"cfg_palabras_alerta_{v}")
            st.text_area("Voz de marca", cfg["voz"], height=100, key=f"cfg_voz_{v}")
            st.text_input("Hashtags fijos", " ".join(cfg["hashtags_base"]), key=f"cfg_hashtags_base_{v}")

        st.form_submit_button("💾 Guardar configuración", type="primary", on_click=guardar_config)

    a1, a2, a3, a4 = st.columns(4)
    a1.button("📡 Probar conexión con n8n", on_click=probar_n8n, disabled=not cfg["n8n_url"], width="stretch",
              help="Hace una petición GET a la URL; no crea ningún lote.")
    a2.button("🔁 Reprocesar el lote actual", on_click=reprocesar, disabled=not st.session_state.ultimo_payload,
              width="stretch", help="Vuelve a enviar el último lote con la configuración guardada. "
                                    "Se pierden las aprobaciones y los tickets de esa corrida.")
    a3.button("↺ Valores por defecto", on_click=restablecer_config, width="stretch")
    a4.download_button("⬇️ Exportar configuración", json.dumps(cfg, ensure_ascii=False, indent=2),
                       "communitylab-config.json", "application/json", width="stretch")
    with st.expander("⬆️ Importar configuración"):
        archivo_cfg = st.file_uploader("Archivo JSON exportado desde este panel", type=["json"], key=f"cfg_file_{v}")
        st.button("Importar", on_click=importar_config, args=(archivo_cfg,))

    st.markdown("##### 🩺 Estado del sistema")
    guardados = almacen_activo().listar()
    motor_res = (res or {}).get("motor", {})
    oci = (res or {}).get("almacenamiento_oci") or {}
    estado = pd.DataFrame([
        {"Componente": "Motor", "Estado": (f"🟢 n8n · {cfg['n8n_url']}" if cfg["motor"] == "n8n"
                                           else "🟡 Demostración local (heurísticas y plantillas)")},
        {"Componente": "Último procesamiento", "Estado": res["generado_en"].replace("T", " ") if res else "—"},
        {"Componente": "Lote en n8n (id / estado)",
         "Estado": f"{motor_res.get('id_lote', '—')} / {motor_res.get('estado_lote', '—')}" if motor_res.get("modo") == "n8n" else "—"},
        {"Componente": "Paquete en OCI (por n8n)",
         "Estado": f"{oci.get('status', '—')} · {oci.get('bucket', '')}/{oci.get('ruta_objeto', '')}" if oci else "—"},
        {"Componente": "Interacciones del último lote",
         "Estado": str(res["resumen"]["total_interacciones_procesadas"]) if res else "—"},
        {"Componente": "Activos generados / aprobados",
         "Estado": f"{len(activos)} / {sum(a['estado'] == 'aprobado' for a in activos)}" if res else "—"},
        {"Componente": "Tickets abiertos / total",
         "Estado": f"{sum(t['estado'] != 'Resuelto' for t in tickets)} / {len(tickets)}" if res else "—"},
        {"Componente": "Archivos guardados localmente", "Estado": f"{len(guardados)} en salida_local/"},
    ])
    st.dataframe(estado, hide_index=True, width="stretch")
    st.button("🧹 Limpiar sesión", on_click=limpiar_sesion,
              help="Borra el lote, los activos y los tickets de esta sesión. Conserva la configuración.")
