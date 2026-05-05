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
    "Obra social / ANSES",
    "Juzgado / Tribunales",
    "Registro Civil / DNI",
    "Escribanía",
    "Emicar / Clínica",
    "Escuela hijo/a",
    "Cuidado familiar",
    "Trámite personal",
    "Otro",
]

MESES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril",
    5: "Mayo", 6: "Junio", 7: "Julio", 8: "Agosto",
    9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre",
}

PASSWORD = "1234"


# ─────────────────────────────────────────────
# LOGIN — pantalla de contraseña
# ─────────────────────────────────────────────
def check_login():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        st.markdown("## 🏭 Control de Permisos — Fábrica San Juan")
        st.markdown("---")
        st.markdown("Ingresá la contraseña para acceder.")
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
# CSS mínimo
# ─────────────────────────────────────────────
st.markdown("""
<style>
    .nombre-display {
        font-size: 1.05rem;
        font-weight: 700;
        color: #1B4F9B;
        background: #E8F0FA;
        border-radius: 6px;
        padding: 0.45rem 0.9rem;
        margin: 0.3rem 0 0.6rem 0;
    }
    .saludo { font-size: 1.1rem; font-weight: 600; margin-bottom: 0.2rem; }
    .stButton > button { border-radius: 6px; font-weight: 600; }
</style>
""", unsafe_allow_html=True)


# ─────────────────────────────────────────────
# LÓGICA DE REDONDEO
# ─────────────────────────────────────────────
def redondear_horas(minutos: float) -> float:
    """
    < 30 min  → 0h
    30–89 min → 1h
    90–149    → 2h   (fracción >= :30 sube al entero siguiente)
    """
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
# ─────────────────────────────────────────────
@st.cache_resource(ttl=300)
def conectar_sheets():
    creds = Credentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=SCOPES
    )
    return gspread.authorize(creds)


def get_wb(gc):
    return gc.open_by_key(st.secrets["SHEET_ID"])


@st.cache_data(ttl=30)
def leer_padron(_gc):
    ws = get_wb(_gc).worksheet("padron")
    df = pd.DataFrame(ws.get_all_records())
    if not df.empty:
        df["legajo"] = df["legajo"].astype(str).str.strip()
    return df


@st.cache_data(ttl=15)
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


@st.cache_data(ttl=15)
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
        [legajo, nombre.upper().strip(), sector, "", "SI"], value_input_option="RAW"
    )
    leer_padron.clear()


def generar_id(prefijo="P"):
    return f"{prefijo}{datetime.now().strftime('%Y%m%d%H%M%S')}"


# ─────────────────────────────────────────────
# CALCULAR SALDOS
# ─────────────────────────────────────────────
def calcular_saldos(permisos: pd.DataFrame, compensaciones: pd.DataFrame) -> pd.DataFrame:
    if permisos.empty:
        return pd.DataFrame(columns=["legajo", "nombre", "debe", "compensado", "saldo"])
    p = permisos[permisos["compensa"] == "SI"].copy()
    if p.empty:
        return pd.DataFrame(columns=["legajo", "nombre", "debe", "compensado", "saldo"])
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
# CARGAR DATOS
# ─────────────────────────────────────────────
try:
    gc = conectar_sheets()
except Exception as e:
    st.error(f"No se pudo conectar con Google Sheets: {e}")
    st.stop()

try:
    padron = leer_padron(gc)
    permisos = leer_permisos(gc)
    compensaciones = leer_compensaciones(gc)
except Exception as e:
    st.error(f"Error al leer datos: {e}")
    st.stop()

padron_dict = dict(zip(padron["legajo"], padron["nombre"])) if not padron.empty else {}


# ─────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────
with st.sidebar:
    st.markdown("### 🏭 Control de Permisos")
    st.caption(f"Hoy: {date.today().strftime('%d/%m/%Y')}")
    st.markdown("---")
    pagina = st.radio(
        "Sección:",
        ["🔵 Panel Guardia", "🟢 Panel RRHH", "📊 Análisis"],
        label_visibility="collapsed",
    )
    st.markdown("---")
    if st.button("🔒 Cerrar sesión", use_container_width=True):
        st.session_state.autenticado = False
        st.rerun()


