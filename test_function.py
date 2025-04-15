import requests
import os # Para obtener variables si las tienes

# --- Configuración ---
function_url = "http://localhost:7071/api/upload-cv"
# Intenta obtener la llave desde variable de entorno o pégala directamente
api_key = os.getenv("FUNC_IARC_UPLOAD_KEY")
file_path = "./data/cvs/518e3052-ad83-4210-82d0-640c6437a4c7_f754f74a-7160-4443-a282-cd56aa66fb3a.pdf"
file_name = os.path.basename(file_path)

# --- Preparar la solicitud ---
headers = {
    "x-functions-key": api_key
    # requests se encarga del Content-Type para multipart/form-data
}

try:
    with open(file_path, 'rb') as f:
        files = {
            'file': (file_name, f, 'application/pdf') # 'file' es la clave esperada por la función
        }
        print(f"Enviando {file_name} a {function_url}...")
        response = requests.post(function_url, headers=headers, files=files, timeout=60) # Timeout de 60s

    # --- Imprimir resultado ---
    print(f"Status Code: {response.status_code}")
    print(f"Response Body: {response.text}")

    response.raise_for_status() # Lanza excepción para errores HTTP (4xx o 5xx)
    print("¡Archivo cargado exitosamente!")

except FileNotFoundError:
    print(f"Error: El archivo no se encontró en '{file_path}'")
except requests.exceptions.RequestException as e:
    print(f"Error durante la solicitud HTTP: {e}")
except Exception as e:
    print(f"Ocurrió un error inesperado: {e}")