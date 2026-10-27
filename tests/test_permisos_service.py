"""
Tests de las reglas de negocio protegidas en CLAUDE.md.
Si alguno falla después de un cambio, se rompió una regla acordada con RRHH.
"""
from datetime import date, time

import pandas as pd
import pytest

from config import HORA_FIN_TURNO, HORA_FIN_TURNO_BSAS
from services.permisos_service import (
    redondear_horas, minutos_entre, obtener_tope, excede_tope_por_permiso,
    horas_comprometidas_año, horas_fuera_tope_año, puede_compensar_por_politica,
    calcular_saldos, kpi_compensacion_acumulado, indicador_mensual,
    validar_permiso, obtener_hora_fin_turno, excepcion_horario_activa, generar_id,
    parse_dias_semana, hora_fin_normal,
)


# ── Redondeo ─────────────────────────────────────────────────
@pytest.mark.parametrize("minutos, esperado", [
    (None, 0), (0, 0), (29, 0), (29.9, 0), (30, 1), (60, 1), (89, 1),
    (90, 2), (149, 2), (150, 3), (209, 3), (270, 5), (300, 5),
])
def test_redondeo_regla_de_fabrica(minutos, esperado):
    assert redondear_horas(minutos) == esperado


def test_minutos_entre():
    assert minutos_entre(time(10, 0), time(11, 0)) == 60
    assert minutos_entre(time(10, 5), time(11, 0)) == 55


# ── Topes ────────────────────────────────────────────────────
def test_topes_por_planta():
    assert obtener_tope("NO") == 8
    assert obtener_tope("SI") == 16
    assert obtener_tope("NO", "Fábrica") == 8
    assert obtener_tope("SI", "Fábrica") == 16
    assert obtener_tope("NO", "Casa Central") == 10
    assert obtener_tope("SI", "Casa Central") == 10


def test_maximo_por_permiso_solo_bsas():
    assert excede_tope_por_permiso(5, "Casa Central")
    assert not excede_tope_por_permiso(4, "Casa Central")
    assert not excede_tope_por_permiso(8, "Fábrica")


