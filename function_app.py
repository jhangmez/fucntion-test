import logging
import os
import json
import time 
from typing import Optional

import azure.functions as func
from azure.storage.blob import BlobServiceClient,ContentSettings
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError

try:
    from src.infrastructure.ocr.document_intelligence_adapter import DocumentIntelligenceAdapter, DocumentIntelligenceError, NoContentExtractedError
    from src.infrastructure.openai.azure_openai_adapter import AzureOpenAIAdapter, OpenAIError
    from src.shared.prompt_system import prompt_system
    # Importa cualquier excepción personalizada de dominio que uses
    # from src.domain.exceptions import FileProcessingError
except ImportError as e:
    logging.critical(f"CRITICAL: Failed to import application modules during startup: {e}. Check __init__.py files and dependencies.")
    # Define clases dummy para permitir que el resto del archivo se analice si falla la importación
    class DocumentIntelligenceAdapter: pass
    class DocumentIntelligenceError(Exception): pass
    class NoContentExtractedError(DocumentIntelligenceError): pass
    class AzureOpenAIAdapter: pass
    class OpenAIError(Exception): pass
    def prompt_system(profile, criterios, cv_candidato, current_date=None): return ""
    # class FileProcessingError(Exception): pass


# Define la aplicación de funciones v2 GLOBALMENTE
app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

TARGET_PROFILE = "Data Scientist"
EVALUATION_CRITERIA = """
A. Años de experiencia total. 
- 5 o más años: asígnale 100% 
- 4 años: asígnale 75% 
- 3 años: asígnale 30% 
- Menos de 2 años: asígnale 0% 
 
B. Años de experiencia en Modelos Predictivos. 
- 5 o más años: asígnale 100% 
- 4 años: asígnale 75% 
- 3 años: asígnale 30% 
- Menos de 2 años: asígnale 0% 

C. Años de experiencia en MLops. 
- 3 o más años: asígnale 100% 
- 2 años: asígnale 75% 
- 1 año: asígnale 45% 
- Menos de 1 año: asígnale 0% 

D. Años de experiencia en la nube (AZURE, AWS, GCP) 
- Si tiene experiencia en Azure, GCP y AWS: asígnale 100% 
- Si tiene experiencia en Azure y AWS: asígnale 80% 
- Si solo tiene experiencia en Azure: asígnale 50% 
- Si no tiene experiencia en Azure: asígnale 0% 

E. Años de experiencia en bases de datos estructuradas. 
- 5 o más años: asígnale 100% 
- 4 años: asígnale 75% 
- 3 años: asígnale 30% 
- Menos de 2 años: asígnale 0% 

F. Años de experiencia en análisis de datos con Python. 
- 5 o más años: asígnale 100% 
- 4 años: asígnale 75% 
- 3 años: asígnale 30% 
- Menos de 2 años: asígnale 0% 

G. Años de experiencia en framework de procesamiento de datos Spark. 
- 3 o más años: asígnale 100% 
- 2 años: asígnale 75% 
- 1 año: asígnale 45% 
- Menos de 1 año: asígnale 0% 
"""
OUTPUT_CONTAINER_NAME = "resultado"
CONNECTION_STRING_ENV_VAR = "AzureWebJobsStorage"
CANDIDATES_CONTAINER = "candidates"


