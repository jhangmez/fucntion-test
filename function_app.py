import logging
import os
import json
from typing import Optional, Tuple

import azure.functions as func
from azure.storage.blob import BlobServiceClient, ContentSettings, BlobClient
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

try:
    from src.infrastructure.ocr.document_intelligence_adapter import (
        DocumentIntelligenceAdapter, DocumentIntelligenceError, NoContentExtractedError
    )
    from src.infrastructure.openai.azure_openai_adapter import (
        AzureOpenAIAdapter, OpenAIError
    )
    from src.infrastructure.api_rest.api_rest_adapter import RestApiAdapter
    from src.domain.exceptions import APIError, KeyVaultError, SecretNotFoundError, AuthenticationError, JSONValidationError
    from src.infrastructure.key_vault.key_vault_client import KeyVaultClient
    from src.shared.prompt_system import prompt_system
    from src.shared.validate_process_json import extract_and_validate_cv_data_from_json
    from src.shared.promedio_scores import calculate_average_score_from_dict
    from src.shared.extract_values import get_id_candidate, get_id_rank
except ImportError as e:
    logging.critical(f"CRÍTICO: Falló la importación de módulos: {e}")
    # Define clases dummy para que el resto del código no falle en el import
    class DocumentIntelligenceAdapter: pass
    class DocumentIntelligenceError(Exception): pass
    class NoContentExtractedError(DocumentIntelligenceError): pass
    class AzureOpenAIAdapter: pass
    class OpenAIError(Exception): pass
    class RestApiAdapter: pass
    class APIError(Exception): pass
    class AuthenticationError(APIError): pass
    class KeyVaultError(Exception): pass
    class SecretNotFoundError(KeyVaultError): pass
    class JSONValidationError(Exception): pass
    class KeyVaultClient: pass
    prompt_system = lambda *args, **kwargs: ""
    extract_and_validate_cv_data_from_json = lambda *args: (None, None, None)
    calculate_average_score_from_dict = lambda *args: "0.0"
    get_id_candidate = lambda fn: "c1" if "c1" in fn else ""
    get_id_rank = lambda fn: "r1" if "r1" in fn else ""
# --- Constantes ---
CONNECTION_STRING_ENV_VAR = "AzureWebJobsStorage"
CANDIDATES_CONTAINER = "candidates"
RESULTS_POST_OPENAI_CONTAINER = "resultados-post-openai"
MANUAL_ERROR_CONTAINER = "error"
KEY_VAULT_URI_ENV_VAR = "KEY_VAULT_URI"

# --- Nombres Secretos Key Vault ---
SECRET_NAMES = {
    "openai_api_key": "OpenaiApiKey",
    "openai_endpoint": "OpenaiEndpoint",
    "openai_api_version": "OpenaiApiVersion",
    "openai_model": "OpenaiModel",
    "openai_deployment": "OpenaiDeployment",
    "docintel_api_key": "DocIntelApiKey",
    "docintel_endpoint": "DocIntelEndpoint",
    "rest_api_username": "RestApiUsername",
    "rest_api_password": "RestApiPassword",
    "rest_api_role": "RestApiRole",
    "rest_api_user_app": "RestApiUserApplication",
    "rest_api_base_url": "RestApiBaseUrl",
}

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# --- Trigger HTTP para subir CV ---
@app.route(route="upload-cv", methods=[func.HttpMethod.POST], auth_level=func.AuthLevel.FUNCTION)
def upload_cv_http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("Función HTTP upload_cv_http_trigger procesando solicitud.")
    try:
        file_content = None
        filename = None
        content_type = "application/octet-stream"

        file_from_form = req.files.get("file")
        if file_from_form:
            filename = os.path.basename(file_from_form.filename)
            file_content = file_from_form.read()
            content_type = file_from_form.mimetype or content_type
            logging.info(f"Recibido archivo '{filename}' vía form-data, tipo: {content_type}")
        else:
            file_content = req.get_body()
            if not file_content: return func.HttpResponse("...", status_code=400)
            filename = os.path.basename(req.headers.get("X-Filename", "uploaded_cv.pdf"))
            content_type = req.headers.get("Content-Type", content_type)
            logging.info(f"Recibido archivo '{filename}' vía body, tipo: {content_type}")

        if not filename: filename = "default_cv.pdf"

        connection_string = os.environ[CONNECTION_STRING_ENV_VAR]
        blob_service_client = BlobServiceClient.from_connection_string(connection_string)
        blob_client = blob_service_client.get_blob_client(container=CANDIDATES_CONTAINER, blob=filename)
        blob_content_settings = ContentSettings(content_type=content_type)
        blob_client.upload_blob(file_content, overwrite=True, content_settings=blob_content_settings)
        logging.info(f"Archivo '{filename}' subido a '{CANDIDATES_CONTAINER}'.")
        return func.HttpResponse(f"Archivo '{filename}' subido.", status_code=200)

    except KeyError:
        logging.exception(f"Variable de entorno '{CONNECTION_STRING_ENV_VAR}' no encontrada.")
        return func.HttpResponse("Error de configuración del servidor.", status_code=500)
    except Exception as e:
        logging.exception(f"Error al subir el archivo al blob: {e}")
        return func.HttpResponse(f"Error al guardar el archivo: {e}", status_code=500)


