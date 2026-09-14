"""
Gerenciador de Sincronizacao Google Drive (Modo Hibrido: Pasta Local / API Cloud)
Head of Data Engineering: Orion
Meridian Technologies
"""
from __future__ import annotations

import logging
import os
import shutil
from typing import Any, Optional

logger = logging.getLogger(__name__)


class GoogleDriveSyncManager:
    """
    Gerencia a distribuicao executiva das planilhas de decisao para o Google Drive.
    Opera com tolerancia a falhas (fail-safe):
      1. Sincronizacao local se pasta espelhada existir (Google Drive Desktop).
      2. Upload direto via Google Drive API v3 se credenciais de Service Account estiverem configuradas.
      3. Fallback inteligente para reports/gdrive_staging/ garantindo integridade e prontidao para upload posterior.
    """

    DEFAULT_STAGING_DIR = "reports/gdrive_staging"

    def __init__(
        self,
        local_drive_dir: Optional[str] = None,
        credentials_path: Optional[str] = None,
        folder_id: Optional[str] = None,
    ):
        self.local_drive_dir = local_drive_dir
        self.credentials_path = credentials_path
        self.folder_id = folder_id

    def sync_file(self, file_path: str) -> dict[str, Any]:
        """
        Executa a sincronizacao respeitando a ordem de precedencia dos canais.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"Arquivo nao encontrado para sync: {file_path}")

        file_name = os.path.basename(file_path)

        # Canal 1: Pasta Local Espelhada do Google Drive
        if self.local_drive_dir and os.path.isdir(self.local_drive_dir):
            target_path = os.path.join(self.local_drive_dir, file_name)
            shutil.copy2(file_path, target_path)
            logger.info("Arquivo sincronizado via Google Drive Desktop: %s", target_path)
            return {
                "status": "synced_local",
                "target_path": os.path.abspath(target_path),
                "channel": "local_drive_mirror",
            }

        # Canal 2: Google Drive API Cloud (se credenciais presentes)
        if self.credentials_path and os.path.exists(self.credentials_path):
            try:
                # Import condicional para nao onerar runtime caso nao use API
                from google.oauth2 import service_account
                from googleapiclient.discovery import build
                from googleapiclient.http import MediaFileUpload

                creds = service_account.Credentials.from_service_account_file(
                    self.credentials_path,
                    scopes=["https://www.googleapis.com/auth/drive.file"],
                )
                service = build("drive", "v3", credentials=creds)

                file_metadata = {"name": file_name}
                if self.folder_id:
                    file_metadata["parents"] = [self.folder_id]

                media = MediaFileUpload(file_path, resumable=True)
                uploaded = (
                    service.files()
                    .create(body=file_metadata, media_body=media, fields="id, webViewLink")
                    .execute()
                )

                logger.info("Arquivo publicado com sucesso na API Google Drive: ID %s", uploaded.get("id"))
                return {
                    "status": "synced_cloud_api",
                    "file_id": uploaded.get("id"),
                    "web_view_link": uploaded.get("webViewLink"),
                    "channel": "google_drive_api_v3",
                }
            except Exception as e:
                logger.error("Falha ao subir via API Google Drive: %s. Aplicando fallback seguro.", e)

        # Canal 3: Fallback Seguro (Staging Directory)
        os.makedirs(self.DEFAULT_STAGING_DIR, exist_ok=True)
        fallback_path = os.path.join(self.DEFAULT_STAGING_DIR, file_name)
        shutil.copy2(file_path, fallback_path)
        logger.info("Arquivo preservado em staging local para upload: %s", fallback_path)
        return {
            "status": "staged_locally",
            "fallback_path": os.path.abspath(fallback_path),
            "channel": "local_staging_fallback",
        }
