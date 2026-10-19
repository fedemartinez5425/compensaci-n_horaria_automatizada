"""
Prueba de punta a punta: corre app.py completo con streamlit AppTest,
contra el Sheet falso en memoria (nunca el real), y hace clics como un
usuario. Cubre los arreglos de la rama fix/auditoria.
"""
from datetime import time
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from repositories import sheets_repo as repo
from services.auth_service import hashear_password
from tests.fake_sheet import workbook_base, FakeWorksheet, HEADERS_HORARIOS

PW_GUARDIA, PW_RRHH = "guardia-test", "rrhh-test"
APP_PY = Path(__file__).resolve().parent.parent / "app.py"


@pytest.fixture
def wb(monkeypatch):
    wb = workbook_base()
    monkeypatch.setattr(repo, "conectar", lambda: None)
    monkeypatch.setattr(repo, "get_workbook", lambda gc: wb)
    st.cache_data.clear()
    yield wb
    st.cache_data.clear()


def _app(wb, secrets=True):
    at = AppTest.from_file(str(APP_PY), default_timeout=30)
    if secrets:
        at.secrets["PASSWORD_GUARDIA_INICIAL"] = PW_GUARDIA
        at.secrets["PASSWORD_RRHH_INICIAL"] = PW_RRHH
    return at.run()


def _login(at, clave=PW_GUARDIA):
    at.text_input[0].set_value(clave)
    at.button[0].click()
    return at.run()


def _ir(at, planta, pagina):
    at.sidebar.selectbox[0].select(planta)
    at.sidebar.radio[0].set_value(pagina)
    return at.run()


def _login_rrhh(at):
    at.text_input(key="pw_rrhh").set_value(PW_RRHH)
    at.button(key="btn_rrhh").click()
    return at.run()


def test_sin_passwords_configuradas_no_deja_entrar(wb):
    at = _app(wb, secrets=False)
    assert any("No hay contraseñas" in e.value for e in at.error)


def test_login_correcto_e_incorrecto(wb):
    at = _app(wb)
    at = _login(at, "1234")  # la vieja clave por defecto ya no existe
    assert any("incorrecta" in e.value for e in at.error)
    at = _login(at, PW_GUARDIA)
    assert not at.exception
    assert at.session_state["autenticado"]


def test_login_con_password_hasheada_en_config_app(wb):
    wb.worksheet("config_app").append_row(["password_guardia", hashear_password("nueva"), "Fede", ""])
    at = _login(_app(wb), "nueva")
    assert at.session_state["autenticado"]


def test_cerrar_sesion_tambien_cierra_rrhh(wb):
    at = _login(_app(wb))
    at = _ir(at, "Fábrica San Juan", "🟢 Panel RRHH")
    at = _login_rrhh(at)
    assert at.session_state["rrhh_autenticado"]
    at.sidebar.button[0].click()
    at = at.run()
    assert not at.session_state["autenticado"]
    assert not at.session_state["rrhh_autenticado"]


def test_guardia_en_total_empresa_no_permite_cargar(wb):
    at = _login(_app(wb))
    at = _ir(at, "🏢 Total Empresa", "🔵 Panel Guardia")
    assert not at.exception
    assert any("elegí la planta" in i.value for i in at.info)
    assert not any(b.label == "💾 GUARDAR REGISTRO" for b in at.button)


def test_guardia_sin_retorno_con_horario_reducido(wb):
    wb.hojas["config_horarios"] = FakeWorksheet(HEADERS_HORARIOS, [[
        "H1", "Fábrica", "2020-01-01", "2099-12-31", "11:00", "Reducción horaria",
        "SI", "", "RRHH", "",
    ]])
    at = _login(_app(wb))
    at = _ir(at, "Fábrica San Juan", "🔵 Panel Guardia")
    at.selectbox[0].select("GOMEZ, LUIS")
    at.selectbox(key="motivo_pre").select("Banco / Cajero")
    at.time_input(key="hora_sal_pre").set_value(time(10, 0))
    at.checkbox(key="sr_pre").check()
    at = at.run()
    next(t for t in at.text_input if t.label == "👮 Tu nombre *").set_value("Guardia Test")
    next(b for b in at.button if b.label == "💾 GUARDAR REGISTRO").click()
    at = at.run()
    assert not at.exception, at.exception
    nuevo = wb.worksheet("permisos").as_dicts()[-1]
    assert nuevo["nombre"] == "GOMEZ, LUIS"
    assert nuevo["hora_entrada"] == "S/R"
    assert nuevo["minutos_reales"] == 60.0     # 10:00 → 11:00, no hasta las 15:00
    assert nuevo["horas_redondeadas"] == 1.0
    assert nuevo["planta"] == "Fábrica"


