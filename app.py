import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date, time

# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Control de Permisos",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Hora de fin de turno en la fábrica (para calcular S/R)
HORA_FIN_TURNO = time(15, 0)

PASSWORD = "1234"

PLANTAS  = ["Fábrica San Juan", "Casa Central Bs. As."]
AÑOS     = list(range(2025, 2036))   # 2025 → 2035

# ── Motivos canónicos ──────────────────────────────────────────
MOTIVOS_LISTA = [
    "Banco / Cajero",
    "Médico propio",
    "Familiar enfermo",
    "Enfermedad propia",
    "Obra social / ANSES",
    "Juzgado / Tribunales",
    "Registro Civil / DNI",
    "Escribanía",
    "Emicar",
    "Clínica / Sanatorio",
    "Análisis de sangre",
    "Colegio hijo/a",
    "Escuela hijo/a",
    "Cuidado familiar",
    "Trámite personal",
    "Duelo / Fallecimiento familiar",
    "Otro",
]

# Mapeo para normalizar motivos históricos escritos a mano
MOTIVO_MAP = {
    "bco":                       "Banco / Cajero",
    "banco":                     "Banco / Cajero",
    "medico":                    "Médico propio",
    "médico":                    "Médico propio",
    "turno médico":              "Médico propio",
    "turno medico":              "Médico propio",
    "junta medica":              "Médico propio",
    "junta médica":              "Médico propio",
    "medico hijos":              "Familiar enfermo",
    "hija enferma":              "Familiar enfermo",
    "retiro hija + emicar":      "Familiar enfermo",
    "enferma":                   "Enfermedad propia",
    "enfermedad":                "Enfermedad propia",
    "presión alta":              "Enfermedad propia",
    "presion alta":              "Enfermedad propia",
    "obra social":               "Obra social / ANSES",
    "anses":                     "Obra social / ANSES",
    "juzgado":                   "Juzgado / Tribunales",
    "tribunales":                "Juzgado / Tribunales",
    "ufi":                       "Juzgado / Tribunales",
    "declarar estafa":           "Juzgado / Tribunales",
    "registro civil":            "Registro Civil / DNI",
    "dni":                       "Registro Civil / DNI",
    "carnet de conducir":        "Registro Civil / DNI",
    "escribania":                "Escribanía",
    "escribanía":                "Escribanía",
    "emicar":                    "Emicar",
    "sanatorio sj":              "Clínica / Sanatorio",
    "clinica":                   "Clínica / Sanatorio",
    "clínica":                   "Clínica / Sanatorio",
    "analisis":                  "Análisis de sangre",
    "análisis":                  "Análisis de sangre",
    "analisis de sangre":        "Análisis de sangre",
    "ipv":                       "Trámite personal",
    "personal":                  "Trámite personal",
    "1 dia de clases":           "Colegio hijo/a",
    "colegio":                   "Colegio hijo/a",
    "fallecimiento familiar":    "Duelo / Fallecimiento familiar",
}

MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}


def normalizar_motivo(raw: str) -> str:
    """Convierte cualquier motivo crudo al canónico estandarizado."""
    if not raw or pd.isna(raw):
        return "Otro"
    return MOTIVO_MAP.get(str(raw).strip().lower(), str(raw).strip().title())


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
def check_login():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False
    if not st.session_state.autenticado:
        st.title("🏭 Control de Permisos")
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


