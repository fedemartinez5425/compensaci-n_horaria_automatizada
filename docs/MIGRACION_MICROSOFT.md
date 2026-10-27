# Migración al ecosistema Microsoft
### Control de Permisos y Compensaciones — de Streamlit Cloud + Google Sheets a Azure App Service + SharePoint + Azure DevOps

> Documento de trabajo, **no se deploya** (la app no lo importa). Pensado para leerlo con los
> equipos de Infraestructura, SharePoint y Azure DevOps. Última revisión: 19/10/2026.

---

## 0. Resumen en un minuto

| | Hoy | Después |
|---|---|---|
| Código | GitHub (repo público personal) | **Azure Repos** (Azure DevOps de la empresa, privado) |
| Deploy | Streamlit Community Cloud, automático desde `main` | **Azure Pipelines** → **Azure App Service** (Linux, plan F1 gratuito) |
| Datos | Google Sheet (5 hojas) vía cuenta de servicio de Google | **5 Listas de SharePoint** vía Microsoft Graph |
| Acceso a datos | Clave privada de Google en los secrets | **Identidad administrada** de App Service con permiso `Sites.Selected` (sin claves) |
| Login de usuarios | 2 contraseñas compartidas (guardia / RRHH) | **Entra ID** (cuenta corporativa) + grupos para los roles |

Lo que **no cambia**: toda la lógica de negocio (`services/`, `config.py`) y las pantallas (`ui/`).
La app ya está separada en capas para esto: el único módulo que habla con Google es
`repositories/sheets_repo.py`, y se reemplaza por un `sharepoint_repo.py` con **las mismas funciones**.

```
            HOY                                         DESPUÉS
 ┌──────────────────────┐                    ┌──────────────────────────────┐
 │ Streamlit Cloud      │                    │ Azure App Service (F1)       │
 │  app.py + ui/        │                    │  app.py + ui/  (igual)       │
 │  services/  (igual)  │                    │  services/     (igual)       │
 │  sheets_repo.py ─────┼──► Google Sheet    │  sharepoint_repo.py ─────────┼──► Listas SharePoint
 │  contraseñas         │                    │  Entra ID (Easy Auth)        │      (Graph, Sites.Selected)
 └──────────────────────┘                    └──────────────────────────────┘
        ▲ deploy desde GitHub main                   ▲ Azure Pipelines desde Azure Repos main
```

---

## 1. Qué es la app (para quien la audita)

- **Para qué**: la guardia registra permisos de salida; la app decide si compensan según la
  política de cada planta (RR.HH. 020 San Juan / convenio 036 Bs. As.), controla topes anuales y
  calcula saldos. RRHH registra compensaciones, corrige/anula registros y saca reportes de gerencia.
- **Usuarios**: guardias de San Juan (Fábrica) y Bs. As. (Casa Central), RRHH, gerencia. Uso liviano,
  algunas decenas de interacciones por día.
- **Volumen** (19/10/2026): padrón 274 personas, 273 permisos, 110 compensaciones; entran
  ~30–40 permisos por mes. Lejos de cualquier límite de SharePoint (umbral de vista: 5.000 ítems).
- **Stack**: Python + Streamlit 1.65, pandas, plotly. Sin base de datos propia, sin archivos en disco.
- **Datos sensibles**: nombres, legajos y **motivos de ausencia que pueden ser médicos**. Son datos
  sensibles en los términos de la Ley 25.326: acceso restringido, sin copias sueltas, nada en repos públicos.
- **Calidad**: 79 tests automáticos (`python -m pytest -q`), incluida una prueba de punta a punta de
  todas las pantallas con un Sheet falso en memoria. Reglas de negocio documentadas y protegidas en
  `CLAUDE.md` y en la pantalla "Cómo se calcula" (`ui/documentacion.py`).
- **Desarrollo asistido por IA**: el código se escribió y auditó con ayuda de Claude Code (Anthropic).
  `CLAUDE.md` es el archivo de instrucciones para ese asistente. Conviene decirlo de entrada.

---

## 2. Decisiones de arquitectura (y por qué)

