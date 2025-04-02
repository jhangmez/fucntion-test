import os 

import logging 

import json 

from dotenv import load_dotenv 

 

# Configura el logging básico 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s') 

 

# --- Carga las variables de entorno --- 

# (Misma lógica que en test_blob_connection.py - ¡Verificada!) 

env_loaded = load_dotenv(".env") 

if not env_loaded: 

    logging.info("'.env' file not found or empty, attempting to load from 'local.settings.json'") 

    if os.path.exists("local.settings.json"): 

        try: 

            with open("local.settings.json", "r") as f: 

                settings = json.load(f) 

                if "Values" in settings: 

                    for key, value in settings["Values"].items(): 

                        os.environ[key] = value 

                    logging.info("Loaded environment variables from 'local.settings.json'") 

                else: 

                    logging.warning("'Values' section not found in 'local.settings.json'") 

        except json.JSONDecodeError: 

            logging.error("Error parsing 'local.settings.json'. Make sure it's valid JSON.") 

        except Exception as e: 

            logging.error(f"An error occurred loading settings from 'local.settings.json': {e}") 

    else: 

        logging.warning("'local.settings.json' not found. Environment variables might not be set.") 

 

 

# --- Importa DESPUÉS de cargar las variables --- 

try: 

    # Importa desde la ubicación correcta en shared/utils.py 

    from src.infrastructure.ocr.document_intelligence_adapter import DocumentIntelligenceAdapter 

    from src.domain.exceptions import DocumentIntelligenceError, NoContentExtractedError, FileProcessingError 

    from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError 

except ImportError as e: 

    logging.error(f"Error importing necessary modules: {e}") 

    logging.error("Ensure project structure is correct, src is importable, and required libraries are installed.") 

    exit(1) 

 

 

def test_document_intelligence(): # Nombre corregido 

    """Prueba el adaptador de Document Intelligence y guarda el resultado en un archivo txt.""" 

 

    pdf_path = "./data/cvs/Camilo_Ospina.pdf" # Asegúrate que este archivo exista 

    logging.info(f"Attempting to process PDF: {pdf_path}") 

 

    # --- Verifica variables de entorno necesarias ANTES de instanciar --- 

    di_endpoint = os.getenv("DOCUMENT_INTELLIGENCE_ENDPOINT") 

    di_key = os.getenv("DOCUMENT_INTELLIGENCE_API_KEY") 

    if not di_endpoint or not di_key: 

        logging.error("Missing DOCUMENT_INTELLIGENCE_ENDPOINT or DOCUMENT_INTELLIGENCE_API_KEY environment variables.") 

        print("\nERROR: Missing required Document Intelligence environment variables. Check your .env or local.settings.json\n") 

        return # Salir si faltan variables críticas 

 

    # Verifica que el archivo PDF exista 

    if not os.path.exists(pdf_path): 

        logging.error(f"PDF file not found at path: {pdf_path}") 

        print(f"\nERROR: PDF file not found at path: {pdf_path}\n") 

        return 

 

    output_filename = "extracted_text_from_test.txt" # Nombre fijo para la salida de prueba 

 

    try: 

        # --- 1. Crear instancia del adaptador --- 

        logging.info("Instantiating DocumentIntelligenceAdapter...") 

        adapter = DocumentIntelligenceAdapter() 

        logging.info("Adapter instantiated.") 

 

        # --- 2. Abrir y analizar el PDF --- 

        logging.info(f"Opening PDF file: {pdf_path}") 

        with open(pdf_path, "rb") as f: 

            logging.info("Calling adapter.analyze_cv()...") 

            extracted_text = adapter.analyze_cv(f) 

            logging.info("analyze_cv() completed.") 

 

        # --- 3. Guardar y Mostrar Resultado --- 

        if extracted_text: 

            logging.info(f"Extracted text successfully ({len(extracted_text)} characters).") 

            with open(output_filename, "w", encoding="utf-8") as output_file: 

                output_file.write(extracted_text) 

            print(f"\n--- Test Result ---") 

            print(f"Text successfully extracted and saved to: {output_filename}") 

            # Opcional: Imprimir una porción del texto 

            print(f"Beginning of extracted text:\n{extracted_text[:500]}...") 

            print("-------------------\n") 

        else: 

            # Esto no debería ocurrir si NoContentExtractedError se lanza correctamente 

            logging.warning("analyze_cv returned empty string, but did not raise NoContentExtractedError.") 

            print("\nWARNING: Text extraction returned empty, but no specific error was raised.\n") 

 

 

    # --- Manejo de Errores Específico --- 

    except (DocumentIntelligenceError, NoContentExtractedError) as e: 

        # Errores específicos de la lógica de Document Intelligence o su API 

        logging.error(f"Document Intelligence Error: {e}", exc_info=True) # exc_info=True añade la traza 

        print(f"\nERROR during Document Intelligence processing:\n{e}\n") 

    except FileProcessingError as e: 

        # Errores relacionados con el manejo de archivos (aunque menos probable aquí) 

        logging.error(f"File Processing Error: {e}", exc_info=True) 

        print(f"\nERROR related to file processing:\n{e}\n") 

    except ClientAuthenticationError as e: 

         # Error específico de autenticación con Azure 

         logging.error(f"Authentication Error with Azure: {e}", exc_info=True) 

         print(f"\nERROR: Authentication failed. Check Document Intelligence API Key or Endpoint.\nDetails: {e}\n") 

    except ServiceRequestError as e: 

         # Error específico de conexión/red con Azure 

         logging.error(f"Connection Error with Azure: {e}", exc_info=True) 

         print(f"\nERROR: Connection failed. Check network or Document Intelligence Endpoint URL.\nDetails: {e}\n") 

    except FileNotFoundError: 

        # Este error ya se verifica al principio, pero por si acaso 

        logging.error(f"PDF file not found during open: {pdf_path}") 

        print(f"\nERROR: PDF file seems to have disappeared: {pdf_path}\n") 

    except Exception as e: 

        # Captura cualquier otro error inesperado 

        logging.exception("An unexpected error occurred during the Document Intelligence test:") # Muestra traza 

        print(f"\nERROR: An unexpected error occurred.\nType: {type(e).__name__}\nDetails: {e}\n") 

 

if __name__ == "__main__": 

    test_document_intelligence() 