# --- Funciones Auxiliares para Manejo de Errores ---

def _get_blob_client(blob_service_client: BlobServiceClient, container_name: str, blob_name: str) -> BlobClient:
    """Obtiene un cliente de blob y crea el contenedor si no existe."""
    try:
        container_client = blob_service_client.get_container_client(container_name)
        if not container_client.exists():
            logging.warning(f"Contenedor '{container_name}' no encontrado, intentando crear.")
            try:
                 container_client.create_container()
                 logging.info(f"Contenedor '{container_name}' creado.")
            except HttpResponseError as e:
                 if e.status_code == 409: # Conflict - ya existe (carrera condición)
                     logging.info(f"Contenedor '{container_name}' ya existe (detectado después del check).")
                 else:
                    logging.error(f"Error al crear contenedor '{container_name}': {e}")
                    raise # Relanzar si no es un conflicto esperado
    except Exception as e:
        logging.error(f"Error inesperado al obtener/crear cliente de contenedor '{container_name}': {e}")
        raise
    return container_client.get_blob_client(blob_name)

def _delete_blob_if_exists(blob_client: BlobClient, blob_description: str):
    """Intenta borrar un blob, logueando si no existe o si falla."""
    try:
        logging.info(f"Intentando borrar blob: {blob_description} ({blob_client.container_name}/{blob_client.blob_name})")
        blob_client.delete_blob(delete_snapshots="include")
        logging.info(f"Blob borrado exitosamente: {blob_description}")
    except ResourceNotFoundError:
        logging.warning(f"No se encontró el blob para borrar (puede que ya se haya movido/borrado): {blob_description}")
    except Exception as e:
        logging.error(f"FALLO al borrar el blob {blob_description}: {e}", exc_info=True)

def _handle_processing_error(
    blob_service_client: BlobServiceClient,
    original_container: str,
    original_blob_name: str,
    error_reason: str,
    file_name_log_prefix: str,
    rest_api_adapter: Optional[RestApiAdapter] = None,
    candidate_id: Optional[str] = None,
):
    """Mueve el blob a error, crea JSON, actualiza API y borra el original."""
    logging.error(f"{file_name_log_prefix} Error Crítico: {error_reason}. Iniciando manejo de error...")

    if rest_api_adapter and candidate_id:
        try:
            logging.info(f"{file_name_log_prefix} Intentando actualizar estado de error en API para candidate_id: {candidate_id}...")
            rest_api_adapter.update_candidate(candidate_id=candidate_id, error_message=error_reason[:1000])
            logging.info(f"{file_name_log_prefix} Estado de error actualizado en API.")
        except Exception as api_err:
            logging.error(f"{file_name_log_prefix} FALLO al actualizar estado de error en API: {api_err}", exc_info=True)
    elif candidate_id:
         logging.warning(f"{file_name_log_prefix} No se pudo actualizar API: rest_api_adapter no disponible.")
    else:
         logging.warning(f"{file_name_log_prefix} No se pudo actualizar API: candidate_id no disponible.")

    source_blob_client = blob_service_client.get_blob_client(container=original_container, blob=original_blob_name)
    _delete_blob_if_exists(source_blob_client, f"original ({original_container}/{original_blob_name}) después de copiar a error")