### 2.1 ¿Lista de SharePoint o Excel en SharePoint? → **Lista**

| Criterio | Excel en SharePoint (Graph Workbook API) | Lista de SharePoint |
|---|---|---|
| Escrituras simultáneas (guardia SJ + guardia BA + RRHH) | Riesgo de bloqueo/conflicto si alguien lo tiene abierto en Excel de escritorio; requiere "sesiones" de workbook | Cada registro es un ítem independiente; sin bloqueos |
| Validación de datos | Ninguna (cualquiera escribe cualquier cosa en una celda) | Tipos de columna, opciones fijas (planta, compensa), obligatorios |
| Auditoría | Historial de versiones del archivo entero | **Historial por ítem** (quién cambió qué y cuándo) — suma a la auditoría de `registrado_por` |
| Permisos | Por archivo | Por lista (ej: config_app solo para la app y el dueño) |
| Riesgo de "romper" el formato | Alto (filas/columnas movidas, celdas combinadas, tipos convertidos: ya pasó en el Sheet) | Bajo |
| Ver/filtrar/exportar para RRHH | Nativo | Vistas, filtros y "Exportar a Excel" nativos |

Excel sí sirve como **formato de intercambio** (exportar para análisis, importar la carga inicial).

### 2.2 Azure App Service **F1 (gratis)** — sirve, con estas condiciones

- **Se duerme** tras ~20 min sin uso (no hay "Always On" en F1): el primer acceso tarda 20–60 s. Aceptado.
- **Cuota de 60 minutos de CPU por día**. Streamlit re-ejecuta el script en cada clic y pandas
  consume CPU; con el uso actual debería alcanzar, pero si se agota la app se detiene hasta el día
  siguiente (error 403 "site stopped"). **Monitorear la primera semana** (Portal → App Service →
  Quotas). Plan B: **B1** (Basic, del orden de USD 13/mes), con Always On.
- 1 GB de RAM, sin slots de staging, sin dominio propio con SSL (no hacen falta; la URL
  `*.azurewebsites.net` tiene HTTPS).
- Streamlit usa **WebSockets**: en App Service Linux funcionan; confirmar que no haya un proxy/WAF
  corporativo delante que los corte.

### 2.3 Login de usuarios → **Entra ID con "Easy Auth"** de App Service

- Se activa en el Portal (App Service → Authentication → Add identity provider → Microsoft),
  restringido al tenant de la empresa. **Sin código**: App Service no deja pasar a nadie sin sesión
  corporativa.
- La app recibe el usuario en el header `X-MS-CLIENT-PRINCIPAL-NAME` (Streamlit lo lee con
  `st.context.headers`) y los grupos en `X-MS-CLIENT-PRINCIPAL`.
- Roles por **grupos de Entra**: `APP-Permisos-Guardia`, `APP-Permisos-RRHH` (nombres a definir con IT).
  Reemplaza las 2 contraseñas compartidas y la hoja `config_app` deja de guardar claves.
- Bonus de auditoría: `registrado_por` puede tomarse del usuario autenticado en vez de tipearse.

### 2.4 Acceso de la app a SharePoint → **Identidad administrada + `Sites.Selected`**

- **Preferido**: la *Managed Identity* del App Service recibe el permiso de aplicación de Microsoft
  Graph `Sites.Selected`, y un admin le otorga **escritura solo sobre el sitio** de la app.
  No hay secretos que guardar ni rotar.
- **Alternativa** (si IT no usa identidades administradas): *App Registration* con certificado
  (o secreto en Key Vault), también con `Sites.Selected`.
- **Evitar** `Sites.ReadWrite.All`: daría acceso a todo SharePoint de la empresa.

### 2.5 Código y deploy → **Azure Repos + Azure Pipelines**

- El repo se importa a un proyecto de Azure DevOps (privado).
- `main` protegida: solo entra código por *Pull Request* con los tests en verde (*build validation*).
- El pipeline corre los tests y, si pasan, deploya a App Service. Mismo circuito que hoy
  (merge a `main` = deploy), pero con un control automático en el medio.

---

## 3. Qué pedirle a cada persona de IT

