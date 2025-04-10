# function_app.py
import logging
import os
import json
import time  # Asegúrate que time esté importado si no lo estaba
from typing import Optional

import azure.functions as func
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

# --- Importaciones Existentes y Nuevas ---
try:
    # Adaptadores existentes
    from src.infrastructure.ocr.document_intelligence_adapter import (
        DocumentIntelligenceAdapter,
        DocumentIntelligenceError,
        NoContentExtractedError,
    )
    from src.infrastructure.openai.azure_openai_adapter import (
        AzureOpenAIAdapter,
        OpenAIError,
    )
    from src.infrastructure.api_rest.rest_api_adapter import (
        RestApiAdapter,
    )  # Asumiendo que aún la necesitas

    # Componentes de AI Search (NUEVO)
    from src.infrastructure.embedding.embedding_generator import (
        EmbeddingGenerator,
        APIError as EmbeddingAPIError,
    )
    from src.infrastructure.aisearch.azure_aisearch_adapter import (
        AzureAISearchAdapter,
        AISearchError,
    )

    # Utilidades y Validación
    from src.shared.prompt_system import prompt_system
    from src.shared.validate_process_json import (
        extract_and_validate_cv_data_from_json,
        JSONValidationError,
    )  # Importar JSONValidationError si existe
    from src.shared.promedio_scores import (
        calculate_average_score_from_dict,
    )  # Asumiendo que esta existe y devuelve float o None
    from src.shared.sanitize_string import (
        sanitize_for_id,
        format_text_for_embedding,
    )  # Cambiado de utils.py a sanitize_string.py
    from src.shared.extract_values import get_id_candidate, get_id_rank

    # Excepciones y Key Vault (Mantener si se usan, aunque KV no esté activo aún)
    from src.domain.exceptions import APIError, KeyVaultError, SecretNotFoundError  # Añadir otras excepciones si existen
    from src.infrastructure.key_vault.key_vault_client import (
        KeyVaultClient,
    )  # Mantener si la estructura lo requiere

except ImportError as e:
    logging.critical(
        f"CRÍTICO: Falló la importación de módulos durante el inicio: {e}. Verifique __init__.py y dependencias."
    )
    # Clases Dummy (Añadir las nuevas)

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
        pass  # Dummy si se quitó

    class EmbeddingGenerator:
        pass  # NUEVO Dummy

    class EmbeddingAPIError(Exception):
        pass  # NUEVO Dummy

    class AzureAISearchAdapter:
        pass  # NUEVO Dummy

    class AISearchError(Exception):
        pass  # NUEVO Dummy

    class APIError(Exception):
        pass

    class KeyVaultError(Exception):
        pass

    class SecretNotFoundError(KeyVaultError):
        pass

    class JSONValidationError(Exception):
        pass

    def prompt_system(p, c, cv, d=None):
        return ""

    def extract_and_validate_cv_data_from_json(j):
        return None, None, None

    def calculate_average_score_from_dict(s):
        return None  # Devolver None en dummy

    def sanitize_for_id(t):
        return "sanitized-id"  # NUEVO Dummy

    def format_text_for_embedding(c, p, cv, a):
        return "formatted text"  # NUEVO Dummy

    def get_id_candidate(f):
        return ""

    def get_id_rank(f):
        return ""

    class KeyVaultClient:
        pass  # Mantener si se usa


# --- Constantes ---
CONNECTION_STRING_ENV_VAR = "AzureWebJobsStorage"
CANDIDATES_CONTAINER = "candidates"
# Contenedor para guardar resultados JSON de OpenAI si fallan pasos posteriores
RESULTS_POST_OPENAI_CONTAINER = "resultados-post-openai-fallidos"

# --- Definición de la App ---
app = func.FunctionApp(
    http_auth_level=func.AuthLevel.FUNCTION
)  # Nivel de auth global si aplica


# --- (Función _initialize_adapters_with_keyvault - Sin cambios, aunque no se use activamente) ---
# ... (código de _initialize_adapters_with_keyvault) ...

# --- (Función upload_cv_http_trigger - Sin cambios) ---
# ... (código de upload_cv_http_trigger) ...

# --- (Función _save_openai_result_on_failure - Sin cambios) ---
# ... (código de _save_openai_result_on_failure) ...