def _save_intermediate_result_and_cleanup(
    blob_service_client: BlobServiceClient,
    original_container: str,
    original_blob_name: str,
    rank_id: str,
    candidate_id: str,
    openai_result_str: str, # El JSON crudo de OpenAI
    get_resumen_result: dict, # Resultado de get_resumen
    transcription: str, # Texto extraído por DI
    failed_step: str,
    error_details: str,
    file_name_log_prefix: str,
    rest_api_adapter: Optional[RestApiAdapter] = None,
):
    """Guarda datos intermedios en 'resultados-post-openai' y borra el original."""
    logging.warning(f"{file_name_log_prefix} Error post-OpenAI en paso '{failed_step}'. Guardando resultado intermedio...")

    result_filename = f"{rank_id}_{candidate_id}_partial_result_{failed_step}.json"
    result_blob_client = _get_blob_client(blob_service_client, "resultados-post-openai", result_filename)

    # Combinar toda la información disponible en un solo JSON
    intermediate_data = {
        "rank_id": rank_id,
        "candidate_id": candidate_id,
        "get_resumen_result": get_resumen_result,
        "document_intelligence_transcription": transcription,
        "azure_openai_raw_result": openai_result_str, # Guardar el string crudo
        "failure_info": {
            "failed_step": failed_step,
            "error_details": error_details
        }
    }
    intermediate_json = json.dumps(intermediate_data, indent=2, ensure_ascii=False)

    # Metadata para búsqueda rápida (opcional pero útil)
    metadata = {
        "original_filename": original_blob_name,
        "rank_id": rank_id,
        "candidate_id": candidate_id,
        "failed_step": failed_step,
        "error_details_summary": error_details[:250], # Resumen corto para metadata
    }
    content_settings = ContentSettings(content_type="application/json", metadata=metadata)

    # 1. Subir el resultado JSON intermedio
    try:
        logging.info(f"{file_name_log_prefix} Guardando resultado intermedio en '{RESULTS_POST_OPENAI_CONTAINER}/{result_filename}'...")
        result_blob_client.upload_blob(intermediate_json, overwrite=True, content_settings=content_settings)
        logging.info(f"{file_name_log_prefix} Resultado intermedio guardado exitosamente.")
    except Exception as e:
        # No detener el flujo principal si falla el guardado del error, solo loguear críticamente
        logging.exception(
            f"{file_name_log_prefix} CRITICAL ERROR al intentar guardar resultado intermedio en '{RESULTS_POST_OPENAI_CONTAINER}': {e}"
        )
        # NO BORRAR EL ORIGINAL SI FALLA EL GUARDADO DEL INTERMEDIO
        return # Salir temprano

    # 2. Actualizar API REST (si es posible)
    if rest_api_adapter and candidate_id:
        try:
            logging.info(f"{file_name_log_prefix} Intentando actualizar estado de error (post-OpenAI) en API para candidate_id: {candidate_id}...")
            rest_api_adapter.update_candidate(candidate_id=candidate_id, error_message=f"Error en {failed_step}: {error_details}"[:1000])
            logging.info(f"{file_name_log_prefix} Estado de error (post-OpenAI) actualizado en API.")
        except Exception as api_err:
            logging.error(f"{file_name_log_prefix} FALLO al actualizar estado de error (post-OpenAI) en API: {api_err}", exc_info=True)
    # (Advertencias si falta adaptador o ID, como en _handle_processing_error)


    # 3. Borrar blob original (AHORA que el resultado intermedio se guardó)
    source_blob_client = blob_service_client.get_blob_client(container=original_container, blob=original_blob_name)
    _delete_blob_if_exists(source_blob_client, f"original ({original_container}/{original_blob_name}) después de guardar resultado intermedio")


