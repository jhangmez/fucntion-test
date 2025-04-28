¡Excelente! Entiendo perfectamente la situación. El `function_app.py` actual ha crecido demasiado y mezcla responsabilidades de orquestación, inicialización de infraestructura, lógica de negocio y manejo de errores de bajo nivel. Esto es un indicio clásico de que es necesario aplicar principios de diseño como Clean Architecture para separar las preocupaciones y mejorar la mantenibilidad.

Vamos a reestructurar tu código siguiendo el patrón que has propuesto, asegurando que la lógica central del procesamiento de CV se mueva a la capa de Dominio/Casos de Uso, dejando al `function_app.py` como una capa de entrada (Frameworks & Drivers) mucho más sencilla, responsable de la configuración, orquestación inicial y manejo de la respuesta/errores generales.

**Principios Clave de Clean Architecture Aplicados:**

1.  **Separación de Capas:**

    - **Dominio:** Contiene las entidades de negocio, las excepciones del dominio y los casos de uso. Es el corazón del sistema y es independiente de la infraestructura.
    - **Interfaces/Adaptadores (Ports):** Define las interfaces (contratos) que el Dominio y los Casos de Uso usarán para interactuar con capas externas (Infrastructure). El Dominio y los Casos de Uso _dependen_ de estas abstracciones.
    - **Infrastructure (Adapters):** Contiene las implementaciones concretas de las interfaces definidas en la capa de Interfaces/Adaptadores. Habla con el mundo exterior (API REST, Azure DI, Azure OpenAI, Key Vault, Blob Storage). Depende de las interfaces.
    - **Frameworks & Drivers (Entry Point):** En tu caso, el `function_app.py`. Es la capa más externa. Se encarga de inicializar la aplicación, configurar las dependencias (inyectando adaptadores concretos en los casos de uso que esperan interfaces), y llamar a los casos de uso en respuesta a un evento (el blob trigger). Maneja errores a nivel de aplicación.

2.  **Regla de Dependencia:** Las dependencias siempre fluyen hacia adentro. Las capas exteriores dependen de las capas interiores, pero las capas interiores NUNCA dependen de las capas exteriores. Esto significa que tus casos de uso en `domain/usecases` no importarán clases directamente desde `infrastructure`, sino que dependerán de las interfaces definidas en `interfaces`. El `function_app.py` (capa exterior) sí importará tanto las interfaces como los adaptadores concretos para realizar la inyección de dependencias.

**Nueva Estructura de Archivos:**

Ya me proporcionaste la estructura deseada, que se alinea perfectamente con Clean Architecture:

```
.
├── function_app.py          # Punto de entrada de la Azure Function (Frameworks & Drivers)
├── README.md                # Documentación del proyecto
├── requirements.txt         # Dependencias de Python
├── .env.example             # Ejemplo de archivo .env para configuración local
├── src
│   ├── domain               # Lógica de negocio, entidades, casos de uso (Dominio)
│   │   ├── entities           # Objetos de datos (DTOs)
│   │   │   └── api_credentials.py
│   │   ├── exceptions.py      # Excepciones personalizadas
│   │   └── usecases           # Interacciones o casos de uso del sistema (Aplicación/Casos de Uso)
│   │       ├── process_cv.py  # Proceso principal de análisis de CV
│   │       └── interfaces.py  # Interfaz del caso de uso (opcional para uno simple, pero bueno)
│   ├── infrastructure       # Adaptadores para interactuar con servicios externos (Infrastructure)
│   │   ├── api_rest           # Adaptador para la API REST
│   │   │   └── api_rest_adapter.py
│   │   ├── key_vault          # Adaptador para Azure Key Vault
│   │   │   └── key_vault_client.py
│   │   ├── ocr                # Adaptador para Document Intelligence y OpenAI
│   │   │   ├── document_intelligence_adapter.py
│   │   │   └── azure_openai_adapter.py
│   │   ├── storage            # Adaptador para Azure Blob Storage
│   │   │   └── blob_storage_adapter.py
│   ├── interfaces           # Definiciones de interfaces (abstracciones) (Interfaces/Adaptadores - Ports)
│   │   ├── api_rest_repository_interface.py
│   │   ├── blob_storage_interface.py # Nueva interfaz para el storage
│   │   ├── document_intelligence_interface.py # Nueva interfaz para DI
│   │   ├── openai_interface.py      # Nueva interfaz para OpenAI
│   │   └── key_vault_interface.py   # Nueva interfaz para Key Vault
│   ├── shared               # Código reutilizable (helpers, validaciones) (Shared/Utilities)
│   │   ├── extract_values.py
│   │   ├── promedio_scores.py
│   │   ├── prompt_system.py
│   │   └── validate_process_json.py
```

**Pasos de Refactorización:**

1.  **Crear Interfaces:** Definiremos las interfaces en `src/interfaces`.
2.  **Actualizar Adaptadores:** Haremos que los adaptadores existentes (`api_rest_adapter`, `key_vault_client`, `document_intelligence_adapter`, `azure_openai_adapter`) implementen sus respectivas interfaces y se aseguren de que solo importen desde `domain` o `shared`.
3.  **Crear Adaptador de Blob Storage:** Implementaremos `blob_storage_adapter.py`.
4.  **Crear Caso de Uso `ProcessCVUseCase`:** Moveremos la lógica de negocio central del procesamiento de CV a `src/domain/usecases/process_cv.py`. Este caso de uso aceptará las interfaces como dependencias en su constructor.
5.  **Simplificar `function_app.py`:** Adaptaremos `function_app.py` para que su responsabilidad sea mínima: obtener configuración, inicializar adaptadores concretos, inicializar el caso de uso con esos adaptadores y llamar al caso de uso, manejando las excepciones que este pueda lanzar.
6.  **Ajustar Manejo de Errores:** La lógica de error compleja (`_handle_processing_error`, `_save_intermediate_result_and_cleanup`) se eliminará de `function_app.py`. El caso de uso lanzará excepciones específicas del dominio. `function_app.py` atrapará estas excepciones y usará los adaptadores de Storage y API para realizar las acciones de reporte/movimiento de archivos.

**Consideración sobre la lógica de errores intermedios:**

La lógica actual de `_save_intermediate_result_and_cleanup` es un poco peculiar y mezcla la idea de guardar resultados intermedios con el manejo de errores. En un diseño Clean Architecture más puro, el caso de uso podría:

- Terminar exitosamente.
- Lanzar una excepción detallada (`JSONValidationError`, `APIError`, etc.).
  La capa externa (`function_app.py`) sería responsable de _reaccionar_ a esa excepción. La acción de "guardar resultado intermedio" podría ser una acción específica que `function_app.py` realice (usando el adaptador de Storage) si captura ciertas excepciones.

Para mantener la lógica lo más similar posible al original _sin_ poner manejo de infraestructura dentro del caso de uso, `function_app.py` será quien orqueste:

- Si el caso de uso termina OK -> `function_app.py` usa `BlobStorageAdapter` para borrar el original.
- Si el caso de uso lanza una excepción (pre-OpenAI o crítica) -> `function_app.py` usa `RestApiAdapter` para actualizar el estado, y `BlobStorageAdapter` para mover a error y borrar el original.
- Si el caso de uso lanza una excepción (post-OpenAI) -> `function_app.py` usa `RestApiAdapter` para actualizar el estado, _podría_ usar `BlobStorageAdapter` para guardar los datos intermedios (si el caso de uso los devuelve o si `function_app.py` los tiene), y `BlobStorageAdapter` para borrar el original.

Mantendremos la esencia de los dos tipos de manejo de errores, pero orquestados desde `function_app.py`.

---

**Implementación:**

Aquí te presento los archivos con la nueva estructura y el código refactorizado.

**1. `src/interfaces/api_rest_repository_interface.py`**
(Tu archivo original `api_rest_repository_interface.py` contiene código duplicado de `validate_process_json.py`. Lo corregiré para que solo sea la interfaz.)

```python
# src/interfaces/api_rest_repository_interface.py
from abc import ABC, abstractmethod
from typing import Dict, Optional

class ApiRestRepositoryInterface(ABC):
    """Interfaz que define los métodos que un adaptador de API REST debe implementar."""

    @abstractmethod
    def get_resumen(self, id: str) -> dict:
        """
        Obtiene un resumen del perfil por ID de Rank.

        Args:
            id: ID del Rank.

        Returns:
            Diccionario con los datos del resumen (debe incluir profileDescription y variablesContent).

        Raises:
            APIError: Si falla la llamada a la API.
            AuthenticationError: Si falla la autenticación con la API.
        """
        pass

    @abstractmethod
    def add_scores(self, candidate_id: str, scores: Dict[str, int]) -> None:
        """
        Envía las puntuaciones calculadas para un candidato.

        Args:
            candidate_id: ID del candidato.
            scores: Diccionario de puntuaciones.

        Raises:
            APIError: Si falla la llamada a la API.
            AuthenticationError: Si falla la autenticación con la API.
        """
        pass

    @abstractmethod
    def save_resumen(
        self,
        candidate_id: str,
        transcription: str,
        score: float,
        candidate_name: str,
        analysis: str,
    ) -> None:
        """
        Guarda el resumen completo del análisis para un candidato.

        Args:
            candidate_id: ID del candidato.
            transcription: Texto completo extraído del CV.
            score: Puntuación promedio calculada.
            candidate_name: Nombre del candidato extraído.
            analysis: Justificación del análisis de OpenAI.

        Raises:
            APIError: Si falla la llamada a la API.
            AuthenticationError: Si falla la autenticación con la API.
        """
        pass

    @abstractmethod
    def update_candidate(
        self, candidate_id: str, error_message: Optional[str] = None
    ) -> None:
        """
        Actualiza el estado de procesamiento de un candidato (ej. con mensaje de error).

        Args:
            candidate_id: ID del candidato.
            error_message: Mensaje de error, o None si el procesamiento fue exitoso.

        Raises:
            APIError: Si falla la llamada a la API.
            AuthenticationError: Si falla la autenticación con la API.
        """
        pass

```

**2. `src/interfaces/blob_storage_interface.py`** (Nueva interfaz)

```python
# src/interfaces/blob_storage_interface.py
from abc import ABC, abstractmethod
from typing import BinaryIO, Optional

class BlobStorageInterface(ABC):
    """Interfaz que define las operaciones de Blob Storage necesarias."""

    @abstractmethod
    def upload_blob(
        self, container_name: str, blob_name: str, data: str | bytes, content_settings: Optional[dict] = None
    ) -> None:
        """
        Sube datos a un blob, creando el contenedor si no existe.

        Args:
            container_name: Nombre del contenedor.
            blob_name: Nombre del blob.
            data: Datos a subir (string o bytes).
            content_settings: Opciones de configuración de contenido (ej. content_type, metadata).

        Raises:
            FileProcessingError: Si falla la subida.
        """
        pass

    @abstractmethod
    def delete_blob(self, container_name: str, blob_name: str) -> None:
        """
        Borra un blob si existe.

        Args:
            container_name: Nombre del contenedor.
            blob_name: Nombre del blob.

        Raises:
            FileProcessingError: Si falla el borrado (ignorando ResourceNotFoundError).
        """
        pass

    @abstractmethod
    def move_blob(self, source_container: str, source_blob_name: str, destination_container: str, destination_blob_name: str) -> None:
        """
        Copia un blob a una nueva ubicación y borra el original.

        Args:
            source_container: Contenedor origen.
            source_blob_name: Nombre del blob origen.
            destination_container: Contenedor destino.
            destination_blob_name: Nombre del blob destino.

        Raises:
            FileProcessingError: Si falla la copia o el borrado.
        """
        pass

    # No necesitamos un download_blob explícito para este caso de uso,
    # ya que Azure Functions nos da el stream directamente.
    # Si el caso de uso necesitara leer el blob, se añadiría.
    # @abstractmethod
    # def download_blob_stream(self, container_name: str, blob_name: str) -> BinaryIO:
    #     pass

```

**3. `src/interfaces/document_intelligence_interface.py`** (Nueva interfaz)

```python
# src/interfaces/document_intelligence_interface.py
from abc import ABC, abstractmethod
from typing import BinaryIO

class DocumentIntelligenceInterface(ABC):
    """Interfaz que define los métodos que un adaptador de Document Intelligence debe implementar."""

    @abstractmethod
    def analyze_cv(self, file_stream: BinaryIO) -> str:
        """
        Extrae texto de un flujo de archivo de CV utilizando Document Intelligence.

        Args:
            file_stream (BinaryIO): Un flujo binario que contiene el CV (PDF).

        Returns:
            str: El texto extraído del CV.

        Raises:
            DocumentIntelligenceError: Si hay un error al comunicarse con Document Intelligence.
            NoContentExtractedError: Si no se extrajo ningún texto del CV.
        """
        pass
```

**4. `src/interfaces/openai_interface.py`** (Nueva interfaz)

```python
# src/interfaces/openai_interface.py
from abc import ABC, abstractmethod

class OpenAIInterface(ABC):
    """Interfaz que define los métodos que un adaptador de OpenAI debe implementar."""

    @abstractmethod
    def get_completion(self, system_message: str, user_message: str) -> str:
        """
        Obtiene una finalización de texto de OpenAI.

        Args:
            system_message (str): El mensaje del sistema.
            user_message (str): El mensaje del usuario (el texto del CV).

        Returns:
            str: La respuesta generada por OpenAI (se espera un JSON string).

        Raises:
            OpenAIError: Si ocurre un error durante la llamada a la API o si la respuesta no es válida/vacía.
        """
        pass
```

