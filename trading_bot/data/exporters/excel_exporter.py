"""
Exportador Executivo de Planilhas Formatadas (.xlsx) para Tomada de Decisao
Head of Data Engineering: Orion
Meridian Technologies
"""
from __future__ import annotations

import datetime
import hashlib
import os
from typing import Any, Optional

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
import pandas as pd


class ExecutiveWorkbookExporter:
    """
    Exporta relatorios analiticos em Excel de alto padrao institucional.
    Cada arquivo gerado contem 4 abas, cabecalhos estilizados e aba de auditoria SHA-256.
    """

    def __init__(self):
        # Paleta institucional Meridian
        self.header_fill = PatternFill(start_color="1A365D", end_color="1A365D", fill_type="solid")  # Azul Marinho
        self.header_font = Font(name="Segoe UI", size=11, bold=True, color="FFFFFF")
        self.bold_font = Font(name="Segoe UI", size=10, bold=True)
        self.regular_font = Font(name="Segoe UI", size=10)
        self.center_align = Alignment(horizontal="center", vertical="center")
        self.thin_border = Border(
            left=Side(style="thin", color="D1D5DB"),
            right=Side(style="thin", color="D1D5DB"),
            top=Side(style="thin", color="D1D5DB"),
            bottom=Side(style="thin", color="D1D5DB"),
        )

    def _style_header(self, ws, max_col: int):
        for col in range(1, max_col + 1):
            cell = ws.cell(row=1, column=col)
            cell.fill = self.header_fill
            cell.font = self.header_font
            cell.alignment = self.center_align

    def _auto_column_width(self, ws):
        for col in ws.columns:
            max_len = 0
            col_letter = col[0].column_letter
            for cell in col:
                val = str(cell.value or "")
                if len(val) > max_len:
                    max_len = len(val)
            ws.column_dimensions[col_letter].width = max(max_len + 4, 12)

    def export(
        self,
        target_path: str,
        resumo_df: pd.DataFrame,
        macro_df: pd.DataFrame,
        proventos_df: pd.DataFrame,
    ) -> dict[str, Any]:
        """
        Gera o arquivo Excel completo e retorna o manifesto com hash SHA-256.
        """
        os.makedirs(os.path.dirname(os.path.abspath(target_path)), exist_ok=True)
        wb = openpyxl.Workbook()

        # Aba 1: Resumo Executivo
        ws_resumo = wb.active
        ws_resumo.title = "Resumo_Executivo"
        if not resumo_df.empty:
            ws_resumo.append(list(resumo_df.columns))
            for row in resumo_df.itertuples(index=False):
                ws_resumo.append(list(row))
            self._style_header(ws_resumo, len(resumo_df.columns))
            self._auto_column_width(ws_resumo)

        # Aba 2: Macro Bacen
        ws_macro = wb.create_sheet(title="Macro_Bacen")
        if not macro_df.empty:
            ws_macro.append(list(macro_df.columns))
            for row in macro_df.itertuples(index=False):
                ws_macro.append(list(row))
            self._style_header(ws_macro, len(macro_df.columns))
            self._auto_column_width(ws_macro)

        # Aba 3: Proventos CVM
        ws_prov = wb.create_sheet(title="Proventos_CVM")
        if not proventos_df.empty:
            ws_prov.append(list(proventos_df.columns))
            for row in proventos_df.itertuples(index=False):
                ws_prov.append(list(row))
            self._style_header(ws_prov, len(proventos_df.columns))
            self._auto_column_width(ws_prov)

        # Aba 4: Auditoria e Integridade
        ws_audit = wb.create_sheet(title="Auditoria_Integridade")
        audit_headers = ["Propriedade", "Valor_Auditado"]
        ws_audit.append(audit_headers)
        self._style_header(ws_audit, 2)

        now_utc = datetime.datetime.now(datetime.timezone.utc).isoformat()
        audit_rows = [
            ("Gerador", "Orion Data Engineering"),
            ("Organizacao", "Meridian Technologies"),
            ("Data_Hora_UTC", now_utc),
            ("Destinatario_Decisao", "CEO Astra / Conselho Executivo"),
            ("Linhas_Macro", str(len(macro_df))),
            ("Linhas_Proventos", str(len(proventos_df))),
        ]
        for prop, val in audit_rows:
            ws_audit.append([prop, val])
        self._auto_column_width(ws_audit)

        # Salvar
        wb.save(target_path)

        # Calcular SHA-256 do arquivo gerado
        hasher = hashlib.sha256()
        with open(target_path, "rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        file_hash = hasher.hexdigest()

        manifest = {
            "target_path": os.path.abspath(target_path),
            "file_name": os.path.basename(target_path),
            "size_bytes": os.path.getsize(target_path),
            "sha256": file_hash,
            "created_at_utc": now_utc,
            "sheets": wb.sheetnames,
        }
        return manifest
