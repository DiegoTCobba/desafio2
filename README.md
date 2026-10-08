<div align="center">

# 🚀 CommunityLab · Frontend

**Interfaz en Streamlit para convertir las conversaciones de una comunidad tech en contenido listo para publicar.**

Carga un lote de mensajes, muestra la salud de la comunidad, permite al equipo aprobar los posts, casos de éxito y FAQs generados, y deriva a tickets lo que el bot no puede resolver solo. Funciona sola, sin API key ni nube, con acceso por contraseña y tema claro u oscuro.

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.50+-FF4B4B?logo=streamlit&logoColor=white)
![Altair](https://img.shields.io/badge/Altair-gráficos-1F77B4)
![Pandas](https://img.shields.io/badge/Pandas-datos-150458?logo=pandas&logoColor=white)

*Hackathon ONE G10 · Oracle Next Education + Alura · Reto 3*

<img src="docs/img/02-salud.png" alt="Tablero de salud de la comunidad" width="85%">

</div>

---

## Qué es este repositorio

Es la **capa de presentación** de CommunityLab, separada del motor de IA para que cualquiera pueda clonarla y probarla en un minuto.

| Repositorio | Contenido |
|---|---|
| **desafio2** (este) | Interfaz Streamlit + motor de demostración por heurísticas. Sin dependencias externas. |
| [**desafio**](https://github.com/DiegoTCobba/desafio) | Proyecto completo: análisis con Google Gemini vía LangChain y persistencia en OCI Object Storage. |

El motor de demostración (`motor_demo.py`) respeta el mismo contrato de datos que el motor real, así que la interfaz es idéntica en ambos.

## ✨ Funcionalidades

| Pestaña | Qué hace |
|---|---|
| 📥 **Ingesta** | Carga el lote de ejemplo, un JSON o CSV, o un JSON pegado. Tabla editable antes de procesar y progreso paso a paso. |
| 📊 **Salud de la comunidad** | Métricas, distribución de sentimiento, temas en tendencia, mapa sentimiento × relevancia, reparto por ruta, ranking explicado y alertas de miembros que necesitan apoyo. |
| ✍️ **Curaduría** | Cada activo se edita, aprueba, rechaza o restablece. Filtros por tipo y estado, contador de caracteres para X, vista previa y barra de avance. |
| 🎫 **Tickets** | Cola de las consultas que el bot no pudo resolver solo: miembros que necesitan apoyo, dudas sin respuesta confiable y dudas que superaron el máximo por ruta. Prioridad, SLA y vencimiento, responsable, respuesta, historial, escalar o reabrir, tickets manuales y exportación a CSV. |
| 📦 **Paquete** | Arma el paquete solo con lo aprobado (con el resumen de tickets), lo descarga en JSON o Markdown y lo guarda con la estructura de carpetas del bucket. |
| ⚙️ **Panel de control** | Ajusta las reglas de ruteo, las palabras que disparan alertas, la voz de marca, los hashtags, el equipo de soporte y los SLA. Reprocesa el lote con la nueva configuración, la exporta o importa en JSON y muestra el estado del sistema. |

### Del ticket al contenido

Cuando el equipo resuelve una duda técnica, la respuesta pasa automáticamente al borrador del FAQ, que vuelve a **Curaduría** marcado como *listo para revisión*. Así, la pregunta que el bot no supo responder termina convertida en contenido para la comunidad.

| Origen del ticket | Prioridad | SLA por defecto |
|---|---|---|
| Alerta de apoyo (frustración o riesgo de abandono) | 🔴 Alta | 4 h |
| Duda que el bot no puede responder, relevancia ≥ 60 | 🟠 Media | 24 h |
| Duda con menor relevancia o que superó el máximo por ruta | 🟢 Baja | 72 h |

## 🖥 Capturas

| Ingesta | Curaduría |
|---|---|
| <img src="docs/img/01-ingesta.png" alt="Ingesta"> | <img src="docs/img/04-curaduria.png" alt="Curaduría"> |
| **Tickets** | **Panel de control** |
| <img src="docs/img/05-tickets.png" alt="Tickets"> | <img src="docs/img/07-panel.png" alt="Panel de control"> |
| **Ranking y alertas** | **Paquete** |
| <img src="docs/img/03-ranking.png" alt="Ranking"> | <img src="docs/img/06-paquete.png" alt="Paquete"> |

## 🔐 Acceso con contraseña

La app no muestra nada hasta ingresar la contraseña del equipo.

| | |
|---|---|
| <img src="docs/img/08-ingreso.png" alt="Pantalla de ingreso"> | - Se compara el **hash SHA-256** en tiempo constante; la contraseña nunca queda en la sesión.<br>- **5 intentos** fallidos bloquean el ingreso por 30 segundos.<br>- La sesión se cierra tras **60 minutos** sin actividad (configurable).<br>- Botón **Cerrar sesión** en la barra lateral. |

**Configurar tu contraseña:** copia `.streamlit/secrets.toml.example` como `.streamlit/secrets.toml` (ya está en `.gitignore`) y pon el hash:

```bat
python -c "import hashlib; print(hashlib.sha256('mi-clave-segura'.encode()).hexdigest())"
```

```toml
[auth]
password_sha256 = "el-hash-que-generaste"
minutos_sesion = 60
```

También acepta las variables de entorno `COMMUNITYLAB_PASSWORD_SHA256` o `COMMUNITYLAB_PASSWORD`. Si no configuras ninguna, la app usa la contraseña de demostración **`communitylab`** y lo avisa en la pantalla de ingreso.

> Al desplegar en Streamlit Community Cloud, pega el bloque `[auth]` en **Settings → Secrets** de la app.

## 🌗 Modo oscuro

La app trae una paleta clara y otra oscura con los colores de la marca (`.streamlit/config.toml`). Por defecto sigue el tema del sistema; cada persona puede elegir **Claro / Oscuro** desde el menú **⋮ → Settings**, y Streamlit recuerda su elección.

<img src="docs/img/09-modo-oscuro.png" alt="CommunityLab en modo oscuro" width="85%">

## ⚡ Cómo ejecutarlo

```bat
git clone https://github.com/DiegoTCobba/desafio2.git
cd desafio2
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m streamlit run app.py
```

> En macOS / Linux: `source .venv/bin/activate` y luego `streamlit run app.py`.

Ingresa con tu contraseña (o `communitylab` si aún no configuraste una), pulsa **Cargar lote de ejemplo** → **Procesar lote** y recorre las pestañas.

### Formato de entrada

JSON con el formato del reto, o CSV con las columnas `autor, canal, tipo, texto`:

```json
{
  "origen_comunidad": "Discord_Grupo_ONE_G10",
  "periodo_referencia": "Semana_04",
  "interacciones": [
    {"autor": "Mariana Souza", "canal": "#logros-y-empleos", "tipo": "testimonio",
     "texto": "Comunidad, quede seleccionada para el puesto de Desarrolladora Junior de IA! ..."}
  ]
}
```

## 🧩 Decisiones de interfaz

- **El flujo sigue el trabajo real** de un community manager: cargar, entender la semana, revisar y guardar.
- **Humano en el circuito**: nada entra al paquete sin aprobación, salvo que se active la opción de incluir pendientes.
- **Cada decisión se explica**: el ranking muestra categoría, puntaje, ruta y justificación de cada mensaje.
- **Las alertas no generan contenido**: un mensaje con frustración se muestra al equipo, no se convierte en publicidad.
- **Nada se pierde en el camino**: lo que el bot no resuelve queda como ticket con responsable y vencimiento.
- **Configuración sin tocar código**: las reglas viven en el panel de control y se pueden versionar como JSON.
- **Estado estable**: las etiquetas de las pestañas son fijas, porque Streamlit reinicia la navegación si cambian.

## 🧪 Pruebas

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests -q
```

**18 pruebas** con **Streamlit AppTest**: el flujo completo (cargar, procesar, aprobar, editar y guardar), la creación de tickets, que resolver exija una respuesta y la envíe al FAQ, los tickets manuales, que el panel de control guarde, valide, restablezca y reprocese, y el acceso: nada visible sin contraseña, contraseña incorrecta, bloqueo por intentos, ingreso por hash, aviso de contraseña de demostración y cierre de sesión. Se ejecutan en cada push con GitHub Actions.

## 📁 Estructura

```text
app.py                  interfaz Streamlit (6 pestañas)
acceso.py               pantalla de ingreso con contraseña, bloqueo y expiración de sesión
motor_demo.py           motor de demostración: heurísticas, ruteo, plantillas, tickets y paquete
data/                   lote de ejemplo del reto (9 mensajes)
tests/test_app.py       18 pruebas de interfaz, motor y acceso
.streamlit/config.toml  temas claro y oscuro
.streamlit/secrets.toml.example  plantilla para la contraseña
docs/img/               capturas
```

## 👤 Autor

**Diego** · [@DiegoTCobba](https://github.com/DiegoTCobba)

---

<sub>Proyecto desarrollado para el Hackathon ONE G10 (Oracle Next Education + Alura). Licencia MIT.</sub>