def test_rrhh_inactivar_no_pisa_planta(wb):
    at = _login(_app(wb))
    at = _ir(at, "Fábrica San Juan", "🟢 Panel RRHH")
    at = _login_rrhh(at)
    at.selectbox(key="emp_gestion").select("PEREZ, ANA")
    at = at.run()
    at.button(key="btn_activo").click()
    at = at.run()
    assert not at.exception, at.exception
    ana = wb.worksheet("padron").as_dicts()[0]
    assert ana["activo"] == "NO" and ana["planta"] == "Fábrica"


def test_rrhh_baja_requiere_confirmacion(wb):
    at = _login(_app(wb))
    at = _ir(at, "Fábrica San Juan", "🟢 Panel RRHH")
    at = _login_rrhh(at)
    at.selectbox(key="emp_gestion").select("GOMEZ, LUIS")
    at = at.run()
    assert at.button(key="btn_baja").disabled
    at.checkbox(key="conf_baja_2002").check()
    at = at.run()
    at.button(key="btn_baja").click()
    at = at.run()
    assert "2002" not in [f["legajo"] for f in wb.worksheet("padron").as_dicts()]


def test_compensacion_desde_total_guarda_planta_de_la_persona(wb):
    at = _login(_app(wb))
    at = _ir(at, "🏢 Total Empresa", "🟢 Panel RRHH")
    at = _login_rrhh(at)
    form_sel = [s for s in at.selectbox if s.label == "Empleado/a" and s.key is None][0]
    form_sel.select("DIAZ, EVA")
    tus_nombres = [t for t in at.text_input if t.label == "Tu nombre *"]
    tus_nombres[0].set_value("RRHH Test")
    next(b for b in at.button if b.label == "✅ REGISTRAR COMPENSACIÓN").click()
    at = at.run()
    assert not at.exception, at.exception
    comp = wb.worksheet("compensaciones").as_dicts()
    assert comp and comp[-1]["planta"] == "Casa Central"


def test_cambiar_password_queda_hasheada(wb):
    at = _login(_app(wb))
    at = _ir(at, "Fábrica San Juan", "🟢 Panel RRHH")
    at = _login_rrhh(at)
    pw = [t for t in at.text_input if t.label in ("Nueva contraseña", "Repetí la nueva contraseña")]
    for t in pw:
        t.set_value("otra-clave")
    [t for t in at.text_input if t.label == "Tu nombre *"][-1].set_value("Fede")
    next(b for b in at.button if b.label == "💾 Actualizar contraseña").click()
    at = at.run()
    assert not at.exception, at.exception
    fila = wb.worksheet("config_app").as_dicts()[0]
    assert fila["clave"] == "password_guardia"
    assert fila["valor"].startswith("pbkdf2_sha256$") and "otra-clave" not in fila["valor"]


@pytest.mark.parametrize("pagina", ["🔵 Panel Guardia", "🟢 Panel RRHH", "📊 Análisis", "📖 Cómo se calcula"])
@pytest.mark.parametrize("planta", ["Fábrica San Juan", "Casa Central Bs. As.", "🏢 Total Empresa"])
def test_todas_las_pantallas_cargan_sin_error(wb, planta, pagina):
    at = _login(_app(wb))
    at = _ir(at, planta, pagina)
    if pagina != "🔵 Panel Guardia":
        at = _login_rrhh(at)
    assert not at.exception, at.exception
