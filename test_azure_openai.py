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

    from src.infrastructure.openai.azure_openai_adapter import AzureOpenAIAdapter 

    from src.domain.exceptions import OpenAIError 

    # Importa excepciones específicas de OpenAI si necesitas más detalle 

    from openai import APIConnectionError, RateLimitError, AuthenticationError as OpenAIAuthError, APIStatusError 

except ImportError as e: 

    logging.error(f"Error importing necessary modules: {e}") 

    logging.error("Ensure project structure is correct, src is importable, and 'openai' library is installed.") 

    exit(1) 

 

def test_azure_openai(): 

    """Prueba la funcionalidad básica del adaptador de Azure OpenAI.""" 

    logging.info("Attempting to test Azure OpenAI Adapter...") 

 

    # --- Verifica variables de entorno necesarias ANTES de instanciar --- 

    openai_key = os.getenv("OPENAI_API_KEY") 

    openai_endpoint = os.getenv("OPENAI_ENDPOINT") 

    openai_api_version = os.getenv("OPENAI_API_VERSION") 

    openai_model = os.getenv("OPENAI_MODEL") 

 

    # --- ¡ALERTA SOBRE API VERSION! --- 

    if openai_api_version == "2024-10-21": 

        logging.warning("The configured OPENAI_API_VERSION '2024-10-21' looks like a future date. " 

                        "This is likely incorrect and will cause errors. Please use a valid GA or preview version (e.g., '2024-02-15-preview', '2023-05-15').") 

        print("\nWARNING: OPENAI_API_VERSION '2024-10-21' seems incorrect. Please verify!\n") 

        # Considera salir si la versión es claramente inválida: 

        # return 

 

    if not all([openai_key, openai_endpoint, openai_api_version, openai_model]): 

        missing_vars = [var for var, val in { 

            "OPENAI_API_KEY": openai_key, 

            "OPENAI_ENDPOINT": openai_endpoint, 

            "OPENAI_API_VERSION": openai_api_version, 

            "OPENAI_MODEL": openai_model 

        }.items() if not val] 

        logging.error(f"Missing required Azure OpenAI environment variables: {', '.join(missing_vars)}") 

        print(f"\nERROR: Missing required Azure OpenAI environment variables: {', '.join(missing_vars)}. Check your .env or local.settings.json\n") 

        return 

 

    try: 

        # --- 1. Crear instancia del adaptador --- 

        logging.info("Instantiating AzureOpenAIAdapter...") 

        adapter = AzureOpenAIAdapter() 

        logging.info("Adapter instantiated.") 

 

        # --- 2. Definir un prompt simple --- 

        system_message = "Eres un asistente útil y conciso." 

        user_message = "Escribeme 10 numeros fibonacci y luego escribe el lema del banco bcp." 

        logging.info(f"Using system message: '{system_message}'") 

        logging.info(f"Using user message: '{user_message}'") 

 

        # --- 3. Obtener la completación --- 

        logging.info("Calling adapter.get_completion()...") 

        completion = adapter.get_completion(system_message, user_message) 

        logging.info("get_completion() completed.") 

 

        # --- 4. Imprimir el Resultado --- 

        if completion: 

            logging.info("Successfully received completion from OpenAI.") 

            print("\n--- OpenAI Completion ---") 

            print(completion) 

            print("-------------------------\n") 

        else: 

            # Si el adaptador devuelve "" sin error (lo modificamos para lanzar error) 

            logging.warning("get_completion returned empty string without raising an error.") 

            print("\nWARNING: OpenAI completion was empty, but no specific error was raised.\n") 

 

        print("Azure OpenAI Adapter test successful!") 

 

    # --- Manejo de Errores Específico --- 

    except OpenAIError as e: # Captura tu excepción personalizada 

        logging.error(f"OpenAI Domain Error: {e}", exc_info=True) 

        # Intenta obtener más detalles de la causa original si está disponible 

        original_error = "" 

        if e.__cause__: 

            original_error = f" | Original Error: {type(e.__cause__).__name__}: {e.__cause__}" 

        print(f"\nERROR during OpenAI operation:\n{e}{original_error}\n") 

        # Podrías añadir manejo específico basado en e.__cause__ si lo necesitas 

        # if isinstance(e.__cause__, RateLimitError): 

        #    print("Rate limit likely exceeded.") 

        # elif isinstance(e.__cause__, OpenAIAuthError): 

        #    print("Authentication failed. Check OpenAI Key/Endpoint/Version.") 

        # elif isinstance(e.__cause__, APIConnectionError): 

        #     print("Connection error. Check network or OpenAI endpoint.") 

    except ValueError as e: 

        # Captura el error si faltan variables de entorno al crear el adaptador 

        logging.error(f"Configuration error: {e}") 

        print(f"\nERROR: Configuration error. Missing required environment variables for Azure OpenAI.\nDetails: {e}\n") 

    except Exception as e: 

        # Captura cualquier otro error inesperado 

        logging.exception("An unexp ected error occurred during the Azure OpenAI test:") # Muestra traza 

        print(f"\nERROR: An unexpected error occurred.\nType: {type(e).__name__}\nDetails: {e}\n") 

 

 

if __name__ == "__main__": 

    test_azure_openai() 