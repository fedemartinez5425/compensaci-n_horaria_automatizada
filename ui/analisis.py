"""
ui/analisis.py
─────────────────────────────────────────────────────────────────
Panel de Análisis — módulo OLAP del sistema.
Paleta visual consistente, filtros independientes por sección,
ayuda contextual desplegable. KPI acumulado de compensación.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date

from config import AÑOS, MESES, COLORES, ALMUERZO_H, MOTIVOS_FUERA_TOPE
from services.permisos_service import fmt_horas, kpi_compensacion_acumulado
from services.analytics_service import (
    filtrar_mod, filtrar_rango_fecha,
    resumen_mod_diario, resumen_mod_nc_diario, detalle_mod_nc_por_persona,
    tiempo_no_productivo, calcular_pareto, tabla_duracion, ORDEN_DURACION,
)

# ─────────────────────────────────────────────
# HELPERS VISUALES — paleta consistente
# ─────────────────────────────────────────────
_AZ  = COLORES["primario"]
_AZ2 = COLORES["secundario"]
_RJ  = COLORES["acento"]
_VD  = COLORES["ok"]
_GR  = COLORES["neutro"]
_NA  = COLORES["advertencia"]

_LAYOUT_BASE = dict(
    plot_bgcolor="white",
    paper_bgcolor="white",
    font=dict(family="Arial", size=12, color="#2C3E50"),
    margin=dict(t=40, b=20, l=10, r=10),
    showlegend=False,
)


def _colores_destacar(serie, color_base=_AZ, color_destaque=_RJ):
    """El valor más alto en rojo, el resto en azul."""
    max_v = serie.max()
    return [color_destaque if v == max_v else color_base for v in serie]


def _ayuda(titulo: str, contenido: str):
    with st.expander(f"ℹ️ {titulo}", expanded=False):
        st.markdown(contenido)


def _caption(text: str):
    st.markdown(
        f'<p style="color:#2C3E50;font-size:0.95rem;margin-top:-4px;">{text}</p>',
        unsafe_allow_html=True,
    )


# ─────────────────────────────────────────────
# RENDER PRINCIPAL
# ─────────────────────────────────────────────
def render(
    planta_activa: str,
    permisos_planta: pd.DataFrame,
    permisos_activos: pd.DataFrame,
    comp_activos: pd.DataFrame,
    sector_dict: dict,
    clasif_dict: dict,
):
    st.title(f"📊 Análisis de Permisos — {planta_activa}")
    _caption("Panel analítico. Cada sección tiene sus propios filtros y puede explorarse de forma independiente.")
    st.divider()

    if permisos_planta.empty:
        st.warning("No hay datos para analizar en esta planta.")
        return

    # ══════════════════════════════════════════
    # KPI ACUMULADO DE COMPENSACIÓN
    # ══════════════════════════════════════════
    st.subheader("🎯 KPI de Compensación — Acumulado a hoy")
    _ayuda("¿Qué mide este KPI?",
        """
**Qué es:** el porcentaje de horas comprometidas a compensar que el equipo efectivamente recuperó,
calculado sobre **todos los datos históricos hasta hoy** (no por mes).

**Cómo se calcula:**
```
% Cumplimiento = Horas compensadas ÷ Horas comprometidas (compensa=SI) × 100
```

**Cómo interpretarlo:**
- 🟢 > 70%: buen ritmo de recuperación
- 🟡 40–70%: ritmo moderado, hay deuda acumulada
- 🔴 < 40%: la deuda crece más rápido que la recuperación

