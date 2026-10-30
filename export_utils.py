"""
Generador de Informes Ejecutivos en Excel para el SENA.
Soporta informes individuales de Ficha y reportes consolidados Multi-Ficha.
"""

import io
from typing import Any, Dict
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter


def create_excel_report(analysis_data: Dict[str, Any]) -> bytes:
    wb = openpyxl.Workbook()

    # Si es una estructura multi-ficha, obtener el consolidado o la ficha principal
    is_multi = analysis_data.get("is_multi_ficha", False) or "tabla_fichas" in analysis_data or "consolidado" in analysis_data
    if "consolidado" in analysis_data:
        consolidado = analysis_data["consolidado"]
        detalle_fichas = analysis_data.get("detalle_fichas", {})
    else:
        consolidado = analysis_data
        detalle_fichas = {}

    # Paleta SENA
    sena_green = "39A900"
    sena_dark = "00324D"
    card_bg = "F4F9F4"
    alert_red = "FF4D4D"
    alert_yellow = "FFB020"

    title_font = Font(name="Segoe UI", size=15, bold=True, color="FFFFFF")
    subtitle_font = Font(name="Segoe UI", size=10, italic=True, color="FFFFFF")
    section_font = Font(name="Segoe UI", size=12, bold=True, color=sena_dark)
    kpi_num_font = Font(name="Segoe UI", size=20, bold=True, color=sena_green)
    kpi_label_font = Font(name="Segoe UI", size=9, bold=True, color="555555")
    header_fill = PatternFill(start_color=sena_dark, end_color=sena_dark, fill_type="solid")
    header_font_white = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")

    thin_border = Border(
        left=Side(style='thin', color='DDDDDD'),
        right=Side(style='thin', color='DDDDDD'),
        top=Side(style='thin', color='DDDDDD'),
        bottom=Side(style='thin', color='DDDDDD')
    )
    fill_green = PatternFill(start_color="E8F8EA", fill_type="solid")
    fill_yellow = PatternFill(start_color="FFF8E7", fill_type="solid")
    fill_red = PatternFill(start_color="FDECEB", fill_type="solid")

    # -------------------------------------------------------------
    # PESTAÑA 1: RESUMEN EJECUTIVO (CONSOLIDADO)
    # -------------------------------------------------------------
    ws_resumen = wb.active
    ws_resumen.title = "Resumen Ejecutivo"
    ws_resumen.views.sheetView[0].showGridLines = True

    # Banner Superior
    for col in range(1, 8):
        for row in range(1, 4):
            c = ws_resumen.cell(row=row, column=col)
            c.fill = PatternFill(start_color=sena_dark, end_color=sena_dark, fill_type="solid")

    ws_resumen.merge_cells("A1:G2")
    banner_cell = ws_resumen.cell(row=1, column=1)
    banner_cell.value = "SENA - INFORME EJECUTIVO DE AVANCE FRENTE A RAPS"
    banner_cell.font = title_font
    banner_cell.alignment = Alignment(horizontal="center", vertical="center")

    ws_resumen.merge_cells("A3:G3")
    meta_cell = ws_resumen.cell(row=3, column=1)
    meta = consolidado["meta"]
    meta_cell.value = f"{meta['ficha']}  |  Programa: {meta['programa']}  |  Aprendices: {meta['total_aprendices_analizados']}"
    meta_cell.font = subtitle_font
    meta_cell.alignment = Alignment(horizontal="center", vertical="center")

    # KPIs Principales
    kpis = consolidado["kpis"]
    kpi_data = [
        ("NIVEL DE AVANCE REAL", f"{kpis['porcentaje_avance_real']}%"),
        ("APROBACIÓN SOBRE EVALUADOS", f"{kpis['porcentaje_aprobacion_evaluados']}%"),
        ("COBERTURA EVALUATIVA", f"{kpis['porcentaje_cobertura_evaluativa']}%"),
        ("RAPS EN REZAGO CRÍTICO", str(kpis['raps_criticos'])),
        ("APRENDICES EN ALTO RIESGO", str(kpis['aprendices_riesgo'])),
        ("APRENDICES AL DÍA", str(kpis['aprendices_al_dia'])),
    ]

    row_offset = 5
    ws_resumen.cell(row=row_offset, column=1, value="INDICADORES CONSOLIDADOS DEL GRUPO").font = section_font
    row_offset += 2

    # Render KPIs Fila 1
    for idx, (label, val) in enumerate(kpi_data[:3]):
        c_val = ws_resumen.cell(row=row_offset, column=idx * 2 + 1, value=val)
        c_val.font = kpi_num_font
        c_val.alignment = Alignment(horizontal="center", vertical="center")
        c_lbl = ws_resumen.cell(row=row_offset + 1, column=idx * 2 + 1, value=label)
        c_lbl.font = kpi_label_font
        c_lbl.alignment = Alignment(horizontal="center", vertical="center")

    row_offset += 3
    # Render KPIs Fila 2
    for idx, (label, val) in enumerate(kpi_data[3:]):
        c_val = ws_resumen.cell(row=row_offset, column=idx * 2 + 1, value=val)
        c_val.font = Font(name="Segoe UI", size=20, bold=True, color=alert_red if "CRÍTICO" in label or "RIESGO" in label else sena_green)
        c_val.alignment = Alignment(horizontal="center", vertical="center")
        c_lbl = ws_resumen.cell(row=row_offset + 1, column=idx * 2 + 1, value=label)
        c_lbl.font = kpi_label_font
        c_lbl.alignment = Alignment(horizontal="center", vertical="center")

    row_offset += 4

    # Si hay tabla comparativa de fichas (Multi-Ficha), incrustarla en el resumen ejecutivo
    if "tabla_fichas" in consolidado and consolidado["tabla_fichas"]:
        ws_resumen.cell(row=row_offset, column=1, value="TABLA COMPARATIVA DE FICHAS DE FORMACIÓN").font = section_font
        row_offset += 1

        headers_tf = [
            "Ficha", "Programa de Formación", "Aprendices", "Total RAPs",
            "Aprobados", "Deficientes", "Pendientes", "% Avance Real", "% Aprobación", "Semáforo"
        ]
        for c_idx, h in enumerate(headers_tf, start=1):
            cell = ws_resumen.cell(row=row_offset, column=c_idx, value=h)
            cell.fill = header_fill
            cell.font = header_font_white
            cell.alignment = Alignment(horizontal="center", vertical="center")
        row_offset += 1

        for f_row in consolidado["tabla_fichas"]:
            row_vals = [
                f_row["ficha"],
                f_row["programa"],
                f_row["total_aprendices"],
                f_row["total_raps"],
                f_row["aprobados"],
                f_row["deficientes"],
                f_row["pendientes"],
                f"{f_row['porcentaje_avance']}%",
                f"{f_row['porcentaje_aprobacion']}%",
                f_row["semaforo"]
            ]
            fill_c = fill_green if f_row["semaforo_cod"] == "optimo" else (fill_yellow if f_row["semaforo_cod"] == "en_avance" else fill_red)
            for c_idx, val in enumerate(row_vals, start=1):
                cell = ws_resumen.cell(row=row_offset, column=c_idx, value=val)
                cell.fill = fill_c
                cell.border = thin_border
                if c_idx not in [2]:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
            row_offset += 1

        row_offset += 2

    # -------------------------------------------------------------
    # PESTAÑA 2: SEGUIMIENTO DE APRENDICES Y RIESGO
    # -------------------------------------------------------------
    ws_apr = wb.create_sheet(title="Seguimiento de Aprendices")
    ws_apr.views.sheetView[0].showGridLines = True

    headers_apr = [
        "Ficha", "Documento", "Nombre Aprendiz", "Estado Sofía", "Aprobados",
        "Deficientes", "Pendientes", "% Avance", "Situación Académica", "RAPs Deficientes (Planes de Mejoramiento)"
    ]
    ws_apr.append(headers_apr)
    for col_idx in range(1, len(headers_apr) + 1):
        c = ws_apr.cell(row=1, column=col_idx)
        c.fill = PatternFill(start_color=sena_green, end_color=sena_green, fill_type="solid")
        c.font = header_font_white
        c.alignment = Alignment(horizontal="center", vertical="center")

    for apr in consolidado.get("aprendices", []):
        def_str = "; ".join(apr.get("raps_deficientes_lista", [])) if apr.get("raps_deficientes_lista") else "Sin juicios deficientes"
        ws_apr.append([
            apr.get("ficha", consolidado["meta"]["ficha"]),
            apr["documento"],
            apr["nombre"],
            apr.get("estado_sofia", "EN FORMACION"),
            apr["raps_aprobados"],
            apr["raps_deficientes"],
            apr["raps_pendientes"],
            f"{apr['porcentaje_avance']}%",
            apr["situacion"],
            def_str
        ])
        curr_row = ws_apr.max_row
        row_fill = fill_green if apr.get("situacion_cod") == "al_dia" else (fill_yellow if apr.get("situacion_cod") == "observacion" else fill_red)
        for col_idx in range(1, len(headers_apr) + 1):
            cell = ws_apr.cell(row=curr_row, column=col_idx)
            cell.fill = row_fill
            cell.border = thin_border
            if col_idx not in [3, 10]:
                cell.alignment = Alignment(horizontal="center", vertical="center")

    # -------------------------------------------------------------
    # PESTAÑA 3: SEMÁFORO DE RAPS (DE LA FICHA ACTIVA O FICHAS)
    # -------------------------------------------------------------
    raps_data = consolidado.get("raps")
    if not raps_data and detalle_fichas:
        # Si el consolidado no tiene RAPs agregados, tomar los de la primera ficha
        first_f = next(iter(detalle_fichas.values()))
        raps_data = first_f.get("raps", [])

    if raps_data:
        ws_raps = wb.create_sheet(title="Semáforo de RAPs")
        ws_raps.views.sheetView[0].showGridLines = True
        
        headers_raps = [
            "Competencia", "Resultado de Aprendizaje (RAP)", "Instructor",
            "Aprobados", "Deficientes", "Por Evaluar", "% Avance Real", "Estado"
        ]
        ws_raps.append(headers_raps)
        for col_idx in range(1, len(headers_raps) + 1):
            c = ws_raps.cell(row=1, column=col_idx)
            c.fill = header_fill
            c.font = header_font_white
            c.alignment = Alignment(horizontal="center", vertical="center")

        for rap in raps_data:
            ws_raps.append([
                rap["competencia"],
                rap["rap"],
                rap.get("instructor", "Por asignar"),
                rap["aprobados"],
                rap["deficientes"],
                rap["pendientes"],
                f"{rap['porcentaje_aprobado']}%",
                rap["semaforo"]
            ])
            curr_row = ws_raps.max_row
            row_fill = fill_green if rap["categoria_cod"] == "optimo" else (fill_yellow if rap["categoria_cod"] == "en_avance" else fill_red)
            for col_idx in range(1, len(headers_raps) + 1):
                cell = ws_raps.cell(row=curr_row, column=col_idx)
                cell.fill = row_fill
                cell.border = thin_border
                if col_idx in [4, 5, 6, 7, 8]:
                    cell.alignment = Alignment(horizontal="center", vertical="center")

    # Autoajuste de anchos para todas las hojas
    for ws in wb.worksheets:
        for col in ws.columns:
            max_len = max(len(str(c.value or "")) for c in col)
            col_letter = get_column_letter(col[0].column)
            ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 45)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()
