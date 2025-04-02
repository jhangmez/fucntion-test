import os
import logging
import json
from dotenv import load_dotenv

# Configura el logging básico
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Carga las variables de entorno ---
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

# --- Importar SDK de Azure ---
try:
    from azure.storage.blob import BlobServiceClient
    from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError, ResourceNotFoundError
except ImportError as e:
    logging.error(f"Error importing Azure Storage Blob library: {e}")
    logging.error("Please ensure 'azure-storage-blob' is installed (`pip install azure-storage-blob`).")
    exit(1)

# --- Constantes para los contenedores ---
CANDIDATES_CONTAINER = "candidates"
RESULTADO_CONTAINER = "resultado"

def list_container_content(blob_service_client: BlobServiceClient, container_name: str):
    """Intenta listar el contenido de un contenedor específico."""
    print(f"\n--- Content of Container: '{container_name}' ---")
    try:
        container_client = blob_service_client.get_container_client(container_name)
        blob_list = container_client.list_blobs()
        count = 0
        for blob in blob_list:
            print(f"- {blob.name} (Size: {blob.size} bytes, Last Modified: {blob.last_modified})")
            count += 1

        if count == 0:
            print("(Container is empty or no blobs found)")
        else:
            print(f"Total blobs found: {count}")

    except ResourceNotFoundError:
        logging.warning(f"Container '{container_name}' not found.")
        print(f"Container '{container_name}' does not exist.")
    except ClientAuthenticationError:
         # Esto es menos probable si la conexión inicial funcionó, pero por si acaso
        logging.error(f"Authentication error while accessing container '{container_name}'.")
        print(f"Authentication error when trying to list blobs in '{container_name}'.")
    except Exception as e:
        logging.exception(f"An unexpected error occurred listing blobs in '{container_name}': {e}")
        print(f"Error listing blobs in '{container_name}': {e}")
    print("--------------------------------------")


def test_blob_storage_connection_and_content(): # Nombre de función actualizado
    """
    Prueba la conexión a Azure Blob Storage, lista contenedores,
    y lista el contenido de 'candidates' y 'resultado'.
    """
    logging.info("Attempting to connect to Azure Blob Storage and list specific containers...")

    try:
        # --- 1. Obtener la Cadena de Conexión ---
        connect_str = os.getenv("AzureWebJobsStorage")
        if not connect_str:
            raise ValueError("'AzureWebJobsStorage' environment variable not found or is empty.")
        logging.info("Using connection string from 'AzureWebJobsStorage'.")

        # --- 2. Crear el BlobServiceClient ---
        blob_service_client = BlobServiceClient.from_connection_string(connect_str)
        logging.info("BlobServiceClient created successfully.")

        # --- 3. Listar Todos los Contenedores (Opcional, pero bueno para confirmar conexión) ---
        logging.info("Attempting to list all containers...")
        print("\n--- Available Containers (Initial Check) ---")
        try:
            containers = blob_service_client.list_containers()
            container_list = [c['name'] for c in containers]
            if container_list:
                for container_name in container_list:
                    print(f"- {container_name}")
            else:
                print("(No containers found)")
        except Exception as e:
             print(f"Error listing all containers: {e}")
        print("------------------------------------------")


        # --- 4. Listar Contenido de 'candidates' ---
        list_container_content(blob_service_client, CANDIDATES_CONTAINER)

        # --- 5. Listar Contenido de 'resultado' ---
        list_container_content(blob_service_client, RESULTADO_CONTAINER)

        print("\nBlob Storage connection and specific container listing test finished.")

    except ValueError as e:
        logging.error(f"Configuration Error: {e}")
        print(f"\nERROR: Configuration error - {e}\n")
    except ClientAuthenticationError as e:
        logging.error(f"Authentication Error: Invalid connection string or key. {e}")
        print("\nERROR: Authentication failed. Check the 'AzureWebJobsStorage' connection string (Account Name and Key).\n")
    except ServiceRequestError as e:
        logging.error(f"Connection Error: Could not connect to the storage endpoint. {e}")
        print("\nERROR: Connection failed. Check network connectivity and the storage endpoint URL in the connection string.\n")
    except ImportError:
         logging.error("Import Error: 'azure-storage-blob' library not found.")
         print("\nERROR: Required library 'azure-storage-blob' is not installed.\n")
    except Exception as e:
        logging.exception("An unexpected error occurred during the Blob Storage test:")
        print(f"\nERROR: An unexpected error occurred.\nDetails: {e}\n")

if __name__ == "__main__":
    test_blob_storage_connection_and_content() # Llama a la nueva función