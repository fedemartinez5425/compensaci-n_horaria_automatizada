# CLAUDE.md — Control de Permisos y Compensaciones (GILDAN)

App Streamlit de uso interno (guardia + RRHH) que registra permisos de salida,
decide si compensan según la política de cada planta, controla topes anuales
y calcula saldos. Los datos viven en un Google Sheet (gspread + cuenta de servicio).

- Ejecutar: `pip install -r requirements.txt` y luego `streamlit run app.py`.
- Tests: `pip install -r requirements-dev.txt` y luego `python -m pytest -q`.
- Secretos: `.streamlit/secrets.toml` (`SHEET_ID`, `PASSWORD_GUARDIA_INICIAL`,
  `PASSWORD_RRHH_INICIAL`, `[gcp_service_account]`). Ver `.streamlit/secrets.toml.template`.

## ⚠️ Forma de trabajo (obligatoria)

- **`main` se deploya automáticamente.** Nunca commitear, pushear ni mergear: trabajar en una
  rama (`fix/...`, `feat/...`) y dejar los cambios para que el usuario los revise y commitee
  desde GitHub Desktop.
- **Nunca correr la app ni scripts contra el Google Sheet real**: escribe datos de producción.
  Para probar, usar `tests/fake_sheet.py` (Sheet en memoria) o `streamlit.testing.v1.AppTest`
  con `repositories.sheets_repo.get_workbook` parcheado (ver `tests/test_app_smoke.py`).
- **El repo es público.** Nunca commitear `secrets.toml`, `credentials.json` ni exportes del
  Sheet (`*.xlsx`, `*.csv`: padrón con nombres, legajos y motivos médicos). Están en `.gitignore`.
- `app copy.py` y el `.rar` son backups viejos del monolito: no son código vivo.
- `.claude/settings.json` bloquea `git commit/push/merge/rebase` y la lectura de credenciales.
  No relajar esas reglas: el usuario commitea y mergea desde GitHub Desktop.
- Para revisar o corregir datos reales: `tools/auditoria_excel.py` (solo lectura) y
  `tools/aplicar_correcciones.py` (escribe una copia del exporte), ver `tools/README.md`.
  Las correcciones las pega el usuario a mano en el Sheet, celda por celda.
- `docs/MIGRACION_MICROSOFT.md`: plan de migración a SharePoint + Azure DevOps + App Service.
  `tools/` y `docs/` no se deployan ni los importa la app.

## Arquitectura (respetarla)

| Capa | Archivo | Regla |
|---|---|---|
| Entrada / login / ruteo | `app.py` | Conecta, autentica, carga datos, filtra por planta y delega. |
| Constantes y políticas | `config.py` | Única fuente de motivos, topes, líderes, horarios, colores. |
| Datos | `repositories/sheets_repo.py` | Único módulo que conoce Google Sheets. |
| Negocio | `services/permisos_service.py`, `services/analytics_service.py`, `services/auth_service.py` | Sin Streamlit ni gspread. |
| UI | `ui/*.py` | Solo presentación; calcula vía services y escribe vía repositories. |

No meter lógica de negocio en `ui/` ni llamadas a gspread fuera de `sheets_repo.py`.

**Migración prevista:** SharePoint (Listas) + Azure DevOps + Azure App Service. Todo cambio en
datos debe seguir aislado en `sheets_repo.py` (será reemplazado por un repo de SharePoint con las
mismas funciones). En Azure, el login por contraseñas compartidas se reemplazará por Entra ID.
Plan detallado en `docs/MIGRACION_MICROSOFT.md`.

---

## 🔒 LÓGICA QUE NO SE DEBE CAMBIAR

Todo lo de esta sección es regla de negocio acordada con RRHH (políticas 020 y 036).
No modificarla salvo pedido explícito del usuario, y si se modifica, actualizar
también `ui/documentacion.py` (pantalla "Cómo se calcula"), `formulas_sistema_permisos.md`
y los tests de `tests/test_permisos_service.py` en el mismo cambio.

### 1. Redondeo de horas — `redondear_horas()`
- `< 30 min → 0h`; luego `int(min // 60)` y si el resto `>= 30 min` suma 1.
- 30–89 → 1h, 90–149 → 2h, 270 min → 5h (caso borde aceptado).
- Siempre se guardan **ambos**: `minutos_reales` (exacto, 1 decimal) y `horas_redondeadas`.
  Las métricas MOD usan `minutos_reales`; saldos y topes usan `horas_redondeadas`.
