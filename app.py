import streamlit as st
import pandas as pd
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

HORA_FIN_TURNO = time(15, 0)   # fin de turno fábrica
PASSWORD = "1234"
PLANTAS  = ["Fábrica San Juan", "Casa Central Bs. As."]
AÑOS     = list(range(2025, 2036))   # 2025 → 2035

MOTIVOS_LISTA = [
    "Banco / Cajero",
    "Médico propio",
    "Familiar enfermo",
    "Enfermedad propia",
    "Obra social / ANSES",
    "Juzgado / Tribunales",
    "Registro Civil / DNI",
    "Escribanía",
    "Emicar / Clínica",
    "Escuela hijo/a",
    "Cuidado familiar",
    "Análisis de sangre",
    "Trámite personal",
    "Estudio / Clases",
    "Duelo / Fallecimiento familiar",
    "Otro",
]

MOTIVO_MAP = {
    "bco":                    "Banco / Cajero",
    "banco":                  "Banco / Cajero",
    "medico":                 "Médico propio",
    "médico":                 "Médico propio",
    "turno médico":           "Médico propio",
    "turno medico":           "Médico propio",
    "junta medica":           "Médico propio",
    "junta médica":           "Médico propio",
    "medico hijos":           "Familiar enfermo",
    "hija enferma":           "Familiar enfermo",
    "retiro hija + emicar":   "Familiar enfermo",
    "enferma":                "Enfermedad propia",
    "enfermedad":             "Enfermedad propia",
    "presión alta":           "Enfermedad propia",
    "presion alta":           "Enfermedad propia",
    "obra social":            "Obra social / ANSES",
    "anses":                  "Obra social / ANSES",
    "juzgado":                "Juzgado / Tribunales",
    "tribunales":             "Juzgado / Tribunales",
    "ufi":                    "Juzgado / Tribunales",
    "declarar estafa":        "Juzgado / Tribunales",
    "registro civil":         "Registro Civil / DNI",
    "dni":                    "Registro Civil / DNI",
    "carnet de conducir":     "Registro Civil / DNI",
    "escribania":             "Escribanía",
    "escribanía":             "Escribanía",
    "emicar":                 "Emicar / Clínica",
    "sanatorio sj":           "Emicar / Clínica",
    "analisis":               "Análisis de sangre",
    "análisis":               "Análisis de sangre",
    "ipv":                    "Trámite personal",
    "personal":               "Trámite personal",
    "1 dia de clases":        "Estudio / Clases",
    "fallecimiento familiar": "Duelo / Fallecimiento familiar",
}

MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

COLORES = {
    "azul":        "#1B4F9B",
    "azul_claro":  "#2471D5",
    "rojo":        "#C0392B",
    "verde":       "#1A7A4A",
    "gris":        "#7F8C8D",
    "naranja":     "#E67E22",
    "violeta":     "#6C3483",
}