### 3.1 Infraestructura (Azure)

1. Suscripción / **Resource Group** para la app (ej: `rg-rrhh-permisos`).
2. **App Service Plan Linux F1** + **Web App** Python (ej: `app-rrhh-permisos`), versión de Python
   3.12 o superior (la más nueva disponible; hoy se desarrolla con 3.14 y Streamlit 1.65).
3. **Identidad administrada** (system-assigned) activada en la Web App.
4. **Authentication (Easy Auth)** con Microsoft Entra ID, solo cuentas del tenant, "require authentication".
5. Dos **grupos de Entra** para los roles (Guardia, RRHH) y alta de los miembros.
6. Configuración de la Web App (sección 7.2) y acceso a **Log stream** para el primer deploy.
7. Confirmar si hay proxy/WAF/restricciones de red (WebSockets) y políticas de datos sensibles.

### 3.2 SharePoint

1. Un **sitio** (o una biblioteca dentro de un sitio de RRHH) para la app, con acceso restringido a RRHH.
2. Crear las **5 listas** de la sección 4 (o darme permisos de propietario y las creo yo).
3. Otorgar a la identidad de la app (la de 3.1-3) el permiso **`Sites.Selected` → write** sobre ese sitio
   (requiere un administrador de Entra/SharePoint; ver 4.4).
4. Activar **historial de versiones** en las listas.
5. Pasarme el **Site ID** y los nombres/ID de las listas.

### 3.3 Azure DevOps

1. Un **proyecto** (ej: `RRHH-Permisos`) y permisos para mí (Basic + Contributor).
2. **Importar el repo** (sección 6.1) o crear uno vacío y lo subo yo.
3. Una **Service Connection** de tipo *Azure Resource Manager* con alcance al Resource Group de 3.1-1.
4. Confirmar que hay **agentes hospedados** disponibles (Microsoft-hosted, `ubuntu-latest`).
5. **Branch policy** en `main`: PR obligatorio + build validation con el pipeline (sección 6.3).
6. Si quieren auditar el código: revisores obligatorios en los PR.

### 3.4 Mails modelo

**A Infraestructura**

> Asunto: Alta de Azure App Service para app interna de RRHH (Control de Permisos)
>
> Hola [nombre], me derivaron con vos desde IT. Tengo una app interna de RRHH (registro de permisos
> de salida y compensaciones horarias de las plantas San Juan y Bs. As.) hecha en Python/Streamlit,
> que hoy corre en Streamlit Cloud con Google Sheets, y la queremos pasar al ecosistema de la empresa.
>
> La propuesta es: Azure App Service Linux en plan F1 (uso liviano, puede dormirse), login con Entra
> ID (Easy Auth) y datos en listas de SharePoint vía Microsoft Graph con identidad administrada y
> permiso Sites.Selected (sin secretos).
>
> Te adjunto el instructivo con el detalle (sección 3.1 es lo que necesitaría de tu lado) y el
> código para que lo puedan revisar antes de desplegar. ¿Podemos coordinar 30 minutos esta semana?

**A SharePoint**

> Asunto: Sitio y listas de SharePoint para app interna de RRHH
>
> Hola [nombre], estoy migrando una app interna de RRHH a Microsoft 365. Necesitaría un sitio con
> acceso restringido a RRHH, 5 listas (estructura en la sección 4 del instructivo adjunto) y otorgar
> permiso Sites.Selected de escritura sobre ese sitio a la identidad administrada de la app.
> Los datos incluyen motivos de ausencia (algunos médicos), por eso el acceso restringido.
> ¿Me decís cuándo podemos verlo?

**A Azure DevOps**

> Asunto: Proyecto en Azure DevOps para app interna de RRHH
>
> Hola [nombre], necesitaría un proyecto en Azure DevOps para alojar una app interna de RRHH
> (Python/Streamlit) con su pipeline de tests y deploy a Azure App Service. El detalle está en la
> sección 3.3 y 6 del instructivo adjunto (incluye el YAML del pipeline). El código ya tiene tests
> automáticos; si quieren auditarlo antes, se los paso como ZIP o lo importamos directo al repo.