- Hay permisos históricos con medias horas (1.5, 2.5): son de antes de esta regla, no tocarlos.

### 2. Sin Retorno (S/R)
- **Solo San Juan** (`key_planta == "Fábrica"`): S/R bloquea la hora de entrada y calcula
  contra el fin de turno vigente (`obtener_hora_fin_turno`), con `hora_entrada = "S/R"`.
- Fin de turno normal (`hora_fin_normal`): San Juan `HORA_FIN_TURNO = 15:00`, Bs. As.
  `HORA_FIN_TURNO_BSAS = 17:00`. Las excepciones temporales vienen de la hoja `config_horarios`
  (planta `Fábrica` / `Casa Central` / `Todas`, rango `desde`–`hasta` inclusive, `activo == "SI"`)
  con columnas opcionales: `dias_semana` (`LU,MA`…; vacío = todos), `solo_legajos` (rige solo
  para esas personas) y `excluidos_legajos` (siguen en horario normal). Precedencia: fila
  `solo_legajos` que incluye a la persona → primera fila general donde no esté excluida →
  horario normal. Se evalúan con la **fecha del permiso**, no con la de hoy. Filas mal cargadas
  (hora o días inválidos) se ignoran, no rompen la app. Todo se edita desde el Panel RRHH
  (`editar_excepcion_horario`, deja auditoría en `creado_por`): no hardcodear personas ni días.
- Activar una excepción **no recalcula** permisos ya cargados.
- **Bs. As.**: S/R no fuerza horario: se **propone** el fin de jornada vigente para esa persona
  (editable) y se guarda la hora real que cargó el guardia. No bloquear ese campo.
- Los horarios especiales **no** afectan los topes anuales.

### 3. Política de motivos por planta — `puede_compensar_por_politica()`
- San Juan (RR.HH. 020): `MOTIVOS_COMPENSAN_SJ`. Líderes: `MOTIVOS_COMPENSAN_LIDERES_SJ`
  (= SJ + "Médico propio").
- Bs. As. (convenio 036): `MOTIVOS_COMPENSAN_BSAS` (incluye "Paro General" por decisión de RRHH).
- "Total" = sin restricción, pero **desde la vista Total no se cargan permisos** (el guardia
  debe elegir la planta); las compensaciones se guardan con la planta de la persona (`planta_dict`).
- Si la política no lo permite, se fuerza `compensa = "NO"` y el guardia no puede elegir.
- "Médico turno mañana" compensa en SJ; "Médico propio" en SJ solo para líderes.

### 4. Topes anuales — `obtener_tope()`
- San Juan: **8h** normal / **16h** líder (`es_lider == "SI"` en la hoja `padron`; sin columna,
  vacío u otro valor = no líder). Nunca listar personas en el código (repo público).
- Bs. As.: **10h** fijas sin distinguir líder + máximo **4h por permiso individual**
  (`excede_tope_por_permiso`; si se supera, el guardado se **bloquea**, no se recorta).
- Año calendario (resetea el 1° de enero), controlado contra el año de la **fecha del permiso**.
- `horas_comprometidas_año` = Σ `horas_redondeadas` con `compensa == "SI"`, del año,
  **excluyendo** `MOTIVOS_FUERA_TOPE`.
- Al alcanzar el tope (`consumido >= tope`) se fuerza `compensa = "NO"`.
- Superar el tope con un permiso puntual está previsto: el reporte lo marca
  "🔴 EXCEDE TOPE" y el excedente se descuenta del jornal. No "arreglarlo" bloqueando.

### 5. Cupo extra fuera de tope (solo San Juan)
- `MOTIVOS_FUERA_TOPE` = Promesa Bandera Primaria Hijo, Renovación Carnet de Conducir,
  Adaptación Jardín / 2do Grado Hijo. Cupo propio de **4h/año** (`TOPE_EXTRA_FUERA_TOPE`)
  que no consume el tope normal. Agotado el cupo → `compensa = "NO"`.

### 6. Saldo — `calcular_saldos()`
- `Saldo = Σ horas_redondeadas (compensa == "SI") − Σ horas_compensadas`, por legajo.
- **Acumulativo**, no se resetea por mes ni por año. **Incluye** motivos fuera de tope.
- Solo se muestran saldos `> 0`; no existe saldo negativo.