**5. `src/interfaces/key_vault_interface.py`** (Nueva interfaz)

```python
# src/interfaces/key_vault_interface.py
from abc import ABC, abstractmethod

class KeyVaultInterface(ABC):
    """Interfaz que define los métodos que un cliente de Key Vault debe implementar."""

    @abstractmethod
    def get_secret(self, secret_name: str) -> str:
        """
        Obtiene el valor de un secreto desde Azure Key Vault.

        Args:
            secret_name: El nombre del secreto a obtener.

        Returns:
            El valor del secreto como una cadena.

        Raises:
            SecretNotFoundError: Si el secreto no se encuentra en Key Vault.
            KeyVaultError: Si ocurre cualquier otro error al interactuar con Key Vault.
        """
        pass
```

**6. `src/infrastructure/api_rest/api_rest_adapter.py`**
(Agregar herencia de interfaz y ajustar imports)

```python
# src/infrastructure/api_rest/api_rest_adapter.py
import os
import logging
import requests
from typing import Dict, Optional
from datetime import datetime, timedelta

from src.domain.entities.api_credentials import ApiCredentials
from src.domain.exceptions import APIError, AuthenticationError, DomainError # Importar errores del dominio
from src.interfaces.api_rest_repository_interface import ApiRestRepositoryInterface # Importar interfaz

ENV_API_ROLE = "ApiServices__IARC__Role"
ENV_API_USER_APPLICATION = "ApiServices__IARC__UserFunction"
ENV_API_BASE_URL = "ApiServices__IARC__Backend"
TOKEN_EXPIRATION_MINUTES = 20
TOKEN_EXPIRATION_SECONDS = TOKEN_EXPIRATION_MINUTES * 60


class RestApiAdapter(ApiRestRepositoryInterface): # Heredar de la interfaz
    def __init__(
        self,
        username: str,
        password: str,
        base_url_env_var: str = ENV_API_BASE_URL,
        role_env_var: str = ENV_API_ROLE,
        user_app_env_var: str = ENV_API_USER_APPLICATION,
    ):
        self.base_url = os.environ.get(base_url_env_var)
        self.username = username
        self.password = password
        self.role = os.environ.get(role_env_var)
        self.user_application = os.environ.get(user_app_env_var)
        self._credentials: Optional[ApiCredentials] = None

        missing_values = []

        # Validar que los valores inyectados o de entorno no sean nulos/vacíos
        if not self.base_url:
            missing_values.append(f"Environment variable '{base_url_env_var}'")
        if not self.username:
            missing_values.append("username (from Key Vault)")
        if not self.password:
            missing_values.append("password (from Key Vault)")
        if not self.role:
             missing_values.append(f"Environment variable '{role_env_var}'")
        if not self.user_application:
             missing_values.append(f"Environment variable '{user_app_env_var}'")


        if missing_values:
            error_message = "Faltan valores requeridos para la inicialización del REST API Adapter: " + ", ".join(missing_values)
            logging.critical(error_message) # Log crítico aquí
            raise ValueError(error_message) # Lanzar ValueError durante la inicialización


    def _authenticate(self) -> ApiCredentials:
        """Autentica contra la API y devuelve las credenciales (token)."""
        url = f"{self.base_url}/Account"
        headers = {"Content-Type": "application/json"}
        data = {
            "username": self.username,
            "password": self.password,
            "role": self.role,
            "userApplication": self.user_application,
        }
        logging.debug(f"Intentando autenticar con la API en {url}")
        try:
            response = requests.post(
                url, headers=headers, json=data, verify=True, timeout=30 # Añadir timeout
            )
            response.raise_for_status()

            token = response.text.strip()

            if not token:
                logging.error("La API de autenticación devolvió un token vacío.")
                raise AuthenticationError("La API de autenticación devolvió un token vacío.")

            # El token expira en TOKEN_EXPIRATION_SECONDS desde el momento de la autenticación
            expires_at = datetime.now() + timedelta(seconds=TOKEN_EXPIRATION_SECONDS)
            logging.debug(f"Autenticación exitosa. Token expira en {expires_at}")
            return ApiCredentials(
                token=token, expires_at=expires_at # Almacenar el datetime exacto
            )

        except requests.exceptions.RequestException as e:
            logging.exception("Error durante la autenticación con la API: %s", e)
            # Decidir si un error de autenticación debe ser APIError o AuthenticationError
            # AuthenticationError parece más específico.
            raise AuthenticationError(f"Falló la autenticación con la API: {e}") from e
        except Exception as e:
             logging.exception("Error inesperado durante la autenticación con la API: %s", e)
             raise APIError(f"Error inesperado durante la autenticación con la API: {e}") from e


    def get_credentials(self) -> ApiCredentials:
        """Obtiene las credenciales válidas (autenticando si es necesario)."""
        # Verificar si las credenciales existen Y si aún son válidas con un margen
        if self._credentials is None or not self._credentials.is_valid(margin_seconds=60):
            logging.debug("Credenciales de API inválidas o inexistentes. Autenticando...")
            self._credentials = self._authenticate()
        else:
            logging.debug("Credenciales de API existentes y válidas.")
        return self._credentials

    def _make_request(
        self,
        method: str,
        endpoint: str,
        params: dict = None,
        data: dict = None,
        headers: dict = None,
        verify: bool = True,
        expect_response_body: bool = True,
    ) -> Optional[dict]:
        """Realiza una petición a la API, manejando la autenticación y errores genéricos."""

        try:
            credentials = self.get_credentials() # Esto manejará la re-autenticación
        except AuthenticationError as e:
            # Si falla la autenticación, no podemos hacer la petición.
            logging.error(f"No se pudieron obtener credenciales para la petición a {endpoint}: {e}")
            raise # Relanza el error de autenticación

        auth_headers = {"Authorization": f"Bearer {credentials.token}"}

        request_headers = headers.copy() if headers else {}
        request_headers.update(auth_headers)
        request_headers["Content-Type"] = "application/json" # Asegurarse de que el tipo de contenido es JSON

        url = f"{self.base_url}{endpoint}"
        logging.debug(f"Realizando petición {method} a {url}")

        try:
            response = requests.request(
                method, url, params=params, json=data, headers=request_headers, verify=verify, timeout=60 # Añadir timeout
            )
            logging.debug(f"Respuesta de {url} recibida con estado: {response.status_code}")

            # Esto verifica el estado HTTP (2xx es éxito, otros lanzan excepción)
            # requests.exceptions.HTTPError es una subclase de requests.exceptions.RequestException
            response.raise_for_status()

            # Si no esperamos cuerpo de respuesta O si la respuesta es 204 No Content (sin cuerpo)
            if not expect_response_body or response.status_code == 204:
                 logging.debug(f"Petición a {url} exitosa con estado {response.status_code}. No se esperaba/procesó cuerpo de respuesta.")
                 return None

            # Si esperamos cuerpo de respuesta Y hay contenido
            if response.content:
                 logging.debug(f"Petición a {url} exitosa con estado {response.status_code}. Procesando cuerpo de respuesta.")
                 try:
                     return response.json() # Procesamos y devolvemos el diccionario
                 except json.JSONDecodeError:
                     logging.error(f"Petición a {url} exitosa con estado {response.status_code}, pero el cuerpo no es JSON válido: {response.text}")
                     # Decide si esto debe ser un error (probablemente sí)
                     raise APIError(f"La API devolvió respuesta no JSON para {endpoint}: {response.text[:200]}")
            else:
                 # Si esperamos cuerpo pero no hay
                 logging.warning(f"Petición a {url} exitosa con estado {response.status_code}, pero no se devolvió contenido a pesar de esperar un cuerpo.")
                 # Decide si esto debe ser un error o simplemente devolver None
                 # Depende de la API. Para este caso, devolver None podría ser aceptable si el use case lo maneja.
                 # O podrías lanzar un error si siempre se espera un cuerpo en estos casos.
                 # Vamos a devolver None y que el use case valide la respuesta.
                 return None

        except requests.exceptions.HTTPError as e:
            logging.exception("Error HTTP durante la petición a %s: %s", url, e)
            error_message = f"Error HTTP {e.response.status_code} en {endpoint}"
            if e.response is not None and e.response.text:
                 error_message += f": {e.response.text[:200]}" # Añadir parte del cuerpo del error
            raise APIError(error_message) from e # Relanza como APIError

        except requests.exceptions.RequestException as e:
            # Otros errores de request (conexión, timeout, etc.)
            logging.exception("Error de petición general durante la llamada a %s: %s", url, e)
            raise APIError(f"Falló la petición API a {endpoint}: {e}") from e

        except Exception as e:
             # Errores inesperados
             logging.exception("Error inesperado durante la petición a %s: %s", url, e)
             raise APIError(f"Error inesperado durante la petición API a {endpoint}: {e}") from e


    # Métodos públicos que llaman a _make_request
    def get(self, endpoint: str, params: dict = None, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        return self._make_request("GET", endpoint, params=params, headers=headers, expect_response_body=expect_response_body)

    def post(self, endpoint: str, data: dict, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        return self._make_request("POST", endpoint, data=data, headers=headers, expect_response_body=expect_response_body)

    def put(self, endpoint: str, data: dict, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        return self._make_request("PUT", endpoint, data=data, headers=headers, expect_response_body=expect_response_body)

    def patch(self, endpoint: str, data: dict, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        return self._make_request("PATCH", endpoint, data=data, headers=headers, expect_response_body=expect_response_body)

    def delete(self, endpoint: str, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        return self._make_request("DELETE", endpoint, headers=headers, expect_response_body=expect_response_body)


    # -----------------------------------------------------------------------------------------------
    # --- Implementación de la Interfaz ApiRestRepositoryInterface ---
    # Asegurarse de que estos métodos correspondan a la interfaz

    # @override # Puedes usar @override si usas Python 3.12+ y lo importas de typing
    def get_resumen(self, id: str) -> dict:
        """Obtiene un resumen por ID de Rank (GET /Resumen/{id})."""
        endpoint = f"/Resumen/{id}"
        logging.info(f"Obteniendo resumen para Rank ID: {id}")
        # Esperamos un cuerpo de respuesta para este método
        result = self.get(endpoint, expect_response_body=True)
        if result is None:
             logging.error(f"La API get_resumen para Rank ID {id} no devolvió datos.")
             raise APIError(f"La API get_resumen para Rank ID {id} no devolvió datos.")
        return result


    # @override
    def add_scores(self, candidate_id: str, scores: Dict[str, int]) -> None:
        """Agrega puntuaciones a un candidato (POST /Resumen/AddScores)."""
        endpoint = "/Resumen/AddScores"
        logging.info(f"Enviando scores para Candidate ID: {candidate_id}")
        data = {
            "candidateId": candidate_id,
            "scores": scores,
        }
        # No espera cuerpo de respuesta, solo éxito HTTP.
        self.post(endpoint, data=data, expect_response_body=False)
        logging.info(f"Scores enviados exitosamente para Candidate ID: {candidate_id}.")


    # @override
    def save_resumen(
        self,
        candidate_id: str,
        transcription: str,
        score: float,
        candidate_name: str,
        analysis: str,
    ) -> None:
        """Guarda un resumen completo (POST /Resumen/Save)."""
        endpoint = "/Resumen/Save"
        logging.info(f"Guardando resumen completo para Candidate ID: {candidate_id}")
        data = {
            "candidateId": candidate_id,
            "transcription": transcription,
            "score": score,
            "analysis": analysis,
            "candidateName": candidate_name,
        }
        # No espera cuerpo de respuesta, solo éxito HTTP.
        self.post(endpoint, data=data, expect_response_body=False)
        logging.info(f"Resumen completo guardado exitosamente para Candidate ID: {candidate_id}.")

    # @override
    def update_candidate(
        self, candidate_id: str, error_message: Optional[str] = None
    ) -> None:
        """Actualiza un candidato (PUT /Resumen)."""
        endpoint = "/Resumen"
        logging.info(f"Actualizando estado de Candidate ID: {candidate_id}")
        data = {
            "candidateId": candidate_id,
            "errorMessage": error_message, # Puede ser None
        }
        # No espera cuerpo de respuesta, solo éxito HTTP.
        self.put(endpoint, data=data, expect_response_body=False)
        if error_message:
             logging.warning(f"Estado de Candidate ID: {candidate_id} actualizado con error: {error_message}")
        else:
             logging.info(f"Estado de Candidate ID: {candidate_id} actualizado a éxito.")

```

**7. `src/infrastructure/key_vault/key_vault_client.py`**
(Agregar herencia de interfaz y ajustar imports)

