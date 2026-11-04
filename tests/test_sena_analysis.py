"""
Batería de Pruebas Automatizadas de Calidad (QA) para el Analizador de RAPs SENA.
Ejecuta validaciones unitarias, de integración, base de datos histórica, migraciones Liquibase,
autenticación JWT, marco de seguridad (RBAC + auditoría encadenada) y consulta de registros Excel.
"""

import copy
import os
import sqlite3
import sys
import tempfile
import unittest
import openpyxl

# Agregar directorio raíz para importación de módulos
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sena_processor import clean_string, normalize_juicio, auto_detect_columns, SenaReader, SenaAnalyzer
from export_utils import create_excel_report
from sample_data import generate_sample_excel
from database import LiquibaseRunner, SenaHistoryRepository
from auth import AuthService
from security import SecurityService
from excel_records import ExcelRecordRepository


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


class TestLiquibaseYBaseDatosHistorica(unittest.TestCase):
    """Pruebas de control de cambios Liquibase, seguridad RBAC, JWT y registros Excel en SQLite."""

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_db = os.path.join(self.tmp_dir.name, "test_historico.db")

    def tearDown(self):
        self.tmp_dir.cleanup()

    def test_liquibase_migrations_and_rollback(self):
        runner = LiquibaseRunner(db_path=self.test_db)
        res = runner.update()
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["applied_count"], 16)

        # Segunda ejecución debe ser idempotente (0 aplicados)
        res2 = runner.update()
        self.assertEqual(res2["applied_count"], 0)
        self.assertEqual(res2["previously_executed"], 16)

        # Verificar estado
        st = runner.status()
        self.assertTrue(st["up_to_date"])
        self.assertEqual(st["executed_count"], 16)

        # Probar rollback del último changeset y reaplicación
        rb = runner.rollback(count=1)
        self.assertEqual(rb["rolled_back_count"], 1)
        st_after_rb = runner.status()
        self.assertFalse(st_after_rb["up_to_date"])
        self.assertEqual(st_after_rb["pending_count"], 1)

        res3 = runner.update()
        self.assertEqual(res3["applied_count"], 1)

    def test_guardar_y_comparar_historico(self):
        sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "muestra_sena_juicios_evaluativos.xlsx")
        with open(sample_path, "rb") as f:
            content = f.read()

        analyzer = SenaAnalyzer(content, "muestra.xlsx")
        analysis_1 = analyzer.run_analysis(filter_estados=["EN FORMACIÓN"])

        repo = SenaHistoryRepository(db_path=self.test_db)
        save_1 = repo.save_analysis(analysis_1, "corte_1.xlsx", file_bytes=content, observaciones="Corte 1")
        self.assertTrue(save_1["saved"])
        self.assertEqual(save_1["cambios_detectados"], 0)

        # Simular segundo corte donde un aprendiz aprueba un RAP pendiente/deficiente
        analysis_2 = copy.deepcopy(analysis_1)
        analysis_2["kpis"]["porcentaje_avance_real"] = round(analysis_1["kpis"]["porcentaje_avance_real"] + 2.5, 2)
        primera_fila = analysis_2["matriz"]["filas"][0]
        primer_rap = analysis_2["matriz"]["raps"][0]
        primera_fila["juicios"][primer_rap] = "A" if primera_fila["juicios"][primer_rap] != "A" else "D"

        save_2 = repo.save_analysis(analysis_2, "corte_2.xlsx", observaciones="Corte 2")
        self.assertTrue(save_2["saved"])
        self.assertEqual(save_2["cambios_detectados"], 1)

        hist = repo.list_history(ficha="2714589")
        self.assertEqual(len(hist["items"]), 2)
        self.assertEqual(hist["items"][0]["cambios_juicios_count"], 1)
        self.assertAlmostEqual(hist["items"][0]["delta_avance"], 2.5, places=1)

    def test_autenticacion_jwt_ciclo_completo(self):
        auth = AuthService(db_path=self.test_db)

        # 1. Login exitoso con usuario por defecto
        res = auth.login("instructor", "sena2026")
        self.assertIn("token", res)
        self.assertEqual(res["user"]["username"], "instructor")
        self.assertEqual(res["user"]["rol"], "INSTRUCTOR")

        token = res["token"]
        self.assertEqual(len(token.split(".")), 3)

        # 2. Verificación del token JWT
        claims = auth.verify_token(token)
        self.assertEqual(claims["username"], "instructor")

        # 3. Rechazo de contraseña incorrecta
        with self.assertRaises(ValueError):
            auth.login("instructor", "clave_erronea")

        # 4. Rechazo de firma manipulada (tampering)
        tampered = token[:-4] + "XXXX"
        with self.assertRaises(ValueError):
            auth.verify_token(tampered)

        # 5. Revocación del token al cerrar sesión (logout)
        self.assertTrue(auth.logout(token))
        with self.assertRaises(ValueError):
            auth.verify_token(token)

    def test_marco_seguridad_y_almacenamiento_registros_excel(self):
        sec = SecurityService(db_path=self.test_db)

        # 1. RBAC: Instructor puede ver registros pero no eliminar ni ver auditoría
        self.assertTrue(sec.has_permission("INSTRUCTOR", "registros.ver"))
        self.assertFalse(sec.has_permission("INSTRUCTOR", "registros.eliminar"))
        self.assertTrue(sec.has_permission("COORDINADOR", "registros.eliminar"))
        self.assertTrue(sec.has_permission("COORDINADOR", "auditoria.ver"))

        # 2. Bitácora encadenada con SHA-256 e inmutabilidad por triggers
        sec.log_event("TEST_EVENTO_1", username="coordinador", rol="COORDINADOR", recurso="recurso_1")
        sec.log_event("TEST_EVENTO_2", username="instructor", rol="INSTRUCTOR", recurso="recurso_2")
        chain = sec.verify_chain()
        self.assertTrue(chain["valid"])
        self.assertEqual(chain["total_eventos"], 2)

        conn = sqlite3.connect(self.test_db)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("DELETE FROM auditoria_eventos WHERE id = 1;")
        conn.close()

        # 3. Almacenamiento y consulta fila a fila de registros Excel
        sample_path = os.path.join(os.path.dirname(__file__), "..", "data", "muestra_sena_juicios_evaluativos.xlsx")
        with open(sample_path, "rb") as f:
            content = f.read()

        analyzer = SenaAnalyzer(content, "muestra.xlsx")
        analysis = analyzer.run_analysis(filter_estados=["EN FORMACIÓN"])

        rec_repo = ExcelRecordRepository(db_path=self.test_db)
        store_res = rec_repo.store_upload(
            content, "muestra.xlsx", analyzer.headers, analyzer.raw_data, analyzer.column_mapping,
            meta=analysis["meta"]
        )
        self.assertTrue(store_res["stored"])
        self.assertEqual(store_res["total_filas"], 250)

        # Consulta filtrada por juicio A
        q_res = rec_repo.query({"ficha": "2714589", "juicio": "A"}, page=1, page_size=20)
        self.assertGreater(q_res["total"], 100)
        self.assertEqual(len(q_res["items"]), 20)

        # Verificación de integridad SHA-256 por fila
        integ = rec_repo.verify_integrity(store_res["carga_id"])
        self.assertTrue(integ["integro"])
        self.assertEqual(integ["total_encontrado"], 250)


if __name__ == "__main__":
    unittest.main()
