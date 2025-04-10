# src/infrastructure/aisearch/azure_aisearch_adapter.py
import logging
import os
from typing import List, Dict

try:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.core.exceptions import HttpResponseError
except ImportError:
    logging.critical(
        "Azure Search SDK not found. Please install 'azure-search-documents'."
    )
    # Clases Dummy
    class AzureKeyCredential:
        pass

    class SearchClient:
        pass

    class HttpResponseError(Exception):
        pass


# Excepción personalizada para errores de AI Search
class AISearchError(Exception):
    pass


# Constantes de Configuración
ENV_SEARCH_ENDPOINT = "SEARCH_ENDPOINT"
ENV_SEARCH_API_KEY = "SEARCH_API_KEY"
ENV_SEARCH_INDEX_NAME = "SEARCH_INDEX_NAME"


class AzureAISearchAdapter:
    """Adaptador para interactuar con Azure AI Search."""

    def __init__(self):
        self.endpoint = os.environ.get(ENV_SEARCH_ENDPOINT)
        self.api_key = os.environ.get(ENV_SEARCH_API_KEY)
        self.index_name = os.environ.get(ENV_SEARCH_INDEX_NAME)

        missing_vars = []
        if not self.endpoint:
            missing_vars.append(ENV_SEARCH_ENDPOINT)
        if not self.api_key:
            missing_vars.append(ENV_SEARCH_API_KEY)
        if not self.index_name:
            missing_vars.append(ENV_SEARCH_INDEX_NAME)
        if missing_vars:
            raise ValueError(
                f"Missing required environment variables for AzureAISearchAdapter: {', '.join(missing_vars)}"
            )

        try:
            self.credential = AzureKeyCredential(self.api_key)
            self.search_client = SearchClient(
                endpoint=self.endpoint,
                index_name=self.index_name,
                credential=self.credential,
            )
            logging.info(
                "AzureAISearchAdapter: SearchClient initialized for index '%s'.",
                self.index_name,
            )
        except Exception as e:
            logging.error(
                "AzureAISearchAdapter: Failed to create SearchClient: %s", e
            )
            raise ValueError(
                f"Failed to initialize Azure AI Search client: {e}"
            ) from e

    def upload_documents(self, documents: List[Dict]) -> bool:
        """
        Sube o fusiona una lista de documentos en el índice de Azure AI Search.

        Args:
            documents: Una lista de diccionarios, donde cada diccionario representa un documento.

        Returns:
            True si la operación fue exitosa (o parcialmente exitosa), False si falló por completo.
        """
        if not documents:
            logging.warning("No documents provided to upload to AI Search.")
            return True  # Considerar éxito si no hay nada que subir

        logging.info(
            f"Attempting to upload/merge {len(documents)} documents to index '{self.index_name}'..."
        )
        try:
            # Usar merge_or_upload_documents es más flexible que upload_documents
            # Actualizará documentos si el 'id' ya existe, o los insertará si son nuevos.
            results = self.search_client.merge_or_upload_documents(
                documents=documents
            )

            # Verificar si hubo errores individuales
            successful_uploads = 0
            errors = []
            for result in results:
                if result.succeeded:
                    successful_uploads += 1
                else:
                    errors.append(
                        f"Document ID {result.key}: {result.error_message} (Status: {result.status_code})"
                    )

            if errors:
                logging.error(
                    "Errors occurred while uploading documents to AI Search:"
                )
                for error in errors:
                    logging.error(f"- {error}")
                # Decidir si considerarlo un fallo total o parcial
                # Por ahora, lo consideramos parcialmente exitoso si al menos uno subió
                if successful_uploads > 0:
                    logging.warning(
                        f"Partial success: {successful_uploads}/{len(documents)} documents uploaded/merged."
                    )
                    return True
                else:
                    logging.error(
                        "Complete failure: No documents were successfully uploaded/merged."
                    )
                    raise AISearchError(
                        "Failed to upload/merge all documents to AI Search."
                    )  # Lanzar error si ninguno subió
            else:
                logging.info(
                    f"Successfully uploaded/merged all {len(documents)} documents to AI Search."
                )
                return True

        except HttpResponseError as e:
            logging.exception(
                f"HTTP error during AI Search upload/merge operation: Status={e.status_code}, Details={e.message}"
            )
            raise AISearchError(
                f"AI Search HTTP error {e.status_code}: {e.message}"
            ) from e
        except Exception as e:
            # Capturar otros errores inesperados (ej: conexión, serialización)
            logging.exception(
                f"Unexpected error during AI Search upload/merge operation: {e}"
            )
            raise AISearchError(
                f"Unexpected error uploading to AI Search: {e}"
            ) from e