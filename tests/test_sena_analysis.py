"""
Batería de Pruebas Automatizadas de Calidad (QA) para el Analizador de RAPs SENA.
Ejecuta validaciones unitarias, de integración y de precisión matemática sobre datos reales.
"""

import os
import sys
import unittest
import openpyxl

# Agregar directorio raíz para importación de módulos
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sena_processor import clean_string, normalize_juicio, auto_detect_columns, SenaReader, SenaAnalyzer
from export_utils import create_excel_report
from sample_data import generate_sample_excel


class TestNormalizacion(unittest.TestCase):
    """Pruebas unitarias de limpieza de cadenas y normalización de juicios evaluativos."""

    def test_clean_string(self):
        self.assertEqual(clean_string("  Número de Documento  "), "numero de documento")
        self.assertEqual(clean_string("Juicio Evaluativo (Calificación)"), "juicio evaluativo calificacion")
        self.assertEqual(clean_string("Bogotá D.C."), "bogota d c")
        self.assertEqual(clean_string(None), "")

    def test_normalize_juicio(self):
        # Aprobados
        self.assertEqual(normalize_juicio("A"), "A")
        self.assertEqual(normalize_juicio("APROBADO"), "A")
        self.assertEqual(normalize_juicio("Aprobó"), "A")
        self.assertEqual(normalize_juicio("1"), "A")
        self.assertEqual(normalize_juicio("SI"), "A")

        # Deficientes
        self.assertEqual(normalize_juicio("D"), "D")
        self.assertEqual(normalize_juicio("DEFICIENTE"), "D")
        self.assertEqual(normalize_juicio("No Aprobado"), "D")
        self.assertEqual(normalize_juicio("0"), "D")

        # Pendientes / Por Evaluar
        self.assertEqual(normalize_juicio("POR EVALUAR"), "P")
        self.assertEqual(normalize_juicio("Pendiente"), "P")
        self.assertEqual(normalize_juicio("SIN EVALUAR"), "P")
        self.assertEqual(normalize_juicio(""), "P")
        self.assertEqual(normalize_juicio(None), "P")
        self.assertEqual(normalize_juicio("N/A"), "P")


class TestMapeoColumnas(unittest.TestCase):
    """Pruebas de detección inteligente y desambiguación de encabezados."""

    def test_auto_detect_columns_sofia_plus(self):
        headers = [
            "Tipo de Documento",
            "Número de Documento",
            "Nombre",
            "Apellidos",
            "Nombre Aprendiz",
            "Estado",
            "Competencia",
            "Resultado de Aprendizaje",
            "Juicio de Evaluación",
            "Fecha y Hora del Juicio Evaluativo",
            "Funcionario que registro el juicio evaluativo",
            "Número Ficha",
            "Programa de Formación"
        ]
        mapping = auto_detect_columns(headers)

        self.assertEqual(mapping.get("documento"), "Número de Documento", "No debe confundirse con 'Tipo de Documento'")
        self.assertEqual(mapping.get("aprendiz"), "Nombre Aprendiz", "No debe confundirse con 'Resultado de Aprendizaje'")
        self.assertEqual(mapping.get("juicio"), "Juicio de Evaluación", "No debe confundirse con 'Fecha y Hora del Juicio'")
        self.assertEqual(mapping.get("rap"), "Resultado de Aprendizaje")
        self.assertEqual(mapping.get("competencia"), "Competencia")
        self.assertEqual(mapping.get("estado_aprendiz"), "Estado")
        self.assertEqual(mapping.get("ficha"), "Número Ficha")
        self.assertEqual(mapping.get("programa"), "Programa de Formación")


