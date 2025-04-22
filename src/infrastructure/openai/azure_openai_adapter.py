import os
import time
import logging
from functools import wraps

import openai
from openai import AzureOpenAI, RateLimitError, APIConnectionError, APIStatusError

from src.domain.exceptions import OpenAIError

ENV_KEY_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_KEY_OPENAI_ENDPOINT = "OPENAI_ENDPOINT"
ENV_KEY_OPENAI_API_VERSION = "OPENAI_API_VERSION"
ENV_KEY_OPENAI_MODEL = "OPENAI_MODEL"
ENV_KEY_DEPLOYMENT_NAME = "OPENAI_DEPLOYMENT"
MAX_TOKENS = 2048
TEMPERATURE = 0.2
TOP_P = 0.95
FREQUENCY_PENALTY = 0
PRESENCE_PENALTY = 0
STOP = None
STREAM = False


class AzureOpenAIAdapter:
    """
    Adaptador para interactuar con el servicio Azure OpenAI. Maneja la autenticación,
    los reintentos y el manejo de errores.
    """

    def __init__(
        self,
        api_key_env_var=ENV_KEY_OPENAI_API_KEY,
        endpoint_env_var=ENV_KEY_OPENAI_ENDPOINT,
        api_version_env_var=ENV_KEY_OPENAI_API_VERSION,
        model_env_var=ENV_KEY_OPENAI_MODEL,
        deployment_env_var=ENV_KEY_DEPLOYMENT_NAME,
    ):
        """
        Inicializa el AzureOpenAIAdapter con claves de API, punto de conexión, versión de API,
        nombre del modelo y nombre de la implementación. Lee estos valores de las variables de entorno.

        Args:
            api_key_env_var (str): Nombre de la variable de entorno para la clave de API de OpenAI.
            endpoint_env_var (str): Nombre de la variable de entorno para el punto de conexión de OpenAI.
            api_version_env_var (str): Nombre de la variable de entorno para la versión de API de OpenAI.
            model_env_var (str): Nombre de la variable de entorno para el Modelo de OpenAI.
            deployment_env_var (str): Nombre de la variable de entorno para el nombre de la implementación de OpenAI.

        Raises:
            ValueError: Si falta alguna de las variables de entorno requeridas.
        """
        self.api_key = os.environ.get(api_key_env_var)
        self.endpoint = os.environ.get(endpoint_env_var)
        self.api_version = os.environ.get(api_version_env_var)
        self.model = os.environ.get(model_env_var)
        self.deployment = os.environ.get(deployment_env_var)

        if not all([self.api_key, self.endpoint, self.api_version, self.model]):
            raise ValueError("Faltan valores requeridos para Azure OpenAI")

        self.client = self._create_client()

    def _create_client(self) -> AzureOpenAI:
        """
        Crea y configura el cliente de Azure OpenAI.

        Returns:
            AzureOpenAI: Cliente AzureOpenAI configurado.
        """
        return AzureOpenAI(
            api_key=self.api_key, azure_endpoint=self.endpoint, api_version=self.api_version
        )

    def _retry_on_rate_limit(max_retries: int = 3, retry_delay: int = 30):
        """
        Decorador para reintentar llamadas a la API en caso de RateLimitError.

        Args:
            max_retries (int): Número máximo de reintentos.
            retry_delay (int): Retraso inicial en segundos entre reintentos.

        Returns:
            callable: Función decorada.
        """

        def decorator(func):
            @wraps(func)
            def wrapper(*args, **kwargs):
                retries = 0
                while retries < max_retries:
                    try:
                        return func(*args, **kwargs)
                    except RateLimitError as e:
                        retries += 1
                        if retries < max_retries:
                            wait_time = retry_delay * (2 ** (retries - 1))
                            logging.warning(
                                f"Se excedió el límite de tasa. Reintento {retries + 1} de {max_retries}. Reintentando en {wait_time} segundos."
                            )
                            time.sleep(wait_time)
                        else:
                            logging.error(
                                f"Se excedió el número máximo de reintentos para llamadas a la API de OpenAI: {e}"
                            )
                            raise OpenAIError(
                                f"Se excedió el límite de tasa después de múltiples reintentos: {e}", e
                            )
                    except APIConnectionError as e:
                        logging.error(f"Error al conectar con la API de OpenAI: {e}")
                        raise OpenAIError(f"Error de conexión: {e}", e)
                    except APIStatusError as e:
                        logging.error(
                            f"La API de OpenAI devolvió el estado %s: %s",
                            e.status_code,
                            e.response,
                        )
                        raise OpenAIError(f"Error de estado de la API: {e}", e)
                    except Exception as e:
                        logging.error(f"Error durante la llamada a la API de OpenAI: {e}")
                        raise OpenAIError(f"Error desconocido: {e}", e)

            return wrapper

        return decorator

    @_retry_on_rate_limit()
    def get_completion(self, system_message: str, user_message: str) -> str:
        """
        Obtiene una finalización de texto de Azure OpenAI.

        Args:
            system_message (str): El mensaje del sistema para guiar al modelo.
            user_message (str): El mensaje del usuario para generar una finalización para.

        Returns:
            str: La finalización de texto generada por el modelo.

        Raises:
            OpenAIError: Si ocurre un error durante la llamada a la API o si la respuesta no es válida.
        """
        logging.info("Inicio: get_openai_completion")
        message_text = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
        return self._create_completion(message_text)

    def _create_completion(self, messages: list[dict]) -> str:
        """
        Función interna para crear la finalización (evita la duplicación).

        Args:
            messages (list[dict]): Lista de diccionarios de mensajes.

        Returns:
            str: El contenido del mensaje de finalización.

        Raises:
            OpenAIError: Si ocurre un error durante la llamada a la API o si la respuesta no es válida.
        """
        try:
            completion = self.client.chat.completions.create(
                model=self.deployment,
                messages=messages,
                temperature=TEMPERATURE,
                max_tokens=MAX_TOKENS,
                top_p=TOP_P,
                frequency_penalty=FREQUENCY_PENALTY,
                presence_penalty=PRESENCE_PENALTY,
                stop=STOP,
                stream=STREAM,
            )

            if (
                completion.choices
                and completion.choices[0].message
                and completion.choices[0].message.content
            ):
                # Retorna el contenido como un mensaje (String)
                return completion.choices[0].message.content
            else:
                logging.warning("OpenAI no devolvió contenido en las opciones.")
                # Genera un error específico en lugar de una cadena vacía
                raise OpenAIError(
                    "OpenAI no devolvió opciones de finalización o contenido vacío."
                )

        except Exception as e:
            # El decorador maneja la mayoría de los errores de API y los convierte en OpenAIError.
            # Este bloque captura errores que ocurren *después* de la llamada o si el decorador falla.
            # También lo volvemos a generar como OpenAIError para mantener la coherencia.
            # Verificamos si ya es un OpenAIError para evitar envolverlo dos veces.
            if isinstance(e, OpenAIError):
                raise  # Si ya es un OpenAIError (probablemente del decorador), vuelva a generarlo.
            else:
                logging.exception(
                    "Error durante la creación de la finalización o el progreso de OpenAI: %s", e
                )
                # Envuelve otras excepciones como OpenAIError
                raise OpenAIError(f"Error en el proceso de finalización: {e}") from e