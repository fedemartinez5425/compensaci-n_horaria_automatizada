"""
repositories/sheets_repo.py
─────────────────────────────────────────────────────────────────
Toda la comunicación con Google Sheets vive aquí.
Para migrar a SharePoint/Excel: reemplazar este archivo únicamente.
El resto de la app no conoce Google Sheets.

Regla: toda escritura se hace por NOMBRE de columna (encabezados de la
fila 1), nunca por posición, y toda búsqueda de personas es por legajo.
"""
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from config import SCOPES, MOTIVO_MAP, LIDERES_SJ, MOTIVOS_LISTA

# Motivos oficiales indexados en minúscula, para reconocerlos tal cual.
_MOTIVOS_CANONICOS = {m.lower(): m for m in MOTIVOS_LISTA}


def normalizar_motivo(raw: str) -> str:
    """
    1) Motivo oficial de MOTIVOS_LISTA → se devuelve EXACTO (antes se le
       aplicaba .title() y "Renovación Carnet de Conducir" pasaba a
       "...De Conducir", rompiendo el cupo fuera de tope y la política).
    2) Variante histórica escrita a mano → MOTIVO_MAP.
    3) Texto libre (motivo "Otro") → se deja prolijo con .title().
    """
    if not raw or pd.isna(raw):
        return "Otro"
    clave = " ".join(str(raw).split()).lower()
    if clave in _MOTIVOS_CANONICOS:
        return _MOTIVOS_CANONICOS[clave]
    return MOTIVO_MAP.get(clave, str(raw).strip().title())


# ─────────────────────────────────────────────
# CONEXIÓN
# ─────────────────────────────────────────────
@st.cache_resource(ttl=3600)
def conectar() -> gspread.Client:
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return gspread.authorize(creds)


@st.cache_resource(ttl=3600)
def get_workbook(_gc: gspread.Client) -> gspread.Spreadsheet:
    return _gc.open_by_key(st.secrets["SHEET_ID"])


# ─────────────────────────────────────────────
# HELPERS DE ESCRITURA — siempre por nombre de columna, nunca por posición.
# Así un cambio de orden de columnas en el Sheet (o una columna nueva) no
# corrompe datos, y la migración a SharePoint Lists es directa.
# ─────────────────────────────────────────────
def _encabezados(ws) -> list[str]:
    return [str(h).strip() for h in ws.row_values(1)]


def _col(headers: list[str], nombre: str) -> int:
    """Número de columna (1-based) de un encabezado. Error claro si no existe."""
    if nombre not in headers:
        raise ValueError(f"La hoja no tiene la columna '{nombre}' en la fila 1.")
    return headers.index(nombre) + 1


def ordenar_por_encabezado(fila: dict, headers: list[str], opcionales=()) -> tuple[list, list[str]]:
    """
    Arma la fila a escribir respetando el orden real de columnas del Sheet.
    Columnas del Sheet que no vienen en `fila` quedan vacías.
    Claves de `fila` sin columna en el Sheet: si son opcionales se descartan
    (y se devuelven en la segunda posición para poder avisar); si no, ValueError.
    """
    faltan = [k for k in fila if k not in headers]
    obligatorias = [k for k in faltan if k not in opcionales]
    if obligatorias:
        raise ValueError(
            "La hoja no tiene estas columnas en la fila 1: "
            + ", ".join(obligatorias) + ". Agregalas y volvé a intentar."
        )
    return [fila.get(h, "") for h in headers], faltan


def _append_por_encabezado(ws, fila: dict, opcionales=(), headers=None) -> list[str]:
    headers = headers or _encabezados(ws)
    valores, descartadas = ordenar_por_encabezado(fila, headers, opcionales)
    ws.append_row(valores, value_input_option="RAW")
    return descartadas


