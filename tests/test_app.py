"""Pruebas de la interfaz: el flujo completo corre sin API key ni nube."""
import json
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
import motor_demo as pl  # noqa: E402


def boton(at, texto):
    return next(b for b in at.button if texto in b.label)


CLAVE = "clave-de-prueba"


def nueva_app(clave=CLAVE):
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)
    if clave is not None:
        at.secrets["auth"] = {"password": clave}
    return at.run()


def ingresar(at, clave=CLAVE):
    at.text_input(key="login_password").input(clave)
    boton(at, "Ingresar").click().run()
    return at


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COMMUNITYLAB_PASSWORD", raising=False)
    monkeypatch.delenv("COMMUNITYLAB_PASSWORD_SHA256", raising=False)
    at = ingresar(nueva_app())
    assert not at.exception and at.session_state.autenticado
    return at


def test_flujo_completo(app):
    boton(app, "Cargar lote de ejemplo").click().run()
    assert app.session_state.df is not None and len(app.session_state.df) == 9

    boton(app, "Procesar lote").click().run()
    assert not app.exception
    activos = app.session_state.activos
    assert len(activos) == 14
    assert {m.label for m in app.metric} >= {"Interacciones", "Alertas de apoyo"}

    boton(app, "Aprobar pendientes").click().run()
    assert all(a["estado"] == "aprobado" for a in app.session_state.activos)

    post_x = next(a for a in app.session_state.activos if a["tipo"] == "post_x")
    app.text_area(key=f"txt_{post_x['id']}").input("Texto editado #ONE").run()
    assert next(a for a in app.session_state.activos if a["id"] == post_x["id"])["contenido"] == "Texto editado #ONE"

    boton(app, "Guardar paquete").click().run()
    assert not app.exception
    g = app.session_state.guardado
    assert g["ok"] and len(g["objetos"]) == 3


def test_procesar_deshabilitado_sin_datos(app):
    assert boton(app, "Procesar lote").disabled


def test_rutas_del_lote_de_ejemplo():
    datos = json.loads((RAIZ / "data" / "interacciones_semana04.json").read_text(encoding="utf-8"))
    r = pl.MotorCommunityLab().procesar(datos)
    rutas = {a["autor"]: a["ruta"] for a in r["analisis"]}
    assert rutas["Mariana Souza"] == "caso_exito"
    assert rutas["Lucas Albuquerque"] == "faq"
    assert rutas["Camila Torres"] == "alerta_apoyo"
    assert all(len(a["contenido"]) <= 280 for a in r["activos"] if a["tipo"] == "post_x")


def test_paquete_solo_aprobados():
    datos = json.loads((RAIZ / "data" / "interacciones_semana04.json").read_text(encoding="utf-8"))
    r = pl.MotorCommunityLab().procesar(datos)
    activos = [dict(a) for a in r["activos"]]
    activos[0]["estado"] = "aprobado"
    pq = pl.construir_paquete(r, activos)
    assert sum(len(v) for v in pq["activos_distribucion_generados"].values()) == 1


# ---------------------------------------------------------------- tickets
def procesar_ejemplo(at):
    boton(at, "Cargar lote de ejemplo").click().run()
    boton(at, "Procesar lote").click().run()
    assert not at.exception
    return at


def test_tickets_se_crean_para_lo_que_el_bot_no_resuelve(app):
    procesar_ejemplo(app)
    tickets = app.session_state.tickets
    tipos = {(t["autor"], t["tipo"]) for t in tickets}
    assert ("Camila Torres", "Apoyo al miembro") in tipos
    assert ("Lucas Albuquerque", "Duda técnica") in tipos
    assert tickets[0]["prioridad"] == "Alta"
    assert [t["id"] for t in tickets] == [f"TCK-{i:03d}" for i in range(1, len(tickets) + 1)]