# --- Función Principal de Procesamiento ---
@app.blob_trigger(
    arg_name="inputblob",
    path=f"{CANDIDATES_CONTAINER}/{{name}}",  # Usar constante
    connection=CONNECTION_STRING_ENV_VAR,
)
def process_candidate_cv(inputblob: func.InputStream):
    """
    Función de Azure activada por un blob en 'candidates'.
    Extrae texto (DI), analiza (OpenAI), valida, calcula promedio,
    genera embeddings, guarda en AI Search y gestiona el blob original.
    """
    if not inputblob or not inputblob.name:
        logging.error("Disparador de blob invocado sin blob o nombre válido.")
        return

    blob_full_path = inputblob.name
    file_name = os.path.basename(blob_full_path)

    # Ignorar blobs en carpetas de error
    if "/error/" in blob_full_path.lower():
        logging.warning(
            f"Ignorando blob encontrado en subcarpeta de error: {blob_full_path}"
        )
        return

    logging.info(f"--- [INICIO] Procesando blob: {blob_full_path} ---")
    logging.info(
        f"Nombre Archivo: {file_name}, Tamaño: {inputblob.length} Bytes"
    )

    # Inicializar variables fuera de los try para acceso en finally/except
    rank_id: str = ""
    candidate_id: str = ""
    blob_service_client: Optional[BlobServiceClient] = None
    doc_intel_adapter: Optional[DocumentIntelligenceAdapter] = None
    openai_adapter: Optional[AzureOpenAIAdapter] = None
    rest_api_adapter: Optional[RestApiAdapter] = None  # Mantener si aún se usa
    embedding_generator: Optional[EmbeddingGenerator] = None  # NUEVO
    ai_search_adapter: Optional[AzureAISearchAdapter] = None  # NUEVO
    analysis_result_str: str = (
        ""  # Para guardar resultado crudo de OpenAI si fallan pasos posteriores
    )
    processed_successfully = False  # Flag de éxito final

    try:
        # --- 0. Inicialización ---
        logging.info(
            f"[{file_name}] Inicializando componentes y extrayendo IDs..."
        )
        rank_id = get_id_rank(file_name)
        candidate_id = get_id_candidate(file_name)
        if not rank_id or not candidate_id:
            raise ValueError(
                f"No se pudo extraer rank_id o candidate_id del archivo: {file_name}"
            )
        logging.info(
            f"[{file_name}] IDs: rank={rank_id}, candidate={candidate_id}"
        )

        storage_connection_string = os.environ.get(CONNECTION_STRING_ENV_VAR)
        if not storage_connection_string:
            raise ValueError(
                f"Variable de entorno requerida '{CONNECTION_STRING_ENV_VAR}' no encontrada."
            )
        blob_service_client = BlobServiceClient.from_connection_string(
            storage_connection_string
        )

        # Inicializar adaptadores (usando variables de entorno directamente por ahora)
        # En el futuro, podrías cambiar esto para usar _initialize_adapters_with_keyvault
        try:
            doc_intel_adapter = (
                DocumentIntelligenceAdapter()
            )  # Asume lectura de env vars en __init__
            openai_adapter = (
                AzureOpenAIAdapter()
            )  # Asume lectura de env vars en __init__
            rest_api_adapter = (
                RestApiAdapter()
            )  # Asume lectura de env vars en __init__
            embedding_generator = (
                EmbeddingGenerator()
            )  # NUEVO - Asume lectura de env vars
            ai_search_adapter = (
                AzureAISearchAdapter()
            )  # NUEVO - Asume lectura de env vars
            logging.info(
                f"[{file_name}] Adaptadores y clientes inicializados correctamente."
            )
        except ValueError as init_error:
            logging.error(
                f"[{file_name}] CRÍTICO: Falló la inicialización de un adaptador: {init_error}"
            )
            raise  # Relanzar para detener

        # --- 1. Extraer texto (Document Intelligence) ---
        logging.info(f"[{file_name}] Llamando a Document Intelligence...")
        extracted_text = doc_intel_adapter.analyze_cv(inputblob)
        logging.info(
            f"[{file_name}] Document Intelligence finalizó. Caracteres extraídos: {len(extracted_text)}"
        )

        # --- 2. Obtener Datos de Contexto (API REST) --- (Mantener si es necesario)
        logging.info(f"[{file_name}] Obteniendo datos de /Resumen/{rank_id}...")
        resumen_data = rest_api_adapter.get_resumen(id=rank_id)
        profile_description = resumen_data.get("profileDescription")
        variables_content = resumen_data.get("variablesContent")
        if profile_description is None or variables_content is None:
            raise APIError(
                f"Datos incompletos de /Resumen/{rank_id}: falta profileDescription o variablesContent"
            )
        logging.info(
            f"[{file_name}] Datos de /Resumen obtenidos para perfil: {profile_description[:50]}..."
        )

        # --- 3. Análisis (Azure OpenAI) ---
        logging.info(
            f"[{file_name}] Generando prompt y llamando a Azure OpenAI para análisis..."
        )
        system_prompt = prompt_system(
            profile=profile_description,
            criterios=variables_content,
            cv_candidato=extracted_text,
        )
        analysis_result_str = openai_adapter.get_completion(
            system_message=system_prompt, user_message=""
        )
        logging.info(f"[{file_name}] Azure OpenAI (análisis) finalizó.")

        # --- PASOS NUEVOS PARA AI SEARCH ---
        try:
            # 4. Validar JSON de OpenAI y Extraer Datos
            logging.info(f"[{file_name}] Validando resultado de OpenAI...")
            # Asume que extract_and_validate... devuelve (list[dict]|None, str|None, str|None) o lanza error
            cv_score, cv_analysis, candidate_name = (
                extract_and_validate_cv_data_from_json(analysis_result_str)
            )
            if cv_score is None or cv_analysis is None or candidate_name is None:
                # Si la función devuelve None en lugar de lanzar error
                raise JSONValidationError(
                    "Validación del JSON de OpenAI falló: campos requeridos faltantes o inválidos."
                )
            logging.info(
                f"[{file_name}] Validación JSON OK. Candidato: {candidate_name}"
            )

            # 5. Calcular Promedio
            logging.info(f"[{file_name}] Calculando promedio de scores...")
            average_score = calculate_average_score_from_dict(
                cv_score
            )  # Usa la función importada
            if average_score is None:
                logging.warning(
                    f"[{file_name}] No se pudo calcular un promedio válido. Se usará un valor indicativo (-1.0)."
                )
                average_score_value = -1.0  # Valor para indicar que no se calculó
            else:
                average_score_value = average_score
                logging.info(
                    f"[{file_name}] Promedio calculado: {average_score_value:.2f}"
                )

            # 6. Formatear Texto para Embedding
            logging.info(f"[{file_name}] Formateando texto para embedding...")
            text_to_embed = format_text_for_embedding(
                candidate_name=candidate_name,
                profile_name=profile_description,  # Usar el perfil obtenido de la API
                cv_analysis=cv_analysis,
                average_score=average_score,  # Pasar el float o None
            )

            # 7. Generar Embeddings
            logging.info(f"[{file_name}] Generando embeddings...")
            embeddings, chunks = embedding_generator.generate_embeddings(
                text_to_embed
            )
            if (
                embeddings is None
                or chunks is None
                or len(embeddings) != len(chunks)
            ):
                # Error ya loggeado dentro del generador
                raise EmbeddingAPIError(
                    "Falló la generación de embeddings o hubo inconsistencia."
                )
            logging.info(f"[{file_name}] Embeddings generados para {len(chunks)} chunks.")

            # 8. Preparar Documentos para AI Search
            logging.info(f"[{file_name}] Preparando documentos para AI Search...")
            documents_to_upload = []
            sanitized_profile = sanitize_for_id(
                profile_description
            )  # Usa la función importada
            sanitized_candidate = sanitize_for_id(
                candidate_name
            )  # Usa la función importada
            base_id = (
                f"{sanitized_profile}-{sanitized_candidate}-{rank_id}-{candidate_id}"
            )  # ID más específico

            for i, chunk in enumerate(chunks):
                doc_id = sanitize_for_id(
                    f"{base_id}-chunk-{i}"
                )  # Sanitizar también el ID final
                document = {
                    "id": doc_id,
                    "content": chunk,
                    "embedding": embeddings[i],
                    "candidateId": candidate_id,  # Campo para filtrar por ID de candidato
                    "candidateName": candidate_name,
                    "profileName": profile_description,  # Perfil específico evaluado
                    "rankId": rank_id,  # ID del proceso de ranking
                    "averageScore": average_score_value,  # Usar el valor calculado o -1.0
                    "sourceFile": file_name,
                    # Asegúrate que estos nombres de campo coincidan con tu índice de AI Search
                }
                documents_to_upload.append(document)

            # 9. Subir Documentos a AI Search
            logging.info(
                f"[{file_name}] Subiendo {len(documents_to_upload)} documentos a AI Search..."
            )
            upload_success = ai_search_adapter.upload_documents(documents_to_upload)
            if not upload_success:
                raise AISearchError("Falló la subida de uno o más documentos a AI Search.")
            logging.info(f"[{file_name}] Documentos subidos/fusionados a AI Search.")

            # --- FIN PASOS NUEVOS ---

            # 10. Enviar a API REST (Si aún es necesario después de guardar en AI Search)
            # Decide si estos pasos son redundantes ahora que guardas en AI Search
            # O si la API REST tiene otro propósito (ej. notificar a otro sistema)
            # Si los mantienes, usa los datos ya extraídos/calculados
            logging.info(f"[{file_name}] Enviando scores a API REST...")
            rest_api_adapter.add_scores(candidate_id=candidate_id, scores=cv_score)
            logging.info(f"[{file_name}] Guardando resumen en API REST...")
            rest_api_adapter.save_resumen(
                candidate_id=candidate_id,
                transcription=extracted_text,
                score=average_score_value,  # Enviar el promedio calculado
                analysis=cv_analysis,
                candidate_name=candidate_name,
            )
            logging.info(f"[{file_name}] Datos enviados a API REST.")

            # 11. Marcar como procesado en API (éxito)
            logging.info(
                f"[{file_name}] Marcando candidato como procesado (éxito) en API REST..."
            )
            rest_api_adapter.update_candidate(
                candidate_id=candidate_id, error_message=None
            )  # None indica éxito
            logging.info(f"[{file_name}] Candidato marcado como procesado.")

            processed_successfully = True  # Marcar éxito final aquí

        except (
            JSONValidationError,
            TypeError,
            EmbeddingAPIError,
            AISearchError,
            APIError,
            AuthenticationError,
        ) as post_openai_error:
            # Errores que ocurren DESPUÉS de obtener la respuesta de OpenAI
            failed_step = "UnknownPostOpenAI"
            if isinstance(post_openai_error, (JSONValidationError, TypeError)):
                failed_step = "ValidationOrCalculation"
            elif isinstance(post_openai_error, EmbeddingAPIError):
                failed_step = "EmbeddingGeneration"
            elif isinstance(post_openai_error, AISearchError):
                failed_step = "AISearchUpload"
            elif isinstance(post_openai_error, (APIError, AuthenticationError)):
                failed_step = "APISaveOrUpdate"  # Error al llamar a la API REST al final

            error_details_str = f"{type(post_openai_error).__name__}: {post_openai_error}"
            logging.error(
                f"[{file_name}] Error en paso '{failed_step}': {error_details_str}",
                exc_info=True,
            )

            # Guardar resultado crudo de OpenAI si lo tenemos
            if blob_service_client and analysis_result_str:
                _save_openai_result_on_failure(
                    blob_service_client,
                    rank_id,
                    candidate_id,
                    analysis_result_str,
                    failed_step,
                    error_details_str,
                )
            # Intentar reportar error a la API REST
            if rest_api_adapter and candidate_id:
                try:
                    logging.info(
                        f"[{file_name}] Reportando error '{failed_step}' a API REST..."
                    )
                    rest_api_adapter.update_candidate(
                        candidate_id=candidate_id,
                        error_message=error_details_str[:1000],
                    )
                    logging.info(
                        f"[{file_name}] Error '{failed_step}' reportado a API REST."
                    )
                except Exception as report_err:
                    logging.error(
                        f"[{file_name}] FALLO al reportar error '{failed_step}' a API REST: {report_err}"
                    )
            # No relanzar aquí, el finally se encargará del blob original

    except (
        ValueError,
        DocumentIntelligenceError,
        NoContentExtractedError,
        OpenAIError,
        APIError,
        AuthenticationError,
    ) as early_error:
        # Errores que ocurren ANTES o DURANTE OpenAI / obtención de datos de API REST
        error_msg = f"[{file_name}] Error temprano en el proceso: {type(early_error).__name__} - {early_error}"
        logging.error(error_msg, exc_info=True)
        # Intentar reportar error a la API REST si tenemos ID y adaptador
        if rest_api_adapter and candidate_id:
            try:
                logging.info(f"[{file_name}] Reportando error temprano a API REST...")
                rest_api_adapter.update_candidate(
                    candidate_id=candidate_id, error_message=error_msg[:1000]
                )
                logging.info(f"[{file_name}] Error temprano reportado a API REST.")
            except Exception as report_err:
                logging.error(
                    f"[{file_name}] FALLO al reportar error temprano a API REST: {report_err}"
                )
        # No relanzar aquí, el finally se encargará del blob original

    except Exception as unexpected_error:
        # Errores completamente inesperados
        error_msg = f"[{file_name}] Error inesperado en el proceso: {type(unexpected_error).__name__} - {unexpected_error}"
        logging.exception(error_msg)
        # Intentar reportar error a la API REST
        if rest_api_adapter and candidate_id:
            try:
                logging.info(f"[{file_name}] Reportando error inesperado a API REST...")
                rest_api_adapter.update_candidate(
                    candidate_id=candidate_id, error_message=error_msg[:1000]
                )
                logging.info(f"[{file_name}] Error inesperado reportado a API REST.")
            except Exception as report_err:
                logging.error(
                    f"[{file_name}] FALLO al reportar error inesperado a API REST: {report_err}"
                )
        # No relanzar aquí, el finally se encargará del blob original

    finally:
        # --- Gestión del Blob Original ---
        if blob_service_client:  # Solo si el cliente se inicializó
            if processed_successfully:
                # Borrar si TODO fue exitoso (incluyendo AI Search y API REST final)
                logging.info(
                    f"[{file_name}] Proceso exitoso. Intentando borrar blob original de '{CANDIDATES_CONTAINER}'."
                )
                try:
                    container_client_del = blob_service_client.get_container_client(
                        CANDIDATES_CONTAINER
                    )
                    blob_client_del = container_client_del.get_blob_client(file_name)
                    blob_client_del.delete_blob(delete_snapshots="include")
                    logging.info(f"[{file_name}] Blob original borrado exitosamente.")
                except ResourceNotFoundError:
                    logging.warning(
                        f"[{file_name}] No se encontró blob original para borrar (posiblemente ya borrado o movido)."
                    )
                except Exception as delete_err:
                    logging.error(
                        f"[{file_name}] FALLO al borrar blob original tras éxito: {delete_err}"
                    )
            else:
                # Si no fue exitoso, mover a error (si no se hizo ya en un except)
                # Verificar si el blob aún existe antes de intentar mover
                try:
                    source_container_client = blob_service_client.get_container_client(
                        CANDIDATES_CONTAINER
                    )
                    source_blob_client = source_container_client.get_blob_client(
                        file_name
                    )
                    source_blob_client.get_blob_properties()  # Lanza ResourceNotFoundError si no existe
                    logging.warning(
                        f"[{file_name}] Proceso NO exitoso. Intentando mover blob original a 'error/general'."
                    )
                    # Usar una carpeta genérica si no se capturó antes el error específico
                    # move_blob_to_folder(blob_service_client, CANDIDATES_CONTAINER, file_name, "error/general") # Comentar esta linea porque no existe esta funcion en el documento
                except ResourceNotFoundError:
                    logging.warning(
                        f"[{file_name}] Blob original ya no existe en '{CANDIDATES_CONTAINER}/{file_name}', probablemente movido por un bloque 'except' anterior."
                    )
                except Exception as move_err:
                    logging.error(
                        f"[{file_name}] FALLO al intentar mover blob original a error/general en finally: {move_err}"
                    )
        else:
            logging.error(
                f"[{file_name}] Cliente de Blob Storage no inicializado, no se puede gestionar el blob original."
            )

        logging.info(f"--- [FIN] Procesamiento para blob: {blob_full_path} ---")

# --- Función Auxiliar move_blob_to_folder ---
# (Asegúrate que esté definida aquí, sin cambios respecto a la versión anterior)
# def move_blob_to_folder(...):
#  ...