**Para qué sirve:** permite a RRHH evaluar si el equipo está cumpliendo con las compensaciones
o si la deuda se está acumulando sin recuperarse.
        """
    )

    kpi = kpi_compensacion_acumulado(permisos_activos, comp_activos)
    if kpi["hs_comprometidas"] > 0:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Hs. comprometidas (total)", fmt_horas(kpi["hs_comprometidas"]))
        k2.metric("Hs. recuperadas",           fmt_horas(kpi["hs_recuperadas"]))
        k3.metric("⏳ Hs. pendientes",          fmt_horas(kpi["hs_pendientes"]))
        k4.metric("✅ % Cumplimiento",          f"{kpi['pct']:.1f}%")

        # Barra de progreso visual
        fig_kpi = go.Figure(go.Bar(
            x=[kpi["pct"]], y=["Cumplimiento"],
            orientation="h",
            marker_color=_VD if kpi["pct"] >= 70 else (_NA if kpi["pct"] >= 40 else _RJ),
            text=[f"{kpi['pct']:.1f}%"],
            textposition="inside",
        ))
        fig_kpi.update_layout(
            **_LAYOUT_BASE,
            height=80,
            xaxis=dict(range=[0, 100], showticklabels=False),
            yaxis=dict(showticklabels=False),
        )
        st.plotly_chart(fig_kpi, use_container_width=True)
    else:
        st.info("No hay datos suficientes para calcular el KPI.")

    st.divider()

    # ══════════════════════════════════════════
    # 1. PERMISOS POR SEMANA
    # ══════════════════════════════════════════
    st.subheader("📅 Permisos por semana")

    with st.container():
        fw1, fw2 = st.columns(2)
        with fw1:
            años_disp = sorted(permisos_planta["fecha"].dt.year.dropna().unique().astype(int).tolist())
            año_sem = st.multiselect("Año", años_disp, default=años_disp, key="fil_sem_año")
        with fw2:
            st.empty()

    _ayuda("Cómo interpretar el gráfico de permisos por semana",
        """
**Qué muestra:** la cantidad de permisos de salida registrados por semana.
La barra en rojo es la semana con más permisos (pico de ausentismo).
La línea punteada es el promedio.

**Para qué sirve:** detectar patrones temporales — semanas con alta demanda de permisos,
coincidencias con fechas particulares (quincena, inicio de mes, feriados).

**Cómo leerlo:** una semana con el doble del promedio merece investigación.
¿Hay algo que explique ese pico? ¿Fue inicio de ciclo escolar, turno de vacunación, etc.?
        """
    )

    df_sem = permisos_planta[permisos_planta["fecha"].dt.year.isin(año_sem)].copy() if año_sem else pd.DataFrame()
    if not df_sem.empty:
        df_sem["año_semana"] = df_sem["fecha"].dt.strftime("%Y-S%V")
        sem = df_sem.groupby("año_semana").size().reset_index(name="cantidad")
        prom = sem["cantidad"].mean()
        fig1 = go.Figure(go.Bar(
            x=sem["año_semana"], y=sem["cantidad"],
            text=sem["cantidad"], textposition="outside",
            marker_color=_colores_destacar(sem["cantidad"]),
            hovertemplate="%{x}: %{y} permisos<extra></extra>",
        ))
        fig1.add_hline(y=prom, line_dash="dash", line_color=_GR,
                       annotation_text=f"Prom: {prom:.1f}", annotation_position="top left")
        fig1.update_layout(**_LAYOUT_BASE, height=280, xaxis_title="", yaxis_title="Permisos")
        st.plotly_chart(fig1, use_container_width=True)
        semana_pico = sem.loc[sem["cantidad"].idxmax(), "año_semana"]
        _caption(f"Promedio semanal: **{prom:.1f} permisos** — Pico: **{semana_pico}** 🔴")
    else:
        st.info("Sin datos para el período seleccionado.")

    st.divider()

    # ══════════════════════════════════════════
    # 2. PERMISOS POR MES
    # ══════════════════════════════════════════
    st.subheader("📆 Permisos por mes")

    fm1, fm2 = st.columns(2)
    with fm1:
        año_mes_fil = st.multiselect("Año", años_disp, default=años_disp, key="fil_mes_año")

    _ayuda("Cómo interpretar permisos por mes",
        """
**Qué muestra:** total de permisos por mes calendario.

**Para qué sirve:** comparar estacionalidad entre meses. Detectar si enero tiene
sistemáticamente menos permisos que marzo (patrones de largo plazo).

