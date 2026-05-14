import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date, time
import plotly.express as px

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

MOTIVOS = [
    "Banco / Cajero",
    "Médico propio",
    "Médico hijo/a",
    "Obra social",
    "ANSES",
    "Juzgado / Tribunales",
    "Registro Civil / DNI",
    "Escribanía",
    "Emicar",
    "Clínica",
    "Escuela hijo/a",
    "Cuidado familiar",
    "Trámite personal",
    "Análisis de sangre",
    "Otro",
]

MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

PASSWORD = "1234"


# ─────────────────────────────────────────────
# LOGIN
# ─────────────────────────────────────────────
def check_login():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False
    if not st.session_state.autenticado:
        st.title("🏭 Control de Permisos — Fábrica San Juan")
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
    """< 30 min → 0h | 30–89 min → 1h | 90–149 min → 2h | etc."""
    if minutos is None or pd.isna(minutos) or minutos < 30:
        return 0.0
    parte = int(minutos // 60)
    fraccion = (minutos % 60) / 60
    return float(parte + 1) if fraccion >= 0.5 else float(parte)


def fmt_dur(minutos: float) -> str:
    h = int(minutos // 60)
    m = int(minutos % 60)
    if h == 0:
        return f"{m} min"
    return f"{h}h {m:02d}min" if m else f"{h}h"


# ─────────────────────────────────────────────
# CONEXIÓN GOOGLE SHEETS
# Cache largo para el cliente (no cambia)
# Cache corto para los datos (se actualizan)
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


# TTL 60s: el padrón cambia poco, no hace falta recargar seguido
@st.cache_data(ttl=60)
def leer_padron(_gc):
    ws = get_wb(_gc).worksheet("padron")
    df = pd.DataFrame(ws.get_all_records())
    if not df.empty:
        df["legajo"] = df["legajo"].astype(str).str.strip()
        df["nombre"] = df["nombre"].astype(str).str.strip().str.upper()
    return df


# TTL 20s: permisos se cargan varias veces por día
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
    return df


# TTL 20s: compensaciones igual que permisos
@st.cache_data(ttl=20)
def leer_compensaciones(_gc):
    ws = get_wb(_gc).worksheet("compensaciones")
    df = pd.DataFrame(ws.get_all_records())
    if df.empty:
        return df
    df["fecha_compensacion"] = pd.to_datetime(df["fecha_compensacion"], errors="coerce")
    df["horas_compensadas"] = pd.to_numeric(df["horas_compensadas"], errors="coerce")
    df["legajo"] = df["legajo"].astype(str).str.strip()
    return df


def guardar_permiso(gc, fila: dict):
    get_wb(gc).worksheet("permisos").append_row(list(fila.values()), value_input_option="RAW")
    leer_permisos.clear()


def guardar_compensacion(gc, fila: dict):
    get_wb(gc).worksheet("compensaciones").append_row(list(fila.values()), value_input_option="RAW")
    leer_compensaciones.clear()


def agregar_empleado(gc, legajo: str, nombre: str, sector: str = ""):
    get_wb(gc).worksheet("padron").append_row(
        [legajo.strip(), nombre.upper().strip(), sector.strip(), "", "SI"],
        value_input_option="RAW"
    )
    leer_padron.clear()


def generar_id(prefijo="P"):
    return f"{prefijo}{datetime.now().strftime('%Y%m%d%H%M%S')}"


# ─────────────────────────────────────────────
# CALCULAR SALDOS
# ─────────────────────────────────────────────
def calcular_saldos(permisos: pd.DataFrame, compensaciones: pd.DataFrame) -> pd.DataFrame:
    cols = ["legajo", "nombre", "debe", "compensado", "saldo"]
    if permisos.empty:
        return pd.DataFrame(columns=cols)
    p = permisos[permisos["compensa"] == "SI"].copy()
    if p.empty:
        return pd.DataFrame(columns=cols)
    debe = (
        p.groupby(["legajo", "nombre"])["horas_redondeadas"]
        .sum().reset_index()
        .rename(columns={"horas_redondeadas": "debe"})
    )
    if not compensaciones.empty:
        comp = (
            compensaciones.groupby("legajo")["horas_compensadas"]
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
# CARGAR DATOS (con spinner para feedback)
# ─────────────────────────────────────────────
try:
    gc = conectar_sheets()
except Exception as e:
    st.error(f"No se pudo conectar con Google Sheets: {e}")
    st.stop()

try:
    with st.spinner("Cargando datos..."):
        padron      = leer_padron(gc)
        permisos    = leer_permisos(gc)
        compensaciones = leer_compensaciones(gc)
except Exception as e:
    st.error(f"Error al leer datos: {e}")
    st.stop()

# Diccionarios de lookup (construidos una vez por sesión)
padron_dict       = dict(zip(padron["legajo"], padron["nombre"])) if not padron.empty else {}
nombre_a_legajo   = dict(zip(padron["nombre"], padron["legajo"])) if not padron.empty else {}
nombres_en_padron = sorted(padron["nombre"].tolist()) if not padron.empty else []


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🏭 Control de Permisos")
    st.caption(f"Hoy: {date.today().strftime('%d/%m/%Y')}")
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


# ═══════════════════════════════════════════════════════════════
# PANEL GUARDIA
# ═══════════════════════════════════════════════════════════════
if pagina == "🔵 Panel Guardia":

    st.title("👋 ¡Hola, Guardia!")
    st.write("Buscá a la persona por nombre y completá los datos del permiso.")
    st.divider()

    # ── Búsqueda por nombre (selectbox con todos los del padrón) ──
    st.subheader("¿Quién sale?")

    # Opción vacía al inicio para que el guardia elija
    opciones_nombre = ["— Seleccioná un nombre —"] + nombres_en_padron

    nombre_sel = st.selectbox(
        "Nombre completo del empleado/a",
        opciones_nombre,
        help="Escribí las primeras letras para filtrar la lista.",
    )

    legajo_resuelto = ""
    nombre_resuelto = ""

    if nombre_sel and nombre_sel != "— Seleccioná un nombre —":
        legajo_resuelto = nombre_a_legajo.get(nombre_sel, "")
        nombre_resuelto = nombre_sel
        col_info1, col_info2 = st.columns(2)
        col_info1.success(f"✅ **{nombre_resuelto}**")
        col_info2.info(f"Legajo: **{legajo_resuelto}**" if legajo_resuelto else "Sin legajo asignado")

    # Legajo opcional (solo si no se encontró por nombre o quiere verificar)
    with st.expander("🔢 Ingresar legajo manualmente (opcional)"):
        legajo_manual = st.text_input("Legajo", placeholder="Ej: 2621")
        if legajo_manual.strip() and legajo_manual.strip() in padron_dict:
            nombre_por_legajo = padron_dict[legajo_manual.strip()]
            st.success(f"✅ {nombre_por_legajo} (legajo {legajo_manual.strip()})")
            # Si se ingresó legajo y es válido, tiene prioridad
            legajo_resuelto = legajo_manual.strip()
            nombre_resuelto = nombre_por_legajo
        elif legajo_manual.strip():
            st.warning("Legajo no encontrado en el padrón.")

    st.divider()

    # ── Formulario principal ──
    st.subheader("Datos del permiso")

    with st.form("form_guardia", clear_on_submit=True):

        col3, col4 = st.columns(2)
        with col3:
            fecha_permiso = st.date_input("📅 Fecha", value=date.today(), format="DD/MM/YYYY")
        with col4:
            motivo = st.selectbox("📋 Motivo de salida *", MOTIVOS)

        # Si selecciona "Otro", permitir especificar
        motivo_otro = ""
        if motivo == "Otro":
            motivo_otro = st.text_input(
                "✍️ Especificar motivo",
                placeholder="Ej: Trámite bancario urgente"
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
            "💰 ¿Va a compensar las horas?",
            ["SI", "NO"],
            horizontal=True,
            help="SI = se queda horas extra otro día. NO = no se descuenta.",
        )

        registrado_por = st.text_input(
            "👮 Tu nombre (guardia) *",
            placeholder="Ej: García Juan",
        )

        # Previsualización del cálculo
        if not sin_retorno and hora_entrada > hora_salida:
            mins_prev = (
                datetime.combine(date.today(), hora_entrada)
                - datetime.combine(date.today(), hora_salida)
            ).seconds / 60
            hrs_prev = redondear_horas(mins_prev)
            st.info(
                f"⏱ Tiempo real fuera: **{fmt_dur(mins_prev)}** → "
                f"Horas a compensar (redondeado): **{int(hrs_prev)}h**"
            )

        submitted = st.form_submit_button(
            "💾 GUARDAR REGISTRO", use_container_width=True, type="primary"
        )

        if submitted:
            errores = []
            if not nombre_resuelto:
                errores.append("Seleccioná o buscá a la persona primero.")
            if not registrado_por.strip():
                errores.append("Falta tu nombre.")
            if not sin_retorno and hora_entrada <= hora_salida:
                errores.append("La hora de entrada debe ser posterior a la salida.")

            if errores:
                for e in errores:
                    st.error(f"❌ {e}")
            else:
                if sin_retorno:
                    mins_r, hrs_r, ent_str = None, None, "S/R"
                else:
                    mins_r = round((
                        datetime.combine(date.today(), hora_entrada)
                        - datetime.combine(date.today(), hora_salida)
                    ).seconds / 60, 1)
                    hrs_r = redondear_horas(mins_r)
                    ent_str = hora_entrada.strftime("%H:%M")

                try:
                    guardar_permiso(gc, {
                        "id": generar_id("P"),
                        "fecha": fecha_permiso.strftime("%Y-%m-%d"),
                        "legajo": legajo_resuelto,
                        "nombre": nombre_resuelto,
                        "hora_salida": hora_salida.strftime("%H:%M"),
                        "hora_entrada": ent_str,
                        "sin_retorno": "SI" if sin_retorno else "NO",
                        "motivo": motivo_otro if motivo == "Otro" else motivo,
                        "compensa": compensa,
                        "minutos_reales": mins_r if mins_r is not None else "",
                        "horas_redondeadas": hrs_r if hrs_r is not None else "",
                        "registrado_por": registrado_por.strip(),
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success(f"✅ Registro guardado — {nombre_resuelto}")
                    if not sin_retorno and mins_r:
                        st.info(
                            f"Tiempo fuera: {fmt_dur(mins_r)} → **{int(hrs_r)}h a compensar**"
                        )
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")

    # ── Registros de hoy ──
    st.divider()
    st.subheader("Registros de hoy")
    if not permisos.empty:
        hoy = permisos[permisos["fecha"].dt.date == date.today()]
        if hoy.empty:
            st.caption("Aún no hay registros hoy.")
        else:
            hoy_s = hoy[["nombre", "hora_salida", "hora_entrada", "motivo", "compensa", "horas_redondeadas"]].copy()
            hoy_s.columns = ["Nombre", "Salida", "Entrada", "Motivo", "Compensa", "Hs."]
            st.dataframe(hoy_s, use_container_width=True, hide_index=True)
    else:
        st.caption("No hay registros cargados aún.")

    # ── Agregar empleado nuevo ──
    st.divider()
    with st.expander("➕ Agregar empleado que no está en la lista"):
        st.caption(
            "Usá esto solo si la persona no aparece en la lista de arriba. "
            "El nombre debe ser completo (apellido/s y nombre/s). "
            "No puede haber dos personas con el mismo nombre completo."
        )
        with st.form("form_nuevo"):
            cn1, cn2 = st.columns(2)
            with cn1:
                nvo_leg = st.text_input("Legajo (opcional)", placeholder="Ej: 3050")
            with cn2:
                nvo_nom = st.text_input(
                    "Apellido y Nombre completo *",
                    placeholder="Ej: GOMEZ PEREZ, CARLOS ALBERTO",
                )
            nvo_sec = st.text_input("Sector (opcional)")
            if st.form_submit_button("Agregar al padrón", use_container_width=True):
                nvo_nom_clean = nvo_nom.strip().upper()
                errores_nuevo = []
                if not nvo_nom_clean:
                    errores_nuevo.append("El nombre es obligatorio.")
                if nvo_nom_clean in nombre_a_legajo:
                    errores_nuevo.append(
                        f"Ya existe una persona con ese nombre: {nvo_nom_clean}. "
                        "Agregá el segundo nombre o apellido para distinguirlos."
                    )
                if errores_nuevo:
                    for e in errores_nuevo:
                        st.error(f"❌ {e}")
                else:
                    try:
                        agregar_empleado(gc, nvo_leg.strip(), nvo_nom_clean, nvo_sec.strip())
                        st.success(
                            f"✅ {nvo_nom_clean} agregado. "
                            "Recargá la página para encontrarlo en la lista."
                        )
                    except Exception as e:
                        st.error(f"❌ Error: {e}")


# ═══════════════════════════════════════════════════════════════
# PANEL RRHH
# ═══════════════════════════════════════════════════════════════
elif pagina == "🟢 Panel RRHH":

    st.title("👋 ¡Hola, RRHH!")
    st.write("Resumen de permisos y compensaciones del período seleccionado.")
    st.divider()

    # Filtros
    col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
    with col_f1:
        año_sel = st.selectbox("Año", [2025, 2026], index=1)
    with col_f2:
        mes_sel = st.selectbox(
            "Mes",
            list(MESES.keys()),
            index=datetime.now().month - 1,
            format_func=lambda x: MESES[x],
        )
    with col_f3:
        modo = st.radio(
            "Vista:",
            ["Solo este mes", "Saldo acumulado total"],
            horizontal=True,
        )

    if permisos.empty:
        st.warning("No hay permisos cargados todavía.")
        st.stop()

    if modo == "Solo este mes":
        p_f = permisos[
            (permisos["fecha"].dt.year == año_sel) &
            (permisos["fecha"].dt.month == mes_sel)
        ].copy()
        c_f = compensaciones[
            (compensaciones["fecha_compensacion"].dt.year == año_sel) &
            (compensaciones["fecha_compensacion"].dt.month == mes_sel)
        ].copy() if not compensaciones.empty else compensaciones.copy()
    else:
        p_f = permisos.copy()
        c_f = compensaciones.copy()

    saldos = calcular_saldos(p_f, c_f)
    comp_total = (
        c_f["horas_compensadas"].sum()
        if not c_f.empty and "horas_compensadas" in c_f.columns
        else 0
    )

    # ── Métricas ──
    st.divider()
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("📋 Permisos registrados", len(p_f))
    col_m2.metric("👥 Personas con deuda", len(saldos))
    col_m3.metric(
        "⏳ Horas pendientes",
        f"{saldos['saldo'].sum():.0f}h" if not saldos.empty else "0h",
    )
    col_m4.metric("✅ Horas compensadas", f"{comp_total:.0f}h")

    # ── REPORTE PARA GERENCIA ──
    st.divider()
    st.subheader(f"📄 Reporte para Gerencia — {MESES[mes_sel]} {año_sel}")
    st.caption(
        "Esta tabla muestra quiénes deben compensar horas y cuántas. "
        "Sacale captura de pantalla y enviala a la gerenta de planta."
    )

    if saldos.empty:
        st.success(
            f"✅ Todo en orden — Ningún empleado tiene horas pendientes "
            f"en {MESES[mes_sel]} {año_sel}."
        )
    else:
        # Tabla limpia, solo lo que la gerenta necesita ver
        reporte = saldos[["nombre", "saldo"]].copy()
        reporte.columns = ["Apellido y Nombre", "Horas a compensar"]
        reporte["Horas a compensar"] = reporte["Horas a compensar"].apply(
            lambda x: f"{int(x)}h"
        )
        reporte.index = range(1, len(reporte) + 1)  # numerado desde 1

        st.dataframe(
            reporte,
            use_container_width=True,
            height=min(500, 45 + len(reporte) * 35),
        )
        st.caption(
            f"Total: **{len(reporte)} personas** con **{saldos['saldo'].sum():.0f}h** pendientes."
        )

    # ── Registrar compensación ──
    st.divider()
    st.subheader("✏️ Registrar compensación")
    st.caption("Cuando alguien se queda horas extra para compensar, registralo acá.")

    opciones_comp = ["— Seleccioná un nombre —"] + nombres_en_padron
    with st.form("form_comp"):
        nombre_comp_sel = st.selectbox("Nombre del empleado/a", opciones_comp)
        nom_c = nombre_comp_sel if nombre_comp_sel != "— Seleccioná un nombre —" else ""
        leg_c = nombre_a_legajo.get(nom_c, "") if nom_c else ""

        if nom_c:
            saldo_actual = saldos[saldos["nombre"] == nom_c]["saldo"].sum() if not saldos.empty else 0
            if saldo_actual > 0:
                st.info(f"Saldo pendiente de **{nom_c}**: **{saldo_actual:.0f}h**")
            else:
                st.success(f"**{nom_c}** no tiene horas pendientes en el período actual.")

        cc3, cc4 = st.columns(2)
        with cc3:
            fecha_comp = st.date_input(
                "Fecha en que compensó", value=date.today(), format="DD/MM/YYYY"
            )
        with cc4:
            hs_comp = st.number_input(
                "Horas compensadas", min_value=0.5, max_value=8.0, value=1.0, step=0.5
            )

        obs = st.text_input(
            "Observación (opcional)", placeholder="Ej: se quedó al final del turno"
        )
        registra = st.text_input("Tu nombre *")

        if st.form_submit_button(
            "✅ REGISTRAR COMPENSACIÓN", use_container_width=True, type="primary"
        ):
            if not nom_c:
                st.error("❌ Seleccioná a la persona primero.")
            elif not registra.strip():
                st.error("❌ Falta tu nombre.")
            else:
                try:
                    guardar_compensacion(gc, {
                        "id": generar_id("C"),
                        "fecha_compensacion": fecha_comp.strftime("%Y-%m-%d"),
                        "legajo": leg_c,
                        "nombre": nom_c,
                        "horas_compensadas": hs_comp,
                        "observacion": obs,
                        "registrado_por": registra.strip(),
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success(
                        f"✅ {nom_c} — {hs_comp}h compensadas el "
                        f"{fecha_comp.strftime('%d/%m/%Y')}"
                    )
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    # ── Detalle del período ──
    st.divider()
    st.subheader("🔍 Detalle de permisos del período")
    if not p_f.empty:
        det = p_f[[
            "fecha", "legajo", "nombre", "hora_salida", "hora_entrada",
            "sin_retorno", "motivo", "compensa", "horas_redondeadas"
        ]].copy()
        det["fecha"] = det["fecha"].dt.strftime("%d/%m/%Y")
        det.columns = [
            "Fecha", "Legajo", "Nombre", "Salida", "Entrada",
            "S/R", "Motivo", "Compensa", "Hs."
        ]
        st.dataframe(det, use_container_width=True, hide_index=True)
    else:
        st.info("No hay permisos en este período.")


# ═══════════════════════════════════════════════════════════════
# ANÁLISIS DE DATOS
# ═══════════════════════════════════════════════════════════════
elif pagina == "📊 Análisis":

    st.title("📊 Análisis de Permisos")
    st.caption("Datos históricos 2025–2026.")

    if permisos.empty:
        st.warning("No hay datos para analizar aún.")
        st.stop()

    df = permisos.copy()
    df["año"] = df["fecha"].dt.year
    df["mes"] = df["fecha"].dt.month
    df["año_semana"] = df["fecha"].dt.strftime("%Y-S%V")

    años_disp = sorted(df["año"].dropna().unique().tolist())
    año_a = st.multiselect("Filtrar por año", años_disp, default=años_disp)
    df = df[df["año"].isin(año_a)]

    if df.empty:
        st.info("No hay datos para ese período.")
        st.stop()

    st.divider()

    # ── 1. Permisos por semana ──
    st.subheader("Permisos registrados por semana")
    sem = df.groupby("año_semana").size().reset_index(name="cantidad")
    fig1 = px.bar(
        sem, x="año_semana", y="cantidad", text="cantidad",
        labels={"año_semana": "Semana", "cantidad": "Permisos"},
        color_discrete_sequence=["#1B4F9B"],
    )
    fig1.update_traces(textposition="outside")
    fig1.update_layout(
        plot_bgcolor="white", height=280,
        margin=dict(t=10, b=10), showlegend=False,
    )
    st.plotly_chart(fig1, use_container_width=True)
    st.caption(f"Promedio semanal: **{sem['cantidad'].mean():.1f} permisos**")

    st.divider()

    # ── 2. Pareto de motivos ──
    st.subheader("¿Por qué salen? — Motivos principales")
    mc = df["motivo"].str.strip().value_counts().reset_index()
    mc.columns = ["Motivo", "Cantidad"]
    mc["acum_pct"] = (mc["Cantidad"].cumsum() / mc["Cantidad"].sum() * 100)
    pareto = mc[mc["acum_pct"].shift(1, fill_value=0) < 80].head(6)

    fig2 = px.bar(
        pareto, x="Cantidad", y="Motivo", orientation="h",
        text="Cantidad", color_discrete_sequence=["#2471D5"],
        labels={"Motivo": "", "Cantidad": "Veces"},
    )
    fig2.update_traces(textposition="outside")
    fig2.update_layout(
        plot_bgcolor="white", height=260, margin=dict(t=10, b=10),
        yaxis={"categoryorder": "total ascending"},
    )
    st.plotly_chart(fig2, use_container_width=True)
    if not pareto.empty:
        top1 = pareto.iloc[-1]
        st.caption(
            f"**{top1['Motivo']}** es el motivo más frecuente ({top1['Cantidad']} veces). "
            f"Estos {len(pareto)} motivos explican el 80% de los permisos."
        )

    st.divider()

    # ── 3. Duración ──
    st.subheader("¿Cuánto tiempo suelen estar fuera?")
    df_dur = df[df["minutos_reales"].notna() & (df["minutos_reales"] > 0)].copy()

    if not df_dur.empty:
        def cat_dur(m):
            if m < 30:   return "< 30 min"
            elif m < 60: return "30–60 min"
            elif m < 90: return "1h – 1h30"
            else:        return "Más de 1h30"

        df_dur["rango"] = df_dur["minutos_reales"].apply(cat_dur)
        orden = ["< 30 min", "30–60 min", "1h – 1h30", "Más de 1h30"]
        c = df_dur["rango"].value_counts().reindex(orden, fill_value=0).reset_index()
        c.columns = ["Rango", "Cantidad"]
        c["Pct"] = (c["Cantidad"] / c["Cantidad"].sum() * 100).round(1)

        cd1, cd2 = st.columns([2, 1])
        with cd1:
            fig3 = px.bar(
                c, x="Rango", y="Cantidad",
                text=c["Pct"].apply(lambda x: f"{x}%"),
                color_discrete_sequence=["#1B4F9B"],
                labels={"Rango": "", "Cantidad": "Permisos"},
            )
            fig3.update_traces(textposition="outside")
            fig3.update_layout(
                plot_bgcolor="white", height=250, margin=dict(t=10, b=10)
            )
            st.plotly_chart(fig3, use_container_width=True)
        with cd2:
            st.dataframe(
                c[["Rango", "Cantidad", "Pct"]].rename(columns={"Pct": "%"}),
                use_container_width=True,
                hide_index=True,
            )
            mayor = c.loc[c["Cantidad"].idxmax()]
            st.caption(f"El **{mayor['Pct']}%** son permisos de {mayor['Rango'].lower()}.")

    st.divider()

    # ── 4. ¿Compensan o no? ──
    st.subheader("¿Compensan o no compensan?")
    ratio = df["compensa"].value_counts().reset_index()
    ratio.columns = ["Compensa", "Cantidad"]
    total_r = ratio["Cantidad"].sum()
    cr1, cr2 = st.columns(2)
    for _, row in ratio.iterrows():
        pct = row["Cantidad"] / total_r * 100
        col = cr1 if row["Compensa"] == "SI" else cr2
        col.metric(
            f"{'✅ Compensa' if row['Compensa'] == 'SI' else '❌ No compensa'}",
            f"{row['Cantidad']} permisos",
            f"{pct:.1f}% del total",
        )

    st.divider()
    st.caption("Análisis automático basado en los datos de Google Sheets.")
