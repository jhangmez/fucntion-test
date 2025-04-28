¡Absolutamente! Vamos a refactorizar tu código de Azure Function para que siga una arquitectura CLEAN, sea más legible, mantenible y testeable.

**Estructura General (CLEAN)**

```
.
├── function_app.py          # Punto de entrada de la Azure Function
├── README.md                # Documentación del proyecto
├── requirements.txt         # Dependencias de Python
├── src
│   ├── domain               # Lógica de negocio, entidades, casos de uso
│   │   ├── entities           # Objetos de datos (DTOs)
│   │   │   └── api_credentials.py
│   │   ├── exceptions.py      # Excepciones personalizadas
│   │   └── usecases           # Interacciones o casos de uso del sistema
│   │       ├── process_cv.py  # Proceso principal de análisis de CV
│   │       └── interfaces.py  # Interface de los casos de uso
│   ├── infrastructure       # Adaptadores para interactuar con servicios externos
│   │   ├── api_rest           # Adaptador para la API REST
│   │   │   └── api_rest_adapter.py
│   │   ├── key_vault          # Adaptador para Azure Key Vault
│   │   │   └── key_vault_client.py
│   │   ├── ocr                # Adaptador para Document Intelligence y OpenAI
│   │   │   ├── document_intelligence_adapter.py
│   │   │   └── azure_openai_adapter.py
│   │   ├── storage            # Adaptador para Azure Blob Storage
│   │   │   └── blob_storage_adapter.py
│   ├── interfaces           # Definiciones de interfaces (abstracciones)
│   │   ├── api_rest_repository_interface.py
│   │   └── blob_storage_interface.py # Nueva interfaz para el storage
│   ├── shared               # Código reutilizable (helpers, validaciones)
│   │   ├── extract_values.py
│   │   ├── promedio_scores.py
│   │   ├── prompt_system.py
│   │   └── validate_process_json.py
```

**Refactorización del Código**

Voy a dividir el código existente en las diferentes capas de la arquitectura CLEAN.

**1. `src/domain/entities/api_credentials.py` (Sin cambios)**

Este archivo ya define una entidad de dominio y no necesita modificaciones.

**2. `src/domain/exceptions.py` (Sin cambios)**

Este archivo ya define excepciones de dominio y no necesita modificaciones.

**3. `src/domain/usecases/interfaces.py`**

```python
# src/domain/usecases/interfaces.py
from abc import ABC, abstractmethod
from typing import BinaryIO, Dict, Optional, Tuple

class ProcessCVUseCaseInterface(ABC):
    """
    Interfaz para el caso de uso de procesamiento de CVs.
    Define el contrato para la ejecución del flujo principal de la aplicación.
    """
    @abstractmethod
    def execute(self, blob_name: str, file_stream: BinaryIO) -> None:
        """
        Ejecuta el proceso de análisis y almacenamiento de los resultados del CV.

        Args:
            blob_name (str): El nombre del blob que contiene el CV.
            file_stream (BinaryIO): Un flujo binario que contiene el CV.
        """
        raise NotImplementedError
```

**4. `src/domain/usecases/process_cv.py`**

