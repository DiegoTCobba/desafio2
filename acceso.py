"""Pantalla de ingreso con contraseña para CommunityLab.

La contraseña se lee, en este orden, de:
1. `.streamlit/secrets.toml` → [auth] password_sha256 (recomendado) o password.
2. Variables de entorno COMMUNITYLAB_PASSWORD_SHA256 o COMMUNITYLAB_PASSWORD.
3. Si no hay ninguna, se usa la contraseña de demostración y la pantalla lo avisa.

Nunca se guarda la contraseña en la sesión: solo se compara su hash en tiempo constante.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import time

import streamlit as st

CONTRASENA_DEMO = "communitylab"
MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 30
MINUTOS_SESION_DEFAULT = 60


def _sha256(texto: str) -> str:
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def _seccion_auth() -> dict:
    try:
        return dict(st.secrets.get("auth", {}))
    except Exception:  # noqa: BLE001  (no existe secrets.toml)
        return {}


def configuracion() -> dict:
    """Devuelve el hash esperado, si es la contraseña de demostración y los minutos de sesión."""
    auth = _seccion_auth()
    hash_cfg = auth.get("password_sha256") or os.getenv("COMMUNITYLAB_PASSWORD_SHA256")
    plano = auth.get("password") or os.getenv("COMMUNITYLAB_PASSWORD")
    minutos = int(auth.get("minutos_sesion") or os.getenv("COMMUNITYLAB_MINUTOS_SESION") or MINUTOS_SESION_DEFAULT)
    if hash_cfg:
        return {"hash": str(hash_cfg).strip().lower(), "demo": False, "minutos": minutos}
    if plano:
        return {"hash": _sha256(str(plano)), "demo": False, "minutos": minutos}
    return {"hash": _sha256(CONTRASENA_DEMO), "demo": True, "minutos": minutos}


def contrasena_valida(intento: str, cfg: dict | None = None) -> bool:
    cfg = cfg or configuracion()
    return hmac.compare_digest(_sha256(intento), cfg["hash"])


def _bloqueado_hasta() -> float:
    return st.session_state.get("acceso_bloqueado_hasta", 0.0)


def _intentar_ingreso():
    if time.time() < _bloqueado_hasta():
        return
    intento = st.session_state.get("login_password", "")
    st.session_state["login_password"] = ""  # no dejar la contraseña en el campo
    if contrasena_valida(intento):
        st.session_state["autenticado"] = True
        st.session_state["acceso_intentos"] = 0
        st.session_state["acceso_ultima_actividad"] = time.time()
        st.session_state.pop("acceso_error", None)
        return
    intentos = st.session_state.get("acceso_intentos", 0) + 1
    st.session_state["acceso_intentos"] = intentos
    if intentos >= MAX_INTENTOS:
        st.session_state["acceso_bloqueado_hasta"] = time.time() + BLOQUEO_SEGUNDOS
        st.session_state["acceso_intentos"] = 0
        st.session_state["acceso_error"] = f"Demasiados intentos. Espera {BLOQUEO_SEGUNDOS} segundos."
    else:
        st.session_state["acceso_error"] = f"Contraseña incorrecta. Te quedan {MAX_INTENTOS - intentos} intento(s)."


def cerrar_sesion(motivo: str | None = None):
    for k in ("autenticado", "acceso_ultima_actividad"):
        st.session_state.pop(k, None)
    if motivo:
        st.session_state["acceso_error"] = motivo


def _sesion_expirada(cfg: dict) -> bool:
    ultima = st.session_state.get("acceso_ultima_actividad", time.time())
    return time.time() - ultima > cfg["minutos"] * 60


def _pantalla_ingreso(cfg: dict):
    _, centro, _ = st.columns([1, 1.3, 1])
    with centro:
        st.markdown("""<div class="hero" style="text-align:center"><h1>🚀 CommunityLab</h1>
<p>Ingresa la contraseña del equipo para continuar.</p></div>""", unsafe_allow_html=True)
        restante = int(_bloqueado_hasta() - time.time())
        with st.form("form_ingreso", clear_on_submit=False):
            st.text_input("Contraseña", type="password", key="login_password", placeholder="••••••••",
                          disabled=restante > 0)
            st.form_submit_button("🔓 Ingresar", type="primary", width="stretch", on_click=_intentar_ingreso,
                                  disabled=restante > 0)
        if restante > 0:
            st.error(f"Acceso bloqueado por demasiados intentos. Vuelve a intentarlo en {restante} s.")
        elif st.session_state.get("acceso_error"):
            st.error(st.session_state["acceso_error"])
        if cfg["demo"]:
            st.info(f"**Modo demostración:** no hay una contraseña configurada, así que se usa "
                    f"`{CONTRASENA_DEMO}`. Define la tuya en `.streamlit/secrets.toml` "
                    f"(ver `secrets.toml.example`) y este aviso desaparecerá.")
        st.caption("🌗 Tema claro u oscuro: menú ⋮ → Settings.")


def requerir_ingreso() -> dict:
    """Detiene la app hasta que la contraseña sea correcta. Devuelve la configuración de acceso."""
    cfg = configuracion()
    if st.session_state.get("autenticado"):
        if _sesion_expirada(cfg):
            cerrar_sesion(f"La sesión se cerró tras {cfg['minutos']} minutos sin actividad.")
        else:
            st.session_state["acceso_ultima_actividad"] = time.time()
            return cfg
    _pantalla_ingreso(cfg)
    st.stop()