# ─────────────────────────────────────────────
# LECTURA
# ─────────────────────────────────────────────
@st.cache_data(ttl=60)
def leer_padron(_gc) -> pd.DataFrame:
    ws = get_workbook(_gc).worksheet("padron")
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return df
    df["legajo"]        = df["legajo"].astype(str).str.strip()
    df["nombre"]        = df["nombre"].astype(str).str.strip().str.upper()
    df["planta"]        = df["planta"].astype(str).str.strip()
    df["sector"]        = df["sector"].astype(str).str.strip() if "sector" in df.columns else ""
    df["clasificacion"] = df["clasificacion"].astype(str).str.strip() if "clasificacion" in df.columns else ""
    if "es_lider" not in df.columns:
        df["es_lider"] = df["nombre"].apply(lambda n: "SI" if n in LIDERES_SJ else "NO")
    else:
        df["es_lider"] = df["es_lider"].astype(str).str.strip().str.upper()
        df["es_lider"] = df["es_lider"].where(
            df["es_lider"].isin(["SI", "NO"]),
            df["nombre"].apply(lambda n: "SI" if n in LIDERES_SJ else "NO")
        )
    return df


@st.cache_data(ttl=20)
def leer_permisos(_gc) -> pd.DataFrame:
    ws = get_workbook(_gc).worksheet("permisos")
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return df
    df["fecha"]             = pd.to_datetime(df["fecha"], errors="coerce")
    df["minutos_reales"]    = pd.to_numeric(df["minutos_reales"], errors="coerce")
    df["horas_redondeadas"] = pd.to_numeric(df["horas_redondeadas"], errors="coerce")
    df["compensa"]          = df["compensa"].astype(str).str.upper().str.strip()
    df["legajo"]            = df["legajo"].astype(str).str.strip()
    df["planta"]            = df["planta"].astype(str).str.strip()
    df["motivo"]            = df["motivo"].apply(normalizar_motivo)
    return df


@st.cache_data(ttl=20)
def leer_compensaciones(_gc) -> pd.DataFrame:
    ws = get_workbook(_gc).worksheet("compensaciones")
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return df
    df["fecha_compensacion"] = pd.to_datetime(df["fecha_compensacion"], errors="coerce")
    df["horas_compensadas"]  = pd.to_numeric(df["horas_compensadas"], errors="coerce")
    df["legajo"]             = df["legajo"].astype(str).str.strip()
    df["planta"]             = df["planta"].astype(str).str.strip()
    return df


@st.cache_data(ttl=30)
def leer_config_horarios(_gc) -> pd.DataFrame:
    """
    Hoja 'config_horarios' — excepciones de horario de fin de turno
    (ej: reducción horaria temporal), editables desde el Panel RRHH sin
    tocar código. Si la hoja todavía no existe en el Google Sheet,
    devuelve vacío y la app sigue funcionando con el horario general
    (fallback seguro, no rompe nada mientras se crea la hoja).
    """
    try:
        ws = get_workbook(_gc).worksheet("config_horarios")
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=[
            "id", "planta", "desde", "hasta", "hora_fin",
            "descripcion", "activo", "excluidos_legajos",
            "creado_por", "timestamp",
        ])
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return df
    df["desde"]    = pd.to_datetime(df["desde"], errors="coerce").dt.date
    df["hasta"]    = pd.to_datetime(df["hasta"], errors="coerce").dt.date
    df["planta"]   = df["planta"].astype(str).str.strip()
    df["activo"]   = df["activo"].astype(str).str.upper().str.strip()
    df["hora_fin"] = df["hora_fin"].astype(str).str.strip()  # formato "HH:MM"
    if "excluidos_legajos" not in df.columns:
        df["excluidos_legajos"] = ""  # hojas creadas antes de esta columna existir
    else:
        df["excluidos_legajos"] = df["excluidos_legajos"].astype(str).replace("nan", "")
    return df


@st.cache_data(ttl=30)
def leer_config_app(_gc) -> dict:
    """
    Hoja 'config_app' — configuración general clave/valor editable desde
    el Panel RRHH (hoy: las 2 contraseñas de acceso). Columnas esperadas:
    clave, valor, actualizado_por, timestamp.
    Si la hoja todavía no existe, devuelve {} — la app cae a las
    contraseñas iniciales de secrets.toml (ver app.py).
    """
    try:
        ws = get_workbook(_gc).worksheet("config_app")
    except gspread.exceptions.WorksheetNotFound:
        return {}
    registros = ws.get_all_records()
    return {str(r["clave"]).strip(): str(r["valor"]) for r in registros if r.get("clave")}