def test_resolver_ticket_exige_respuesta_y_actualiza_el_faq(app):
    procesar_ejemplo(app)
    t = next(t for t in app.session_state.tickets if t["activo_id"])
    tid = t["id"]

    app.button(key=f"tk_res_{tid}").click().run()
    assert next(x for x in app.session_state.tickets if x["id"] == tid)["estado"] != "Resuelto"

    app.selectbox(key=f"tk_asig_{tid}").select("Mentoría técnica").run()
    app.text_area(key=f"tk_resp_{tid}").input("Usa un nodo router con un contador de reintentos.").run()
    app.button(key=f"tk_res_{tid}").click().run()
    assert not app.exception
    resuelto = next(x for x in app.session_state.tickets if x["id"] == tid)
    assert resuelto["estado"] == "Resuelto" and resuelto["asignado_a"] == "Mentoría técnica"
    faq = next(a for a in app.session_state.activos if a["id"] == resuelto["activo_id"])
    assert "contador de reintentos" in faq["contenido"]
    assert faq["meta"]["status"] == "listo_para_revision"


def test_ticket_manual(app):
    procesar_ejemplo(app)
    n = len(app.session_state.tickets)
    app.text_input(key="nt_autor").input("Ana Pérez").run()
    app.text_area(key="nt_mensaje").input("No puedo acceder al aula virtual.").run()
    boton(app, "Crear ticket").click().run()
    assert len(app.session_state.tickets) == n + 1
    assert app.session_state.tickets[-1]["motivo"] == "Creado manualmente"


def test_paquete_incluye_tickets(app):
    procesar_ejemplo(app)
    boton(app, "Aprobar pendientes").click().run()
    boton(app, "Guardar paquete").click().run()
    pq = app.session_state.guardado["paquete"]
    assert pq["tickets_soporte"]["total"] == len(app.session_state.tickets)


# ---------------------------------------------------------------- panel de control
def test_panel_cambia_reglas_y_reprocesa(app):
    procesar_ejemplo(app)
    exitos_antes = sum(a["ruta"] == "caso_exito" for a in app.session_state.resultado["analisis"])
    assert exitos_antes > 0

    # Un formulario envía todos sus campos juntos: se completan y luego se pulsa el botón, sin reruns intermedios.
    app.slider(key="cfg_umbral_exito_0").set_value(1.0)
    app.number_input(key="cfg_max_por_ruta_0").set_value(5)
    app.text_area(key="cfg_equipo_0").input("Ana\nLuis")
    boton(app, "Guardar configuración").click().run()
    cfg = app.session_state.config
    assert cfg["umbral_exito"] == 1.0 and cfg["max_por_ruta"] == 5 and cfg["equipo"] == ["Ana", "Luis"]

    boton(app, "Reprocesar el lote actual").click().run()
    assert not app.exception
    exitos = [a for a in app.session_state.resultado["analisis"] if a["ruta"] == "caso_exito"]
    assert len(exitos) <= exitos_antes


def test_panel_restablece_valores(app):
    app.slider(key="cfg_umbral_exito_0").set_value(0.9)
    boton(app, "Guardar configuración").click().run()
    assert app.session_state.config["umbral_exito"] == 0.9
    boton(app, "Valores por defecto").click().run()
    assert app.session_state.config["umbral_exito"] == 0.4


def test_panel_rechaza_equipo_vacio(app):
    app.text_area(key="cfg_equipo_0").input("   ")
    boton(app, "Guardar configuración").click().run()
    assert app.session_state.config["equipo"]


def test_palabras_de_alerta_configurables():
    datos = {"interacciones": [{"autor": "X", "canal": "#g", "tipo": "feedback", "texto": "El curso esta bien pero me aburro mucho"}]}
    base = pl.MotorCommunityLab().procesar(datos)
    assert base["analisis"][0]["ruta"] != "alerta_apoyo"
    con = pl.MotorCommunityLab(palabras_alerta=["me aburro"]).procesar(datos)
    assert con["analisis"][0]["ruta"] == "alerta_apoyo"