def _initialize_adapters(kv_uri: str) -> Tuple[DocumentIntelligenceAdapter, AzureOpenAIAdapter, RestApiAdapter]:
    """Inicializa todos los adaptadores obteniendo secretos de Key Vault."""
    logging.info("Inicializando adaptadores usando Key Vault: %s", kv_uri)
    if not kv_uri:
        raise ValueError("KEY_VAULT_URI no está configurado en las variables de entorno.")

    kv_client = KeyVaultClient(kv_uri) # Pasar URI al constructor
    secrets = {}
    try:
        for key, secret_name in SECRET_NAMES.items():
            secrets[key] = kv_client.get_secret(secret_name)
            if not secrets[key]: # Doble check por si get_secret devuelve None/vacío
                 raise SecretNotFoundError(f"Secreto '{secret_name}' (para {key}) está vacío o no se pudo obtener.")
        logging.info("Todos los secretos requeridos fueron recuperados de Key Vault.")

        # Instanciar adaptadores (Asegúrate que los constructores acepten estos nombres de parámetros)
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
            base_url=secrets["rest_api_base_url"],
        )

        logging.info("Adaptadores inicializados exitosamente.")
        return doc_intel_adapter, openai_adapter, rest_api_adapter

    except (SecretNotFoundError, KeyVaultError) as e:
        logging.critical(f"CRÍTICO: Falló la obtención de secretos de Key Vault: {e}", exc_info=True)
        raise # Relanza para detener la ejecución de la función
    except KeyError as e:
         logging.critical(f"CRÍTICO: Falta un secreto esperado '{e}' en la configuración SECRET_NAMES o en Key Vault.")
         raise SecretNotFoundError(f"Secreto de configuración faltante: {e}")
    except Exception as e:
        logging.critical(f"CRÍTICO: Falló la inicialización de adaptadores: {e}", exc_info=True)
        raise # Relanza error inesperado durante la inicialización