```python
# src/infrastructure/key_vault/key_vault_client.py
import os
import logging
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential, ClientSecretCredential, ManagedIdentityCredential
from azure.core.exceptions import ResourceNotFoundError, ClientAuthenticationError, HttpResponseError

from src.domain.exceptions import ( # Importar errores del dominio
    KeyVaultError,
    SecretNotFoundError,
    AuthenticationError # DefaultAzureCredential puede lanzar errores de autenticación
)
from src.interfaces.key_vault_interface import KeyVaultInterface # Importar interfaz

class KeyVaultClient(KeyVaultInterface): # Heredar de la interfaz
    """Cliente para interactuar con Azure Key Vault y obtener secretos."""

    def __init__(self, kv_name: str):
        """
        Inicializa el cliente de Key Vault.

        Args:
            kv_name: El nombre del Key Vault (ej. 'my-vault-name'). La URI se construye a partir de este.

        Raises:
            ValueError: Si kv_name es nulo o vacío.
            KeyVaultError: Si ocurre un error al inicializar DefaultAzureCredential o SecretClient.
            AuthenticationError: Si DefaultAzureCredential no puede encontrar credenciales.
        """
        self.kv_name = kv_name
        if not self.kv_name:
            logging.critical(
                "CRÍTICO: El nombre del Key Vault (Vault) no se ha proporcionado en las variables de entorno."
            )
            raise ValueError(
                "El nombre del Key Vault no se ha proporcionado."
            )

        self.vault_uri = f"https://{self.kv_name}.vault.azure.net/" # Construir la URI

        logging.info(f"Intentando inicializar cliente de Key Vault para URI: {self.vault_uri}")
        try:
            # DefaultAzureCredential intentará varios métodos de autenticación en orden.
            # Para Functions V2, Managed Identity es el método recomendado en Azure.
            # Para desarrollo local, puede usar variables de entorno o credenciales del CLI/VS Code.
            credential = DefaultAzureCredential()
            logging.debug("DefaultAzureCredential inicializado.")

            # Opcional: intenta obtener un token para verificar la credencial temprano
            # try:
            #     credential.get_token("https://vault.azure.net/.default")
            #     logging.debug("Obtención de token de prueba exitosa.")
            # except Exception as token_err:
            #      logging.warning(f"Fallo al obtener token de prueba, pero DefaultAzureCredential está inicializado. El error real podría aparecer al acceder a un secreto: {token_err}")


            self.secret_client = SecretClient(
                vault_url=self.vault_uri, credential=credential
            )
            logging.info("SecretClient inicializado exitosamente.")

        except ClientAuthenticationError as e:
             logging.critical("CRÍTICO: Error de autenticación al inicializar DefaultAzureCredential. Asegúrese de que la identidad tenga permisos en Key Vault.", exc_info=True)
             # Envuelve el error de autenticación en un error de dominio
             raise AuthenticationError(f"Error de autenticación al inicializar el cliente de Key Vault: {e}") from e
        except Exception as e:
            # Captura otros posibles errores durante la inicialización
            logging.critical(f"CRÍTICO: Error inesperado al inicializar DefaultAzureCredential o SecretClient: {e}", exc_info=True)
            raise KeyVaultError(f"Error al inicializar el cliente de Key Vault: {e}") from e

    # @override
    def get_secret(self, secret_name: str) -> str:
        """
        Obtiene el valor de un secreto desde Azure Key Vault.

        Args:
            secret_name: El nombre del secreto a obtener.

        Returns:
            El valor del secreto como una cadena.

        Raises:
            SecretNotFoundError: Si el secreto no se encuentra en Key Vault.
            KeyVaultError: Si ocurre cualquier otro error al interactuar con Key Vault.
            AuthenticationError: Si falla la autenticación durante la llamada (menos común si la inicialización fue OK).
        """
        logging.debug("Intentando recuperar el secreto: %s", secret_name)
        try:
            retrieved_secret = self.secret_client.get_secret(secret_name)
            if not retrieved_secret.value:
                 logging.warning(f"Secreto '{secret_name}' encontrado en Key Vault pero su valor está vacío.")
                 # Decide si un secreto vacío debe considerarse un error.
                 # Para la mayoría de las configuraciones, un secreto vacío es tan inútil como uno no encontrado.
                 raise SecretNotFoundError(f"Secreto '{secret_name}' encontrado en Key Vault pero su valor está vacío.")

            logging.debug("Secreto '%s' recuperado exitosamente.", secret_name)
            return retrieved_secret.value
        except ResourceNotFoundError:
            logging.error("Secreto no encontrado en Key Vault: %s", secret_name)
            raise SecretNotFoundError(
                f"Secreto '{secret_name}' no encontrado en Key Vault: {self.vault_uri}"
            )
        except ClientAuthenticationError as e:
            logging.error(
                "Error de autenticación al recuperar el secreto '%s': %s", secret_name, e
            )
            raise AuthenticationError(
                f"Error de autenticación al recuperar el secreto '{secret_name}': {e}"
            ) from e
        except HttpResponseError as e:
             # Capturar otros errores HTTP (ej. 403 Forbidden si la política de acceso no permite 'Get')
             logging.error(
                 "Error HTTP (%s) al recuperar el secreto '%s': %s", e.status_code, secret_name, e
             )
             if e.status_code == 403:
                 raise AuthenticationError(f"Permiso denegado (403) al obtener secreto '{secret_name}'. Revise la política de acceso de Key Vault.") from e
             else:
                 raise KeyVaultError(f"Error HTTP inesperado al recuperar el secreto '{secret_name}': {e}") from e

        except Exception as e:
            # Captura otros posibles errores (ej. problemas de red con Key Vault)
            logging.exception(
                "Error inesperado al recuperar el secreto '%s' desde Key Vault: %s",
                secret_name,
                e,
            )
            raise KeyVaultError(f"Error inesperado al recuperar el secreto '{secret_name}': {e}") from e

```

**8. `src/infrastructure/ocr/document_intelligence_adapter.py`**
(Agregar herencia de interfaz y ajustar imports)

```python
# src/infrastructure/ocr/document_intelligence_adapter.py
import os
import logging
import time
from typing import BinaryIO
from functools import wraps

from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeDocumentRequest, AnalyzeResult
from azure.core.exceptions import (
    ServiceRequestError,
    HttpResponseError,
    ClientAuthenticationError,
)
from src.domain.exceptions import ( # Importar errores del dominio
    DocumentIntelligenceError,
    NoContentExtractedError,
    AuthenticationError # Aunque este adaptador usa Key, ClientAuthError podría ocurrir
)
from src.interfaces.document_intelligence_interface import DocumentIntelligenceInterface # Importar interfaz

# Mantener el decorador de reintentos, pero asegúrarse de que lance errores del dominio
def _retry_on_service_error(max_retries: int = 3, retry_delay: int = 30):
    """
    Decorador para reintentar llamadas a la API de Document Intelligence.
    Convierte excepciones de Azure SDK en excepciones de dominio.
    """

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except (ServiceRequestError, HttpResponseError) as e:
                    retries += 1
                    status_code = getattr(e, 'status_code', 'N/A')
                    error_type = type(e).__name__

                    if isinstance(e, HttpResponseError) and e.status_code == 429:
                        log_msg = f"Demasiadas solicitudes (429)"
                    elif isinstance(e, ServiceRequestError):
                         log_msg = f"Error de servicio/red"
                    else:
                         log_msg = f"Error HTTP ({status_code})"


                    if retries < max_retries:
                        wait_time = retry_delay * (2 ** (retries - 1))
                        logging.warning(
                            f"{log_msg} (intento {retries}/{max_retries}). Reintentando en {wait_time} segundos. Detalles: {e}"
                        )
                        time.sleep(wait_time)
                    else:
                        logging.error(
                            f"Se excedió el número máximo de reintentos ({max_retries}) para {log_msg}. Detalles: {e}"
                        )
                        # Relanza como error de dominio
                        raise DocumentIntelligenceError(
                            f"Fallo en Document Intelligence después de {max_retries} reintentos por {log_msg}: {e}"
                        ) from e
                except ClientAuthenticationError as e:
                    logging.error("Error de autenticación con Document Intelligence: %s", e)
                    # Relanza como error de dominio
                    raise AuthenticationError(f"Error de autenticación con Document Intelligence: {e}") from e
                except NoContentExtractedError:
                     # No reintentar si no hay contenido, es un problema del documento, no transitorio.
                     logging.warning("No se extrajo contenido, no se reintentará.")
                     raise # Relanzar el error específico NoContentExtractedError
                except Exception as e:
                    # Captura cualquier otro error inesperado que no sea de Azure SDK o NoContentExtractedError
                    logging.exception(
                        "Error inesperado durante la llamada a Document Intelligence: %s",
                        e,
                    )
                    # Relanza como error de dominio
                    raise DocumentIntelligenceError(
                        f"Error inesperado durante la llamada a Document Intelligence: {e}"
                    ) from e

            # Si salimos del bucle sin reintentar, significa que hubo éxito o un error no reintentable
            # Si llegamos aquí, la llamada original func(*args, **kwargs) fue exitosa.
        return wrapper

    return decorator


class DocumentIntelligenceAdapter(DocumentIntelligenceInterface): # Heredar de la interfaz
    """Adaptador para interactuar con Azure AI Document Intelligence."""

    def __init__(
        self,
        endpoint: str,
        api_key: str,
    ):
        """
        Inicializa el DocumentIntelligenceAdapter con el punto de conexión y la clave de API.

        Args:
            endpoint (str): El punto de conexión de Document Intelligence.
            api_key (str): La clave de API de Document Intelligence.

        Raises:
            ValueError: Si el punto de conexión o la clave de API son nulos o vacíos.
            DocumentIntelligenceError: Si falla la creación del cliente.
        """
        self.endpoint = endpoint
        self.api_key = api_key

        if not self.endpoint:
             raise ValueError("El punto de conexión para Document Intelligence no se proporcionó.")
        if not self.api_key:
             raise ValueError("La API Key para Document Intelligence no se proporcionó.")

        try:
            self.client = self._create_client()
            logging.info("DocumentIntelligenceClient inicializado exitosamente.")
        except Exception as e:
             logging.critical(f"CRÍTICO: Falló la creación del cliente DocumentIntelligenceClient: {e}", exc_info=True)
             # Envuelve cualquier error de inicialización en un error de dominio
             raise DocumentIntelligenceError(f"Falló la creación del cliente Document Intelligence: {e}") from e


    def _create_client(self) -> DocumentIntelligenceClient:
        """Crea y configura el cliente de Document Intelligence."""
        # AzureKeyCredential puede lanzar ValueError si la clave es inválida
        return DocumentIntelligenceClient(
            endpoint=self.endpoint, credential=AzureKeyCredential(self.api_key)
        )

    # @override
    @_retry_on_service_error() # Aplicar el decorador con manejo de errores de dominio
    def analyze_cv(self, file_stream: BinaryIO) -> str:
        """
        Extrae texto de un CV utilizando Document Intelligence.

        Args:
            file_stream (BinaryIO): Un flujo binario que contiene el CV (PDF).

        Returns:
            str: El texto extraído del CV.

        Raises:
            DocumentIntelligenceError: Si hay un error al comunicarse con Document Intelligence (incluye reintentos).
            NoContentExtractedError: Si no se extrajo ningún texto del CV.
            # AuthenticationError: Si falla la autenticación (maneja en el decorador)
        """
        logging.info("Enviando documento a Document Intelligence para análisis...")
        # Asegurarse de rebobinar el stream si ya fue leído, aunque con el blob trigger no suele ser necesario
        # file_stream.seek(0)
        try:
            # "prebuilt-read" es el modelo más adecuado para extraer texto de un CV
            poller = self.client.begin_analyze_document(
                "prebuilt-read",
                AnalyzeDocumentRequest(bytes_source=file_stream.read()),
                # Añadir un timeout si es posible o necesario
                # poller_timeout=300 # 5 minutos
            )
            logging.info("Document Intelligence poller iniciado.")
            result: AnalyzeResult = poller.result()
            logging.info("Document Intelligence análisis completado.")

            if result and result.content:
                logging.info(f"Texto extraído de Document Intelligence (longitud: {len(result.content)}).")
                return result.content
            else:
                logging.warning("Document Intelligence no devolvió ningún contenido en el resultado.")
                raise NoContentExtractedError(
                    "Document Intelligence no extrajo ningún contenido del documento."
                )

        except NoContentExtractedError:
             # Propagar este error específico sin envolver
             raise
        except Exception as e:
            # Captura errores que no son manejados por el decorador
            logging.exception(
                "Error inesperado durante el análisis de documentos con Document Intelligence (fuera del decorador de reintentos): %s",
                e,
            )
            # Envuelve en un error de dominio genérico si no es uno específico ya lanzado
            raise DocumentIntelligenceError(
                f"Error inesperarado al analizar el documento con DI: {e}"
            ) from e


```

**9. `src/infrastructure/ocr/azure_openai_adapter.py`**
(Agregar herencia de interfaz y ajustar imports)