def actualizar_config_app(gc, clave: str, valor: str, actualizado_por: str) -> None:
    """
    Actualiza el valor de una clave en config_app (o la crea si no existía
    todavía esa fila). Requiere que la hoja 'config_app' ya exista en el
    Google Sheet — si no existe, tira WorksheetNotFound (se atrapa en la UI).
    """
    ws = get_workbook(gc).worksheet("config_app")
    headers = _encabezados(ws)
    cell = ws.find(clave, in_column=_col(headers, "clave"))
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if cell:
        ws.update_cell(cell.row, _col(headers, "valor"), valor)
        if "actualizado_por" in headers:
            ws.update_cell(cell.row, _col(headers, "actualizado_por"), actualizado_por)
        if "timestamp" in headers:
            ws.update_cell(cell.row, _col(headers, "timestamp"), ts)
    else:
        _append_por_encabezado(ws, {
            "clave": clave, "valor": valor,
            "actualizado_por": actualizado_por, "timestamp": ts,
        }, opcionales=("actualizado_por", "timestamp"), headers=headers)
    leer_config_app.clear()


# ─────────────────────────────────────────────
# ESCRITURA
# ─────────────────────────────────────────────
def guardar_permiso(gc, fila: dict) -> None:
    _append_por_encabezado(get_workbook(gc).worksheet("permisos"), fila)
    leer_permisos.clear()


def guardar_compensacion(gc, fila: dict) -> None:
    _append_por_encabezado(get_workbook(gc).worksheet("compensaciones"), fila)
    leer_compensaciones.clear()


def agregar_empleado(gc, legajo: str, nombre: str, sector: str,
                     planta: str, clasificacion: str = "", es_lider: str = "NO") -> list[str]:
    """
    Agrega una persona al padrón. Devuelve las columnas opcionales que no
    se pudieron guardar porque la hoja no las tiene (ej: 'es_lider').
    """
    descartadas = _append_por_encabezado(
        get_workbook(gc).worksheet("padron"),
        {
            "legajo":        legajo.strip(),
            "nombre":        nombre.upper().strip(),
            "sector":        sector.strip(),
            "centro_costo":  "",
            "planta":        planta,
            "activo":        "SI",
            "clasificacion": clasificacion.strip(),
            "es_lider":      es_lider,
        },
        opcionales=("centro_costo", "clasificacion", "es_lider"),
    )
    leer_padron.clear()
    return descartadas


def corregir_permiso(
    gc, id_permiso: str, accion: str, razon: str, usuario: str,
    nuevas_horas: float = None,
) -> bool:
    """
    Corrige un permiso existente. Acciones soportadas:
      - "Anular registro"
      - "Cambiar compensa=SI a NO"
      - "Cambiar compensa=NO a SI"
      - "Corregir horas manualmente" (requiere nuevas_horas)
    Escribe la razón en el campo registrado_por (auditoría).
    Retorna True si encontró y modificó el registro.
    """
    ws = get_workbook(gc).worksheet("permisos")
    headers = _encabezados(ws)
    cell = ws.find(id_permiso, in_column=_col(headers, "id"))
    if not cell:
        return False
    row       = cell.row
    col_comp  = _col(headers, "compensa")
    col_horas = _col(headers, "horas_redondeadas")
    col_audit = _col(headers, "registrado_por")
    ts  = datetime.now().strftime("%d/%m/%Y %H:%M")
    if accion == "Anular registro":
        audit = f"{accion} por {usuario} — {razon} — {ts}"
        ws.update_cell(row, col_comp,  "ANULADO")
        ws.update_cell(row, col_horas, "0")
    elif accion == "Cambiar compensa=SI a NO":
        audit = f"{accion} por {usuario} — {razon} — {ts}"
        ws.update_cell(row, col_comp,  "NO")
        ws.update_cell(row, col_horas, "0")
    elif accion == "Cambiar compensa=NO a SI":
        audit = f"{accion} por {usuario} — {razon} — {ts}"
        ws.update_cell(row, col_comp, "SI")
    elif accion == "Corregir horas manualmente":
        horas_previas = ws.cell(row, col_horas).value
        audit = (
            f"Horas corregidas manualmente: {horas_previas}h → {nuevas_horas}h "
            f"por {usuario} — {razon} — {ts}"
        )
        ws.update_cell(row, col_horas, str(nuevas_horas))
    else:
        return False
    ws.update_cell(row, col_audit, audit)
    leer_permisos.clear()
    return True