# --- Trigger Principal del Blob ---
@app.blob_trigger(
    arg_name="inputblob",
    path="candidates/{name}",
    connection="AzureWebJobsStorage",
)
def process_candidate_cv(inputblob: func.InputStream):
    """
    Procesa un CV desde el contenedor 'candidates'.
    Orden: IDs -> get_resumen -> DI -> OpenAI -> Validación/Cálculo -> API Final.
    Maneja errores moviendo a 'error' o guardando resultados intermedios.
    """
    if not inputblob or not inputblob.name:
        logging.error("Disparador de blob invocado sin blob o nombre válido.")
        return

    # Extraer container/blob name correctamente
    # inputblob.name suele ser 'container/blobname'
    try:
        container_from_path, blob_name_from_path = inputblob.name.split('/', 1)
        if container_from_path.lower() != CANDIDATES_CONTAINER.lower():
             logging.warning(f"Blob '{inputblob.name}' no está en el contenedor esperado '{CANDIDATES_CONTAINER}'. Ignorando.")
             return
        file_name = os.path.basename(blob_name_from_path) # Nombre del archivo sin ruta
        blob_full_path = inputblob.name # Mantener path completo para logs
        log_prefix = f"[{file_name}]" # Prefijo para logs
    except ValueError:
        logging.error(f"No se pudo extraer nombre de archivo/contenedor del path: {inputblob.name}")
        # Decide qué hacer aquí, ¿mover a error? Probablemente sí.
        # Necesitarías inicializar blob_service_client antes si quieres moverlo.
        # Por ahora, solo retornamos.
        return

    logging.info(f"{log_prefix} --- Iniciando procesamiento para: {blob_full_path} (Tamaño: {inputblob.length} Bytes) ---")

    # Ignorar blobs en subdirectorios (si aplica) o en el contenedor de error mismo
    if "/" in blob_name_from_path: # Si hay subdirectorios dentro de 'candidates'
        logging.warning(f"{log_prefix} Ignorando blob en subdirectorio: {blob_full_path}")
        return

    # Variables de estado y datos
    rank_id: Optional[str] = None
    candidate_id: Optional[str] = None
    blob_service_client: Optional[BlobServiceClient] = None
    doc_intel_adapter: Optional[DocumentIntelligenceAdapter] = None
    openai_adapter: Optional[AzureOpenAIAdapter] = None
    rest_api_adapter: Optional[RestApiAdapter] = None
    resumen_data: Optional[dict] = None
    extracted_text: Optional[str] = None
    analysis_result_str: Optional[str] = None # Guardar el JSON crudo de OpenAI
    processed_successfully = False # Flag de éxito final

    try:
        # --- 0. Inicialización Temprana (IDs y Blob Service) ---
        logging.info(f"{log_prefix} Paso 0: Extrayendo IDs y conectando a Storage...")
        rank_id = get_id_rank(file_name)
        candidate_id = get_id_candidate(file_name)
        if not rank_id or not candidate_id:
            # Error Crítico Temprano: No se puede continuar sin IDs
            # Usar ValueError para indicar fallo de datos de entrada
             raise ValueError(f"No se pudieron extraer rank_id o candidate_id del nombre de archivo: {file_name}")
        logging.info(f"{log_prefix} IDs extraídos -> RankID: {rank_id}, CandidateID: {candidate_id}")

        storage_connection_string = os.environ.get(CONNECTION_STRING_ENV_VAR)
        if not storage_connection_string:
            raise ValueError(f"Variable de entorno '{CONNECTION_STRING_ENV_VAR}' no encontrada.")
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
        logging.info(f"{log_prefix} Conexión a Blob Storage establecida.")

        # --- 1. Inicializar Adaptadores (usando Key Vault) ---
        # logging.info(f"{log_prefix} Paso 1: Inicializando adaptadores desde Key Vault...")
        # kv_uri = os.environ.get(KEY_VAULT_URI_ENV_VAR)
        # La excepción de _initialize_adapters detendrá la función si falla
        # doc_intel_adapter, openai_adapter, rest_api_adapter = _initialize_adapters(kv_uri)
        # logging.info(f"{log_prefix} Adaptadores inicializados.")

        # --- 1. Inicializar Adaptadores directamente desde env ---
        logging.info(f"{log_prefix} Paso 1: Inicializando adaptadores...")
        try:
            doc_intel_adapter = DocumentIntelligenceAdapter()
            openai_adapter = AzureOpenAIAdapter()
            rest_api_adapter = RestApiAdapter()
            logging.info(f"[{file_name}] Adaptadores inicializados correctamente.")
        except ValueError as init_error:
            logging.error(f"[{file_name}] CRÍTICO: Falló la inicialización de un adaptador: {init_error}")
            raise

        except ValueError as init_error:
            logging.error(f"[{file_name} CRIRICO]")

        # --- 2. Obtener Resumen de API Externa ---
        logging.info(f"{log_prefix} Paso 2: Llamando a get_resumen para RankID: {rank_id}...")
        resumen_data = rest_api_adapter.get_resumen(id=rank_id) # APIError se captura abajo
        profile_description = resumen_data.get("profileDescription")
        variables_content = resumen_data.get("variablesContent")
        if profile_description is None or variables_content is None:
            # Considerar esto un tipo de APIError si los datos esperados no vienen
            raise APIError(f"Respuesta de get_resumen incompleta para RankID {rank_id}. Faltan 'profileDescription' o 'variablesContent'.")
        logging.info(f"{log_prefix} Datos de get_resumen obtenidos correctamente.")

        # --- 3. Extraer Texto con Document Intelligence ---
        logging.info(f"{log_prefix} Paso 3: Llamando a Document Intelligence...")
        # Pasar el stream directamente
        extracted_text = doc_intel_adapter.analyze_cv(inputblob) # DocumentIntelligenceError o NoContentExtractedError se capturan abajo
        if not extracted_text or not extracted_text.strip():
             raise NoContentExtractedError(f"Document Intelligence no extrajo contenido o el contenido está vacío para {file_name}.")
        logging.info(f"{log_prefix} Document Intelligence completado. {len(extracted_text)} caracteres extraídos.")

        # --- 4. Preparar y Llamar a Azure OpenAI ---
        logging.info(f"{log_prefix} Paso 4: Generando prompt y llamando a Azure OpenAI...")
        system_prompt = prompt_system(
            profile=profile_description,
            criterios=variables_content,
        )
        if not system_prompt:
             raise ValueError("El prompt generado para OpenAI está vacío.")
        if not extracted_text:
             extracted_text="No se envio ningun contenido, debes retornar vacio."
        analysis_result_str = openai_adapter.get_completion(
            system_message=system_prompt, user_message=extracted_text
        )
        if not analysis_result_str:
            raise OpenAIError(f"Azure OpenAI devolvió una respuesta vacía para {file_name}.")
        logging.info(f"{log_prefix} Azure OpenAI completado.")
        # A partir de aquí, si hay un error, se guardará en analysis_result_str

        # --- Inicio Bloque Post-OpenAI ---
        # Cualquier error aquí resultará en guardar el resultado intermedio

        # --- 5. Validar JSON de OpenAI ---
        logging.info(f"{log_prefix} Paso 5: Validando resultado JSON de OpenAI...")
        cv_score, cv_analysis, candidate_name = extract_and_validate_cv_data_from_json(analysis_result_str)
        # La función de validación debería lanzar JSONValidationError si falla
        if cv_score is None or cv_analysis is None or candidate_name is None:
             # Reforzar la validación por si la función no lanza excepción pero devuelve None
             raise JSONValidationError(f"Validación fallida o datos incompletos en JSON de OpenAI para {file_name}.")
        logging.info(f"{log_prefix} Validación de JSON exitosa. Candidate Name: {candidate_name}")

        # --- 6. Calcular Promedio ---
        logging.info(f"{log_prefix} Paso 6: Calculando promedio de scores...")
        promedio_scores = calculate_average_score_from_dict(cv_score)
        # Esta función debería manejar internamente errores de tipo o formato en cv_score
        if promedio_scores is None:
             raise ValueError(f"Cálculo del promedio de scores falló para {file_name}.")
        logging.info(f"{log_prefix} Promedio calculado: {promedio_scores}")

        # --- 8. Enviar Resultados a API REST Final ---
        logging.info(f"{log_prefix} Paso 8: Enviando resultados finales a la API REST...")

        # 8a. Enviar Scores
        logging.info(f"{log_prefix} Paso 8a: Llamando a add_scores para CandidateID: {candidate_id}...")
        rest_api_adapter.add_scores(candidate_id=candidate_id, scores=cv_score)
        logging.info(f"{log_prefix} add_scores completado.")

        # 8b. Guardar Resumen Completo
        logging.info(f"{log_prefix} Paso 8b: Llamando a save_resumen para CandidateID: {candidate_id}...")
        rest_api_adapter.save_resumen(
            candidate_id=candidate_id,
            transcription=extracted_text, # El texto completo de DI
            score=promedio_scores, # El promedio calculado
            analysis=cv_analysis, # El análisis validado de OpenAI
            candidate_name=candidate_name # El nombre validado de OpenAI
        )
        logging.info(f"{log_prefix} save_resumen completado.")

        # 8c. Marcar como Procesado Exitosamente
        logging.info(f"{log_prefix} Paso 8c: Llamando a update_candidate (estado éxito) para CandidateID: {candidate_id}...")
        rest_api_adapter.update_candidate(
            candidate_id=candidate_id,
            error_message=None # Indicar éxito explícitamente
        )
        logging.info(f"{log_prefix} update_candidate (éxito) completado.")
        logging.info(f"{log_prefix} Paso 8 (API REST Final) completado.")

        # --- Éxito Total ---
        processed_successfully = True
        logging.info(f"{log_prefix} *** PROCESO COMPLETADO EXITOSAMENTE ***")

    # --- Manejo de Errores Específicos (Pre-OpenAI o Críticos) ---
    except (ValueError, SecretNotFoundError, KeyVaultError, # Errores de inicialización/configuración/IDs
            APIError, AuthenticationError, # Errores de API REST (get_resumen)
            DocumentIntelligenceError, NoContentExtractedError, # Errores de DI
            OpenAIError # Errores de OpenAI
            ) as early_or_critical_error:
        error_details = f"{type(early_or_critical_error).__name__}: {early_or_critical_error}"
        # Mover a error, crear JSON, actualizar API, borrar original
        if blob_service_client:
            _handle_processing_error(
                blob_service_client=blob_service_client,
                original_container=CANDIDATES_CONTAINER,
                original_blob_name=file_name,
                error_reason=error_details,
                file_name_log_prefix=log_prefix,
                rest_api_adapter=rest_api_adapter,
                candidate_id=candidate_id
            )
        else:
            # Si blob_service_client no se inicializó, solo podemos loguear
            logging.critical(f"{log_prefix} Error MUY temprano ({error_details}). No se puede mover a error (BlobServiceClient no disponible).")


    # --- Manejo de Errores Post-OpenAI ---
    except (JSONValidationError, TypeError, APIError, AuthenticationError
             ) as post_openai_error:
        failed_step = "UnknownPostOpenAI"
        # Determinar el paso específico si es posible
        if isinstance(post_openai_error, (JSONValidationError, TypeError, ValueError)): # ValueError podría ser del promedio
            failed_step = "ValidationOrCalculation"
        elif isinstance(post_openai_error, (APIError, AuthenticationError)):
            # Aquí podrías intentar ser más específico si tu adaptador API lanza errores distintos
            # por add_scores, save_resumen, update_candidate. Por ahora, genérico.
            failed_step = "FinalAPISaveOrUpdate"

        error_details = f"{type(post_openai_error).__name__}: {post_openai_error}"
        logging.error(f"{log_prefix} Error en paso post-OpenAI '{failed_step}': {error_details}", exc_info=True)

        # Guardar resultado intermedio y borrar original
        if blob_service_client and analysis_result_str and resumen_data and extracted_text:
            _save_intermediate_result_and_cleanup(
                 blob_service_client=blob_service_client,
                 original_container=CANDIDATES_CONTAINER,
                 original_blob_name=file_name,
                 rank_id=rank_id,
                 candidate_id=candidate_id,
                 openai_result_str=analysis_result_str,
                 get_resumen_result=resumen_data,
                 transcription=extracted_text,
                 failed_step=failed_step,
                 error_details=error_details,
                 file_name_log_prefix=log_prefix,
                 rest_api_adapter=rest_api_adapter
            )
        else:
             logging.critical(f"{log_prefix} No se pudo guardar el resultado intermedio por falta de datos críticos (blob_service_client, openai_result, etc.). El blob original podría NO ser borrado.")
             # Intentar actualizar API aunque no se guarde el intermedio
             if rest_api_adapter and candidate_id:
                  try:
                      rest_api_adapter.update_candidate(candidate_id=candidate_id, error_message=f"Error en {failed_step} (Intermedio NO guardado): {error_details}"[:1000])
                  except Exception as api_err:
                      logging.error(f"{log_prefix} FALLO al actualizar API sobre error post-OpenAI (sin intermedio): {api_err}")


    # --- Manejo de Errores Inesperados ---
    except Exception as unexpected_error:
        error_details = f"UnexpectedError: {type(unexpected_error).__name__} - {unexpected_error}"
        logging.exception(f"{log_prefix} ¡Error Inesperado!") # Log con traceback

        # Decidir si tratarlo como error temprano o post-OpenAI
        if analysis_result_str and blob_service_client and resumen_data and extracted_text:
            # Si OpenAI ya corrió, intentar guardar intermedio
             _save_intermediate_result_and_cleanup(
                 blob_service_client=blob_service_client,
                 original_container=CANDIDATES_CONTAINER,
                 original_blob_name=file_name,
                 rank_id=rank_id,
                 candidate_id=candidate_id,
                 openai_result_str=analysis_result_str,
                 get_resumen_result=resumen_data,
                 transcription=extracted_text,
                 failed_step="Unexpected",
                 error_details=error_details,
                 file_name_log_prefix=log_prefix,
                 rest_api_adapter=rest_api_adapter
             )
        elif blob_service_client:
             # Si fue antes de OpenAI o faltan datos, tratar como error temprano
             _handle_processing_error(
                 blob_service_client=blob_service_client,
                 original_container=CANDIDATES_CONTAINER,
                 original_blob_name=file_name,
                 error_reason=error_details,
                 file_name_log_prefix=log_prefix,
                 rest_api_adapter=rest_api_adapter,
                 candidate_id=candidate_id
            )
        else:
            logging.critical(f"{log_prefix} Error Inesperado ({error_details}). No se puede manejar el blob (BlobServiceClient no disponible).")


    finally:
        # --- Limpieza Final ---
        # La lógica principal de borrado/movimiento ya está en los handlers de error.
        # Aquí solo necesitamos borrar el original SI el proceso fue COMPLETAMENTE exitoso.
        if processed_successfully and blob_service_client:
            logging.info(f"{log_prefix} Proceso exitoso. Intentando borrar blob original final...")
            source_blob_client = blob_service_client.get_blob_client(container=CANDIDATES_CONTAINER, blob=file_name)
            _delete_blob_if_exists(source_blob_client, f"original ({CANDIDATES_CONTAINER}/{file_name}) después de éxito total")
        elif not processed_successfully:
             logging.warning(f"{log_prefix} El proceso no fue exitoso. La gestión del blob original (borrado/movido a error) debería haberse realizado en el bloque 'except' correspondiente.")
             # Podrías añadir un check aquí para ver si el blob original todavía existe,
             # lo cual indicaría un posible fallo en la lógica de manejo de errores.
             try:
                 if blob_service_client:
                     check_client = blob_service_client.get_blob_client(container=CANDIDATES_CONTAINER, blob=file_name)
                     if check_client.exists():
                         logging.error(f"{log_prefix} ¡ALERTA! El blob original '{CANDIDATES_CONTAINER}/{file_name}' todavía existe después de un fallo. La lógica de manejo de errores puede tener un problema.")
             except Exception as check_err:
                 logging.error(f"{log_prefix} Error al verificar existencia del blob original después de fallo: {check_err}")


        logging.info(f"{log_prefix} --- Finalizando procesamiento para: {blob_full_path} ---")