---

## 4. SharePoint: cómo crear las listas

### 4.1 Reglas generales (importantes)

- **Crear cada columna con el nombre interno exacto** (sin acentos ni espacios: `hora_salida`,
  `minutos_reales`…). SharePoint fija el nombre interno al crearla; después se puede cambiar el
  nombre visible, pero no el interno, que es el que usa la app.
- **No crear una columna llamada `id`**: choca con la columna interna `ID` de SharePoint. El `id` de
  la app va en la columna **Title** (se puede renombrar su nombre visible a "id").
- **Fechas y horas como texto** (`YYYY-MM-DD`, `HH:MM`): es el mismo contrato que hoy y evita el
  problema de zona horaria de las columnas Fecha de SharePoint (Graph las devuelve en UTC: un
  `2026-09-01` puede volver como `2026-09-01T03:00:00Z`). Se ordenan bien igual porque el formato es ISO.
- **Legajo como texto**, nunca número (es un identificador, no se suma; evita `2177.0`).
- Textos que crecen con la auditoría (`registrado_por`, `observacion`) como **Varias líneas de texto
  (texto sin formato)**: "Una línea de texto" corta en 255 caracteres y hoy ya hay de 175.
- **Indexar** las columnas por las que se busca (`Title` ya lo está; agregar `legajo` y `fecha`).
- Activar **historial de versiones** (Configuración de la lista → Versiones).

Abreviaturas: **T** = una línea de texto · **ML** = varias líneas, texto sin formato ·
**N1** = número con 1 decimal · **E** = elección (opciones fijas, sin "permitir valores personalizados").

### 4.2 Las 5 listas

**`permisos`**

| Columna (interno) | Tipo | Obligatoria | Notas |
|---|---|---|---|
| Title (= id) | T | Sí | `P20261019142302123ab12cd34`, `HIST0001` |
| fecha | T | Sí | `YYYY-MM-DD` — indexar |
| legajo | T | Sí | indexar |
| nombre | T | Sí | `APELLIDO, NOMBRE` |
| hora_salida | T | Sí | `HH:MM` |
| hora_entrada | T | Sí | `HH:MM` o `S/R` |
| sin_retorno | E | Sí | SI, NO |
| motivo | T | Sí | texto (lista oficial + "Otro" libre) |
| compensa | E | Sí | SI, NO, ANULADO |
| minutos_reales | N1 | Sí | |
| horas_redondeadas | N1 | Sí | |
| registrado_por | ML | Sí | guardia + historial de correcciones |
| planta | E | Sí | Fábrica, Casa Central |
| timestamp | T | Sí | `YYYY-MM-DD HH:MM:SS` |

**`compensaciones`**: Title (= id), fecha_compensacion (T), legajo (T, indexar), nombre (T),
horas_compensadas (N1), observacion (ML), registrado_por (T), planta (E: Fábrica, Casa Central), timestamp (T).

**`padron`**: Title (= legajo, **único**: Configuración de columna → "Exigir valores únicos"),
nombre (T), sector (T), centro_costo (T), planta (E: Fábrica, Casa Central), activo (E: SI, NO),
clasificacion (E: HOURLY DIRECT, HOURLY INDIRECT, EXEMPT, NON EXEMPT — confirmar lista con RRHH),
**es_lider (E: SI, NO)** — define quién tiene tope de líder (ya no hay nombres en el código).

**`config_horarios`**: Title (= id), planta (E: Fábrica, Casa Central, Todas), desde (T), hasta (T),
hora_fin (T `HH:MM`), descripcion (T), activo (E: SI, NO), excluidos_legajos (ML), creado_por (ML,
lleva el historial de ediciones), timestamp (T), dias_semana (T, ej `LU,MA`), solo_legajos (ML).

**`config_app`**: Title (= clave), valor (ML), actualizado_por (T), timestamp (T).
Con Entra ID ya no guarda contraseñas; queda para parámetros futuros. Permisos: solo la app y el dueño.

### 4.3 Crear las listas