```python
# src/domain/usecases/process_cv.py
import logging
import os
import json
from typing import BinaryIO, Dict, Optional

from src.domain.exceptions import (
    APIError,
    AuthenticationError,
    DocumentIntelligenceError,
    JSONValidationError,
    KeyVaultError,
    NoContentExtractedError,
    OpenAIError,
    SecretNotFoundError,
)
from src.infrastructure.ocr.document_intelligence_adapter import DocumentIntelligenceAdapter
from src.infrastructure.openai.azure_openai_adapter import AzureOpenAIAdapter
from src.infrastructure.api_rest.api_rest_adapter import RestApiAdapter
from src.infrastructure.storage.blob_storage_adapter import BlobStorageAdapter  # Importa el adaptador de Blob Storage
from src.domain.usecases.interfaces import ProcessCVUseCaseInterface
from src.shared.prompt_system import prompt_system
from src.shared.validate_process_json import extract_and_validate_cv_data_from_json
from src.shared.promedio_scores import calculate_average_score_from_dict
from src.shared.extract_values import get_id_candidate, get_id_rank

# --- Constantes ---
CANDIDATES_CONTAINER = "candidates"
RESULTS_POST_OPENAI_CONTAINER = "resultados-post-openai"
MANUAL_ERROR_CONTAINER = "error"
FUNCTION_PROCESS_TYPE = "FUNCTION-IARC"


class ProcessCVUseCase(ProcessCVUseCaseInterface):
    """
    Implementación del caso de uso para procesar CVs.
    Orquesta la extracción de texto, análisis con IA y almacenamiento de resultados.
    """

    def __init__(
        self,
        doc_intel_adapter: DocumentIntelligenceAdapter,
        openai_adapter: AzureOpenAIAdapter,
        rest_api_adapter: RestApiAdapter,
        blob_storage_adapter: BlobStorageAdapter,  # Inyecta el adaptador de Blob Storage
    ):
        """
        Inicializa el caso de uso con los adaptadores necesarios.
        """
        self.doc_intel_adapter = doc_intel_adapter
        self.openai_adapter = openai_adapter
        self.rest_api_adapter = rest_api_adapter
        self.blob_storage_adapter = blob_storage_adapter  # Guarda el adaptador de Blob Storage

    def execute(self, blob_name: str, file_stream: BinaryIO) -> None:
        """
        Ejecuta el flujo principal de procesamiento del CV.
        """
        log_prefix = f"[{FUNCTION_PROCESS_TYPE}]"
        logging.info(f"{log_prefix} --- Iniciando procesamiento para: {blob_name} ---")

        rank_id: Optional[str] = None
        candidate_id: Optional[str] = None
        resumen_data: Optional[dict] = None
        extracted_text: Optional[str] = None
        analysis_result_str: Optional[str] = None
        processed_successfully = False

        try:
            # --- 0. Inicialización Temprana (IDs) ---
            rank_id = get_id_rank(blob_name)
            candidate_id = get_id_candidate(blob_name)

            if not rank_id or not candidate_id:
                raise ValueError(
                    f"{log_prefix} - No se pudieron extraer rank_id o candidate_id del nombre de archivo: {blob_name}"
                )

            # --- 2. Obtener Resumen de API Externa ---
            resumen_data = self.rest_api_adapter.get_resumen(id=rank_id)
            profile_description = resumen_data.get("profileDescription")
            variables_content = resumen_data.get("variablesContent")

            if profile_description is None or variables_content is None:
                raise APIError(
                    f"{log_prefix} - Respuesta de get_resumen incompleta para RankID {rank_id}. Faltan 'profileDescription' o 'variablesContent'."
                )

            # --- 3. Extraer Texto con Document Intelligence ---
            extracted_text = self.doc_intel_adapter.analyze_cv(file_stream)
            if not extracted_text or not extracted_text.strip():
                raise NoContentExtractedError(
                    f"{log_prefix} - Document Intelligence no extrajo contenido o el contenido está vacío para {blob_name}."
                )

            # --- 4. Preparar y Llamar a Azure OpenAI ---
            system_prompt = prompt_system(
                profile=profile_description, criterios=variables_content
            )
            if not system_prompt:
                raise ValueError(f"{log_prefix} - El prompt generado para OpenAI está vacío.")
            if not extracted_text:
                extracted_text = (
                    "No se envio ningun contenido, debes retornar vacio."  # type: ignore
                )
            analysis_result_str = self.openai_adapter.get_completion(
                system_message=system_prompt, user_message=extracted_text
            )
            if not analysis_result_str:
                raise OpenAIError(
                    f"{log_prefix} - Azure OpenAI devolvió una respuesta vacía para {blob_name}."
                )

            # --- Inicio Bloque Post-OpenAI ---
            cv_score, cv_analysis, candidate_name = extract_and_validate_cv_data_from_json(
                analysis_result_str
            )

            if cv_score is None or cv_analysis is None or candidate_name is None:
                raise JSONValidationError(
                    f"Validación fallida o datos incompletos en JSON de OpenAI para {blob_name}."
                )

            # --- 6. Calcular Promedio ---
            promedio_scores = calculate_average_score_from_dict(cv_score)

            if promedio_scores is None:
                raise ValueError(
                    f"{log_prefix} - Cálculo del promedio de scores falló para {blob_name}."
                )

            # --- 8. Enviar Resultados a API REST Final ---
            self.rest_api_adapter.add_scores(candidate_id=candidate_id, scores=cv_score)

            self.rest_api_adapter.save_resumen(
                candidate_id=candidate_id,
                transcription=extracted_text,
                score=promedio_scores,
                analysis=cv_analysis,
                candidate_name=candidate_name,
            )

            self.rest_api_adapter.update_candidate(candidate_id=candidate_id, error_message=None)

            processed_successfully = True
            logging.info(f"{log_prefix} *** PROCESO COMPLETADO EXITOSAMENTE ***")

        except (
            ValueError,
            SecretNotFoundError,
            KeyVaultError,
            APIError,
            AuthenticationError,
            DocumentIntelligenceError,
            NoContentExtractedError,
            OpenAIError,
        ) as early_or_critical_error:
            error_details = f"{type(early_or_critical_error).__name__}: {early_or_critical_error}"
            self._handle_processing_error(
                blob_name=blob_name,
                error_reason=error_details,
                log_prefix=log_prefix,
                candidate_id=candidate_id,
            )

        except (JSONValidationError, TypeError, APIError, AuthenticationError) as post_openai_error:
            failed_step = "UnknownPostOpenAI"
            if isinstance(post_openai_error, (JSONValidationError, TypeError, ValueError)):
                failed_step = "ValidationOrCalculation"
            elif isinstance(post_openai_error, (APIError, AuthenticationError)):
                failed_step = "FinalAPISaveOrUpdate"

            error_details = f"{type(post_openai_error).__name__}: {post_openai_error}"
            logging.error(f"{log_prefix} Error en paso post-OpenAI '{failed_step}': {error_details}")
            self._save_intermediate_result_and_cleanup(
                blob_name=blob_name,
                rank_id=rank_id,
                candidate_id=candidate_id,
                openai_result_str=analysis_result_str,
                get_resumen_result=resumen_data,
                transcription=extracted_text,
                failed_step=failed_step,
                error_details=error_details,
                log_prefix=log_prefix,
            )

        except Exception as unexpected_error:
            error_details = f"{type(unexpected_error).__name__} - {unexpected_error}"
            logging.exception(f"{log_prefix} ¡Error Inesperado!")
            if analysis_result_str and resumen_data and extracted_text:
                self._save_intermediate_result_and_cleanup(
                    blob_name=blob_name,
                    rank_id=rank_id,
                    candidate_id=candidate_id,
                    openai_result_str=analysis_result_str,
                    get_resumen_result=resumen_data,
                    transcription=extracted_text,
                    failed_step="Unexpected",
                    error_details=error_details,
                    log_prefix=log_prefix,
                )
            else:
                self._handle_processing_error(
                    blob_name=blob_name,
                    error_reason=error_details,
                    log_prefix=log_prefix,
                    candidate_id=candidate_id,
                )

        finally:
            if processed_successfully:
                logging.info(f"{log_prefix} Proceso exitoso. Intentando borrar blob original final...")
                self.blob_storage_adapter.delete_blob(CANDIDATES_CONTAINER, blob_name)
            else:
                logging.warning(f"{log_prefix} El proceso no fue exitoso. La gestión del blob original debería haberse realizado en el bloque 'except' correspondiente.")
                try:
                    if self.blob_storage_adapter.blob_exists(CANDIDATES_CONTAINER, blob_name):
                        logging.error(f"{log_prefix} ¡ALERTA! El blob original '{CANDIDATES_CONTAINER}/{blob_name}' todavía existe después de un fallo. La lógica de manejo de errores puede tener un problema.")
                except Exception as check_err:
                    logging.error(f"{log_prefix} Error al verificar existencia del blob original después de fallo: {check_err}")
            logging.info(f"{log_prefix} --- Finalizando procesamiento para: {blob_name} ---")

    def _handle_processing_error(
        self,
        blob_name: str,
        error_reason: str,
        log_prefix: str,
        candidate_id: Optional[str] = None,
    ):
        """
        Maneja errores críticos moviendo el blob a un contenedor de error y actualizando la API.
        """
        logging.error(f"{log_prefix} Error Crítico: {error_reason}. Iniciando manejo de error...")
        if self.rest_api_adapter and candidate_id:
            try:
                logging.info(f"{log_prefix} Intentando actualizar estado de error en API para candidate_id: {candidate_id}...")
                self.rest_api_adapter.update_candidate(
                    candidate_id=candidate_id, error_message=error_reason[:1000]
                )
                logging.info(f"{log_prefix} Estado de error actualizado en API.")
            except Exception as api_err:
                logging.error(f"{log_prefix} FALLO al actualizar estado de error en API: {api_err}", exc_info=True)
        elif candidate_id:
            logging.warning(f"{log_prefix} No se pudo actualizar API: rest_api_adapter no disponible.")
        else:
            logging.warning(f"{log_prefix} No se pudo actualizar API: candidate_id no disponible.")

        self.blob_storage_adapter.move_blob(CANDIDATES_CONTAINER, blob_name, MANUAL_ERROR_CONTAINER)

    def _save_intermediate_result_and_cleanup(
        self,
        blob_name: str,
        rank_id: str,
        candidate_id: str,
        openai_result_str: Optional[str],
        get_resumen_result: Optional[dict],
        transcription: Optional[str],
        failed_step: str,
        error_details: str,
        log_prefix: str,
    ):
        """
        Guarda resultados intermedios en caso de error post-OpenAI y limpia el blob original.
        """
        logging.warning(f"{log_prefix} Error post-OpenAI en paso '{failed_step}'. Guardando resultado intermedio...")

        result_filename = f"{rank_id}_{candidate_id}_partial_result_{failed_step}.json"

        intermediate_data = {
            "rank_id": rank_id,
            "candidate_id": candidate_id,
            "get_resumen_result": get_resumen_result,
            "document_intelligence_transcription": transcription,
            "azure_openai_raw_result": openai_result_str,
            "failure_info": {"failed_step": failed_step, "error_details": error_details},
        }
        intermediate_json = json.dumps(intermediate_data, indent=2, ensure_ascii=False)
        metadata = {
            "original_filename": blob_name,
            "rank_id": rank_id,
            "candidate_id": candidate_id,
            "failed_step": failed_step,
            "error_details_summary": error_details[:250],
        }

        try:
            logging.info(f"{log_prefix} Guardando resultado intermedio en '{RESULTS_POST_OPENAI_CONTAINER}/{result_filename}'...")
            self.blob_storage_adapter.upload_blob(
                RESULTS_POST_OPENAI_CONTAINER, result_filename, intermediate_json, metadata=metadata
            )
            logging.info(f"{log_prefix} Resultado intermedio guardado exitosamente.")
        except Exception as e:
            logging.exception(
                f"{log_prefix} CRITICAL ERROR al intentar guardar resultado intermedio en '{RESULTS_POST_OPENAI_CONTAINER}': {e}"
            )
            return

        if self.rest_api_adapter and candidate_id:
            try:
                logging.info(f"{log_prefix} Intentando actualizar estado de error (post-OpenAI) en API para candidate_id: {candidate_id}...")
                self.rest_api_adapter.update_candidate(
                    candidate_id=candidate_id, error_message=f"Error en {failed_step}: {error_details}"[:1000]
                )
                logging.info(f"{log_prefix} Estado de error (post-OpenAI) actualizado en API.")
            except Exception as api_err:
                logging.error(f"{log_prefix} FALLO al actualizar estado de error (post-OpenAI) en API: {api_err}", exc_info=True)
        self.blob_storage_adapter.delete_blob(CANDIDATES_CONTAINER, blob_name)
```

