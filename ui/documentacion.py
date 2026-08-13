"""
ui/documentacion.py
─────────────────────────────────────────────────────────────────
Panel de documentación interna — "Cómo se calcula".
Desplegable por sección para no sobrecargar la pantalla.
"""
import streamlit as st
import pandas as pd
from config import (
    MOTIVOS_COMPENSAN_SJ, MOTIVOS_COMPENSAN_LIDERES_SJ,
    MOTIVOS_COMPENSAN_BSAS, MOTIVOS_LISTA, MOTIVOS_FUERA_TOPE,
    LIDERES_SJ, TOPE_HORAS_NORMAL, TOPE_HORAS_LIDER, TOPE_EXTRA_FUERA_TOPE,
    ALMUERZO_H,
)


def _caption(text: str):
    import re
    text_html = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    st.markdown(
        f'<p style="color:#2C3E50;font-size:0.95rem;margin-top:-4px;">{text_html}</p>',
        unsafe_allow_html=True,
    )


def render():
    st.title("📖 Cómo se calcula todo en esta app")
    _caption(
        "Documentación de referencia para entender la lógica del sistema. "
        "Si una fórmula cambia, se actualiza aquí también."
    )
    st.divider()

    # ── 1. Redondeo ───────────────────────────────────────────
    with st.expander("⏱ 1. Redondeo de horas — regla de fábrica", expanded=False):
        st.markdown("""
Toda ausencia parcial se convierte a horas enteras con esta regla:

| Minutos reales | Horas redondeadas |
|---|---|
| < 30 min | 0 horas |
| 30 – 89 min | 1 hora |
| 90 – 149 min | 2 horas |
| 150 – 209 min | 3 horas |

**Regla general:** si los minutos restantes sobre la hora entera son ≥ 30, sube al entero siguiente.
""")
        st.code(
            "horas = ENTERO(minutos / 60)\n"
            "si (minutos % 60) >= 30 → horas + 1",
            language="text"
        )
        st.markdown("**Ejemplos reales:**")
        st.dataframe(pd.DataFrame({
            "Salida":             ["09:50", "09:00", "08:00", "11:00", "14:00"],
            "Entrada":            ["10:40", "10:45", "09:10", "13:24", "15:00"],
            "Tiempo real":        ["50 min", "1h 45min", "1h 10min", "2h 24min", "1h 00min"],
            "Horas redondeadas":  ["1 hora", "2 horas", "1 hora", "2 horas", "1 hora"],
        }), use_container_width=True, hide_index=True)

        st.warning(
            "⚠️ **Caso borde:** 270 min = 4.5h exactas → redondea a **5h**. "
            "Para auditar, revisá la columna 'Minutos reales' en el Detalle de permisos del Panel RRHH."
        )
        st.markdown("**Sin Retorno (S/R):** se calcula contra fin de turno (15:00 hs).")
        st.code("Minutos ausente = (15:00 − hora_salida) × 60\nEj: salida 10:00 → 300 min → 5h", language="text")

    # ── 2. Saldo pendiente ────────────────────────────────────
    with st.expander("💰 2. Cálculo de saldo pendiente por persona", expanded=False):
        st.markdown("""
El saldo es **acumulativo** — no se resetea por mes.
Una deuda de febrero puede compensarse en mayo. Eso es correcto y esperado.
""")
        st.code(
            "Debe_total  = Σ horas_redondeadas  (donde compensa = 'SI')\n"
            "Compensado  = Σ horas_compensadas  (todas las fechas)\n"
            "Saldo       = Debe_total − Compensado",
            language="text"
        )
        st.caption("Si Saldo ≤ 0 la persona NO aparece en el reporte. No hay saldo negativo.")

    # ── 3. Tope anual ──────────────────────────────────────────
    with st.expander("🚦 3. Tope anual de compensación", expanded=False):
        st.markdown(f"""
Cada empleada tiene un límite anual de horas que puede comprometer para compensar.
Al alcanzar ese límite, el sistema **fuerza No compensa** automáticamente.

- Empleada normal: **{TOPE_HORAS_NORMAL}h / año**
- Líder: **{TOPE_HORAS_LIDER}h / año**
- Año calendario: resetea el **1° de enero**.
""")
        st.code(
            f"Tope_anual =  {TOPE_HORAS_NORMAL}h  (normal)\n"
            f"Tope_anual = {TOPE_HORAS_LIDER}h  (líder)\n\n"
            "Consumido_año = Σ horas_redondeadas donde:\n"
            "  • compensa = 'SI'\n"
            "  • año(fecha) = año actual\n"
            "  • motivo NO es fuera de tope\n\n"
            "Disponible = MAX(0, Tope − Consumido_año)\n"
            "Excedente  = MAX(0, Consumido_año − Tope)",
            language="text"
        )
        st.markdown("**Semáforo:**")
        st.dataframe(pd.DataFrame({
            "Estado":       ["🟢 OK", "🟡 ATENCIÓN", "🔴 LÍMITE", "🔴 EXCEDE TOPE"],
            "Condición":    ["Disponible > 2h", "Disponible ≤ 2h",
                             "Consumido = Tope", "Consumido > Tope"],
            "Consecuencia": [
                "Puede seguir compensando",
                "Próximo permiso puede cerrar el tope",
                "No puede sumar más compensa=SI",
                "Excedente a descontar del jornal",
            ],
        }), use_container_width=True, hide_index=True)

        st.markdown("**Líderes con tope de 16h/año:**")
        for lider in sorted(LIDERES_SJ):
            st.markdown(f"- {lider}")

    # ── 4. Cupo extra fuera de tope ───────────────────────────
    with st.expander(f"⭐ 4. Cupo extra de {TOPE_EXTRA_FUERA_TOPE}h — motivos especiales", expanded=False):
        st.markdown(f"""
Tres motivos tienen un cupo **independiente** de **{TOPE_EXTRA_FUERA_TOPE}h anuales**
que NO descuenta del tope normal (8h o 16h).

Una persona con el tope agotado puede seguir compensando por estos motivos
hasta consumir las {TOPE_EXTRA_FUERA_TOPE}h extra del cupo especial.
""")
        st.dataframe(pd.DataFrame({
            "Motivo":      sorted(MOTIVOS_FUERA_TOPE),
            "Cupo extra":  [f"{TOPE_EXTRA_FUERA_TOPE}h / año"] * len(MOTIVOS_FUERA_TOPE),
        }), use_container_width=True, hide_index=True)

        st.code(
            "Cupo_extra_usado = Σ horas_redondeadas donde:\n"
            "  • compensa = 'SI'\n"
            "  • motivo ∈ {motivos fuera de tope}\n"
            "  • año(fecha) = año actual\n\n"
            f"Cupo_extra_disponible = MAX(0, {TOPE_EXTRA_FUERA_TOPE} − Cupo_extra_usado)",
            language="text"
        )
        st.info(
            "**Renovación Carnet de Conducir** es un único motivo que engloba cualquier "
            "variante ('carnet de conducir', 'renovacion carnet', etc.). "
            "Requiere turno mañana. Es el trámite con cupo extra porque es de larga "
            "duración y no puede postergarse."
        )

    # ── 5. Política de motivos ────────────────────────────────
    with st.expander("📋 5. Política de motivos — qué puede compensar y qué no", expanded=False):
        st.markdown("**Fábrica San Juan (RR.HH. 020):**")
        sj_si = pd.DataFrame({"Motivo": sorted(MOTIVOS_COMPENSAN_SJ)})
        sj_si["¿Puede compensar?"] = sj_si["Motivo"].apply(
            lambda m: f"✅ SÍ + cupo extra {TOPE_EXTRA_FUERA_TOPE}h/año (fuera de tope)"
            if m in MOTIVOS_FUERA_TOPE else "✅ SÍ — guardia elige SI/NO"
        )
        st.dataframe(sj_si, use_container_width=True, hide_index=True)

        sj_no = [m for m in MOTIVOS_LISTA if m not in MOTIVOS_COMPENSAN_SJ]
        st.dataframe(pd.DataFrame({
            "Motivo": sj_no,
            "¿Puede compensar?": ["❌ NO — sistema fuerza NO"] * len(sj_no),
        }), use_container_width=True, hide_index=True)

        st.markdown("**Líderes y Calidad — motivos adicionales que SÍ compensan:**")
        adicionales = sorted(MOTIVOS_COMPENSAN_LIDERES_SJ - MOTIVOS_COMPENSAN_SJ)
        for m in adicionales:
            st.markdown(f"- **{m}** (solo líderes y calidad)")

        st.warning(
            "⚠️ **'Médico turno mañana'** SÍ compensa. **'Médico propio'** (sin especificar turno) "
            "NO compensa salvo para líderes y calidad."
        )

        st.markdown("**Casa Central Bs. As. (convenio 036):**")
        bsas = pd.DataFrame({"Motivo": sorted(MOTIVOS_COMPENSAN_BSAS)})
        bsas["¿Puede compensar?"] = "✅ SÍ — guardia elige SI/NO"
        st.dataframe(bsas, use_container_width=True, hide_index=True)

    # ── 6. Reporte de gerencia ────────────────────────────────
    with st.expander("📄 6. Cómo leer el reporte para gerencia", expanded=False):
        st.dataframe(pd.DataFrame({
            "Columna": ["Apellido y Nombre", "Clasificación", "Base anual",
                        "Pendiente", "Consumido año", "Disponible", "Estado"],
            "Qué significa": [
                "Empleada. Las líderes tienen 👑 al lado.",
                "Categoría laboral: HOURLY DIRECT, HOURLY INDIRECT, EXEMPT, NON EXEMPT.",
                f"Tope máximo anual: {TOPE_HORAS_NORMAL}h normal, {TOPE_HORAS_LIDER}h líder.",
                "Horas pendientes de compensar (acumuladas, todas las fechas).",
                "Horas con compensa=SI en el año actual. Resetea 1° de enero.",
                "Cuánto le queda = Base anual − Consumido año (mínimo 0).",
                "Semáforo según el tope (ver sección 3).",
            ],
        }), use_container_width=True, hide_index=True)
        st.error(
            "⚠️ El reporte SOLO debe generarse desde el botón 'Descargar PNG' o 'Descargar CSV'. "
            "Copiar datos a mano causa omisiones."
        )

    # ── 7. Métricas MOD ───────────────────────────────────────
    with st.expander("🔧 7. Métricas de producción (MOD)", expanded=False):
        st.markdown(f"""
**MOD (Mano de Obra Directa):** empleadas **HOURLY DIRECT** del sector **COSTURA**.

**Horas no trabajadas MOD:**
```
Horas del día = (Σ minutos_reales ÷ 60) − {ALMUERZO_H}h almuerzo
```
Usa `minutos_reales` (decimal exacto, sin redondeo). Se descuentan **{ALMUERZO_H}h de almuerzo** por día.

**Horas MOD sin compensar:** mismo filtro MOD pero solo donde `compensa = NO`.
Es tiempo de producción perdido que **no se recupera** — insumo para evaluar prima de producción.

**Tiempo no productivo acumulado:** horas comprometidas (`compensa=SI`) de toda la dotación,
comparadas contra lo ya recuperado. NO está limitado a MOD.
""")
        st.info(
            "Las tres métricas son independientes. "
            "Solo 'Horas MOD sin compensar' combina filtro MOD + compensa=NO."
        )

    # ── 8. KPI acumulado ─────────────────────────────────────
    with st.expander("🎯 8. KPI de compensación acumulado", expanded=False):
        st.markdown("""
**Qué mide:** el porcentaje de horas comprometidas que el equipo efectivamente recuperó,
calculado sobre **todo el histórico hasta hoy** (no por mes).

```
% Cumplimiento = Horas compensadas ÷ Horas comprometidas (compensa=SI) × 100
```

**Interpretación:**
- 🟢 > 70%: buen ritmo de recuperación
- 🟡 40–70%: ritmo moderado, hay deuda acumulada
- 🔴 < 40%: la deuda crece más rápido que la recuperación
""")

    st.divider()
    _caption(
        "Esta documentación vive en el código (ui/documentacion.py) y se actualiza "
        "junto con la lógica del sistema."
    )