**Diferencia con el gráfico por semana:** el gráfico mensual suaviza variaciones
semanales y permite ver tendencias más amplias.
        """
    )

    df_mes = permisos_planta[permisos_planta["fecha"].dt.year.isin(año_mes_fil)].copy() if año_mes_fil else pd.DataFrame()
    if not df_mes.empty:
        df_mes["mes_label"] = df_mes["fecha"].dt.strftime("%Y-%m")
        mes_g = df_mes.groupby("mes_label").size().reset_index(name="cantidad")
        fig_mes = go.Figure(go.Bar(
            x=mes_g["mes_label"], y=mes_g["cantidad"],
            text=mes_g["cantidad"], textposition="outside",
            marker_color=_colores_destacar(mes_g["cantidad"]),
            hovertemplate="%{x}: %{y} permisos<extra></extra>",
        ))
        fig_mes.update_layout(**_LAYOUT_BASE, height=270, xaxis_title="", yaxis_title="Permisos")
        st.plotly_chart(fig_mes, use_container_width=True)
    else:
        st.info("Sin datos.")

    st.divider()

    # ══════════════════════════════════════════
    # 3. PARETO DE MOTIVOS — bug corregido
    # ══════════════════════════════════════════
    st.subheader("📋 Motivos principales — Pareto 80%")

    fp1, fp2 = st.columns(2)
    with fp1:
        año_par = st.multiselect("Año", años_disp, default=años_disp, key="fil_par_año")
    with fp2:
        clasifs_disp = sorted(permisos_planta["compensa"].dropna().unique().tolist())
        comp_par = st.multiselect("Compensa", ["SI", "NO"], default=["SI", "NO"], key="fil_par_comp")

    _ayuda("Cómo interpretar el Pareto de motivos",
        """
**Qué es Pareto:** el principio dice que el 20% de los motivos explica el 80% de los casos.
Este gráfico muestra exactamente qué motivos representan el 80% de los permisos.

**Cómo se calcula:**
1. Se cuentan los permisos por motivo (de mayor a menor).
2. Se acumula el porcentaje hasta llegar al 80%.
3. Solo se muestran los motivos que entran en ese 80%.

**Para qué sirve:** focalizar las acciones de RRHH en los motivos que más impactan.
Si "Banco / Cajero" representa el 40% de los permisos, quizás hay una oportunidad
de coordinar permisos bancarios en horarios menos críticos para producción.
        """
    )

    df_par = permisos_planta[
        permisos_planta["fecha"].dt.year.isin(año_par) &
        permisos_planta["compensa"].isin(comp_par)
    ].copy() if año_par else pd.DataFrame()

    if not df_par.empty:
        pareto = calcular_pareto(df_par)
        if not pareto.empty:
            # FIX: el top1 es el último de la lista (categoryorder ascending = mayor arriba)
            # El gráfico muestra de menor a mayor (yaxis ascending), entonces
            # el más frecuente queda arriba. top1 = fila con mayor Cantidad.
            top1 = pareto.loc[pareto["Cantidad"].idxmax()]

            colores_par = [_RJ if v == pareto["Cantidad"].max() else _AZ2
                           for v in pareto["Cantidad"]]
            fig2 = go.Figure(go.Bar(
                x=pareto["Cantidad"], y=pareto["Motivo"],
                orientation="h", text=pareto["Cantidad"], textposition="outside",
                marker_color=colores_par,
                hovertemplate="%{y}: %{x} veces<extra></extra>",
            ))
            fig2.update_layout(
                **_LAYOUT_BASE,
                height=max(260, len(pareto) * 44),
                xaxis_title="Cantidad",
                yaxis=dict(categoryorder="total ascending"),
            )
            st.plotly_chart(fig2, use_container_width=True)
            # Interpretación construida desde los MISMOS datos del gráfico
            _caption(
                f"**{top1['Motivo']}** es el motivo más frecuente con **{top1['Cantidad']} permisos**. "
                f"Estos {len(pareto)} motivos explican el 80% del total."
            )
        else:
            st.info("No hay datos suficientes para el Pareto.")
    else:
        st.info("Sin datos para los filtros seleccionados.")

    st.divider()

    # ══════════════════════════════════════════
    # 4. DURACIÓN DE PERMISOS
    # ══════════════════════════════════════════
    st.subheader("⏱ ¿Cuánto tiempo suelen estar fuera?")

    fd1, fd2 = st.columns(2)
    with fd1:
        año_dur = st.multiselect("Año", años_disp, default=años_disp, key="fil_dur_año")
    with fd2:
        sector_opts = ["Todos"] + sorted([s for s in permisos_planta["legajo"].map(sector_dict).dropna().unique()
                                          if s and s != "nan"])
        sector_dur = st.selectbox("Sector", sector_opts, key="fil_dur_sec")

    _ayuda("Cómo interpretar la duración de los permisos",
        """
**Qué muestra:** en qué rango de duración se concentran los permisos.