**5. `src/infrastructure/api_rest/api_rest_adapter.py` (Sin Cambios)**

Adaptador para interactuar con la API REST. (No Requiere Cambios)

**6. `src/infrastructure/key_vault/key_vault_client.py` (Sin Cambios)**

Cliente para interactuar con Azure Key Vault y obtener secretos. (No Requiere Cambios)

**7. `src/infrastructure/ocr/document_intelligence_adapter.py` (Sin Cambios)**

Adaptador para interactuar con Azure AI Document Intelligence. (No Requiere Cambios)

**8. `src/infrastructure/ocr/azure_openai_adapter.py` (Sin Cambios)**

Adaptador para interactuar con el servicio Azure OpenAI. (No Requiere Cambios)

**9. `src/interfaces/api_rest_repository_interface.py` (Sin Cambios)**

Interfaz que define las operaciones básicas que debe implementar un repositorio de API REST. (No Requiere Cambios)

**10. `src/infrastructure/storage/blob_storage_adapter.py`**

````python
# src/infrastructure/storage/blob_storage_adapter.py
import logging
import os
from azure.storage.blob import BlobServiceClient, ContentSettings
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError
from src.interfaces.blob_storage_interface import BlobStorageInterface

class BlobStorageAdapter(BlobStorageInterface):
    """Adaptador para interactuar con Azure Blob Storage."""

    def __init__(self, connection_string: str):
        """
        Inicializa el adaptador con la cadena de conexión a Azure Blob Storage.
        """
        self.connection_string = connection_string
        try:
            self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
        except Exception as e:
            logging.error(f"Error al inicializar BlobServiceClient: {e}")
            raise

    def _get_blob_client(self, container_name: str, blob_name: str):
        """Obtiene un cliente de blob y crea el contenedor si no existe."""
        try:
            container_client = self.blob_service_client.get_container_client(container_name)
            if not container_client.exists():
                logging.warning(f"Contenedor '{container_name}' no encontrado, intentando crear.")
                try:
                    container_client.create_container()
                    logging.info(f"Contenedor '{container_name}' creado.")
                except HttpResponseError as e:
                    if e.status_code == 409:  # Conflict - ya existe (carrera condición)
                        logging.info(f"Contenedor '{container_name}' ya existe (detectado después del check).")
                    else:
                        logging.error(f"Error al crear contenedor '{container_name}': {e}")
                        raise  # Relanzar si no es un conflicto esperado
        except Exception as e:
            logging.error(f"Error inesperado al obtener/crear cliente de contenedor '{container_name}': {e}")
            raise
        return container_client.get_blob_client(blob_name)

    def blob_exists(self, container_name: str, blob_name: str) -> bool:
        """Verifica si un blob existe en el contenedor."""
        blob_client = self._get_blob_client(container_name, blob_name)
        try:
            return blob_client.exists()
        except Exception as e:
            logging.error(f"Error al verificar la existencia del blob '{container_name}/{blob_name}': {e}")
            return False

    def upload_blob(self, container_name: str, blob_name: str, data: str, metadata: dict = None):
        """Sube un blob al contenedor."""
        try:
            blob_client = self._get_blob_client(container_name, blob_name)
            content_settings = ContentSettings(content_type="application/json", metadata=metadata)
            blob_client.upload_blob(data, overwrite=True, content_settings=content_settings)
            logging.info(f"Blob '{container_name}/{blob_name}' subido exitosamente.")
        except Exception as e:
            logging.error(f"Error al subir el blob '{container_name}/{blob_name}': {e}")
            raise

    def delete_blob(self, container_name: str, blob_name: str):
        """Elimina un blob del contenedor."""
        try:
            blob_client = self._get_blob_client(container_name, blob_name)
            blob_client.delete_blob(delete_snapshots="include")
            logging.info(f"Blob '{container_name}/{blob_name}' borrado exitosamente.")
        except ResourceNotFoundError:
            logging.warning(f"No se encontró el blob '{container_name}/{blob_name}' para borrar.")
        except Exception as e:
            logging.error(f"Error al borrar el blob '{container_name}/{blob_name}': {e}")
            raise

    def move_blob(self, source_container_name: str, source_blob_name: str, dest_container_name: str):
        """Mueve un blob de un contenedor a otro."""
        try:
            source_blob_client = self._get_blob_client(source_container_name, source_blob_name)
            dest_blob_client = self._get_blob_client(dest_container_name, source_blob_name)

            # Descargar el contenido del blob fuente
            blob_content = source_blob_client.download_blob().readall()

            # Subir el contenido al blob de destino
            dest_blob_client.upload_blob(blob_content, overwrite=True)

            # Eliminar el blob fuente
            source_blob_client.delete_blob()
            logging.info(f"Blob '{source_container_name}/{source_blob_name}' movido a '{dest_container_name}/{source_blob_name}' exitosamente.")

        except Exception as e:
            logging.error(f"Error al mover el blob '{source_container_name}/{source_blob_name}' a '{dest_container_name}/{source_blob_name}': {e}")
            raise