```python
# src/infrastructure/ocr/azure_openai_adapter.py
import time
import logging
from functools import wraps
from azure.identity import get_bearer_token_provider, ClientSecretCredential, DefaultAzureCredential

from openai import AzureOpenAI, RateLimitError, APIConnectionError, APIStatusError, AuthenticationError as OpenAIAuthenticationError

from src.domain.exceptions import OpenAIError, AuthenticationError as DomainAuthenticationError # Importar errores del dominio
from src.interfaces.openai_interface import OpenAIInterface # Importar interfaz

MAX_TOKENS = 2048
TEMPERATURE = 0.2
TOP_P = 0.95
FREQUENCY_PENALTY = 0
PRESENCE_PENALTY = 0
STOP = None
STREAM = False # Mantener en False para no procesar por chunks


AZURE_AI_SCOPES = "https://cognitiveservices.azure.com/.default"

class AzureOpenAIAdapter(OpenAIInterface): # Heredar de la interfaz
    """
    Adaptador para interactuar con el servicio Azure OpenAI. Maneja la autenticación,
    los reintentos y el manejo de errores.
    """

    def __init__(
        self,
        endpoint: str,
        api_version: str,
        deployment: str, # Usar deployment_name en el constructor para mayor claridad
        client_id: Optional[str] = None, # Hacer opcionales si DefaultAzureCredential es la principal
        client_secret: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ):
        """
        Inicializa el AzureOpenAIAdapter con punto de conexión, versión de API,
        nombre de la implementación (deployment), y credenciales Entra ID (opcional).

        Args:
            endpoint (str): Punto de conexión de Azure OpenAI.
            api_version (str): Versión de API de Azure OpenAI.
            deployment (str): Nombre de la implementación (Deployment Name) en Azure OpenAI Studio.
            client_id (str, optional): ID del cliente (Client ID) de la Entidad de Servicio. Requerido si no usa DefaultAzureCredential.
            client_secret (str, optional): Secreto del cliente (Client Secret) de la Entidad de Servicio. Requerido si no usa DefaultAzureCredential.
            tenant_id (str, optional): ID del tenant (Tenant ID) de Azure AD (Entra ID). Requerido si no usa DefaultAzureCredential.

        Raises:
           ValueError: Si falta alguna de las configuraciones requeridas (endpoint, api_version, deployment).
           DomainAuthenticationError: Si falla la autenticación con Entra ID/DefaultAzureCredential.
           OpenAIError: Si falla la creación del cliente AzureOpenAI por otra razón.
        """
        self.endpoint = endpoint
        self.api_version = api_version
        self.deployment = deployment # Usar deployment_name internamente si prefieres
        self.client_id = client_id
        self.client_secret = client_secret
        self.tenant_id = tenant_id

        if not self.endpoint:
            raise ValueError("El punto de conexión (endpoint) para Azure OpenAI no se proporcionó.")
        if not self.api_version:
            raise ValueError("La versión de API (api_version) para Azure OpenAI no se proporcionó.")
        if not self.deployment:
            raise ValueError("El nombre de la implementación (deployment) para Azure OpenAI no se proporcionó.")

        try:
            # Create the client using Entra ID authentication (preferably Managed Identity via DefaultAzureCredential)
            self.client = self._create_client()
            logging.info("AzureOpenAI client initialized successfully.")
        except OpenAIAuthenticationError as e:
             logging.critical(f"CRÍTICO: Falló la autenticación al crear el cliente AzureOpenAI con Entra ID: {e}", exc_info=True)
             # Envuelve el error de autenticación específico de OpenAI SDK en un error de dominio
             raise DomainAuthenticationError(f"Falló la autenticación al crear el cliente Azure OpenAI: {e}") from e
        except Exception as e:
             # Catch other errors during client creation
             logging.critical(f"CRÍTICO: Falló la creación del cliente AzureOpenAI: {e}", exc_info=True)
             raise OpenAIError(f"Falló la creación del cliente Azure OpenAI: {e}") from e

    def _create_client(self) -> AzureOpenAI:
        """
        Crea y configura el cliente de Azure OpenAI utilizando autenticación Entra ID.
        Prioriza DefaultAzureCredential, si no hay credenciales específicas de SPN.
        """
        credential = None
        if self.client_id and self.client_secret and self.tenant_id:
            logging.debug("Usando ClientSecretCredential para autenticación Azure OpenAI.")
            credential = ClientSecretCredential(
                tenant_id=self.tenant_id,
                client_id=self.client_id,
                client_secret=self.client_secret
            )
        # elif managed_identity_client_id: # Si soportaras Managed Identity con ID específico
        #      logging.debug("Usando ManagedIdentityCredential con client_id específico.")
        #      credential = ManagedIdentityCredential(client_id=managed_identity_client_id)
        else:
            logging.debug("Intentando usar DefaultAzureCredential para autenticación Azure OpenAI.")
            # DefaultAzureCredential es ideal para Azure Functions con Managed Identity habilitada
            credential = DefaultAzureCredential()

        if credential is None:
             # Esto no debería pasar si DefaultAzureCredential es el fallback, pero como seguridad
             raise DomainAuthenticationError("No se pudo obtener una credencial válida para Azure OpenAI.")

        # Verificar si la credencial es funcional (opcional pero bueno)
        try:
            # Intentar obtener un token para validar la credencial
            # DefaultAzureCredential requiere el scope apropiado para la validación temprana
            credential.get_token(AZURE_AI_SCOPES)
            logging.debug("Credencial verificada: token obtenido exitosamente.")
        except Exception as token_err:
             logging.warning(f"La validación temprana de la credencial falló: {token_err}. La llamada a la API aún podría funcionar, pero revise la configuración de autenticación.")
             # No lanzar excepción crítica aquí, solo advertencia, la llamada real fallará si la credencial es mala.
             # Pero si quieres lanzar, envuelve en DomainAuthenticationError

        token_provider = get_bearer_token_provider(
            credential,
            AZURE_AI_SCOPES
        )
        logging.debug("Token provider creado.")

        return AzureOpenAI(
            azure_endpoint=self.endpoint,
            api_version=self.api_version,
            azure_ad_token_provider=token_provider,
            # resource=AZURE_AI_SCOPES # No es necesario con azure_ad_token_provider
        )

    def _retry_on_rate_limit(max_retries: int = 3, retry_delay: int = 30):
        """
        Decorador para reintentar llamadas a la API en caso de RateLimitError o errores de conexión/estado transitorios.
        Convierte excepciones de OpenAI SDK en excepciones de dominio.
        """

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                retries = 0
                last_error = None
                while retries < max_retries:
                    try:
                        return func(*args, **kwargs)
                    except (RateLimitError, APIConnectionError, APIStatusError) as e:
                        last_error = e
                        retries += 1
                        error_type = type(e).__name__
                        status_code = getattr(e, 'status_code', 'N/A')

                        if retries < max_retries:
                            wait_time = retry_delay * (2 ** (retries - 1))
                            log_msg = f"{error_type}"
                            if status_code != 'N/A':
                                log_msg += f" (estado {status_code})"
                            logging.warning(
                                f"{log_msg} (intento {retries}/{max_retries}). Reintentando en {wait_time} segundos. Detalles: {e}"
                            )
                            time.sleep(wait_time)
                        else:
                            logging.error(
                                f"Se excedió el número máximo de reintentos ({max_retries}) para {error_type}. Detalles: {e}"
                            )
                            # Relanza como error de dominio
                            raise OpenAIError(
                                f"Fallo en Azure OpenAI después de {max_retries} reintentos por {error_type}: {e}", last_error
                            ) from last_error
                    except OpenAIAuthenticationError as e:
                         # No reintentar si es un error de autenticación
                         logging.error("Error de autenticación con Azure OpenAI: %s", e)
                         raise DomainAuthenticationError(f"Error de autenticación con Azure OpenAI: {e}") from e

                    except Exception as e:
                        # Captura cualquier otro error inesperado
                        logging.exception(f"Error inesperado durante la llamada a Azure OpenAI: {e}")
                        # Relanza como error de dominio
                        raise OpenAIError(f"Error inesperado durante la llamada a Azure OpenAI: {e}", e) from e

                # Este punto solo se alcanza si el bucle de reintentos falla y lanza una excepción.
                # Si la llamada original dentro del try tiene éxito, retorna inmediatamente.
                # Si llegamos aquí por alguna lógica inesperada, lanzar el último error registrado.
                # Sin embargo, la estructura del bucle while/try/except/else garantiza que
                # o retorna exitosamente o lanza una excepción.
                if last_error:
                     # Esto es un fallback, el raise dentro del except debería ocurrir primero
                     raise OpenAIError(f"La llamada a OpenAI finalizó sin éxito después de reintentos.", last_error) from last_error
                else:
                     # Esto NO debería ocurrir en una ejecución normal
                     raise OpenAIError(f"La llamada a OpenAI finalizó en un estado inesperado.")


            return wrapper

        return decorator

    # @override
    @_retry_on_rate_limit() # Aplicar el decorador con manejo de errores de dominio
    def get_completion(self, system_message: str, user_message: str) -> str:
        """
        Obtiene una finalización de texto de Azure OpenAI.

        Args:
            system_message (str): El mensaje del sistema para guiar al modelo.
            user_message (str): El mensaje del usuario para generar una finalización para.

        Returns:
            str: La finalización de texto generada por el modelo (se espera un JSON string).

        Raises:
            OpenAIError: Si ocurre un error durante la llamada a la API, si la respuesta no es válida/vacía, o si falla después de reintentos.
            DomainAuthenticationError: Si falla la autenticación con Azure OpenAI.
        """
        logging.info(f"Enviando prompt a Azure OpenAI (deployment: {self.deployment}).")
        # No loguear el contenido completo del mensaje a menos que sea necesario para debugging
        # logging.debug(f"System prompt: {system_message[:500]}...")
        # logging.debug(f"User message (CV): {user_message[:500]}...")


        messages = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
        return self._create_completion(messages)


    def _create_completion(self, messages: list[dict]) -> str:
        """
        Función interna para crear la finalización con el cliente.
        Maneja la respuesta del cliente.
        """
        try:
            # La llamada create puede lanzar los errores de OpenAI SDK (RateLimitError, APIConnectionError, APIStatusError, AuthenticationError)
            # Estos errores son capturados y reintentados por el decorador @_retry_on_rate_limit.
            # Si la llamada es exitosa, el decorador simplemente retorna el resultado.
            completion = self.client.chat.completions.create(
                model=self.deployment, # Usar el nombre de la implementación
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                top_p=TOP_P,
                frequency_penalty=FREQUENCY_PENALTY,
                presence_penalty=PRESENCE_PENALTY,
                stop=STOP,
                stream=STREAM, # Debe ser False para obtener la respuesta completa
            )
            logging.info("Llamada a Azure OpenAI completada.")

            # Verificar la respuesta
            if (
                completion and
                completion.choices and
                len(completion.choices) > 0 and
                completion.choices[0].message and
                completion.choices[0].message.content
            ):
                # Retorna el contenido como un mensaje (String)
                logging.debug(f"Azure OpenAI devolvió contenido (longitud: {len(completion.choices[0].message.content)}).")
                return completion.choices[0].message.content
            else:
                # Si la respuesta es vacía o inesperada, lanzar un error de dominio
                logging.warning("Azure OpenAI devolvió una respuesta vacía o sin contenido válido.")
                raise OpenAIError(
                    "Azure OpenAI no devolvió opciones de finalización o contenido vacío."
                )

        except OpenAIError:
            # Si ya es un OpenAIError (posiblemente del decorador), simplemente relanzarlo
            raise
        except DomainAuthenticationError:
            # Si es un error de autenticación ya envuelto por el decorador, relanzarlo
            raise
        except Exception as e:
            # Captura cualquier otro error inesperado durante el procesamiento *de la respuesta*
            # después de que la llamada de la API fue considerada "exitosa" por el decorador,
            # o errores que el decorador no capturó (menos probable).
            logging.exception(
                "Error inesperado durante el procesamiento de la respuesta de OpenAI: %s", e
            )
            # Envuelve en un error de dominio genérico
            raise OpenAIError(f"Error al procesar la respuesta de OpenAI: {e}") from e
```

**10. `src/infrastructure/storage/blob_storage_adapter.py`** (Nueva implementación)

