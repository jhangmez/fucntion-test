import logging
import os
import json
from typing import Optional

import azure.functions as func
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

try:
    from src.infrastructure.ocr.document_intelligence_adapter import (
        DocumentIntelligenceAdapter,
        DocumentIntelligenceError,
        NoContentExtractedError,
    )
    from src.infrastructure.openai.azure_openai_adapter import (
        AzureOpenAIAdapter,
        OpenAIError,
    )
    from src.infrastructure.api_rest.rest_api_adapter import RestApiAdapter
    from src.infrastructure.embedding.embedding_generator import (
        EmbeddingGenerator,
        APIError as EmbeddingAPIError,
    )
    from src.infrastructure.aisearch.azure_aisearch_adapter import (
        AzureAISearchAdapter,
        AISearchError,
    )
    from src.domain.exceptions import APIError, KeyVaultError, SecretNotFoundError
    from src.infrastructure.key_vault.key_vault_client import KeyVaultClient
    from src.shared.prompt_system import prompt_system
    from src.shared.validate_process_json import (
        extract_and_validate_cv_data_from_json,
    )
    from src.shared.promedio_scores import calculate_average_score_from_dict
    from src.domain.exceptions import APIError, KeyVaultError, SecretNotFoundError
    from src.infrastructure.key_vault.key_vault_client import KeyVaultClient
    from src.shared.extract_values import get_id_candidate, get_id_rank
    from src.shared.sanitize_string import sanitize_for_id, format_text_for_embedding
    from src.shared.extract_values import get_id_candidate, get_id_rank
except ImportError as e:
    logging.critical(
        f"CRÍTICO: Falló la importación de módulos de la aplicación durante el inicio: {e}. Verifique los archivos __init__.py y las dependencias."
    )

    class DocumentIntelligenceAdapter:
        pass

    class DocumentIntelligenceError(Exception):
        pass

    class NoContentExtractedError(DocumentIntelligenceError):
        pass

    class AzureOpenAIAdapter:
        pass

    class OpenAIError(Exception):
        pass

    class RestApiAdapter:
        pass

    class EmbeddingGenerator:
        pass

    class EmbeddingAPIError(Exception):
        pass

    class AzureAISearchAdapter:
        pass

    class AISearchError(Exception):
        pass

    class APIError(Exception):
        pass

    class AuthenticationError(APIError):
        pass

    class KeyVaultError(Exception):
        pass

    class SecretNotFoundError(KeyVaultError):
        pass

    class JSONValidationError(Exception):
        pass

    class KeyVaultClient:
        pass

    def prompt_system(profile, criterios, cv_candidato, current_date=None):
        return ""

    def extract_and_validate_cv_data_from_json(json_string: str):
        return None, None, None

    def sanitize_for_id(t):
        return "sanitized-id"

    def format_text_for_embedding(
        candidate_name, profile_name, cv_analysis, average_score
    ):
        return "formatted text"

    def calculate_average_score_from_dict(cv_score: dict):
        return "0.0"

    def get_id_candidate(file_path: str) -> str:
        return ""

    def get_id_rank(file_path: str) -> str:
        return ""


CONNECTION_STRING_ENV_VAR = "AzureWebJobsStorage"
CANDIDATES_CONTAINER = "candidates"
RESULTS_POST_OPENAI_CONTAINER = "resultados-post-openai"

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

SECRET_NAMES = {
    "openai_api_key": "OpenaiApiKey",
    "openai_endpoint": "OpenaiEndpoint",
    "openai_api_version": "OpenaiApiVersion",
    "openai_model": "OpenaiModel",
    "docintel_api_key": "DocIntelApiKey",
    "docintel_endpoint": "DocIntelEndpoint",
    "rest_api_username": "RestApiUsername",
    "rest_api_password": "RestApiPassword",
    "rest_api_role": "RestApiRole",
    "rest_api_user_app": "RestApiUserApplication",
    "rest_api_base_url": "RestApiBaseUrl",
}