- **A mano** (Sitio → Nuevo → Lista → Lista en blanco → Agregar columna): ~15 minutos por lista.
  Seguir las tablas de arriba; las columnas de "elección" con las opciones exactas (mayúsculas y acentos incluidos).
- **Por script** (recomendado si SharePoint lo permite): con PnP PowerShell (`New-PnPList`,
  `Add-PnPField -InternalName …`) o con Graph (`POST /sites/{site-id}/lists` con `columns`).
  Se puede escribir y versionar en `tools/` para que IT lo revise antes de correrlo.

### 4.4 Otorgar acceso a la app (lo hace un admin)

1. La identidad administrada del App Service (o la App Registration) recibe el permiso de aplicación
   **Microsoft Graph → `Sites.Selected`**, con consentimiento de administrador.
2. Un admin otorga el rol `write` sobre el sitio, con Graph:
   `POST https://graph.microsoft.com/v1.0/sites/{site-id}/permissions`
   con `{"roles": ["write"], "grantedToIdentities": [{"application": {"id": "<client-id de la identidad>", "displayName": "app-rrhh-permisos"}}]}`
   (o el equivalente de PnP: `Grant-PnPAzureADAppSitePermission`).
3. Las personas de RRHH que quieran ver las listas directamente se agregan como **miembros/lectores
   del sitio**; los guardias **no** necesitan acceso al sitio: escriben a través de la app.

---

## 5. Migración de los datos

1. **Congelar** la carga en la app vieja (avisar a guardias/RRHH un horario de corte, idealmente
   fuera de turno).
2. **Exportar** el Google Sheet a `.xlsx`.
3. **Auditar**: `python -X utf8 tools/auditoria_excel.py export.xlsx` y resolver lo pendiente antes de
   migrar (no arrastrar errores a SharePoint).
4. **Cargar** en las listas:
   - **Recomendado: script** `tools/migrar_a_sharepoint.py` (a escribir en la etapa 2 del plan): lee el
     exporte, normaliza tipos (legajos y fechas como texto, horas `HH:MM`), sube en lotes por Graph y
     al final **compara conteos y totales** (horas comprometidas y compensadas por legajo) contra el
     exporte. Es repetible: se prueba en un sitio de prueba y se corre igual el día del corte.
   - Alternativa manual: en cada lista "Editar en vista de cuadrícula" y pegar desde Excel. Con ~650
     filas en total es viable, pero Excel convierte legajos/fechas/horas y no queda verificación.
5. **Verificar** con la app nueva: mismos saldos, topes y KPIs que la vieja para un puñado de personas
   (elegir algunas de cada planta, líderes y gente con compensaciones).
6. **Archivar** el Google Sheet en modo solo lectura (no borrarlo hasta que pasen un par de meses).

---

## 6. Azure DevOps

### 6.1 Llevar el código

- **Opción A (simple)**: Repos → Import repository → URL del repo de GitHub. Trae el historial.
- **Opción B (recomendada para auditoría)**: crear el repo vacío y subir **una foto limpia** del
  código (`git archive` de `main`) como primer commit. El historial de GitHub tiene versiones viejas
  con las contraseñas iniciales (`1234`/`9876`, ya no válidas) y no aporta a la empresa.
- Archivos que **nunca** van: `credentials.json`, `.streamlit/secrets.toml`, exportes `*.xlsx`/`*.csv`
  (ya están en `.gitignore`; `git archive` solo empaqueta lo versionado).

### 6.2 Protección de `main`

Repos → Branches → `main` → Branch policies:
- Require a minimum number of reviewers (1, o el que pida IT).
- Build validation: el pipeline de 6.3 (obligatorio).
- Limitar tipos de merge (squash) y prohibir push directo.

### 6.3 Pipeline (`azure-pipelines.yml`, en la raíz del repo)

Plantilla a ajustar con los nombres reales (`<…>`):