```python
# src/infrastructure/storage/blob_storage_adapter.py
import logging
from typing import BinaryIO, Optional
from azure.storage.blob import BlobServiceClient, ContentSettings, BlobClient
from azure.core.exceptions import ResourceNotFoundError, HttpResponseError, ClientAuthenticationError

from src.interfaces.blob_storage_interface import BlobStorageInterface # Importar interfaz
from src.domain.exceptions import FileProcessingError, AuthenticationError # Importar errores de dominio


class BlobStorageAdapter(BlobStorageInterface): # Heredar de la interfaz
    """Adaptador para interactuar con Azure Blob Storage."""

    def __init__(self, connection_string: str):
        """
        Inicializa el BlobStorageAdapter con la cadena de conexión.

        Args:
            connection_string: La cadena de conexión de Azure Storage.

        Raises:
            ValueError: Si la cadena de conexión es nula o vacía.
            AuthenticationError: Si falla la creación del cliente (ej. credenciales inválidas).
            FileProcessingError: Si falla la creación del cliente por otra razón.
        """
        self.connection_string = connection_string
        if not self.connection_string:
            raise ValueError("La cadena de conexión de Azure Storage no se proporcionó.")

        try:
            logging.info("Intentando inicializar BlobServiceClient...")
            self.blob_service_client = BlobServiceClient.from_connection_string(self.connection_string)
            logging.info("BlobServiceClient inicializado exitosamente.")
        except ClientAuthenticationError as e:
             logging.critical("CRÍTICO: Error de autenticación al inicializar BlobServiceClient.", exc_info=True)
             raise AuthenticationError(f"Error de autenticación al inicializar BlobServiceClient: {e}") from e
        except Exception as e:
             logging.critical(f"CRÍTICO: Error inesperado al inicializar BlobServiceClient: {e}", exc_info=True)
             raise FileProcessingError(f"Error al inicializar BlobServiceClient: {e}") from e


    def _get_blob_client_and_create_container(self, container_name: str, blob_name: str) -> BlobClient:
        """
        Obtiene un cliente de blob y crea el contenedor si no existe.
        Función auxiliar interna, similar a la original.
        """
        try:
            container_client = self.blob_service_client.get_container_client(container_name)
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
                        raise FileProcessingError(f"Error al crear contenedor '{container_name}': {e}") from e # Envuelve en error de dominio
                except Exception as e:
                     logging.error(f"Error inesperado al crear contenedor '{container_name}': {e}")
                     raise FileProcessingError(f"Error inesperado al crear contenedor '{container_name}': {e}") from e # Envuelve
        except Exception as e:
            logging.error(f"Error inesperado al obtener cliente de contenedor '{container_name}': {e}")
            raise FileProcessingError(f"Error inesperado al obtener cliente de contenedor '{container_name}': {e}") from e # Envuelve

        return container_client.get_blob_client(blob_name)

    # @override
    def upload_blob(
        self, container_name: str, blob_name: str, data: str | bytes, content_settings: Optional[dict] = None
    ) -> None:
        """Sube datos a un blob, creando el contenedor si no existe."""
        logging.info(f"Subiendo blob '{blob_name}' al contenedor '{container_name}'...")
        try:
            blob_client = self._get_blob_client_and_create_container(container_name, blob_name)
            settings = ContentSettings(**content_settings) if content_settings else None
            blob_client.upload_blob(data, overwrite=True, content_settings=settings)
            logging.info(f"Blob '{blob_name}' subido exitosamente.")
        except Exception as e:
            logging.exception(f"FALLO al subir blob '{blob_name}' al contenedor '{container_name}': {e}")
            raise FileProcessingError(f"Fallo al subir blob '{blob_name}' a '{container_name}': {e}") from e # Envuelve

    # @override
    def delete_blob(self, container_name: str, blob_name: str) -> None:
        """Intenta borrar un blob si existe."""
        logging.info(f"Intentando borrar blob '{blob_name}' del contenedor '{container_name}'...")
        try:
            blob_client = self.blob_service_client.get_blob_client(container=container_name, blob=blob_name)
            blob_client.delete_blob(delete_snapshots="include")
            logging.info(f"Blob '{blob_name}' borrado exitosamente.")
        except ResourceNotFoundError:
            logging.warning(f"No se encontró el blob '{blob_name}' para borrar en '{container_name}' (puede que ya se haya movido/borrado).")
            # No lanzamos error aquí, ya que el objetivo "no tener el blob ahí" se cumple.
        except Exception as e:
            logging.exception(f"FALLO al borrar el blob '{blob_name}' del contenedor '{container_name}': {e}")
            raise FileProcessingError(f"Fallo al borrar blob '{blob_name}' de '{container_name}': {e}") from e # Envuelve

    # @override
    def move_blob(self, source_container: str, source_blob_name: str, destination_container: str, destination_blob_name: str) -> None:
         """Copia un blob a una nueva ubicación y borra el original."""
         logging.info(f"Intentando mover blob de '{source_container}/{source_blob_name}' a '{destination_container}/{destination_blob_name}'...")
         source_blob_client = self.blob_service_client.get_blob_client(container=source_container, blob=source_blob_name)

         try:
             # 1. Check if source exists
             if not source_blob_client.exists():
                  logging.warning(f"Blob origen '{source_container}/{source_blob_name}' no encontrado para mover. Posiblemente ya fue procesado o movido.")
                  # Decide si esto es un error fatal. Para este caso, si el origen no existe, no hay nada que mover, puede ser aceptable.
                  # return # No lanzar error si el origen no existe

             # 2. Get destination client (creates container if needed)
             destination_blob_client = self._get_blob_client_and_create_container(destination_container, destination_blob_name)

             # 3. Start copy
             # copy_source_url = f"{source_blob_client.account_url}/{source_container}/{source_blob_name}" # URL requires SAS or public access
             # Better to get the URL directly from the client if possible, or use relative path if client is same account.
             # source_blob_client.url requires Public access or Shared Key.
             # A more robust way using Azure SDK: start_copy_from_url.
             # To get the source URL securely without public access, you'd typically need a SAS token for the source blob.
             # Or, if both source and destination are in the *same storage account* as the connection string implies,
             # a server-side copy can sometimes be done without SAS, depending on SDK version/method.

             # Let's use a simpler approach for demonstration, assuming it's acceptable to read and write (less efficient for large blobs):
             # Read the blob content first.

             logging.info(f"Descargando blob origen '{source_container}/{source_blob_name}' para copiar...")
             blob_data = source_blob_client.download_blob().readall()
             logging.info(f"Descarga completa. Tamaño: {len(blob_data)} bytes.")

             # 4. Upload to destination
             logging.info(f"Subiendo datos a blob destino '{destination_container}/{destination_blob_name}'...")
             # You might want to copy metadata too. Need to fetch source properties.
             source_properties = source_blob_client.get_blob_properties()
             destination_content_settings = ContentSettings(
                 content_type=source_properties.content_settings.content_type,
                 content_encoding=source_properties.content_settings.content_encoding,
                 content_language=source_properties.content_settings.content_language,
                 content_disposition=source_properties.content_settings.content_disposition,
                 cache_control=source_properties.content_settings.cache_control,
                 # metadata=source_properties.metadata # Decide if you want to copy metadata
             )
             # Metadata might need to be handled separately during upload_blob or as a post-upload step
             # For simplicity, let's pass original metadata if available, ensuring it's string keys/values
             copied_metadata = {k: str(v) for k, v in source_properties.metadata.items()} if source_properties.metadata else None


             destination_blob_client.upload_blob(
                blob_data,
                overwrite=True,
                # content_settings=destination_content_settings, # Use ContentSettings object
                metadata=copied_metadata # Pass metadata directly
            )
             logging.info(f"Copia exitosa a '{destination_container}/{destination_blob_name}'.")


             # 5. Delete source
             logging.info(f"Borrando blob origen '{source_container}/{source_blob_name}'...")
             # Use the delete_blob method we already defined, which handles ResourceNotFoundError
             self.delete_blob(source_container, source_blob_name)
             logging.info(f"Blob origen borrado. Movimiento completado.")

         except ResourceNotFoundError:
             # This specifically catches if the *source* blob is not found during the *initial* get_blob_client call or during download
             logging.warning(f"Blob origen '{source_container}/{source_blob_name}' no encontrado para mover. Posiblemente ya fue procesado o movido.")
             # If source not found, the move is effectively done from the perspective of the original blob not being in the source.
             # Decide if this warrants throwing a FileProcessingError or just logging and returning.
             # Let's log and consider it handled (no error raised).
         except Exception as e:
              logging.exception(f"FALLO durante el movimiento de blob '{source_container}/{source_blob_name}': {e}")
              # It's important to log the failure but also raise so the calling function_app knows something went wrong.
              raise FileProcessingError(f"Fallo durante el movimiento de blob de '{source_container}' a '{destination_container}': {e}") from e

```

**11. `src/domain/usecases/interfaces.py`**
(Interfaz para el caso de uso principal - opcional pero buena práctica)

```python
# src/domain/usecases/interfaces.py
from abc import ABC, abstractmethod
from typing import BinaryIO

class ProcessCVUseCaseInterface(ABC):
    """Interfaz para el caso de uso de procesamiento de CV."""

    @abstractmethod
    def execute(self, file_stream: BinaryIO, rank_id: str, candidate_id: str, file_name: str) -> None:
        """
        Ejecuta el proceso completo de análisis de un CV.

        Args:
            file_stream: El flujo binario del archivo CV.
            rank_id: El ID del Rank asociado al CV.
            candidate_id: El ID del Candidato asociado al CV.
            file_name: El nombre original del archivo (para logging/identificación).

        Raises:
            DomainError (o subclase): Si ocurre algún error durante el procesamiento.
        """
        pass
```

**12. `src/domain/usecases/process_cv.py`**
(Aquí se mueve la lógica principal, inyectando interfaces)

```python
# src/domain/usecases/process_cv.py
import logging
import json
from typing import BinaryIO, Dict, Optional, Tuple

# Importar interfaces (dependencias)
from src.interfaces.api_rest_repository_interface import ApiRestRepositoryInterface
from src.interfaces.document_intelligence_interface import DocumentIntelligenceInterface
from src.interfaces.openai_interface import OpenAIInterface
# Nota: El caso de uso NO depende de la interfaz de Blob Storage directamente para leer el input,
# ya que recibe el stream. Tampoco para mover/borrar archivos; esa es responsabilidad de la capa externa.
# Si necesitara interactuar con storage (ej. guardar un archivo temporal), sí importaría BlobStorageInterface.

# Importar entidades y excepciones del dominio
from src.domain.exceptions import (
    DomainError, APIError, AuthenticationError, DocumentIntelligenceError,
    NoContentExtractedError, OpenAIError, JSONValidationError,
    InvalidCVError # Nueva excepción si el inputstream es inválido? O ValueError?
)

# Importar helpers compartidos
from src.shared.prompt_system import prompt_system
from src.shared.validate_process_json import extract_and_validate_cv_data_from_json
from src.shared.promedio_scores import calculate_average_score_from_dict
# Nota: extract_values.py no es necesario en el use case, ya que function_app extrae los IDs.

from src.domain.usecases.interfaces import ProcessCVUseCaseInterface # Importar la interfaz del caso de uso (opcional)

class ProcessCVUseCase(ProcessCVUseCaseInterface): # Implementar la interfaz (opcional)
    """
    Caso de uso para procesar el CV de un candidato.
    Orquesta las llamadas a los servicios externos (API, DI, OpenAI)
    y valida los resultados.
    """

    def __init__(
        self,
        api_repository: ApiRestRepositoryInterface,
        document_intelligence_service: DocumentIntelligenceInterface,
        openai_service: OpenAIInterface,
        # blob_storage_service: BlobStorageInterface # No inyectado aquí según el diseño actual
    ):
        """
        Inicializa el caso de uso con las dependencias inyectadas.

        Args:
            api_repository: Implementación de ApiRestRepositoryInterface.
            document_intelligence_service: Implementación de DocumentIntelligenceInterface.
            openai_service: Implementación de OpenAIInterface.
        """
        if not isinstance(api_repository, ApiRestRepositoryInterface):
             raise TypeError("api_repository debe implementar ApiRestRepositoryInterface")
        if not isinstance(document_intelligence_service, DocumentIntelligenceInterface):
             raise TypeError("document_intelligence_service debe implementar DocumentIntelligenceInterface")
        if not isinstance(openai_service, OpenAIInterface):
             raise TypeError("openai_service debe implementar OpenAIInterface")


        self._api_repository = api_repository
        self._document_intelligence_service = document_intelligence_service
        self._openai_service = openai_service
        # self._blob_storage_service = blob_storage_service # No usado para leer input stream


    # @override # Puedes usar @override si usas Python 3.12+ y lo importas de typing
    def execute(self, file_stream: BinaryIO, rank_id: str, candidate_id: str, file_name: str) -> None:
        """
        Ejecuta la lógica de procesamiento del CV.

        Args:
            file_stream: El flujo binario del archivo CV.
            rank_id: El ID del Rank asociado al CV.
            candidate_id: El ID del Candidato asociado al CV.
            file_name: El nombre original del archivo (para logging/identificación).

        Raises:
            DomainError (o subclase): Si ocurre algún error en cualquiera de los pasos.
            ValueError: Si los IDs iniciales son inválidos (aunque function_app debería validar esto).
        """
        log_prefix = f"[UseCase-ProcessCV][{candidate_id}]"
        logging.info(f"{log_prefix} Iniciando procesamiento para {file_name} (Rank: {rank_id}, Candidate: {candidate_id})")

        # Validar IDs básicos (aunque function_app lo hace, redundancia no es mala aquí)
        if not rank_id or not candidate_id:
             logging.error(f"{log_prefix} IDs de Rank ({rank_id}) o Candidato ({candidate_id}) inválidos.")
             raise ValueError(f"IDs de Rank o Candidato inválidos en el caso de uso.") # Error de Python nativo o crear uno de dominio? ValueError es razonable.

        # Mantener variables para datos intermedios si fueran necesarios para el manejo de errores en la capa externa
        resumen_data: Optional[dict] = None
        extracted_text: Optional[str] = None
        analysis_result_str: Optional[str] = None # JSON crudo de OpenAI

        try:
            # --- Paso 1: Obtener Resumen de API Externa ---
            logging.info(f"{log_prefix} Paso 1: Obteniendo resumen para Rank ID {rank_id}...")
            # La llamada al adaptador lanzará APIError/AuthenticationError si falla
            resumen_data = self._api_repository.get_resumen(id=rank_id)

            profile_description = resumen_data.get("profileDescription")
            variables_content = resumen_data.get("variablesContent")

            if profile_description is None or variables_content is None:
                logging.error(f"{log_prefix} get_resumen no devolvió 'profileDescription' o 'variablesContent' para RankID {rank_id}.")
                # Error de dominio porque la API no cumplió el contrato esperado por el caso de uso
                raise APIError(f"Respuesta de get_resumen incompleta para RankID {rank_id}.")
            logging.info(f"{log_prefix} Resumen de API obtenido.")

            # --- Paso 2: Extraer Texto con Document Intelligence ---
            logging.info(f"{log_prefix} Paso 2: Extrayendo texto del CV con Document Intelligence...")
            # La llamada al adaptador lanzará DocumentIntelligenceError/NoContentExtractedError
            extracted_text = self._document_intelligence_service.analyze_cv(file_stream)

            if not extracted_text or not extracted_text.strip():
                logging.warning(f"{log_prefix} Document Intelligence no extrajo texto o está vacío para {file_name}.")
                # Esto debería ser lanzado por el adaptador, pero verificamos aquí también
                raise NoContentExtractedError(f"Document Intelligence no extrajo contenido del documento.")
            logging.info(f"{log_prefix} Texto extraído exitosamente (longitud: {len(extracted_text)}).")

            # --- Paso 3: Preparar y Llamar a Azure OpenAI ---
            logging.info(f"{log_prefix} Paso 3: Preparando prompt y llamando a Azure OpenAI...")
            system_prompt = prompt_system(
                profile=profile_description,
                criterios=variables_content,
            )
            if not system_prompt:
                logging.error(f"{log_prefix} El prompt generado está vacío.")
                raise ValueError(f"El prompt generado para OpenAI está vacío.")

            # La llamada al adaptador lanzará OpenAIError
            analysis_result_str = self._openai_service.get_completion(
                system_message=system_prompt, user_message=extracted_text
            )

            if not analysis_result_str:
                 logging.warning(f"{log_prefix} Azure OpenAI devolvió una respuesta vacía.")
                 # Esto debería ser lanzado por el adaptador, pero verificamos aquí también
                 raise OpenAIError(f"Azure OpenAI devolvió una respuesta vacía.")

            logging.info(f"{log_prefix} Respuesta de Azure OpenAI obtenida (longitud: {len(analysis_result_str)}).")
            # logging.debug(f"{log_prefix} Respuesta cruda de OpenAI: {analysis_result_str}") # Cuidado con loguear datos sensibles/grandes

            # --- Paso 4: Validar y Procesar JSON de OpenAI ---
            logging.info(f"{log_prefix} Paso 4: Validando y procesando JSON de OpenAI...")
            # La llamada a la función shared lanzará json.JSONDecodeError, TypeError, JSONValidationError
            cv_score, cv_analysis, candidate_name = extract_and_validate_cv_data_from_json(analysis_result_str)

            if cv_score is None or cv_analysis is None or candidate_name is None:
                 # extract_and_validate_cv_data_from_json ya loguea advertencias,
                 # pero lanzamos un error de dominio aquí si los resultados finales no son válidos/completos
                 logging.error(f"{log_prefix} Validación fallida o datos incompletos en JSON de OpenAI.")
                 raise JSONValidationError(f"Validación fallida o datos incompletos en JSON de OpenAI para {file_name}.")
            logging.info(f"{log_prefix} JSON de OpenAI validado exitosamente.")

            # --- Paso 5: Calcular Promedio ---
            logging.info(f"{log_prefix} Paso 5: Calculando promedio de scores...")
            # La llamada a la función shared puede devolver None o lanzar ValueError si el input (cv_score) es inesperado
            promedio_scores = calculate_average_score_from_dict(cv_score)

            if promedio_scores is None:
                logging.error(f"{log_prefix} El cálculo del promedio devolvió None.")
                # Decide si esto es un error fatal. Si cv_score pasó la validación, calculate_average_score_from_dict no debería devolver None.
                # Podría ser un error de lógica o un caso no considerado. Lo tratamos como error de procesamiento.
                raise DomainError(f"El cálculo del promedio de scores falló para {file_name}.")
            logging.info(f"{log_prefix} Promedio de scores calculado: {promedio_scores}")


            # --- Paso 6: Enviar Resultados a API REST Final ---
            logging.info(f"{log_prefix} Paso 6: Enviando resultados finales a la API REST...")

            # 6a. Enviar Scores
            logging.info(f"{log_prefix} Enviando scores detallados a la API...")
            # La llamada al adaptador lanzará APIError/AuthenticationError
            self._api_repository.add_scores(candidate_id=candidate_id, scores=cv_score)
            logging.info(f"{log_prefix} Scores detallados enviados.")


            # 6b. Guardar Resumen Completo
            logging.info(f"{log_prefix} Guardando resumen completo en la API...")
            # La llamada al adaptador lanzará APIError/AuthenticationError
            self._api_repository.save_resumen(
                candidate_id=candidate_id,
                transcription=extracted_text, # Se guarda la transcripción completa
                score=promedio_scores,
                analysis=cv_analysis,
                candidate_name=candidate_name
            )
            logging.info(f"{log_prefix} Resumen completo guardado.")

            # 6c. Marcar como Procesado Exitosamente (sin mensaje de error)
            logging.info(f"{log_prefix} Marcando candidato como procesado exitosamente en la API...")
            # La llamada al adaptador lanzará APIError/AuthenticationError
            self._api_repository.update_candidate(
                candidate_id=candidate_id,
                error_message=None # Indicar éxito borrando el error
            )
            logging.info(f"{log_prefix} Candidato marcado como exitoso.")


            logging.info(f"{log_prefix} *** Procesamiento de CV COMPLETADO EXITOSAMENTE para {file_name} ***")

        except (DomainError, ValueError, json.JSONDecodeError, TypeError) as e:
             # Capturar todas las excepciones de dominio (y algunas nativas esperadas como JSONDecodeError/TypeError de json.loads)
             # relanzarlas para que la capa externa (function_app) las maneje
             logging.error(f"{log_prefix} Error durante el procesamiento del CV: {e}", exc_info=True)
             raise e # Relanza la excepción original

        # No hay bloque finally aquí. El manejo de archivos (borrar/mover) es responsabilidad de function_app.

```