def _initialize_adapters_with_keyvault() -> tuple:
    """Inicializa los adaptadores obteniendo secretos de Key Vault."""
    logging.info("Initializing adapters using Key Vault...")
    kv_client = KeyVaultClient()
    secrets = {}
    try:
        for key, secret_name in SECRET_NAMES.items():
            secrets[key] = kv_client.get_secret(secret_name)
        logging.info("All required secrets retrieved from Key Vault.")

        # Instanciar adaptadores pasando los secretos obtenidos
        doc_intel_adapter = DocumentIntelligenceAdapter(
            api_key=secrets["docintel_api_key"], endpoint=secrets["docintel_endpoint"]
        )
        openai_adapter = AzureOpenAIAdapter(
            api_key=secrets["openai_api_key"],
            endpoint=secrets["openai_endpoint"],
            api_version=secrets["openai_api_version"],
            model=secrets["openai_model"],
        )
        rest_api_adapter = RestApiAdapter(
            username=secrets["rest_api_username"],
            password=secrets["rest_api_password"],
            role=secrets["rest_api_role"],
            user_app=secrets["rest_api_user_app"],
            base_url=secrets[
                "rest_api_base_url"
            ],  # Base URL también puede venir de KV si es sensible
        )
        logging.info("Adapters initialized successfully.")
        return doc_intel_adapter, openai_adapter, rest_api_adapter

    except (SecretNotFoundError, KeyVaultError, ValueError) as e:
        # ValueError puede ocurrir si falta KEY_VAULT_URI
        logging.error(
            "CRITICAL: Failed to initialize adapters due to Key Vault error: %s", e
        )
        raise  # Relanza para detener la ejecución de la función


@app.route(
    route="upload-cv",
    methods=[func.HttpMethod.POST],
    auth_level=func.AuthLevel.FUNCTION,
)
def upload_cv_http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    """
    Azure Function triggered by an HTTP POST request to upload a CV file (v2 model).
    Saves the file to the 'candidates' blob container.
    """
    logging.info(
        "Función de disparador HTTP de Python procesó una solicitud para subir un CV."
    )

    file_content = None
    filename = None
    content_type = "application/octet-stream"

    try:
        file_from_form = req.files.get("file")

        if file_from_form:
            filename = os.path.basename(file_from_form.filename)  # Sanitizar
            file_content = file_from_form.read()
            content_type = (
                file_from_form.mimetype or content_type
            )  # Obtener mimetype si está disponible
            logging.info(
                f"Recibido archivo '{filename}' a través de form-data ({len(file_content)} bytes), tipo: {content_type}"
            )
        else:
            file_content = req.get_body()
            if not file_content:
                return func.HttpResponse(
                    "Por favor, pase un archivo en el cuerpo de la solicitud o como form-data con la clave 'file'.",
                    status_code=400,
                )
            # Intentar obtener nombre de header o usar default
            filename = os.path.basename(
                req.headers.get("X-Filename", "uploaded_cv.pdf")
            )  # Sanitizar
            content_type = req.headers.get("Content-Type", content_type)
            logging.info(
                f"Recibido archivo '{filename}' a través del cuerpo de la solicitud ({len(file_content)} bytes), tipo: {content_type}"
            )

        if not filename:
            filename = "default_uploaded_cv.pdf"
            logging.warning("No se pudo determinar el nombre del archivo, usando el nombre por defecto.")

        try:
            connection_string = os.environ[CONNECTION_STRING_ENV_VAR]
            blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )
            blob_client = blob_service_client.get_blob_client(
                container=CANDIDATES_CONTAINER, blob=filename
            )

            blob_content_settings = ContentSettings(content_type=content_type)

            logging.info(
                f"Subiendo '{filename}' al contenedor '{CANDIDATES_CONTAINER}' con content_settings: {blob_content_settings}"
            )

            blob_client.upload_blob(
                file_content,
                overwrite=True,
                content_settings=blob_content_settings,
            )

            logging.info(
                f"Subido exitosamente '{filename}'. El disparador de blob lo procesará."
            )

            return func.HttpResponse(
                f"Archivo '{filename}' subido exitosamente a '{CANDIDATES_CONTAINER}'. Será procesado en breve.",
                status_code=200,
            )

        except KeyError:
            logging.exception(
                f"Variable de entorno '{CONNECTION_STRING_ENV_VAR}' no encontrada."
            )
            return func.HttpResponse(
                "Error de configuración del servidor (falta la conexión de almacenamiento).",
                status_code=500,
            )
        except Exception as e:
            logging.exception(f"Error al subir el archivo '{filename}' al almacenamiento de blobs: {e}")
            return func.HttpResponse(
                f"Error al guardar el archivo en el almacenamiento: {e}",
                status_code=500,
            )

    except Exception as e:
        logging.exception("Error inesperado al procesar la solicitud de carga HTTP.")
        return func.HttpResponse(
            "Ocurrió un error interno del servidor durante el procesamiento de la carga.",
            status_code=500,
        )