def marcar_activo(gc, legajo: str, activo: str) -> bool:
    """Cambia el campo 'activo' (SI/NO) de un empleado, buscándolo por legajo."""
    ws = get_workbook(gc).worksheet("padron")
    headers = _encabezados(ws)
    celdas = ws.findall(str(legajo).strip(), in_column=_col(headers, "legajo"))
    if not celdas:
        return False
    col_activo = _col(headers, "activo")
    for c in celdas:
        ws.update_cell(c.row, col_activo, activo)
    leer_padron.clear()
    return True


def eliminar_empleado_padron(gc, legajo: str) -> bool:
    """Elimina físicamente del padrón (usar solo para bajas definitivas)."""
    ws = get_workbook(gc).worksheet("padron")
    headers = _encabezados(ws)
    celdas = ws.findall(str(legajo).strip(), in_column=_col(headers, "legajo"))
    if not celdas:
        return False
    for c in sorted(celdas, key=lambda x: x.row, reverse=True):
        ws.delete_rows(c.row)
    leer_padron.clear()
    return True


def verificar_compensacion_duplicada(comp_df: pd.DataFrame, legajo: str, fecha) -> bool:
    """Retorna True si ya existe una compensación para ese legajo en esa fecha."""
    if comp_df.empty:
        return False
    return bool((
        (comp_df["legajo"] == legajo) &
        (comp_df["fecha_compensacion"].dt.date == fecha)
    ).any())


def guardar_excepcion_horario(gc, fila: dict) -> None:
    """
    Agrega una excepción de horario nueva a la hoja config_horarios.
    Si se cargaron personas excluidas y la hoja no tiene la columna
    'excluidos_legajos', falla con un mensaje claro en vez de correr
    los valores de columna sin avisar.
    """
    opcionales = () if fila.get("excluidos_legajos") else ("excluidos_legajos",)
    _append_por_encabezado(
        get_workbook(gc).worksheet("config_horarios"), fila, opcionales=opcionales,
    )
    leer_config_horarios.clear()


def desactivar_excepcion_horario(gc, id_excepcion: str) -> bool:
    """
    Marca una excepción como inactiva (activo=NO). No se borra la fila,
    para dejar historial de qué horarios especiales rigieron y cuándo.
    """
    ws = get_workbook(gc).worksheet("config_horarios")
    headers = _encabezados(ws)
    cell = ws.find(id_excepcion, in_column=_col(headers, "id"))
    if not cell:
        return False
    ws.update_cell(cell.row, _col(headers, "activo"), "NO")
    leer_config_horarios.clear()
    return True


def editar_excluidos_horario(gc, id_excepcion: str, legajos_excluidos: list[str]) -> bool:
    """
    Reemplaza la lista completa de legajos excluidos de una excepción de
    horario ya cargada (ej: agregar o sacar gente de "sigue con horario
    normal") sin tener que borrar y recrear todo el horario especial.
    """
    ws = get_workbook(gc).worksheet("config_horarios")
    headers = _encabezados(ws)
    if "excluidos_legajos" not in headers:
        return False  # hoja vieja sin esta columna — hay que agregarla a mano una vez
    cell = ws.find(id_excepcion, in_column=_col(headers, "id"))
    if not cell:
        return False
    ws.update_cell(cell.row, _col(headers, "excluidos_legajos"), ",".join(legajos_excluidos))
    leer_config_horarios.clear()
    return True
