"""
app.py
─────────────────────────────────────────────────────────────────
Punto de entrada de la aplicación. Solo responsabilidad:
1. Autenticación
2. Carga de datos compartidos
3. Enrutamiento entre páginas

Toda la lógica de negocio vive en services/.
Todo acceso a datos vive en repositories/.
Toda la UI vive en ui/.
"""
import streamlit as st
import pandas as pd
from datetime import date

from config import APP_TITLE, APP_ICON, PLANTAS, PASSWORD, PASSWORD_RRHH
from repositories.sheets_repo import (
    conectar, leer_padron, leer_permisos, leer_compensaciones,
)
from ui import guardia, rrhh, analisis, documentacion

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title=APP_TITLE,
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
def check_login():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False
    if not st.session_state.autenticado:
        st.markdown("# 🧵 GILDAN")
        st.title("Control de Permisos — Recursos Humanos")
        st.divider()
        st.write("Ingresá la contraseña para acceder.")
        clave = st.text_input("Contraseña", type="password", placeholder="••••")
        if st.button("Ingresar", use_container_width=True, type="primary"):
            if clave == PASSWORD:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta.")
        st.stop()

check_login()

def check_login_rrhh():
    if "rrhh_autenticado" not in st.session_state:
        st.session_state.rrhh_autenticado = False
    if not st.session_state.rrhh_autenticado:
        st.warning("🔒 Sección restringida — RR.HH.")
        clave = st.text_input("Contraseña RR.HH.", type="password", placeholder="••••", key="pw_rrhh")
        if st.button("Ingresar", key="btn_rrhh"):
            if clave == PASSWORD_RRHH:
                st.session_state.rrhh_autenticado = True
                st.rerun()
            else:
                st.error("Contraseña incorrecta.")
        st.stop()

# ─────────────────────────────────────────────
# CONEXIÓN Y CARGA DE DATOS
# ─────────────────────────────────────────────
try:
    gc = conectar()
except Exception as e:
    st.error(f"No se pudo conectar con Google Sheets: {e}")
    st.stop()

try:
    with st.spinner("Cargando datos..."):
        padron         = leer_padron(gc)
        permisos       = leer_permisos(gc)
        compensaciones = leer_compensaciones(gc)
except Exception as e:
    st.error(f"Error al leer datos: {e}")
    st.stop()

# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🧵 GILDAN")
    st.markdown("### Control de Permisos")
    st.caption(f"Hoy: {date.today().strftime('%d/%m/%Y')}")
    st.divider()

    planta_activa = st.selectbox("📍 Planta", PLANTAS)

    st.divider()
    pagina = st.radio(
        "Sección:",
        ["🔵 Panel Guardia", "🟢 Panel RRHH", "📊 Análisis", "📖 Cómo se calcula"],
        label_visibility="collapsed",
    )
    st.divider()
    if st.button("🔒 Cerrar sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

# ─────────────────────────────────────────────
# DERIVAR CONTEXTO DE PLANTA
# ─────────────────────────────────────────────
KEY_PLANTA = (
    "Fábrica"      if "San Juan" in planta_activa else
    "Casa Central" if "Bs."     in planta_activa else
    "Total"
)
ES_TOTAL = KEY_PLANTA == "Total"
ES_SJ    = KEY_PLANTA == "Fábrica"

# Filtrar DataFrames por planta
def _filtrar(df: pd.DataFrame, col: str = "planta") -> pd.DataFrame:
    if ES_TOTAL or df.empty or col not in df.columns:
        return df.copy()
    return df[df[col] == KEY_PLANTA].copy()

padron_planta   = _filtrar(padron)
permisos_planta = _filtrar(permisos)
comp_planta     = _filtrar(compensaciones)

# Solo activos (para reportes y selectboxes)
padron_activos = (
    padron_planta[padron_planta["activo"].astype(str).str.upper() == "SI"].copy()
    if not padron_planta.empty else padron_planta
)
legajos_activos  = set(padron_activos["legajo"].tolist())
permisos_activos = (
    permisos_planta[permisos_planta["legajo"].isin(legajos_activos)].copy()
    if not permisos_planta.empty else permisos_planta
)
comp_activos = (
    comp_planta[comp_planta["legajo"].isin(legajos_activos)].copy()
    if not comp_planta.empty else comp_planta
)

# Dicts de lookup
padron_dict     = dict(zip(padron_activos["legajo"], padron_activos["nombre"])) if not padron_activos.empty else {}
nombre_a_legajo = dict(zip(padron_activos["nombre"], padron_activos["legajo"])) if not padron_activos.empty else {}
nombres_lista   = sorted(padron_activos["nombre"].tolist()) if not padron_activos.empty else []
sector_dict     = dict(zip(padron_activos["legajo"], padron_activos["sector"])) if not padron_activos.empty else {}
clasif_dict     = dict(zip(padron_activos["legajo"], padron_activos["clasificacion"])) if not padron_activos.empty else {}
planta_dict     = dict(zip(padron_activos["legajo"], padron_activos["planta"])) if not padron_activos.empty else {}

# ─────────────────────────────────────────────
# ENRUTAMIENTO
# ─────────────────────────────────────────────
if pagina == "🔵 Panel Guardia":
    guardia.render(
        gc=gc,
        planta_activa=planta_activa,
        key_planta=KEY_PLANTA,
        es_sj=ES_SJ,
        es_total=ES_TOTAL,
        padron=padron,
        padron_activos=padron_activos,
        permisos_activos=permisos_activos,
        padron_dict=padron_dict,
        nombre_a_legajo=nombre_a_legajo,
        nombres_lista=nombres_lista,
    )

elif pagina == "🟢 Panel RRHH":
    check_login_rrhh()
    rrhh.render(
        gc=gc,
        planta_activa=planta_activa,
        key_planta=KEY_PLANTA,
        padron_planta=padron_planta,
        padron_activos=padron_activos,
        permisos_activos=permisos_activos,
        comp_activos=comp_activos,
        compensaciones=compensaciones,
        nombre_a_legajo=nombre_a_legajo,
        nombres_lista=nombres_lista,
        sector_dict=sector_dict,
        clasif_dict=clasif_dict,
        planta_dict=planta_dict,
    )

elif pagina == "📊 Análisis":
    check_login_rrhh()
    analisis.render(
        planta_activa=planta_activa,
        permisos_planta=permisos_planta,
        permisos_activos=permisos_activos,
        comp_activos=comp_activos,
        sector_dict=sector_dict,
        clasif_dict=clasif_dict,
    )

elif pagina == "📖 Cómo se calcula":
    check_login_rrhh()
    documentacion.render()
