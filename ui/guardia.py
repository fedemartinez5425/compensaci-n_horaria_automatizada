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
    TOPE_HORAS_POR_PERMISO_BSAS,
)
from services.permisos_service import (
    redondear_horas, minutos_entre, fmt_dur, fmt_horas,
    generar_id, validar_permiso, obtener_tope,
    horas_comprometidas_año, horas_fuera_tope_año,
    puede_compensar_por_politica, excede_tope_por_permiso,
    obtener_hora_fin_turno, excepcion_horario_activa, hora_fin_normal,
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


def _registros_de_hoy(permisos_activos: pd.DataFrame):
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
    config_horarios: pd.DataFrame,
):
    st.title(f"🛡️ {_label_planta(planta_activa)}")
    st.markdown(
        "Buscá a la persona y completá los datos del permiso.",
        help="Este panel es para uso exclusivo del guardia de seguridad."
    )
    st.divider()

    # Desde "Total Empresa" no se carga: no hay una política de planta que
    # aplicar (ni tope, ni motivos, ni Sin Retorno) y el registro quedaría
    # con planta="Total", invisible en las vistas de San Juan y Bs. As.
    if es_total:
        st.info(
            "Para cargar un permiso, elegí la planta (**Fábrica San Juan** o "
            "**Casa Central Bs. As.**) en el menú de la izquierda. "
            "Desde *Total Empresa* solo se pueden consultar los registros."
        )
        _registros_de_hoy(permisos_activos)
        return

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
    # Fin de turno vigente HOY para esta persona/planta: el normal de la
    # planta o un horario especial del Panel RRHH (por días, solo para
    # algunas personas o con excluidos). El cálculo final al guardar usa la
    # fecha real del permiso, no necesariamente hoy.
    # San Juan: S/R bloquea la entrada y calcula contra este horario.
    # Bs. As.: S/R solo SUGIERE este horario como entrada; el guardia la
    # puede cambiar porque carga la hora real en que terminó la jornada.
    _hora_fin_hoy = obtener_hora_fin_turno(config_horarios, key_planta, date.today(), legajo=legajo_resuelto)
    _exc_activa   = excepcion_horario_activa(config_horarios, key_planta, date.today(), legajo=legajo_resuelto)
    if _exc_activa:
        _para = f" para {nombre_resuelto}" if _exc_activa["solo_legajos"] and nombre_resuelto else ""
        st.caption(
            f"🕐 Horario especial vigente{_para}: fin de turno **{_hora_fin_hoy.strftime('%H:%M')}hs** "
            f"— {_exc_activa['descripcion']} (hasta {_exc_activa['hasta'].strftime('%d/%m/%Y')})"
        )
    elif legajo_resuelto:
        # Puede que haya una excepción activa para la planta pero esta
        # persona esté en la lista de excluidos — avisamos por qué.
        _exc_sin_filtro = excepcion_horario_activa(config_horarios, key_planta, date.today())
        if _exc_sin_filtro and legajo_resuelto in _exc_sin_filtro.get("excluidos", []):
            st.caption(
                f"ℹ️ {nombre_resuelto} está exceptuada del horario especial "
                f"'{_exc_sin_filtro['descripcion']}' — sigue con el horario normal "
                f"({_hora_fin_hoy.strftime('%H:%M')}hs)."
            )

    cs1, cs2 = st.columns([2, 1])
    with cs1:
        hora_salida_pre = st.time_input("🚪 Hora de salida *", value=time(8, 0), step=60, key="hora_sal_pre")
    with cs2:
        sin_retorno_pre = st.checkbox("🔴 Sin retorno\n(no volvió)", value=False, key="sr_pre")

    # En San Juan, Sin Retorno bloquea el campo y calcula contra el fin de
    # turno. En Bs. As., Sin Retorno solo propone el fin de jornada de esa
    # persona: el campo queda siempre editable.
    _sr_bloqueado  = sin_retorno_pre and es_sj
    _sr_sugerido   = sin_retorno_pre and not es_sj
    valor_entrada  = _hora_fin_hoy if sin_retorno_pre else time(9, 0)

    if _sr_sugerido:
        st.caption(
            f"ℹ️ En Bs. As., 'Sin retorno' propone el fin de jornada de hoy para esta persona "
            f"(**{_hora_fin_hoy.strftime('%H:%M')}hs**). Si terminó a otra hora, cambiala abajo."
        )

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
    if _sr_bloqueado and hora_salida_pre < _hora_fin_hoy:
        mins = minutos_entre(hora_salida_pre, _hora_fin_hoy)
        hrs  = redondear_horas(mins)
        st.info(
            f"🔴 Sin retorno — {hora_salida_pre.strftime('%H:%M')} → {_hora_fin_hoy.strftime('%H:%M')} "
            f"= **{fmt_dur(mins)}** → "
            + (f"**{int(hrs)}h a compensar**" if compensa_pre == "SI" else "no compensa")
        )
    elif not _sr_bloqueado and valor_entrada > hora_salida_pre:
        mins = minutos_entre(hora_salida_pre, valor_entrada)
        hrs  = redondear_horas(mins)
        st.info(
            f"⏱ Tiempo real: **{fmt_dur(mins)}** → Horas a compensar: **{int(hrs)}h**"
        )

    # ── Formulario ───────────────────────────────────────────
    with st.form("form_guardia", clear_on_submit=True):
        fecha_permiso  = st.date_input("📅 Fecha", value=date.today(),
                                        max_value=date.today(), format="DD/MM/YYYY")
        if _sr_bloqueado:
            _label_entrada = f"🏁 Hora de entrada (automático {_hora_fin_hoy.strftime('%H:%M')} — Sin retorno)"
        elif _sr_sugerido:
            _label_entrada = f"🏁 Hora de fin de jornada (sugerida {_hora_fin_hoy.strftime('%H:%M')} — Sin retorno)"
        else:
            _label_entrada = "🏁 Hora de entrada"
        hora_entrada   = st.time_input(_label_entrada, value=valor_entrada, step=60, disabled=_sr_bloqueado)
        registrado_por = st.text_input("👮 Tu nombre *", placeholder="Ej: García Juan")

        submitted = st.form_submit_button("💾 GUARDAR REGISTRO", use_container_width=True, type="primary")

        if submitted:
            motivo_final = motivo_otro.strip() if motivo_sel == "Otro" and motivo_otro.strip() else motivo_sel

            # Horario de fin de turno efectivo según la FECHA REAL del permiso
            # (no la de hoy) — solo aplica a San Juan. Bs. As. no fuerza
            # ningún horario; usa siempre la hora real que cargó el guardia.
            if es_sj:
                _hora_fin_efectiva = obtener_hora_fin_turno(
                    config_horarios, key_planta, fecha_permiso, legajo=legajo_resuelto
                )
            else:
                _hora_fin_efectiva = hora_fin_normal(key_planta)  # no se usa (sin_retorno=False acá abajo)

            errores = validar_permiso(
                nombre_resuelto, registrado_por,
                _sr_bloqueado, hora_salida_pre, hora_entrada,
                hora_fin_turno=_hora_fin_efectiva,
            )
            if not nombre_resuelto:
                errores.insert(0, "Seleccioná o buscá a la persona primero.")

            # Calcular horas ANTES de validar, para poder chequear el
            # tope por permiso individual de Bs. As. (política 036).
            if _sr_bloqueado:
                mins_r  = minutos_entre(hora_salida_pre, _hora_fin_efectiva)
                hrs_r   = redondear_horas(mins_r) if compensa_pre == "SI" else 0.0
                ent_str = "S/R"
            else:
                mins_r  = minutos_entre(hora_salida_pre, hora_entrada)
                hrs_r   = redondear_horas(mins_r)
                ent_str = hora_entrada.strftime("%H:%M")

            # El tope de arriba se mostró con el año de HOY. Si el permiso es
            # de otro año (ej: en enero se carga uno de diciembre), se vuelve
            # a controlar contra el año real del permiso.
            if compensa_pre == "SI" and legajo_resuelto and fecha_permiso.year != date.today().year:
                _año_p = fecha_permiso.year
                if es_sj and es_motivo_ext:
                    if horas_fuera_tope_año(permisos_activos, legajo_resuelto, _año_p) >= TOPE_EXTRA_FUERA_TOPE:
                        errores.append(
                            f"En {_año_p} {nombre_resuelto} ya había usado las {TOPE_EXTRA_FUERA_TOPE}h "
                            "del cupo especial. Marcá 'NO' en ¿Va a compensar?"
                        )
                else:
                    _tope_p = obtener_tope("SI" if es_lider_persona else "NO", key_planta)
                    if horas_comprometidas_año(permisos_activos, legajo_resuelto, _año_p) >= _tope_p:
                        errores.append(
                            f"En {_año_p} {nombre_resuelto} ya había alcanzado el tope de "
                            f"{_tope_p:.0f}h. Marcá 'NO' en ¿Va a compensar?"
                        )

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
    _registros_de_hoy(permisos_activos)

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
            _planta_def  = 0 if es_sj else 1
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
                if not padron.empty and nvo_leg.strip() in set(padron["legajo"]):
                    err.append(f"Ya existe una persona con legajo {nvo_leg.strip()} en el padrón.")
                if err:
                    for e in err:
                        st.error(f"❌ {e}")
                else:
                    try:
                        _sin_guardar = agregar_empleado(gc, nvo_leg.strip(), nom_clean,
                                                        nvo_sec, nvo_planta, nvo_cla, nvo_lider)
                        st.success(f"✅ {nom_clean} agregado. Recargá la página.")
                        if "es_lider" in _sin_guardar and nvo_lider == "SI":
                            st.warning(
                                "El padrón no tiene la columna 'es_lider', así que no quedó "
                                "marcada como líder. Agregá esa columna en la hoja 'padron' "
                                "y poné SI en su fila."
                            )
                    except Exception as e:
                        st.error(f"❌ Error: {e}")