# ─────────────────────────────────────────────
# REDONDEO DE HORAS
# ─────────────────────────────────────────────
def redondear_horas(minutos: float) -> float:
    """
    < 30 min  → 0h
    30–89 min → 1h
    90–149    → 2h  (fracción >= :30 sube al entero siguiente)
    """
    if minutos is None or pd.isna(minutos) or minutos < 30:
        return 0.0
    parte = int(minutos // 60)
    fraccion = (minutos % 60) / 60
    return float(parte + 1) if fraccion >= 0.5 else float(parte)


def minutos_entre(t_sal: time, t_ent: time) -> float:
    """Minutos entre dos objetos time (mismo día)."""
    ref = date.today()
    delta = datetime.combine(ref, t_ent) - datetime.combine(ref, t_sal)
    return round(delta.seconds / 60, 1)


def fmt_dur(minutos: float) -> str:
    h = int(minutos // 60)
    m = int(minutos % 60)
    if h == 0:
        return f"{m} min"
    return f"{h}h {m:02d}min" if m else f"{h}h"


# ─────────────────────────────────────────────
# CONEXIÓN GOOGLE SHEETS
# ─────────────────────────────────────────────
@st.cache_resource(ttl=3600)
def conectar_sheets():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return gspread.authorize(creds)


@st.cache_resource(ttl=3600)
def get_wb(_gc):
    return _gc.open_by_key(st.secrets["SHEET_ID"])


@st.cache_data(ttl=60)
def leer_padron(_gc):
    ws = get_wb(_gc).worksheet("padron")
    df = pd.DataFrame(ws.get_all_records())
    if not df.empty:
        df["legajo"] = df["legajo"].astype(str).str.strip()
        df["nombre"] = df["nombre"].astype(str).str.strip().str.upper()
        df["planta"] = df["planta"].astype(str).str.strip()
    return df


@st.cache_data(ttl=20)
def leer_permisos(_gc):
    ws = get_wb(_gc).worksheet("permisos")
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return df
    df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce")
    df["minutos_reales"] = pd.to_numeric(df["minutos_reales"], errors="coerce")
    df["horas_redondeadas"] = pd.to_numeric(df["horas_redondeadas"], errors="coerce")
    df["compensa"] = df["compensa"].astype(str).str.upper().str.strip()
    df["legajo"] = df["legajo"].astype(str).str.strip()
    df["planta"] = df["planta"].astype(str).str.strip()
    # Normalizar motivos al leer
    df["motivo"] = df["motivo"].apply(normalizar_motivo)
    return df


@st.cache_data(ttl=20)
def leer_compensaciones(_gc):
    ws = get_wb(_gc).worksheet("compensaciones")
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return df
    df["fecha_compensacion"] = pd.to_datetime(df["fecha_compensacion"], errors="coerce")
    df["horas_compensadas"] = pd.to_numeric(df["horas_compensadas"], errors="coerce")
    df["legajo"] = df["legajo"].astype(str).str.strip()
    df["planta"] = df["planta"].astype(str).str.strip()
    return df


def guardar_permiso(gc, fila: dict):
    get_wb(gc).worksheet("permisos").append_row(list(fila.values()), value_input_option="RAW")
    leer_permisos.clear()


def guardar_compensacion(gc, fila: dict):
    get_wb(gc).worksheet("compensaciones").append_row(list(fila.values()), value_input_option="RAW")
    leer_compensaciones.clear()


def agregar_empleado(gc, legajo: str, nombre: str, sector: str, planta: str):
    get_wb(gc).worksheet("padron").append_row(
        [legajo.strip(), nombre.upper().strip(), sector.strip(), planta, "SI"],
        value_input_option="RAW"
    )
    leer_padron.clear()


def generar_id(prefijo="P"):
    return f"{prefijo}{datetime.now().strftime('%Y%m%d%H%M%S')}"


# ─────────────────────────────────────────────
# CALCULAR SALDOS
# ─────────────────────────────────────────────
def calcular_saldos(permisos_df: pd.DataFrame, comp_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["legajo", "nombre", "debe", "compensado", "saldo"]
    if permisos_df.empty:
        return pd.DataFrame(columns=cols)
    p = permisos_df[permisos_df["compensa"] == "SI"].copy()
    if p.empty:
        return pd.DataFrame(columns=cols)
    debe = (
        p.groupby(["legajo", "nombre"])["horas_redondeadas"]
        .sum().reset_index()
        .rename(columns={"horas_redondeadas": "debe"})
    )
    if not comp_df.empty:
        comp = (
            comp_df.groupby("legajo")["horas_compensadas"]
            .sum().reset_index()
            .rename(columns={"horas_compensadas": "compensado"})
        )
        saldo = debe.merge(comp, on="legajo", how="left")
    else:
        saldo = debe.copy()
        saldo["compensado"] = 0.0
    saldo["compensado"] = saldo["compensado"].fillna(0.0)
    saldo["saldo"] = saldo["debe"] - saldo["compensado"]
    return saldo[saldo["saldo"] > 0].sort_values("saldo", ascending=False).reset_index(drop=True)


# ─────────────────────────────────────────────
# CARGAR DATOS
# ─────────────────────────────────────────────
try:
    gc = conectar_sheets()
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
# SIDEBAR — selección de planta + navegación
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🏭 Control de Permisos")
    st.caption(f"Hoy: {date.today().strftime('%d/%m/%Y')}")
    st.divider()

    planta_activa = st.selectbox("📍 Planta", PLANTAS)

    st.divider()
    pagina = st.radio(
        "Sección:",
        ["🔵 Panel Guardia", "🟢 Panel RRHH", "📊 Análisis"],
        label_visibility="collapsed",
    )
    st.divider()
    if st.button("🔒 Cerrar sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()

# Filtrar datos por planta seleccionada
KEY_PLANTA = "Fábrica" if "San Juan" in planta_activa else "Casa Central"

padron_planta = padron[padron["planta"] == KEY_PLANTA].copy() if not padron.empty else padron
permisos_planta = permisos[permisos["planta"] == KEY_PLANTA].copy() if not permisos.empty else permisos
comp_planta = compensaciones[compensaciones["planta"] == KEY_PLANTA].copy() if not compensaciones.empty else compensaciones

padron_dict     = dict(zip(padron_planta["legajo"], padron_planta["nombre"])) if not padron_planta.empty else {}
nombre_a_legajo = dict(zip(padron_planta["nombre"], padron_planta["legajo"])) if not padron_planta.empty else {}
nombres_lista   = sorted(padron_planta["nombre"].tolist()) if not padron_planta.empty else []


# ═══════════════════════════════════════════════════════════════
# PANEL GUARDIA
# ═══════════════════════════════════════════════════════════════
if pagina == "🔵 Panel Guardia":

    st.title("🏭 Hola San Juan" if "San Juan" in planta_activa else "🏭 Hola Bs. As.")
    st.write("Buscá a la persona por nombre y completá los datos del permiso.")
    st.divider()

    # ── Búsqueda por nombre ──
    st.subheader("¿Quién sale?")
    opciones = ["— Seleccioná un nombre —"] + nombres_lista
    nombre_sel = st.selectbox(
        "Nombre completo",
        opciones,
        help="Escribí las primeras letras para filtrar.",
    )

    legajo_resuelto = ""
    nombre_resuelto = ""

    if nombre_sel and nombre_sel != "— Seleccioná un nombre —":
        legajo_resuelto = nombre_a_legajo.get(nombre_sel, "")
        nombre_resuelto = nombre_sel
        ci1, ci2 = st.columns(2)
        ci1.success(f"✅ **{nombre_resuelto}**")
        ci2.info(f"Legajo: **{legajo_resuelto}**" if legajo_resuelto else "Sin legajo")

    with st.expander("🔢 Buscar por legajo (opcional)"):
        leg_manual = st.text_input("Legajo", placeholder="Ej: 2621")
        if leg_manual.strip() in padron_dict:
            nombre_resuelto = padron_dict[leg_manual.strip()]
            legajo_resuelto = leg_manual.strip()
            st.success(f"✅ {nombre_resuelto}")
        elif leg_manual.strip():
            st.warning("Legajo no encontrado.")

    st.divider()
    st.subheader("Datos del permiso")


    # ── Controles FUERA del form (necesitan reactividad inmediata) ──
    # Motivo + campo "Otro" reactivo
    motivo_sel = st.selectbox("📋 Motivo de salida *", MOTIVOS_LISTA, key="motivo_pre")
    motivo_otro = ""
    if motivo_sel == "Otro":
        motivo_otro = st.text_input(
            "✏️ Especificá el motivo",
            placeholder="Ej: Trámite bancario especial, reunión escuela, etc.",
            max_chars=80,
            key="motivo_otro_pre",
        )

    # Hora de salida y Sin retorno — fuera del form para reactividad
    col_sr1, col_sr2 = st.columns([2, 1])
    with col_sr1:
        hora_salida_pre = st.time_input("🚪 Hora de salida *", value=time(8, 0), step=60, key="hora_sal_pre")
    with col_sr2:
        sin_retorno_pre = st.checkbox("🔴 Sin retorno (no volvió)", value=False, key="sr_pre")

    # Si S/R → hora entrada automática 15:00 y deshabilitada
    valor_entrada = HORA_FIN_TURNO if sin_retorno_pre else time(9, 0)

    with st.form("form_guardia", clear_on_submit=True):

        fecha_permiso = st.date_input("📅 Fecha", value=date.today(), format="DD/MM/YYYY")

        # Leer valores del pre-form
        hora_salida  = hora_salida_pre
        sin_retorno  = sin_retorno_pre
        hora_entrada = st.time_input(
            "🏁 Hora de entrada" + (" (automático — Sin retorno: 15:00)" if sin_retorno else ""),
            value=valor_entrada,
            step=60,
            disabled=sin_retorno,
        )


        compensa = st.radio(
            "💰 ¿Va a compensar las horas? *",
            ["SI", "NO"],
            horizontal=True,
            help="SI = se queda horas extra otro día. NO = no se descuenta.",
        )
        registrado_por = st.text_input("👮 Tu nombre *", placeholder="Ej: García Juan")

        # ── PREVISUALIZACIÓN ──
        # S/R: se calcula contra fin de turno (15:00)
        # Normal: diferencia entre salida y entrada
        if sin_retorno:
            if hora_salida < HORA_FIN_TURNO:
                mins_prev = minutos_entre(hora_salida, HORA_FIN_TURNO)
                hrs_prev  = redondear_horas(mins_prev)
                st.info(
                    f"🔴 Sin retorno — salió a las {hora_salida.strftime('%H:%M')}, "
                    f"fin de turno 15:00 → **{fmt_dur(mins_prev)} real** "
                    f"→ {'**' + str(int(hrs_prev)) + 'h a compensar**' if compensa == 'SI' else 'no compensa'}"
                )
            else:
                st.warning("La hora de salida es posterior al fin de turno (15:00). Verificá.")
        elif hora_entrada > hora_salida:
            mins_prev = minutos_entre(hora_salida, hora_entrada)
            hrs_prev  = redondear_horas(mins_prev)
            st.info(
                f"⏱ Tiempo real fuera: **{fmt_dur(mins_prev)}** "
                f"→ Horas a compensar: **{int(hrs_prev)}h**"
            )

        submitted = st.form_submit_button(
            "💾 GUARDAR REGISTRO", use_container_width=True, type="primary"
        )

        if submitted:
            motivo_final = motivo_otro.strip() if motivo_sel == "Otro" and motivo_otro.strip() else motivo_sel
            errores = []
            if not nombre_resuelto:
                errores.append("Seleccioná o buscá a la persona primero.")
            if not registrado_por.strip():
                errores.append("Falta tu nombre.")
            if sin_retorno and hora_salida >= HORA_FIN_TURNO:
                errores.append("Hora de salida posterior al fin de turno (15:00). Verificá.")
            if not sin_retorno and hora_entrada <= hora_salida:
                errores.append("La hora de entrada debe ser posterior a la salida.")

            if errores:
                for e in errores:
                    st.error(f"❌ {e}")
            else:
                if sin_retorno:
                    # Calcular contra fin de turno
                    mins_r = minutos_entre(hora_salida, HORA_FIN_TURNO)
                    hrs_r  = redondear_horas(mins_r) if compensa == "SI" else 0.0
                    ent_str = "S/R"
                else:
                    mins_r = minutos_entre(hora_salida, hora_entrada)
                    hrs_r  = redondear_horas(mins_r)
                    ent_str = hora_entrada.strftime("%H:%M")

                try:
                    guardar_permiso(gc, {
                        "id":               generar_id("P"),
                        "fecha":            fecha_permiso.strftime("%Y-%m-%d"),
                        "legajo":           legajo_resuelto,
                        "nombre":           nombre_resuelto,
                        "hora_salida":      hora_salida.strftime("%H:%M"),
                        "hora_entrada":     ent_str,
                        "sin_retorno":      "SI" if sin_retorno else "NO",
                        "motivo":           motivo_final,
                        "compensa":         compensa,
                        "minutos_reales":   round(mins_r, 1),
                        "horas_redondeadas": hrs_r,
                        "registrado_por":   registrado_por.strip(),
                        "planta":           KEY_PLANTA,
                        "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success(f"✅ Registro guardado — {nombre_resuelto}")
                    st.info(
                        f"Tiempo fuera: {fmt_dur(mins_r)} → "
                        f"**{int(hrs_r)}h a compensar**"
                        if compensa == "SI" else
                        f"Tiempo fuera: {fmt_dur(mins_r)} — no compensa"
                    )
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")

    # Registros del día
    st.divider()
    st.subheader("Registros de hoy")
    if not permisos_planta.empty:
        hoy = permisos_planta[permisos_planta["fecha"].dt.date == date.today()]
        if hoy.empty:
            st.caption("Aún no hay registros hoy.")
        else:
            hs = hoy[["nombre", "hora_salida", "hora_entrada", "sin_retorno", "motivo", "compensa", "horas_redondeadas"]].copy()
            hs.columns = ["Nombre", "Salida", "Entrada", "S/R", "Motivo", "Compensa", "Hs."]
            st.dataframe(hs, use_container_width=True, hide_index=True)
    else:
        st.caption("No hay registros aún.")

    # Agregar empleado
    st.divider()
    with st.expander("➕ Agregar empleado que no está en la lista"):
        st.caption(
            "Usá esto solo si la persona no aparece en el listado. "
            "El nombre debe ser completo — no puede haber dos personas con el mismo nombre."
        )
        with st.form("form_nuevo"):
            cn1, cn2 = st.columns(2)
            with cn1:
                nvo_leg = st.text_input("Legajo (opcional)", placeholder="Ej: 3050")
            with cn2:
                nvo_nom = st.text_input("Apellido y Nombre *", placeholder="Ej: GOMEZ, CARLOS ALBERTO")
            nvo_sec = st.text_input("Sector (opcional)")
            if st.form_submit_button("Agregar al padrón", use_container_width=True):
                nom_clean = nvo_nom.strip().upper()
                err = []
                if not nom_clean:
                    err.append("El nombre es obligatorio.")
                if nom_clean in nombre_a_legajo:
                    err.append(f"Ya existe '{nom_clean}'. Agregá segundo nombre o apellido.")
                if err:
                    for e in err:
                        st.error(f"❌ {e}")
                else:
                    try:
                        agregar_empleado(gc, nvo_leg.strip(), nom_clean, nvo_sec.strip(), KEY_PLANTA)
                        st.success(f"✅ {nom_clean} agregado. Recargá la página.")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")


# ═══════════════════════════════════════════════════════════════
# PANEL RRHH
# ═══════════════════════════════════════════════════════════════
elif pagina == "🟢 Panel RRHH":

    st.title("🟢 Hola, RRHH — San Juan" if "San Juan" in planta_activa else "🟢 Hola, RRHH — Bs. As.")
    st.write("Seguimiento de permisos y compensaciones.")
    st.divider()

    col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
    with col_f1:
        año_sel = st.selectbox("Año", AÑOS, index=AÑOS.index(min(date.today().year, max(AÑOS))))
    with col_f2:
        mes_sel = st.selectbox(
            "Mes", list(MESES.keys()),
            index=datetime.now().month - 1,
            format_func=lambda x: MESES[x],
        )
    with col_f3:
        modo = st.radio("Vista:", ["Solo este mes", "Saldo acumulado total"], horizontal=True)

    if permisos_planta.empty:
        st.warning("No hay permisos cargados para esta planta.")
        st.stop()

    if modo == "Solo este mes":
        p_f = permisos_planta[
            (permisos_planta["fecha"].dt.year == año_sel) &
            (permisos_planta["fecha"].dt.month == mes_sel)
        ].copy()
        c_f = comp_planta[
            (comp_planta["fecha_compensacion"].dt.year == año_sel) &
            (comp_planta["fecha_compensacion"].dt.month == mes_sel)
        ].copy() if not comp_planta.empty else comp_planta.copy()
    else:
        p_f = permisos_planta.copy()
        c_f = comp_planta.copy()

    saldos = calcular_saldos(p_f, c_f)
    comp_total = c_f["horas_compensadas"].sum() if not c_f.empty and "horas_compensadas" in c_f.columns else 0

    # Métricas
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("📋 Permisos registrados", len(p_f))
    col_m2.metric("👥 Personas con deuda", len(saldos))
    col_m3.metric("⏳ Horas pendientes", f"{saldos['saldo'].sum():.0f}h" if not saldos.empty else "0h")
    col_m4.metric("✅ Horas compensadas", f"{comp_total:.0f}h")

    # ── Reporte para gerencia ──
    st.divider()
    st.subheader(f"📄 Reporte para Gerencia — {MESES[mes_sel]} {año_sel}")
    st.caption(
        "Quiénes deben compensar horas y cuántas. "
        "Sacá captura y enviá a gerencia de planta."
    )

    if saldos.empty:
        st.success(f"✅ Ningún empleado tiene horas pendientes en {MESES[mes_sel]} {año_sel}.")
    else:
        reporte = saldos[["nombre", "debe", "compensado", "saldo"]].copy()
        reporte["debe"]      = reporte["debe"].apply(lambda x: f"{x:.0f}h")
        reporte["compensado"] = reporte["compensado"].apply(lambda x: f"{x:.0f}h")
        reporte["saldo"]     = saldos["saldo"].apply(lambda x: f"{x:.0f}h")
        reporte.columns      = ["Apellido y Nombre", "Debe", "Ya compensó", "Saldo pendiente"]
        reporte.index        = range(1, len(reporte) + 1)
        st.dataframe(reporte, use_container_width=True, height=min(500, 45 + len(reporte) * 35))
        st.caption(f"**{len(reporte)} personas** — **{saldos['saldo'].sum():.0f}h** pendientes en total.")

    # ── Registrar compensación ──
    st.divider()
    st.subheader("✏️ Registrar compensación")
    st.caption("Cuando alguien se queda horas extra para compensar.")

    with st.form("form_comp"):
        nombre_comp_sel = st.selectbox(
            "Empleado/a",
            ["— Seleccioná un nombre —"] + nombres_lista,
        )
        nom_c = nombre_comp_sel if nombre_comp_sel != "— Seleccioná un nombre —" else ""
        leg_c = nombre_a_legajo.get(nom_c, "") if nom_c else ""

        if nom_c and not saldos.empty:
            saldo_actual = saldos[saldos["nombre"] == nom_c]["saldo"].sum()
            if saldo_actual > 0:
                st.info(f"Saldo pendiente de **{nom_c}**: **{saldo_actual:.0f}h**")
            else:
                st.success(f"**{nom_c}** no tiene horas pendientes en el período actual.")

        cc3, cc4 = st.columns(2)
        with cc3:
            fecha_comp = st.date_input("Fecha en que compensó", value=date.today(), format="DD/MM/YYYY")
        with cc4:
            hs_comp = st.number_input("Horas compensadas", min_value=0.5, max_value=8.0, value=1.0, step=0.5)

        obs     = st.text_input("Observación (opcional)", placeholder="Ej: se quedó al final del turno")
        registra = st.text_input("Tu nombre *")

        if st.form_submit_button("✅ REGISTRAR COMPENSACIÓN", use_container_width=True, type="primary"):
            if not nom_c:
                st.error("❌ Seleccioná a la persona.")
            elif not registra.strip():
                st.error("❌ Falta tu nombre.")
            else:
                try:
                    guardar_compensacion(gc, {
                        "id":                generar_id("C"),
                        "fecha_compensacion": fecha_comp.strftime("%Y-%m-%d"),
                        "legajo":            leg_c,
                        "nombre":            nom_c,
                        "horas_compensadas": hs_comp,
                        "observacion":       obs,
                        "registrado_por":    registra.strip(),
                        "planta":            KEY_PLANTA,
                        "timestamp":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success(f"✅ {nom_c} — {hs_comp}h el {fecha_comp.strftime('%d/%m/%Y')}")
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    # Detalle del período
    st.divider()
    st.subheader("🔍 Detalle de permisos del período")
    if not p_f.empty:
        det = p_f[[
            "fecha", "legajo", "nombre", "hora_salida", "hora_entrada",
            "sin_retorno", "motivo", "compensa", "horas_redondeadas"
        ]].copy()
        det["fecha"] = det["fecha"].dt.strftime("%d/%m/%Y")
        det.columns = ["Fecha", "Legajo", "Nombre", "Salida", "Entrada", "S/R", "Motivo", "Compensa", "Hs."]
        st.dataframe(det, use_container_width=True, hide_index=True)
    else:
        st.info("No hay permisos en este período.")


# ═══════════════════════════════════════════════════════════════
# ANÁLISIS
# ═══════════════════════════════════════════════════════════════
elif pagina == "📊 Análisis":

    st.title(f"📊 Análisis de Permisos — {planta_activa}")
    st.caption("Datos históricos completos.")

    if permisos_planta.empty:
        st.warning("No hay datos para analizar en esta planta.")
        st.stop()

    df = permisos_planta.copy()
    df["año"]       = df["fecha"].dt.year
    df["mes"]       = df["fecha"].dt.month
    df["año_semana"] = df["fecha"].dt.strftime("%Y-S%V")

    años_disp = sorted(df["año"].dropna().unique().tolist())
    año_a = st.multiselect("Filtrar por año", años_disp, default=años_disp)
    df = df[df["año"].isin(año_a)]

    if df.empty:
        st.info("No hay datos para ese período.")
        st.stop()

    st.divider()

    # ── 1. Permisos por semana ──
    st.subheader("Permisos por semana")
    sem = df.groupby("año_semana").size().reset_index(name="cantidad")
    prom = sem["cantidad"].mean()
    max_sem = sem["cantidad"].max()

    # Color especial para la semana con más permisos
    colores_sem = ["#C0392B" if v == max_sem else "#1B4F9B" for v in sem["cantidad"]]

    fig1 = go.Figure(go.Bar(
        x=sem["año_semana"],
        y=sem["cantidad"],
        text=sem["cantidad"],
        textposition="outside",
        marker_color=colores_sem,
        hovertemplate="%{x}: %{y} permisos<extra></extra>",
    ))
    fig1.add_hline(
        y=prom, line_dash="dash", line_color="#7F8C8D",
        annotation_text=f"Promedio: {prom:.1f}",
        annotation_position="top left",
    )
    fig1.update_layout(
        plot_bgcolor="white", height=280,
        margin=dict(t=30, b=10, l=10, r=10),
        xaxis_title="", yaxis_title="Permisos",
        showlegend=False,
    )
    st.plotly_chart(fig1, use_container_width=True)
    st.caption(
        f"Promedio semanal: **{prom:.1f} permisos** — "
        f"La semana con más permisos fue **{sem.loc[sem['cantidad'].idxmax(), 'año_semana']}** "
        f"({max_sem} permisos, marcada en rojo)."
    )

    st.divider()

    # ── 1b. Permisos por mes ──
    st.subheader("Permisos por mes")
    df["mes_label"] = df["fecha"].dt.strftime("%Y-%m")
    mes_g    = df.groupby("mes_label").size().reset_index(name="cantidad")
    prom_mes = mes_g["cantidad"].mean()
    max_mes  = mes_g["cantidad"].max()
    cols_mes = ["#C0392B" if v == max_mes else "#2471D5" for v in mes_g["cantidad"]]

    fig1b = go.Figure(go.Bar(
        x=mes_g["mes_label"], y=mes_g["cantidad"],
        text=mes_g["cantidad"], textposition="outside",
        marker_color=cols_mes,
        hovertemplate="%{x}: %{y} permisos<extra></extra>",
    ))
    fig1b.add_hline(
        y=prom_mes, line_dash="dash", line_color="#7F8C8D",
        annotation_text=f"Promedio: {prom_mes:.1f}",
        annotation_position="top left",
    )
    fig1b.update_layout(
        plot_bgcolor="white", height=270,
        margin=dict(t=30, b=10, l=10, r=10),
        xaxis_title="", yaxis_title="Permisos", showlegend=False,
    )
    st.plotly_chart(fig1b, use_container_width=True)
    mes_pico = mes_g.loc[mes_g["cantidad"].idxmax(), "mes_label"]
    st.caption(
        f"Promedio: **{prom_mes:.1f} permisos/mes** — "
        f"Mes pico: **{mes_pico}** con {max_mes} permisos 🔴"
    )

    st.divider()

    # ── 2. Pareto de motivos ──
    st.subheader("¿Por qué salen? — Motivos principales (Pareto 80%)")
    mc = df["motivo"].value_counts().reset_index()
    mc.columns = ["Motivo", "Cantidad"]
    mc["acum_pct"] = (mc["Cantidad"].cumsum() / mc["Cantidad"].sum() * 100)
    pareto = mc[mc["acum_pct"].shift(1, fill_value=0) < 80].head(8)

    max_mot = pareto["Cantidad"].max()
    colores_mot = ["#C0392B" if v == max_mot else "#2471D5" for v in pareto["Cantidad"]]

    fig2 = go.Figure(go.Bar(
        x=pareto["Cantidad"],
        y=pareto["Motivo"],
        orientation="h",
        text=pareto["Cantidad"],
        textposition="outside",
        marker_color=colores_mot,
        hovertemplate="%{y}: %{x} veces<extra></extra>",
    ))
    fig2.update_layout(
        plot_bgcolor="white", height=max(250, len(pareto) * 40),
        margin=dict(t=10, b=10, l=10, r=60),
        xaxis_title="Cantidad", yaxis_title="",
        yaxis={"categoryorder": "total ascending"},
        showlegend=False,
    )
    st.plotly_chart(fig2, use_container_width=True)
    if not pareto.empty:
        top1 = pareto.iloc[-1]
        st.caption(
            f"**{top1['Motivo']}** es el motivo más frecuente ({top1['Cantidad']} veces). "
            f"Estos {len(pareto)} motivos explican el 80% de los permisos."
        )

    st.divider()

    # ── 3. Duración corregida ──
    st.subheader("¿Cuánto tiempo suelen estar fuera?")

    df_dur = df[df["minutos_reales"].notna() & (df["minutos_reales"] > 0)].copy()

    if not df_dur.empty:
        def cat_dur(m):
            if m < 30:    return "< 30 min"
            elif m < 60:  return "30 – 60 min"
            elif m < 90:  return "1h – 1h 30min"
            elif m < 120: return "1h 30min – 2h"
            else:         return "Más de 2h"

        orden = ["< 30 min", "30 – 60 min", "1h – 1h 30min", "1h 30min – 2h", "Más de 2h"]
        df_dur["rango"] = df_dur["minutos_reales"].apply(cat_dur)
        c = (
            df_dur["rango"]
            .value_counts()
            .reindex(orden, fill_value=0)
            .reset_index()
        )
        c.columns = ["Rango", "Cantidad"]
        c["Pct"] = (c["Cantidad"] / c["Cantidad"].sum() * 100).round(1)

        max_dur = c["Cantidad"].max()
        colores_dur = ["#C0392B" if v == max_dur else "#1B4F9B" for v in c["Cantidad"]]

        cd1, cd2 = st.columns([2, 1])
        with cd1:
            fig3 = go.Figure(go.Bar(
                x=c["Rango"],
                y=c["Cantidad"],
                text=c["Pct"].apply(lambda x: f"{x}%"),
                textposition="outside",
                marker_color=colores_dur,
                hovertemplate="%{x}: %{y} permisos (%{text})<extra></extra>",
            ))
            fig3.update_layout(
                plot_bgcolor="white", height=270,
                margin=dict(t=10, b=10, l=10, r=10),
                xaxis_title="", yaxis_title="Permisos",
                showlegend=False,
            )
            st.plotly_chart(fig3, use_container_width=True)
        with cd2:
            st.dataframe(
                c[["Rango", "Cantidad", "Pct"]].rename(columns={"Pct": "%"}),
                use_container_width=True,
                hide_index=True,
            )
            mayor = c.loc[c["Cantidad"].idxmax()]
            prom_min = df_dur["minutos_reales"].mean()
            st.caption(
                f"Rango más frecuente: **{mayor['Rango']}** ({mayor['Pct']}%).\n\n"
                f"Promedio real de ausencia: **{fmt_dur(prom_min)}**."
            )
    else:
        st.info("No hay datos de duración suficientes para este período.")

    st.divider()

    # ── 4. ¿Compensan? Intención vs Realidad ──
    st.subheader("Compensación: intención vs. realidad")
    st.caption(
        "Izquierda: cuántos eligen compensar al salir. "
        "Derecha: de los que dijeron SI, cuántos realmente lo hicieron."
    )

    ratio = df["compensa"].value_counts().reset_index()
    ratio.columns = ["Compensa", "Cantidad"]
    total_r = ratio["Cantidad"].sum()

    colores_ratio = {"SI": "#1A7A4A", "NO": "#C0392B"}

    fig4 = go.Figure(go.Pie(
        labels=ratio["Compensa"],
        values=ratio["Cantidad"],
        hole=0.5,
        marker_colors=[colores_ratio.get(v, "#95A5A6") for v in ratio["Compensa"]],
        textinfo="label+percent",
        hovertemplate="%{label}: %{value} permisos (%{percent})<extra></extra>",
    ))
    fig4.update_layout(
        height=260, margin=dict(t=30, b=10, l=10, r=10),
        showlegend=False, title_text="Intención al salir",
    )

    # Segundo gráfico: de los que dijeron SI, cuántos tienen al menos 1 compensación registrada
    dijeron_si = df[df["compensa"] == "SI"]["legajo"].unique()
    n_dijeron_si = len(dijeron_si)

    if n_dijeron_si > 0 and not comp_planta.empty:
        compensaron = comp_planta[comp_planta["legajo"].isin(dijeron_si)]["legajo"].unique()
        n_compensaron    = len(compensaron)
        n_no_compensaron = n_dijeron_si - n_compensaron

        labels_r = ["Compensaron", "No compensaron"]
        values_r = [n_compensaron, n_no_compensaron]
        cols_r   = ["#1A7A4A", "#E67E22"]

        fig5 = go.Figure(go.Pie(
            labels=labels_r, values=values_r, hole=0.5,
            marker_colors=cols_r,
            textinfo="label+percent",
            hovertemplate="%{label}: %{value} personas (%{percent})<extra></extra>",
        ))
        fig5.update_layout(
            height=260, margin=dict(t=30, b=10, l=10, r=10),
            showlegend=False, title_text="Realidad (de los que dijeron SI)",
        )

        cr1, cr2 = st.columns(2)
        with cr1:
            st.plotly_chart(fig4, use_container_width=True)
            for _, row in ratio.iterrows():
                pct   = row["Cantidad"] / total_r * 100
                icono = "✅" if row["Compensa"] == "SI" else "❌"
                st.metric(f"{icono} {row['Compensa']}", f"{row['Cantidad']} permisos", f"{pct:.1f}%")
        with cr2:
            st.plotly_chart(fig5, use_container_width=True)
            st.metric("✅ Compensaron efectivamente", f"{n_compensaron} personas",
                      f"{n_compensaron/n_dijeron_si*100:.1f}% de los que dijeron SI")
            st.metric("⚠️ Dijeron SI pero no compensaron aún", f"{n_no_compensaron} personas",
                      f"{n_no_compensaron/n_dijeron_si*100:.1f}% de los que dijeron SI")
    else:
        st.plotly_chart(fig4, use_container_width=True)
        st.info("Aún no hay compensaciones registradas para cruzar con los permisos.")

    st.divider()
    st.caption("Análisis automático basado en los datos de Google Sheets.")

    # ── 5. (OPCIONAL) Tiempo no productivo acumulado por mes ──
    st.divider()
    st.subheader("⏳ Tiempo no productivo acumulado")
    st.caption(
        "Horas que se deben compensar pero todavía no se recuperaron, agrupadas por mes de origen. "
        "Cada hora pendiente es tiempo de producción no recuperado."
    )

    if not permisos_planta.empty:
        # Horas comprometidas por mes (solo las que eligen compensar)
        # Usamos permisos_planta completo (sin filtro de año) para el histórico total
        p_comp = permisos_planta[permisos_planta["compensa"] == "SI"].copy()
        p_comp["mes_label"] = p_comp["fecha"].dt.strftime("%Y-%m")
        hs_por_mes = p_comp.groupby("mes_label")["horas_redondeadas"].sum().reset_index()
        hs_por_mes.columns = ["Mes", "Horas comprometidas"]

        # Total compensado hasta hoy
        total_comp = compensaciones[compensaciones["planta"] == KEY_PLANTA]["horas_compensadas"].sum()             if not compensaciones.empty else 0
        total_comprometido = hs_por_mes["Horas comprometidas"].sum()
        pendiente_total = max(0, total_comprometido - total_comp)

        # Mostrar métricas clave
        tp1, tp2, tp3 = st.columns(3)
        tp1.metric("Horas comprometidas (total)", f"{total_comprometido:.0f}h")
        tp2.metric("Horas ya recuperadas", f"{total_comp:.0f}h")
        tp3.metric("⚠️ Horas aún sin recuperar", f"{pendiente_total:.0f}h",
                   delta=f"-{pendiente_total:.0f}h vs producción plena", delta_color="inverse")

        # Gráfico de barras por mes
        max_np = hs_por_mes["Horas comprometidas"].max()
        cols_np = ["#C0392B" if v == max_np else "#E67E22" for v in hs_por_mes["Horas comprometidas"]]

        fig_np = go.Figure(go.Bar(
            x=hs_por_mes["Mes"],
            y=hs_por_mes["Horas comprometidas"],
            text=hs_por_mes["Horas comprometidas"].apply(lambda x: f"{x:.0f}h"),
            textposition="outside",
            marker_color=cols_np,
            hovertemplate="%{x}: %{y}h comprometidas<extra></extra>",
        ))
        fig_np.update_layout(
            plot_bgcolor="white", height=270,
            margin=dict(t=30, b=10, l=10, r=10),
            xaxis_title="", yaxis_title="Horas", showlegend=False,
            title_text="Horas comprometidas a compensar por mes de origen",
        )
        st.plotly_chart(fig_np, use_container_width=True)
        st.caption(
            f"De las **{total_comprometido:.0f}h** totales comprometidas, "
            f"se recuperaron **{total_comp:.0f}h** ({total_comp/total_comprometido*100:.1f}% si hubiera datos). "
            f"Quedan **{pendiente_total:.0f}h** sin recuperar."
            if total_comprometido > 0 else "Sin datos suficientes."
        )