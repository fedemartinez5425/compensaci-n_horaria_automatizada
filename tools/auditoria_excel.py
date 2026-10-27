"""
tools/auditoria_excel.py
─────────────────────────────────────────────────────────────────
Auditoría de SOLO LECTURA de un exporte del Google Sheet (.xlsx).
No toca el Sheet real ni modifica el archivo: lista inconsistencias
para revisarlas y, si corresponde, corregirlas con aplicar_correcciones.py.

Uso (desde la raíz del repo):
    python -X utf8 tools/auditoria_excel.py "Control de Permisos - Fábrica.xlsx"
    python -X utf8 tools/auditoria_excel.py export.xlsx --hoy 2026-10-19 --csv auditoria.csv

El CSV de salida tiene nombres y legajos: queda ignorado por .gitignore,
no subirlo al repo.

Qué revisa:
- Valores fuera de lo canónico (compensa, planta).
- Minutos que no coinciden con salida/entrada, y horas que no respetan el redondeo.
- Sin Retorno de San Juan contra el fin de turno VIGENTE ese día según la
  hoja config_horarios del propio exporte (con sus excluidos_legajos).
  Detecta los permisos cargados antes de activar un horario especial.
- Fechas futuras o posteriores a la carga del registro.
- Compensa = SI con motivo fuera de la política de San Juan.
- Permisos duplicados y compensaciones repetidas el mismo día.
- Nombre distinto al del padrón, legajos fuera del padrón, planta rara o
  espacios de más en el padrón.
"""
import argparse
import os
import sys
from datetime import date, datetime

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit import logger as _st_logger  # noqa: E402

_st_logger.set_log_level("error")  # sheets_repo usa st.cache_data; fuera de la app avisa "No runtime found"

from config import HORA_FIN_TURNO, MOTIVOS_LISTA  # noqa: E402
from repositories.sheets_repo import normalizar_motivo  # noqa: E402
from services.permisos_service import (  # noqa: E402
    redondear_horas, puede_compensar_por_politica, obtener_hora_fin_turno,
)

PLANTAS_VALIDAS = ("Fábrica", "Casa Central")
TOLERANCIA_MIN = 0.6
_OFICIALES = {m.lower() for m in MOTIVOS_LISTA}


def _hora(valor):
    """Acepta '09:00', '9:00', '09:00:00' o un datetime.time."""
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if hasattr(valor, "hour"):
        return valor.replace(second=0, microsecond=0)
    texto = str(valor).strip()
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            return datetime.strptime(texto, fmt).time()
        except ValueError:
            continue
    return None


def _legajo(valor) -> str:
    """'2177', 2177 y 2177.0 son el mismo legajo."""
    texto = str(valor).strip()
    return texto[:-2] if texto.endswith(".0") else texto


def _minutos(f, desde, hasta) -> float:
    return (datetime.combine(f, hasta) - datetime.combine(f, desde)).total_seconds() / 60


def leer_config_horarios(xl: pd.ExcelFile) -> pd.DataFrame:
    """Misma normalización que repositories.sheets_repo.leer_config_horarios."""
    if "config_horarios" not in xl.sheet_names:
        return pd.DataFrame()
    df = xl.parse("config_horarios", dtype=object)
    if df.empty:
        return df
    df["desde"] = pd.to_datetime(df["desde"], errors="coerce").dt.date
    df["hasta"] = pd.to_datetime(df["hasta"], errors="coerce").dt.date
    df["planta"] = df["planta"].astype(str).str.strip()
    df["activo"] = df["activo"].astype(str).str.upper().str.strip()
    df["hora_fin"] = df["hora_fin"].apply(lambda v: _hora(v).strftime("%H:%M") if _hora(v) else str(v))
    for col in ("excluidos_legajos", "dias_semana", "solo_legajos"):
        if col not in df.columns:
            df[col] = ""
        df[col] = df[col].fillna("").astype(str)
    return df