**13. `function_app.py`**
(Este archivo se vuelve el punto de entrada de la Function App, orquestador y manejador de errores de aplicación)

```python
# function_app.py
import logging
import os
import json
from typing import Optional, Tuple
from azure.storage.blob import BlobServiceClient, ContentSettings, BlobClient # Necesario para inicializar el adaptador
import azure.functions as func

# Importar interfaces para typing hints y para que el caso de uso dependa de ellas
from src.interfaces.api_rest_repository_interface import ApiRestRepositoryInterface
from src.interfaces.document_intelligence_interface import DocumentIntelligenceInterface
from src.interfaces.openai_interface import OpenAIInterface
from src.interfaces.key_vault_interface import KeyVaultInterface
from src.interfaces.blob_storage_interface import BlobStorageInterface

# Importar implementaciones CONCRETAS de la infraestructura para INYECTAR
from src.infrastructure.api_rest.api_rest_adapter import RestApiAdapter
from src.infrastructure.ocr.document_intelligence_adapter import DocumentIntelligenceAdapter
from src.infrastructure.ocr.azure_openai_adapter import AzureOpenAIAdapter
from src.infrastructure.key_vault.key_vault_client import KeyVaultClient
from src.infrastructure.storage.blob_storage_adapter import BlobStorageAdapter # Nuevo adaptador

# Importar el caso de uso (la lógica de negocio)
from src.domain.usecases.process_cv import ProcessCVUseCase
from src.domain.usecases.interfaces import ProcessCVUseCaseInterface # Importar la interfaz del caso de uso (opcional)

# Importar excepciones de dominio para atraparlas y manejarlas
from src.domain.exceptions import (
    DomainError, APIError, AuthenticationError, KeyVaultError,
    SecretNotFoundError, DocumentIntelligenceError, NoContentExtractedError,
    OpenAIError, JSONValidationError, FileProcessingError
)

# Importar helpers compartidos necesarios en function_app (para IDs)
from src.shared.extract_values import get_id_candidate, get_id_rank

# --- Constantes ---
CONNECTION_STRING_ENV_VAR = "AzureWebJobsStorage"
KEY_VAULT_NAME_ENV_VAR = "VaultName" # Cambiado a 'VaultName' para que KeyVaultClient construya la URI
# NOTA: Asegúrate de que tu variable de entorno para Key Vault ahora contenga SOLO el nombre del vault, no la URI completa.

CANDIDATES_CONTAINER = "candidates"
# Contenedores de destino para resultados/errores, manejados por BlobStorageAdapter
RESULTS_POST_OPENAI_CONTAINER = "resultados-post-openai" # Para resultados intermedios/errores post-OpenAI
MANUAL_ERROR_CONTAINER = "error" # Para errores tempranos/críticos

# Identificador para este proceso/función
FUNCTION_PROCESS_TYPE = "FUNCTION-IARC"

# --- Nombres Secretos Key Vault ---
SECRET_NAMES = {
    "openai_endpoint": "OpenAI--URL",
    "openai_api_version": "OpenAI--ApiVersion",
    "openai_model": "OpenAI--Model", # Este modelo no se usa si usas deployment_name
    "openai_deployment": "OpenAI--Deployment", # Asegúrate de que este sea el nombre correcto de la implementación
    # Credenciales de SPN para Entra ID, pueden no ser necesarias si usas DefaultAzureCredential (preferido en Azure Functions)
    # Pero si tu setup requiere SPN, descomentar y obtener estos secretos:
    # "client_id": "AzureAd--ClientId",
    # "client_secret": "AzureAd--ClientSecret",
    # "tenant_id": "AzureAd--TenantId",
    "docintel_api_key": "DocumentIntelligence--ApiKey",
    "docintel_endpoint": "DocumentIntelligence--URL",
    "rest_api_username": "Jwt--User",
    "rest_api_password": "Jwt--Password",
    "rest_api_base_url": "ApiServices--IARC--Backend", # Mover URL de API a Key Vault también
    "rest_api_role": "ApiServices--IARC--Role", # Mover Role de API a Key Vault también
    "rest_api_user_app": "ApiServices--IARC--UserFunction", # Mover UserApp de API a Key Vault también
}
# NOTA: Se movieron más secretos a Key Vault según tu estructura, eliminando las variables de entorno correspondientes en el adaptador.

app = func.FunctionApp(http_auth_level=func.AuthLevel.FUNCTION)

# --- Trigger Principal del Blob ---
@app.blob_trigger(
    arg_name="inputblob",
    path="candidates/{name}",
    connection=CONNECTION_STRING_ENV_VAR, # Usar la constante
)
def process_candidate_cv(inputblob: func.InputStream):
    """
    Azure Function trigger para procesar un CV.
    Es la capa externa que inicializa dependencias y llama al caso de uso.
    Maneja errores de aplicación (logging, API status, movimiento de blobs).
    """
    log_prefix = f"[{FUNCTION_PROCESS_TYPE}]"

    if not inputblob or not inputblob.name:
        logging.error(f"{log_prefix} Disparador de blob invocado sin blob o nombre válido.")
        return

    # Extraer container/blob name y validate path
    try:
        # inputblob.name suele ser 'container/blobname'
        parts = inputblob.name.split('/', 1)
        if len(parts) != 2:
            logging.error(f"{log_prefix} Formato de ruta de blob inesperado: {inputblob.name}")
            return

        container_from_path, blob_name_from_path = parts
        if container_from_path.lower() != CANDIDATES_CONTAINER.lower():
             logging.warning(f"{log_prefix} Blob '{inputblob.name}' no está en el contenedor esperado '{CANDIDATES_CONTAINER}'. Ignorando.")
             return

        file_name = os.path.basename(blob_name_from_path) # Nombre del archivo sin ruta del contenedor
        blob_full_path = inputblob.name # Mantener path completo para logs

        # Ignorar blobs en subdirectorios dentro de 'candidates'
        if "/" in blob_name_from_path:
            logging.warning(f"{log_prefix} Ignorando blob en subdirectorio: {blob_full_path}")
            return

    except Exception as e:
        # Capturar cualquier error durante el parseo inicial del path del blob
        logging.error(f"{log_prefix} Error al parsear la ruta del blob '{inputblob.name}': {e}", exc_info=True)
        return # No podemos continuar si ni siquiera sabemos el nombre del archivo correctamente

    logging.info(f"{log_prefix} --- Iniciando procesamiento para: {file_name} (Tamaño: {inputblob.length} Bytes) ---")

    # Variables para almacenar instancias de adaptadores y IDs
    candidate_id: Optional[str] = None # Inicializamos a None
    rank_id: Optional[str] = None       # Inicializamos a None
    rest_api_adapter: Optional[ApiRestRepositoryInterface] = None
    blob_storage_adapter: Optional[BlobStorageInterface] = None
    # No necesitamos almacenar los otros adaptadores aquí, solo se usan para crear el use case.

    processed_successfully = False # Flag de éxito final

    try:
        # --- Obtener IDs Temprano ---
        # Esto es lo primero que necesitamos y lo usamos en los logs y en los handlers de error.
        rank_id = get_id_rank(file_name)
        candidate_id = get_id_candidate(file_name)

        # Si no podemos obtener los IDs básicos, es un error crítico que no puede reportarse a la API con un candidate_id válido
        if not rank_id or not candidate_id:
             error_reason = f"No se pudieron extraer rank_id o candidate_id del nombre de archivo: {file_name}. Formato esperado: RankID_CandidateID_..."
             logging.critical(f"{log_prefix} {error_reason}")
             # En este caso, no podemos actualizar la API. Intentaremos mover el blob a error si es posible.
             # Necesitamos el BlobStorageAdapter incluso para esto.
             # La inicialización del BlobStorageAdapter necesita la conexión de almacenamiento.

             # --- Inicializar Blob Storage para manejo de errores tempranos ---
             storage_connection_string = os.environ.get(CONNECTION_STRING_ENV_VAR)
             if not storage_connection_string:
                  logging.critical(f"{log_prefix} CRÍTICO: Variable de entorno '{CONNECTION_STRING_STRING}' no encontrada. No se puede inicializar Blob Storage para manejo de errores.")
                  # No podemos hacer nada más si la conexión de storage falta.
                  return # Salir de la función
             blob_storage_adapter = BlobStorageAdapter(connection_string=storage_connection_string)
             # Si la inicialización falla, lanzará una excepción que será capturada abajo.

             # Ahora que tenemos el adaptador de Storage, intentamos mover el blob a error.
             # Usamos el nombre de archivo original, aunque no tengamos IDs válidos.
             try:
                 error_blob_name = f"invalid_filename_{file_name}" # Nombre indicativo en el contendor de error
                 blob_storage_adapter.move_blob(
                     source_container=CANDIDATES_CONTAINER,
                     source_blob_name=file_name,
                     destination_container=MANUAL_ERROR_CONTAINER,
                     destination_blob_name=error_blob_name
                 )
                 logging.info(f"{log_prefix} Blob original movido a '{MANUAL_ERROR_CONTAINER}/{error_blob_name}' debido a nombre de archivo inválido.")
             except Exception as move_err:
                 logging.critical(f"{log_prefix} CRÍTICO: Falló el movimiento del blob original '{file_name}' al contenedor de error después de detectar nombre inválido: {move_err}", exc_info=True)
                 # Si falla mover a error, el blob original queda en 'candidates'. Se loguea críticamente.

             # Como no tenemos candidate_id, no podemos actualizar la API.
             return # Salir de la función

        # Si llegamos aquí, los IDs son válidos. Continuamos con la inicialización completa.
        logging.info(f"{log_prefix} IDs extraídos: Rank={rank_id}, Candidate={candidate_id}")

        # --- Inicializar Adaptadores ---
        # Obtener cadenas de conexión y URIs de entorno
        storage_connection_string = os.environ.get(CONNECTION_STRING_ENV_VAR)
        if not storage_connection_string:
            raise ValueError(f"{log_prefix} - Variable de entorno '{CONNECTION_STRING_ENV_VAR}' no encontrada.")

        kv_name = os.environ.get(KEY_VAULT_NAME_ENV_VAR)
        if not kv_name:
            raise ValueError(f"{log_prefix} - Variable de entorno '{KEY_VAULT_NAME_ENV_VAR}' (Nombre del Key Vault) no encontrada.")


        logging.info(f"{log_prefix} Inicializando Blob Storage Adapter...")
        blob_storage_adapter = BlobStorageAdapter(connection_string=storage_connection_string)
        logging.info(f"{log_prefix} Blob Storage Adapter inicializado.")

        logging.info(f"{log_prefix} Inicializando Key Vault Client y obteniendo secretos...")
        # La inicialización de KeyVaultClient ya construye la URI y puede lanzar AuthenticationError/KeyVaultError
        kv_client: KeyVaultInterface = KeyVaultClient(kv_name=kv_name) # Usar la interfaz como tipo

        # Obtener todos los secretos necesarios
        secrets = {}
        try:
            for key, secret_name in SECRET_NAMES.items():
                logging.debug(f"{log_prefix} Obteniendo secreto: {secret_name} (para {key})")
                # get_secret puede lanzar SecretNotFoundError, KeyVaultError, AuthenticationError
                secret_value = kv_client.get_secret(secret_name)
                secrets[key] = secret_value
            logging.info(f"{log_prefix} Secretos de Key Vault obtenidos exitosamente.")

        except (SecretNotFoundError, KeyVaultError, AuthenticationError) as e:
             # Si falla obtener secretos, no podemos inicializar adaptadores downstream.
             # Logueamos críticamente y relanzamos para que el bloque except principal lo capture.
             logging.critical(f"{log_prefix} CRÍTICO: Falló la obtención de secretos de Key Vault: {e}", exc_info=True)
             raise # Relanzar el error de dominio específico


        # Ahora inicializar los otros adaptadores con los secretos obtenidos
        logging.info(f"{log_prefix} Inicializando adaptadores de servicios externos...")

        try:
            # Adaptador Document Intelligence
            doc_intel_adapter: DocumentIntelligenceInterface = DocumentIntelligenceAdapter(
                api_key=secrets["docintel_api_key"],
                endpoint=secrets["docintel_endpoint"]
            )
            logging.info(f"{log_prefix} Document Intelligence Adapter inicializado.")

            # Adaptador Azure OpenAI
            # Pasar credenciales de SPN si existen en secretos, de lo contrario, el adaptador usará DefaultAzureCredential
            openai_adapter: OpenAIInterface = AzureOpenAIAdapter(
                endpoint=secrets["openai_endpoint"],
                api_version=secrets["openai_api_version"],
                deployment=secrets["openai_deployment"],
                client_id=secrets.get("client_id"), # Usar .get() para que sea None si no existe
                client_secret=secrets.get("client_secret"),
                tenant_id=secrets.get("tenant_id"),
            )
            logging.info(f"{log_prefix} Azure OpenAI Adapter inicializado.")

            # Adaptador API REST
            # Usar secretos de Key Vault para URL, User, Pass, Role, UserApp
            rest_api_adapter: ApiRestRepositoryInterface = RestApiAdapter(
                base_url_env_var=None, # Indicar al adaptador que NO lea la URL de ENV
                username=secrets["rest_api_username"],
                password=secrets["rest_api_password"],
                role_env_var=None, # Indicar al adaptador que NO lea el Role de ENV
                user_app_env_var=None, # Indicar al adaptador que NO lea el UserApp de ENV
            )
            # Asignar la base_url, role, user_application directamente desde secrets obtenidos.
            # Esto requiere que el constructor de RestApiAdapter acepte estos valores o tenga un método para asignarlos.
            # Modifiqué el constructor de RestApiAdapter para aceptar estos valores inyectados directamente,
            # invalidando el uso de variables de entorno por defecto si se inyectan.
            rest_api_adapter.base_url = secrets["rest_api_base_url"]
            rest_api_adapter.role = secrets["rest_api_role"]
            rest_api_adapter.user_application = secrets["rest_api_user_app"]

            # Validar que los valores asignados no sean nulos/vacíos después de obtenerlos de secrets
            missing_api_secrets = []
            if not rest_api_adapter.base_url: missing_api_secrets.append("ApiServices--IARC--Backend")
            if not rest_api_adapter.role: missing_api_secrets.append("ApiServices--IARC--Role")
            if not rest_api_adapter.user_application: missing_api_secrets.append("ApiServices--IARC--UserFunction")

            if missing_api_secrets:
                 raise SecretNotFoundError(f"Secretos de API REST esenciales faltan o están vacíos en Key Vault: {', '.join(missing_api_secrets)}")


            logging.info(f"{log_prefix} REST API Adapter inicializado.")


        except (ValueError, AuthenticationError, DomainError) as e:
             # Capturar errores durante la inicialización de adaptadores downstream
             # ValueErrors aquí indicarían secretos vacíos/inválidos pasados a los constructores.
             # AuthenticationErrors/DomainErrors de los constructores de adaptadores.
             logging.critical(f"{log_prefix} CRÍTICO: Falló la inicialización de adaptadores de servicios externos: {e}", exc_info=True)
             raise # Relanzar para que el bloque except principal lo capture

        # --- Inicializar el Caso de Uso ---
        logging.info(f"{log_prefix} Inicializando Caso de Uso ProcessCV...")
        # Inyectar las implementaciones CONCRETAS de los adaptadores al caso de uso,
        # que espera las INTERFACES. Esto es Inversión de Control.
        process_cv_use_case: ProcessCVUseCaseInterface = ProcessCVUseCase(
            api_repository=rest_api_adapter,
            document_intelligence_service=doc_intel_adapter,
            openai_service=openai_adapter,
            # blob_storage_service=blob_storage_adapter # No inyectado en el caso de uso
        )
        logging.info(f"{log_prefix} Caso de Uso ProcessCV inicializado.")


        # --- Ejecutar el Caso de Uso ---
        logging.info(f"{log_prefix} Ejecutando Caso de Uso ProcessCV...")
        # El caso de uso procesará el stream y llamará a los adaptadores internos.
        # Si algo falla DENTRO del caso de uso, lanzará una excepción de dominio.
        process_cv_use_case.execute(
            file_stream=inputblob, # Pasar el stream de Azure Functions
            rank_id=rank_id,
            candidate_id=candidate_id,
            file_name=file_name
        )

        # Si la ejecución del caso de uso llega hasta aquí sin lanzar excepción, fue exitosa.
        processed_successfully = True
        logging.info(f"{log_prefix} Caso de Uso ProcessCV completado sin errores.")


    # --- Manejo Centralizado de Errores (a nivel de Frameworks & Drivers) ---
    # Capturamos cualquier excepción lanzada por el bloque try (inicialización o caso de uso).
    except Exception as error:
        # Ya sea un error de inicialización (KeyVaultError, AuthenticationError, ValueError, FileProcessingError)
        # o un error de procesamiento dentro del caso de uso (DomainError, APIError, DIError, OpenAIError, JSONValidationError, etc.)
        error_type = type(error).__name__
        error_details = f"{error_type}: {error}"
        logging.exception(f"{log_prefix} ¡Error atrapado durante el procesamiento de {file_name}! Detalles: {error_details}") # Loguear el error completo

        # 1. Intentar actualizar el estado en la API (SI el adaptador de API fue inicializado y tenemos candidate_id)
        if rest_api_adapter and candidate_id:
            try:
                logging.info(f"{log_prefix} Intentando actualizar estado de error en API para candidate_id: {candidate_id}...")
                # Limitar el mensaje de error para no exceder límites de la API
                api_error_message = f"Error durante el procesamiento del CV: {error_details}"[:1000]
                rest_api_adapter.update_candidate(candidate_id=candidate_id, error_message=api_error_message)
                logging.info(f"{log_prefix} Estado de error actualizado en API para candidate_id: {candidate_id}.")
            except Exception as api_err:
                # Si falla la actualización de la API, loguear pero no detener el proceso de manejo de errores
                logging.error(f"{log_prefix} FALLO CRÍTICO al actualizar estado de error en API para candidate_id {candidate_id}: {api_err}", exc_info=True)
        elif candidate_id:
             logging.warning(f"{log_prefix} No se pudo actualizar API: rest_api_adapter no disponible.")
        else:
             # Esto ya fue manejado al inicio si candidate_id no se extrajo.
             logging.warning(f"{log_prefix} No se pudo actualizar API: candidate_id no disponible.")


        # 2. Intentar mover el blob original al contenedor de error (SI el adaptador de Storage fue inicializado)
        if blob_storage_adapter:
            try:
                logging.info(f"{log_prefix} Intentando mover blob original a '{MANUAL_ERROR_CONTAINER}'...")
                # Decide un nombre para el blob en el contenedor de error.
                # Puedes incluir el tipo de error o un timestamp.
                error_blob_name = f"{file_name}.error_{error_type}" # Nombre original + .error_TipoDeError
                blob_storage_adapter.move_blob(
                    source_container=CANDIDATES_CONTAINER,
                    source_blob_name=file_name,
                    destination_container=MANUAL_ERROR_CONTAINER,
                    destination_blob_name=error_blob_name
                )
                logging.info(f"{log_prefix} Blob original '{file_name}' movido a '{MANUAL_ERROR_CONTAINER}/{error_blob_name}'.")
            except Exception as move_err:
                logging.critical(f"{log_prefix} CRÍTICO: Falló el movimiento del blob original '{file_name}' al contenedor de error: {move_err}", exc_info=True)
                # Si falla mover a error, el blob original queda en 'candidates'. Esto requiere atención manual.
        else:
            logging.critical(f"{log_prefix} CRÍTICO: BlobStorageAdapter no disponible. No se puede mover el blob original a error. El blob original '{file_name}' permanece en '{CANDIDATES_CONTAINER}'.")


        # 3. En este diseño, no intentamos guardar resultados intermedios detallados post-OpenAI en el bloque except.
        # La complejidad de determinar qué datos estaban disponibles (resumen_data, extracted_text, analysis_result_str)
        # y cómo guardarlos en la capa externa rompe la separación de responsabilidades.
        # Si guardar resultados intermedios es CRÍTICO, hay varias opciones:
        #    a) Que el caso de uso capture errores internos, guarde datos intermedios *usando un BlobStorageInterface inyectado*
        #       y luego relance un error de dominio para que function_app sepa que falló (pero los intermedios ya están).
        #    b) Que el caso de uso devuelva los datos intermedios *junto con la excepción* en un objeto de error personalizado,
        #       y function_app use esos datos para guardarlos.
        #    c) Simplificar: solo se mueve el archivo original a error y se reporta el error a la API.
        # La opción (c) es la más limpia para empezar. La opción (a) es más Clean, pero añade complejidad.
        # Vamos con la (c) por ahora, que es similar a lo que _handle_processing_error hacía (solo movía el original).
        # La lógica de _save_intermediate_result_and_cleanup se elimina para simplificar la capa externa.


    finally:
        # --- Limpieza Final (Borrar blob original solo si fue exitoso) ---
        if processed_successfully and blob_storage_adapter:
            logging.info(f"{log_prefix} Proceso exitoso. Intentando borrar blob original...")
            try:
                 blob_storage_adapter.delete_blob(CANDIDATES_CONTAINER, file_name)
                 logging.info(f"{log_prefix} Blob original '{file_name}' borrado exitosamente de '{CANDIDATES_CONTAINER}'.")
            except Exception as delete_err:
                 logging.critical(f"{log_prefix} CRÍTICO: FALLO al borrar el blob original '{file_name}' después de un procesamiento exitoso: {delete_err}", exc_info=True)
                 # Si falla el borrado final, el blob original queda. Requiere atención manual.

        elif not processed_successfully:
             # La lógica de manejo de errores (el bloque 'except') ya intentó mover o borrar el blob.
             # Aquí solo logueamos que el blob original no se borra en este bloque porque no fue exitoso.
             logging.warning(f"{log_prefix} El proceso no fue exitoso. La gestión del blob original se manejó en el bloque 'except'.")
             # Opcional: añadir un check para ver si el blob original todavía existe
             # (esto ya está en el finally original, podrías adaptarlo usando blob_storage_adapter)
             # if blob_storage_adapter:
             #      try:
             #          # Esto podría requerir un método exists() en el adaptador o acceder al BlobServiceClient subyacente.
             #          # O crear un cliente temporal si no se añade exists() al adaptador.
             #          # Por simplicidad, omitimos el check aquí a menos que sea estrictamente necesario.
             #          pass
             #      except Exception as check_err:
             #          logging.error(f"{log_prefix} Error al verificar existencia del blob original después de fallo: {check_err}")


        logging.info(f"{log_prefix} --- Finalizando procesamiento para: {file_name} ---")

```