@app.blob_trigger(
    arg_name="inputblob",
    path="candidates/{name}",
    connection=CONNECTION_STRING_ENV_VAR
)
def process_candidate_cv(inputblob: func.InputStream):
    """
    Azure Function triggered by a blob in 'candidates' container.
    Extracts text (DI), analyzes (OpenAI), and saves result to 'resultado'.
    Moves original blob on error, deletes on success.
    """
    if not inputblob or not inputblob.name:
        logging.error("Blob trigger invoked without valid input blob or name.")
        return

    blob_full_path = inputblob.name # E.g., "candidates/cv_juan.pdf"
    file_name = os.path.basename(blob_full_path) # E.g., "cv_juan.pdf"

    logging.info(f"--- Processing started for blob: {blob_full_path} ---")
    logging.info(f"File Name: {file_name}, Size: {inputblob.length} Bytes")

    blob_service_client = None # Inicializar fuera del try para usar en finally
    processed_successfully = False # Flag para controlar el borrado final

    try:
        # Obtener cadena de conexión
        storage_connection_string = os.environ[CONNECTION_STRING_ENV_VAR]
        if not storage_connection_string:
             raise ValueError(f"Environment variable '{CONNECTION_STRING_ENV_VAR}' is missing.")

        # Crear clientes y adaptadores
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
        doc_intel_adapter = DocumentIntelligenceAdapter()
        openai_adapter = AzureOpenAIAdapter()
        output_container_client = blob_service_client.get_container_client(OUTPUT_CONTAINER_NAME)
        logging.info(f"[{file_name}] Adapters and clients initialized successfully.")

    except (ValueError, ImportError, KeyError) as e:
        logging.exception(f"[{file_name}] CRITICAL: Failed to initialize adapters/clients. Configuration error?: {e}")
        # No se puede continuar ni mover el archivo si falla la inicialización básica
        return
    except Exception as e:
        logging.exception(f"[{file_name}] CRITICAL: Unexpected error during initialization: {e}")
        return

    # --- Lógica de Procesamiento Principal ---
    try:
        # Paso 1: Extraer texto con Document Intelligence
        logging.info(f"[{file_name}] Calling Document Intelligence...")
        extracted_text = doc_intel_adapter.analyze_cv(inputblob)
        logging.info(f"[{file_name}] Document Intelligence finished. Extracted {len(extracted_text)} characters.")

        # Paso 2: Preparar y llamar a Azure OpenAI
        logging.info(f"[{file_name}] Generating OpenAI prompt...")
        system_prompt = prompt_system(
            profile=TARGET_PROFILE,
            criterios=EVALUATION_CRITERIA,
            cv_candidato=extracted_text
        )
        logging.info(f"[{file_name}] Calling Azure OpenAI...")
        analysis_result = openai_adapter.get_completion(system_message=system_prompt, user_message="")
        logging.info(f"[{file_name}] Azure OpenAI finished.")

        try:
            # Solo intentar cargar, no necesitamos el objeto parseado aquí
            json.loads(analysis_result)
            logging.info(f"[{file_name}] OpenAI result appears to be valid JSON.")
        except (json.JSONDecodeError, TypeError) as json_e:
            logging.error(f"[{file_name}] OpenAI result is NOT valid JSON or not a string: {json_e}. Result snippet: {str(analysis_result)[:500]}...")
            # Considerar esto un error de OpenAI
            raise OpenAIError(f"OpenAI did not return valid JSON. Snippet: {str(analysis_result)[:100]}")

        # Paso 4: Guardar resultado final en 'resultado'
        output_filename = f"analysis_{os.path.splitext(file_name)[0]}.json"
        output_blob_client = output_container_client.get_blob_client(output_filename)
        logging.info(f"[{file_name}] Saving final analysis to '{OUTPUT_CONTAINER_NAME}/{output_filename}'...")
        output_blob_client.upload_blob(
            analysis_result.encode('utf-8'),
            overwrite=True,
            content_settings=ContentSettings(content_type='application/json; charset=utf-8')
        )
        logging.info(f"[{file_name}] Final analysis successfully saved.")
        processed_successfully = True

    # --- Manejo de Errores ---
    except NoContentExtractedError as e:
        logging.warning(f"[{file_name}] No content extracted by Document Intelligence: {e}")
        move_blob_to_folder(blob_service_client, CANDIDATES_CONTAINER, file_name, "error/no_content")
    except DocumentIntelligenceError as e:
        logging.error(f"[{file_name}] Error during Document Intelligence analysis: {e}", exc_info=True)
        move_blob_to_folder(blob_service_client, CANDIDATES_CONTAINER, file_name, "error/document_intelligence")
    except OpenAIError as e:
        logging.error(f"[{file_name}] Error during Azure OpenAI analysis or validation: {e}", exc_info=True)
        move_blob_to_folder(blob_service_client, CANDIDATES_CONTAINER, file_name, "error/openai")
    except (OSError, HttpResponseError, Exception) as e:
         # Captura errores al guardar el resultado final u otros errores inesperados
         logging.exception(f"[{file_name}] Error saving final result or other unexpected error during processing: {e}")
         # Mover a una carpeta genérica de error de procesamiento si no es de DI u OpenAI
         move_blob_to_folder(blob_service_client, CANDIDATES_CONTAINER, file_name, "error/processing")
    # Nota: No necesitamos un except para Exception general aquí si el anterior lo captura

    # --- Limpieza Final ---
    finally:
        if processed_successfully:
            logging.info(f"[{file_name}] Process completed successfully. Attempting to delete original blob.")
            try:
                source_blob_client = blob_service_client.get_blob_client(CANDIDATES_CONTAINER, file_name)
                source_blob_client.delete_blob(delete_snapshots="include")
                logging.info(f"[{file_name}] Original blob '{CANDIDATES_CONTAINER}/{file_name}' deleted successfully.")
            except ResourceNotFoundError:
                 logging.warning(f"[{file_name}] Original blob not found for deletion (might have been moved due to prior error or already deleted).")
            except Exception as e:
                 logging.error(f"[{file_name}] Failed to delete original blob '{CANDIDATES_CONTAINER}/{file_name}' after successful processing: {e}")
        else:
            # Si no fue exitoso, el archivo ya debería haber sido movido por un bloque except
            logging.warning(f"[{file_name}] Process did not complete successfully. Original blob should be in an error folder.")

        logging.info(f"--- Processing finished for blob: {blob_full_path} ---")