def normalizar_motivo(raw: str) -> str:
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
# REDONDEO
# ─────────────────────────────────────────────
def redondear_horas(minutos: float) -> float:
    """< 30 min → 0h | 30–89 → 1h | 90–149 → 2h | etc."""
    if minutos is None or pd.isna(minutos) or minutos < 30:
        return 0.0
    parte = int(minutos // 60)
    fraccion = (minutos % 60) / 60
    return float(parte + 1) if fraccion >= 0.5 else float(parte)


def minutos_entre(t_sal: time, t_ent: time) -> float:
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
# GOOGLE SHEETS
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
    df = pd.DataFrame(get_wb(_gc).worksheet("padron").get_all_records())
    if not df.empty:
        df["legajo"] = df["legajo"].astype(str).str.strip()
        df["nombre"] = df["nombre"].astype(str).str.strip().str.upper()
        df["planta"] = df["planta"].astype(str).str.strip()
    return df


@st.cache_data(ttl=20)
def leer_permisos(_gc):
    df = pd.DataFrame(get_wb(_gc).worksheet("permisos").get_all_records())
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
def leer_compensaciones(_gc):
    df = pd.DataFrame(get_wb(_gc).worksheet("compensaciones").get_all_records())
    if df.empty:
        return df
    df["fecha_compensacion"] = pd.to_datetime(df["fecha_compensacion"], errors="coerce")
    df["horas_compensadas"]  = pd.to_numeric(df["horas_compensadas"], errors="coerce")
    df["legajo"]             = df["legajo"].astype(str).str.strip()
    df["planta"]             = df["planta"].astype(str).str.strip()
    return df


def guardar_permiso(gc, fila: dict):
    get_wb(gc).worksheet("permisos").append_row(list(fila.values()), value_input_option="RAW")
    leer_permisos.clear()


def guardar_compensacion(gc, fila: dict):
    get_wb(gc).worksheet("compensaciones").append_row(list(fila.values()), value_input_option="RAW")
    leer_compensaciones.clear()


def agregar_empleado(gc, legajo, nombre, sector, planta):
    get_wb(gc).worksheet("padron").append_row(
        [legajo.strip(), nombre.upper().strip(), sector.strip(), planta, "SI"],
        value_input_option="RAW"
    )
    leer_padron.clear()


def generar_id(prefijo="P"):
    return f"{prefijo}{datetime.now().strftime('%Y%m%d%H%M%S')}"


# ─────────────────────────────────────────────
# CALCULAR SALDOS — LÓGICA ACUMULATIVA CORRECTA
#
# REGLA: El saldo es SIEMPRE acumulativo sobre TODO el histórico
# de la planta. No se puede filtrar permisos por mes y compensaciones
# por mes por separado — eso produce saldos incorrectos porque una
# persona puede compensar en mayo horas de abril.
#
# El parámetro `hasta_fecha` permite calcular el saldo acumulado
# hasta un momento dado (útil para el reporte mensual: "¿cuánto
# debía esta persona al cierre de abril?").
# ─────────────────────────────────────────────
def calcular_saldos(
    permisos_df: pd.DataFrame,
    comp_df: pd.DataFrame,
    hasta_fecha=None,
) -> pd.DataFrame:
    """
    Calcula saldo acumulado por persona.
    Si `hasta_fecha` (date), usa permisos y compensaciones hasta esa fecha inclusive.
    Retorna solo personas con saldo > 0.
    """
    cols = ["legajo", "nombre", "debe", "compensado", "saldo"]
    if permisos_df.empty:
        return pd.DataFrame(columns=cols)

    p = permisos_df[permisos_df["compensa"] == "SI"].copy()
    c = comp_df.copy() if not comp_df.empty else pd.DataFrame()

    if hasta_fecha is not None:
        p = p[p["fecha"].dt.date <= hasta_fecha]
        if not c.empty:
            c = c[c["fecha_compensacion"].dt.date <= hasta_fecha]

    if p.empty:
        return pd.DataFrame(columns=cols)

    debe = (
        p.groupby(["legajo", "nombre"])["horas_redondeadas"]
        .sum().reset_index()
        .rename(columns={"horas_redondeadas": "debe"})
    )

    if not c.empty and "horas_compensadas" in c.columns:
        comp_sum = (
            c.groupby("legajo")["horas_compensadas"]
            .sum().reset_index()
            .rename(columns={"horas_compensadas": "compensado"})
        )
        saldo = debe.merge(comp_sum, on="legajo", how="left")
    else:
        saldo = debe.copy()
        saldo["compensado"] = 0.0

    saldo["compensado"] = saldo["compensado"].fillna(0.0)
    saldo["saldo"] = (saldo["debe"] - saldo["compensado"]).round(1)
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
# SIDEBAR
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

# Filtrar por planta
KEY_PLANTA      = "Fábrica" if "San Juan" in planta_activa else "Casa Central"
padron_p        = padron[padron["planta"] == KEY_PLANTA].copy() if not padron.empty else padron
permisos_p      = permisos[permisos["planta"] == KEY_PLANTA].copy() if not permisos.empty else permisos
comp_p          = compensaciones[compensaciones["planta"] == KEY_PLANTA].copy() if not compensaciones.empty else compensaciones

padron_dict     = dict(zip(padron_p["legajo"], padron_p["nombre"])) if not padron_p.empty else {}
nombre_a_legajo = dict(zip(padron_p["nombre"], padron_p["legajo"])) if not padron_p.empty else {}
nombres_lista   = sorted(padron_p["nombre"].tolist()) if not padron_p.empty else []


# ═══════════════════════════════════════════════════════════════
# PANEL GUARDIA
# ═══════════════════════════════════════════════════════════════
if pagina == "🔵 Panel Guardia":

    st.title(f"👋 ¡Hola, Guardia! — {planta_activa}")
    st.write("Buscá a la persona por nombre y completá los datos del permiso.")
    st.divider()

    st.subheader("¿Quién sale?")
    nombre_sel = st.selectbox(
        "Nombre completo",
        ["— Seleccioná un nombre —"] + nombres_lista,
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

    with st.form("form_guardia", clear_on_submit=True):
        col3, col4 = st.columns(2)
        with col3:
            fecha_permiso = st.date_input("📅 Fecha", value=date.today(), format="DD/MM/YYYY")
        with col4:
            motivo_sel = st.selectbox("📋 Motivo *", MOTIVOS_LISTA)

        motivo_otro = ""
        if motivo_sel == "Otro":
            motivo_otro = st.text_input(
                "Especificá el motivo",
                placeholder="Ej: Trámite bancario especial",
                max_chars=80,
            )

        col5, col6, col7 = st.columns(3)
        with col5:
            hora_salida = st.time_input("🚪 Hora de salida *", value=time(8, 0), step=60)
        with col6:
            sin_retorno = st.checkbox("🔴 Sin retorno\n(no volvió)", value=False)
        with col7:
            hora_entrada = st.time_input(
                "🏁 Hora de entrada",
                value=time(9, 0),
                step=60,
                disabled=sin_retorno,
            )

        compensa = st.radio(
            "💰 ¿Va a compensar las horas? *",
            ["SI", "NO"],
            horizontal=True,
        )
        registrado_por = st.text_input("👮 Tu nombre *", placeholder="Ej: García Juan")

        # Previsualización
        if sin_retorno:
            if hora_salida < HORA_FIN_TURNO:
                mins_prev = minutos_entre(hora_salida, HORA_FIN_TURNO)
                hrs_prev  = redondear_horas(mins_prev)
                st.info(
                    f"🔴 Sin retorno — de {hora_salida.strftime('%H:%M')} a 15:00 "
                    f"= **{fmt_dur(mins_prev)}** → "
                    f"{'**' + str(int(hrs_prev)) + 'h a compensar**' if compensa == 'SI' else 'no compensa'}"
                )
            else:
                st.warning("La hora de salida es posterior al fin de turno (15:00). Verificá.")
        elif hora_entrada > hora_salida:
            mins_prev = minutos_entre(hora_salida, hora_entrada)
            hrs_prev  = redondear_horas(mins_prev)
            st.info(
                f"⏱ Tiempo real: **{fmt_dur(mins_prev)}** → "
                f"Horas a compensar: **{int(hrs_prev)}h**"
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
                    mins_r = minutos_entre(hora_salida, HORA_FIN_TURNO)
                    hrs_r  = redondear_horas(mins_r) if compensa == "SI" else 0.0
                    ent_str = "S/R"
                else:
                    mins_r  = minutos_entre(hora_salida, hora_entrada)
                    hrs_r   = redondear_horas(mins_r)
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
                    st.success(f"✅ Guardado — {nombre_resuelto}")
                    st.info(
                        f"Tiempo fuera: {fmt_dur(mins_r)} → **{int(hrs_r)}h a compensar**"
                        if compensa == "SI" else
                        f"Tiempo fuera: {fmt_dur(mins_r)} — no compensa"
                    )
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")

    # Registros del día
    st.divider()
    st.subheader("Registros de hoy")
    if not permisos_p.empty:
        hoy = permisos_p[permisos_p["fecha"].dt.date == date.today()]
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
        st.caption("Solo si la persona no aparece arriba. El nombre debe ser único y completo.")
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

    st.title(f"👋 ¡Hola, RRHH! — {planta_activa}")
    st.write("Seguimiento de permisos y compensaciones.")
    st.divider()

    # Filtros de período
    col_f1, col_f2 = st.columns(2)
    with col_f1:
        año_sel = st.selectbox("Año", AÑOS, index=AÑOS.index(date.today().year))
    with col_f2:
        mes_sel = st.selectbox(
            "Mes", list(MESES.keys()),
            index=date.today().month - 1,
            format_func=lambda x: MESES[x],
        )

    if permisos_p.empty:
        st.warning("No hay permisos cargados para esta planta.")
        st.stop()

    # Último día del mes seleccionado para calcular saldo al cierre
    import calendar
    ultimo_dia_mes = date(año_sel, mes_sel, calendar.monthrange(año_sel, mes_sel)[1])

    # ── SALDOS ──────────────────────────────────────────────────
    # CORRECCIÓN: el saldo acumulado se calcula sobre TODO el histórico
    # hasta el último día del mes seleccionado.
    # Así, si alguien compensó en mayo deudas de abril, el saldo de abril
    # al cierre del mes es correcto (incluye compensaciones hasta fin de abril).
    # Para el saldo ACTUAL (a hoy), usamos sin límite de fecha.
    saldos_al_cierre = calcular_saldos(permisos_p, comp_p, hasta_fecha=ultimo_dia_mes)
    saldos_actuales  = calcular_saldos(permisos_p, comp_p)  # saldo real hoy

    # Permisos del mes para métricas y detalle
    p_mes = permisos_p[
        (permisos_p["fecha"].dt.year == año_sel) &
        (permisos_p["fecha"].dt.month == mes_sel)
    ].copy()

    # Compensaciones del mes para métricas
    c_mes = comp_p[
        (comp_p["fecha_compensacion"].dt.year == año_sel) &
        (comp_p["fecha_compensacion"].dt.month == mes_sel)
    ].copy() if not comp_p.empty else comp_p.copy()

    comp_mes_total = c_mes["horas_compensadas"].sum() if not c_mes.empty and "horas_compensadas" in c_mes.columns else 0

    # ── Métricas ──
    st.divider()
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("📋 Permisos en el mes", len(p_mes))
    col_m2.metric("👥 Con deuda al cierre del mes", len(saldos_al_cierre))
    col_m3.metric(
        "⏳ Horas pendientes (hoy)",
        f"{saldos_actuales['saldo'].sum():.0f}h" if not saldos_actuales.empty else "0h",
    )
    col_m4.metric("✅ Compensadas en el mes", f"{comp_mes_total:.0f}h")

    # ── REPORTE PARA GERENCIA ────────────────────────────────────
    # Solo muestra: Nombre y Saldo pendiente al cierre del mes.
    # Saldo es ACUMULATIVO: incluye deudas anteriores no saldadas.
    # Si saldo = 0 (ya compensó todo), NO aparece.
    # ─────────────────────────────────────────────────────────────
    st.divider()
    st.subheader(f"📄 Reporte para Gerencia — {MESES[mes_sel]} {año_sel}")
    st.caption(
        f"Empleados con horas pendientes al cierre de {MESES[mes_sel]}. "
        "Saldo acumulativo: incluye meses anteriores no compensados."
    )

    if saldos_al_cierre.empty:
        st.success(f"✅ Sin horas pendientes al cierre de {MESES[mes_sel]} {año_sel}.")
    else:
        # Tabla mínima para gerencia: solo nombre y saldo
        reporte = saldos_al_cierre[["nombre", "saldo"]].copy()
        reporte["saldo"] = reporte["saldo"].apply(lambda x: f"{x:.0f}h")
        reporte.columns  = ["Apellido y Nombre", "Horas pendientes"]
        reporte.index    = range(1, len(reporte) + 1)

        st.dataframe(
            reporte,
            use_container_width=True,
            height=min(480, 45 + len(reporte) * 35),
        )
        total_hs = saldos_al_cierre["saldo"].sum()
        st.caption(
            f"**{len(reporte)} personas** — **{total_hs:.0f}h** pendientes totales al cierre de {MESES[mes_sel]}."
        )

    # ── Saldo actual (a hoy) ────────────────────────────────────
    st.divider()
    st.subheader("📊 Saldo acumulado actual (a hoy)")
    st.caption("Refleja todas las compensaciones registradas hasta hoy, incluidos meses futuros.")

    if saldos_actuales.empty:
        st.success("✅ Nadie tiene horas pendientes a la fecha.")
    else:
        sa = saldos_actuales[["nombre", "debe", "compensado", "saldo"]].copy()
        sa["debe"]       = sa["debe"].apply(lambda x: f"{x:.0f}h")
        sa["compensado"] = sa["compensado"].apply(lambda x: f"{x:.0f}h")
        sa["saldo"]      = saldos_actuales["saldo"].apply(lambda x: f"{x:.0f}h")
        sa.columns       = ["Nombre", "Debe total", "Ya compensó", "Saldo hoy"]
        sa.index         = range(1, len(sa) + 1)
        st.dataframe(sa, use_container_width=True, height=min(400, 45 + len(sa) * 35))

    # ── Registrar compensación ──────────────────────────────────
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

        if nom_c and not saldos_actuales.empty:
            saldo_act = saldos_actuales[saldos_actuales["nombre"] == nom_c]["saldo"].sum()
            if saldo_act > 0:
                st.info(f"Saldo pendiente de **{nom_c}**: **{saldo_act:.0f}h**")
            else:
                st.success(f"**{nom_c}** no tiene horas pendientes.")

        cc3, cc4 = st.columns(2)
        with cc3:
            fecha_comp = st.date_input("Fecha en que compensó", value=date.today(), format="DD/MM/YYYY")
        with cc4:
            hs_comp = st.number_input("Horas compensadas", min_value=0.5, max_value=8.0, value=1.0, step=0.5)

        obs      = st.text_input("Observación (opcional)", placeholder="Ej: se quedó al final del turno")
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

    # ── Detalle del mes ─────────────────────────────────────────
    st.divider()
    st.subheader(f"🔍 Permisos de {MESES[mes_sel]} {año_sel}")
    if not p_mes.empty:
        det = p_mes[[
            "fecha", "legajo", "nombre", "hora_salida", "hora_entrada",
            "sin_retorno", "motivo", "compensa", "horas_redondeadas"
        ]].copy()
        det["fecha"] = det["fecha"].dt.strftime("%d/%m/%Y")
        det.columns  = ["Fecha", "Legajo", "Nombre", "Salida", "Entrada", "S/R", "Motivo", "Compensa", "Hs."]
        st.dataframe(det, use_container_width=True, hide_index=True)
    else:
        st.info(f"No hay permisos registrados en {MESES[mes_sel]} {año_sel}.")


# ═══════════════════════════════════════════════════════════════
# ANÁLISIS
# ═══════════════════════════════════════════════════════════════
elif pagina == "📊 Análisis":

    st.title(f"📊 Análisis de Permisos — {planta_activa}")
    st.caption("Datos históricos completos.")

    if permisos_p.empty:
        st.warning("No hay datos para analizar en esta planta.")
        st.stop()

    df = permisos_p.copy()
    df["año"]       = df["fecha"].dt.year
    df["mes"]       = df["fecha"].dt.month
    df["año_semana"] = df["fecha"].dt.strftime("%Y-S%V")

    años_disp = sorted(df["año"].dropna().astype(int).unique().tolist())
    año_a = st.multiselect("Filtrar por año", años_disp, default=años_disp)
    df = df[df["año"].isin(año_a)]

    if df.empty:
        st.info("No hay datos para ese período.")
        st.stop()

    st.divider()

    # ── 1. Permisos por semana ──
    st.subheader("Permisos por semana")
    sem  = df.groupby("año_semana").size().reset_index(name="cantidad")
    prom = sem["cantidad"].mean()
    max_v = sem["cantidad"].max()
    colores_sem = [COLORES["rojo"] if v == max_v else COLORES["azul"] for v in sem["cantidad"]]

    fig1 = go.Figure(go.Bar(
        x=sem["año_semana"], y=sem["cantidad"],
        text=sem["cantidad"], textposition="outside",
        marker_color=colores_sem,
        hovertemplate="%{x}: %{y} permisos<extra></extra>",
    ))
    fig1.add_hline(
        y=prom, line_dash="dash", line_color=COLORES["gris"],
        annotation_text=f"Promedio: {prom:.1f}",
        annotation_position="top left",
    )
    fig1.update_layout(
        plot_bgcolor="white", height=290,
        margin=dict(t=30, b=10, l=10, r=10),
        xaxis_title="", yaxis_title="Permisos", showlegend=False,
    )
    st.plotly_chart(fig1, use_container_width=True)
    semana_pico = sem.loc[sem["cantidad"].idxmax(), "año_semana"]
    st.caption(
        f"Promedio: **{prom:.1f} permisos/semana** — "
        f"Pico: **{semana_pico}** con {max_v} permisos 🔴"
    )

    st.divider()

    # ── 2. Pareto de motivos ──
    st.subheader("¿Por qué salen? — Pareto 80%")
    mc = df["motivo"].value_counts().reset_index()
    mc.columns  = ["Motivo", "Cantidad"]
    mc["acum"]  = (mc["Cantidad"].cumsum() / mc["Cantidad"].sum() * 100)
    pareto = mc[mc["acum"].shift(1, fill_value=0) < 80].head(8)

    max_mot = pareto["Cantidad"].max()
    cols_mot = [COLORES["rojo"] if v == max_mot else COLORES["azul_claro"] for v in pareto["Cantidad"]]

    fig2 = go.Figure(go.Bar(
        x=pareto["Cantidad"], y=pareto["Motivo"],
        orientation="h", text=pareto["Cantidad"], textposition="outside",
        marker_color=cols_mot,
        hovertemplate="%{y}: %{x} veces<extra></extra>",
    ))
    fig2.update_layout(
        plot_bgcolor="white", height=max(260, len(pareto) * 42),
        margin=dict(t=10, b=10, l=10, r=60),
        xaxis_title="Cantidad", yaxis_title="",
        yaxis={"categoryorder": "total ascending"}, showlegend=False,
    )
    st.plotly_chart(fig2, use_container_width=True)
    if not pareto.empty:
        top1 = pareto.iloc[-1]
        st.caption(
            f"**{top1['Motivo']}** lidera con {top1['Cantidad']} casos. "
            f"Estos {len(pareto)} motivos explican el 80% del total."
        )

    st.divider()

    # ── 3. Duración ──
    st.subheader("¿Cuánto tiempo suelen estar fuera?")
    df_dur = df[df["minutos_reales"].notna() & (df["minutos_reales"] > 0)].copy()

    if not df_dur.empty:
        orden = ["< 30 min", "30 – 60 min", "1h – 1h 30min", "1h 30min – 2h", "Más de 2h"]

        def cat_dur(m):
            if m < 30:    return "< 30 min"
            elif m < 60:  return "30 – 60 min"
            elif m < 90:  return "1h – 1h 30min"
            elif m < 120: return "1h 30min – 2h"
            else:         return "Más de 2h"

        df_dur["rango"] = df_dur["minutos_reales"].apply(cat_dur)
        c = df_dur["rango"].value_counts().reindex(orden, fill_value=0).reset_index()
        c.columns = ["Rango", "Cantidad"]
        c["Pct"]  = (c["Cantidad"] / c["Cantidad"].sum() * 100).round(1)

        max_dur   = c["Cantidad"].max()
        cols_dur  = [COLORES["rojo"] if v == max_dur else COLORES["azul"] for v in c["Cantidad"]]
        prom_min  = df_dur["minutos_reales"].mean()

        cd1, cd2 = st.columns([2, 1])
        with cd1:
            fig3 = go.Figure(go.Bar(
                x=c["Rango"], y=c["Cantidad"],
                text=c["Pct"].apply(lambda x: f"{x}%"),
                textposition="outside",
                marker_color=cols_dur,
                hovertemplate="%{x}: %{y} permisos (%{text})<extra></extra>",
            ))
            fig3.update_layout(
                plot_bgcolor="white", height=270,
                margin=dict(t=10, b=10, l=10, r=10),
                xaxis_title="", yaxis_title="Permisos", showlegend=False,
            )
            st.plotly_chart(fig3, use_container_width=True)
        with cd2:
            st.dataframe(
                c[["Rango", "Cantidad", "Pct"]].rename(columns={"Pct": "%"}),
                use_container_width=True, hide_index=True,
            )
            mayor = c.loc[c["Cantidad"].idxmax()]
            st.caption(
                f"Rango más frecuente: **{mayor['Rango']}** ({mayor['Pct']}%).\n\n"
                f"Promedio real de ausencia: **{fmt_dur(prom_min)}**."
            )
    else:
        st.info("No hay datos de duración suficientes.")

    st.divider()

    # ── 4. ¿Compensan o no? ──
    st.subheader("¿Compensan o no compensan?")
    ratio = df["compensa"].value_counts().reset_index()
    ratio.columns = ["Compensa", "Cantidad"]
    total_r = ratio["Cantidad"].sum()

    mapa_col = {"SI": COLORES["verde"], "NO": COLORES["rojo"]}
    fig4 = go.Figure(go.Pie(
        labels=ratio["Compensa"],
        values=ratio["Cantidad"],
        hole=0.5,
        marker_colors=[mapa_col.get(v, COLORES["gris"]) for v in ratio["Compensa"]],
        textinfo="label+percent",
        hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
    ))
    fig4.update_layout(
        height=260, margin=dict(t=10, b=10, l=10, r=10), showlegend=False,
    )

    cr1, cr2 = st.columns([1, 2])
    with cr1:
        st.plotly_chart(fig4, use_container_width=True)
    with cr2:
        for _, row in ratio.iterrows():
            pct   = row["Cantidad"] / total_r * 100
            icono = "✅" if row["Compensa"] == "SI" else "❌"
            st.metric(
                f"{icono} {row['Compensa']}",
                f"{row['Cantidad']} permisos",
                f"{pct:.1f}% del total",
            )

    st.divider()
    st.caption("Análisis basado en los datos de Google Sheets.")