# 11. `src/interfaces/blob_storage_interface.py`
```python
# src/interfaces/blob_storage_interface.py
from abc import ABC, abstractmethod
from typing import Optional

class BlobStorageInterface(ABC):
    """
    Interfaz para la interacción con el servicio de almacenamiento de blobs.
    Define los métodos necesarios para la gestión de blobs, como la carga,
    eliminación y movimiento de archivos entre contenedores.
    """

    @abstractmethod
    def blob_exists(self, container_name: str, blob_name: str) -> bool:
        """
        Verifica si un blob existe en el contenedor especificado.

        Args:
            container_name (str): El nombre del contenedor.
            blob_name (str): El nombre del blob.

        Returns:
            bool: True si el blob existe, False en caso contrario.
        """
        raise NotImplementedError

    @abstractmethod
    def upload_blob(self, container_name: str, blob_name: str, data: str, metadata: Optional[dict] = None):
        """
        Sube un blob al contenedor especificado.

        Args:
            container_name (str): El nombre del contenedor.
            blob_name (str): El nombre del blob.
            data (str): Los datos a subir al blob.
            metadata (Optional[dict]): Metadatos opcionales para el blob.
        """
        raise NotImplementedError

    @abstractmethod
    def delete_blob(self, container_name: str, blob_name: str):
        """
        Elimina un blob del contenedor especificado.

        Args:
            container_name (str): El nombre del contenedor.
            blob_name (str): El nombre del blob.
        """
        raise NotImplementedError

    @abstractmethod
    def move_blob(self, source_container_name: str, source_blob_name: str, dest_container_name: str):
        """
        Mueve un blob de un contenedor a otro.

        Args:
            source_container_name (str): El nombre del contenedor de origen.
            source_blob_name (str): El nombre del blob de origen.
            dest_container_name (str): El nombre del contenedor de destino.
        """
        raise NotImplementedError
````

**12. `src/shared/extract_values.py` (Sin Cambios)**

Funciones auxiliares para extraer información de los nombres de archivo. (No Requiere Cambios)

**13. `src/shared/promedio_scores.py` (Sin Cambios)**

Función para calcular el promedio de los scores. (No Requiere Cambios)

**14. `src/shared/prompt_system.py` (Sin Cambios)**

Función para generar el prompt para el modelo de lenguaje. (No Requiere Cambios)

**15. `src/shared/validate_process_json.py` (Sin Cambios)**

Función para validar el JSON de respuesta del modelo de lenguaje. (No Requiere Cambios)

**16. `function_app.py`**

```python
# function_app.py
import logging
import os

