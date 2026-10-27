# tools/ — mantenimiento de datos (no se deploya)

Scripts para revisar y corregir los datos **sin tocar el Google Sheet real**.
Trabajan sobre un exporte `.xlsx` del Sheet (Archivo → Descargar → Microsoft Excel)
dejado en la raíz del repo. Los exportes, CSV y archivos corregidos están en
`.gitignore`: tienen nombres, legajos y motivos médicos, **nunca al repo**.

Requieren el entorno de desarrollo (`pip install -r requirements-dev.txt`).
En Windows usar `python -X utf8` para que se vean bien los acentos.

## 1. Auditar (solo lectura)

```
python -X utf8 tools/auditoria_excel.py "Control de Permisos - Fábrica.xlsx"
python -X utf8 tools/auditoria_excel.py export.xlsx --hoy 2026-10-19 --csv auditoria.csv
```

Lista inconsistencias con hoja, fila e id. Lo más útil:
- **S/R de San Juan contra el fin de turno vigente** ese día según la hoja
  `config_horarios` del exporte (respeta `excluidos_legajos`). Detecta permisos
  cargados antes de activar un horario especial, que la app no recalcula.
- Minutos/horas que no cuadran, motivos oficiales que compensan fuera de política,
  duplicados, fechas futuras, nombres distintos al padrón, planta mal cargada.

Son observaciones, no errores seguros: los históricos (`HIST…`) con medias horas o sin
minutos son anteriores a las reglas actuales y no se tocan (ver CLAUDE.md §1).

## 2. Corregir en una copia

```
python -X utf8 tools/aplicar_correcciones.py export.xlsx correcciones.csv
```

`correcciones.csv`:

```
hoja,id,columna,valor_anterior,valor_nuevo,motivo
permisos,P20261014132041,minutos_reales,300,60,S/R recalculado con horario 6 a 11
permisos,P20261014132041,registrado_por,*,{actual} | Corregido por <nombre> — 300min → 60min — <fecha>,S/R recalculado
padron,9348,activo,SI,NO,Baja
```

- Busca la fila por la columna A (id; legajo en el padrón) y la columna por **nombre**.
- `valor_anterior` debe coincidir con la celda (o `*`); si una sola no coincide, no guarda nada.
- `{actual}` = contenido actual de la celda (para sumar auditoría en `registrado_por`).
- Genera `<export> (corregido).xlsx` con las celdas en amarillo y una hoja
  `CAMBIOS_<fecha>` con la **celda real** de cada cambio: es la lista para pegar en el Sheet.

### Pegar en el Sheet
- Celda por celda (Ctrl+Shift+V = pegar solo valores), buscando antes el id con Ctrl+F.
- No pegar filas ni columnas enteras: pisa registros cargados después del exporte y
  Sheets convierte legajos, fechas y horas a número/fecha.
- Después, volver a exportar y correr la auditoría para confirmar.
