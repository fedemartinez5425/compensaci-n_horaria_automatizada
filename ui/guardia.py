"""
ui/guardia.py
─────────────────────────────────────────────────────────────────
Panel de carga del guardia de seguridad.
Solo lógica de presentación — delega cálculos a services y
escritura a repositories.
"""
import streamlit as st
import pandas as pd
from datetime import date, time, datetime

from config import (
    MOTIVOS_LISTA, MOTIVOS_FUERA_TOPE, TOPE_EXTRA_FUERA_TOPE,
    MOTIVOS_COMPENSAN_SJ, MOTIVOS_COMPENSAN_LIDERES_SJ,
    MOTIVOS_COMPENSAN_BSAS, HORA_FIN_TURNO,
    TOPE_HORAS_POR_PERMISO_BSAS,
)
from services.permisos_service import (
    redondear_horas, minutos_entre, fmt_dur, fmt_horas,
    generar_id, validar_permiso, obtener_tope,
    horas_comprometidas_año, horas_fuera_tope_año,
    puede_compensar_por_politica, excede_tope_por_permiso,
)
from repositories.sheets_repo import (
    guardar_permiso, agregar_empleado,
)


def _label_planta(planta_activa: str) -> str:
    if "San Juan" in planta_activa:
        return "Hola — Fábrica San Juan"
    elif "Bs." in planta_activa:
        return "Hola — Casa Central Bs. As."
    return "Hola — Vista Total"


