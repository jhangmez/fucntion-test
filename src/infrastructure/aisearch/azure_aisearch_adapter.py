# src/infrastructure/aisearch/azure_aisearch_adapter.py
import logging
import os
import time
from functools import wraps
from typing import List, Dict

try:
    from azure.core.credentials import AzureKeyCredential
    from azure.search.documents import SearchClient
    from azure.core.exceptions import HttpResponseError,ServiceRequestError
except ImportError:
    logging.critical("Azure Search SDK no encontrado. Instalar 'azure-search-documents'.")
    class AzureKeyCredential: pass

    class SearchClient: pass

    class HttpResponseError(Exception): pass

def _retry_aisearch_on_error(max_retries: int = 3, initial_delay: int = 10):
    """Decorador para reintentar operaciones de AI Search en errores específicos."""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            delay = initial_delay
            last_exception = None # Guardar la última excepción para relanzar
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except HttpResponseError as e:
                    last_exception = e # Guardar la excepción
                    # Reintentar en 429 (Too Many Requests) o 503 (Service Unavailable)
                    if e.status_code in [429, 503]:
                        retries += 1
                        if retries < max_retries:
                            # Intentar obtener 'Retry-After' del header (viene en segundos)
                            retry_after_seconds = int(e.response.headers.get("Retry-After", delay))
                            wait_time = max(retry_after_seconds, delay) # Usar el mayor entre el sugerido y nuestro delay
                            logging.warning(
                                f"Error de AI Search {e.status_code} (intento {retries}/{max_retries}). Intentando nuevamente en {wait_time} segundos. Detalle: {e.message}"
                            )
                            time.sleep(wait_time)
                            delay *= 2 # Aumentar delay para el siguiente intento si no hay Retry-After
                        else:
                            logging.error(f"Se excedió el número máximo de reintentos para el error de AI Search {e.status_code}: {e.message}")
                            raise AISearchError(f"La operación de AI Search falló después de múltiples reintentos ({e.status_code}): {e.message}") from e
                    else:
                        # No reintentar otros errores HTTP (400, 401, 404, etc.)
                        logging.error(f"HttpResponseError de AI Search no reintentable {e.status_code}: {e.message}")
                        raise AISearchError(f"Error HTTP de AI Search {e.status_code}: {e.message}") from e
                except ServiceRequestError as e: # Errores de conexión/red (el SDK puede ya reintentar, pero podemos añadir uno más)
                     last_exception = e
                     retries += 1
                     if retries < max_retries:
                         wait_time = delay
                         logging.warning(f"ServiceRequestError de AI Search (intento {retries}/{max_retries}). Reintentando en {wait_time} segundos: {e}")
                         time.sleep(wait_time)
                         delay *= 2
                     else:
                         logging.error("Se excedió el número máximo de reintentos para ServiceRequestError de AI Search: %s", e)
                         raise AISearchError(f"La conexión de AI Search falló después de múltiples reintentos: {e}") from e
                except Exception as e:
                     # Otros errores inesperados no se reintentan
                     logging.exception(f"Error inesperado durante el envoltorio de la operación de AI Search: {e}")
                     raise # Relanzar inmediatamente

            # Si el bucle termina sin éxito (no debería pasar si relanzamos antes)
            # Pero por si acaso, relanzar la última excepción conocida
            if last_exception:
                 raise AISearchError("Se excedió el número máximo de reintentos para la operación de AI Search.") from last_exception
            else:
                 # Caso improbable
                 raise AISearchError("Se excedió el número máximo de reintentos para la operación de AI Search (error final desconocido).")

        return wrapper
    return decorator

# Excepción personalizada para errores de AI Search
class AISearchError(Exception): pass


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
                f"Faltan variables de entorno requeridas para AzureAISearchAdapter: {', '.join(missing_vars)}"
            )

        try:
            self.credential = AzureKeyCredential(self.api_key)
            self.search_client = SearchClient(
                endpoint=self.endpoint,
                index_name=self.index_name,
                credential=self.credential,
            )
            logging.info(
                "AzureAISearchAdapter: SearchClient inicializado para el índice '%s'.",
                self.index_name,
            )
        except Exception as e:
            logging.error(
                "AzureAISearchAdapter: Falló la creación de SearchClient: %s", e
            )
            raise ValueError(
                f"Falló la inicialización del cliente de Azure AI Search: {e}"
            ) from e

    @_retry_aisearch_on_error()
    def upload_documents(self, documents: List[Dict]) -> bool:
        """
        Sube o fusiona una lista de documentos en el índice de Azure AI Search.
        (Decorado con lógica de reintentos para errores 429/503).
        """
        if not documents:
            logging.warning("No se proporcionaron documentos para subir a AI Search.")
            return True

        logging.info(
            f"Intentando subir/fusionar {len(documents)} documentos al índice '{self.index_name}'..."
        )
        try:
            # La llamada real a la API
            results = self.search_client.merge_or_upload_documents(documents=documents)
            successful_uploads = 0
            errors = []
            # IMPORTANTE: results puede ser None si la llamada falló antes de devolver IndexingResults
            # Aunque el decorador debería haber relanzado la excepción en ese caso.
            if results:
                for result in results:
                    if result.succeeded:
                        successful_uploads += 1
                    else:
                        errors.append(
                            f"Documento ID {result.key}: {result.error_message} (Status: {result.status_code})"
                        )
            else:
                 # Si results es None, asumimos que la operación falló a nivel general
                 # (aunque el decorador debería haber lanzado una excepción antes)
                 logging.error("La operación merge_or_upload_documents no devolvió resultados (posible fallo general).")
                 # Podríamos lanzar AISearchError aquí, pero el decorador ya debería haberlo hecho.
                 # Considerar esto un fallo si ocurre.
                 return False

            if errors:
                logging.error("Ocurrieron errores al subir documentos a AI Search:")
                for error in errors:
                    logging.error(f"- {error}")
                if successful_uploads > 0:
                    logging.warning(f"Éxito parcial: {successful_uploads}/{len(documents)} documentos subidos/fusionados.")
                    return True
                else:
                    logging.error("Fallo completo: Ningún documento fue subido/fusionado exitosamente.")
                    raise AISearchError("Falló la subida/fusión de todos los documentos a AI Search (ver logs para detalles).")
            else:
                logging.info(f"Se subieron/fusionaron exitosamente todos los {len(documents)} documentos a AI Search.")
                return True
        except Exception as e:
            if isinstance(e, AISearchError):
                 raise # Relanzar si ya es nuestro tipo de error
            else:
                 logging.exception(f"Error inesperado durante la operación de subida/fusión a AI Search: {e}")
                 raise AISearchError(f"Error inesperado subiendo a AI Search: {e}") from e