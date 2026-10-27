"""
Tests de escritura contra un Sheet falso: verifican que se escribe en la
columna correcta por NOMBRE, que las personas se buscan por legajo y que
una hoja con columnas faltantes da error claro en vez de correr datos.
"""
import pytest

from repositories import sheets_repo as repo
from tests.fake_sheet import workbook_base, HEADERS_HORARIOS, FakeWorksheet


@pytest.fixture
def wb(monkeypatch):
    wb = workbook_base()
    monkeypatch.setattr(repo, "get_workbook", lambda gc: wb)
    return wb


def test_normalizar_motivo_respeta_motivos_oficiales():
    from config import MOTIVOS_LISTA
    for m in MOTIVOS_LISTA:
        assert repo.normalizar_motivo(m) == m
        assert repo.normalizar_motivo(f"  {m.upper()} ") == m
    assert repo.normalizar_motivo("bco") == "Banco / Cajero"
    assert repo.normalizar_motivo("IPV") == "Trámite personal"
    assert repo.normalizar_motivo("turno con hijo especial") == "Turno Con Hijo Especial"
    assert repo.normalizar_motivo("") == "Otro"


def test_ordenar_por_encabezado_respeta_orden_del_sheet():
    valores, desc = repo.ordenar_por_encabezado({"b": 2, "a": 1}, ["a", "x", "b"])
    assert valores == [1, "", 2] and desc == []


def test_ordenar_por_encabezado_falta_obligatoria():
    with pytest.raises(ValueError, match="excluidos_legajos"):
        repo.ordenar_por_encabezado({"a": 1, "excluidos_legajos": "1"}, ["a"])


def test_ordenar_por_encabezado_descarta_opcional():
    valores, desc = repo.ordenar_por_encabezado({"a": 1, "es_lider": "SI"}, ["a"], opcionales=("es_lider",))
    assert valores == [1] and desc == ["es_lider"]


# ── Bug 1: marcar inactivo pisaba la planta ──────────────────
def test_marcar_inactivo_escribe_activo_y_no_toca_planta(wb):
    assert repo.marcar_activo(None, "2001", "NO")
    fila = wb.worksheet("padron").as_dicts()[0]
    assert fila["activo"] == "NO"
    assert fila["planta"] == "Fábrica"


def test_marcar_activo_busca_solo_en_columna_legajo(wb):
    # "2001" aparece como legajo de Ana; ningún otro campo debe coincidir
    assert not repo.marcar_activo(None, "9999", "NO")
    assert all(f["activo"] == "SI" for f in wb.worksheet("padron").as_dicts())


def test_eliminar_por_legajo(wb):
    assert repo.eliminar_empleado_padron(None, "2002")
    legajos = [f["legajo"] for f in wb.worksheet("padron").as_dicts()]
    assert legajos == ["2001", "3001"]


def test_agregar_empleado_sin_columna_es_lider_avisa(wb):
    desc = repo.agregar_empleado(None, "2003", "nueva, persona", "CALIDAD", "Fábrica", "EXEMPT", "SI")
    assert desc == ["es_lider"]
    ultima = wb.worksheet("padron").as_dicts()[-1]
    assert ultima["nombre"] == "NUEVA, PERSONA"
    assert ultima["planta"] == "Fábrica" and ultima["activo"] == "SI"


# ── Corrección de permisos por nombre de columna ─────────────
def test_corregir_horas_manual(wb):
    assert repo.corregir_permiso(None, "P1", "Corregir horas manualmente", "Horario reducido", "RRHH", nuevas_horas=1.0)
    f = wb.worksheet("permisos").as_dicts()[0]
    assert f["horas_redondeadas"] == "1.0"
    assert f["compensa"] == "SI"
    assert "5h → 1.0h" in f["registrado_por"]


def test_anular_no_borra(wb):
    assert repo.corregir_permiso(None, "P1", "Anular registro", "Duplicado", "RRHH")
    f = wb.worksheet("permisos").as_dicts()[0]
    assert f["compensa"] == "ANULADO" and f["horas_redondeadas"] == "0"


def test_corregir_id_inexistente(wb):
    assert not repo.corregir_permiso(None, "NOEXISTE", "Anular registro", "x", "y")


def test_guardar_permiso_en_orden_del_sheet(wb):
    fila = {
        "id": "P2", "fecha": "2026-10-13", "legajo": "2002", "nombre": "GOMEZ, LUIS",
        "hora_salida": "08:00", "hora_entrada": "09:00", "sin_retorno": "NO",
        "motivo": "Banco / Cajero", "compensa": "SI", "minutos_reales": 60,
        "horas_redondeadas": 1.0, "registrado_por": "G", "planta": "Fábrica",
        "timestamp": "2026-10-13 09:00:00",
    }
    repo.guardar_permiso(None, fila)
    assert wb.worksheet("permisos").as_dicts()[-1] == fila


# ── Horarios especiales con la hoja como está hoy ────────────
def _excepcion(excluidos=""):
    return {
        "id": "H1", "planta": "Fábrica", "desde": "2026-09-01", "hasta": "2026-12-31",
        "hora_fin": "11:00", "descripcion": "Reducción horaria", "activo": "SI",
        "excluidos_legajos": excluidos, "creado_por": "RRHH", "timestamp": "2026-10-13 08:00:00",
    }