# ---------------------------------------------------------------- acceso
def test_sin_contrasena_no_se_muestra_la_app(monkeypatch):
    monkeypatch.delenv("COMMUNITYLAB_PASSWORD", raising=False)
    at = nueva_app()
    assert not at.exception
    assert len(at.tabs) == 0
    assert not any("Cargar lote" in b.label for b in at.button)


def test_contrasena_incorrecta_y_bloqueo(monkeypatch):
    import acceso
    monkeypatch.delenv("COMMUNITYLAB_PASSWORD", raising=False)
    at = nueva_app()
    ingresar(at, "otra")
    assert "autenticado" not in at.session_state
    assert any("incorrecta" in e.value for e in at.error)
    for _ in range(acceso.MAX_INTENTOS - 1):
        ingresar(at, "otra")
    assert any("bloqueado" in e.value.lower() for e in at.error)
    # Mientras dura el bloqueo no se puede escribir ni enviar, ni siquiera la contraseña correcta.
    assert at.text_input(key="login_password").disabled
    assert boton(at, "Ingresar").disabled
    assert "autenticado" not in at.session_state


def test_ingreso_correcto_y_cierre_de_sesion(app):
    assert len(app.tabs) == 6
    boton(app, "Cerrar sesión").click().run()
    assert len(app.tabs) == 0


def test_contrasena_por_hash(monkeypatch):
    import hashlib
    monkeypatch.delenv("COMMUNITYLAB_PASSWORD", raising=False)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60)
    at.secrets["auth"] = {"password_sha256": hashlib.sha256(b"secreta").hexdigest()}
    at.run()
    assert not any("no hay una contraseña configurada" in i.value for i in at.info)
    ingresar(at, "secreta")
    assert at.session_state.autenticado
    assert not any("contraseña de demostración" in c.value for c in at.caption)


def test_contrasena_demo_avisa(monkeypatch):
    import acceso
    monkeypatch.delenv("COMMUNITYLAB_PASSWORD", raising=False)
    monkeypatch.delenv("COMMUNITYLAB_PASSWORD_SHA256", raising=False)
    at = nueva_app(clave=None)
    assert any("no hay una contraseña configurada" in i.value for i in at.info)
    ingresar(at, acceso.CONTRASENA_DEMO)
    assert at.session_state.autenticado
    assert any("contraseña de demostración" in c.value for c in at.caption)


def test_limpiar_sesion_no_cierra_la_sesion(app):
    boton(app, "Cargar lote de ejemplo").click().run()
    boton(app, "Limpiar sesión").click().run()
    assert app.session_state.autenticado and app.session_state.df is None


# ---------------------------------------------------------------- bandeja de resueltos
def test_bandeja_de_resueltos(app):
    procesar_ejemplo(app)
    t = app.session_state.tickets[0]
    tid = t["id"]
    app.text_area(key=f"tk_resp_{tid}").input("Te escribimos por privado para acompañarte.").run()
    app.button(key=f"tk_res_{tid}").click().run()
    assert not any(b.key == f"tk_res_{tid}" for b in app.button)  # ya no está en Abiertos

    app.radio(key="bandeja_tickets").set_value("Resueltos").run()
    assert any("acompañarte" in s.value for s in app.success)
    assert any("dentro del SLA" in c.value for c in app.caption)

    app.button(key=f"tk_reab_{tid}").click().run()
    assert next(x for x in app.session_state.tickets if x["id"] == tid)["estado"] != "Resuelto"


# ---------------------------------------------------------------- n8n
import threading  # noqa: E402
from http.server import BaseHTTPRequestHandler, HTTPServer  # noqa: E402