```yaml
trigger:
  branches:
    include: [main]

pool:
  vmImage: ubuntu-latest

variables:
  pythonVersion: '3.12'                       # misma versión que la Web App
  azureSubscription: '<service-connection>'   # 3.3-3
  webAppName: '<app-rrhh-permisos>'           # 3.1-2

stages:
- stage: Test
  jobs:
  - job: pytest
    steps:
    - task: UsePythonVersion@0
      inputs: { versionSpec: '$(pythonVersion)' }
    - script: |
        python -m pip install --upgrade pip
        pip install -r requirements-dev.txt
        python -m pytest -q --junitxml=test-results.xml
      displayName: Tests
    - task: PublishTestResults@2
      condition: always()
      inputs: { testResultsFiles: test-results.xml }

- stage: Deploy
  dependsOn: Test
  condition: and(succeeded(), eq(variables['Build.SourceBranch'], 'refs/heads/main'))
  jobs:
  - deployment: webapp
    environment: produccion          # permite exigir aprobación manual antes del deploy
    strategy:
      runOnce:
        deploy:
          steps:
          - checkout: self
          - task: CopyFiles@2        # solo lo que corre en producción
            inputs:
              Contents: |
                app.py
                config.py
                requirements.txt
                repositories/**
                services/**
                ui/**
              TargetFolder: $(Build.ArtifactStagingDirectory)/app
          - task: ArchiveFiles@2
            inputs:
              rootFolderOrFile: $(Build.ArtifactStagingDirectory)/app
              includeRootFolder: false
              archiveFile: $(Build.ArtifactStagingDirectory)/app.zip
          - task: AzureWebApp@1
            inputs:
              azureSubscription: $(azureSubscription)
              appType: webAppLinux
              appName: $(webAppName)
              package: $(Build.ArtifactStagingDirectory)/app.zip
              startUpCommand: python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0 --server.headless true
```

Notas:
- `tests/`, `tools/`, `docs/`, `CLAUDE.md` y `.claude/` **no** se deployan (filtro de `CopyFiles`).
- Las dependencias las instala App Service al recibir el zip (`SCM_DO_BUILD_DURING_DEPLOYMENT=true`, ver 7.2).
- El `environment: produccion` permite que IT configure una **aprobación manual** antes de cada deploy.
- Organización nueva de DevOps sin agentes hospedados: hay que pedir el *free grant* de paralelismo o usar
  un agente propio; preguntarlo en 3.3-4.

---

## 7. Azure App Service

### 7.1 Creación (Infra)

Web App → Publish: Code → Runtime: Python 3.12+ → Linux → Plan F1 → región cercana
(ej: Brazil South / East US 2, según política de la empresa sobre residencia de datos).

### 7.2 Configuración → Variables de entorno (Application settings)

| Variable | Valor | Para qué |
|---|---|---|
| `SCM_DO_BUILD_DURING_DEPLOYMENT` | `true` | instala `requirements.txt` al deployar |
| `WEBSITES_PORT` | `8000` | puerto donde escucha Streamlit |
| `DATA_BACKEND` | `sharepoint` | (nuevo) elige el repositorio de datos (ver 8.1) |
| `SP_SITE_ID` | `<site-id>` | sitio de SharePoint (3.2-5) |
| `SP_LIST_PERMISOS`… | `<list-id o nombre>` | una por lista |
| `GRUPO_GUARDIA` / `GRUPO_RRHH` | `<object-id de los grupos>` | roles (2.3) |

Sin secretos: con identidad administrada no hay clave de SharePoint que guardar.
Si se usa App Registration con secreto, va en **Key Vault** referenciado desde acá, nunca en el código.

- **Startup command**: `python -m streamlit run app.py --server.port 8000 --server.address 0.0.0.0 --server.headless true`
- **Authentication**: Microsoft, tenant único, "Require authentication", acción para no autenticados: *redirect to login*.
- **Logs**: App Service logs → Application logging (Filesystem) para ver errores en *Log stream*.
- **HTTPS only**: On. **Versión mínima de TLS**: 1.2. **FTP**: deshabilitado.

---

## 8. Cambios de código (los hago yo, con tests, en ramas y PR)

La regla es la misma de siempre (`CLAUDE.md`): **no se toca lógica de negocio**, solo la capa de datos
y el login. Orden propuesto:

