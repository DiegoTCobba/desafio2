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