def _save_openai_result_on_failure(
    blob_service_client: BlobServiceClient,
    rank_id: str,
    candidate_id: str,
    openai_result_str: str,
    failed_step: str,
    error_details: str,
):
    """Guarda el resultado de OpenAI en un contenedor separado en caso de fallo."""
    try:
        container_name = RESULTS_POST_OPENAI_CONTAINER
        # Crear contenedor si no existe
        try:
            container_client = blob_service_client.create_container(container_name)
            logging.info(f"Contenedor '{container_name}' creado.")
        except HttpResponseError as e:
            if e.status_code == 409:  # 409 Conflict significa que ya existe
                logging.info(f"Contenedor '{container_name}' ya existe.")
                container_client = blob_service_client.get_container_client(
                    container_name
                )
            else:
                raise  # Relanzar otros errores HTTP

        # Nombre del archivo para guardar el resultado
        result_filename = f"{rank_id}_{candidate_id}_openai_result.json"
        blob_client = container_client.get_blob_client(result_filename)

        # Metadata para indicar el error
        metadata = {
            "original_filename": f"{rank_id}_{candidate_id}.pdf",  # Asume extensión original
            "failed_step": failed_step,
            "error_details": error_details[:8000],  # Limitar longitud de metadata si es necesario (límite de Azure es 8KB total)
        }

        # Definir content settings
        content_settings = ContentSettings(
            content_type="application/json", metadata=metadata
        )

        logging.warning(
            f"Guardando resultado de OpenAI para '{result_filename}' en '{container_name}' debido a fallo en paso '{failed_step}'. Error: {error_details}"
        )

        # Subir el resultado JSON crudo con metadata
        blob_client.upload_blob(
            openai_result_str,
            overwrite=True,  # Sobreescribir si ya existe (para reintentos fallidos)
            content_settings=content_settings,
        )
        logging.info(
            f"Resultado de OpenAI guardado exitosamente en '{container_name}/{result_filename}'"
        )

    except Exception as e:
        # No detener el flujo principal si falla el guardado del error, solo loguear
        logging.exception(
            f"ERROR al intentar guardar el resultado fallido de OpenAI en '{RESULTS_POST_OPENAI_CONTAINER}': {e}"
        )


