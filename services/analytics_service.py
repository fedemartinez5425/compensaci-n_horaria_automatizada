"""
services/analytics_service.py
─────────────────────────────────────────────────────────────────
Lógica analítica: MOD, pareto, duración, tiempo no productivo.
No conoce Google Sheets ni Streamlit.
"""
import pandas as pd
from config import ALMUERZO_H
from services.permisos_service import excepcion_horario_activa


# ─────────────────────────────────────────────
# FILTROS BASE
# ─────────────────────────────────────────────
def filtrar_mod(
    permisos_df: pd.DataFrame,
    sector_dict: dict,
    clasif_dict: dict,
) -> pd.DataFrame:
    """Filtra HOURLY DIRECT de sector COSTURA."""
    if permisos_df.empty:
        return permisos_df
    df = permisos_df.copy()
    df["sector_emp"] = df["legajo"].map(sector_dict).fillna("")
    df["clasif_emp"] = df["legajo"].map(clasif_dict).fillna("")
    return df[
        (df["clasif_emp"].str.upper() == "HOURLY DIRECT") &
        (df["sector_emp"].str.upper().str.contains("COSTURA", na=False))
    ].copy()


def filtrar_rango_fecha(df: pd.DataFrame, desde, hasta, col="fecha") -> pd.DataFrame:
    return df[(df[col].dt.date >= desde) & (df[col].dt.date <= hasta)].copy()


# ─────────────────────────────────────────────
# ALMUERZO — se descuenta solo en días con jornada normal
# ─────────────────────────────────────────────
def almuerzo_del_dia(fecha, plantas, config_horarios=None, almuerzo_h: float = ALMUERZO_H) -> float:
    """
    Horas de almuerzo a descontar ese día en las métricas MOD.
    Si ese día rige un horario especial (hoja config_horarios) para TODAS
    las plantas con registros ese día, no se descuenta: la jornada
    reducida (ej: 6 a 11) no tiene almuerzo. Si no hay horario especial,
    se descuenta el almuerzo normal (ALMUERZO_H).
    """
    if config_horarios is None or config_horarios.empty:
        return almuerzo_h
    plantas = [p for p in set(plantas) if p]
    if plantas and all(excepcion_horario_activa(config_horarios, p, fecha) for p in plantas):
        return 0.0
    return almuerzo_h


def _resumen_diario(df: pd.DataFrame, col_horas: str, titulo: str,
                    config_horarios, almuerzo_h: float) -> pd.DataFrame:
    df = df.copy()
    df["_dia"] = df["fecha"].dt.date
    if "planta" not in df.columns:
        df["planta"] = ""
    resumen = (
        df.groupby("_dia")
        .agg(
            total=(col_horas, "sum"),
            plantas=("planta", lambda x: list(x.unique())),
            personas=("nombre", "nunique"),
            nombres=("nombre", lambda x: ", ".join(sorted(x.unique()))),
        )
        .reset_index()
        .sort_values("_dia")   # orden cronológico real (no alfabético dd/mm/aaaa)
    )
    resumen["Almuerzo desc."] = [
        almuerzo_del_dia(d, pl, config_horarios, almuerzo_h)
        for d, pl in zip(resumen["_dia"], resumen["plantas"])
    ]
    resumen[titulo] = (resumen["total"] - resumen["Almuerzo desc."]).clip(lower=0).round(2)
    resumen["Fecha"] = pd.to_datetime(resumen["_dia"]).dt.strftime("%d/%m/%Y")
    return resumen.rename(columns={"personas": "Personas", "nombres": "Empleados"})[
        ["Fecha", titulo, "Almuerzo desc.", "Personas", "Empleados"]
    ].reset_index(drop=True)


# ─────────────────────────────────────────────
# MOD — HORAS NO TRABAJADAS (todas)
# ─────────────────────────────────────────────
def resumen_mod_diario(df_mod: pd.DataFrame, config_horarios=None,
                       almuerzo_h: float = ALMUERZO_H) -> pd.DataFrame:
    """
    Agrupa por día: horas brutas − almuerzo (0 en días con horario especial).
    Usa minutos_reales para decimales exactos.
    """
    if df_mod.empty:
        return pd.DataFrame()
    df = df_mod.copy()
    df["hs_brutas"] = df["minutos_reales"] / 60
    return _resumen_diario(df, "hs_brutas", "Hs. no trabajadas", config_horarios, almuerzo_h)


# ─────────────────────────────────────────────
# MOD — HORAS SIN COMPENSAR
# ─────────────────────────────────────────────
def calc_hs_no_comp(row) -> float:
    """Calcula horas reales desde las columnas disponibles (en orden de prioridad)."""
    if pd.notna(row.get("minutos_reales")) and row["minutos_reales"] > 0:
        return round(row["minutos_reales"] / 60, 2)
    if pd.notna(row.get("horas_redondeadas")) and row["horas_redondeadas"] > 0:
        return float(row["horas_redondeadas"])
    try:
        sal, ent = row["hora_salida"], row["hora_entrada"]
        if (isinstance(sal, str) and isinstance(ent, str)
                and len(sal) == 5 and len(ent) == 5 and ent != "S/R"):
            h_s, m_s = map(int, sal.split(":"))
            h_e, m_e = map(int, ent.split(":"))
            mins = (h_e * 60 + m_e) - (h_s * 60 + m_s)
            return round(mins / 60, 2) if mins > 0 else 0.0
    except Exception:
        pass
    return 0.0