### 8.1 Repositorio de SharePoint
- Nuevo `repositories/sharepoint_repo.py` con **las mismas funciones** que `sheets_repo.py`:
  `leer_padron`, `leer_permisos`, `leer_compensaciones`, `leer_config_horarios`, `leer_config_app`,
  `actualizar_config_app`, `guardar_permiso`, `guardar_compensacion`, `agregar_empleado`,
  `corregir_permiso`, `marcar_activo`, `eliminar_empleado_padron`, `verificar_compensacion_duplicada`,
  `guardar_excepcion_horario`, `desactivar_excepcion_horario`, `editar_excluidos_horario`.
- Mismos DataFrames de salida (mismas columnas y tipos) → `services/` y `ui/` no se enteran.
- Graph: `GET /sites/{site}/lists/{lista}/items?expand=fields&$top=999` (con paginado),
  `POST …/items` para altas, `PATCH …/items/{item-id}/fields` para correcciones. Token con
  `azure-identity` (`ManagedIdentityCredential` en Azure, `DefaultAzureCredential`/CLI en desarrollo).
- Búsquedas por legajo/id sobre lo ya leído (o `$filter` sobre columnas indexadas). Se mantiene el
  cache (`st.cache_data`) y su invalidación después de cada escritura.
- `DATA_BACKEND=sheets|sharepoint` para elegir el repositorio sin tocar código: permite probar la app
  nueva contra SharePoint y **volver a Sheets** si algo falla durante la transición.
- Tests: un `tests/fake_sharepoint.py` (como el Sheet falso) y los **mismos tests de contrato** que hoy
  corren contra `sheets_repo` (escritura por nombre de columna, búsqueda por legajo, anular sin borrar).

### 8.2 Login con Entra ID
- `app.py`: en lugar de pedir contraseña, leer el usuario de `X-MS-CLIENT-PRINCIPAL-NAME` y sus grupos;
  Guardia → pantalla de guardia; RRHH → todo. Sin grupo → "no tenés acceso, pedilo a RRHH".
- `registrado_por` / `creado_por` / `actualizado_por` se completan con el usuario autenticado.
- Para desarrollo local, un modo que simule el usuario (solo si no se está en Azure).
- Se borra el manejo de contraseñas (`auth_service.py`, claves en `config_app`).

### 8.3 Limpieza que va a pedir una auditoría
- ✅ Hecho (27/10/2026): los líderes salieron de `config.py` y se marcan solo con la columna `es_lider`
  del padrón. Los nombres siguen en el historial de git de GitHub: por eso conviene la opción B de 6.1
  (foto limpia sin historial) al llevar el código a Azure Repos.
- Fijar versiones de todas las dependencias (hoy solo Streamlit está fija): generar un
  `requirements.txt` con versiones exactas (`pip freeze` filtrado o `pip-tools`) y probarlo en el pipeline.
- Quitar `gspread`/`google-auth` cuando ya no se use Sheets.
- Leer configuración de variables de entorno (`os.environ`) en lugar de `st.secrets`.

---

## 9. Plan por etapas

| # | Etapa | Quién | Resultado | Vuelta atrás |
|---|---|---|---|---|
| 0 | Presentación y revisión del código | Yo + IT | IT aprueba el enfoque; se crean recursos | — |
| 1 | Recursos: Resource Group, App Service F1, Entra (grupos, Easy Auth), proyecto DevOps, sitio SharePoint | IT | Todo creado, vacío | — |
| 2 | Código: `sharepoint_repo.py`, login Entra, pipeline, script de migración | Yo | PR con tests en verde | Producción sigue en Streamlit Cloud |
| 3 | Prueba: listas de prueba con una copia de los datos; app en Azure apuntando a ellas | Yo + RRHH | Saldos/topes/KPIs iguales a la app vieja | Producción sigue en Streamlit Cloud |
| 4 | Corte: congelar, exportar, auditar, migrar, verificar, avisar URL nueva | Yo + RRHH | App nueva en producción | `DATA_BACKEND=sheets` o volver a la URL vieja (el Sheet quedó intacto) |
| 5 | Convivencia (2–4 semanas) | RRHH | Uso normal; monitoreo de cuota F1 | Ídem |
| 6 | Cierre: Sheet en solo lectura, **revocar la clave de la cuenta de servicio de Google**, app de Streamlit Cloud eliminada, repo de GitHub privado o archivado | Yo | Una sola app, sin datos fuera de la empresa | — |

