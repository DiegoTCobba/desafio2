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


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file(str(RAIZ / "app.py"), default_timeout=60).run()
    assert not at.exception
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

    app.slider(key="cfg_umbral_exito_0").set_value(1.0).run()
    app.number_input(key="cfg_max_por_ruta_0").set_value(5).run()
    app.text_area(key="cfg_equipo_0").input("Ana\nLuis").run()
    boton(app, "Guardar configuración").click().run()
    cfg = app.session_state.config
    assert cfg["umbral_exito"] == 1.0 and cfg["max_por_ruta"] == 5 and cfg["equipo"] == ["Ana", "Luis"]

    boton(app, "Reprocesar el lote actual").click().run()
    assert not app.exception
    exitos = [a for a in app.session_state.resultado["analisis"] if a["ruta"] == "caso_exito"]
    assert len(exitos) <= exitos_antes


def test_panel_restablece_valores(app):
    app.slider(key="cfg_umbral_exito_0").set_value(0.9).run()
    boton(app, "Guardar configuración").click().run()
    assert app.session_state.config["umbral_exito"] == 0.9
    boton(app, "Restablecer valores por defecto").click().run()
    assert app.session_state.config["umbral_exito"] == 0.4


def test_panel_rechaza_equipo_vacio(app):
    app.text_area(key="cfg_equipo_0").input("   ").run()
    boton(app, "Guardar configuración").click().run()
    assert app.session_state.config["equipo"]


def test_palabras_de_alerta_configurables():
    datos = {"interacciones": [{"autor": "X", "canal": "#g", "tipo": "feedback", "texto": "El curso esta bien pero me aburro mucho"}]}
    base = pl.MotorCommunityLab().procesar(datos)
    assert base["analisis"][0]["ruta"] != "alerta_apoyo"
    con = pl.MotorCommunityLab(palabras_alerta=["me aburro"]).procesar(datos)
    assert con["analisis"][0]["ruta"] == "alerta_apoyo"
