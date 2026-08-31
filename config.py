"""
config.py
─────────────────────────────────────────────────────────────────
Constantes globales, políticas de compensación y configuración
de la aplicación. Centralizar aquí evita hardcoding en otros módulos.

Para cambiar una política de motivos, solo modificar este archivo.
Para migrar de Google Sheets a SharePoint, no hay nada que cambiar aquí.
"""
from datetime import time

# ── App ────────────────────────────────────────────────────────
APP_TITLE     = "GILDAN — Control de Permisos"
APP_ICON      = "🏭"
PASSWORD      = "1234"
PASSWORD_RRHH = "9876"

# ── Turnos ─────────────────────────────────────────────────────
HORA_FIN_TURNO      = time(15, 0)   # fin de turno fábrica (para S/R)
ALMUERZO_H          = 0.5           # descuento de almuerzo en métricas MOD

# ── Plantas ────────────────────────────────────────────────────
PLANTAS = ["Fábrica San Juan", "Casa Central Bs. As.", "🏢 Total Empresa"]

# ── Años disponibles ───────────────────────────────────────────
AÑOS = list(range(2025, 2036))

# ── Topes anuales de compensación ─────────────────────────────
TOPE_HORAS_NORMAL     = 8
TOPE_HORAS_LIDER      = 16
TOPE_EXTRA_FUERA_TOPE = 4    # cupo extra para motivos especiales (solo San Juan)

# ── Bs. As. — política RR.HH. 036 (NO aplica a San Juan) ───────
TOPE_HORAS_BSAS            = 10   # tope anual, sin distinción de líder
TOPE_HORAS_POR_PERMISO_BSAS = 4   # máximo de horas compensables por permiso individual

# ── Líderes SJ ────────────────────────────────────────────────
# Nombres exactos del padrón. Sincronizar si cambia el padrón.
LIDERES_SJ = {
    "SANTANA, SANDRA BETTINA",
    "RODRIGUEZ, PATRICIA SOLEDAD",
    "TEJADA, DALINDA MATILDE",
    "FLORES FRIAS, CELIA ROMINA",
    "MURO, LILIANA MABEL",
    "CERDA, CLAUDIA DEL VALLE",
    "OLIVA ZEBALLOS, ANALIA",
}

# ── Motivos ────────────────────────────────────────────────────
MOTIVOS_LISTA = [
    "Banco / Cajero",
    "Médico propio",
    "Médico turno mañana",
    "Familiar enfermo",
    "Enfermedad propia / Clínica",
    "Obra social / ANSES",
    "Juzgado / Tribunales",
    "Registro Civil / DNI",
    "Escribanía",
    "Renovación Carnet de Conducir",
    "Análisis de sangre",
    "Colegio hijo/a",
    "Escuela hijo/a",
    "Promesa Bandera Primaria Hijo",
    "Adaptación Jardín / 2do Grado Hijo",
    "Cuidado familiar",
    "Trámite personal",
    "Duelo / Fallecimiento familiar",
    "ART",
    "Otro",
    # ── Agregados política Bs. As. 036 ──
    "Jardín",
    "Trámite Automotor",
    "Paro General",   # agregado como compensable por decisión de RRHH,
                       # aunque no figura textualmente en la política 036.
]

# Cupo extra de 4h/año FUERA del tope normal. Solo estos 3 motivos.
MOTIVOS_FUERA_TOPE = {
    "Promesa Bandera Primaria Hijo",
    "Renovación Carnet de Conducir",
    "Adaptación Jardín / 2do Grado Hijo",
}

# Política San Juan (RR.HH. 020)
MOTIVOS_COMPENSAN_SJ = {
    "Banco / Cajero",
    "Análisis de sangre",
    "Renovación Carnet de Conducir",
    "Registro Civil / DNI",
    "Obra social / ANSES",
    "Juzgado / Tribunales",
    "Escribanía",
    "Colegio hijo/a",
    "Médico turno mañana",
    "Promesa Bandera Primaria Hijo",
    "Adaptación Jardín / 2do Grado Hijo",
    "Otro",
}

# Líderes y Calidad — set ampliado
MOTIVOS_COMPENSAN_LIDERES_SJ = MOTIVOS_COMPENSAN_SJ | {"Médico propio"}