RESPUESTA_N8N = {
    "status": "exito", "id_lote": 42, "estado_lote": "completado",
    "resumen_comunidad": {"total_interacciones_procesadas": 9, "sentimiento_predominante": "Altamente Positivo",
                          "temas_principales": ["Contratacion / Logros", "LangGraph / Nodos Condicionales"]},
    "activos_distribucion_generados": {
        "post_linkedin": {"titulo": "De la Comunidad al Mercado", "copy": "Nada nos da mas orgullo...",
                          "canal_recomendado": "LinkedIn Oficial", "potencial_engagement": "Alto"},
        "destaque_newsletter_semanal": {"seccion": "Logro de la Semana", "titular": "Estudiante consigue empleo",
                                        "resumen": "Mariana Souza obtuvo su primera oportunidad."},
        "sugerencia_contenido_faq": {"tema": "Tip Rapido: nodos de reintento en LangGraph",
                                     "origen": "Duda frecuente planteada por Lucas Albuquerque",
                                     "status": "derivado_a_mentoria"},
    },
    "almacenamiento_oci": {"bucket": "communitylab-activos-marketing",
                           "ruta_objeto": "activos/2026-semana-04/paquete-distribucion.json",
                           "status": "guardado_con_exito"},
}


@pytest.fixture
def n8n_falso():
    recibido = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(405)
            self.end_headers()

        def do_POST(self):
            cuerpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            recibido["payload"] = cuerpo
            if self.path.endswith("/falla"):
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'{"message":"Error in workflow"}')
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(RESPUESTA_N8N).encode())

    srv = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/webhook/communitylab/actividades", recibido
    srv.shutdown()


def conectar_n8n(at, url):
    at.radio(key="cfg_motor_0").set_value("n8n")
    at.text_input(key="cfg_n8n_url_0").input(url)
    boton(at, "Guardar configuración").click().run()
    assert at.session_state.config["motor"] == "n8n"
    return at


def test_procesar_con_n8n(app, n8n_falso):
    url, recibido = n8n_falso
    conectar_n8n(app, url)
    procesar_ejemplo(app)

    assert recibido["payload"]["opciones"]["generar_linkedin"] is True
    assert len(recibido["payload"]["interacciones"]) == 9
    res = app.session_state.resultado
    assert res["motor"]["modo"] == "n8n" and res["motor"]["id_lote"] == 42
    assert {a["tipo"] for a in app.session_state.activos} == {"post_linkedin", "newsletter", "faq"}
    ticket = app.session_state.tickets[0]
    assert ticket["autor"] == "Lucas Albuquerque" and ticket["activo_id"]
    assert any("solo el resumen" in i.value for i in app.info)  # sin análisis por interacción


def test_n8n_con_error_muestra_mensaje(app, n8n_falso):
    url, _ = n8n_falso
    conectar_n8n(app, url + "/falla")
    procesar_ejemplo_sin_assert = boton(app, "Cargar lote de ejemplo").click().run()
    boton(procesar_ejemplo_sin_assert, "Procesar lote").click().run()
    assert any("HTTP 500" in e.value for e in app.error)
    assert app.session_state.resultado is None


def test_probar_conexion_n8n(app, n8n_falso):
    url, recibido = n8n_falso
    conectar_n8n(app, url)
    boton(app, "Probar conexión").click().run()
    assert any("405" in s.value for s in app.success)
    assert "payload" not in recibido  # probar no crea lotes


def test_n8n_exige_url_valida(app):
    app.radio(key="cfg_motor_0").set_value("n8n")
    app.text_input(key="cfg_n8n_url_0").input("localhost:5678")
    boton(app, "Guardar configuración").click().run()
    assert app.session_state.config["motor"] == "demo"


def test_opciones_filtran_activos_en_demo(app):
    app.checkbox(key="cfg_generar_linkedin_0").uncheck()
    boton(app, "Guardar configuración").click().run()
    procesar_ejemplo(app)
    tipos = {a["tipo"] for a in app.session_state.activos}
    assert not tipos & {"post_linkedin", "post_x", "caso_exito"} and "faq" in tipos
