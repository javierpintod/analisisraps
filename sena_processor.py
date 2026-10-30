"""
Motor de Procesamiento y Análisis de Juicios Evaluativos SENA.
Desarrollado en Python puro con soporte para Excel (.xlsx) y CSV.
Garantiza máxima compatibilidad, velocidad e independencia de extensiones binarias.
"""

from collections import defaultdict
import csv
from dataclasses import dataclass, field, asdict
import io
import re
from typing import Any, Dict, List, Optional, Set, Tuple
import openpyxl


COLUMN_SYNONYMS = {
    "ficha": [
        "ficha", "numero_ficha", "número de ficha", "numero de ficha", "codigo_ficha",
        "código de ficha", "ficha de caracterizacion", "ficha de caracterización", "grupo",
        "id_ficha", "ficha caracterizacion", "no ficha", "no. ficha"
    ],
    "programa": [
        "programa", "nombre_programa", "programa de formación", "programa de formacion",
        "denominacion", "denominación de programa", "nombre del programa", "programa formacion"
    ],
    "documento": [
        "documento", "numero_documento", "número de documento", "identificacion",
        "identificación", "doc", "numero_doc", "cedula", "cédula", "no. documento",
        "numero doc", "num doc", "nro documento", "nro doc", "documento de identidad",
        "no_documento", "num_documento", "identificacion aprendiz"
    ],
    "aprendiz": [
        "aprendiz", "nombre_aprendiz", "nombre aprendiz", "nombres y apellidos",
        "nombre completo", "aprendices", "nombre del aprendiz", "nombres", "estudiante",
        "nombre", "alumno", "nombre y apellidos", "apellidos y nombres", "datos aprendiz"
    ],
    "estado_aprendiz": [
        "estado_aprendiz", "estado aprendiz", "estado del aprendiz", "estado",
        "estado matricula", "estado de matrícula", "estado matricula aprendiz",
        "estado en la ficha", "situacion del aprendiz", "situacion aprendiz", "estado formacion"
    ],
    "competencia": [
        "competencia", "nombre_competencia", "código competencia", "codigo competencia",
        "descripcion competencia", "descripción competencia", "nombre de competencia",
        "competencia laboral", "competencia asociada", "desc competencia"
    ],
    "rap": [
        "resultado_aprendizaje", "resultado de aprendizaje", "rap", "nombre_rap",
        "descripción rap", "descripcion rap", "resultado", "nombre resultado de aprendizaje",
        "resultado aprendizaje", "resultado de aprendizaje asociado", "desc rap", "ra", "codigo rap"
    ],
    "juicio": [
        "juicio_evaluativo", "juicio evaluativo", "juicio", "estado juicio",
        "estado_juicio", "calificacion", "calificación", "estado de evaluacion", "evaluacion",
        "juicio de evaluacion", "resultado evaluacion", "concepto evaluativo", "concepto",
        "estado del juicio", "valor juicio", "juicio valorativo", "evaluacion rap"
    ],
    "fecha_juicio": [
        "fecha_juicio", "fecha juicio", "fecha evaluacion", "fecha_evaluacion",
        "fecha de evaluacion", "fecha de juicio", "fecha", "fecha registro"
    ],
    "instructor": [
        "instructor", "nombre_instructor", "evaluador", "instructor asignado",
        "docente", "funcionario", "tutor", "profesor"
    ]
}


