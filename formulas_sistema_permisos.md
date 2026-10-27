# Fórmulas del Sistema de Control de Permisos — GILDAN

## 1. Redondeo de horas

Toda ausencia se convierte a horas enteras con esta regla:

| Minutos reales | Resultado |
|---|---|
| < 30 min | 0 horas |
| 30 – 89 min | 1 hora |
| 90 – 149 min | 2 horas |
| 150 – 209 min | 3 horas |
| … | … |

**Regla general:** si los minutos sobrantes sobre la hora entera son ≥ 30, sube al entero siguiente.

```
horas = ENTERO(minutos / 60)
si (minutos % 60) >= 30 → horas + 1
```

**Caso Sin Retorno (S/R) — solo San Juan:** cuando la persona no vuelve, el tiempo se calcula contra el fin de turno vigente ese día: 15:00 hs por defecto, o el horario especial cargado por RRHH (Panel RRHH → Horarios especiales) para esa fecha, salvo para las personas excluidas de ese horario. En Bs. As. "Sin retorno" no fuerza horario: la app propone el fin de jornada vigente para esa persona ese día (17:00 hs normal, o el horario especial que le toque) y el guardia lo cambia si terminó a otra hora; se guarda la hora real.

**Horarios especiales (Panel RRHH → hoja `config_horarios`):** cada fila tiene planta, fechas `desde`–`hasta` y `hora_fin`, y opcionalmente `dias_semana` (ej: `LU,MA`; vacío = todos los días), `solo_legajos` (rige solo para esas personas) y `excluidos_legajos` (personas a las que una fila general no se les aplica). Para una persona y un día: primero se busca una fila con `solo_legajos` que la incluya; si no hay, la primera fila general donde no esté excluida; si tampoco, el horario normal de la planta (San Juan 15:00, Bs. As. 17:00). Ej. Bs. As. desde 01/10/2026: general 7 a 13 (fin 13:00) + jornada completa 7 a 16 (fin 16:00) solo para 5 personas + 7 a 16 solo lunes y martes para los rotativos.

```
minutos_ausente = (fin_de_turno_vigente − hora_salida) × 60
```

> ⚠️ **Caso borde a tener en cuenta:** 270 min = 4.5 h exactas → redondea a **5h**. Para auditar esto, revisá la columna "Minutos reales" en el Detalle de permisos del Panel RRHH.

---

## 2. Saldo pendiente por persona

El saldo es **acumulativo** — no se resetea por mes. Una deuda de febrero se puede compensar en mayo.

```
Debe_total  = Σ horas_redondeadas  (donde compensa = "SI", INCLUYE motivos fuera de tope)
Compensado  = Σ horas_compensadas  (todas las fechas registradas)
Saldo       = Debe_total − Compensado
```

Si `Saldo ≤ 0` la persona no aparece en el reporte. No hay saldo negativo.

---

## 3. Tope anual de compensación

El tope se evalúa por año calendario (resetea el **1° de enero**).

```
Tope_anual =  8h   → San Juan, empleada normal
Tope_anual = 16h   → San Juan, líderes
Tope_anual = 10h   → Bs. As. (todos) — además, máximo 4h por permiso individual

Consumido_año = Σ horas_redondeadas donde:
  • compensa = "SI"
  • año(fecha) = año actual
  • motivo NO es de tipo "fuera de tope"

Disponible = MAX(0, Tope_anual − Consumido_año)
Excedente  = MAX(0, Consumido_año − Tope_anual)
```

**Semáforo:**

| Estado | Condición |
|---|---|
| 🟢 OK | Disponible > 2h |
| 🟡 ATENCIÓN | Disponible ≤ 2h |
| 🔴 LÍMITE | Consumido = Tope |
| 🔴 EXCEDE TOPE | Consumido > Tope — horas excedentes se descuentan del jornal |

---

## 4. Cupo extra — motivos fuera de tope

Tres motivos tienen un cupo independiente de **4 horas anuales** que no descuenta del tope normal. Una persona con el tope agotado puede seguir compensando por estos motivos hasta consumir las 4h extra.

| Motivo | Cupo extra |
|---|---|
| Renovación Carnet de Conducir | 4h / año |
| Promesa Bandera Primaria Hijo | 4h / año |
| Adaptación Jardín / 2do Grado Hijo | 4h / año |

```
Cupo_extra_usado = Σ horas_redondeadas donde:
  • compensa = "SI"
  • motivo ∈ {motivos fuera de tope}
  • año(fecha) = año actual

Cupo_extra_disponible = MAX(0, 4 − Cupo_extra_usado)
```

Si `Cupo_extra_disponible = 0` → el sistema fuerza `compensa = NO` también para estos motivos.

---

## 5. Política de motivos por planta

El sistema determina automáticamente si un motivo puede compensar. Si no está en la lista, el guardia no puede elegir — se fuerza `NO`.

**San Juan (RR.HH. 020) — motivos que SÍ pueden compensar:**

Banco / Cajero · Análisis de sangre · Renovación Carnet de Conducir · Registro Civil / DNI · Obra social / ANSES · Juzgado / Tribunales · Escribanía · Colegio hijo/a · Médico turno mañana · Promesa Bandera Primaria Hijo · Adaptación Jardín / 2do Grado Hijo · Otro

**Líderes y Calidad — motivos adicionales:**

Médico propio (además de todos los anteriores)

**Buenos Aires (convenio 036) — motivos que SÍ pueden compensar:**

Banco / Cajero · Análisis de sangre · Médico propio · Familiar enfermo · Registro Civil / DNI · Obra social / ANSES · Juzgado / Tribunales · Escribanía · Escuela hijo/a · Colegio hijo/a · Otro

**No compensan en ninguna planta:** Médico propio (SJ, salvo líderes) · Familiar enfermo (SJ) · Enfermedad propia / Clínica · Cuidado familiar · Trámite personal · Duelo / Fallecimiento familiar · ART · Escuela hijo/a (SJ)

---

## 6. Indicador mensual de cumplimiento

```
% Cumplimiento (mes M) = MIN(100%, Hs. compensadas en M / Hs. comprometidas en M × 100)
```

Permite ver mes a mes qué porcentaje del equipo efectivamente compensó lo que debía.

---

## 7. Métricas MOD (Mano de Obra Directa)

Se aplican solo a empleadas **HOURLY DIRECT** del sector **COSTURA**.

```
Hs. no trabajadas (día) = (Σ minutos_reales / 60) − 0.5h almuerzo
```

El descuento de 0.5h por almuerzo se aplica por cada día con registros MOD, independientemente de la cantidad de personas o permisos en ese día. **Excepción:** los días con horario especial vigente (ej: reducción horaria 6 a 11) no tienen almuerzo, así que ese día se descuentan 0h.

**Horas MOD sin compensar:** mismo filtro pero solo donde `compensa = "NO"`. Es tiempo de producción perdido que no se recupera — insumo directo para evaluar prima de producción.
