import os
import logging
import time
from typing import BinaryIO
from functools import wraps

from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, AnalyzeResult
from azure.core.exceptions import (
    ServiceRequestError,
    HttpResponseError,
    ClientAuthenticationError,
)
from src.domain.exceptions import (
    DocumentIntelligenceError,
    NoContentExtractedError,
)

ENV_DOCUMENT_INTELLIGENCE_ENDPOINT = "DOCUMENT_INTELLIGENCE_ENDPOINT"
ENV_DOCUMENT_INTELLIGENCE_API_KEY = "DOCUMENT_INTELLIGENCE_API_KEY"


def _retry_on_service_error(max_retries: int = 3, retry_delay: int = 30):
    """
    Decorador para reintentar llamadas a la API en caso de errores de servicio transitorios.

    Args:
        max_retries (int): Número máximo de reintentos.
        retry_delay (int): Retraso inicial en segundos entre reintentos.

    Returns:
        callable: Función decorada.
    """

    def decorator(func):
        @wraps(func)  # Preserva los metadatos de la función original (nombre, docstring, etc.)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except ServiceRequestError as e:  # Errores de conexión/red
                    retries += 1
                    if retries < max_retries:
                        wait_time = retry_delay * (2 ** (retries - 1))
                        logging.warning(
                            "ServiceRequestError (intento %d de %d). Reintentando en %d segundos: %s",
                            retries + 1,
                            max_retries,
                            wait_time,
                            e,
                        )
                        time.sleep(wait_time)
                    else:
                        logging.error(
                            "Se excedió el número máximo de reintentos para ServiceRequestError: %s", e
                        )
                        raise DocumentIntelligenceError(
                            f"La solicitud de servicio falló después de múltiples reintentos: {e}"
                        ) from e

                except HttpResponseError as e:
                    retries += 1
                    if e.status_code == 429:
                        if retries < max_retries:
                            wait_time = retry_delay * (2 ** (retries - 1))
                            logging.warning(
                                "Demasiadas solicitudes (429) (intento %d de %d). Reintentando en %d segundos: %s",
                                retries + 1,
                                max_retries,
                                wait_time,
                                e,
                            )
                            time.sleep(wait_time)
                        else:
                            logging.error(
                                "Se excedió el número máximo de reintentos para 429 Demasiadas solicitudes: %s", e
                            )
                            raise DocumentIntelligenceError(
                                f"Demasiadas solicitudes (429) después de múltiples reintentos: {e}"
                            ) from e
                    elif retries < max_retries:
                        wait_time = retry_delay * (2 ** (retries - 1))
                        logging.warning(
                            "HttpResponseError (intento %d de %d). Reintentando en %d segundos: %s",
                            retries + 1,
                            max_retries,
                            wait_time,
                            e,
                        )
                        time.sleep(wait_time)
                    else:
                        logging.error(
                            "Se excedió el número máximo de reintentos para HttpResponseError: %s", e
                        )
                        raise DocumentIntelligenceError(
                            f"Error HTTP después de múltiples reintentos: {e}"
                        ) from e
                except ClientAuthenticationError as e:
                    logging.error("Error de autenticación: %s", e)
                    raise DocumentIntelligenceError(f"Error de autenticación: {e}") from e
                except Exception as e:
                    if isinstance(e, NoContentExtractedError):
                        logging.exception("No se extrajo contenido del documento: %s", e)
                        raise
                    else:
                        logging.exception(
                            "Error durante el análisis de documentos con Document Intelligence: %s",
                            e,
                        )
                        raise DocumentIntelligenceError(
                            f"Error al analizar el documento: {e}"
                        ) from e

        return wrapper

    return decorator


class DocumentIntelligenceAdapter:
    """Adaptador para interactuar con Azure AI Document Intelligence."""

    def __init__(
        self,
        endpoint_env_var: str = ENV_DOCUMENT_INTELLIGENCE_ENDPOINT,
        api_key_env_var: str = ENV_DOCUMENT_INTELLIGENCE_API_KEY,
    ):
        """
        Inicializa el DocumentIntelligenceAdapter con el punto de conexión y la clave de API.

        Args:
            endpoint_env_var (str): El nombre de la variable de entorno para el punto de conexión de Document Intelligence.
            api_key_env_var (str): El nombre de la variable de entorno para la clave de API de Document Intelligence.

        Raises:
            ValueError: Si el punto de conexión o la clave de API no se encuentran en las variables de entorno.
        """
        self.endpoint = os.environ.get(endpoint_env_var)
        self.api_key = os.environ.get(api_key_env_var)

        if not self.endpoint or not self.api_key:
            raise ValueError(
                "Faltan variables de entorno requeridas para Document Intelligence."
            )
        self.client = self._create_client()

    def _create_client(self) -> DocumentIntelligenceClient:
        """Crea y configura el cliente de Document Intelligence.

        Returns:
            DocumentIntelligenceClient: Cliente de DocumentIntelligenceClient configurado.
        """
        return DocumentIntelligenceClient(
            endpoint=self.endpoint, credential=AzureKeyCredential(self.api_key)
        )

    @_retry_on_service_error()
    def analyze_cv(self, file_stream: BinaryIO) -> str:
        """
        Extrae texto de un CV utilizando Document Intelligence.

        Args:
            file_stream (BinaryIO): Un flujo binario que contiene el CV (PDF).

        Returns:
            str: El texto extraído del CV.

        Raises:
            FileProcessingError: Si hay un error al procesar el archivo.
            DocumentIntelligenceError: Si hay un error al comunicarse con Document Intelligence.
            NoContentExtractedError: Si no se extrajo ningún texto del CV.
        """
        try:
            # "prebuilt-read" es el modelo más adecuado para extraer texto de un CV
            poller = self.client.begin_analyze_document(
                "prebuilt-read",
                AnalyzeDocumentRequest(bytes_source=file_stream.read()),
            )
            result: AnalyzeResult = poller.result()

            if result.content:
                return result.content
            else:
                logging.warning("Document Intelligence no devolvió ningún contenido.")
                raise NoContentExtractedError(
                    "Document Intelligence no extrajo ningún contenido del documento."
                )

        except Exception as e:
            if isinstance(e, NoContentExtractedError):
                logging.exception("No se extrajo contenido del documento: %s", e)
                raise
            else:
                logging.exception(
                    "Error durante el análisis de documentos con Document Intelligence: %s",
                    e,
                )
                raise DocumentIntelligenceError(
                    f"Error al analizar el documento: {e}"
                ) from e