class TestAnalisisDatosMuestra(unittest.TestCase):
    """Pruebas de procesamiento con datos de muestra sintéticos (ADSO Ficha 2714589)."""

    @classmethod
    def setUpClass(cls):
        cls.sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "muestra_sena_juicios_evaluativos.xlsx")
        if not os.path.exists(cls.sample_path):
            generate_sample_excel(cls.sample_path)
        with open(cls.sample_path, "rb") as f:
            cls.content = f.read()

    def test_analisis_muestra(self):
        analyzer = SenaAnalyzer(self.content, "muestra.xlsx")
        res = analyzer.run_analysis(filter_estados=["EN FORMACIÓN"])

        self.assertEqual(res["meta"]["ficha"], "2714589")
        self.assertEqual(res["meta"]["total_raps"], 10)
        self.assertEqual(res["meta"]["total_aprendices_analizados"], 23)
        self.assertGreater(res["kpis"]["porcentaje_avance_real"], 50.0)
        self.assertLessEqual(res["kpis"]["porcentaje_avance_real"], 100.0)


class TestAnalisisDatosRealesSofiaPlus(unittest.TestCase):
    """Pruebas de validación pedagógica y matemática con el archivo REAL de SofiaPlus (Ficha 3239137)."""

    @classmethod
    def setUpClass(cls):
        cls.real_path = os.path.join(os.path.dirname(__file__), "..", "data", "Reporte_de_Juicios_Evaluativos.xls")
        if not os.path.exists(cls.real_path):
            raise unittest.SkipTest("Archivo real Reporte_de_Juicios_Evaluativos.xls no disponible para pruebas.")
        with open(cls.real_path, "rb") as f:
            cls.content = f.read()

    def test_analisis_reporte_real(self):
        analyzer = SenaAnalyzer(self.content, "Reporte_de_Juicios_Evaluativos.xls")
        res = analyzer.run_analysis(filter_estados=["EN FORMACION"])

        # Metadatos del grupo
        self.assertEqual(res["meta"]["ficha"], "3239137")
        self.assertIn("ANALISIS Y DESARROLLO DE SOFTWARE", res["meta"]["programa"])
        self.assertEqual(res["meta"]["total_aprendices_analizados"], 28)
        self.assertEqual(res["meta"]["total_raps"], 75)

        # Validación Matemática de la Fórmula del SENA
        total_posibles = 28 * 75  # 2100
        self.assertEqual(res["kpis"]["total_evaluaciones_posibles"], total_posibles)
        
        aprobados = res["kpis"]["total_aprobados"]
        esperado_avance = round((aprobados / total_posibles) * 100, 2)
        self.assertEqual(res["kpis"]["porcentaje_avance_real"], esperado_avance)
        self.assertAlmostEqual(res["kpis"]["porcentaje_avance_real"], 58.29, delta=0.1)

        # Eficacia: Aprobados / (Aprobados + Deficientes)
        evaluados = res["kpis"]["total_aprobados"] + res["kpis"]["total_deficientes"]
        esperado_eficacia = round((res["kpis"]["total_aprobados"] / evaluados) * 100, 2)
        self.assertEqual(res["kpis"]["porcentaje_aprobacion_evaluados"], esperado_eficacia)

        # Semáforo de RAPs
        total_raps_clasificados = res["kpis"]["raps_criticos"] + res["kpis"]["raps_en_avance"] + res["kpis"]["raps_optimos"]
        self.assertEqual(total_raps_clasificados, 75)


class TestExportacionExcel(unittest.TestCase):
    """Pruebas de generación del archivo oficial de reporte en Excel."""

    def test_generacion_excel_valida(self):
        sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "muestra_sena_juicios_evaluativos.xlsx")
        with open(sample_path, "rb") as f:
            content = f.read()

        analyzer = SenaAnalyzer(content, "muestra.xlsx")
        analysis = analyzer.run_analysis()
        excel_bytes = create_excel_report(analysis)

        self.assertGreater(len(excel_bytes), 5000, "El archivo Excel generado debe ser un binario válido y no vacío.")

        # Abrir y verificar las 4 hojas
        import io
        wb = openpyxl.load_workbook(io.BytesIO(excel_bytes))
        sheet_names = wb.sheetnames
        self.assertIn("Resumen Ejecutivo", sheet_names)
        self.assertIn("Semáforo de RAPs", sheet_names)
        self.assertIn("Seguimiento de Aprendices", sheet_names)
        self.assertIn("Matriz Aprendiz vs RAP", sheet_names)


if __name__ == "__main__":
    unittest.main()