def resumen_mod_nc_diario(df_mod_nc: pd.DataFrame, config_horarios=None,
                          almuerzo_h: float = ALMUERZO_H) -> pd.DataFrame:
    """Resumen diario de horas MOD sin compensar, con descuento de almuerzo (0 en horario especial)."""
    if df_mod_nc.empty:
        return pd.DataFrame()
    df = df_mod_nc.copy()
    df["hs_real"] = df.apply(calc_hs_no_comp, axis=1)
    return _resumen_diario(df, "hs_real", "Hs. no compensadas", config_horarios, almuerzo_h)


def detalle_mod_nc_por_persona(df_mod_nc: pd.DataFrame) -> pd.DataFrame:
    if df_mod_nc.empty:
        return pd.DataFrame()
    df = df_mod_nc.copy()
    df["hs_real"]   = df.apply(calc_hs_no_comp, axis=1)
    df["fecha_str"] = df["fecha"].dt.strftime("%d/%m/%Y")
    det = (
        df.groupby(["nombre", "motivo"])
        .agg(permisos=("fecha_str", "count"), horas=("hs_real", "sum"))
        .reset_index()
        .sort_values("horas", ascending=False)
    )
    det["horas"] = det["horas"].apply(lambda x: f"{x:.2f}h")
    det.columns  = ["Nombre", "Motivo", "Permisos", "Horas"]
    return det


# ─────────────────────────────────────────────
# TIEMPO NO PRODUCTIVO ACUMULADO
# ─────────────────────────────────────────────
def tiempo_no_productivo(
    permisos_df: pd.DataFrame,
    comp_df: pd.DataFrame,
) -> dict:
    """Horas comprometidas vs recuperadas — vista acumulada."""
    if permisos_df.empty:
        return {}
    df_p = permisos_df[permisos_df["compensa"] == "SI"].copy()
    df_p["mes"] = df_p["fecha"].dt.strftime("%Y-%m")
    por_mes = df_p.groupby("mes")["horas_redondeadas"].sum().reset_index()
    por_mes.columns = ["Mes", "Horas comprometidas"]

    total_c = float(df_p["horas_redondeadas"].sum())
    total_r = float(comp_df["horas_compensadas"].sum()) if not comp_df.empty else 0.0
    pct     = round(total_r / total_c * 100, 1) if total_c > 0 else 0.0

    return {
        "total_comprometidas": total_c,
        "total_recuperadas":   total_r,
        "total_pendientes":    round(max(0.0, total_c - total_r), 1),
        "pct_recuperado":      pct,
        "por_mes":             por_mes,
    }


# ─────────────────────────────────────────────
# PARETO DE MOTIVOS
# ─────────────────────────────────────────────
def calcular_pareto(df: pd.DataFrame, col_motivo: str = "motivo") -> pd.DataFrame:
    """
    Retorna el subset de motivos que explican el 80% de los permisos,
    ordenado de mayor a menor. El top1 es el primero de la lista ordenada.
    """
    if df.empty:
        return pd.DataFrame(columns=["Motivo", "Cantidad", "acum_pct"])
    mc = df[col_motivo].value_counts().reset_index()
    mc.columns = ["Motivo", "Cantidad"]
    mc["acum_pct"] = (mc["Cantidad"].cumsum() / mc["Cantidad"].sum() * 100)
    pareto = mc[mc["acum_pct"].shift(1, fill_value=0) < 80].head(8)
    return pareto.reset_index(drop=True)


# ─────────────────────────────────────────────
# DURACIÓN DE PERMISOS
# ─────────────────────────────────────────────
def categorizar_duracion(minutos: float) -> str:
    if minutos < 30:    return "< 30 min"
    elif minutos < 60:  return "30 – 60 min"
    elif minutos < 90:  return "1h – 1h 30min"
    elif minutos < 120: return "1h 30min – 2h"
    else:               return "Más de 2h"


ORDEN_DURACION = ["< 30 min", "30 – 60 min", "1h – 1h 30min", "1h 30min – 2h", "Más de 2h"]


def tabla_duracion(df: pd.DataFrame) -> pd.DataFrame:
    df_dur = df[df["minutos_reales"].notna() & (df["minutos_reales"] > 0)].copy()
    if df_dur.empty:
        return pd.DataFrame()
    df_dur["rango"] = df_dur["minutos_reales"].apply(categorizar_duracion)
    c = (
        df_dur["rango"].value_counts()
        .reindex(ORDEN_DURACION, fill_value=0)
        .reset_index()
    )
    c.columns = ["Rango", "Cantidad"]
    c["Pct"]  = (c["Cantidad"] / c["Cantidad"].sum() * 100).round(1)
    return c