def clean_string(val: Any) -> str:
    """Limpia cadenas eliminando tildes y caracteres especiales para matching."""
    if val is None:
        return ""
    s = str(val).strip().lower()
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u', 'ü': 'u', 'ñ': 'n'
    }
    for orig, repl in replacements.items():
        s = s.replace(orig, repl)
    s = re.sub(r'[^a-z0-9_\s]', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s


def normalize_juicio(val: Any) -> str:
    """
    Normaliza el juicio evaluativo:
    - 'A' : Aprobado
    - 'D' : Deficiente / No Aprobado
    - 'P' : Por evaluar / Pendiente / Sin registrar
    """
    if val is None:
        return "P"
    s = str(val).strip().upper()
    if not s or s in ["NAN", "NONE", "NULL", "-", "--", "N/A", "00/00/0000"]:
        return "P"
    
    if s == "A" or s.startswith("APROB") or s == "1" or s in ["SI", "SÍ", "APROBADO"]:
        return "A"
    
    if s == "D" or s.startswith("DEFIC") or s.startswith("NO APROB") or s == "0" or s in ["NO", "DEFICIENTE"]:
        return "D"
    
    if any(k in s for k in ["POR EVALUAR", "PENDIENTE", "SIN JUICIO", "SIN EVALUAR", "NO EVALUADO"]):
        return "P"
    
    return "P"


class SenaReader:
    """Lee archivos .xlsx, .xls (BIFF8 de SofiaPlus) y .csv en una lista de diccionarios limpios."""
    
    @staticmethod
    def read_file(file_bytes: bytes, filename: str) -> Tuple[List[str], List[Dict[str, Any]]]:
        lower_name = filename.lower()
        # Verificar si es Excel 97-2003 (.xls) por extensión o por firma OLE2 (D0 CF 11 E0)
        is_ole_xls = file_bytes.startswith(b'\xd0\xcf\x11\xe0') or lower_name.endswith('.xls')
        
        if is_ole_xls:
            return SenaReader._read_xls(file_bytes)
        elif lower_name.endswith((".xlsx", ".xlsm")):
            return SenaReader._read_excel(file_bytes)
        else:
            return SenaReader._read_csv(file_bytes)

    @staticmethod
    def _read_xls(file_bytes: bytes) -> Tuple[List[str], List[Dict[str, Any]]]:
        import xlrd
        book = xlrd.open_workbook(file_contents=file_bytes)
        sheet = book.sheet_by_index(0)
        if sheet.nrows == 0:
            return [], []

        # Extraer metadatos superiores típicos de SofiaPlus
        metadata = {}
        header_row_idx = 0
        for idx in range(min(30, sheet.nrows)):
            row = [str(sheet.cell_value(idx, col)).strip() for col in range(sheet.ncols)]
            first_cell = clean_string(row[0]) if row else ""
            
            # Ficha de Caracterización
            if "ficha de caracterizac" in first_cell and "estado" not in first_cell:
                # Buscar valor no vacío en la fila
                for cell_val in row[1:]:
                    if cell_val:
                        val_str = str(cell_val).replace(".0", "").strip()
                        if val_str:
                            metadata["ficha"] = val_str
                            break
            # Denominación del Programa
            elif "denominaci" in first_cell or "programa" in first_cell:
                for cell_val in row[1:]:
                    if cell_val:
                        metadata["programa"] = str(cell_val).strip()
                        break
            elif "regional" in first_cell:
                for cell_val in row[1:]:
                    if cell_val: metadata["regional"] = str(cell_val).strip(); break
            elif "centro" in first_cell:
                for cell_val in row[1:]:
                    if cell_val: metadata["centro"] = str(cell_val).strip(); break

            # Buscar fila de encabezados
            clean_cells = [clean_string(c) for c in row if c]
            if any("documento" in c for c in clean_cells) and any("resultado" in c or "competencia" in c or "juicio" in c for c in clean_cells):
                header_row_idx = idx
                break

        headers_raw = [str(sheet.cell_value(header_row_idx, c)).strip() for c in range(sheet.ncols)]
        headers = [h if h else f"Columna_{i+1}" for i, h in enumerate(headers_raw)]
        
        # Agregar columnas calculadas si no existen
        if "Nombre Aprendiz" not in headers:
            headers.append("Nombre Aprendiz")
        if metadata.get("ficha") and "Número Ficha" not in headers:
            headers.append("Número Ficha")
        if metadata.get("programa") and "Programa de Formación" not in headers:
            headers.append("Programa de Formación")

        data_rows = []
        for r_idx in range(header_row_idx + 1, sheet.nrows):
            # Saltar filas vacías
            row_raw = [sheet.cell_value(r_idx, c) for c in range(sheet.ncols)]
            if not any(str(x).strip() for x in row_raw if x is not None):
                continue
            
            row_dict = {}
            for col_i, h in enumerate(headers_raw):
                col_name = headers[col_i]
                val = row_raw[col_i] if col_i < len(row_raw) else None
                # Si el valor numérico termina en .0 (como documentos o fichas), limpiarlo
                if isinstance(val, float) and val.is_integer():
                    val = str(int(val))
                row_dict[col_name] = val

            # Si vienen 'Nombre' y 'Apellidos' por separado (estándar en SofiaPlus)
            nom = str(row_dict.get("Nombre") or "").strip()
            ape = str(row_dict.get("Apellidos") or "").strip()
            if nom or ape:
                row_dict["Nombre Aprendiz"] = f"{nom} {ape}".strip()

            # Asignar metadatos de ficha y programa si no estaban en las columnas
            if metadata.get("ficha"):
                row_dict["Número Ficha"] = metadata["ficha"]
            if metadata.get("programa"):
                row_dict["Programa de Formación"] = metadata["programa"]

            data_rows.append(row_dict)

        return headers, data_rows

    @staticmethod
    def _read_excel(file_bytes: bytes) -> Tuple[List[str], List[Dict[str, Any]]]:
        wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return [], []
        
        # Buscar la fila de encabezados
        header_row_idx = 0
        metadata = {}
        for idx, row in enumerate(rows[:25]):
            if not row: continue
            first_cell = clean_string(row[0]) if row[0] is not None else ""
            if "ficha de caracterizac" in first_cell and "estado" not in first_cell:
                for cell_val in row[1:]:
                    if cell_val:
                        metadata["ficha"] = str(cell_val).replace(".0", "").strip()
                        break
            elif "denominaci" in first_cell or "programa" in first_cell:
                for cell_val in row[1:]:
                    if cell_val:
                        metadata["programa"] = str(cell_val).strip()
                        break

            clean_cells = [clean_string(c) for c in row if c is not None]
            if any("documento" in c for c in clean_cells) and any("resultado" in c or "competencia" in c or "juicio" in c for c in clean_cells):
                header_row_idx = idx
                break

        headers = [str(c).strip() if c is not None else f"Columna_{i+1}" for i, c in enumerate(rows[header_row_idx])]
        if "Nombre Aprendiz" not in headers: headers.append("Nombre Aprendiz")
        if metadata.get("ficha") and "Número Ficha" not in headers: headers.append("Número Ficha")
        if metadata.get("programa") and "Programa de Formación" not in headers: headers.append("Programa de Formación")

        data_rows = []
        for r in rows[header_row_idx + 1:]:
            if not any(r):
                continue
            row_dict = {}
            for i, h in enumerate(headers[:len(r)]):
                val = r[i]
                if isinstance(val, float) and val.is_integer():
                    val = str(int(val))
                row_dict[h] = val

            nom = str(row_dict.get("Nombre") or "").strip()
            ape = str(row_dict.get("Apellidos") or "").strip()
            if nom or ape:
                row_dict["Nombre Aprendiz"] = f"{nom} {ape}".strip()

            if metadata.get("ficha"):
                row_dict["Número Ficha"] = metadata["ficha"]
            if metadata.get("programa"):
                row_dict["Programa de Formación"] = metadata["programa"]

            data_rows.append(row_dict)
            
        return headers, data_rows


    @staticmethod
    def _read_csv(file_bytes: bytes) -> Tuple[List[str], List[Dict[str, Any]]]:
        # Detección de encoding
        text = None
        for enc in ["utf-8-sig", "latin-1", "cp1252", "utf-8"]:
            try:
                text = file_bytes.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            text = file_bytes.decode("latin-1", errors="replace")

        # Detección de delimitador
        first_few_lines = "\n".join(text.splitlines()[:5])
        delimiter = ";"
        if first_few_lines.count(";") < first_few_lines.count(",") and first_few_lines.count(",") > 2:
            delimiter = ","
        elif first_few_lines.count("\t") > first_few_lines.count(";"):
            delimiter = "\t"

        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        raw_rows = list(reader)
        if not raw_rows:
            return [], []

        # Buscar encabezados
        header_row_idx = 0
        for idx, row in enumerate(raw_rows[:10]):
            clean_cells = [clean_string(c) for c in row if c]
            if any("documento" in c or "aprendiz" in c or "resultado" in c or "competencia" in c or "ficha" in c for c in clean_cells):
                header_row_idx = idx
                break

        headers = [c.strip() if c.strip() else f"Columna_{i+1}" for i, c in enumerate(raw_rows[header_row_idx])]
        data_rows = []
        for r in raw_rows[header_row_idx + 1:]:
            if not any(r):
                continue
            row_dict = {}
            for i, h in enumerate(headers):
                row_dict[h] = r[i].strip() if i < len(r) else None
            data_rows.append(row_dict)

        return headers, data_rows


def auto_detect_columns(headers: List[str]) -> Dict[str, Optional[str]]:
    """Mapea automáticamente los encabezados a los campos requeridos del SENA con alta precisión."""
    mapping: Dict[str, Optional[str]] = {}
    normalized_headers = {h: clean_string(h) for h in headers}

    # 1. Primer pase: Coincidencia exacta
    for key, synonyms in COLUMN_SYNONYMS.items():
        matched = None
        for syn in synonyms:
            clean_syn = clean_string(syn)
            for orig_h, norm_h in normalized_headers.items():
                if clean_syn == norm_h:
                    matched = orig_h
                    break
            if matched:
                break
        if matched:
            mapping[key] = matched

    # 2. Segundo pase: Coincidencia por contención con filtros estrictos anti-colisión
    for key, synonyms in COLUMN_SYNONYMS.items():
        if mapping.get(key):
            continue
        matched = None
        for syn in synonyms:
            clean_syn = clean_string(syn)
            for orig_h, norm_h in normalized_headers.items():
                # Evitar colisiones conocidas en reportes de SofiaPlus
                if key == "documento" and "tipo" in norm_h:
                    continue  # Saltar 'Tipo de Documento' para asignar el 'Número de Documento'
                if key == "aprendiz" and any(x in norm_h for x in ["resultado", "competencia", "estado", "fecha"]):
                    continue  # Evitar que 'Resultado de Aprendizaje' sea tomado como el aprendiz
                if key == "juicio" and any(x in norm_h for x in ["fecha", "hora", "funcionario", "instructor"]):
                    continue  # Evitar que 'Fecha y Hora del Juicio' o funcionario sea tomado como juicio
                if key == "fecha_juicio" and any(x in norm_h for x in ["funcionario", "instructor"]):
                    continue
                if key == "rap" and any(x in norm_h for x in ["funcionario", "instructor"]):
                    continue

                if clean_syn in norm_h:
                    matched = orig_h
                    break
            if matched:
                break
        mapping[key] = matched

    # Verificación final para 'documento': si quedó asignado a 'Tipo de Documento', reasignar
    if mapping.get("documento") and "tipo" in clean_string(mapping["documento"]):
        for orig_h, norm_h in normalized_headers.items():
            if "numero" in norm_h and "documento" in norm_h:
                mapping["documento"] = orig_h
                break

    return mapping



class SenaAnalyzer:
    """Motor de análisis de avance real frente a los RAPs para grupos de formación SENA."""

    def __init__(self, file_bytes: bytes, filename: str, custom_mapping: Optional[Dict[str, str]] = None):
        self.filename = filename
        self.headers, self.raw_data = SenaReader.read_file(file_bytes, filename)
        self.column_mapping = custom_mapping or auto_detect_columns(self.headers)

    def get_available_columns(self) -> List[str]:
        return list(self.headers)

    def get_detected_columns(self) -> Dict[str, Optional[str]]:
        return dict(self.column_mapping)

    def get_unique_states(self) -> List[str]:
        col_estado = self.column_mapping.get("estado_aprendiz")
        if not col_estado:
            return []
        states = set()
        for r in self.raw_data:
            val = r.get(col_estado)
            if val is not None and str(val).strip():
                states.add(str(val).strip().upper())
        return sorted(list(states))

    def run_analysis(
        self,
        filter_estados: Optional[List[str]] = None,
        umbral_verde: float = 80.0,
        umbral_amarillo: float = 50.0
    ) -> Dict[str, Any]:
        """
        Ejecuta el análisis y retorna un diccionario completo con métricas,
        semáforos, listados de aprendices y RAPs.
        """
        mapping = self.column_mapping

        # Validar columnas mínimas
        col_doc = mapping.get("documento")
        col_rap = mapping.get("rap")
        col_juicio = mapping.get("juicio")

        if not col_doc or not col_rap or not col_juicio:
            faltantes = []
            if not col_doc: faltantes.append("Documento Aprendiz")
            if not col_rap: faltantes.append("Resultado de Aprendizaje (RAP)")
            if not col_juicio: faltantes.append("Juicio Evaluativo")
            raise ValueError(f"Faltan columnas indispensables: {', '.join(faltantes)}. Por favor defina el mapeo manual.")

        col_aprendiz = mapping.get("aprendiz")
        col_comp = mapping.get("competencia")
        col_estado = mapping.get("estado_aprendiz")
        col_ficha = mapping.get("ficha")
        col_prog = mapping.get("programa")
        col_instructor = mapping.get("instructor")

        # 1. Filtrado de registros y recolección de metadatos
        fichas_encontradas = set()
        programas_encontrados = set()
        estados_totales = set()
        aprendices_totales_set = set()

        # Almacenar juicios limpios: (doc, rap) -> juicio más favorable (A > D > P)
        # y metadatos del aprendiz: doc -> {nombre, estado}
        # y metadatos del RAP: rap -> {competencia, instructor}
        aprendiz_meta: Dict[str, Dict[str, str]] = {}
        rap_meta: Dict[str, Dict[str, str]] = {}
        
        # Primero una pasada para conocer todos los aprendices y estados
        for row in self.raw_data:
            doc_raw = row.get(col_doc)
            if doc_raw is None or not str(doc_raw).strip():
                continue
            doc = str(doc_raw).strip().replace(".0", "")
            aprendices_totales_set.add(doc)

            if col_estado:
                est = str(row.get(col_estado) or "").strip().upper()
                if est:
                    estados_totales.add(est)

            if col_ficha:
                f = str(row.get(col_ficha) or "").strip()
                if f: fichas_encontradas.add(f)

            if col_prog:
                p = str(row.get(col_prog) or "").strip()
                if p: programas_encontrados.add(p)

        # Filtro de aprendices por estado seleccionado
        filter_set = set([str(x).strip().upper() for x in filter_estados]) if filter_estados else None

        # Matriz: doc -> {rap: juicio}
        matriz_juicios: Dict[str, Dict[str, str]] = defaultdict(dict)

        for row in self.raw_data:
            doc_raw = row.get(col_doc)
            rap_raw = row.get(col_rap)
            if doc_raw is None or rap_raw is None:
                continue

            doc = str(doc_raw).strip().replace(".0", "")
            rap = str(rap_raw).strip()
            if not doc or not rap:
                continue

            # Verificar estado si se aplica filtro
            est_aprendiz = str(row.get(col_estado) or "EN FORMACIÓN").strip().upper() if col_estado else "EN FORMACIÓN"
            if filter_set and est_aprendiz not in filter_set:
                continue

            # Nombre
            nom = doc
            if col_aprendiz and row.get(col_aprendiz):
                nom = str(row.get(col_aprendiz)).strip().upper()

            if doc not in aprendiz_meta:
                aprendiz_meta[doc] = {"doc": doc, "nombre": nom, "estado": est_aprendiz}

            # Metadatos del RAP
            comp = str(row.get(col_comp) or "COMPETENCIA GENERAL").strip() if col_comp else "COMPETENCIA GENERAL"
            inst = str(row.get(col_instructor) or "No especificado").strip() if col_instructor else "No especificado"
            if rap not in rap_meta:
                rap_meta[rap] = {"rap": rap, "competencia": comp, "instructor": inst}

            # Juicio
            raw_j = row.get(col_juicio)
            norm_j = normalize_juicio(raw_j)

            # Prioridad de juicio en caso de registros duplicados: 'A' > 'D' > 'P'
            curr_j = matriz_juicios[doc].get(rap, "P")
            if curr_j == "A":
                pass
            elif norm_j == "A":
                matriz_juicios[doc][rap] = "A"
            elif norm_j == "D" and curr_j != "A":
                matriz_juicios[doc][rap] = "D"
            elif curr_j not in ["A", "D"]:
                matriz_juicios[doc][rap] = norm_j

        total_aprendices_analizados = len(aprendiz_meta)
        if total_aprendices_analizados == 0:
            raise ValueError("No se encontraron aprendices para analizar con el filtro de estado seleccionado.")

        lista_raps = sorted(list(rap_meta.keys()))
        total_raps = len(lista_raps)
        lista_docs = sorted(list(aprendiz_meta.keys()), key=lambda d: aprendiz_meta[d]["nombre"])

        # -------------------------------------------------------------
        # 2. CÁLCULO DETALLADO POR RAP
        # -------------------------------------------------------------
        resumen_raps = []
        for rap in lista_raps:
            n_aprob = 0
            n_defic = 0
            n_pend = 0

            for doc in lista_docs:
                j = matriz_juicios[doc].get(rap, "P")
                if j == "A":
                    n_aprob += 1
                elif j == "D":
                    n_defic += 1
                else:
                    n_pend += 1

            pct_aprob = round((n_aprob / total_aprendices_analizados) * 100, 1)
            pct_defic = round((n_defic / total_aprendices_analizados) * 100, 1)
            pct_pend = round((n_pend / total_aprendices_analizados) * 100, 1)

            if pct_aprob >= umbral_verde:
                semaforo = "🟢 Óptimo"
                categoria_cod = "optimo"
            elif pct_aprob >= umbral_amarillo:
                semaforo = "🟡 En Avance"
                categoria_cod = "en_avance"
            else:
                semaforo = "🔴 Crítico / Rezago"
                categoria_cod = "critico"

            resumen_raps.append({
                "rap": rap,
                "competencia": rap_meta[rap]["competencia"],
                "instructor": rap_meta[rap]["instructor"],
                "aprobados": n_aprob,
                "deficientes": n_defic,
                "pendientes": n_pend,
                "porcentaje_aprobado": pct_aprob,
                "porcentaje_deficiente": pct_defic,
                "porcentaje_pendiente": pct_pend,
                "semaforo": semaforo,
                "categoria_cod": categoria_cod
            })

        # Ordenar RAPs: primero los críticos (menor avance) para enfocar atención
        resumen_raps.sort(key=lambda x: (x["porcentaje_aprobado"], x["aprobados"]))

        # -------------------------------------------------------------
        # 3. CÁLCULO DETALLADO POR APRENDIZ
        # -------------------------------------------------------------
        resumen_aprendices = []
        for doc in lista_docs:
            info = aprendiz_meta[doc]
            n_aprob = 0
            n_defic = 0
            n_pend = 0
            raps_def_list = []
            raps_pend_list = []

            for rap in lista_raps:
                j = matriz_juicios[doc].get(rap, "P")
                if j == "A":
                    n_aprob += 1
                elif j == "D":
                    n_defic += 1
                    raps_def_list.append(rap)
                else:
                    n_pend += 1
                    raps_pend_list.append(rap)

            pct_avance = round((n_aprob / total_raps) * 100, 1) if total_raps > 0 else 0.0

            if pct_avance >= umbral_verde:
                situacion = "🟢 Al Día"
                situacion_cod = "al_dia"
            elif pct_avance >= umbral_amarillo:
                situacion = "🟡 En Observación"
                situacion_cod = "observacion"
            else:
                situacion = "🔴 Alto Riesgo Académico"
                situacion_cod = "riesgo"

            resumen_aprendices.append({
                "documento": doc,
                "nombre": info["nombre"],
                "estado_sofia": info["estado"],
                "raps_aprobados": n_aprob,
                "raps_deficientes": n_defic,
                "raps_pendientes": n_pend,
                "porcentaje_avance": pct_avance,
                "situacion": situacion,
                "situacion_cod": situacion_cod,
                "raps_deficientes_lista": raps_def_list,
                "raps_pendientes_lista": raps_pend_list,
                "total_faltantes": n_defic + n_pend
            })

        # Ordenar por menor avance
        resumen_aprendices.sort(key=lambda x: (x["porcentaje_avance"], x["raps_aprobados"]))

        # -------------------------------------------------------------
        # 4. ANÁLISIS POR COMPETENCIA
        # -------------------------------------------------------------
        competencias_dict: Dict[str, List[str]] = defaultdict(list)
        for rap, meta in rap_meta.items():
            competencias_dict[meta["competencia"]].append(rap)

        resumen_competencias = []
        for comp_name, comp_raps in competencias_dict.items():
            total_raps_comp = len(comp_raps)
            max_evals = total_raps_comp * total_aprendices_analizados
            aprob_comp = 0
            defic_comp = 0

            for rap in comp_raps:
                for doc in lista_docs:
                    j = matriz_juicios[doc].get(rap, "P")
                    if j == "A":
                        aprob_comp += 1
                    elif j == "D":
                        defic_comp += 1

            pend_comp = max_evals - aprob_comp - defic_comp
            pct_comp = round((aprob_comp / max_evals) * 100, 1) if max_evals > 0 else 0.0

            if pct_comp >= umbral_verde:
                estado_comp = "🟢 Consolidada"
            elif pct_comp >= umbral_amarillo:
                estado_comp = "🟡 En Progreso"
            else:
                estado_comp = "🔴 Rezagada"

            resumen_competencias.append({
                "competencia": comp_name,
                "total_raps": total_raps_comp,
                "aprobados": aprob_comp,
                "deficientes": defic_comp,
                "pendientes": pend_comp,
                "porcentaje_avance": pct_comp,
                "estado": estado_comp,
                "raps": comp_raps
            })

        resumen_competencias.sort(key=lambda x: x["porcentaje_avance"], reverse=True)

        # -------------------------------------------------------------
        # 5. MATRIZ APRENDIZ X RAP (PARA VISUALIZACIÓN)
        # -------------------------------------------------------------
        matriz_tabla = []
        for doc in lista_docs:
            row_vals = {
                "documento": doc,
                "nombre": aprendiz_meta[doc]["nombre"],
                "juicios": {rap: matriz_juicios[doc].get(rap, "P") for rap in lista_raps}
            }
            matriz_tabla.append(row_vals)

        # -------------------------------------------------------------
        # 6. MÉTRICAS GLOBALES CONSOLIDADAS
        # -------------------------------------------------------------
        total_evaluaciones_posibles = total_raps * total_aprendices_analizados
        total_aprobados = sum(r["aprobados"] for r in resumen_raps)
        total_deficientes = sum(r["deficientes"] for r in resumen_raps)
        total_por_evaluar = total_evaluaciones_posibles - total_aprobados - total_deficientes

        pct_avance_real = round((total_aprobados / total_evaluaciones_posibles) * 100, 2) if total_evaluaciones_posibles > 0 else 0.0
        
        evaluaciones_emitidas = total_aprobados + total_deficientes
        pct_aprob_evaluados = round((total_aprobados / evaluaciones_emitidas) * 100, 2) if evaluaciones_emitidas > 0 else 0.0
        pct_cobertura = round((evaluaciones_emitidas / total_evaluaciones_posibles) * 100, 2) if total_evaluaciones_posibles > 0 else 0.0

        raps_criticos = sum(1 for r in resumen_raps if r["categoria_cod"] == "critico")
        raps_en_avance = sum(1 for r in resumen_raps if r["categoria_cod"] == "en_avance")
        raps_optimos = sum(1 for r in resumen_raps if r["categoria_cod"] == "optimo")

        aprendices_al_dia = sum(1 for a in resumen_aprendices if a["situacion_cod"] == "al_dia")
        aprendices_observacion = sum(1 for a in resumen_aprendices if a["situacion_cod"] == "observacion")
        aprendices_riesgo = sum(1 for a in resumen_aprendices if a["situacion_cod"] == "riesgo")

        ficha_text = ", ".join(sorted(list(fichas_encontradas))[:3]) if fichas_encontradas else "Ficha no especificada"
        programa_text = next(iter(programas_encontrados)) if programas_encontrados else "Programa de Formación SENA"

        return {
            "meta": {
                "ficha": ficha_text,
                "programa": programa_text,
                "total_aprendices_totales": len(aprendices_totales_set),
                "total_aprendices_analizados": total_aprendices_analizados,
                "estados_disponibles": sorted(list(estados_totales)),
                "total_raps": total_raps,
                "total_competencias": len(competencias_dict),
                "umbral_verde": umbral_verde,
                "umbral_amarillo": umbral_amarillo
            },
            "kpis": {
                "porcentaje_avance_real": pct_avance_real,
                "porcentaje_aprobacion_evaluados": pct_aprob_evaluados,
                "porcentaje_cobertura_evaluativa": pct_cobertura,
                "total_evaluaciones_posibles": total_evaluaciones_posibles,
                "total_aprobados": total_aprobados,
                "total_deficientes": total_deficientes,
                "total_por_evaluar": total_por_evaluar,
                "raps_criticos": raps_criticos,
                "raps_en_avance": raps_en_avance,
                "raps_optimos": raps_optimos,
                "aprendices_al_dia": aprendices_al_dia,
                "aprendices_observacion": aprendices_observacion,
                "aprendices_riesgo": aprendices_riesgo
            },
            "raps": resumen_raps,
            "aprendices": resumen_aprendices,
            "competencias": resumen_competencias,
            "matriz": {
                "raps": lista_raps,
                "filas": matriz_tabla
            }
        }


class MultiFichaAnalyzer:
    """Motor de análisis simultáneo para múltiples fichas y grupos de formación SENA."""

    def __init__(self, files: List[Tuple[str, bytes]], custom_mapping: Optional[Dict[str, str]] = None):
        """
        files: Lista de tuplas (nombre_archivo, contenido_bytes)
        """
        self.files = files
        self.custom_mapping = custom_mapping
        self.analyzers: List[SenaAnalyzer] = []
        
        for fname, fbytes in files:
            analyzer = SenaAnalyzer(fbytes, fname, custom_mapping=custom_mapping)
            self.analyzers.append(analyzer)

    def get_unique_states(self) -> List[str]:
        states = set()
        for a in self.analyzers:
            for s in a.get_unique_states():
                states.add(s)
        return sorted(list(states))

    def run_multi_analysis(
        self,
        filter_estados: Optional[List[str]] = None,
        umbral_verde: float = 80.0,
        umbral_amarillo: float = 50.0
    ) -> Dict[str, Any]:
        """
        Ejecuta el análisis sobre todas las fichas cargadas, generando:
        1. Diagnóstico individual por cada ficha.
        2. Consolidado general y ranking comparativo entre fichas.
        """
        detalle_fichas: Dict[str, Any] = {}
        fichas_resumen: List[Dict[str, Any]] = []

        total_posibles_acum = 0
        total_aprobados_acum = 0
        total_deficientes_acum = 0
        total_pendientes_acum = 0
        total_aprendices_acum = 0
        total_aprendices_totales_acum = 0
        estados_totales = set()
        aprendices_riesgo_todos = []

        for idx, analyzer in enumerate(self.analyzers):
            try:
                res = analyzer.run_analysis(
                    filter_estados=filter_estados,
                    umbral_verde=umbral_verde,
                    umbral_amarillo=umbral_amarillo
                )
            except Exception as e:
                # Si una ficha falla con el filtro de estado, intentar sin filtro
                try:
                    res = analyzer.run_analysis(filter_estados=None, umbral_verde=umbral_verde, umbral_amarillo=umbral_amarillo)
                except Exception as e2:
                    continue

            ficha_id = res["meta"]["ficha"]
            # En caso de fichas con nombre duplicado o no especificado
            if ficha_id in detalle_fichas or not ficha_id or ficha_id == "Ficha no especificada":
                ficha_id = f"{ficha_id} ({analyzer.filename})"

            detalle_fichas[ficha_id] = res

            kpis = res["kpis"]
            total_posibles_acum += kpis["total_evaluaciones_posibles"]
            total_aprobados_acum += kpis["total_aprobados"]
            total_deficientes_acum += kpis["total_deficientes"]
            total_pendientes_acum += kpis["total_por_evaluar"]
            total_aprendices_acum += res["meta"]["total_aprendices_analizados"]
            total_aprendices_totales_acum += res["meta"]["total_aprendices_totales"]
            estados_totales.update(res["meta"]["estados_disponibles"])

            # Semáforo de la ficha
            pct_av = kpis["porcentaje_avance_real"]
            if pct_av >= umbral_verde:
                sem = "🟢 Óptimo"
                sem_cod = "optimo"
            elif pct_av >= umbral_amarillo:
                sem = "🟡 En Avance"
                sem_cod = "en_avance"
            else:
                sem = "🔴 Crítico"
                sem_cod = "critico"

            ficha_item = {
                "id": ficha_id,
                "ficha": res["meta"]["ficha"],
                "archivo": analyzer.filename,
                "programa": res["meta"]["programa"],
                "total_aprendices": res["meta"]["total_aprendices_analizados"],
                "total_raps": res["meta"]["total_raps"],
                "porcentaje_avance": pct_av,
                "porcentaje_aprobacion": kpis["porcentaje_aprobacion_evaluados"],
                "porcentaje_cobertura": kpis["porcentaje_cobertura_evaluativa"],
                "aprobados": kpis["total_aprobados"],
                "deficientes": kpis["total_deficientes"],
                "pendientes": kpis["total_por_evaluar"],
                "raps_criticos": kpis["raps_criticos"],
                "aprendices_riesgo": kpis["aprendices_riesgo"],
                "semaforo": sem,
                "semaforo_cod": sem_cod
            }
            fichas_resumen.append(ficha_item)

            # Acumular aprendices con ficha asociada para la vista de riesgo
            for apr in res["aprendices"]:
                apr_copy = dict(apr)
                apr_copy["ficha"] = res["meta"]["ficha"]
                aprendices_riesgo_todos.append(apr_copy)

        if not detalle_fichas:
            raise ValueError("No se pudo procesar ninguna ficha válida con los archivos proporcionados.")

        # Ordenar fichas por menor avance para visibilizar rezagos
        fichas_resumen.sort(key=lambda x: x["porcentaje_avance"])
        aprendices_riesgo_todos.sort(key=lambda x: (x["porcentaje_avance"], x["raps_aprobados"]))

        # Métricas Globales Consolidadas
        pct_global_avance = round((total_aprobados_acum / total_posibles_acum) * 100, 2) if total_posibles_acum > 0 else 0.0
        evaluaciones_emitidas_acum = total_aprobados_acum + total_deficientes_acum
        pct_global_aprob = round((total_aprobados_acum / evaluaciones_emitidas_acum) * 100, 2) if evaluaciones_emitidas_acum > 0 else 0.0
        pct_global_cobertura = round((evaluaciones_emitidas_acum / total_posibles_acum) * 100, 2) if total_posibles_acum > 0 else 0.0

        consolidado = {
            "meta": {
                "ficha": f"Consolidado General ({len(detalle_fichas)} Fichas)",
                "programa": "Múltiples Programas de Formación SENA" if len(set(f["programa"] for f in fichas_resumen)) > 1 else fichas_resumen[0]["programa"],
                "total_fichas": len(detalle_fichas),
                "total_aprendices_totales": total_aprendices_totales_acum,
                "total_aprendices_analizados": total_aprendices_acum,
                "estados_disponibles": sorted(list(estados_totales)),
                "total_raps": sum(f["total_raps"] for f in fichas_resumen),
                "umbral_verde": umbral_verde,
                "umbral_amarillo": umbral_amarillo
            },
            "kpis": {
                "porcentaje_avance_real": pct_global_avance,
                "porcentaje_aprobacion_evaluados": pct_global_aprob,
                "porcentaje_cobertura_evaluativa": pct_global_cobertura,
                "total_evaluaciones_posibles": total_posibles_acum,
                "total_aprobados": total_aprobados_acum,
                "total_deficientes": total_deficientes_acum,
                "total_por_evaluar": total_pendientes_acum,
                "raps_criticos": sum(f["raps_criticos"] for f in fichas_resumen),
                "raps_en_avance": sum(detalle_fichas[f["id"]]["kpis"]["raps_en_avance"] for f in fichas_resumen),
                "raps_optimos": sum(detalle_fichas[f["id"]]["kpis"]["raps_optimos"] for f in fichas_resumen),
                "aprendices_al_dia": sum(detalle_fichas[f["id"]]["kpis"]["aprendices_al_dia"] for f in fichas_resumen),
                "aprendices_observacion": sum(detalle_fichas[f["id"]]["kpis"]["aprendices_observacion"] for f in fichas_resumen),
                "aprendices_riesgo": sum(f["aprendices_riesgo"] for f in fichas_resumen)
            },
            "tabla_fichas": fichas_resumen,
            "aprendices": aprendices_riesgo_todos,
            "raps": [],
            "competencias": [],
            "matriz": {"raps": [], "filas": []}
        }

        # Lista de selección para la interfaz
        fichas_nav = [{
            "id": "ALL",
            "label": f"📊 Todas las Fichas ({len(detalle_fichas)})",
            "programa": "Vista Consolidada",
            "aprendices": total_aprendices_acum,
            "avance": pct_global_avance,
            "semaforo": "Consolidado"
        }]
        for f in fichas_resumen:
            fichas_nav.append({
                "id": f["id"],
                "label": f"Ficha {f['ficha']} ({f['total_aprendices']} apr.)",
                "programa": f["programa"],
                "aprendices": f["total_aprendices"],
                "avance": f["porcentaje_avance"],
                "semaforo": f["semaforo"]
            })

        return {
            "is_multi_ficha": len(detalle_fichas) > 1,
            "total_fichas": len(detalle_fichas),
            "fichas_selector": fichas_nav,
            "consolidado": consolidado,
            "detalle_fichas": detalle_fichas
        }

