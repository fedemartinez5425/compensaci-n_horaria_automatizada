"""
ui/rrhh.py
─────────────────────────────────────────────────────────────────
Panel de RRHH: reporte gerencia, compensaciones, histórico,
corrección de registros y gestión del padrón.
Solo lógica de presentación.
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import date, datetime
import calendar as _cal

from config import AÑOS, MESES, CLASIF_COLOR, DIAS_SEMANA, COLORES
from services.permisos_service import (
    calcular_saldos, fmt_horas, generar_id,
    obtener_tope, horas_comprometidas_año,
    validar_compensacion, excepcion_horario_activa, hora_fin_normal,
    filtrar_permisos_rango,
)
from repositories.sheets_repo import (
    guardar_compensacion, corregir_permiso,
    marcar_activo, eliminar_empleado_padron,
    verificar_compensacion_duplicada,
    guardar_excepcion_horario, desactivar_excepcion_horario,
    editar_excepcion_horario,
    actualizar_config_app,
)
from services.auth_service import hashear_password


def _caption(text: str):
    """Caption con mejor contraste y legibilidad."""
    import re
    text_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    st.markdown(
        f'<p style="color:#2C3E50;font-size:0.95rem;margin-top:-4px;">{text_html}</p>',
        unsafe_allow_html=True,
    )


def _excel_detalle_permisos(det: pd.DataFrame, titulo: str) -> bytes:
    """
    Excel del detalle de permisos para Producción: título, tabla de Excel con
    filtros y filas a bandas, y la columna Compensa en verde (SI) / rojo (NO).
    """
    import io
    import openpyxl
    from openpyxl.styles import PatternFill, Font, Alignment
    from openpyxl.formatting.rule import CellIsRule
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.table import Table, TableStyleInfo

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Permisos"

    n_cols = len(det.columns)
    ultima_col = get_column_letter(n_cols)

    # Título (fila 1), fila 2 en blanco, encabezados de la tabla en la fila 3.
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_cols)
    ws["A1"] = titulo
    ws["A1"].font = Font(bold=True, size=13, color="FFFFFF")
    ws["A1"].fill = PatternFill("solid", fgColor=COLORES["primario"].lstrip("#"))
    ws["A1"].alignment = Alignment(vertical="center", indent=1)
    ws.row_dimensions[1].height = 28

    fila_enc = 3
    for ci, col_name in enumerate(det.columns, 1):
        c = ws.cell(row=fila_enc, column=ci, value=col_name)
        c.font = Font(bold=True, color="FFFFFF", size=11)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[fila_enc].height = 22

    centradas = {"Fecha", "Legajo", "Salida", "Entrada", "S/R", "Compensa",
                 "Minutos reales", "Hs. (redondeadas)"}
    for ri, fila in enumerate(det.itertuples(index=False), fila_enc + 1):
        for ci, (col_name, valor) in enumerate(zip(det.columns, fila), 1):
            if pd.isna(valor):
                valor = None
            elif hasattr(valor, "item"):   # numpy → tipo nativo de Python
                valor = valor.item()
            c = ws.cell(row=ri, column=ci, value=valor)
            c.font = Font(size=10)
            if col_name == "Fecha":
                c.number_format = "DD/MM/YYYY"
            elif col_name == "Hs. (redondeadas)":
                c.number_format = "0.0"
            if col_name in centradas:
                c.alignment = Alignment(horizontal="center")

    ultima_fila = fila_enc + max(len(det), 1)
    tabla = Table(displayName="TablaPermisos", ref=f"A{fila_enc}:{ultima_col}{ultima_fila}")
    tabla.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
    ws.add_table(tabla)

    if "Compensa" in det.columns:
        col_comp = get_column_letter(list(det.columns).index("Compensa") + 1)
        rango = f"{col_comp}{fila_enc + 1}:{col_comp}{ultima_fila}"
        for valor, fondo, letra in (("SI", "C6EFCE", "006100"),
                                    ("NO", "FFC7CE", "9C0006"),
                                    ("ANULADO", "EDEDED", "7F7F7F")):
            ws.conditional_formatting.add(rango, CellIsRule(
                operator="equal", formula=[f'"{valor}"'],
                fill=PatternFill("solid", bgColor=fondo), font=Font(bold=True, color=letra),
            ))

    anchos = {"Fecha": 12, "Legajo": 10, "Nombre": 36, "Sector": 22, "Clasificación": 18,
              "Salida": 10, "Entrada": 10, "S/R": 7, "Motivo": 30, "Compensa": 12,
              "Minutos reales": 12, "Hs. (redondeadas)": 13}
    for ci, col_name in enumerate(det.columns, 1):
        ws.column_dimensions[get_column_letter(ci)].width = anchos.get(col_name, 14)

    ws.freeze_panes = f"A{fila_enc + 1}"
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = f"{fila_enc}:{fila_enc}"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def render(
    gc,
    planta_activa: str,
    key_planta: str,
    padron_planta: pd.DataFrame,
    padron_activos: pd.DataFrame,
    permisos_activos: pd.DataFrame,
    comp_activos: pd.DataFrame,
    compensaciones: pd.DataFrame,
    nombre_a_legajo: dict,
    nombres_lista: list,
    sector_dict: dict,
    clasif_dict: dict,
    planta_dict: dict,
    config_horarios: pd.DataFrame,
):
    if "San Juan" in planta_activa:
        _titulo = "🟢 RRHH — San Juan"
    elif "Bs." in planta_activa:
        _titulo = "🟢 RRHH — Bs. As."
    else:
        _titulo = "🟢 RRHH — Total Empresa"

    st.title(_titulo)
    st.markdown("Seguimiento de permisos y compensaciones.")
    st.divider()

    # ── Gestión de empleados ──────────────────────────────────
    st.subheader("Gestionar empleados — marcar inactivo o dar de baja")
    with st.expander("👤 Gestionar empleados — marcar inactivo o dar de baja"):
        _caption("Marcá como Inactivo a quien se fue de la empresa. Sus horas "
                  "pendientes desaparecen del reporte pero quedan en el historial.")
        if not padron_planta.empty:
            emp_sel = st.selectbox(
                "Empleado/a",
                ["— Seleccioná —"] + sorted(padron_planta["nombre"].tolist()),
                key="emp_gestion",
            )
            if emp_sel and emp_sel != "— Seleccioná —":
                _fila_emp     = padron_planta[padron_planta["nombre"] == emp_sel].iloc[0]
                legajo_emp    = str(_fila_emp["legajo"])
                activo_actual = str(_fila_emp["activo"]).upper()
                st.write(
                    f"Legajo **{legajo_emp}** — Estado actual: "
                    f"**{'✅ Activo' if activo_actual == 'SI' else '⛔ Inactivo'}**"
                )
                cg1, cg2 = st.columns(2)
                with cg1:
                    lbl = "⛔ Marcar como Inactivo" if activo_actual == "SI" else "✅ Reactivar"
                    nuevo = "NO" if activo_actual == "SI" else "SI"
                    if st.button(lbl, use_container_width=True, key="btn_activo"):
                        if marcar_activo(gc, legajo_emp, nuevo):
                            st.success(f"{'⛔ Inactivo' if nuevo == 'NO' else '✅ Reactivado'}: {emp_sel}")
                            st.rerun()
                        else:
                            st.error("❌ No se encontró el legajo en el padrón. Recargá la página.")
                with cg2:
                    # Baja definitiva: borra la fila y no se puede deshacer.
                    # Para quien se fue de la empresa alcanza con Inactivo.
                    _confirma_baja = st.checkbox(
                        "Confirmo que quiero BORRAR a esta persona del padrón (no se puede deshacer)",
                        key=f"conf_baja_{legajo_emp}",
                    )
                    if st.button("🗑️ Dar de baja del padrón", use_container_width=True,
                                  disabled=not _confirma_baja, key="btn_baja"):
                        if eliminar_empleado_padron(gc, legajo_emp):
                            st.success(f"🗑️ {emp_sel} eliminado.")
                            st.rerun()
                        else:
                            st.error("❌ No se encontró el legajo en el padrón. Recargá la página.")
        else:
            st.info("No hay empleados para esta planta.")

    st.divider()

    # ── Filtros ───────────────────────────────────────────────
    st.subheader("Seleccionar 'acumulado' para el reporte gerencia:")
    cf1, cf2, cf3 = st.columns([1, 1, 2])
    with cf1:
        año_sel = st.selectbox("Año", AÑOS, index=AÑOS.index(min(date.today().year, max(AÑOS))))
    with cf2:
        mes_sel = st.selectbox(
            "Mes", list(MESES.keys()),
            index=date.today().month - 1,
            format_func=lambda x: MESES[x],
        )
    with cf3:
        modo = st.radio("Vista:", ["Solo este mes", "Saldo acumulado total"], horizontal=True)

    if key_planta in ("Fábrica", "Total") and not padron_activos.empty:
        _sj = padron_activos[padron_activos["planta"] == "Fábrica"]
        if not _sj.empty and not (_sj["es_lider"] == "SI").any():
            st.warning(
                "⚠️ Ninguna persona de San Juan figura como líder: todas tienen tope de "
                f"{obtener_tope('NO')}h. Marcá **SI** en la columna **es_lider** de la hoja "
                "*padron* para las líderes (tope 16h)."
            )

    if permisos_activos.empty:
        st.warning("No hay permisos cargados para esta planta.")
        return

    # Filtrar por modo
    if modo == "Solo este mes":
        p_f = permisos_activos[
            (permisos_activos["fecha"].dt.year == año_sel) &
            (permisos_activos["fecha"].dt.month == mes_sel)
        ].copy()
        c_f = comp_activos[
            (comp_activos["fecha_compensacion"].dt.year == año_sel) &
            (comp_activos["fecha_compensacion"].dt.month == mes_sel)
        ].copy() if not comp_activos.empty else comp_activos.copy()
    else:
        p_f = permisos_activos.copy()
        c_f = comp_activos.copy()

    # Saldos
    _ultimo_dia = date(año_sel, mes_sel, _cal.monthrange(año_sel, mes_sel)[1])
    if modo == "Solo este mes":
        saldos_al_cierre = calcular_saldos(
            permisos_activos[
                (permisos_activos["fecha"].dt.year == año_sel) &
                (permisos_activos["fecha"].dt.month == mes_sel)
            ],
            comp_activos,
            hasta_fecha=_ultimo_dia,
        )
    else:
        saldos_al_cierre = calcular_saldos(permisos_activos, comp_activos)

    saldos_actuales = calcular_saldos(permisos_activos, comp_activos)
    comp_total      = c_f["horas_compensadas"].sum() if not c_f.empty and "horas_compensadas" in c_f.columns else 0
    _label_periodo  = f"{MESES[mes_sel]} {año_sel}" if modo == "Solo este mes" else "Total acumulado"

    # ── Métricas ──────────────────────────────────────────────
    st.divider()
    cm1, cm2, cm3, cm4 = st.columns(4)
    cm1.metric(f"📋 Permisos ({_label_periodo})", len(p_f))
    cm2.metric("👥 Con saldo > 0", len(saldos_al_cierre))
    cm3.metric("⏳ Hs. pendientes (hoy)",
               f"{saldos_actuales['saldo'].sum():.0f}h" if not saldos_actuales.empty else "0h")
    cm4.metric(f"✅ Hs. compensadas ({_label_periodo})", f"{comp_total:.0f}h")

    # ── Reporte para Gerencia ─────────────────────────────────
    st.divider()
    st.subheader(f"📄 Reporte para Gerencia — {MESES[mes_sel]} {año_sel}")
    _caption("Quiénes deben compensar horas, base anual, consumido y disponible. "
             "Descargá en PNG o Excel — no copies a mano.")

    if saldos_al_cierre.empty:
        st.success(f"✅ Sin horas pendientes al cierre de {MESES[mes_sel]} {año_sel}.")
    else:
        rep = saldos_al_cierre.copy()
        rep["sector"]        = rep["legajo"].map(sector_dict).fillna("Sin sector")
        rep["clasificacion"] = rep["legajo"].map(clasif_dict).fillna("Sin clasificar")
        rep["es_lider"]      = rep["legajo"].map(
            dict(zip(padron_activos["legajo"], padron_activos["es_lider"]))
        ).fillna("NO")
        # planta por legajo — necesario en la vista "Total Empresa" para
        # que cada persona use el tope correcto (SJ 8/16h vs Bs.As. 10h fijo).
        rep["planta_legajo"] = rep["legajo"].map(planta_dict).fillna(
            key_planta if key_planta != "Total" else "Fábrica"
        )
        rep["base_anual"]    = rep.apply(
            lambda r: obtener_tope(r["es_lider"], r["planta_legajo"]), axis=1
        )
        rep["consumido_año"] = rep["legajo"].apply(
            lambda leg: horas_comprometidas_año(permisos_activos, leg, año_sel)
        )
        rep["disponible"]    = (rep["base_anual"] - rep["consumido_año"]).clip(lower=0)
        rep["excedente"]     = (rep["consumido_año"] - rep["base_anual"]).clip(lower=0)

        def _estado(row):
            if row["excedente"] > 0:   return "🔴 EXCEDE TOPE"
            if row["disponible"] == 0: return "🔴 LÍMITE"
            if row["disponible"] <= 2: return "🟡 ATENCIÓN"
            return "🟢 OK"

        rep["estado"] = rep.apply(_estado, axis=1)
        rep = rep.sort_values(["sector", "clasificacion", "saldo"], ascending=[True, True, False])

        sector_actual, html_rows = None, []
        for _, row in rep.iterrows():
            if row["sector"] != sector_actual:
                sector_actual = row["sector"]
                html_rows.append(
                    f'<tr style="background:#1B4F9B;color:white;font-weight:700;">'
                    f'<td colspan="7" style="padding:6px 10px;">📁 {sector_actual}</td></tr>'
                )
            bg      = CLASIF_COLOR.get(row["clasificacion"], "#F8F9FA")
            nombre_ = row["nombre"] + (" 👑" if row["es_lider"] == "SI" else "")
            html_rows.append(
                f'<tr style="background:{bg};">'
                f'<td style="padding:5px 10px;">{nombre_}</td>'
                f'<td style="padding:5px 10px;color:#555;font-size:0.85rem;">{row["clasificacion"]}</td>'
                f'<td style="text-align:center;padding:5px;">{fmt_horas(row["base_anual"])}</td>'
                f'<td style="text-align:center;padding:5px;font-weight:700;color:#C0392B;">{fmt_horas(row["saldo"])}</td>'
                f'<td style="text-align:center;padding:5px;">{fmt_horas(row["consumido_año"])}</td>'
                f'<td style="text-align:center;padding:5px;color:#1A7A4A;font-weight:700;">{fmt_horas(row["disponible"])}</td>'
                f'<td style="text-align:center;padding:5px;">{row["estado"]}</td>'
                f'</tr>'
            )

        st.markdown(
            f'<style>.rep-t{{width:100%;border-collapse:collapse;font-size:0.85rem;font-family:sans-serif;}}'
            f'.rep-t th{{background:#1B4F9B;color:white;padding:8px;text-align:left;font-size:0.78rem;}}</style>'
            f'<table class="rep-t"><thead><tr>'
            f'<th>Apellido y Nombre</th><th>Clasificación</th>'
            f'<th style="text-align:center">Base</th><th style="text-align:center">Pendiente</th>'
            f'<th style="text-align:center">Consumido {año_sel}</th>'
            f'<th style="text-align:center">Disponible</th><th style="text-align:center">Estado</th>'
            f'</tr></thead><tbody>{"".join(html_rows)}</tbody></table>',
            unsafe_allow_html=True,
        )
        st.caption("👑 = líder (tope 16h/año)")
        st.markdown("<br>", unsafe_allow_html=True)

        n_exc = (rep["excedente"] > 0).sum()
        if n_exc > 0:
            for _, r in rep[rep["excedente"] > 0].iterrows():
                st.error(
                    f"🔴 **{r['nombre']}** — excede el tope de {fmt_horas(r['base_anual'])} "
                    f"en {fmt_horas(r['excedente'])}. A descontar del jornal: **{fmt_horas(r['excedente'])}**."
                )

        # Descargas
        _dl1, _dl2, _dl3 = st.columns(3)
        _png_rep    = rep[["nombre", "sector", "clasificacion", "base_anual",
                           "saldo", "consumido_año", "disponible", "estado"]].copy()
        for _c in ["base_anual", "saldo", "consumido_año", "disponible"]:
            _png_rep[_c] = _png_rep[_c].apply(fmt_horas)
        _png_rep.columns = ["Nombre", "Sector", "Clasificación", "Base",
                            "Pendiente", f"Consumido {año_sel}", "Disponible", "Estado"]

        _row_h = 32
        _fig_png = go.Figure(go.Table(
            header=dict(values=list(_png_rep.columns),
                        fill_color="#1B4F9B",
                        font=dict(color="white", size=11, family="Arial"),
                        align="left", height=36),
            cells=dict(values=[_png_rep[c] for c in _png_rep.columns],
                       fill_color="white",
                       font=dict(color="#222", size=10, family="Arial"),
                       align="left", height=_row_h),
        ))
        _fig_png.update_layout(
            title=dict(
                text=f"GILDAN — Compensación Horaria | {MESES[mes_sel]} {año_sel} | {planta_activa}",
                font=dict(size=13, color="#1B4F9B"), x=0,
            ),
            margin=dict(t=60, b=20, l=10, r=10),
            height=max(220, 60 + len(_png_rep) * _row_h),
            width=1000,
        )
        with _dl1:
            try:
                _img = _fig_png.to_image(format="png", scale=2)
                st.download_button("⬇️ Descargar PNG", data=_img,
                                   file_name=f"reporte_{MESES[mes_sel]}_{año_sel}.png",
                                   mime="image/png", use_container_width=True)
            except Exception:
                st.caption("PNG no disponible (kaleido no instalado).")
        with _dl2:
            try:
                import io as _io
                import openpyxl
                from openpyxl.styles import PatternFill, Font, Alignment, Border, Side
                from openpyxl.utils import get_column_letter

                _CLASIF_COLOR_XL = {
                    "HOURLY DIRECT": "EBF5FB", "HOURLY INDIRECT": "EAF4F4",
                    "EXEMPT": "FEF9E7", "NON EXEMPT": "FDEDEC",
                }
                _ESTADO_COLOR_XL = {
                    "🟢 OK": "D5EFE3", "🟡 ATENCIÓN": "FEF0E0",
                    "🔴 LÍMITE": "FDEDEC", "🔴 EXCEDE TOPE": "FDEDEC",
                }

                _wb_xl = openpyxl.Workbook()
                _ws_xl = _wb_xl.active
                _ws_xl.title = f"Reporte {MESES[mes_sel]} {año_sel}"

                _xl_cols = list(_png_rep.columns)
                _ws_xl.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(_xl_cols))
                _ws_xl.cell(row=1, column=1,
                    value=f"GILDAN — Compensación Horaria | {MESES[mes_sel]} {año_sel} | {planta_activa}")
                _ws_xl["A1"].font = Font(bold=True, size=13, color="FFFFFF")
                _ws_xl["A1"].fill = PatternFill("solid", fgColor="1B4F9B")
                _ws_xl.row_dimensions[1].height = 28

                for ci, col_name in enumerate(_xl_cols, 1):
                    cell = _ws_xl.cell(row=2, column=ci, value=col_name)
                    cell.font = Font(bold=True, color="FFFFFF", size=10)
                    cell.fill = PatternFill("solid", fgColor="2471D5")
                    cell.alignment = Alignment(horizontal="center", wrap_text=True)
                _ws_xl.row_dimensions[2].height = 22

                _thin = Side(style="thin", color="CCCCCC")
                _border = Border(left=_thin, right=_thin, top=_thin, bottom=_thin)
                _sector_xl = None
                _xl_row = 3
                for _, xl_r in _png_rep.iterrows():
                    if xl_r["Sector"] != _sector_xl:
                        _sector_xl = xl_r["Sector"]
                        _ws_xl.merge_cells(start_row=_xl_row, start_column=1,
                                            end_row=_xl_row, end_column=len(_xl_cols))
                        _c = _ws_xl.cell(row=_xl_row, column=1, value=f"  {_sector_xl}")
                        _c.font = Font(bold=True, color="FFFFFF", size=10)
                        _c.fill = PatternFill("solid", fgColor="1B4F9B")
                        _xl_row += 1
                    _clasif_fill = _CLASIF_COLOR_XL.get(xl_r.get("Clasificación", ""), "FFFFFF")
                    for ci, col_name in enumerate(_xl_cols, 1):
                        cell = _ws_xl.cell(row=_xl_row, column=ci, value=xl_r[col_name])
                        cell.border = _border
                        cell.alignment = Alignment(horizontal="center" if ci > 2 else "left")
                        cell.font = Font(size=10)
                        if col_name == "Clasificación":
                            cell.fill = PatternFill("solid", fgColor=_clasif_fill)
                        elif col_name == "Estado":
                            cell.fill = PatternFill("solid", fgColor=_ESTADO_COLOR_XL.get(str(xl_r[col_name]), "FFFFFF"))
                            cell.font = Font(bold=True, size=10)
                        elif col_name == "Pendiente":
                            cell.fill = PatternFill("solid", fgColor="FDEDEC")
                            cell.font = Font(color="C0392B", bold=True, size=10)
                        elif col_name == "Disponible":
                            cell.fill = PatternFill("solid", fgColor="E8F5EE")
                            cell.font = Font(color="1A7A4A", bold=True, size=10)
                        else:
                            cell.fill = PatternFill("solid", fgColor="FFFFFF")
                    _xl_row += 1

                for ci, w in enumerate([32, 22, 18, 11, 11, 14, 11, 16], 1):
                    _ws_xl.column_dimensions[get_column_letter(ci)].width = w

                _xl_bytes = _io.BytesIO()
                _wb_xl.save(_xl_bytes)
                st.download_button(
                    "⬇️ Descargar Excel", data=_xl_bytes.getvalue(),
                    file_name=f"reporte_{MESES[mes_sel]}_{año_sel}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    use_container_width=True,
                )
            except Exception as _xl_err:
                st.caption(f"Excel no disponible: {_xl_err}")
        with _dl3:
            st.download_button(
                "⬇️ Descargar CSV",
                _png_rep.to_csv(index=False, encoding="utf-8-sig"),
                file_name=f"reporte_{MESES[mes_sel]}_{año_sel}.csv",
                mime="text/csv", use_container_width=True,
            )

    # ── Reporte NO compensan ──────────────────────────────────
    with st.expander("Ver reporte de permisos sin compensación"):
        _caption("Personas que eligieron NO compensar. Dato para evaluar prima de producción.")
        p_no = p_f[p_f["compensa"] == "NO"].copy() if not p_f.empty else pd.DataFrame()
        if p_no.empty:
            st.success("✅ No hay permisos sin compensación en este período.")
        else:
            p_no["sector_nc"] = p_no["legajo"].map(sector_dict).fillna("Sin sector")
            p_no["clasif_nc"] = p_no["legajo"].map(clasif_dict).fillna("Sin clasificar")
            p_no["fecha_str"] = p_no["fecha"].dt.strftime("%d/%m/%Y")

            def _calc_nc(row):
                if pd.notna(row["minutos_reales"]) and row["minutos_reales"] > 0:
                    return round(row["minutos_reales"] / 60, 2)
                if pd.notna(row["horas_redondeadas"]) and row["horas_redondeadas"] > 0:
                    return float(row["horas_redondeadas"])
                try:
                    sal, ent = row["hora_salida"], row["hora_entrada"]
                    if isinstance(sal, str) and isinstance(ent, str) and ent != "S/R":
                        h_s, m_s = map(int, sal.split(":"))
                        h_e, m_e = map(int, ent.split(":"))
                        return round(((h_e*60+m_e)-(h_s*60+m_s))/60, 2)
                except Exception:
                    pass
                return 0.0

            p_no["hs_real"] = p_no.apply(_calc_nc, axis=1)
            rep_nc = (
                p_no.groupby(["nombre", "sector_nc", "clasif_nc"])
                .agg(permisos=("fecha_str", "count"), horas_no_comp=("hs_real", "sum"))
                .reset_index()
                .sort_values(["sector_nc", "horas_no_comp"], ascending=[True, False])
            )
            rep_nc = rep_nc[rep_nc["horas_no_comp"] > 0].copy()
            rep_nc["horas_no_comp"] = rep_nc["horas_no_comp"].apply(fmt_horas)
            rep_nc.columns = ["Nombre", "Sector", "Clasificación", "Permisos", "Hs. no compensadas"]
            st.dataframe(rep_nc, use_container_width=True, hide_index=True)

    # ── Histórico de compensaciones ───────────────────────────
    st.divider()
    st.subheader("📜 Histórico de compensaciones")
    _caption("Consultá todas las compensaciones de una persona y su situación de tope.")
    hist_sel = st.selectbox(
        "Empleado/a",
        ["— Seleccioná —"] + nombres_lista,
        key="hist_comp_sel",
    )
    if hist_sel and hist_sel != "— Seleccioná —":
        _leg_h = nombre_a_legajo.get(hist_sel, "")
        _hc    = comp_activos[comp_activos["legajo"] == _leg_h].copy() if not comp_activos.empty else pd.DataFrame()
        _hp    = permisos_activos[
            (permisos_activos["legajo"] == _leg_h) &
            (permisos_activos["compensa"] == "SI")
        ].copy() if not permisos_activos.empty else pd.DataFrame()
        _lider  = padron_activos[padron_activos["legajo"] == _leg_h]["es_lider"].values
        _lider  = _lider[0] if len(_lider) > 0 else "NO"
        _planta_h = planta_dict.get(_leg_h, key_planta if key_planta != "Total" else "Fábrica")
        _tope   = obtener_tope(_lider, _planta_h)
        _cons   = horas_comprometidas_año(permisos_activos, _leg_h, date.today().year)

        hh1, hh2, hh3 = st.columns(3)
        hh1.metric("Tipo", "👑 Líder" if _lider == "SI" else "Empleada")
        hh1.caption(f"Tope: {_tope:.0f}h/año")
        hh2.metric(f"Consumido {date.today().year}", fmt_horas(_cons))
        hh3.metric("Compensado histórico total",
                   fmt_horas(_hc["horas_compensadas"].sum()) if not _hc.empty else "0h")

        st.markdown("**Permisos que generaron deuda**")
        if _hp.empty:
            st.caption("Sin permisos con compensa=SI.")
        else:
            _hp_s = _hp[["fecha", "motivo", "horas_redondeadas"]].copy()
            _hp_s["fecha"] = _hp_s["fecha"].dt.strftime("%d/%m/%Y")
            _hp_s["horas_redondeadas"] = _hp_s["horas_redondeadas"].apply(fmt_horas)
            _hp_s.columns = ["Fecha", "Motivo", "Horas"]
            st.dataframe(_hp_s.sort_values("Fecha"), use_container_width=True, hide_index=True)

        st.markdown("**Compensaciones registradas**")
        if _hc.empty:
            st.caption("Sin compensaciones registradas.")
        else:
            _hc_s = _hc[["fecha_compensacion", "horas_compensadas", "observacion", "registrado_por"]].copy()
            _hc_s["fecha_compensacion"] = _hc_s["fecha_compensacion"].dt.strftime("%d/%m/%Y")
            _hc_s["horas_compensadas"]  = _hc_s["horas_compensadas"].apply(fmt_horas)
            _hc_s.columns = ["Fecha", "Horas", "Observación", "Registrado por"]
            st.dataframe(_hc_s.sort_values("Fecha"), use_container_width=True, hide_index=True)

    # ── Corrección de registros ───────────────────────────────
    st.divider()
    st.subheader("🛠️ Corregir o anular un permiso")
    _caption("Corregí un permiso cargado por error. Queda en el historial con la razón del cambio.")
    with st.expander("Abrir corrector de registros"):
        edit_nombre = st.selectbox("Empleado/a", ["— Seleccioná —"] + nombres_lista, key="edit_n")
        if edit_nombre and edit_nombre != "— Seleccioná —":
            _leg_e = nombre_a_legajo.get(edit_nombre, "")
            _pe    = permisos_activos[permisos_activos["legajo"] == _leg_e].copy() if not permisos_activos.empty else pd.DataFrame()
            if not _pe.empty:
                _pe["_label"] = (
                    _pe["fecha"].dt.strftime("%d/%m/%Y") + " | " +
                    _pe["motivo"] + " | " + _pe["compensa"] + " | " +
                    _pe["horas_redondeadas"].apply(fmt_horas)
                )
                reg_sel = st.selectbox("Registro", ["— Seleccioná —"] + _pe["_label"].tolist(), key="edit_r")
                if reg_sel and reg_sel != "— Seleccioná —":
                    _id_sel = _pe[_pe["_label"] == reg_sel]["id"].values[0]
                    _horas_actuales = _pe[_pe["_label"] == reg_sel]["horas_redondeadas"].values[0]
                    st.info(f"ID: **{_id_sel}** — horas actuales: **{fmt_horas(_horas_actuales)}**")
                    accion  = st.radio(
                        "Acción",
                        ["Cambiar compensa=SI a NO", "Cambiar compensa=NO a SI",
                         "Anular registro", "Corregir horas manualmente"],
                        horizontal=True, key="edit_acc",
                    )
                    _nuevas_horas = None
                    if accion == "Corregir horas manualmente":
                        _nuevas_horas = st.number_input(
                            "Nuevas horas (reemplaza el valor actual)",
                            min_value=0.0, max_value=24.0,
                            value=float(_horas_actuales), step=0.5, key="edit_nuevas_horas",
                        )
                    razon   = st.text_input("Razón del cambio *", key="edit_raz")
                    quien   = st.text_input("Tu nombre *", key="edit_qui")
                    if st.button("Aplicar corrección", type="primary", key="btn_editar"):
                        if not razon.strip():
                            st.error("❌ La razón es obligatoria.")
                        elif not quien.strip():
                            st.error("❌ Falta tu nombre.")
                        else:
                            if corregir_permiso(
                                gc, _id_sel, accion, razon.strip(), quien.strip(),
                                nuevas_horas=_nuevas_horas,
                            ):
                                st.success("✅ Corrección aplicada.")
                            else:
                                st.error("❌ No se encontró el registro. Recargá la página.")
            else:
                st.info("Sin permisos registrados.")

    # ── Registrar compensación ────────────────────────────────
    st.divider()
    st.subheader("✏️ Registrar compensación")
    _caption("Cuando alguien se queda horas extra para compensar, registralo acá.")

    with st.form("form_comp"):
        nom_c_sel = st.selectbox("Empleado/a", ["— Seleccioná —"] + nombres_lista)
        nom_c     = nom_c_sel if nom_c_sel != "— Seleccioná —" else ""
        leg_c     = nombre_a_legajo.get(nom_c, "") if nom_c else ""

        if nom_c and not saldos_actuales.empty:
            saldo_a = saldos_actuales[saldos_actuales["nombre"] == nom_c]["saldo"].sum()
            if saldo_a > 0:
                st.info(f"Saldo pendiente de **{nom_c}**: **{fmt_horas(saldo_a)}**")
            else:
                st.success(f"**{nom_c}** no tiene horas pendientes.")

        cc3, cc4 = st.columns(2)
        with cc3:
            fecha_comp = st.date_input("Fecha en que compensó", value=date.today(),
                                        max_value=date.today(), format="DD/MM/YYYY")
        with cc4:
            hs_comp = st.number_input("Horas compensadas", min_value=0.5, max_value=8.0, value=1.0, step=0.5)

        obs      = st.text_input("Observación (opcional)")
        registra = st.text_input("Tu nombre *")

        if st.form_submit_button("✅ REGISTRAR COMPENSACIÓN", use_container_width=True, type="primary"):
            errores = validar_compensacion(nom_c, registra)
            if verificar_compensacion_duplicada(comp_activos, leg_c, fecha_comp):
                errores.append(
                    f"{nom_c} ya tiene una compensación registrada el "
                    f"{fecha_comp.strftime('%d/%m/%Y')}. No se puede compensar dos veces el mismo día."
                )
            if errores:
                for e in errores:
                    st.error(f"❌ {e}")
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
                        # Planta de la persona según el padrón (no la de la
                        # vista): desde "Total Empresa" quedaba planta="Total"
                        # y la compensación no restaba en la vista de su planta.
                        "planta":            planta_dict.get(leg_c, key_planta),
                        "timestamp":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    })
                    st.success(f"✅ {nom_c} — {fmt_horas(hs_comp)} el {fecha_comp.strftime('%d/%m/%Y')}")
                except Exception as e:
                    st.error(f"❌ Error: {e}")

    # ── Detalle del período ───────────────────────────────────
    st.divider()
    st.subheader("🔍 Detalle de permisos del período")
    _caption(
        "Elegí el rango de fechas (por ejemplo el **mes productivo**, que no coincide con el "
        "mes calendario) y descargá el Excel con filtros para Producción."
    )
    _primer_dia = date(año_sel, mes_sel, 1)
    _rango = st.date_input(
        "Período (desde – hasta)",
        value=(_primer_dia, _ultimo_dia),
        format="DD/MM/YYYY",
        # La key depende del mes elegido arriba para que el rango se reinicie al cambiarlo.
        key=f"rango_detalle_{año_sel}_{mes_sel}",
    )
    if not isinstance(_rango, (tuple, list)) or len(_rango) < 2:
        st.info("Elegí también la fecha de fin del período.")
    else:
        _desde_det, _hasta_det = _rango[0], _rango[1]
        p_det = filtrar_permisos_rango(permisos_activos, _desde_det, _hasta_det)
        if not p_det.empty:
            det = pd.DataFrame({
                "Fecha":             p_det["fecha"].dt.date,
                "Legajo":            p_det["legajo"],
                "Nombre":            p_det["nombre"],
                "Sector":            p_det["legajo"].map(sector_dict).fillna(""),
                "Clasificación":     p_det["legajo"].map(clasif_dict).fillna(""),
                "Salida":            p_det["hora_salida"],
                "Entrada":           p_det["hora_entrada"],
                "S/R":               p_det["sin_retorno"],
                "Motivo":            p_det["motivo"],
                "Compensa":          p_det["compensa"],
                "Minutos reales":    pd.to_numeric(p_det["minutos_reales"], errors="coerce").fillna(0).round(0).astype(int),
                "Hs. (redondeadas)": p_det["horas_redondeadas"],
            })
            _periodo_txt = f"{_desde_det:%d/%m/%Y} al {_hasta_det:%d/%m/%Y}"
            _caption(
                f"**{len(det)}** permisos del {_periodo_txt}. Revisá la columna Minutos reales "
                "si sospechás que el redondeo no fue correcto."
            )
            st.dataframe(
                det, use_container_width=True, hide_index=True,
                column_config={"Fecha": st.column_config.DateColumn(format="DD/MM/YYYY")},
            )
            try:
                st.download_button(
                    "⬇️ Descargar Excel del período",
                    data=_excel_detalle_permisos(
                        det, f"GILDAN — Permisos del {_periodo_txt} | {planta_activa}"
                    ),
                    file_name=f"permisos_{_desde_det:%Y-%m-%d}_al_{_hasta_det:%Y-%m-%d}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    key="dl_detalle_permisos",
                )
            except Exception as _xl_err:
                st.caption(f"Excel no disponible: {_xl_err}")
        else:
            st.info("No hay permisos en este período.")

    # ── Horarios especiales ────────────────────────────────────
    st.divider()
    st.subheader("⚙️ Horarios especiales")
    _caption(
        "Configurá acá cambios temporales del fin de turno (reducción horaria, jornada "
        "completa de algunas personas ciertos días, etc.), sin tocar código. Horario normal: "
        f"San Juan **{hora_fin_normal('Fábrica'):%H:%M}hs**, Bs. As. **{hora_fin_normal('Casa Central'):%H:%M}hs**. "
        "En San Juan define el cálculo de los 'Sin retorno'; en Bs. As. solo propone la hora "
        "de fin de jornada al guardia. El tope anual de horas no cambia por esto."
    )
    _caption(
        "Cómo se combinan: un horario **solo para algunas personas** le gana al horario general "
        "de la planta. Los **excluidos** de un horario general siguen con el horario normal "
        "(o con otro horario cargado para ellos). Los **días** limitan el horario a esos días "
        "de la semana (vacío = todos)."
    )

    _legajo_a_nombre = {v: k for k, v in nombre_a_legajo.items()}
    _dias_cod = list(DIAS_SEMANA)

    def _a_legajos(nombres):
        return ",".join(nombre_a_legajo[n] for n in nombres if n in nombre_a_legajo)

    def _lista(legajos_txt):
        return [l.strip() for l in str(legajos_txt).split(",") if l.strip()]

    def _a_nombres(legajos_txt):
        return [_legajo_a_nombre.get(l, l) for l in _lista(legajos_txt)]

    def _dias_de(texto):
        elegidos = [d.strip().upper()[:2] for d in str(texto).split(",")]
        return [c for c in _dias_cod if c in elegidos]

    _exc_hoy = excepcion_horario_activa(config_horarios, key_planta, date.today())
    if _exc_hoy:
        st.success(
            f"🕐 **Vigente hoy** para {planta_activa}: fin de turno "
            f"**{_exc_hoy['hora_fin'].strftime('%H:%M')}hs** — {_exc_hoy['descripcion']} "
            f"(hasta {_exc_hoy['hasta'].strftime('%d/%m/%Y')})"
        )
    else:
        st.caption("Hoy no hay un horario especial general vigente para esta vista — rige el horario normal.")

    _plt_opts = ["Fábrica", "Casa Central", "Todas"]
    _plt_labels = {"Fábrica": "San Juan", "Casa Central": "Bs. As.", "Todas": "Ambas plantas"}

    with st.expander("➕ Agregar un horario especial nuevo"):
        with st.form("form_horario_especial", clear_on_submit=True):
            _plt_def = _plt_opts.index(key_planta) if key_planta in _plt_opts else 0
            _plt_h = st.selectbox("Planta a la que aplica", _plt_opts, index=_plt_def,
                                  format_func=lambda p: _plt_labels[p])

            _ch1, _ch2, _ch3 = st.columns(3)
            with _ch1:
                _desde_h = st.date_input("Vigente desde", value=date.today(), format="DD/MM/YYYY")
            with _ch2:
                _hasta_h = st.date_input("Vigente hasta", value=date.today(), format="DD/MM/YYYY")
            with _ch3:
                _hora_h = st.time_input("Hora de fin de turno", value=hora_fin_normal(key_planta), step=60)

            _dias_h = st.multiselect(
                "Días de la semana (vacío = todos los días)", _dias_cod,
                format_func=lambda c: DIAS_SEMANA[c], key="dias_nuevo_horario",
            )
            _solo_h = st.multiselect(
                "Solo para estas personas (vacío = toda la planta). Ej: jornada completa de algunos",
                nombres_lista, key="solo_nuevo_horario",
            )
            _nombres_excl_pre = st.multiselect(
                "Personas EXCLUIDAS (siguen con el horario normal; solo para horarios de toda la planta)",
                nombres_lista, key="excl_nuevo_horario",
            )

            _desc_h  = st.text_input("Descripción", placeholder="Ej: Reducción horaria — 7 a 13")
            _quien_h = st.text_input("Tu nombre *", key="quien_nuevo_horario")

            if st.form_submit_button("💾 Guardar horario especial", type="primary", use_container_width=True):
                if _hasta_h < _desde_h:
                    st.error("❌ La fecha 'hasta' no puede ser anterior a 'desde'.")
                elif not _quien_h.strip():
                    st.error("❌ Falta tu nombre.")
                elif _solo_h and _nombres_excl_pre:
                    st.error("❌ Un horario 'solo para estas personas' no lleva excluidos: dejá una de las dos listas vacía.")
                else:
                    try:
                        guardar_excepcion_horario(gc, {
                            "id":                generar_id("H"),
                            "planta":            _plt_h,
                            "desde":             _desde_h.strftime("%Y-%m-%d"),
                            "hasta":             _hasta_h.strftime("%Y-%m-%d"),
                            "hora_fin":          _hora_h.strftime("%H:%M"),
                            "descripcion":       _desc_h.strip() or "Horario especial",
                            "activo":            "SI",
                            "excluidos_legajos": _a_legajos(_nombres_excl_pre),
                            "dias_semana":       ",".join(_dias_h),
                            "solo_legajos":      _a_legajos(_solo_h),
                            "creado_por":        _quien_h.strip(),
                            "timestamp":         datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        })
                        st.success(
                            "✅ Horario especial guardado — ya está vigente para los permisos "
                            "que correspondan, sin necesidad de reiniciar nada."
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"❌ Error al guardar: {e}")

    if not config_horarios.empty:
        st.markdown("**Horarios especiales cargados:**")
        _tabla_h = config_horarios.copy()
        _tabla_h["planta"] = _tabla_h["planta"].map(_plt_labels).fillna(_tabla_h["planta"])
        _tabla_h["desde"] = _tabla_h["desde"].apply(lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "—")
        _tabla_h["hasta"] = _tabla_h["hasta"].apply(lambda d: d.strftime("%d/%m/%Y") if pd.notna(d) else "—")
        _tabla_h["dias"] = _tabla_h["dias_semana"].apply(
            lambda t: ", ".join(DIAS_SEMANA[c] for c in _dias_de(t)) or "Todos")
        _tabla_h["solo"] = _tabla_h["solo_legajos"].apply(lambda t: ", ".join(_a_nombres(t)) or "Toda la planta")
        _tabla_h["excl"] = _tabla_h["excluidos_legajos"].apply(lambda t: ", ".join(_a_nombres(t)) or "—")
        _mostrar_h = _tabla_h[["descripcion", "planta", "desde", "hasta", "hora_fin",
                               "dias", "solo", "excl", "activo"]].copy()
        _mostrar_h.columns = ["Descripción", "Planta", "Desde", "Hasta", "Hora fin", "Días",
                              "Aplica a", "Excluidos", "Activo"]
        st.dataframe(_mostrar_h, use_container_width=True, hide_index=True)

        _activas_h = config_horarios[config_horarios["activo"] == "SI"]
        if not _activas_h.empty:
            # La etiqueta lleva el final del id: dos horarios pueden tener la misma descripción.
            _opciones_h = {
                f"{f['descripcion']} — {_plt_labels.get(f['planta'], f['planta'])} — "
                f"{f['hora_fin']}hs ({str(f['id'])[-6:]})": f
                for _, f in _activas_h.iterrows()
            }

            st.markdown("**✏️ Editar un horario especial** (fechas, hora, días, a quién aplica, excluidos)")
            _sel_edit = st.selectbox("Horario especial a editar", ["— Seleccioná —"] + list(_opciones_h),
                                     key="sel_editar_horario")
            if _sel_edit != "— Seleccioná —":
                _f = _opciones_h[_sel_edit]
                _id_f = str(_f["id"])
                # Personas de otra planta (no aparecen en esta vista): se conservan tal cual.
                _solo_fuera = [l for l in _lista(_f["solo_legajos"]) if _legajo_a_nombre.get(l) not in nombres_lista]
                _excl_fuera = [l for l in _lista(_f["excluidos_legajos"]) if _legajo_a_nombre.get(l) not in nombres_lista]
                with st.form(f"form_editar_horario_{_id_f}"):
                    _e1, _e2, _e3 = st.columns(3)
                    with _e1:
                        _e_desde = st.date_input(
                            "Vigente desde", format="DD/MM/YYYY",
                            value=_f["desde"] if pd.notna(_f["desde"]) else date.today())
                    with _e2:
                        _e_hasta = st.date_input(
                            "Vigente hasta", format="DD/MM/YYYY",
                            value=_f["hasta"] if pd.notna(_f["hasta"]) else date.today())
                    with _e3:
                        try:
                            _hora_actual = datetime.strptime(str(_f["hora_fin"]), "%H:%M").time()
                        except ValueError:
                            _hora_actual = hora_fin_normal(_f["planta"])
                        _e_hora = st.time_input("Hora de fin de turno", value=_hora_actual, step=60)
                    _e_dias = st.multiselect("Días de la semana (vacío = todos)", _dias_cod,
                                             default=_dias_de(_f["dias_semana"]),
                                             format_func=lambda c: DIAS_SEMANA[c])
                    _e_solo = st.multiselect(
                        "Solo para estas personas (vacío = toda la planta)", nombres_lista,
                        default=[n for n in _a_nombres(_f["solo_legajos"]) if n in nombres_lista])
                    _e_excl = st.multiselect(
                        "Personas excluidas (siguen con el horario normal)", nombres_lista,
                        default=[n for n in _a_nombres(_f["excluidos_legajos"]) if n in nombres_lista])
                    if _solo_fuera or _excl_fuera:
                        st.caption(
                            "ℹ️ Este horario también incluye personas que no están en esta vista "
                            f"(legajos {', '.join(_solo_fuera + _excl_fuera)}): se mantienen."
                        )
                    _e_desc  = st.text_input("Descripción", value=str(_f["descripcion"]))
                    _e_quien = st.text_input("Tu nombre *", key=f"quien_editar_horario_{_id_f}")

                    if st.form_submit_button("💾 Guardar cambios", type="primary"):
                        if _e_hasta < _e_desde:
                            st.error("❌ La fecha 'hasta' no puede ser anterior a 'desde'.")
                        elif not _e_quien.strip():
                            st.error("❌ Falta tu nombre.")
                        elif (_e_solo or _solo_fuera) and (_e_excl or _excl_fuera):
                            st.error("❌ Un horario 'solo para estas personas' no lleva excluidos: dejá una de las dos listas vacía.")
                        else:
                            try:
                                ok = editar_excepcion_horario(gc, _f["id"], {
                                    "desde":             _e_desde.strftime("%Y-%m-%d"),
                                    "hasta":             _e_hasta.strftime("%Y-%m-%d"),
                                    "hora_fin":          _e_hora.strftime("%H:%M"),
                                    "descripcion":       _e_desc.strip() or "Horario especial",
                                    "dias_semana":       ",".join(_e_dias),
                                    "solo_legajos":      ",".join([nombre_a_legajo[n] for n in _e_solo] + _solo_fuera),
                                    "excluidos_legajos": ",".join([nombre_a_legajo[n] for n in _e_excl] + _excl_fuera),
                                }, _e_quien)
                                if ok:
                                    st.success("✅ Horario actualizado.")
                                    st.rerun()
                                else:
                                    st.error("❌ No se encontró el registro. Recargá la página e intentá de nuevo.")
                            except ValueError as e:
                                st.error(f"❌ {e}")

            st.markdown("**🚫 Desactivar un horario especial** (ej: si terminó antes de lo previsto)")
            _sel_desact = st.selectbox("Horario a desactivar", ["— Seleccioná —"] + list(_opciones_h),
                                       key="desact_horario_especial")
            if _sel_desact != "— Seleccioná —":
                if st.button("🚫 Desactivar horario seleccionado", key="btn_desact_horario"):
                    if desactivar_excepcion_horario(gc, _opciones_h[_sel_desact]["id"]):
                        st.success("✅ Desactivado.")
                        st.rerun()
                    else:
                        st.error("❌ No se encontró el registro. Recargá la página e intentá de nuevo.")
    else:
        st.caption(
            "No hay horarios especiales cargados todavía. Si el Google Sheet no tiene "
            "la hoja 'config_horarios', creála una vez con las columnas: id, planta, "
            "desde, hasta, hora_fin, descripcion, activo, excluidos_legajos, creado_por, "
            "timestamp, dias_semana, solo_legajos."
        )

    # ── Contraseñas de acceso ───────────────────────────────────
    st.divider()
    st.subheader("🔑 Cambiar contraseñas de acceso")
    _caption(
        "Las contraseñas del Panel Guardia y del Panel RRHH se guardan cifradas "
        "en el Google Sheet, no en el código — así cualquier persona de RRHH puede "
        "cambiarlas sin depender de un programador."
    )
    with st.expander("Cambiar una contraseña"):
        with st.form("form_cambiar_password", clear_on_submit=True):
            _cual_pw = st.selectbox(
                "¿Cuál contraseña querés cambiar?",
                ["Panel Guardia", "Panel RRHH"],
            )
            _nueva_pw   = st.text_input("Nueva contraseña", type="password")
            _repetir_pw = st.text_input("Repetí la nueva contraseña", type="password")
            _quien_pw   = st.text_input("Tu nombre *")

            if st.form_submit_button("💾 Actualizar contraseña", type="primary", use_container_width=True):
                if not _nueva_pw.strip():
                    st.error("❌ La contraseña no puede estar vacía.")
                elif _nueva_pw != _repetir_pw:
                    st.error("❌ Las dos contraseñas no coinciden.")
                elif not _quien_pw.strip():
                    st.error("❌ Falta tu nombre.")
                else:
                    _clave_config = "password_guardia" if _cual_pw == "Panel Guardia" else "password_rrhh"
                    try:
                        actualizar_config_app(gc, _clave_config, hashear_password(_nueva_pw), _quien_pw.strip())
                        st.success(
                            f"✅ Contraseña de {_cual_pw} actualizada. "
                            "Va a regir desde el próximo ingreso (las sesiones ya abiertas no se cierran solas)."
                        )
                    except Exception as e:
                        st.error(
                            f"❌ Error: {e}. Si el Google Sheet no tiene la hoja 'config_app', "
                            "creála una vez con las columnas: clave, valor, actualizado_por, timestamp."
                        )