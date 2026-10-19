"""
Google Sheet falso en memoria para tests: imita lo que la app usa de gspread
(row_values, find, findall, update_cell, cell, append_row, delete_rows,
get_all_records). Nunca toca el Sheet real.
"""
from types import SimpleNamespace

import gspread


class FakeWorksheet:
    def __init__(self, headers, filas=()):
        self.rows = [list(headers)] + [list(f) for f in filas]

    # lectura
    def row_values(self, n):
        return list(self.rows[n - 1])

    def get_all_records(self):
        h = self.rows[0]
        return [
            {h[i]: (r[i] if i < len(r) else "") for i in range(len(h)) if h[i]}
            for r in self.rows[1:]
        ]

    def findall(self, query, in_row=None, in_column=None, case_sensitive=True):
        out = []
        for ri, r in enumerate(self.rows, start=1):
            for ci, v in enumerate(r, start=1):
                if in_column and ci != in_column:
                    continue
                if str(v) == str(query):
                    out.append(SimpleNamespace(row=ri, col=ci, value=v))
        return out

    def find(self, query, in_row=None, in_column=None, case_sensitive=True):
        r = self.findall(query, in_column=in_column)
        return r[0] if r else None

    def cell(self, row, col):
        r = self.rows[row - 1]
        return SimpleNamespace(value=r[col - 1] if col <= len(r) else "")

    # escritura
    def update_cell(self, row, col, value):
        r = self.rows[row - 1]
        while len(r) < col:
            r.append("")
        r[col - 1] = value

    def append_row(self, values, value_input_option="RAW"):
        self.rows.append(list(values))

    def delete_rows(self, row):
        del self.rows[row - 1]

    # helper de tests
    def as_dicts(self):
        return self.get_all_records()


class FakeWorkbook:
    def __init__(self, hojas: dict):
        self.hojas = hojas

    def worksheet(self, nombre):
        if nombre not in self.hojas:
            raise gspread.exceptions.WorksheetNotFound(nombre)
        return self.hojas[nombre]


HEADERS_PADRON   = ["legajo", "nombre", "sector", "centro_costo", "planta", "activo", "clasificacion"]
HEADERS_PERMISOS = ["id", "fecha", "legajo", "nombre", "hora_salida", "hora_entrada", "sin_retorno",
                    "motivo", "compensa", "minutos_reales", "horas_redondeadas", "registrado_por",
                    "planta", "timestamp"]
HEADERS_COMP     = ["id", "fecha_compensacion", "legajo", "nombre", "horas_compensadas",
                    "observacion", "registrado_por", "planta", "timestamp"]
# Así está HOY la hoja real: sin 'excluidos_legajos'.
HEADERS_HORARIOS_VIEJA = ["id", "planta", "desde", "hasta", "hora_fin", "descripcion",
                          "activo", "creado_por", "timestamp"]
HEADERS_HORARIOS = ["id", "planta", "desde", "hasta", "hora_fin", "descripcion",
                    "activo", "excluidos_legajos", "creado_por", "timestamp"]
HEADERS_CONFIG_APP = ["clave", "valor", "actualizado_por", "timestamp"]


def workbook_base():
    return FakeWorkbook({
        "padron": FakeWorksheet(HEADERS_PADRON, [
            ["2001", "PEREZ, ANA", "COSTURA SAN JUAN", "", "Fábrica", "SI", "HOURLY DIRECT"],
            ["2002", "GOMEZ, LUIS", "CALIDAD", "", "Fábrica", "SI", "NON EXEMPT"],
            ["3001", "DIAZ, EVA", "E-COMMERCE", "", "Casa Central", "SI", "NON EXEMPT"],
        ]),
        "permisos": FakeWorksheet(HEADERS_PERMISOS, [
            ["P1", "2026-09-17", "2001", "PEREZ, ANA", "10:05", "S/R", "SI",
             "Banco / Cajero", "SI", 295, 5, "Guardia", "Fábrica", "2026-09-17 13:18:51"],
        ]),
        "compensaciones": FakeWorksheet(HEADERS_COMP),
        "config_horarios": FakeWorksheet(HEADERS_HORARIOS_VIEJA),
        "config_app": FakeWorksheet(HEADERS_CONFIG_APP),
    })
