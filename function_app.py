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
    from src.shared.validate_process_json import extract_and_validate_cv_data_from_json
except ImportError as e:
    logging.critical(f"CRÍTICO: Falló la importación de módulos de la aplicación durante el inicio: {e}. Verifique los archivos __init__.py y las dependencias.")
    class DocumentIntelligenceAdapter: pass
    class DocumentIntelligenceError(Exception): pass
    class NoContentExtractedError(DocumentIntelligenceError): pass
    class AzureOpenAIAdapter: pass
    class OpenAIError(Exception): pass
    def prompt_system(profile, criterios, cv_candidato, current_date=None): return ""
    def extract_and_validate_cv_data_from_json(json_string: str): return None, None, None


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
    Función de Azure activada por un blob en el contenedor "Candidatos".
    Extrae texto (DI), analiza (OpenAI), valida los datos y guarda el resultado en "Resultado".
    Mueve el blob original en caso de error y lo elimina en caso de éxito.
    """
    if not inputblob or not inputblob.name:
        logging.error("El disparador de blob se invocó sin un blob de entrada o un nombre válido.")
        return

    blob_full_path = inputblob.name
    file_name = os.path.basename(blob_full_path)

    logging.info(f"--- Comenzó el procesamiento del blob: {blob_full_path} ---")
    logging.info(f"Nombre del archivo: {file_name}, Tamaño: {inputblob.length} Bytes")

    blob_service_client = None # Inicializar fuera del try para usar en finally
    processed_successfully = False # Flag para controlar el borrado final

    try:
        # Obtener cadena de conexión
        storage_connection_string = os.environ[CONNECTION_STRING_ENV_VAR]
        if not storage_connection_string:
             raise ValueError(f"La variable de entorno '{CONNECTION_STRING_ENV_VAR}' no existe.")

        # Crear clientes y adaptadores
        blob_service_client = BlobServiceClient.from_connection_string(storage_connection_string)
        doc_intel_adapter = DocumentIntelligenceAdapter()
        openai_adapter = AzureOpenAIAdapter()
        output_container_client = blob_service_client.get_container_client(OUTPUT_CONTAINER_NAME)
        logging.info(f"[{file_name}] Adaptadores y clientes inicializados correctamente.")

    except (ValueError, ImportError, KeyError) as e:
        logging.exception(f"[{file_name}] CRÍTICO: Falló la inicialización de adaptadores/clientes. ¿Error de configuración?: {e}")
        # No se puede continuar ni mover el archivo si falla la inicialización básica
        return
    except Exception as e:
        logging.exception(f"[{file_name}] CRÍTICO: Error inesperado durante la inicialización: {e}")
        return

    try:
        # Paso 1: Extraer texto con Document Intelligence
        logging.info(f"[{file_name}] Llamando a Document Intelligence...")
        extracted_text = doc_intel_adapter.analyze_cv(inputblob)
        logging.info(f"[{file_name}] Document Intelligence finalizó. Se extrajeron {len(extracted_text)} caracteres.")

        # Paso 2: Preparar y llamar a Azure OpenAI
        logging.info(f"[{file_name}] Generando prompt de OpenAI...")
        system_prompt = prompt_system(
            profile=TARGET_PROFILE,
            criterios=EVALUATION_CRITERIA,
            cv_candidato=extracted_text
        )
        logging.info(f"[{file_name}] Llamando a Azure OpenAI...")
        analysis_result = openai_adapter.get_completion(system_message=system_prompt, user_message="")
        logging.info(f"[{file_name}] Azure OpenAI finalizó.")

        # Paso 3: Validar la respuesta de OpenAI
        logging.info(f"[{file_name}] Validando el resultado de Azure OpenAI...")
        try:
            cv_score, cv_analysis, candidate_name = extract_and_validate_cv_data_from_json(analysis_result)
            logging.info(f"[{file_name}] Resultado de la validación: cv_score={cv_score is not None}, cv_analysis={cv_analysis is not None}, candidate_name={candidate_name is not None}")
        except (json.JSONDecodeError, TypeError) as e:
            logging.error(f"[{file_name}] Error al decodificar o validar el JSON de OpenAI: {e}", exc_info=True)
            raise OpenAIError(f"Error al decodificar o validar el JSON de OpenAI: {e}")  # Raise para mover el blob a error

        # Paso 4: Crear el diccionario con los resultados validados
        final_result = {
            "cvScore": cv_score,
            "cvAnalysis": cv_analysis,
            "nameCandidate": candidate_name
        }

        # Paso 5: Guardar resultado final en 'resultado'
        output_filename = f"analysis_{os.path.splitext(file_name)[0]}.json"
        output_blob_client = output_container_client.get_blob_client(output_filename)
        logging.info(f"[{file_name}] Guardando el análisis final en '{OUTPUT_CONTAINER_NAME}/{output_filename}'...")
        output_blob_client.upload_blob(
            json.dumps(final_result, ensure_ascii=False, indent=4).encode('utf-8'),  # Convertir a JSON y codificar
            overwrite=True,
            content_settings=ContentSettings(content_type='application/json; charset=utf-8')
        )
        logging.info(f"[{file_name}] El análisis final se guardó correctamente.")
        processed_successfully = True

    # --- Manejo de Errores ---
    except NoContentExtractedError as e:
        logging.warning(f"[{file_name}] Document Intelligence no extrajo contenido: {e}")
        move_blob_to_folder(blob_service_client, CANDIDATES_CONTAINER, file_name, "error/no_content")
    except DocumentIntelligenceError as e:
        logging.error(f"[{file_name}] Error durante el análisis de Document Intelligence: {e}", exc_info=True)
        move_blob_to_folder(blob_service_client, CANDIDATES_CONTAINER, file_name, "error/document_intelligence")
    except OpenAIError as e:
        logging.error(f"[{file_name}] Error durante el análisis o la validación de Azure OpenAI: {e}", exc_info=True)
        move_blob_to_folder(blob_service_client, CANDIDATES_CONTAINER, file_name, "error/openai")
    except (OSError, HttpResponseError, Exception) as e:
         # Captura errores al guardar el resultado final u otros errores inesperados
         logging.exception(f"[{file_name}] Error al guardar el resultado final u otro error inesperado durante el procesamiento: {e}")
         # Mover a una carpeta genérica de error de procesamiento si no es de DI u OpenAI
         move_blob_to_folder(blob_service_client, CANDIDATES_CONTAINER, file_name, "error/processing")
    # Nota: No necesitamos un except para Exception general aquí si el anterior lo captura

    finally:
        if processed_successfully:
            logging.info(f"[{file_name}] El proceso se completó correctamente. Intentando borrar el blob original.")
            try:
                source_blob_client = blob_service_client.get_blob_client(CANDIDATES_CONTAINER, file_name)
                source_blob_client.delete_blob(delete_snapshots="include")
                logging.info(f"[{file_name}] Blob original '{CANDIDATES_CONTAINER}/{file_name}' borrado correctamente.")
            except ResourceNotFoundError:
                 logging.warning(f"[{file_name}] No se encontró el blob original para borrar (podría haberse movido debido a un error anterior o ya se ha borrado).")
            except Exception as e:
                 logging.error(f"[{file_name}] No se pudo borrar el blob original '{CANDIDATES_CONTAINER}/{file_name}' después de un procesamiento exitoso: {e}")
        else:
            # Si no fue exitoso, el archivo ya debería haber sido movido por un bloque except
            logging.warning(f"[{file_name}] El proceso no se completó correctamente. El blob original debería estar en una carpeta de error.")

        logging.info(f"--- Finalizó el procesamiento del blob: {blob_full_path} ---")


def move_blob_to_folder(blob_service_client: BlobServiceClient, source_container: str, blob_name: str, error_folder: str):
    """Copia un blob a una 'carpeta' de error dentro del mismo contenedor y lo elimina del origen."""
    if not blob_service_client:
         logging.error(f"[{blob_name}] No se puede mover el blob a la carpeta de error porque BlobServiceClient no está inicializado.")
         return

    source_blob_url = f"{blob_service_client.url}{source_container}/{blob_name}"
    destination_blob_name = f"{error_folder}/{blob_name}" # Destino dentro del mismo contenedor

    try:
        destination_blob_client = blob_service_client.get_blob_client(source_container, destination_blob_name)
        source_blob_client = blob_service_client.get_blob_client(source_container, blob_name)

        logging.info(f"[{blob_name}] Intentando mover a la carpeta '{error_folder}' dentro de '{source_container}'...")

        # Verificar si el origen existe
        try:
            source_props = source_blob_client.get_blob_properties()
            logging.info(f"[{blob_name}] Se encontró el blob de origen. Iniciando la copia a la carpeta de error...")
        except ResourceNotFoundError:
             logging.warning(f"[{blob_name}] No se encontró el blob de origen '{source_container}/{blob_name}'. No se puede mover a la carpeta de error.")
             return

        # Iniciar copia
        copy_job = destination_blob_client.start_copy_from_url(source_blob_url)

        # Esperar a que la copia termine (bucle de sondeo simple)
        copy_wait_seconds = 15
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
                  logging.warning(f"[{blob_name}] No se encontraron las propiedades de copia para '{destination_blob_name}'. Esperando...")
             time.sleep(copy_poll_interval)
             elapsed_time += copy_poll_interval
             logging.debug(f"[{blob_name}] El estado de la copia a la carpeta de error es '{copy_status}', esperando...")

        # Evaluar resultado de la copia y eliminar origen si tuvo éxito
        if copy_status == "success":
             logging.info(f"[{blob_name}] La copia a la carpeta de error '{error_folder}' fue exitosa. Borrando el original.")
             source_blob_client.delete_blob(delete_snapshots="include")
             logging.info(f"[{blob_name}] Blob original borrado después de moverlo a la carpeta de error.")
        else:
             logging.error(f"[{blob_name}] El estado de la copia a la carpeta de error '{error_folder}' es '{copy_status}' después de esperar. El blob original NO será borrado.")
             # Intentar abortar si quedó pendiente
             if props and props.copy and props.copy.id and copy_status == 'pending':
                  try:
                      destination_blob_client.abort_copy(props.copy.id)
                      logging.info(f"[{blob_name}] Se abortó la copia pendiente a la carpeta de error.")
                  except Exception as abort_ex:
                      logging.error(f"[{blob_name}] No se pudo abortar la copia a la carpeta de error: {abort_ex}")

    except ResourceNotFoundError:
         # Podría ocurrir si el blob se elimina mientras se intenta mover
         logging.warning(f"[{blob_name}] Recurso no encontrado durante la operación de movimiento a la carpeta de error.")
    except Exception as e:
        logging.exception(f"[{blob_name}] No se pudo mover el blob a la carpeta de error '{error_folder}': {e}")

@app.route(
    route="upload-cv",
    methods=[func.HttpMethod.POST],
    auth_level=func.AuthLevel.FUNCTION
)
def upload_cv_http_trigger(req: func.HttpRequest) -> func.HttpResponse:
    """
    Azure Function triggered by an HTTP POST request to upload a CV file (v2 model).
    Saves the file to the 'candidates' blob container.
    """
    logging.info('Función de disparador HTTP de Python procesó una solicitud para subir un CV.')

    file_content = None
    filename = None
    content_type = 'application/octet-stream'

    try:
        file_from_form = req.files.get('file')

        if file_from_form:
            filename = os.path.basename(file_from_form.filename) # Sanitizar
            file_content = file_from_form.read()
            content_type = file_from_form.mimetype or content_type # Obtener mimetype si está disponible
            logging.info(f"Recibido archivo '{filename}' a través de form-data ({len(file_content)} bytes), tipo: {content_type}")
        else:
            file_content = req.get_body()
            if not file_content:
                 return func.HttpResponse(
                       "Por favor, pase un archivo en el cuerpo de la solicitud o como form-data con la clave 'file'.",
                       status_code=400
                 )
            # Intentar obtener nombre de header o usar default
            filename = os.path.basename(req.headers.get('X-Filename', 'uploaded_cv.pdf')) # Sanitizar
            content_type = req.headers.get('Content-Type', content_type)
            logging.info(f"Recibido archivo '{filename}' a través del cuerpo de la solicitud ({len(file_content)} bytes), tipo: {content_type}")

        if not filename:
             filename = "default_uploaded_cv.pdf"
             logging.warning("No se pudo determinar el nombre del archivo, usando el nombre por defecto.")

        try:
            connection_string = os.environ[CONNECTION_STRING_ENV_VAR]
            blob_service_client = BlobServiceClient.from_connection_string(connection_string)
            blob_client = blob_service_client.get_blob_client(container=CANDIDATES_CONTAINER, blob=filename)

            blob_content_settings = ContentSettings(content_type=content_type)

            logging.info(f"Subiendo '{filename}' al contenedor '{CANDIDATES_CONTAINER}' con content_settings: {blob_content_settings}")

            blob_client.upload_blob(
                file_content,
                overwrite=True,
                content_settings=blob_content_settings
            )

            logging.info(f"Subido exitosamente '{filename}'. El disparador de blob lo procesará.")

            return func.HttpResponse(
                f"Archivo '{filename}' subido exitosamente a '{CANDIDATES_CONTAINER}'. Será procesado en breve.",
                status_code=200
            )

        except KeyError:
             logging.exception(f"Variable de entorno '{CONNECTION_STRING_ENV_VAR}' no encontrada.")
             return func.HttpResponse("Error de configuración del servidor (falta la conexión de almacenamiento).", status_code=500)
        except Exception as e:
            logging.exception(f"Error al subir el archivo '{filename}' al almacenamiento de blobs: {e}")
            return func.HttpResponse(f"Error al guardar el archivo en el almacenamiento: {e}", status_code=500)

    except Exception as e:
         logging.exception("Error inesperado al procesar la solicitud de carga HTTP.")
         return func.HttpResponse("Ocurrió un error interno del servidor durante el procesamiento de la carga.", status_code=500)