def auditar(ruta: str, hoy: date | None = None) -> pd.DataFrame:
    hoy = hoy or date.today()
    xl = pd.ExcelFile(ruta)
    pe = xl.parse("permisos", dtype=object)
    pa = xl.parse("padron", dtype=object)
    co = xl.parse("compensaciones", dtype=object)
    horarios = leer_config_horarios(xl)

    for df in (pe, pa, co):
        df["_fila"] = df.index + 2
        df["legajo"] = df["legajo"].apply(_legajo)
    pa["nombre"] = pa["nombre"].astype(str)

    prob = []

    def anotar(hoja, fila, ident, problema, detalle=""):
        prob.append({"hoja": hoja, "fila": fila, "id": ident, "problema": problema, "detalle": detalle})

    # ── Permisos ────────────────────────────────────────────────
    for _, r in pe.iterrows():
        pid = str(r["id"])
        f = pd.to_datetime(r["fecha"], errors="coerce")
        comp = str(r["compensa"]).upper().strip()
        planta = str(r["planta"]).strip()
        mins = pd.to_numeric(r["minutos_reales"], errors="coerce")
        hrs = pd.to_numeric(r["horas_redondeadas"], errors="coerce")
        sal = _hora(r["hora_salida"])
        ent_txt = str(r["hora_entrada"]).strip()

        if pd.isna(f):
            anotar("permisos", r._fila, pid, "fecha inválida", str(r["fecha"]))
            continue
        if comp not in ("SI", "NO", "ANULADO"):
            anotar("permisos", r._fila, pid, "compensa fuera de SI/NO/ANULADO", comp)
        if planta not in PLANTAS_VALIDAS:
            anotar("permisos", r._fila, pid, "planta rara", planta)
        if pd.isna(mins):
            anotar("permisos", r._fila, pid, "minutos vacíos")
        if f.date() > hoy:
            anotar("permisos", r._fila, pid, "fecha futura", str(f.date()))

        if pid.startswith("P"):
            creado = pd.to_datetime(pid[1:15], format="%Y%m%d%H%M%S", errors="coerce")
            if pd.notna(creado) and f.normalize() > creado.normalize():
                anotar("permisos", r._fila, pid, "fecha posterior a la carga", str(f.date()))

        if not pid.startswith("P") or sal is None or comp == "ANULADO" or pd.isna(mins):
            continue  # históricos (HIST) y anulados no se recalculan

        if ent_txt == "S/R":
            if planta == "Fábrica":
                fin = obtener_hora_fin_turno(horarios, "Fábrica", f.date(), legajo=r["legajo"])
                calc = _minutos(f, sal, fin)
                if abs(calc - mins) > TOLERANCIA_MIN:
                    anotar("permisos", r._fila, pid, f"S/R no coincide con fin de turno {fin:%H:%M}",
                           f"{r['nombre']} salida {sal:%H:%M}: guardado {mins:g}min/{hrs:g}h → "
                           f"{calc:g}min/{redondear_horas(calc):g}h (compensa {comp})")
        else:
            ent = _hora(ent_txt)
            if ent:
                calc = _minutos(f, sal, ent)
                if abs(calc - mins) > TOLERANCIA_MIN:
                    anotar("permisos", r._fila, pid, "minutos ≠ entrada − salida",
                           f"{sal:%H:%M}–{ent:%H:%M} = {calc:g}min, guardado {mins:g}")

        if comp == "SI" and hrs != redondear_horas(mins):
            anotar("permisos", r._fila, pid, "horas ≠ redondeo de minutos",
                   f"{mins:g}min → {redondear_horas(mins):g}h, guardado {hrs:g}h")
        if comp == "NO" and ent_txt != "S/R" and hrs not in (0, redondear_horas(mins)):
            anotar("permisos", r._fila, pid, "horas raras en permiso que no compensa", f"{mins:g}min / {hrs:g}h")

        # Un texto libre es un motivo "Otro" (compensa por política); solo se
        # revisan los motivos de la lista oficial.
        if comp == "SI" and planta == "Fábrica" and str(r["motivo"]).strip().lower() in _OFICIALES:
            mot = normalizar_motivo(r["motivo"])
            if not puede_compensar_por_politica(mot, "Fábrica", True):
                anotar("permisos", r._fila, pid, "compensa SI con motivo fuera de política SJ",
                       f"'{r['motivo']}' → {mot}")

    claves = ["fecha", "legajo", "hora_salida", "hora_entrada", "motivo"]
    activos = pe[pe["id"].astype(str).str.startswith("P") & (pe["compensa"].astype(str).str.upper() != "ANULADO")]
    for _, r in activos[activos.duplicated(claves, keep=False)].iterrows():
        anotar("permisos", r._fila, r["id"], "posible duplicado",
               f"{r['nombre']} {r['fecha']} {r['hora_salida']} ({r['compensa']})")

    # ── Padrón y consistencia de nombres ────────────────────────
    leg2nom = dict(zip(pa["legajo"], pa["nombre"].str.strip().str.upper()))
    for hoja, df in (("permisos", pe), ("compensaciones", co)):
        for _, r in df.iterrows():
            nombre = leg2nom.get(r["legajo"])
            if nombre is None:
                anotar(hoja, r._fila, r["id"], "legajo fuera del padrón", f"{r['legajo']} {r['nombre']}")
            elif nombre != str(r["nombre"]).strip().upper():
                anotar(hoja, r._fila, r["id"], "nombre distinto al del padrón", f"{r['nombre']} vs {nombre}")

    for _, r in co[co.duplicated(["legajo", "fecha_compensacion"], keep=False)].iterrows():
        anotar("compensaciones", r._fila, r["id"], "más de una compensación el mismo día",
               f"{r['nombre']} {r['fecha_compensacion']} {r['horas_compensadas']}h")

    for _, r in pa.iterrows():
        if str(r["planta"]).strip() not in PLANTAS_VALIDAS:
            anotar("padron", r._fila, r["legajo"], "planta rara",
                   f"{r['nombre']} planta={r['planta']} activo={r.get('activo')}")
        if r["nombre"] != r["nombre"].strip() or "  " in r["nombre"]:
            anotar("padron", r._fila, r["legajo"], "espacios de más en el nombre", repr(r["nombre"]))
    for _, r in pa[pa.duplicated("legajo", keep=False)].iterrows():
        anotar("padron", r._fila, r["legajo"], "legajo repetido en el padrón", r["nombre"])

    return pd.DataFrame(prob, columns=["hoja", "fila", "id", "problema", "detalle"])


def main():
    ap = argparse.ArgumentParser(description="Auditoría de solo lectura de un exporte del Sheet.")
    ap.add_argument("excel", help="Ruta al .xlsx exportado del Google Sheet")
    ap.add_argument("--hoy", help="Fecha de referencia YYYY-MM-DD (default: hoy)")
    ap.add_argument("--csv", help="Guardar el resultado en este CSV (tiene datos personales)")
    args = ap.parse_args()

    hoy = date.fromisoformat(args.hoy) if args.hoy else None
    resultado = auditar(args.excel, hoy)
    if resultado.empty:
        print("Sin observaciones.")
        return
    pd.set_option("display.width", 250)
    pd.set_option("display.max_colwidth", 140)
    pd.set_option("display.max_rows", 1000)
    print(resultado.to_string(index=False))
    print(f"\n{len(resultado)} observaciones. Fin de turno general: {HORA_FIN_TURNO:%H:%M}.")
    if args.csv:
        resultado.to_csv(args.csv, index=False, encoding="utf-8-sig")
        print(f"Guardado en {args.csv}")


if __name__ == "__main__":
    main()
