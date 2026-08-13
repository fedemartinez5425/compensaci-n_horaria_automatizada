# GILDAN — Sistema de Control de Permisos y Compensaciones

Esta aplicación permite registrar permisos del personal, controlar si esos permisos corresponden o no a horas compensables, y generar reportes de gestión para RRHH y Gerencia.

Está orientada a una operación diaria de control de ausencias, con reglas definidas por planta, motivo y nivel del empleado.

## ¿Para qué sirve?

El sistema ayuda a:
- registrar permisos de salida del personal
- validar si el motivo puede compensarse
- calcular horas pendientes de compensación
- controlar topes anuales por persona
- evitar errores en la carga de permisos
- generar reportes y análisis de gestión
- mantener un historial auditable de cada registro

## Funcionalidad principal

La app trabaja con tres grandes bloques:

1. Padrón de empleados
2. Registro de permisos
3. Registro de compensaciones

A partir de esos datos, calcula:
- horas comprometidas
- saldo de horas pendientes
- tope anual disponible
- cumplimiento mensual y acumulado
- reportes por persona, sector y clasificación

## Cómo funciona en la práctica

### 1. El guardia carga un permiso
Desde el panel de guardia se registra:
- nombre o legajo de la persona
- fecha
- hora de salida
- hora de entrada o sin retorno
- motivo del permiso
- si el permiso compensa o no
- quién lo registró

El sistema valida:
- si la persona existe en el padrón
- si el motivo está permitido por política
- si el empleado alcanzó el tope anual
- si la salida es válida según la regla de turno

### 2. El sistema calcula horas
Luego, la app transforma el tiempo real en horas redondeadas aplicando la regla interna del negocio:
- menos de 30 minutos = 0 horas
- 30 a 89 minutos = 1 hora
- 90 a 149 minutos = 2 horas
- y así sucesivamente

Esto permite convertir ausencias reales en un valor operativo para compensación.

### 3. RRHH revisa saldos y reportes
En el panel de RRHH se puede:
- consultar qué empleados tienen saldo pendiente
- revisar el historial de permisos
- registrar compensaciones reales que ya fueron cubiertas
- corregir o anular permisos cargados por error
- exportar reportes para gerencia

### 4. Gerencia visualiza el estado general
La app incluye análisis y resúmenes para ver:
- cuántas horas están comprometidas
- cuántas ya fueron compensadas
- cuál es el porcentaje de cumplimiento
- cuáles son los motivos más frecuentes
- qué sectores o clasificaciones tienen mayor impacto

## Reglas de negocio clave

### Política por planta
La compensación no es homogénea para todas las plantas:

- Fábrica San Juan: política RR.HH. 020
- Casa Central Bs. As.: convenio 036
- Total empresa: vista consolidada sin restricción de motivo

### Tope anual por empleado
Cada persona tiene un límite anual de horas que puede comprometer:
- empleado normal: 8 horas por año
- líder: 16 horas por año

Además, existen ciertos motivos con un cupo especial de 4 horas anuales fuera del tope regular.

### Motivos con cupo especial
Los siguientes motivos tienen tratamiento especial:
- Promesa Bandera Primaria Hijo
- Renovación Carnet de Conducir
- Adaptación Jardín / 2do Grado Hijo

Esto permite que se puedan compensar horas adicionales aunque la persona ya haya consumido su tope base.

### Cálculo del saldo
El saldo de cada empleado se calcula como:

```text
Saldo = Horas comprometidas - Horas compensadas
```

Es decir:
- si una persona acumuló permisos con compensa = SI
- y luego se registró una compensación
- la diferencia queda como saldo pendiente

## Paneles principales

### Panel Guardia
Permite la carga operativa del día a día.

Funcionalidades:
- buscar empleado por nombre o legajo
- registrar motivo y duración del permiso
- verificar si el motivo corresponde a compensación
- validar topes y políticas
- guardar el registro automáticamente
- agregar personas que no estén en el padrón