import azure.functions as func

from src.domain.exceptions import KeyVaultError
from src.infrastructure.ocr.document_intelligence_adapter import DocumentIntelligenceAdapter
from src.infrastructure.openai.azure_openai_adapter import AzureOpenAIAdapter
from src.infrastructure.api_rest.api_rest_adapter import RestApiAdapter
from src.infrastructure.key_vault.key_vault_client import KeyVaultClient
from src.infrastructure.storage.blob_storage_adapter import BlobStorageAdapter
from src.domain.usecases.process_cv import ProcessCVUseCase

# --- Constantes ---
CONNECTION_STRING_ENV_VAR = "AzureWebJobsStorage"
KEY_VAULT_URI_ENV_VAR = "Vault"

# --- Nombres Secretos Key Vault ---
SECRET_NAMES = {
    "openai_api_key": "OpenAI--Key",
    "openai_endpoint": "OpenAI--URL",
    "openai_api_version": "OpenAI--ApiVersion",
    "openai_model": "OpenAI--Model",
    "openai_deployment": "OpenAI--Deployment",
    "docintel_api_key": "DocumentIntelligence--ApiKey",
    "docintel_endpoint": "DocumentIntelligence--URL",
    "rest_api_username": "Jwt--User",
    "rest_api_password": "Jwt--Password",
}

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)