# ═══════════════════════════════════════════════════════════════
# PANEL GUARDIA
# ═══════════════════════════════════════════════════════════════
if pagina == "🔵 Panel Guardia":

    st.markdown('<div class="saludo">👋 ¡Hola, Guardia! Registrá el permiso acá abajo.</div>', unsafe_allow_html=True)
    st.markdown("---")

    with st.form("form_guardia", clear_on_submit=True):
        col1, col2 = st.columns([1, 2])
        with col1:
            legajo_input = st.text_input("Legajo *", placeholder="Ej: 2621")
        with col2:
            nombre_enc = padron_dict.get(legajo_input.strip(), "")
            if legajo_input.strip() and nombre_enc:
                st.markdown(f'<div class="nombre-display">✅ {nombre_enc}</div>', unsafe_allow_html=True)
            elif legajo_input.strip():
                st.warning("⚠️ Legajo no encontrado. Podés agregarlo más abajo.")
            else:
                st.info("Ingresá el legajo para ver el nombre.")

        col3, col4 = st.columns(2)
        with col3:
            fecha_permiso = st.date_input("Fecha *", value=date.today(), format="DD/MM/YYYY")
        with col4:
            motivo = st.selectbox("Motivo de salida *", MOTIVOS)

        col5, col6, col7 = st.columns(3)
        with col5:
            hora_salida = st.time_input("Hora de salida *", value=time(8, 0), step=60)
        with col6:
            sin_retorno = st.checkbox("Sin retorno (no volvió)", value=False)
        with col7:
            hora_entrada = st.time_input("Hora de entrada", value=time(9, 0), step=60, disabled=sin_retorno)

        compensa = st.radio("¿Va a compensar las horas? *", ["SI", "NO"], horizontal=True)
        registrado_por = st.text_input("Tu nombre (guardia) *", placeholder="Ej: García Juan")

        # Previsualización del cálculo
        if not sin_retorno and hora_entrada > hora_salida:
            mins_prev = (
                datetime.combine(date.today(), hora_entrada)
                - datetime.combine(date.today(), hora_salida)
            ).seconds / 60
            hrs_prev = redondear_horas(mins_prev)
            st.info(
                f"⏱ Tiempo real: **{fmt_dur(mins_prev)}** → "
                f"Horas a compensar (redondeado): **{int(hrs_prev)}h**"
            )

        submitted = st.form_submit_button("💾 GUARDAR REGISTRO", use_container_width=True, type="primary")

        if submitted:
            leg = legajo_input.strip()
            errores = []
            if not leg:
                errores.append("Falta el legajo.")
            if leg and not padron_dict.get(leg):
                errores.append("El legajo no está en el padrón. Agregalo con el formulario de abajo primero.")
            if not registrado_por.strip():
                errores.append("Falta tu nombre.")
            if not sin_retorno and hora_entrada <= hora_salida:
                errores.append("La hora de entrada debe ser posterior a la salida.")

            if errores:
                for e in errores:
                    st.error(f"❌ {e}")
            else:
                nombre = padron_dict[leg]
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
                        "legajo": leg,
                        "nombre": nombre,
                        "hora_salida": hora_salida.strftime("%H:%M"),
                        "hora_entrada": ent_str,
                        "sin_retorno": "SI" if sin_retorno else "NO",
                        "motivo": motivo,
                        "compensa": compensa,
                        "minutos_reales": mins_r if mins_r is not None else "",
                        "horas_redondeadas": hrs_r if hrs_r is not None else "",
                        "registrado_por": registrado_por.strip(),
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success(f"✅ Registro guardado — {nombre}")
                    if not sin_retorno and mins_r:
                        st.info(f"Tiempo fuera: {fmt_dur(mins_r)} → **{int(hrs_r)}h a compensar**")
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")

    # Últimos registros del día
    st.markdown("---")
    st.markdown("**Registros de hoy**")
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

    # Agregar empleado nuevo
    st.markdown("---")
    with st.expander("➕ Agregar empleado que no está en el padrón"):
        st.caption("Solo si el legajo no apareció arriba. Verificá bien el número antes de agregar.")
        with st.form("form_nuevo"):
            cn1, cn2 = st.columns(2)
            with cn1:
                nvo_leg = st.text_input("Legajo nuevo", placeholder="Ej: 3050")
            with cn2:
                nvo_nom = st.text_input("Apellido y Nombre", placeholder="Ej: GOMEZ, CARLOS ALBERTO")
            nvo_sec = st.text_input("Sector (opcional)")
            if st.form_submit_button("Agregar al padrón", use_container_width=True):
                if not nvo_leg.strip() or not nvo_nom.strip():
                    st.error("❌ Legajo y nombre son obligatorios.")
                elif nvo_leg.strip() in padron_dict:
                    st.error("❌ Ese legajo ya existe.")
                else:
                    try:
                        agregar_empleado(gc, nvo_leg.strip(), nvo_nom.strip(), nvo_sec.strip())
                        st.success(f"✅ {nvo_nom.upper().strip()} agregado. Recargá la página y buscá el legajo.")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")