### Panel RRHH
Es el panel de control y administración.

Funcionalidades:
- gestión de activo/inactivo
- listas de empleados por planta
- saldo pendiente por persona
- historial por empleado
- corrección de permisos
- registro de compensaciones
- exportación de reportes

### Panel Análisis
Permite evaluar tendencias y desempeño.

Incluye:
- permisos por semana y por mes
- motivos más frecuentes
- distribución por duración
- KPI de cumplimiento de compensación
- comparación entre permisos compensables y no compensables
- métricas relacionadas con MOD

### Panel de documentación
Muestra la lógica interna del sistema para explicar:
- cómo se redondean los minutos
- cómo se calcula el saldo
- cómo se aplican topes y políticas
- qué significa cada reporte

## Instalación

### Requisitos
- Python 3.10 o superior
- conexión a Google Sheets con una cuenta de servicio
- configuración de secretos en Streamlit

### Dependencias
Instalar con:

```bash
pip install -r requirements.txt
```

### Ejecutar la app

```bash
streamlit run app.py
```

## Configuración necesaria

La aplicación conecta a Google Sheets usando `gspread` y una cuenta de servicio. Debe existir el archivo de secretos de Streamlit con la información de autenticación.

Un ejemplo de configuración es:

```toml
[gcp_service_account]
project_id = "..."
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "..."

SHEET_ID = "..."
```

## Flujo de trabajo típico

1. Un empleado solicita un permiso.
2. El guardia lo registra desde el panel de guardia.
3. El sistema clasifica la salida por motivo y planta.
4. Se valida si compensa o no según la política.
5. RRHH revisa el saldo acumulado y registra compensaciones cuando corresponden.
6. Gerencia consulta indicadores y reportes.

## Ventajas del sistema

- centraliza la información en una sola herramienta
- evita errores de cálculo manual
- reduce el tiempo de operación de RRHH
- da trazabilidad a cada permiso y compensación
- facilita la toma de decisiones con reportes automatizados

## Estructura del proyecto

```text
permisos_refactor_final/
├── app.py
├── config.py
├── requirements.txt
├── README.MD
├── repositories/
│   ├── __init__.py
│   └── sheets_repo.py
├── services/
│   ├── __init__.py
│   ├── analytics_service.py
│   └── permisos_service.py
├── ui/
│   ├── __init__.py
│   ├── analisis.py
│   ├── documentacion.py
│   ├── guardia.py
│   └── rrhh.py
└── .streamlit/
    └── secrets.toml
```

## En resumen

El proyecto es una herramienta operativa para gestionar permisos y compensaciones de personal, combinando:
- registro diario
- validación automática
- control de topes
- reportes de gestión
- análisis de historial

Es una solución pensada para dar orden, trazabilidad y rapidez en la administración de horas compensables dentro de la organización.


## Observaciones importantes

- La aplicación depende de la configuración de Google Sheets y de secretos.
- La lógica de negocio está desacoplada de la fuente de datos y de la UI.
- La app está orientada a uso interno de RRHH y guardia, con gran foco en auditoría y trazabilidad de cambios.
- La validación por motivo y tope es automática; no depende del usuario para decidir la regla.

## Casos de uso típicos

- Un guardia registra una salida por trámite bancario.
- El sistema valida si ese motivo compensa según la planta.
- Calcula el tiempo real, redondea a horas y determina si la operación va a compensar o no.
- RRHH revisa saldos acumulados y compensa las horas pendientes.
- Gerencia analiza el estado del equipo y exporta reportes.

## Mantenimiento

Si se cambia una política, normalmente se modifica en `config.py`. Si se cambia la fuente de datos, se trabaja en `repositories/sheets_repo.py`. La UI no necesita cambiar por esas decisiones.

## Autor
Proyecto interno para control de permisos y compensación horaria.