def _permisos(filas):
    df = pd.DataFrame(filas, columns=["legajo", "nombre", "fecha", "motivo", "compensa", "horas_redondeadas"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


def test_consumido_año_excluye_fuera_de_tope_y_otros_años():
    p = _permisos([
        ("1", "A", "2026-03-01", "Banco / Cajero", "SI", 2),
        ("1", "A", "2026-04-01", "Renovación Carnet de Conducir", "SI", 3),
        ("1", "A", "2026-05-01", "Banco / Cajero", "NO", 4),
        ("1", "A", "2026-06-01", "Banco / Cajero", "ANULADO", 0),
        ("1", "A", "2025-12-01", "Banco / Cajero", "SI", 5),
        ("2", "B", "2026-03-01", "Banco / Cajero", "SI", 7),
    ])
    assert horas_comprometidas_año(p, "1", 2026) == 2
    assert horas_fuera_tope_año(p, "1", 2026) == 3
    assert horas_comprometidas_año(p, "1", 2025) == 5


def test_cupo_extra_solo_san_juan():
    p = _permisos([
        ("1", "A", "2026-04-01", "Renovación Carnet de Conducir", "SI", 3),
        ("2", "B", "2026-04-01", "Renovación Carnet de Conducir", "SI", 3),
    ])
    p["planta"] = ["Fábrica", "Casa Central"]
    assert horas_comprometidas_año(p, "1", 2026) == 0 and horas_fuera_tope_año(p, "1", 2026) == 3
    assert horas_comprometidas_año(p, "2", 2026) == 3 and horas_fuera_tope_año(p, "2", 2026) == 0


# ── Política de motivos ──────────────────────────────────────
def test_politica_motivos():
    assert puede_compensar_por_politica("Médico turno mañana", "Fábrica", False)
    assert not puede_compensar_por_politica("Médico propio", "Fábrica", False)
    assert puede_compensar_por_politica("Médico propio", "Fábrica", True)
    assert puede_compensar_por_politica("Médico propio", "Casa Central", False)
    assert puede_compensar_por_politica("Paro General", "Casa Central", False)
    assert not puede_compensar_por_politica("Paro General", "Fábrica", False)
    assert not puede_compensar_por_politica("ART", "Casa Central", False)
    assert puede_compensar_por_politica("ART", "Total", False)


# ── Saldos ───────────────────────────────────────────────────
def _comp(filas):
    df = pd.DataFrame(filas, columns=["legajo", "fecha_compensacion", "horas_compensadas"])
    df["fecha_compensacion"] = pd.to_datetime(df["fecha_compensacion"])
    return df


def test_saldo_acumulado_incluye_fuera_de_tope_y_oculta_no_positivos():
    p = _permisos([
        ("1", "A", "2026-02-01", "Banco / Cajero", "SI", 2),
        ("1", "A", "2026-05-01", "Promesa Bandera Primaria Hijo", "SI", 3),
        ("1", "A", "2026-05-02", "ART", "NO", 4),
        ("2", "B", "2026-02-01", "Banco / Cajero", "SI", 1),
    ])
    c = _comp([("1", "2026-06-01", 1), ("2", "2026-06-01", 2)])
    s = calcular_saldos(p, c)
    assert list(s["legajo"]) == ["1"]
    assert s.iloc[0]["debe"] == 5
    assert s.iloc[0]["saldo"] == 4


def test_saldo_hasta_fecha():
    p = _permisos([
        ("1", "A", "2026-02-01", "Banco / Cajero", "SI", 2),
        ("1", "A", "2026-07-01", "Banco / Cajero", "SI", 3),
    ])
    c = _comp([("1", "2026-08-01", 5)])
    s = calcular_saldos(p, c, hasta_fecha=date(2026, 3, 1))
    assert s.iloc[0]["saldo"] == 2


def test_kpi_y_mensual_con_tope_100():
    p = _permisos([("1", "A", "2026-02-01", "Banco / Cajero", "SI", 2)])
    c = _comp([("1", "2026-02-10", 5)])
    k = kpi_compensacion_acumulado(p, c)
    assert k["pct"] == 100 and k["hs_pendientes"] == 0
    m = indicador_mensual(p, c)
    assert m.iloc[0]["% Cumplimiento"] == 100


# ── Validaciones ─────────────────────────────────────────────
def test_validar_permiso():
    assert validar_permiso("X", "Guardia", False, time(9), time(10)) == []
    assert validar_permiso("", "", False, time(9), time(10))  # faltan datos
    assert validar_permiso("X", "G", False, time(10), time(9))  # entrada antes de salida
    assert validar_permiso("X", "G", True, time(15), time(15))  # S/R después del fin de turno
    assert validar_permiso("X", "G", True, time(11, 30), None, hora_fin_turno=time(11))


# ── Horarios especiales (Sin Retorno SJ) ─────────────────────
def _horarios(excluidos=""):
    return pd.DataFrame([{
        "id": "H1", "planta": "Fábrica",
        "desde": date(2026, 9, 1), "hasta": date(2026, 12, 31),
        "hora_fin": "11:00", "descripcion": "Reducción horaria", "activo": "SI",
        "excluidos_legajos": excluidos,
    }])


def test_horario_especial_aplica_en_rango_y_planta():
    h = _horarios()
    assert obtener_hora_fin_turno(h, "Fábrica", date(2026, 9, 17)) == time(11)
    assert obtener_hora_fin_turno(h, "Fábrica", date(2026, 8, 31)) == HORA_FIN_TURNO
    assert obtener_hora_fin_turno(h, "Casa Central", date(2026, 9, 17)) == HORA_FIN_TURNO_BSAS


def test_horario_especial_respeta_excluidos():
    h = _horarios(excluidos="100, 200")
    assert obtener_hora_fin_turno(h, "Fábrica", date(2026, 9, 17), legajo="100") == HORA_FIN_TURNO
    assert obtener_hora_fin_turno(h, "Fábrica", date(2026, 9, 17), legajo="300") == time(11)


def test_horario_especial_inactivo_o_mal_cargado_se_ignora():
    h = _horarios()
    h.loc[0, "activo"] = "NO"
    assert excepcion_horario_activa(h, "Fábrica", date(2026, 9, 17)) is None
    h = _horarios()
    h.loc[0, "hora_fin"] = "once"
    assert obtener_hora_fin_turno(h, "Fábrica", date(2026, 9, 17)) == HORA_FIN_TURNO


def test_sin_retorno_con_horario_reducido():
    # Caso real: salida 10:05 S/R con horario 6 a 11 → 55 min → 1h (no 5h).
    fin = obtener_hora_fin_turno(_horarios(), "Fábrica", date(2026, 9, 17))
    assert redondear_horas(minutos_entre(time(10, 5), fin)) == 1


# ── IDs ──────────────────────────────────────────────────────
def test_ids_no_se_repiten_en_el_mismo_segundo():
    ids = {generar_id("P") for _ in range(500)}
    assert len(ids) == 500
    assert all(i.startswith("P") for i in ids)


# ── Horarios por días y por persona (caso Bs. As. octubre 2026) ──
def test_horario_normal_por_planta():
    assert hora_fin_normal("Fábrica") == time(15)
    assert hora_fin_normal("Casa Central") == time(17)
    assert obtener_hora_fin_turno(None, "Casa Central", date(2026, 10, 27)) == time(17)


def test_parse_dias_semana():
    assert parse_dias_semana("") is None
    assert parse_dias_semana("LU,MA") == {0, 1}
    assert parse_dias_semana("lunes, Miércoles, sábado") == {0, 2, 5}
    assert parse_dias_semana("cualquiera") == set()


def _fila_h(id_, hora_fin, dias="", solo="", excluidos="", planta="Casa Central"):
    return {"id": id_, "planta": planta, "desde": date(2026, 10, 1), "hasta": date(2026, 12, 31),
            "hora_fin": hora_fin, "descripcion": id_, "activo": "SI",
            "excluidos_legajos": excluidos, "dias_semana": dias, "solo_legajos": solo}


def _horarios_bsas():
    # 7 a 13 para todos · 5 fijos con jornada completa 7 a 16 · rotativos 7 a 16 lunes y martes
    return pd.DataFrame([
        _fila_h("general", "13:00"),
        _fila_h("fijos", "16:00", solo="2455,2458,9010,9016,2411"),
        _fila_h("rotativos", "16:00", dias="LU,MA", solo="2459,9260,9236,9261"),
    ])


LUNES, MIERCOLES = date(2026, 10, 26), date(2026, 10, 28)


def test_bsas_general_fijos_y_rotativos():
    h = _horarios_bsas()
    assert obtener_hora_fin_turno(h, "Casa Central", LUNES, legajo="9999") == time(13)
    assert obtener_hora_fin_turno(h, "Casa Central", LUNES, legajo="2411") == time(16)
    assert obtener_hora_fin_turno(h, "Casa Central", MIERCOLES, legajo="2411") == time(16)
    assert obtener_hora_fin_turno(h, "Casa Central", LUNES, legajo="9260") == time(16)
    assert obtener_hora_fin_turno(h, "Casa Central", MIERCOLES, legajo="9260") == time(13)
    # Antes del 1/10 rige el horario normal de Bs. As.
    assert obtener_hora_fin_turno(h, "Casa Central", date(2026, 9, 30), legajo="9260") == time(17)


def test_horario_solo_legajos_no_aplica_sin_legajo_ni_en_otra_planta():
    h = _horarios_bsas()
    assert excepcion_horario_activa(h, "Casa Central", LUNES)["id"] == "general"
    assert obtener_hora_fin_turno(h, "Fábrica", LUNES, legajo="2411") == HORA_FIN_TURNO


def test_excluido_de_la_general_va_al_horario_normal():
    h = pd.DataFrame([_fila_h("general", "13:00", excluidos="2455")])
    assert obtener_hora_fin_turno(h, "Casa Central", LUNES, legajo="2455") == time(17)


def test_dias_invalidos_ignoran_la_fila():
    h = pd.DataFrame([_fila_h("mal", "13:00", dias="xx")])
    assert excepcion_horario_activa(h, "Casa Central", LUNES) is None


def test_san_juan_sin_columnas_nuevas_sigue_igual():
    h = _horarios()  # hoja sin dias_semana ni solo_legajos
    assert obtener_hora_fin_turno(h, "Fábrica", LUNES) == time(11)
    assert obtener_hora_fin_turno(h, "Fábrica", date(2026, 10, 25)) == time(11)  # domingo: sin días = todos