---

## 10. Cómo presentarlo a IT (mañana)

**Qué llevar:**
1. **Este documento** (`docs/MIGRACION_MICROSOFT.md`, se puede exportar a PDF).
2. **El código como ZIP limpio**, generado desde git (solo archivos versionados: no incluye
   `credentials.json`, `secrets.toml`, exportes ni el entorno virtual):
   ```
   git archive --format=zip -o "control-permisos-codigo.zip" main
   ```
   o desde GitHub: botón *Code → Download ZIP* de `main` (equivalente).
   **No** comprimir la carpeta a mano: tiene la clave de Google, los secrets y los Excel con datos personales.
3. Opcional: una demo en vivo de la app actual (datos reales: mostrarla solo a quien corresponda).

**Cómo mandarlo:** por un link de OneDrive/SharePoint corporativo compartido con los 3 contactos
(los ZIP con `.py` suelen quedar bloqueados por el filtro de adjuntos del mail).

**Sobre la cuenta de Claude:** no hace falta para llevar el código (el código está en el repo, no en
Claude). Antes de usar herramientas de IA con datos de la empresa en una máquina corporativa,
**consultar con IT qué herramientas están aprobadas**; y nunca pasar exportes con datos personales a
cuentas personales. Sí conviene contar que se desarrolló con asistencia de IA y que `CLAUDE.md` documenta las reglas.

**Lo que van a preguntar (y las respuestas):**

| Pregunta probable | Respuesta |
|---|---|
| ¿Dónde están los datos hoy? | Google Sheet personal + cuenta de servicio de Google. Por eso migramos. |
| ¿Hay secretos en el código? | No. Nunca se versionaron `credentials.json` ni `secrets.toml`. El historial tiene las contraseñas iniciales viejas, ya reemplazadas (y con Entra desaparecen). |
| ¿Quién puede entrar hoy? | Quien tenga la URL y la contraseña compartida. Con Entra: solo cuentas corporativas en los grupos. |
| ¿Datos sensibles? | Sí: motivos médicos. Sitio restringido a RRHH, la app accede con `Sites.Selected` solo a ese sitio. |
| ¿Qué pasa si se cae? | La guardia puede anotar en papel y cargar después (la app acepta fechas pasadas). Los datos están en SharePoint con historial de versiones. |
| ¿Cuánto cuesta? | App Service F1: gratis. SharePoint: incluido en M365. DevOps: gratis hasta 5 usuarios Basic. Si F1 no alcanza: B1 ~USD 13/mes. |
| ¿Quién la mantiene? | [Yo], con tests automáticos y pipeline que bloquea deploys con tests en rojo. |
| ¿Por qué Streamlit y no Power Apps? | Ya existe, tiene reglas de negocio complejas testeadas (redondeo, topes por planta, cupo extra, horarios especiales) y reportes; rehacerla en Power Apps es reescribir todo y perder los tests. Si IT prefiere Power Apps a futuro, las listas de SharePoint de este plan sirven igual. |

---

## 11. Riesgos y preguntas abiertas

- **Cuota de CPU de F1**: medir la primera semana; si se agota seguido, pasar a B1.
- **Política de IT sobre Streamlit/Python en App Service**: confirmar que esté permitido.
- **Proxy/WAF corporativo y WebSockets**: si la red de planta pasa por un proxy, probar desde la PC de guardia.
- **Cuentas de los guardias**: ¿tienen cuenta corporativa de M365? Si la guardia es tercerizada y no la
  tiene, alternativas: cuenta de servicio compartida por puesto (definir con IT) o licencias F (frontline).
- **Residencia de datos / Ley 25.326**: confirmar región de Azure y si hace falta registrar la base.
- **Bs. As.**: horario reducido pendiente de definir; si su jornada reducida tiene almuerzo, hay que
  agregar ese dato a `config_horarios` (hoy se asume que no).