**Importante — regla de redondeo:**
Los rangos muestran los minutos REALES. El sistema luego redondea a horas enteras
según la política de fábrica (< 30 min = 0h, 30–89 min = 1h, etc.).

**Ejemplo:** un permiso en el rango "1h – 1h 30min" puede haberse redondeado a 1h o 2h
dependiendo de si los minutos extras son >= 30.

**Para qué sirve:** si la mayoría de los permisos son de menos de 30 minutos,
eso significa que en realidad no generan deuda de compensación (redondean a 0h).
Si la mayoría son de 30–60 minutos, cada uno genera 1h de deuda.
        """
    )

    df_dur = permisos_planta[permisos_planta["fecha"].dt.year.isin(año_dur)].copy() if año_dur else pd.DataFrame()
    if sector_dur != "Todos" and not df_dur.empty:
        df_dur = df_dur[df_dur["legajo"].map(sector_dict).fillna("") == sector_dur]

    if not df_dur.empty:
        tabla_d = tabla_duracion(df_dur)
        if not tabla_d.empty:
            prom_min = df_dur[df_dur["minutos_reales"].notna()]["minutos_reales"].mean()
            colores_d = [_RJ if v == tabla_d["Cantidad"].max() else _AZ for v in tabla_d["Cantidad"]]
            cd1, cd2 = st.columns([2, 1])
            with cd1:
                fig3 = go.Figure(go.Bar(
                    x=tabla_d["Rango"], y=tabla_d["Cantidad"],
                    text=tabla_d["Pct"].apply(lambda x: f"{x}%"),
                    textposition="outside",
                    marker_color=colores_d,
                    hovertemplate="%{x}: %{y} permisos (%{text})<extra></extra>",
                ))
                fig3.update_layout(**_LAYOUT_BASE, height=260,
                                   xaxis_title="", yaxis_title="Permisos")
                st.plotly_chart(fig3, use_container_width=True)
            with cd2:
                st.dataframe(
                    tabla_d[["Rango", "Cantidad", "Pct"]].rename(columns={"Pct": "%"}),
                    use_container_width=True, hide_index=True,
                )
                mayor = tabla_d.loc[tabla_d["Cantidad"].idxmax()]
                _caption(
                    f"Rango más frecuente: **{mayor['Rango']}** ({mayor['Pct']}%). "
                    f"Promedio real: **{int(prom_min // 60)}h {int(prom_min % 60):02d}min**."
                )

    st.divider()

    # ══════════════════════════════════════════
    # 5. ¿COMPENSAN O NO?
    # ══════════════════════════════════════════
    st.subheader("💰 ¿Compensan o no compensan?")

    fco1, fco2 = st.columns(2)
    with fco1:
        año_co = st.multiselect("Año", años_disp, default=años_disp, key="fil_co_año")

    _ayuda("Cómo interpretar el gráfico de compensación",
        """
**Qué muestra:** de todos los permisos registrados, cuántos se marcaron como
"Compensa=SI" y cuántos como "Compensa=NO".

**Importante:** esto no mide si efectivamente compensaron — mide la **intención declarada**
al momento de la salida.

Para ver cuántos de los que dijeron SI realmente compensaron, revisá el KPI de Cumplimiento
en la parte superior de esta pantalla.

**Para qué sirve:** si el porcentaje de NO es muy alto, puede indicar que muchos permisos
son por motivos que no compensan por política (ART, enfermedad, etc.).
        """
    )

    df_co = permisos_planta[permisos_planta["fecha"].dt.year.isin(año_co)].copy() if año_co else pd.DataFrame()
    if not df_co.empty:
        ratio = df_co["compensa"].value_counts().reset_index()
        ratio.columns = ["Compensa", "Cantidad"]
        total_r = ratio["Cantidad"].sum()

        fig4 = go.Figure(go.Pie(
            labels=ratio["Compensa"],
            values=ratio["Cantidad"],
            hole=0.5,
            marker_colors=[_VD if v == "SI" else _RJ for v in ratio["Compensa"]],
            textinfo="label+percent",
            hovertemplate="%{label}: %{value} (%{percent})<extra></extra>",
        ))
        fig4.update_layout(**_LAYOUT_BASE, height=260)

        cr1, cr2 = st.columns([1, 2])
        with cr1:
            st.plotly_chart(fig4, use_container_width=True)
        with cr2:
            for _, row in ratio.iterrows():
                pct = row["Cantidad"] / total_r * 100
                st.metric(
                    f"{'✅' if row['Compensa'] == 'SI' else '❌'} {row['Compensa']}",
                    f"{row['Cantidad']} permisos",
                    f"{pct:.1f}% del total",
                )

    st.divider()

    # ══════════════════════════════════════════
    # 6. MOD — HORAS NO TRABAJADAS
    # ══════════════════════════════════════════
    st.subheader("🔧 Horas no trabajadas — MOD")

    _ayuda("¿Qué es MOD y cómo se calcula?",
        """
