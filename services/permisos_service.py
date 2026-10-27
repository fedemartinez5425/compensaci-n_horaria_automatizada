"""
services/permisos_service.py
─────────────────────────────────────────────────────────────────
Toda la lógica de negocio de permisos y compensaciones.
No conoce Google Sheets ni Streamlit.
"""
import secrets
import unicodedata
import pandas as pd
from datetime import date, datetime, time
from config import (
    HORA_FIN_TURNO, HORA_FIN_TURNO_BSAS, DIAS_SEMANA,
    TOPE_HORAS_NORMAL, TOPE_HORAS_LIDER,
    MOTIVOS_FUERA_TOPE,
    MOTIVOS_COMPENSAN_SJ, MOTIVOS_COMPENSAN_LIDERES_SJ,
    MOTIVOS_COMPENSAN_BSAS,
    TOPE_HORAS_BSAS, TOPE_HORAS_POR_PERMISO_BSAS,
)


# ─────────────────────────────────────────────
# REDONDEO Y FORMATEO
# ─────────────────────────────────────────────
def redondear_horas(minutos: float) -> float:
    """
    Regla de fábrica: < 30 min → 0h | 30–89 → 1h | 90–149 → 2h …
    Fracción >= :30 sobre la hora entera sube al entero siguiente.
    """
    if minutos is None or pd.isna(minutos) or minutos < 30:
        return 0.0
    parte    = int(minutos // 60)
    fraccion = (minutos % 60) / 60
    return float(parte + 1) if fraccion >= 0.5 else float(parte)


def minutos_entre(t_sal: time, t_ent: time) -> float:
    """Minutos entre dos objetos time (mismo día)."""
    ref   = date.today()
    delta = datetime.combine(ref, t_ent) - datetime.combine(ref, t_sal)
    return round(delta.seconds / 60, 1)


def fmt_dur(minutos: float) -> str:
    h = int(minutos // 60)
    m = int(minutos % 60)
    if h == 0:
        return f"{m} min"
    return f"{h}h {m:02d}min" if m else f"{h}h"


def fmt_horas(h: float) -> str:
    """0.5 → '0.5h', 1 → '1h', 1.5 → '1.5h'"""
    if h == int(h):
        return f"{int(h)}h"
    return f"{h:.1f}h"


def generar_id(prefijo: str = "P") -> str:
    """
    Prefijo + fecha/hora + milisegundos + 8 caracteres al azar.
    Los milisegundos y el sufijo evitan IDs repetidos si dos personas
    guardan en el mismo segundo (ej: guardia SJ y Bs. As. a la vez).
    """
    ahora = datetime.now()
    return f"{prefijo}{ahora.strftime('%Y%m%d%H%M%S')}{ahora.microsecond // 1000:03d}{secrets.token_hex(4)}"


# ─────────────────────────────────────────────
# HORARIO DE FIN DE TURNO (con excepciones configurables desde la UI)
# ─────────────────────────────────────────────
def _parse_excluidos(valor) -> list[str]:
    """Convierte un campo de legajos separados por coma ('excluidos_legajos', 'solo_legajos') en lista."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return []
    return [x.strip() for x in str(valor).split(",") if x.strip()]


_DIA_A_NUMERO = {cod: i for i, cod in enumerate(DIAS_SEMANA)}  # LU=0 … DO=6, como date.weekday()


def parse_dias_semana(valor) -> set[int] | None:
    """
    'LU,MA' → {0, 1}. Vacío → None (todos los días). Acepta nombres completos
    o con/sin acento ('lunes', 'Miércoles'): se usan las 2 primeras letras.
    Si hay texto pero ningún día reconocible → set() (la fila se ignora).
    """
    dias = _parse_excluidos(valor)
    if not dias:
        return None
    out = set()
    for d in dias:
        cod = unicodedata.normalize("NFKD", d).encode("ascii", "ignore").decode().upper()[:2]
        if cod in _DIA_A_NUMERO:
            out.add(_DIA_A_NUMERO[cod])
    return out


def hora_fin_normal(planta_key: str) -> time:
    """Fin de turno sin horario especial: San Juan 15:00, Bs. As. 17:00."""
    return HORA_FIN_TURNO_BSAS if planta_key == "Casa Central" else HORA_FIN_TURNO


def excepcion_horario_activa(
    config_horarios_df: pd.DataFrame,
    planta_key: str,
    fecha=None,
    legajo: str = None,
) -> dict | None:
    """
    Devuelve el diccionario de la excepción vigente para esa planta/fecha
    (leída de la hoja config_horarios, cargada desde el Panel RRHH), o
    None si no hay ninguna activa (rige el horario general).

    Cada fila puede limitarse con columnas opcionales:
    - `dias_semana` ('LU,MA'): solo rige esos días. Vacío = todos.
    - `solo_legajos`: rige SOLO para esas personas (ej: rotativos que hacen
      jornada completa los lunes). Le gana a una fila general de la planta.
    - `excluidos_legajos`: personas a las que una fila general NO se les
      aplica (siguen con el horario normal o con la siguiente fila que les toque).

    Orden: primero una fila con `solo_legajos` que incluya a la persona;
    si no hay, la primera fila general donde no esté excluida. Sin `legajo`
    solo se miran las filas generales.
    """
    if fecha is None:
        fecha = date.today()
    if config_horarios_df is None or config_horarios_df.empty:
        return None
    activas = config_horarios_df[config_horarios_df["activo"] == "SI"]
    especificas, generales = [], []
    for _, row in activas.iterrows():
        try:
            if not (row["desde"] <= fecha <= row["hasta"]):
                continue
        except TypeError:
            continue  # fecha vacía o inválida: fila mal cargada
        if row["planta"] not in (planta_key, "Todas"):
            continue
        dias = parse_dias_semana(row.get("dias_semana", ""))
        if dias is not None and fecha.weekday() not in dias:
            continue
        try:
            hora_fin = datetime.strptime(str(row["hora_fin"]), "%H:%M").time()
        except ValueError:
            continue  # fila mal cargada, la ignoramos en vez de romper la app
        exc = {
            "id":           row.get("id", ""),
            "descripcion":  row.get("descripcion", "Horario especial"),
            "planta":       row["planta"],
            "desde":        row["desde"],
            "hasta":        row["hasta"],
            "hora_fin":     hora_fin,
            "excluidos":    _parse_excluidos(row.get("excluidos_legajos", "")),
            "solo_legajos": _parse_excluidos(row.get("solo_legajos", "")),
            "dias":         dias,
        }
        (especificas if exc["solo_legajos"] else generales).append(exc)

    if legajo:
        for exc in especificas:
            if legajo in exc["solo_legajos"]:
                return exc
    for exc in generales:
        if legajo and legajo in exc["excluidos"]:
            continue  # esta persona está exceptuada de la excepción
        return exc
    return None


def obtener_hora_fin_turno(
    config_horarios_df: pd.DataFrame,
    planta_key: str,
    fecha=None,
    legajo: str = None,
) -> time:
    """
    Hora de "fin de turno" vigente para esa planta/fecha/persona.
    Si hay una excepción activa (cargada desde el Panel RRHH) la usa; si no,
    el horario normal de la planta (`hora_fin_normal`). En San Juan calcula
    los S/R; en Bs. As. solo sugiere la hora de entrada. No afecta topes.
    """
    exc = excepcion_horario_activa(config_horarios_df, planta_key, fecha, legajo)
    return exc["hora_fin"] if exc else hora_fin_normal(planta_key)


# ─────────────────────────────────────────────
# TOPES
# ─────────────────────────────────────────────
def obtener_tope(es_lider: str, planta_key: str = "Fábrica") -> float:
    """
    Tope anual de compensación.
    - Bs. As. (política 036): 10h fijas, sin distinguir líder.
    - San Juan (política 020) — comportamiento sin cambios: 8h normal / 16h líder.
    El parámetro planta_key es opcional para no romper llamados existentes
    de San Juan que no lo pasan (default = "Fábrica").
    """
    if planta_key == "Casa Central":
        return TOPE_HORAS_BSAS
    return TOPE_HORAS_LIDER if str(es_lider).strip().upper() == "SI" else TOPE_HORAS_NORMAL


def excede_tope_por_permiso(horas: float, planta_key: str) -> bool:
    """
    Bs. As. (política 036): máximo 4h compensables por permiso individual.
    No aplica a San Juan (siempre devuelve False ahí).
    """
    if planta_key == "Casa Central":
        return horas > TOPE_HORAS_POR_PERMISO_BSAS
    return False


def _es_fuera_tope(permisos_df: pd.DataFrame) -> pd.Series:
    """
    Motivo con cupo extra fuera de tope. El cupo extra es SOLO de San Juan:
    en Bs. As. esos motivos (si aparecen, ej: importación histórica) cuentan
    contra el tope normal de 10h.
    """
    es_sj = (permisos_df["planta"] == "Fábrica") if "planta" in permisos_df.columns else True
    return permisos_df["motivo"].isin(MOTIVOS_FUERA_TOPE) & es_sj


def horas_comprometidas_año(permisos_df: pd.DataFrame, legajo: str, año: int) -> float:
    """Horas con compensa=SI en el año (excluye motivos fuera de tope de San Juan)."""
    if permisos_df.empty:
        return 0.0
    p = permisos_df[
        (permisos_df["legajo"] == legajo) &
        (permisos_df["compensa"] == "SI") &
        (permisos_df["fecha"].dt.year == año) &
        (~_es_fuera_tope(permisos_df))
    ]
    return float(p["horas_redondeadas"].sum()) if not p.empty else 0.0


def horas_fuera_tope_año(permisos_df: pd.DataFrame, legajo: str, año: int) -> float:
    """Horas del cupo extra (motivos fuera de tope, solo San Juan) en el año."""
    if permisos_df.empty:
        return 0.0
    p = permisos_df[
        (permisos_df["legajo"] == legajo) &
        (permisos_df["compensa"] == "SI") &
        (permisos_df["fecha"].dt.year == año) &
        (_es_fuera_tope(permisos_df))
    ]
    return float(p["horas_redondeadas"].sum()) if not p.empty else 0.0


# ─────────────────────────────────────────────
# POLÍTICA DE MOTIVOS
# ─────────────────────────────────────────────
def puede_compensar_por_politica(motivo: str, planta_key: str, es_lider: bool) -> bool:
    """
    Dado un motivo, planta y si la persona es líder,
    retorna si la política permite compensar.
    """
    if planta_key == "Fábrica":
        policy = MOTIVOS_COMPENSAN_LIDERES_SJ if es_lider else MOTIVOS_COMPENSAN_SJ
    elif planta_key == "Casa Central":
        policy = MOTIVOS_COMPENSAN_BSAS
    else:
        return True   # Total Empresa: sin restricción
    return motivo in policy


# ─────────────────────────────────────────────
# SALDOS
# ─────────────────────────────────────────────
def calcular_saldos(
    permisos_df: pd.DataFrame,
    comp_df: pd.DataFrame,
    hasta_fecha=None,
) -> pd.DataFrame:
    """
    Saldo acumulado por persona (compensa=SI menos compensaciones registradas).
    Si hasta_fecha (date), filtra ambas tablas hasta esa fecha.
    Retorna solo personas con saldo > 0.
    """
    cols = ["legajo", "nombre", "debe", "compensado", "saldo"]
    if permisos_df.empty:
        return pd.DataFrame(columns=cols)

    p = permisos_df[permisos_df["compensa"] == "SI"].copy()
    c = comp_df.copy() if not comp_df.empty else pd.DataFrame()

    if hasta_fecha is not None:
        p = p[p["fecha"].dt.date <= hasta_fecha]
        if not c.empty and "fecha_compensacion" in c.columns:
            c = c[c["fecha_compensacion"].dt.date <= hasta_fecha]

    if p.empty:
        return pd.DataFrame(columns=cols)

    debe = (
        p.groupby(["legajo", "nombre"])["horas_redondeadas"]
        .sum().reset_index()
        .rename(columns={"horas_redondeadas": "debe"})
    )
    if not c.empty and "horas_compensadas" in c.columns:
        comp = (
            c.groupby("legajo")["horas_compensadas"]
            .sum().reset_index()
            .rename(columns={"horas_compensadas": "compensado"})
        )
        saldo = debe.merge(comp, on="legajo", how="left")
    else:
        saldo          = debe.copy()
        saldo["compensado"] = 0.0

    saldo["compensado"] = saldo["compensado"].fillna(0.0)
    saldo["saldo"]      = (saldo["debe"] - saldo["compensado"]).round(1)
    return (
        saldo[saldo["saldo"] > 0]
        .sort_values("saldo", ascending=False)
        .reset_index(drop=True)
    )


# ─────────────────────────────────────────────
# KPI ACUMULADO DE COMPENSACIÓN
# ─────────────────────────────────────────────
def kpi_compensacion_acumulado(
    permisos_df: pd.DataFrame,
    comp_df: pd.DataFrame,
) -> dict:
    """
    Retorna dict con:
      - hs_comprometidas: total horas con compensa=SI
      - hs_recuperadas:   total horas efectivamente compensadas
      - pct:              porcentaje de cumplimiento (0-100)
      - hs_pendientes:    diferencia
    """
    if permisos_df.empty:
        return {"hs_comprometidas": 0, "hs_recuperadas": 0, "pct": 0, "hs_pendientes": 0}

    hs_c = float(permisos_df[permisos_df["compensa"] == "SI"]["horas_redondeadas"].sum())
    hs_r = float(comp_df["horas_compensadas"].sum()) if not comp_df.empty else 0.0
    pct  = round(min(100.0, (hs_r / hs_c * 100)), 1) if hs_c > 0 else 0.0
    return {
        "hs_comprometidas": hs_c,
        "hs_recuperadas":   hs_r,
        "pct":              pct,
        "hs_pendientes":    round(max(0.0, hs_c - hs_r), 1),
    }


# ─────────────────────────────────────────────
# INDICADOR MENSUAL (para tabla Panel RRHH)
# ─────────────────────────────────────────────
def indicador_mensual(
    permisos_df: pd.DataFrame,
    comp_df: pd.DataFrame,
) -> pd.DataFrame:
    if permisos_df.empty:
        return pd.DataFrame()
    df_p = permisos_df[permisos_df["compensa"] == "SI"].copy()
    df_p["mes"] = df_p["fecha"].dt.to_period("M").astype(str)
    por_mes = df_p.groupby("mes")["horas_redondeadas"].sum().reset_index()
    por_mes.columns = ["Mes", "Hs. comprometidas"]

    if not comp_df.empty:
        df_c = comp_df.copy()
        df_c["mes"] = df_c["fecha_compensacion"].dt.to_period("M").astype(str)
        comp_mes = df_c.groupby("mes")["horas_compensadas"].sum().reset_index()
        comp_mes.columns = ["Mes", "Hs. compensadas"]
        ind = por_mes.merge(comp_mes, on="Mes", how="left")
    else:
        ind = por_mes.copy()
        ind["Hs. compensadas"] = 0.0

    ind["Hs. compensadas"] = ind["Hs. compensadas"].fillna(0)
    ind["% Cumplimiento"] = (
        (ind["Hs. compensadas"] / ind["Hs. comprometidas"] * 100)
        .clip(upper=100).round(1)
    )
    return ind


# ─────────────────────────────────────────────
# VALIDACIONES
# ─────────────────────────────────────────────
def validar_permiso(
    nombre_resuelto: str,
    registrado_por: str,
    sin_retorno: bool,
    hora_salida: time,
    hora_entrada: time,
    hora_fin_turno: time = HORA_FIN_TURNO,
) -> list[str]:
    """Retorna lista de errores. Vacía = sin errores."""
    errores = []
    if not nombre_resuelto:
        errores.append("Seleccioná o buscá a la persona primero.")
    if not registrado_por.strip():
        errores.append("Falta el nombre del guardia.")
    if sin_retorno and hora_salida >= hora_fin_turno:
        errores.append(
            f"Hora de salida posterior al fin de turno ({hora_fin_turno.strftime('%H:%M')}). Verificá."
        )
    if not sin_retorno and hora_entrada <= hora_salida:
        errores.append("La hora de entrada debe ser posterior a la salida.")
    return errores


def validar_compensacion(nombre: str, registrado_por: str) -> list[str]:
    errores = []
    if not nombre:
        errores.append("Seleccioná a la persona.")
    if not registrado_por.strip():
        errores.append("Falta tu nombre.")
    return errores