@app.blob_trigger(
    arg_name="inputblob",
    path="candidates/{name}",
    connection=CONNECTION_STRING_ENV_VAR,
)
def process_candidate_cv(inputblob: func.InputStream):
    """
    Función de Azure activada por un blob en el contenedor "Candidatos".
    Extrae texto (DI), analiza (OpenAI), valida los datos y guarda el resultado en "Resultado".
    Mueve el blob original en caso de error y lo elimina en caso de éxito.
    """
    if not inputblob or not inputblob.name:
        logging.error("Disparador de blob invocado sin blob o nombre válido.")
        return
    blob_full_path = inputblob.name
    file_name = os.path.basename(blob_full_path)
    logging.info(f"--- Comenzó el procesamiento del blob: {blob_full_path} ---")
    logging.info(
        f"Nombre del archivo: {file_name}, Tamaño: {inputblob.length} Bytes"
    )

    # Ignorar blobs en carpetas de error
    if "/error/" in blob_full_path.lower():
        logging.warning(
            f"Ignorando blob encontrado en subcarpeta de error: {blob_full_path}"
        )
        return

    rank_id: str = ""
    candidate_id: str = ""
    blob_service_client: Optional[BlobServiceClient] = None
    doc_intel_adapter: Optional[DocumentIntelligenceAdapter] = None
    openai_adapter: Optional[AzureOpenAIAdapter] = None
    rest_api_adapter: Optional[RestApiAdapter] = None
    embedding_generator: Optional[EmbeddingGenerator] = None
    ai_search_adapter: Optional[AzureAISearchAdapter] = None
    analysis_result_str: str = ""
    processed_successfully = False

    final_status_code = (
        "" if processed_successfully else "Error desconocido"
    )  # Flag para controlar el estado final

    try:
        # --- 0. Inicialización ---
        logging.info(f"[{file_name}] Inicializando componentes desde variables de entorno...")
        # Obtener IDs
        rank_id = get_id_rank(file_name)
        candidate_id = get_id_candidate(file_name)
        if not rank_id or not candidate_id:
            raise ValueError(
                f"No se pudo extraer rank_id o candidate_id del archivo: {file_name}"
            )
        logging.info(
            f"[{file_name}] IDs extraídos - rank_id: {rank_id}, candidate_id: {candidate_id}"
        )

        # Obtener cadena de conexión
        storage_connection_string = os.environ.get(
            CONNECTION_STRING_ENV_VAR
        )  # Usar .get() para evitar KeyError inmediato
        if not storage_connection_string:
            raise ValueError(
                f"Variable de entorno requerida '{CONNECTION_STRING_ENV_VAR}' no encontrada."
            )
        blob_service_client = BlobServiceClient.from_connection_string(
            storage_connection_string
        )

        # Envolver en try/except por si fallan por falta de env vars
        try:
            doc_intel_adapter = DocumentIntelligenceAdapter()
            openai_adapter = AzureOpenAIAdapter()
            rest_api_adapter = RestApiAdapter()
            logging.info(f"[{file_name}] Adaptadores inicializados correctamente.")
        except ValueError as init_error:  # Capturar ValueError si falta alguna variable en los adaptadores
            logging.error(
                f"[{file_name}] CRÍTICO: Falló la inicialización de un adaptador: {init_error}"
            )
            raise  # Relanzar para detener la ejecución

        # --- 1. Extraer texto con Document Intelligence
        logging.info(f"[{file_name}] Llamando a Document Intelligence...")
        extracted_text = doc_intel_adapter.analyze_cv(inputblob)
        logging.info(
            f"[{file_name}] Document Intelligence finalizó. Se extrajeron {len(extracted_text)} caracteres."
        )

        # --- 2. Extraer información de la API de junior :D
        logging.info(f"[{file_name}] Obteniendo datos de /Resumen/{rank_id}...")
        resumen_data = rest_api_adapter.get_resumen(id=rank_id)
        profile_description = resumen_data.get("profileDescription")
        variables_content = resumen_data.get("variablesContent")
        if profile_description is None or variables_content is None:
            raise APIError(
                f"Datos incompletos de /Resumen/{rank_id}: falta profileDescription o variablesContent"
            )
        logging.info(f"[{file_name}] Datos de /Resumen obtenidos.")

        # --- 3. Preparar y llamar a Azure OpenAI
        logging.info(f"[{file_name}] Generando prompt y llamando a Azure OpenAI...")
        system_prompt = prompt_system(
            profile=profile_description,
            criterios=variables_content,
            cv_candidato=extracted_text,
        )
        logging.info(f"[{file_name}] Llamando a Azure OpenAI...")
        analysis_result = openai_adapter.get_completion(
            system_message=system_prompt, user_message=""
        )
        logging.info(f"[{file_name}] Azure OpenAI finalizó.")

        try:
            # 4. Validar JSON de OpenAI
            logging.info(f"[{file_name}] Validando resultado de OpenAI...")
            cv_score, cv_analysis, candidate_name = (
                extract_and_validate_cv_data_from_json(analysis_result)
            )
            logging.info(
                f"[{file_name}] Resultado de la validación: cv_score={cv_score is not None}, cv_analysis={cv_analysis is not None}, candidate_name={candidate_name is not None}"
            )

            # 5. Calcular Promedio
            logging.info(f"[{file_name}] Calculando promedio de scores...")
            promedio_scores = calculate_average_score_from_dict(cv_score)
            logging.info(
                f"[{file_name}] Resultado del promedio: promedio_scores={promedio_scores is not None}"
            )

            ## A partir de aca son cambios que se harán par aimplementar Azure AI Search

            # 6. Formatear Texto para Embedding
            logging.info(f"[{file_name}] Formateando texto para embedding...")
            text_to_embed = format_text_for_embedding(
                candidate_name=candidate_name,
                profile_name=profile_description,
                cv_analysis=cv_analysis,
                average_score=promedio_scores,
            )

            ## Fin de cambios de  Azure AI Search

            # 6. Enviar a API REST
            logging.info(f"[{file_name}] Enviando scores a API (/Resumen/AddScores)...")
            rest_api_adapter.add_scores(candidate_id=candidate_id, scores=cv_score)
            logging.info(f"[{file_name}] Scores enviados.")

            logging.info(f"[{file_name}] Guardando resumen en API (/Resumen/Save)...")
            # Llamar a SaveResumen
            logging.info(
                "Guardando resumen en la API para candidate_id: %s", candidate_id
            )
            rest_api_adapter.save_resumen(
                candidate_id=candidate_id,
                transcription=extracted_text,
                score=promedio_scores,
                analysis=cv_analysis,
                candidate_name=candidate_name,
            )
            logging.info("Resumen guardado exitosamente.")

            # 7. Marcar como procesado en API (éxito)
            logging.info(
                f"[{file_name}] Marcando candidato como procesado exitosamente en API (/Resumen PUT)..."
            )
            rest_api_adapter.update_candidate(
                candidate_id=candidate_id, error_message=None
            )
            logging.info(f"[{file_name}] Candidato marcado como procesado.")

            processed_successfully = True  # Éxito

        except (
            JSONValidationError,
            TypeError,
            APIError,
            AuthenticationError,
            Exception,
        ) as post_openai_error:
            failed_step = "UnknownPostOpenAI"
            if isinstance(post_openai_error, (JSONValidationError, TypeError)):
                failed_step = "ValidationOrCalculation"
            elif isinstance(post_openai_error, (APIError, AuthenticationError)):
                failed_step = "APISaveOrUpdate"
            error_details_str = f"{type(post_openai_error).__name__}: {post_openai_error}"
            logging.error(
                f"[{file_name}] Error en paso '{failed_step}': {error_details_str}",
                exc_info=True,
            )
            if blob_service_client and analysis_result_str:
                _save_openai_result_on_failure(
                    blob_service_client,
                    rank_id,
                    candidate_id,
                    analysis_result_str,
                    failed_step,
                    error_details_str,
                )
            if rest_api_adapter:
                try:
                    logging.info(f"[{file_name}] Reportando error post-OpenAI a API...")
                    rest_api_adapter.update_candidate(
                        candidate_id=candidate_id,
                        error_message=error_details_str[:1000],
                    )
                    logging.info(f"[{file_name}] Error post-OpenAI reportado a API.")
                except Exception as report_err:
                    logging.error(
                        f"[{file_name}] FALLO al reportar error post-OpenAI a API: {report_err}"
                    )

    except (
        ValueError,
        DocumentIntelligenceError,
        NoContentExtractedError,
        OpenAIError,
        APIError,
        AuthenticationError,
    ) as early_error:
        error_msg = (
            f"[{file_name}] Error temprano en el proceso: {type(early_error).__name__} - {early_error}"
        )
        logging.error(error_msg, exc_info=True)
        if rest_api_adapter and candidate_id:
            try:
                logging.info(f"[{file_name}] Reportando error temprano a API...")
                rest_api_adapter.update_candidate(
                    candidate_id=candidate_id, error_message=error_msg[:1000]
                )
                logging.info(f"[{file_name}] Error temprano reportado a API.")
            except Exception as report_err:
                logging.error(
                    f"[{file_name}] FALLO al reportar error temprano a API: {report_err}"
                )
        elif not candidate_id:
            logging.warning(
                f"[{file_name}] No se pudo reportar error temprano a API: candidate_id no extraído."
            )
        elif "rest_api_adapter" not in locals() or rest_api_adapter is None:
            logging.warning(
                f"[{file_name}] No se pudo reportar error temprano a API: adaptador REST no inicializado."
            )

    except Exception as unexpected_error:
        error_msg = f"[{file_name}] Error inesperado en el proceso: {type(unexpected_error).__name__} - {unexpected_error}"
        logging.exception(error_msg)
        if rest_api_adapter and candidate_id:
            try:
                logging.info(f"[{file_name}] Reportando error inesperado a API...")
                rest_api_adapter.update_candidate(
                    candidate_id=candidate_id, error_message=error_msg[:1000]
                )
                logging.info(f"[{file_name}] Error inesperado reportado a API.")
            except Exception as report_err:
                logging.error(
                    f"[{file_name}] FALLO al reportar error inesperado a API: {report_err}"
                )

    finally:
        # --- Borrado Final del Blob Original ---
        if blob_service_client:
            if processed_successfully:
                logging.info(
                    f"[{file_name}] Proceso exitoso. Intentando borrar blob original de '{CANDIDATES_CONTAINER}'."
                )
                try:
                    # Reobtener cliente por si acaso
                    container_client_del = blob_service_client.get_container_client(
                        CANDIDATES_CONTAINER
                    )
                    blob_client_del = container_client_del.get_blob_client(file_name)
                    blob_client_del.delete_blob(delete_snapshots="include")
                    logging.info(f"[{file_name}] Blob original borrado exitosamente.")
                except ResourceNotFoundError:
                    logging.warning(
                        f"[{file_name}] No se encontró el blob original '{CANDIDATES_CONTAINER}/{file_name}' para borrar."
                    )
                except Exception as delete_err:
                    logging.error(
                        f"[{file_name}] FALLO al borrar el blob original '{CANDIDATES_CONTAINER}/{file_name}' después de éxito: {delete_err}"
                    )
            else:
                if analysis_result_str:  # Fallo DESPUÉS de OpenAI
                    logging.warning(
                        f"[{file_name}] Proceso falló después de OpenAI. Intentando borrar blob original de '{CANDIDATES_CONTAINER}' (resultado intermedio guardado)."
                    )
                    try:
                        container_client_del = blob_service_client.get_container_client(
                            CANDIDATES_CONTAINER
                        )
                        blob_client_del = container_client_del.get_blob_client(
                            file_name
                        )
                        blob_client_del.delete_blob(delete_snapshots="include")
                        logging.info(
                            f"[{file_name}] Blob original borrado después de fallo post-OpenAI."
                        )
                    except ResourceNotFoundError:
                        logging.warning(
                            f"[{file_name}] No se encontró el blob original '{CANDIDATES_CONTAINER}/{file_name}' para borrar (fallo post-OpenAI)."
                        )
                    except Exception as delete_err:
                        logging.error(
                            f"[{file_name}] FALLO al borrar el blob original '{CANDIDATES_CONTAINER}/{file_name}' después de fallo post-OpenAI: {delete_err}"
                        )
                else:  # Fallo ANTES o DURANTE OpenAI
                    logging.warning(
                        f"[{file_name}] Proceso falló antes o durante OpenAI. El blob original '{CANDIDATES_CONTAINER}/{file_name}' NO se borrará."
                    )
        else:
            logging.error(
                f"[{file_name}] Blob service client no fue inicializado, no se puede intentar borrar el blob."
            )

        logging.info(f"--- Finalizó el procesamiento del blob: {blob_full_path} ---")