**MOD (Mano de Obra Directa):** empleadas clasificadas como **HOURLY DIRECT** del sector **COSTURA**.
Son las que impactan directamente en la línea de producción cuando están ausentes.

**Cómo se calculan las horas:**
```
Horas del día = (Σ minutos_reales de ese día ÷ 60) − 0.5h de almuerzo
```
Se usa `minutos_reales` (decimal exacto) y no el redondeo, para mayor precisión.

**Para qué sirve:** la jefa de calidad usa este número para calcular el impacto
real en la producción del día. Cada hora aquí es una hora de producción no ejecutada.
        """
    )

    mod_col1, mod_col2 = st.columns(2)
    with mod_col1:
        mod_desde = st.date_input("📅 Desde", value=date.today().replace(day=1),
                                   max_value=date.today(), format="DD/MM/YYYY", key="mod_desde")
    with mod_col2:
        mod_hasta = st.date_input("📅 Hasta", value=date.today(),
                                   max_value=date.today(), format="DD/MM/YYYY", key="mod_hasta")

    if mod_desde > mod_hasta:
        st.warning("⚠️ 'Desde' no puede ser posterior a 'Hasta'.")
    else:
        mod_label = f"{mod_desde.strftime('%d/%m/%Y')} — {mod_hasta.strftime('%d/%m/%Y')}"
        df_mod_base = filtrar_mod(permisos_planta, sector_dict, clasif_dict)
        df_mod      = filtrar_rango_fecha(df_mod_base, mod_desde, mod_hasta)

        if df_mod.empty:
            st.info(f"No hay permisos MOD en {mod_label}.")
        else:
            res_mod = resumen_mod_diario(df_mod)
            total_mod = res_mod["Hs. no trabajadas"].sum()
            tm1, tm2, tm3 = st.columns(3)
            tm1.metric("Total hs. no trabajadas (MOD)", f"{total_mod:.2f}h")
            tm2.metric("Días con ausentismo MOD", len(res_mod))
            tm3.metric("Personas MOD afectadas", df_mod["nombre"].nunique())

            st.dataframe(res_mod, use_container_width=True, hide_index=True,
                         height=min(420, 45 + len(res_mod) * 35))

            max_mod = res_mod["Hs. no trabajadas"].max()
            fig_mod = go.Figure(go.Bar(
                x=res_mod["Fecha"], y=res_mod["Hs. no trabajadas"],
                text=res_mod["Hs. no trabajadas"].apply(lambda x: f"{x:.2f}h"),
                textposition="outside",
                marker_color=[_RJ if v == max_mod else _NA for v in res_mod["Hs. no trabajadas"]],
                hovertemplate="%{x}: %{y:.2f}h<extra></extra>",
            ))
            fig_mod.update_layout(**_LAYOUT_BASE, height=260,
                                  xaxis_title="", yaxis_title="Horas no trabajadas")
            st.plotly_chart(fig_mod, use_container_width=True)
            _caption(f"Período: {mod_label}. Descuento de {ALMUERZO_H}h almuerzo por día. Decimales exactos.")

    st.divider()

    # ══════════════════════════════════════════
    # 7. MOD SIN COMPENSAR
    # ══════════════════════════════════════════
    st.subheader("🔧❌ Horas MOD sin compensar")

    _ayuda("¿Qué son las horas MOD sin compensar?",
        """
**Qué muestra:** horas de personal MOD (HOURLY DIRECT / Costura) donde la persona
eligió o le correspondió **NO compensar**. Son horas de producción perdidas **para siempre**.

**Diferencia clave:**
- Horas MOD totales: incluye tanto las que se van a compensar como las que no.
- Horas MOD sin compensar: solo las que NO se recuperan → impacto neto en producción.

