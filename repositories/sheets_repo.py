"""
repositories/sheets_repo.py
─────────────────────────────────────────────────────────────────
Toda la comunicación con Google Sheets vive aquí.
Para migrar a SharePoint/Excel: reemplazar este archivo únicamente.
El resto de la app no conoce Google Sheets.
"""
import pandas as pd
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime

from config import SCOPES, MOTIVO_MAP, LIDERES_SJ


def normalizar_motivo(raw: str) -> str:
    if not raw or pd.isna(raw):
        return "Otro"
    return MOTIVO_MAP.get(str(raw).strip().lower(), str(raw).strip().title())


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
            "descripcion", "activo", "creado_por", "timestamp",
        ])
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return df
    df["desde"]    = pd.to_datetime(df["desde"], errors="coerce").dt.date
    df["hasta"]    = pd.to_datetime(df["hasta"], errors="coerce").dt.date
    df["planta"]   = df["planta"].astype(str).str.strip()
    df["activo"]   = df["activo"].astype(str).str.upper().str.strip()
    df["hora_fin"] = df["hora_fin"].astype(str).str.strip()  # formato "HH:MM"
    return df


@st.cache_data(ttl=30)
def leer_config_app(_gc) -> dict:
    """
    Hoja 'config_app' — configuración general clave/valor editable desde
    el Panel RRHH (hoy: las 2 contraseñas de acceso). Columnas esperadas:
    clave, valor, actualizado_por, timestamp.
    Si la hoja todavía no existe, devuelve {} — la app cae de forma segura
    a los valores por defecto de config.py (PASSWORD_DEFAULT/_RRHH_DEFAULT).
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
    cell = ws.find(clave)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if cell:
        headers = ws.row_values(1)
        ws.update_cell(cell.row, headers.index("valor") + 1, valor)
        if "actualizado_por" in headers:
            ws.update_cell(cell.row, headers.index("actualizado_por") + 1, actualizado_por)
        if "timestamp" in headers:
            ws.update_cell(cell.row, headers.index("timestamp") + 1, ts)
    else:
        ws.append_row([clave, valor, actualizado_por, ts], value_input_option="RAW")
    leer_config_app.clear()


# ─────────────────────────────────────────────
# ESCRITURA
# ─────────────────────────────────────────────
def guardar_permiso(gc, fila: dict) -> None:
    get_workbook(gc).worksheet("permisos").append_row(
        list(fila.values()), value_input_option="RAW"
    )
    leer_permisos.clear()


def guardar_compensacion(gc, fila: dict) -> None:
    get_workbook(gc).worksheet("compensaciones").append_row(
        list(fila.values()), value_input_option="RAW"
    )
    leer_compensaciones.clear()


def agregar_empleado(gc, legajo: str, nombre: str, sector: str,
                     planta: str, clasificacion: str = "", es_lider: str = "NO") -> None:
    get_workbook(gc).worksheet("padron").append_row(
        [legajo.strip(), nombre.upper().strip(), sector.strip(), "",
         planta, "SI", clasificacion.strip(), es_lider],
        value_input_option="RAW"
    )
    leer_padron.clear()


def corregir_permiso(gc, id_permiso: str, accion: str, razon: str, usuario: str) -> bool:
    """
    Anula o cambia compensa de un permiso existente.
    Escribe la razón en el campo registrado_por (auditoría).
    Retorna True si encontró y modificó el registro.
    """
    ws = get_workbook(gc).worksheet("permisos")
    cell = ws.find(id_permiso)
    if not cell:
        return False
    row = cell.row
    ts  = datetime.now().strftime("%d/%m/%Y %H:%M")
    audit = f"{accion} por {usuario} — {razon} — {ts}"
    if accion == "Anular registro":
        ws.update_cell(row, 9,  "ANULADO")
        ws.update_cell(row, 11, "0")
    elif accion == "Cambiar compensa=SI a NO":
        ws.update_cell(row, 9,  "NO")
        ws.update_cell(row, 11, "0")
    elif accion == "Cambiar compensa=NO a SI":
        ws.update_cell(row, 9, "SI")
    ws.update_cell(row, 12, audit)
    leer_permisos.clear()
    return True


def marcar_activo(gc, nombre_empleado: str, activo: str) -> bool:
    """Cambia el campo activo de un empleado (SI/NO)."""
    ws = get_workbook(gc).worksheet("padron")
    celdas = ws.findall(nombre_empleado)
    if not celdas:
        return False
    for c in celdas:
        ws.update_cell(c.row, 5, activo)
    leer_padron.clear()
    return True


def eliminar_empleado_padron(gc, nombre_empleado: str) -> bool:
    """Elimina físicamente del padrón (usar solo para bajas definitivas)."""
    ws = get_workbook(gc).worksheet("padron")
    celdas = ws.findall(nombre_empleado)
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
    """Agrega una excepción de horario nueva a la hoja config_horarios."""
    get_workbook(gc).worksheet("config_horarios").append_row(
        list(fila.values()), value_input_option="RAW"
    )
    leer_config_horarios.clear()


def desactivar_excepcion_horario(gc, id_excepcion: str) -> bool:
    """
    Marca una excepción como inactiva (activo=NO). No se borra la fila,
    para dejar historial de qué horarios especiales rigieron y cuándo.
    """
    ws = get_workbook(gc).worksheet("config_horarios")
    cell = ws.find(id_excepcion)
    if not cell:
        return False
    headers = ws.row_values(1)
    col_activo = headers.index("activo") + 1
    ws.update_cell(cell.row, col_activo, "NO")
    leer_config_horarios.clear()
    return True