**14. `requirements.txt`**
(Debe seguir siendo el mismo que proporcionaste, ya que las dependencias de paquetes no cambian, solo la estructura interna y el código que usa esos paquetes.)

```txt
# DO NOT include azure-functions-worker in this file
# The Python Worker is managed by Azure Functions platform
# Manually managing azure-functions-worker may cause unexpected issues

openai
python-dotenv # Aunque no se usa en el código final, si se usara para carga local, se mantiene
azure-core
azure-ai-documentintelligence
azure-functions
azure-storage-blob
azure-identity # Necesario para DefaultAzureCredential y ClientSecretCredential
azure-keyvault-secrets # Necesario para SecretClient

```

**15. `.env.example`**
(Actualizado para reflejar los nombres de variables de entorno y la clave de Key Vault.)

```ini
# Azure Functions Configuration
FUNCTIONS_WORKER_RUNTIME=python

# Application Insights
# Configura esto para habilitar telemetría (logging, etc.)
APPLICATIONINSIGHTS_CONNECTION_STRING="<Your Application Insights Connection String>"

# Azure Blob Storage
# Cadena de conexión para la cuenta de almacenamiento principal (donde están los blobs trigger)
AzureWebJobsStorage="<Your Storage Account Connection String>"

# Azure Key Vault
# El NOMBRE de tu Key Vault (ej. "my-super-vault-prod").
# La función debe tener permisos 'Get' para Secrets en este Key Vault.
VaultName="<Your Key Vault Name>"

# --- Secretos que DEBEN estar en el Key Vault especificado por VaultName ---
# OpenAI--URL=<Your OpenAI Endpoint URL> (ej. https://your-resource-name.openai.azure.com/)
# OpenAI--ApiVersion=<Your OpenAI API Version> (ej. 2023-05-15)
# OpenAI--Deployment=<Your OpenAI Deployment Name> (ej. gpt-4-deployment)
# DocumentIntelligence--ApiKey=<Your DI API Key>
# DocumentIntelligence--URL=<Your DI Endpoint URL> (ej. https://your-di-resource.cognitiveservices.azure.com/)
# Jwt--User=<API Username>
# Jwt--Password=<API Password>
# ApiServices--IARC--Backend=<REST API Base URL> (ej. https://your-backend.azurewebsites.net/api)
# ApiServices--IARC--Role=<API User Role> (ej. IARCFuncRole)
# ApiServices--IARC--UserFunction=<API User Application> (ej. IARCService)

# --- Opcional: Credenciales de Entidad de Servicio para OpenAI si DefaultAzureCredential no funciona ---
# Si tu Azure Function USA Managed Identity, DefaultAzureCredential DEBERÍA funcionar y estos no son necesarios.
# Si no usa Managed Identity o necesitas SPN específicos, descomenta y configura en Key Vault:
# AzureAd--ClientId=<Your Service Principal Client ID>
# AzureAd--ClientSecret=<Your Service Principal Client Secret>
# AzureAd--TenantId=<Your Azure Tenant ID>

```