# ═══════════════════════════════════════════════════════════════
# PANEL RRHH
# ═══════════════════════════════════════════════════════════════
elif pagina == "🟢 Panel RRHH":

    st.markdown('<div class="saludo">👋 ¡Hola, RRHH! Acá podés ver el resumen de permisos y compensaciones.</div>', unsafe_allow_html=True)
    st.markdown("---")

    col_f1, col_f2, col_f3 = st.columns([1, 1, 2])
    with col_f1:
        año_sel = st.selectbox("Año", [2025, 2026], index=1)
    with col_f2:
        mes_sel = st.selectbox(
            "Mes", list(MESES.keys()),
            index=datetime.now().month - 1,
            format_func=lambda x: MESES[x],
        )
    with col_f3:
        modo = st.radio("Vista:", ["Saldo acumulado total", "Solo este mes"], horizontal=True)

    st.markdown("---")

    if permisos.empty:
        st.warning("No hay permisos cargados todavía.")
        st.stop()

    if modo == "Solo este mes":
        p_f = permisos[(permisos["fecha"].dt.year == año_sel) & (permisos["fecha"].dt.month == mes_sel)].copy()
        c_f = compensaciones[
            (compensaciones["fecha_compensacion"].dt.year == año_sel) &
            (compensaciones["fecha_compensacion"].dt.month == mes_sel)
        ].copy() if not compensaciones.empty else compensaciones.copy()
    else:
        p_f = permisos.copy()
        c_f = compensaciones.copy()

    saldos = calcular_saldos(p_f, c_f)

    # Métricas
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("Permisos registrados", len(p_f))
    col_m2.metric("Personas con deuda", len(saldos))
    col_m3.metric("Horas pendientes", f"{saldos['saldo'].sum():.0f}h" if not saldos.empty else "0h")
    comp_total = c_f["horas_compensadas"].sum() if not c_f.empty and "horas_compensadas" in c_f.columns else 0
    col_m4.metric("Horas ya compensadas", f"{comp_total:.0f}h")

    st.markdown("---")

    # Tabla de saldos — lista para captura
    st.markdown(f"**Horas pendientes — {MESES[mes_sel]} {año_sel}**")
    st.caption("Ajustá el ancho de las columnas si querés y sacale captura para gerencia.")

    if saldos.empty:
        st.success("✅ No hay horas pendientes para este período.")
    else:
        tabla = saldos.copy()
        tabla["debe"] = tabla["debe"].apply(lambda x: f"{x:.0f}h")
        tabla["compensado"] = tabla["compensado"].apply(lambda x: f"{x:.0f}h")
        tabla["saldo"] = saldos["saldo"].apply(lambda x: f"{x:.0f}h")
        tabla.columns = ["Legajo", "Nombre", "Debe", "Compensó", "Saldo pendiente"]
        st.dataframe(tabla, use_container_width=True, hide_index=True, height=min(450, 45 + len(tabla) * 35))

    # Registrar compensación
    st.markdown("---")
    st.markdown("**Registrar compensación**")
    st.caption("Cuando alguien se queda horas extra, registralo acá.")

    with st.form("form_comp"):
        cc1, cc2 = st.columns(2)
        with cc1:
            leg_c = st.text_input("Legajo")
        with cc2:
            nom_c = padron_dict.get(leg_c.strip(), "")
            if nom_c:
                st.markdown(f'<div class="nombre-display">✅ {nom_c}</div>', unsafe_allow_html=True)
            elif leg_c.strip():
                st.warning("Legajo no encontrado.")

        cc3, cc4 = st.columns(2)
        with cc3:
            fecha_comp = st.date_input("Fecha en que compensó", value=date.today(), format="DD/MM/YYYY")
        with cc4:
            hs_comp = st.number_input("Horas compensadas", min_value=0.5, max_value=8.0, value=1.0, step=0.5)

        obs = st.text_input("Observación (opcional)", placeholder="Ej: se quedó al final del turno")
        registra = st.text_input("Tu nombre *")

        if st.form_submit_button("✅ REGISTRAR COMPENSACIÓN", use_container_width=True, type="primary"):
            if not nom_c:
                st.error("❌ Legajo no válido.")
            elif not registra.strip():
                st.error("❌ Falta tu nombre.")
            else:
                try:
                    guardar_compensacion(gc, {
                        "id": generar_id("C"),
                        "fecha_compensacion": fecha_comp.strftime("%Y-%m-%d"),
                        "legajo": leg_c.strip(),
                        "nombre": nom_c,
                        "horas_compensadas": hs_comp,
                        "observacion": obs,
                        "registrado_por": registra.strip(),
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success(f"✅ {nom_c} — {hs_comp}h compensadas el {fecha_comp.strftime('%d/%m/%Y')}")
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    # Detalle del período
    st.markdown("---")
    st.markdown("**Detalle de permisos del período**")
    if not p_f.empty:
        det = p_f[["fecha", "legajo", "nombre", "hora_salida", "hora_entrada",
                    "sin_retorno", "motivo", "compensa", "horas_redondeadas"]].copy()
        det["fecha"] = det["fecha"].dt.strftime("%d/%m/%Y")
        det.columns = ["Fecha", "Legajo", "Nombre", "Salida", "Entrada", "S/R", "Motivo", "Compensa", "Hs."]
        st.dataframe(det, use_container_width=True, hide_index=True)
    else:
        st.info("No hay permisos en este período.")


# ═══════════════════════════════════════════════════════════════
# ANÁLISIS DE DATOS
# ═══════════════════════════════════════════════════════════════
elif pagina == "📊 Análisis":

    st.markdown("## 📊 Análisis de Permisos")
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

    st.markdown("---")

    # 1. Permisos por semana
    st.markdown("**Permisos registrados por semana**")
    sem = df.groupby("año_semana").size().reset_index(name="cantidad")
    fig1 = px.bar(
        sem, x="año_semana", y="cantidad", text="cantidad",
        labels={"año_semana": "Semana", "cantidad": "Permisos"},
        color_discrete_sequence=["#1B4F9B"],
    )
    fig1.update_traces(textposition="outside")
    fig1.update_layout(plot_bgcolor="white", height=270, margin=dict(t=10, b=10))
    st.plotly_chart(fig1, use_container_width=True)
    st.caption(f"Promedio semanal: **{sem['cantidad'].mean():.1f} permisos**")

    st.markdown("---")

    # 2. Pareto de motivos (los que explican el 80%)
    st.markdown("**¿Por qué salen? — Motivos principales**")
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
    top1 = pareto.iloc[-1]
    st.caption(
        f"**{top1['Motivo']}** es el motivo más frecuente ({top1['Cantidad']} veces). "
        f"Estos {len(pareto)} motivos explican el 80% de los permisos."
    )

    st.markdown("---")

    # 3. Duración de los permisos
    st.markdown("**¿Cuánto tiempo suelen estar fuera?**")
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
            fig3.update_layout(plot_bgcolor="white", height=250, margin=dict(t=10, b=10))
            st.plotly_chart(fig3, use_container_width=True)
        with cd2:
            st.dataframe(c[["Rango", "Cantidad", "Pct"]].rename(columns={"Pct": "%"}),
                         use_container_width=True, hide_index=True)
            mayor = c.loc[c["Cantidad"].idxmax()]
            st.caption(f"El **{mayor['Pct']}%** son permisos de {mayor['Rango'].lower()}.")

    st.markdown("---")

    # 4. ¿Compensan o no?
    st.markdown("**¿Compensan o no compensan?**")
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

    st.markdown("---")
    st.caption("Análisis automático basado en los datos de Google Sheets.")