# Política Bs. As. (convenio 036)
MOTIVOS_COMPENSAN_BSAS = {
    "Banco / Cajero",
    "Análisis de sangre",
    "Médico propio",
    "Familiar enfermo",
    "Registro Civil / DNI",
    "Obra social / ANSES",
    "Juzgado / Tribunales",
    "Escribanía",
    "Escuela hijo/a",
    "Colegio hijo/a",
    "Otro",
    "Jardín",              # "Primer día de clases... jardín" — política 036
    "Trámite Automotor",   # "Registro Civil/Automotor" — política 036
    "Paro General",        # No está en la política 036 escrita — se agregó
                            # como compensable por decisión de RRHH (confirmado
                            # verbalmente). Si esto se revierte, sacar esta línea.
}

# Mapeo para normalizar motivos históricos escritos a mano
MOTIVO_MAP = {
    "bco":                    "Banco / Cajero",
    "banco":                  "Banco / Cajero",
    "medico":                 "Médico propio",
    "médico":                 "Médico propio",
    "turno médico":           "Médico propio",
    "turno medico":           "Médico propio",
    "junta medica":           "Médico propio",
    "junta médica":           "Médico propio",
    "medico hijos":           "Familiar enfermo",
    "hija enferma":           "Familiar enfermo",
    "retiro hija + emicar":   "Familiar enfermo",
    "enferma":                "Enfermedad propia",
    "enfermedad":             "Enfermedad propia",
    "presión alta":           "Enfermedad propia",
    "presion alta":           "Enfermedad propia",
    "obra social":            "Obra social / ANSES",
    "anses":                  "Obra social / ANSES",
    "juzgado":                "Juzgado / Tribunales",
    "tribunales":             "Juzgado / Tribunales",
    "ufi":                    "Juzgado / Tribunales",
    "declarar estafa":        "Juzgado / Tribunales",
    "registro civil":         "Registro Civil / DNI",
    "dni":                    "Registro Civil / DNI",
    "carnet de conducir":     "Renovación Carnet de Conducir",
    "escribania":             "Escribanía",
    "escribanía":             "Escribanía",
    "emicar":                 "Emicar / Clínica",
    "sanatorio sj":           "Enfermedad propia / Clínica",
    "clinica":                "Enfermedad propia / Clínica",
    "clínica":                "Enfermedad propia / Clínica",
    "analisis":               "Análisis de sangre",
    "análisis":               "Análisis de sangre",
    "analisis de sangre":     "Análisis de sangre",
    "ipv":                    "Trámite personal",
    "personal":               "Trámite personal",
    "1 dia de clases":        "Colegio hijo/a",
    "colegio":                "Colegio hijo/a",
    "fallecimiento familiar": "Duelo / Fallecimiento familiar",
    "promesa bandera":        "Promesa Bandera Primaria Hijo",
    "juramento bandera":      "Promesa Bandera Primaria Hijo",
    "promesa":                "Promesa Bandera Primaria Hijo",
    "adaptacion jardin":      "Adaptación Jardín / 2do Grado Hijo",
    "adaptación jardín":      "Adaptación Jardín / 2do Grado Hijo",
    "renovacion carnet":      "Renovación Carnet de Conducir",
    "renovación carnet":      "Renovación Carnet de Conducir",
    "tramite personal":       "Trámite personal",
}

MESES = {
    1: "Enero",    2: "Febrero",   3: "Marzo",
    4: "Abril",    5: "Mayo",      6: "Junio",
    7: "Julio",    8: "Agosto",    9: "Septiembre",
    10: "Octubre", 11: "Noviembre",12: "Diciembre",
}

# ── Paleta visual ──────────────────────────────────────────────
# Un único lugar para definir colores. Todos los gráficos usan esto.
COLORES = {
    "primario":   "#1B4F9B",   # azul corporativo
    "secundario": "#2471D5",   # azul medio
    "acento":     "#C0392B",   # rojo — dato más importante / alerta
    "ok":         "#1A7A4A",   # verde
    "advertencia":"#E67E22",   # naranja
    "neutro":     "#7F8C8D",   # gris
    "fondo":      "#F4F6F9",
    "blanco":     "#FFFFFF",
}

CLASIF_COLOR = {
    "HOURLY DIRECT":   "#EBF5FB",
    "HOURLY INDIRECT": "#EAF4F4",
    "EXEMPT":          "#FEF9E7",
    "NON EXEMPT":      "#FDEDEC",
}

# ── Google Sheets (SCOPE) ──────────────────────────────────────
# Cuando se migre a SharePoint, solo cambiar repositories/sheets_repo.py.
# Este archivo no necesita modificarse.
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