def test_horario_sin_excluidos_funciona_con_hoja_vieja(wb):
    repo.guardar_excepcion_horario(None, _excepcion())
    f = wb.worksheet("config_horarios").as_dicts()[0]
    assert f["creado_por"] == "RRHH" and f["timestamp"] == "2026-10-13 08:00:00"


def test_horario_con_excluidos_y_hoja_vieja_da_error_claro(wb):
    with pytest.raises(ValueError, match="excluidos_legajos"):
        repo.guardar_excepcion_horario(None, _excepcion("2002"))
    assert wb.worksheet("config_horarios").as_dicts() == []


def test_horario_con_excluidos_y_hoja_nueva(wb):
    wb.hojas["config_horarios"] = FakeWorksheet(HEADERS_HORARIOS)
    repo.guardar_excepcion_horario(None, _excepcion("2002"))
    assert repo.editar_excluidos_horario(None, "H1", ["2002", "2001"])
    assert wb.worksheet("config_horarios").as_dicts()[0]["excluidos_legajos"] == "2002,2001"
    assert repo.desactivar_excepcion_horario(None, "H1")
    assert wb.worksheet("config_horarios").as_dicts()[0]["activo"] == "NO"


def test_config_app_crea_y_actualiza(wb):
    repo.actualizar_config_app(None, "password_rrhh", "h1", "Fede")
    repo.actualizar_config_app(None, "password_rrhh", "h2", "Fede")
    filas = wb.worksheet("config_app").as_dicts()
    assert len(filas) == 1 and filas[0]["valor"] == "h2"


# ── Horarios por días / por persona y edición desde el panel ─
from tests.fake_sheet import HEADERS_HORARIOS_COMPLETA  # noqa: E402


def test_horario_con_dias_en_hoja_sin_columna_da_error_claro(wb):
    wb.hojas["config_horarios"] = FakeWorksheet(HEADERS_HORARIOS)
    with pytest.raises(ValueError, match="dias_semana"):
        repo.guardar_excepcion_horario(None, {**_excepcion(), "dias_semana": "LU,MA"})
    assert wb.worksheet("config_horarios").as_dicts() == []


def test_horario_completo_se_lee_con_columnas_nuevas(wb):
    wb.hojas["config_horarios"] = FakeWorksheet(HEADERS_HORARIOS_COMPLETA)
    repo.guardar_excepcion_horario(None, {**_excepcion(), "dias_semana": "LU,MA", "solo_legajos": "3001"})
    df = repo.leer_config_horarios(None)
    assert df.iloc[0]["dias_semana"] == "LU,MA" and df.iloc[0]["solo_legajos"] == "3001"
    assert df.iloc[0]["creado_por"] == "RRHH"


def test_hoja_vieja_lee_columnas_nuevas_vacias(wb):
    repo.guardar_excepcion_horario(None, _excepcion())  # hoja sin columnas opcionales
    df = repo.leer_config_horarios(None)
    assert df.iloc[0]["dias_semana"] == "" and df.iloc[0]["solo_legajos"] == ""
    assert df.iloc[0]["excluidos_legajos"] == ""


def test_editar_horario_por_nombre_de_columna_y_audita(wb):
    wb.hojas["config_horarios"] = FakeWorksheet(HEADERS_HORARIOS_COMPLETA)
    repo.guardar_excepcion_horario(None, _excepcion())
    assert repo.editar_excepcion_horario(None, "H1", {
        "hasta": "2027-01-31", "hora_fin": "13:00", "dias_semana": "LU,MA", "solo_legajos": "3001",
    }, "Ailen")
    f = wb.worksheet("config_horarios").as_dicts()[0]
    assert f["hasta"] == "2027-01-31" and f["hora_fin"] == "13:00"
    assert f["dias_semana"] == "LU,MA" and f["solo_legajos"] == "3001"
    assert f["planta"] == "Fábrica" and f["activo"] == "SI"
    assert f["creado_por"].startswith("RRHH | editado por Ailen")


def test_editar_horario_columna_faltante_no_escribe_nada(wb):
    wb.hojas["config_horarios"] = FakeWorksheet(HEADERS_HORARIOS)
    repo.guardar_excepcion_horario(None, _excepcion())
    with pytest.raises(ValueError, match="solo_legajos"):
        repo.editar_excepcion_horario(None, "H1", {"hora_fin": "13:00", "solo_legajos": "3001"}, "Ailen")
    assert wb.worksheet("config_horarios").as_dicts()[0]["hora_fin"] == "11:00"
    # Vacío en una columna que no existe: se ignora, el resto se guarda
    assert repo.editar_excepcion_horario(None, "H1", {"hora_fin": "13:00", "solo_legajos": ""}, "Ailen")
    assert wb.worksheet("config_horarios").as_dicts()[0]["hora_fin"] == "13:00"


def test_editar_horario_campo_no_editable(wb):
    with pytest.raises(ValueError, match="planta"):
        repo.editar_excepcion_horario(None, "H1", {"planta": "Todas"}, "Ailen")
