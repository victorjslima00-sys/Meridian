"""
Testes unitarios para o Exportador de Planilhas Executivas — Orion Data Engineering
"""
import os
import pandas as pd
import pytest

openpyxl = pytest.importorskip("openpyxl")
from trading_bot.data.exporters.excel_exporter import ExecutiveWorkbookExporter


def test_export_executive_workbook(tmp_path):
    exporter = ExecutiveWorkbookExporter()

    resumo_data = {
        "Metrica": ["Regime Macro", "Selic Atual", "CDI Atual", "Universo Monitorado"],
        "Valor": ["Expansionista", "10.50% a.a.", "10.40% a.a.", "PETR4, VALE3, BBAS3"],
    }
    macro_df = pd.DataFrame({
        "data": ["01/09/2026", "02/09/2026"],
        "taxa_diaria": [0.041, 0.041],
        "taxa_anualizada": [10.50, 10.50],
    })
    proventos_df = pd.DataFrame({
        "empresa": ["PETROBRAS", "VALE"],
        "tipo": ["DIVIDENDO", "JCP"],
        "valor": [1.25, 0.85],
        "data_corte": ["12/12/2025", "20/10/2025"],
    })

    target_file = str(tmp_path / "Meridian_Decisao_Executiva.xlsx")
    manifest = exporter.export(
        target_path=target_file,
        resumo_df=pd.DataFrame(resumo_data),
        macro_df=macro_df,
        proventos_df=proventos_df,
    )

    assert os.path.exists(target_file)
    assert manifest["sha256"] is not None
    assert len(manifest["sha256"]) == 64

    # Validar estrutura interna do Excel (OpenPyXL)
    wb = openpyxl.load_workbook(target_file)
    sheet_names = wb.sheetnames
    assert "Resumo_Executivo" in sheet_names
    assert "Macro_Bacen" in sheet_names
    assert "Proventos_CVM" in sheet_names
    assert "Auditoria_Integridade" in sheet_names

    # Validar conteudo da aba de auditoria
    ws_audit = wb["Auditoria_Integridade"]
    assert ws_audit.cell(row=2, column=1).value == "Gerador"
    assert ws_audit.cell(row=2, column=2).value == "Orion Data Engineering"