def render(
    gc,
    planta_activa: str,
    key_planta: str,
    es_sj: bool,
    es_total: bool,
    padron: pd.DataFrame,
    padron_activos: pd.DataFrame,
    permisos_activos: pd.DataFrame,
    padron_dict: dict,
    nombre_a_legajo: dict,
    nombres_lista: list,
):
    st.title(f"🛡️ {_label_planta(planta_activa)}")
    st.markdown(
        "Buscá a la persona y completá los datos del permiso.",
        help="Este panel es para uso exclusivo del guardia de seguridad."
    )
    st.divider()

    # ── Búsqueda por nombre ──────────────────────────────────
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
        c1, c2 = st.columns(2)
        c1.success(f"✅ **{nombre_resuelto}**")
        c2.info(f"Legajo: **{legajo_resuelto}**" if legajo_resuelto else "Sin legajo")

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

    # ── Motivo y política ────────────────────────────────────
    motivo_sel = st.selectbox("📋 Motivo de salida *", MOTIVOS_LISTA, key="motivo_pre")
    motivo_otro = ""
    if motivo_sel == "Otro":
        motivo_otro = st.text_input(
            "✏️ Especificá el motivo",
            placeholder="Ej: Trámite bancario especial",
            max_chars=80,
            key="motivo_otro_pre",
        )

    # Determinar si la persona es líder
    es_lider_persona = False
    if legajo_resuelto and not padron_activos.empty:
        vals = padron_activos[padron_activos["legajo"] == legajo_resuelto]["es_lider"].values
        es_lider_persona = len(vals) > 0 and str(vals[0]).upper() == "SI"

    # Evaluar política
    puede_compensar = puede_compensar_por_politica(motivo_sel, key_planta, es_lider_persona)
    if not puede_compensar:
        planta_nombre = "San Juan" if es_sj else "Bs. As."
        st.info(
            f"ℹ️ **{motivo_sel}** no está contemplado en la política de {planta_nombre} "
            "— se registrará como **No compensa** automáticamente."
        )

    # ── Hora salida y Sin Retorno (fuera del form para reactividad) ──
    cs1, cs2 = st.columns([2, 1])
    with cs1:
        hora_salida_pre = st.time_input("🚪 Hora de salida *", value=time(8, 0), step=60, key="hora_sal_pre")
    with cs2:
        sin_retorno_pre = st.checkbox("🔴 Sin retorno\n(no volvió)", value=False, key="sr_pre")

    valor_entrada = HORA_FIN_TURNO if sin_retorno_pre else time(9, 0)

    # ── Chequeo de tope anual ────────────────────────────────
    tope_alcanzado     = False
    es_motivo_ext      = motivo_sel in MOTIVOS_FUERA_TOPE

    if legajo_resuelto and es_sj:
        año_actual = date.today().year
        _es_lid    = "SI" if es_lider_persona else "NO"
        _tope      = obtener_tope(_es_lid)
        _consumi   = horas_comprometidas_año(permisos_activos, legajo_resuelto, año_actual)
        _ext_usad  = horas_fuera_tope_año(permisos_activos, legajo_resuelto, año_actual)

        if es_motivo_ext:
            _disp_ext = max(0, TOPE_EXTRA_FUERA_TOPE - _ext_usad)
            if _disp_ext > 0:
                st.caption(
                    f"⭐ Cupo especial: **{_ext_usad:.1f}h / {TOPE_EXTRA_FUERA_TOPE}h** usadas este año."
                )
            else:
                tope_alcanzado  = True
                puede_compensar = False
                st.warning(
                    f"⚠️ **{nombre_resuelto}** ya usó las {TOPE_EXTRA_FUERA_TOPE}h del cupo especial "
                    f"en {año_actual}. Se registra como No compensa."
                )
        else:
            st.caption(
                f"📊 Tope {año_actual}: **{_consumi:.1f}h / {_tope:.0f}h** "
                f"{'(líder)' if _es_lid == 'SI' else ''}"
            )
            if _consumi >= _tope:
                tope_alcanzado  = True
                puede_compensar = False
                st.warning(
                    f"⚠️ **{nombre_resuelto}** alcanzó el tope de {_tope:.0f}h en {año_actual} "
                    f"({_consumi:.1f}h acumuladas). Se registra como No compensa."
                )

    elif legajo_resuelto and key_planta == "Casa Central":
        # Política 036 — no distingue líder, tope fijo de 10h/año.
        año_actual = date.today().year
        _tope    = obtener_tope("NO", key_planta)
        _consumi = horas_comprometidas_año(permisos_activos, legajo_resuelto, año_actual)
        st.caption(
            f"📊 Tope {año_actual}: **{_consumi:.1f}h / {_tope:.0f}h** — política Bs. As. (036)"
        )
        st.caption(f"⚠️ Máximo por permiso individual: **{TOPE_HORAS_POR_PERMISO_BSAS}h**")
        if _consumi >= _tope:
            tope_alcanzado  = True
            puede_compensar = False
            st.warning(
                f"⚠️ **{nombre_resuelto}** alcanzó el tope de {_tope:.0f}h en {año_actual} "
                f"({_consumi:.1f}h acumuladas). Se registra como No compensa."
            )

    # Radio compensa — fuera del form para reactividad
    if puede_compensar:
        compensa_pre = st.radio(
            "💰 ¿Va a compensar las horas?",
            ["SI", "NO"],
            horizontal=True,
            key="compensa_pre",
            help="SI = se queda horas extra otro día. NO = no se descuenta.",
        )
    else:
        compensa_pre = "NO"
        if not tope_alcanzado:
            st.markdown("💰 **No compensa** — automático por política.")

    # ── Previsualización ────────────────────────────────────
    if sin_retorno_pre and hora_salida_pre < HORA_FIN_TURNO:
        mins = minutos_entre(hora_salida_pre, HORA_FIN_TURNO)
        hrs  = redondear_horas(mins)
        st.info(
            f"🔴 Sin retorno — {hora_salida_pre.strftime('%H:%M')} → 15:00 "
            f"= **{fmt_dur(mins)}** → "
            + (f"**{int(hrs)}h a compensar**" if compensa_pre == "SI" else "no compensa")
        )
    elif not sin_retorno_pre and valor_entrada > hora_salida_pre:
        mins = minutos_entre(hora_salida_pre, valor_entrada)
        hrs  = redondear_horas(mins)
        st.info(
            f"⏱ Tiempo real: **{fmt_dur(mins)}** → Horas a compensar: **{int(hrs)}h**"
        )

    # ── Formulario ───────────────────────────────────────────
    with st.form("form_guardia", clear_on_submit=True):
        fecha_permiso  = st.date_input("📅 Fecha", value=date.today(),
                                        max_value=date.today(), format="DD/MM/YYYY")
        hora_entrada   = st.time_input(
            "🏁 Hora de entrada" + (" (automático 15:00 — Sin retorno)" if sin_retorno_pre else ""),
            value=valor_entrada, step=60, disabled=sin_retorno_pre,
        )
        registrado_por = st.text_input("👮 Tu nombre *", placeholder="Ej: García Juan")

        submitted = st.form_submit_button("💾 GUARDAR REGISTRO", use_container_width=True, type="primary")

        if submitted:
            motivo_final = motivo_otro.strip() if motivo_sel == "Otro" and motivo_otro.strip() else motivo_sel
            errores = validar_permiso(
                nombre_resuelto, registrado_por,
                sin_retorno_pre, hora_salida_pre, hora_entrada,
            )
            if not nombre_resuelto:
                errores.insert(0, "Seleccioná o buscá a la persona primero.")

            # Calcular horas ANTES de validar, para poder chequear el
            # tope por permiso individual de Bs. As. (política 036).
            if sin_retorno_pre:
                mins_r  = minutos_entre(hora_salida_pre, HORA_FIN_TURNO)
                hrs_r   = redondear_horas(mins_r) if compensa_pre == "SI" else 0.0
                ent_str = "S/R"
            else:
                mins_r  = minutos_entre(hora_salida_pre, hora_entrada)
                hrs_r   = redondear_horas(mins_r)
                ent_str = hora_entrada.strftime("%H:%M")

            if compensa_pre == "SI" and excede_tope_por_permiso(hrs_r, key_planta):
                errores.append(
                    f"Este permiso equivale a {fmt_horas(hrs_r)}, supera el máximo de "
                    f"{TOPE_HORAS_POR_PERMISO_BSAS}h por permiso individual "
                    "(política Bs. As. 036). Dividí el trámite o marcá 'No compensa'."
                )

            if errores:
                for e in errores:
                    st.error(f"❌ {e}")
            else:
                try:
                    guardar_permiso(gc, {
                        "id":               generar_id("P"),
                        "fecha":            fecha_permiso.strftime("%Y-%m-%d"),
                        "legajo":           legajo_resuelto,
                        "nombre":           nombre_resuelto,
                        "hora_salida":      hora_salida_pre.strftime("%H:%M"),
                        "hora_entrada":     ent_str,
                        "sin_retorno":      "SI" if sin_retorno_pre else "NO",
                        "motivo":           motivo_final,
                        "compensa":         compensa_pre,
                        "minutos_reales":   round(mins_r, 1),
                        "horas_redondeadas": hrs_r,
                        "registrado_por":   registrado_por.strip(),
                        "planta":           key_planta,
                        "timestamp":        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success(f"✅ Guardado — {nombre_resuelto}")
                    if compensa_pre == "SI":
                        st.info(f"Tiempo fuera: {fmt_dur(mins_r)} → **{int(hrs_r)}h a compensar**")
                    else:
                        st.info(f"Tiempo fuera: {fmt_dur(mins_r)} — no compensa")
                except Exception as e:
                    st.error(f"❌ Error al guardar: {e}")

    # ── Registros de hoy ─────────────────────────────────────
    st.divider()
    st.subheader("Registros de hoy")
    if not permisos_activos.empty:
        hoy = permisos_activos[permisos_activos["fecha"].dt.date == date.today()]
        if hoy.empty:
            st.caption("Aún no hay registros hoy.")
        else:
            hs = hoy[["nombre", "hora_salida", "hora_entrada",
                       "sin_retorno", "motivo", "compensa", "horas_redondeadas"]].copy()
            hs.columns = ["Nombre", "Salida", "Entrada", "S/R", "Motivo", "Compensa", "Hs."]
            st.dataframe(hs, use_container_width=True, hide_index=True)
    else:
        st.caption("No hay registros aún.")

    # ── Agregar empleado nuevo ───────────────────────────────
    st.divider()
    st.subheader("Agregar empleado nuevo")
    with st.expander("➕ Agregar empleado que no está en la lista"):
        st.markdown(
            "Usá esto **solo** si la persona no aparece arriba. "
            "El nombre debe ser único y completo (Apellido, Nombre)."
        )
        _sectores = sorted([s for s in padron["sector"].dropna().unique()
                            if s and s not in ("", "nan")]) if not padron.empty else []
        _clasifs  = sorted([c for c in padron["clasificacion"].dropna().unique()
                            if c and c not in ("", "nan")]) if not padron.empty else []
        if not _sectores:
            _sectores = ["COSTURA SAN JUAN", "CALIDAD", "ABASTECIMIENTO", "OTRO"]
        if not _clasifs:
            _clasifs  = ["HOURLY DIRECT", "HOURLY INDIRECT", "EXEMPT", "NON EXEMPT"]

        with st.form("form_nuevo"):
            cn1, cn2 = st.columns(2)
            with cn1:
                nvo_leg = st.text_input("Legajo *", placeholder="Ej: 3050")
            with cn2:
                nvo_nom = st.text_input("Apellido y Nombre *",
                                         placeholder="Ej: GOMEZ, CARLOS ALBERTO")
            na1, na2 = st.columns(2)
            with na1:
                nvo_sec = st.selectbox("Sector *", _sectores)
            with na2:
                nvo_cla = st.selectbox("Clasificación *", _clasifs)
            _planta_opts = ["Fábrica", "Casa Central"]
            _planta_def  = 0 if es_sj else (1 if not es_total else 0)
            nvo_planta   = st.selectbox("Planta *", _planta_opts, index=_planta_def)
            nvo_lider    = st.radio("¿Es líder?", ["NO", "SI"], horizontal=True)

            if st.form_submit_button("Agregar al padrón", use_container_width=True):
                nom_clean = nvo_nom.strip().upper()
                err = []
                if not nvo_leg.strip():
                    err.append("El legajo es obligatorio.")
                if not nom_clean:
                    err.append("El nombre es obligatorio.")
                if nom_clean in nombre_a_legajo:
                    err.append(f"Ya existe '{nom_clean}'. Agregá segundo nombre o apellido.")
                if err:
                    for e in err:
                        st.error(f"❌ {e}")
                else:
                    try:
                        agregar_empleado(gc, nvo_leg.strip(), nom_clean,
                                         nvo_sec, nvo_planta, nvo_cla, nvo_lider)
                        st.success(f"✅ {nom_clean} agregado. Recargá la página.")
                    except Exception as e:
                        st.error(f"❌ Error: {e}")