def move_blob_to_folder(blob_service_client: BlobServiceClient, source_container: str, blob_name: str, error_folder: str):
    """Copia un blob a una 'carpeta' de error dentro del mismo contenedor y lo elimina del origen."""
    if not blob_service_client:
         logging.error(f"[{blob_name}] Cannot move blob to error folder because BlobServiceClient is not initialized.")
         return

    source_blob_url = f"{blob_service_client.url}{source_container}/{blob_name}"
    destination_blob_name = f"{error_folder}/{blob_name}" # Destino dentro del mismo contenedor

    try:
        destination_blob_client = blob_service_client.get_blob_client(source_container, destination_blob_name)
        source_blob_client = blob_service_client.get_blob_client(source_container, blob_name)

        logging.info(f"[{blob_name}] Attempting to move to '{error_folder}' folder within '{source_container}'...")

        # Verificar si el origen existe
        try:
            source_props = source_blob_client.get_blob_properties()
            logging.info(f"[{blob_name}] Source blob found. Starting copy to error folder...")
        except ResourceNotFoundError:
             logging.warning(f"[{blob_name}] Source blob '{source_container}/{blob_name}' not found. Cannot move to error folder.")
             return

        # Iniciar copia
        copy_job = destination_blob_client.start_copy_from_url(source_blob_url)

        # Esperar a que la copia termine (bucle de sondeo simple)
        copy_wait_seconds = 15 # Aumentar un poco el tiempo de espera
        copy_poll_interval = 1
        elapsed_time = 0
        copy_status = None
        props = None

        while elapsed_time < copy_wait_seconds:
             props = destination_blob_client.get_blob_properties()
             if props and props.copy:
                  copy_status = props.copy.status
                  if copy_status != "pending":
                      break
             else:
                  logging.warning(f"[{blob_name}] Copy properties not found for '{destination_blob_name}'. Waiting...")
             time.sleep(copy_poll_interval)
             elapsed_time += copy_poll_interval
             logging.debug(f"[{blob_name}] Copy status to error folder is '{copy_status}', waiting...")

        # Evaluar resultado de la copia y eliminar origen si tuvo éxito
        if copy_status == "success":
             logging.info(f"[{blob_name}] Copy to error folder '{error_folder}' successful. Deleting original.")
             source_blob_client.delete_blob(delete_snapshots="include")
             logging.info(f"[{blob_name}] Original blob deleted after moving to error folder.")
        else:
             logging.error(f"[{blob_name}] Copy status to error folder '{error_folder}' is '{copy_status}' after waiting. Original blob will NOT be deleted.")
             # Intentar abortar si quedó pendiente
             if props and props.copy and props.copy.id and copy_status == 'pending':
                  try:
                      destination_blob_client.abort_copy(props.copy.id)
                      logging.info(f"[{blob_name}] Aborted pending copy to error folder.")
                  except Exception as abort_ex:
                      logging.error(f"[{blob_name}] Failed to abort copy to error folder: {abort_ex}")

    except ResourceNotFoundError:
         # Podría ocurrir si el blob se elimina mientras se intenta mover
         logging.warning(f"[{blob_name}] Resource not found during move to error folder operation.")
    except Exception as e:
        logging.exception(f"[{blob_name}] Failed to move blob to error folder '{error_folder}': {e}")
