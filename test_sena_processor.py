import pytest
import os
from sena_processor import SenaAnalyzer
from sample_data import generate_sample_excel

def test_sena_analyzer_logic():
    # Use the real sample generator to create valid data
    test_file_path = os.path.join(os.getcwd(), "test_sample.xlsx")
    sample_path = generate_sample_excel(test_file_path)
    with open(sample_path, "rb") as f:
        file_bytes = f.read()

    analyzer = SenaAnalyzer(file_bytes, "test_sample.xlsx")

    assert len(analyzer.raw_data) > 0, "Debería haber datos crudos"
    assert len(analyzer.headers) > 0, "Debería haber columnas"

    # Analyze with valid state
    analysis = analyzer.run_analysis(filter_estados=["EN FORMACIÓN"])

    # Basic structure assertions
    assert "kpis" in analysis
    assert "raps" in analysis
    assert "aprendices" in analysis
    assert "competencias" in analysis
    assert "matriz" in analysis

    kpis = analysis["kpis"]
    assert kpis["total_aprobados"] >= 0
    assert kpis["total_evaluaciones_posibles"] > 0
    assert kpis["porcentaje_avance_real"] >= 0.0

    # Test umbral calculation logic indirectly
    for rap in analysis["raps"]:
        assert "aprobados" in rap
        assert "deficientes" in rap
        assert "porcentaje_aprobado" in rap
        assert "semaforo" in rap
        assert rap["semaforo"] in ["🟢 Óptimo", "🟡 En Avance", "🔴 Crítico / Rezago"]

    for aprendiz in analysis["aprendices"]:
        assert "porcentaje_avance" in aprendiz
        assert "situacion" in aprendiz
        assert aprendiz["situacion"] in ["🟢 Al Día", "🟡 En Observación", "🔴 Alto Riesgo Académico"]

    os.remove(test_file_path)