### 7. Semáforo del reporte de gerencia (`ui/rrhh.py`, `_estado`)
- Excedente > 0 → 🔴 EXCEDE TOPE · Disponible == 0 → 🔴 LÍMITE · Disponible ≤ 2 → 🟡 ATENCIÓN · resto 🟢 OK.
- En vista "Total Empresa" cada persona usa el tope de **su** planta (`planta_dict`).

### 8. KPIs y MOD
- % cumplimiento = min(100, compensadas / comprometidas × 100) (acumulado y mensual).
- MOD = `clasificacion == "HOURLY DIRECT"` y sector que contiene `"COSTURA"`.
  Horas del día = Σ minutos_reales / 60 − 0.5h de almuerzo (una vez por día, piso 0).
  **Días con horario especial general vigente → 0h de almuerzo** (la jornada 6 a 11 no tiene almuerzo;
  `almuerzo_del_dia()` en `analytics_service.py`). Decisión de RRHH del 2026-10-12.

### 9. Contratos con el Google Sheet (romperlos corrompe datos)
- **Hojas**: `padron`, `permisos`, `compensaciones`, `config_horarios`, `config_app`.
- **Toda escritura va por NOMBRE de columna** (`_append_por_encabezado`, `_col`), nunca por
  posición. Si falta una columna obligatoria, error claro; nunca correr valores de columna.
  (El bug histórico de `marcar_activo` escribía `activo` en la columna de `planta`.)
- **Personas se buscan por legajo** (`find(..., in_column=col_legajo)`), nunca por nombre.
- Columnas actuales:
  - `permisos`: `id, fecha, legajo, nombre, hora_salida, hora_entrada, sin_retorno, motivo,
    compensa, minutos_reales, horas_redondeadas, registrado_por, planta, timestamp`.
  - `compensaciones`: `id, fecha_compensacion, legajo, nombre, horas_compensadas,
    observacion, registrado_por, planta, timestamp`.
  - `padron`: `legajo, nombre, sector, centro_costo, planta, activo, clasificacion`
    + `es_lider` (opcional para no romper hojas viejas, pero sin ella nadie es líder).
  - `config_horarios`: `id, planta, desde, hasta, hora_fin, descripcion, activo,
    excluidos_legajos, creado_por, timestamp, dias_semana, solo_legajos` (las tres opcionales
    pueden faltar si están vacías; se agregan al final de la hoja).
  - `config_app`: `clave, valor, actualizado_por, timestamp`.
- Valores canónicos: `planta` ∈ {`Fábrica`, `Casa Central`}; `compensa` ∈ {`SI`, `NO`, `ANULADO`};
  `activo`/`es_lider` ∈ {`SI`, `NO`}; fechas `YYYY-MM-DD`; horas `HH:MM`;
  `hora_entrada = "S/R"` para sin retorno. Prefijos de ID: `P` permiso, `C` compensación,
  `H` horario, `HIST` importación histórica.
- Nombres del padrón en MAYÚSCULAS ("APELLIDO, NOMBRE"); el legajo es string y único.
- **Anular nunca borra**: marca `compensa = "ANULADO"` y horas en 0. Desactivar un horario especial
  pone `activo = "NO"`. Toda corrección exige razón y usuario y deja auditoría en `registrado_por`.
- `leer_*` normalizan tipos y motivos (`MOTIVO_MAP`); después de cada escritura se llama
  `leer_xxx.clear()` para invalidar el cache. Mantener ese patrón.
- Hojas opcionales (`config_horarios`, `config_app`) deben tener **fallback seguro** si no existen.

### 10. Contraseñas
- Vigentes en la hoja `config_app` (`password_guardia`, `password_rrhh`), **hasheadas** con
  PBKDF2 (`services/auth_service.py`). Valores en texto plano viejos se siguen aceptando.
- Si `config_app` no tiene contraseñas, se usan `PASSWORD_*_INICIAL` de los secrets; si tampoco
  hay, la app no deja entrar. **Nunca** poner contraseñas en el código.
- Panel RRHH, Análisis y "Cómo se calcula" requieren la clave de RRHH. Cerrar sesión cierra ambas.

---

## Convenciones
- Todo en español (UI, nombres, comentarios). Tono rioplatense en los textos de la UI.
- Cambiar una política = tocar `config.py` + `ui/documentacion.py` + `formulas_sistema_permisos.md` + tests.
- Colores solo desde `COLORES` / `CLASIF_COLOR` de `config.py`.
- Antes de entregar cualquier cambio: `python -m pytest -q` en verde (incluye la prueba de punta a
  punta de todas las pantallas en las 3 plantas).
