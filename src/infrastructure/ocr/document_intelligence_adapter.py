import os 

import logging 

import time 

from typing import BinaryIO 

from functools import wraps  # Importa wraps 

 

from azure.core.credentials import AzureKeyCredential 

from azure.ai.documentintelligence import DocumentIntelligenceClient 

from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, AnalyzeResult 

from azure.core.exceptions import ServiceRequestError, HttpResponseError, ClientAuthenticationError 

 

from src.domain.exceptions import FileProcessingError, DocumentIntelligenceError, NoContentExtractedError 

 

ENV_DOCUMENT_INTELLIGENCE_ENDPOINT = "DOCUMENT_INTELLIGENCE_ENDPOINT" 

ENV_DOCUMENT_INTELLIGENCE_API_KEY = "DOCUMENT_INTELLIGENCE_API_KEY" 

 

def _retry_on_service_error(max_retries: int = 3, retry_delay: int = 30): 

    """Decorador para reintentar llamadas a la API en caso de errores transitorios.""" 

    def decorator(func): 

        @wraps(func)  #  Preserva la información de la función original (nombre, docstring, etc.) 

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

                            "ServiceRequestError (attempt %d of %d). Retrying in %d seconds: %s", 

                            retries + 1, max_retries, wait_time, e 

                        ) 

                        time.sleep(wait_time) 

                    else: 

                        logging.error("Max retries exceeded for ServiceRequestError: %s", e) 

                        raise DocumentIntelligenceError(f"Service request failed after multiple retries: {e}") from e 

 

                except HttpResponseError as e: 

                    retries += 1 

                    if e.status_code == 429: 

                        if retries < max_retries: 

                            wait_time = retry_delay * (2 ** (retries - 1)) 

                            logging.warning( 

                                "Too Many Requests (429) (attempt %d of %d). Retrying in %d seconds: %s", 

                                retries + 1, max_retries, wait_time, e 

                            ) 

                            time.sleep(wait_time) 

                        else: 

                            logging.error("Max retries exceeded for 429 Too Many Requests: %s", e) 

                            raise DocumentIntelligenceError(f"Too Many Requests (429) after multiple retries: {e}") from e 

                    elif retries < max_retries:  

                        wait_time = retry_delay * (2**(retries - 1)) 

                        logging.warning( 

                            "HttpResponseError (attempt %d of %d). Retrying in %d seconds: %s", 

                             retries + 1, max_retries, wait_time, e 

                        ) 

                        time.sleep(wait_time) 

                    else:   

                        logging.error("Max retries exceeded for HttpResponseError: %s", e) 

                        raise DocumentIntelligenceError(f"HTTP error after multiple retries: {e}") from e 

                except ClientAuthenticationError as e: 

                    logging.error("Authentication error: %s", e) 

                    raise DocumentIntelligenceError(f"Authentication error: {e}") from e 

                except Exception as e: 

                    

                   if isinstance(e,NoContentExtractedError): 

                        logging.exception("No content extracted from document: %s", e) 

                        raise 

                   else: 

                        logging.exception("Error during document analysis with Document Intelligence: %s", e) 

                        raise DocumentIntelligenceError(f"Error analyzing document: {e}") from e 

        return wrapper 

    return decorator 

 

 

class DocumentIntelligenceAdapter: 

    """Adaptador para interactuar con Azure AI Document Intelligence.""" 

 

    def __init__(self, 

                 endpoint_env_var: str = ENV_DOCUMENT_INTELLIGENCE_ENDPOINT, 

                 api_key_env_var: str = ENV_DOCUMENT_INTELLIGENCE_API_KEY): 

 

        self.endpoint = os.environ.get(endpoint_env_var) 

        self.api_key = os.environ.get(api_key_env_var) 

 

        if not self.endpoint or not self.api_key: 

            raise ValueError( 

                "Missing required environment variables for Document Intelligence." 

            ) 

        self.client = self._create_client() 

 

    def _create_client(self) -> DocumentIntelligenceClient: 

        """Crea y configura el cliente de Document Intelligence.""" 

        return DocumentIntelligenceClient( 

            endpoint=self.endpoint, 

            credential=AzureKeyCredential(self.api_key),
           

        ) 

 

    @_retry_on_service_error()  # Aplica el decorador 

    def analyze_cv(self, file_stream: BinaryIO) -> str: 

        """Extrae el texto de un CV usando Document Intelligence. 

 

        Args: 

            file_stream: Un flujo binario (BinaryIO) que contiene el CV (PDF). 

 

        Returns: 

            El texto extraído del CV. 

 

        Raises: 

            FileProcessingError: Si hay un error al procesar el archivo. 

            DocumentIntelligenceError: Si hay un error en la comunicación con Document Intelligence. 

            NoContentExtractedError: Si no se extrajo texto del CV. 

        """ 

        try: 

            # "prebuilt-read" es el modelo más adecuado para extraer texto de un CV 

            poller = self.client.begin_analyze_document( 

                "prebuilt-read", 

                AnalyzeDocumentRequest(bytes_source=file_stream.read())

            ) 

            result: AnalyzeResult = poller.result() 

 

            if result.content: 

                return result.content 

            else: 

                logging.warning("Document Intelligence returned no content.") 

                raise NoContentExtractedError("Document Intelligence did not extract any content from the document.") 

 

        except Exception as e: 

            if isinstance(e, NoContentExtractedError): 

                logging.exception("No content extracted from document: %s", e) 

                raise 

            else: 

                logging.exception("Error during document analysis with Document Intelligence: %s", e) 

                raise DocumentIntelligenceError(f"Error analyzing document: {e}") from e 