from datetime import date

import pandas as pd

from services.analytics_service import (
    almuerzo_del_dia, resumen_mod_diario, resumen_mod_nc_diario,
)


def _horarios():
    return pd.DataFrame([{
        "id": "H1", "planta": "Fábrica",
        "desde": date(2026, 9, 1), "hasta": date(2026, 12, 31),
        "hora_fin": "11:00", "descripcion": "Reducción horaria", "activo": "SI",
        "excluidos_legajos": "",
    }])


def _mod(filas):
    df = pd.DataFrame(filas, columns=["fecha", "nombre", "planta", "minutos_reales", "compensa"])
    df["fecha"] = pd.to_datetime(df["fecha"])
    df["horas_redondeadas"] = 0
    df["hora_salida"] = df["hora_entrada"] = ""
    return df


def test_almuerzo_normal_y_horario_especial():
    h = _horarios()
    assert almuerzo_del_dia(date(2026, 8, 31), ["Fábrica"], h) == 0.5
    assert almuerzo_del_dia(date(2026, 9, 17), ["Fábrica"], h) == 0.0
    assert almuerzo_del_dia(date(2026, 9, 17), ["Casa Central"], h) == 0.5
    assert almuerzo_del_dia(date(2026, 9, 17), ["Fábrica"], None) == 0.5


def test_resumen_mod_sin_almuerzo_en_horario_especial_y_orden_cronologico():
    df = _mod([
        ("2026-10-01", "A", "Fábrica", 120, "NO"),
        ("2026-08-31", "B", "Fábrica", 120, "NO"),
        ("2026-09-17", "C", "Fábrica", 60, "NO"),
    ])
    r = resumen_mod_diario(df, _horarios())
    assert list(r["Fecha"]) == ["31/08/2026", "17/09/2026", "01/10/2026"]
    assert list(r["Hs. no trabajadas"]) == [1.5, 1.0, 2.0]
    assert list(r["Almuerzo desc."]) == [0.5, 0.0, 0.0]


def test_resumen_mod_sin_config_mantiene_regla_vieja():
    df = _mod([("2026-09-17", "C", "Fábrica", 60, "NO")])
    assert resumen_mod_diario(df)["Hs. no trabajadas"].iloc[0] == 0.5
    assert resumen_mod_nc_diario(df)["Hs. no compensadas"].iloc[0] == 0.5
    assert resumen_mod_nc_diario(df, _horarios())["Hs. no compensadas"].iloc[0] == 1.0