**Para evaluar prima de producción:** este número es el insumo directo.
Una persona que salió 2h y no compensa generó 2h de producción perdida neta.
        """
    )

    if mod_desde <= mod_hasta:
        df_mod_nc_base = filtrar_mod(permisos_planta, sector_dict, clasif_dict)
        df_mod_nc_base = df_mod_nc_base[df_mod_nc_base["compensa"] == "NO"]
        df_mod_nc      = filtrar_rango_fecha(df_mod_nc_base, mod_desde, mod_hasta)

        if df_mod_nc.empty:
            st.success(f"✅ No hay permisos MOD sin compensar en {mod_label}.")
        else:
            res_nc = resumen_mod_nc_diario(df_mod_nc)
            total_nc = res_nc["Hs. no compensadas"].sum()
            tn1, tn2, tn3 = st.columns(3)
            tn1.metric("Total hs. MOD no compensadas", f"{total_nc:.2f}h")
            tn2.metric("Días con ausentismo sin compensar", len(res_nc))
            tn3.metric("Personas afectadas", df_mod_nc["nombre"].nunique())

            st.dataframe(res_nc, use_container_width=True, hide_index=True,
                         height=min(420, 45 + len(res_nc) * 35))

            det_nc = detalle_mod_nc_por_persona(df_mod_nc)
            if not det_nc.empty:
                st.markdown("**Detalle por persona y motivo**")
                st.dataframe(det_nc, use_container_width=True, hide_index=True)

            _caption(f"Período: {mod_label}. Solo HOURLY DIRECT de Costura con compensa=NO.")

    st.divider()

    # ══════════════════════════════════════════
    # 8. TIEMPO NO PRODUCTIVO ACUMULADO
    # ══════════════════════════════════════════
    st.subheader("⏳ Tiempo no productivo acumulado")

    _ayuda("¿Qué es el tiempo no productivo acumulado?",
        """
**Qué muestra:** de todas las horas que el personal comprometió a compensar
(compensa=SI, todas las fechas), cuántas se recuperaron y cuántas siguen pendientes.

**Importante:** esto incluye a TODA la dotación activa, no solo MOD.

**Cómo interpretarlo:**
```
Pendiente = Comprometidas − Recuperadas
```
Cada hora pendiente es tiempo de producción que todavía no se recuperó.
Si el número crece mes a mes, significa que la tasa de compensación es menor
que la tasa de nuevos permisos.

**Diferencia con el KPI de Cumplimiento:** el KPI muestra el porcentaje.
Este bloque muestra el volumen absoluto y la tendencia mensual.
        """
    )

    tnp = tiempo_no_productivo(permisos_activos, comp_activos)
    if tnp:
        tp1, tp2, tp3 = st.columns(3)
        tp1.metric("Horas comprometidas (total)", fmt_horas(tnp["total_comprometidas"]))
        tp2.metric("Horas ya recuperadas",        fmt_horas(tnp["total_recuperadas"]))
        tp3.metric("⚠️ Horas aún sin recuperar",  fmt_horas(tnp["total_pendientes"]))

        if tnp["total_comprometidas"] > 0:
            _caption(
                f"De las {fmt_horas(tnp['total_comprometidas'])} comprometidas, "
                f"se recuperaron {fmt_horas(tnp['total_recuperadas'])} "
                f"({tnp['pct_recuperado']:.1f}%). "
                f"Quedan {fmt_horas(tnp['total_pendientes'])} sin recuperar."
            )

        if not tnp["por_mes"].empty:
            pm = tnp["por_mes"]
            fig_tnp = go.Figure(go.Bar(
                x=pm["Mes"], y=pm["Horas comprometidas"],
                text=pm["Horas comprometidas"].apply(fmt_horas),
                textposition="outside",
                marker_color=_colores_destacar(pm["Horas comprometidas"], _AZ, _RJ),
                hovertemplate="%{x}: %{y:.1f}h comprometidas<extra></extra>",
            ))
            fig_tnp.update_layout(**_LAYOUT_BASE, height=270,
                                  xaxis_title="", yaxis_title="Horas comprometidas")
            st.plotly_chart(fig_tnp, use_container_width=True)
    else:
        st.info("No hay datos suficientes.")

    st.divider()
    _caption("Análisis automático basado en los datos de Google Sheets.")