def _initialize_adapters(kv_name: str) -> tuple[DocumentIntelligenceAdapter, AzureOpenAIAdapter, RestApiAdapter, BlobStorageAdapter]:
    """Inicializa todos los adaptadores obteniendo secretos de Key Vault."""
    if not kv_name:
        raise ValueError("KEY_VAULT_URI no está configurado en las variables de entorno.")

    kv_client = KeyVaultClient(kv_name)  # Pasar URI al constructor
    secrets = {}
    try:
        for key, secret_name in SECRET_NAMES.items():
            logging.debug(f"Obteniendo secreto: {secret_name} (para {key})")
            secret_value = kv_client.get_secret(secret_name)
            secrets[key] = secret_value

        # Instanciar adaptadores, pasando los secretos recuperados
        doc_intel_adapter = DocumentIntelligenceAdapter(
            api_key=secrets["docintel_api_key"], endpoint=secrets["docintel_endpoint"]
        )
        openai_adapter = AzureOpenAIAdapter(
            api_key=secrets["openai_api_key"],
            endpoint=secrets["openai_endpoint"],
            api_version=secrets["openai_api_version"],
            model=secrets["openai_model"],
            deployment=secrets["openai_deployment"],
        )
        rest_api_adapter = RestApiAdapter(
            username=secrets["rest_api_username"], password=secrets["rest_api_password"]
        )
        # Inicializa el adaptador de Blob Storage
        storage_connection_string = os.environ.get(CONNECTION_STRING_ENV_VAR)
        if not storage_connection_string:
            raise ValueError(
                f"Variable de entorno '{CONNECTION_STRING_ENV_VAR}' no encontrada."
            )
        blob_storage_adapter = BlobStorageAdapter(storage_connection_string)

        return doc_intel_adapter, openai_adapter, rest_api_adapter, blob_storage_adapter

    except Exception as e:
        logging.critical(f"CRÍTICO: Falló la inicialización de adaptadores: {e}", exc_info=True)
        raise KeyVaultError(f"Error al inicializar adaptadores: {e}") from e


@app.blob_trigger(arg_name="inputblob", path="candidates/{name}", connection="AzureWebJobsStorage")
def process_candidate_cv(inputblob: func.InputStream):
    """
    Procesa un CV desde el contenedor 'candidates'.
    """
    try:
        # --- 1. Inicializar Adaptadores (usando Key Vault) ---
        kv_name = os.environ.get(KEY_VAULT_URI_ENV_VAR)
        (
            doc_intel_adapter,
            openai_adapter,
            rest_api_adapter,
            blob_storage_adapter,
        ) = _initialize_adapters(kv_name)

        # --- 2. Inicializar Caso de Uso ---
        process_cv_use_case = ProcessCVUseCase(
            doc_intel_adapter=doc_intel_adapter,
            openai_adapter=openai_adapter,
            rest_api_adapter=rest_api_adapter,
            blob_storage_adapter=blob_storage_adapter,
        )

        # --- 3. Ejecutar Caso de Uso ---
        process_cv_use_case.execute(blob_name=inputblob.name, file_stream=inputblob)

    except Exception as e:
        logging.critical(f"Error general en la función: {e}", exc_info=True)
```