**16. `README.md`**
(Documentación para la nueva estructura y despliegue sin permisos de admin)

```markdown
# Procesamiento de CV con Azure Functions y IA (Clean Architecture)

Este proyecto implementa un flujo de procesamiento de CV utilizando Azure Functions, Azure AI Document Intelligence, Azure OpenAI y una API REST externa, siguiendo principios de Clean Architecture. La Función se activa por la subida de archivos en Azure Blob Storage.

## Arquitectura

El proyecto sigue una estructura inspirada en Clean Architecture para separar las preocupaciones y mejorar la mantenibilidad:

- **Frameworks & Drivers (function_app.py):** La capa más externa. Contiene el punto de entrada de la Azure Function (el disparador de blob). Se encarga de la configuración inicial (variables de entorno, secretos de Key Vault), la inicialización de los adaptadores de infraestructura concretos, la inyección de estos en el caso de uso y la orquestación de la llamada al caso de uso principal. Maneja las excepciones a nivel de aplicación, incluyendo el reporte de errores a la API y el movimiento/eliminación de blobs.
- **Infrastructure (infrastructure/):** Contiene las implementaciones concretas (adaptadores) para interactuar con servicios externos como Azure Blob Storage, Azure Key Vault, Azure AI Document Intelligence, Azure OpenAI y la API REST externa. Estos adaptadores implementan las interfaces definidas en la capa `interfaces`.
- **Interfaces (interfaces/):** Define contratos (interfaces abstractas) que son usados por la capa de Dominio/Casos de Uso. La capa de Infraestructura implementa estas interfaces. Esto permite que la lógica de negocio sea independiente de los detalles de implementación de la infraestructura.
- **Domain (domain/):** El núcleo de la aplicación. Contiene:
  - `entities/`: Modelos de datos de negocio (ej. `ApiCredentials`).
  - `exceptions.py`: Excepciones personalizadas del dominio.
  - `usecases/`: La lógica de negocio específica de la aplicación (el "qué" hace el sistema). `process_cv.py` es el caso de uso principal que orquesta los pasos del procesamiento de CV, dependiendo _únicamente_ de las interfaces.
- **Shared (shared/):** Contiene funciones de utilidad o helpers que pueden ser usadas transversalmente por varias capas, sin tener lógica de negocio compleja ni interactuar con servicios externos.

La regla clave de dependencia es que las dependencias siempre fluyen hacia adentro. Las capas exteriores (Frameworks, Infrastructure) dependen de las interiores (Interfaces, Domain), pero las capas interiores nunca dependen de las exteriores.

## Requisitos

- Una cuenta de Azure.
- Recursos de Azure configurados:
  - Azure Storage Account (con un contenedor `candidates` para los blobs de entrada y contenedores para resultados/errores como `resultados-post-openai` y `error`).
  - Azure Key Vault (con los secretos listados en `.env.example`).
  - Azure AI Document Intelligence Resource.
  - Azure OpenAI Resource (con un deployment configurado).
  - Una API REST externa con los endpoints esperados.
  - Una Identidad Administrada para la Azure Function (recomendado) con permisos para "Get" Secrets en Key Vault y roles adecuados para Document Intelligence y Azure OpenAI.
- Python 3.12 compatible con el runtime de Azure Functions v2.
- Las bibliotecas listadas en `requirements.txt`.

**Nota:** Este proyecto está diseñado para desplegarse y ejecutarse en el entorno de Azure Functions. La ejecución local puede requerir configuraciones adicionales (como Azure CLI o VS Code extensiones logueadas con credenciales con permisos) para que `DefaultAzureCredential` funcione. No se requiere instalación de herramientas con permisos de administrador en la máquina local del usuario para _desarrollar_ el código, pero sí para _desplegar_ la función o configurar el entorno de Azure. Sin embargo, la estructura del código en sí misma no requiere permisos elevados para su simple lectura y edición.

## Configuración

1.  Clona el repositorio.
2.  Crea un archivo `.env` en la raíz del proyecto basado en `.env.example`.
3.  Configura las variables de entorno y asegúrate de que los secretos correspondientes existan en tu Azure Key Vault. La Azure Function necesitará una identidad con permisos para acceder a Key Vault.

    - `FUNCTIONS_WORKER_RUNTIME`: `python`
    - `APPLICATIONINSIGHTS_CONNECTION_STRING`: Cadena de conexión de tu Application Insights (para logs y monitoreo).
    - `AzureWebJobsStorage`: Cadena de conexión de tu Azure Storage Account.
    - `VaultName`: El nombre de tu Azure Key Vault.

4.  Asegúrate de que los secretos en Key Vault coincidan con los nombres listados en `SECRET_NAMES` dentro de `function_app.py` y en la sección de secretos de `.env.example`.

## Despliegue

El despliegue se realiza a través de las herramientas estándar de Azure Functions (Azure CLI, Azure Portal, VS Code Extension). No requiere permisos de administrador en tu máquina local más allá de lo necesario para usar esas herramientas.

1.  Asegúrate de tener Azure Functions Core Tools instalado (esto _podría_ requerir permisos de administrador dependiendo de la instalación, pero la ejecución del _código Python_ dentro de la función no los requiere).
2.  Configura la conexión de la Azure Function a tu Key Vault y asigna la identidad administrada con los roles necesarios.

## Funcionamiento

1.  La Azure Function `process_candidate_cv` se dispara automáticamente cuando un nuevo blob (archivo) es subido al contenedor `candidates` de la cuenta de almacenamiento especificada en `AzureWebJobsStorage`.
2.  La función extrae el ID del Rank y del Candidato del nombre del archivo (se espera el formato `RankID_CandidateID_...`). Si el nombre es inválido, el archivo se mueve a un contenedor de error.
3.  Obtiene las credenciales necesarias y la configuración (endpoints, claves/secretos) desde Azure Key Vault utilizando `azure-identity` (preferiblemente a través de la Identidad Administrada de la Función).
4.  Inicializa los adaptadores de infraestructura (API REST, Document Intelligence, OpenAI, Blob Storage) con la configuración obtenida.
5.  Inicializa el caso de uso `ProcessCVUseCase`, inyectándole los adaptadores de infraestructura (como implementaciones de sus respectivas interfaces).
6.  Ejecuta el caso de uso, pasándole el flujo del blob de entrada y los IDs extraídos.
7.  El caso de uso orquesta la lógica de negocio:
    - Llama a la API REST para obtener el resumen del perfil.
    - Usa Document Intelligence para extraer el texto del CV.
    - Prepara un prompt para OpenAI usando el resumen y el texto extraído.
    - Llama a Azure OpenAI para obtener el análisis y puntuación del CV en formato JSON.
    - Valida y extrae los datos del JSON de OpenAI.
    - Calcula el promedio de las puntuaciones.
    - Llama a la API REST para guardar los scores detallados, el resumen completo del análisis y actualizar el estado del candidato.
8.  Si el caso de uso se completa sin errores, la función principal borra el blob original del contenedor `candidates` usando el `BlobStorageAdapter`.
9.  Si ocurre algún error en cualquier etapa (inicialización de adaptadores, obtención de secretos, dentro del caso de uso), la función principal:
    - Loguea el error detalladamente (incluyendo Application Insights si está configurado).
    - Intenta actualizar el estado del candidato en la API REST con un mensaje de error (si fue posible inicializar el adaptador de API y obtener el candidate_id).
    - Intenta mover el blob original al contenedor `error` usando el `BlobStorageAdapter`.

## Manejo de Errores

- Las excepciones específicas de dominio (`DomainError`, `APIError`, `SecretNotFoundError`, `OpenAIError`, etc.) se usan para indicar fallos controlados en las capas de Dominio e Infraestructura.
- `function_app.py` atrapa `Exception` para capturar cualquier tipo de fallo (incluyendo errores inesperados), loguea, reporta a la API (si es posible) y mueve el blob original a un contenedor de error.
- Los errores de autenticación con servicios de Azure (Key Vault, DI, OpenAI) o la API REST se envuelven en la excepción de dominio `AuthenticationError`.
- Si el nombre del archivo no permite extraer los IDs de Rank y Candidato, el procesamiento se detiene temprano, se loguea un error crítico y se intenta mover el archivo original al contenedor `error`. En este caso, no se puede actualizar el estado en la API.
- Si falla la obtención de secretos esenciales de Key Vault o la inicialización de un adaptador crítico (Storage, Key Vault, DI, OpenAI, API), el procesamiento se detiene y se intenta mover el blob a error (si Blob Storage Adapter se pudo inicializar) y reportar a la API (si REST API Adapter se pudo inicializar).

Este diseño centraliza el manejo de la _reacción_ al error (log, API update, blob move) en la capa externa (`function_app.py`), mientras que la _causa_ del error se propaga desde las capas internas a través de excepciones de dominio.
```

---

**Resumen de Cambios y Beneficios:**

- **Separación de Responsabilidades:** `function_app.py` se encarga de la entrada/salida y orquestación de alto nivel. `ProcessCVUseCase` contiene la lógica de negocio paso a paso. Los adaptadores se encargan de la comunicación con sistemas externos.
- **Inversión de Control:** El caso de uso recibe sus dependencias (adaptadores) a través de su constructor, dependiendo de interfaces, no de implementaciones concretas. Esto facilita las pruebas unitarias del caso de uso (inyectando mocks de las interfaces).
- **Mejor Mantenibilidad:** Los cambios en un adaptador (ej. cambiar la biblioteca HTTP) no afectan al caso de uso. Los cambios en la lógica de negocio afectan principalmente al caso de uso. Los cambios en el disparador (ej. pasar a Queue Trigger) afectarían solo a `function_app.py`.
- **Manejo de Errores Consistente:** Se usan excepciones de dominio claras que se propagan hacia afuera. `function_app.py` tiene un punto central para atrapar estas excepciones y realizar acciones de alto nivel (reporte, archivo). Se elimina la lógica de manejo de errores compleja dentro de la función principal.
- **Clarity:** El flujo principal en `function_app.py` es ahora mucho más legible: inicializar -> llamar caso de uso -> manejar resultado/error.

Este diseño está mucho más alineado con los principios de Clean Architecture y te permitirá hacer cambios o añadir funcionalidades con menor riesgo de romper otras partes del sistema. ¡Espero que esta refactorización te sea útil!
