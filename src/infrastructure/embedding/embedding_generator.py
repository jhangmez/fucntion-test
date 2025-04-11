# src/infrastructure/embedding/embedding_generator.py
import logging
import os
import time
from typing import List, Tuple, Optional
from functools import wraps

try:
    from openai import AzureOpenAI, RateLimitError, APIError
except ImportError:
    logging.critical("Librería OpenAI no encontrada. Por favor, instala 'openai'.")

    class AzureOpenAI:
        pass  # Dummy

    class RateLimitError(Exception):
        pass

    class APIError(Exception):
        pass


try:
    from langchain.text_splitter import RecursiveCharacterTextSplitter

    # Asegúrate que tiktoken esté instalado si usas from_tiktoken_encoder
    # import tiktoken
except ImportError:
    logging.warning("LangChain o TikToken no encontrados. Usando división de texto básica.")
    RecursiveCharacterTextSplitter = None  # Flag para usar alternativa


# Definir constantes para configuración
ENV_OPENAI_ENDPOINT = (
    "OPENAI_ENDPOINT"
)
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"
ENV_OPENAI_EMBEDDING_DEPLOYMENT = "OPENAI_EMBEDDING_DEPLOYMENT"
ENV_OPENAI_API_VERSION = (
    "OPENAI_EMBEDDING_API_VERSION"
)


# --- Decorador de Reintentos Específico para Embeddings ---
def _retry_embeddings_on_error(max_retries: int = 5, initial_delay: int = 5):
    """Decorador para reintentar llamadas a la API de Embeddings de OpenAI."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            delay = initial_delay
            while retries < max_retries:
                try:
                    return func(*args, **kwargs)
                except RateLimitError as e:
                    retries += 1
                    if retries < max_retries:
                        # Usar el tiempo sugerido por OpenAI si está en e.retry_after, si no, backoff
                        wait_time = getattr(e, "retry_after", delay)
                        logging.warning(
                            f"Se excedió el límite de tasa de Embedding (intento {retries}/{max_retries}). Reintentando en {wait_time} segundos: {e}"
                        )
                        time.sleep(wait_time)
                        delay *= (
                            2  # Exponential backoff para el siguiente intento si no hay retry_after
                        )
                    else:
                        logging.error(
                            "Se excedió el número máximo de reintentos para el Error de Límite de Tasa de Embedding de OpenAI: %s",
                            e,
                        )
                        # Relanzar como error genérico de API para manejo externo
                        raise APIError(
                            f"Límite de tasa de Embedding excedido después de múltiples reintentos: {e}"
                        ) from e
                except APIError as e:  # Capturar otros errores de API (conexión, auth, etc.)
                    # Podríamos añadir reintento para errores 5xx si fuera necesario
                    logging.error(
                        f"Error de la API de OpenAI durante la generación de embedding: {e}"
                    )
                    raise  # Relanzar errores de API no relacionados con RateLimit
                except Exception as e:
                    # Errores inesperados no directamente de la API
                    logging.exception(
                        "Error inesperado durante el envoltorio de la generación de embedding: %s", e
                    )
                    raise  # Relanzar errores inesperados

            # Si el bucle termina (no debería pasar con los raise)
            raise APIError("Se excedió el número máximo de reintentos para la generación de embedding.")

        return wrapper

    return decorator


class EmbeddingGenerator:
    """Genera embeddings usando Azure OpenAI."""

    def __init__(self):
        self.endpoint = os.environ.get(ENV_OPENAI_ENDPOINT)
        self.api_key = os.environ.get(ENV_OPENAI_API_KEY)
        # Versión API específica para embeddings si es necesario, si no, usar la general
        self.api_version = os.environ.get(
            ENV_OPENAI_API_VERSION, "2024-02-01"
        )  # Usar una versión GA común
        self.deployment = os.environ.get(ENV_OPENAI_EMBEDDING_DEPLOYMENT)

        missing_vars = []
        if not self.endpoint:
            missing_vars.append(ENV_OPENAI_ENDPOINT)
        if not self.api_key:
            missing_vars.append(ENV_OPENAI_API_KEY)
        if not self.deployment:
            missing_vars.append(ENV_OPENAI_EMBEDDING_DEPLOYMENT)
        if missing_vars:
            raise ValueError(
                f"Faltan variables de entorno requeridas para EmbeddingGenerator: {', '.join(missing_vars)}"
            )

        try:
            self.client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version,
            )
            logging.info(
                "EmbeddingGenerator: Cliente AzureOpenAI inicializado para el deployment '%s'.",
                self.deployment,
            )
        except Exception as e:
            logging.error(
                "EmbeddingGenerator: Falló la creación del cliente Azure OpenAI: %s", e
            )
            raise ValueError(
                f"Falló la inicialización del cliente Azure OpenAI para embeddings: {e}"
            ) from e

        # Inicializar el text splitter
        self._initialize_text_splitter()

    def _initialize_text_splitter(self):
        """Inicializa el text splitter (Langchain o básico)."""
        self.chunk_size = 1024  # Tamaño del chunk (ajustar según modelo de embedding y necesidad)
        self.chunk_overlap = 128  # Solapamiento entre chunks
        self.text_splitter = None

        if RecursiveCharacterTextSplitter:
            try:
                # Intentar usar el splitter basado en tokens de Tiktoken (más preciso)
                self.text_splitter = (
                    RecursiveCharacterTextSplitter.from_tiktoken_encoder(
                        chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
                    )
                )
                logging.info(
                    "Usando RecursiveCharacterTextSplitter de LangChain con TikToken."
                )
            except Exception as e:
                logging.warning(
                    f"Falló la inicialización del splitter de TikToken ({e}), volviendo al splitter de caracteres."
                )
                # Fallback a splitter basado en caracteres si Tiktoken falla o no está
                self.text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self.chunk_size * 4,  # Aproximar tamaño de chunk en caracteres
                    chunk_overlap=self.chunk_overlap * 4,
                    length_function=len,
                )
                logging.info(
                    "Usando RecursiveCharacterTextSplitter de LangChain basado en caracteres."
                )
        else:
            logging.warning(
                "LangChain no disponible. Usando división básica por nueva línea/caracteres."
            )
            self.text_splitter = None  # Indicador para usar lógica manual

    def _split_text(self, text: str) -> List[str]:
        """Divide el texto en chunks."""
        if self.text_splitter:
            return self.text_splitter.split_text(text)
        else:
            # Lógica de splitting manual muy básica (ej: por párrafos o longitud)
            # Esto es menos ideal que LangChain.
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            chunks = []
            current_chunk = ""
            max_len = self.chunk_size * 4  # Aproximado
            for p in paragraphs:
                if len(current_chunk) + len(p) + 2 < max_len:
                    current_chunk += ("\n\n" + p) if current_chunk else p
                else:
                    if current_chunk:
                        chunks.append(current_chunk)
                    # Si el párrafo solo es más grande que el chunk, dividirlo bruscamente
                    if len(p) > max_len:
                        for i in range(0, len(p), max_len):
                            chunks.append(p[i : i + max_len])
                        current_chunk = ""  # Empezar nuevo chunk
                    else:
                        current_chunk = p  # El párrafo empieza el nuevo chunk
            if current_chunk:
                chunks.append(current_chunk)
            return chunks

    @_retry_embeddings_on_error()
    def _generate_embeddings_internal(
        self, text_chunks: List[str]
    ) -> List[List[float]]:
        """Llama a la API de embeddings con reintentos."""
        if not text_chunks:
            return []

        logging.info(
            f"Generando embeddings para {len(text_chunks)} chunks usando el deployment '{self.deployment}'..."
        )
        response = self.client.embeddings.create(
            input=text_chunks,
            model=self.deployment,  # Usar el nombre del deployment de embedding
        )
        logging.info(f"Embeddings recibidos. Uso: {response.usage}")

        # Extraer los embeddings en el orden correcto
        embeddings_list = sorted(response.data, key=lambda item: item.index)
        return [item.embedding for item in embeddings_list]

    def generate_embeddings(
        self, text: str
    ) -> Tuple[Optional[List[List[float]]], Optional[List[str]]]:
        """
        Genera embeddings para un texto dado, dividiéndolo en chunks si es necesario.

        Returns:
            Una tupla: (lista de vectores de embedding, lista de chunks de texto correspondientes)
            o (None, None) si ocurre un error.
        """
        if not text:
            logging.warning("El texto de entrada para la generación de embedding está vacío.")
            return None, None

        try:
            logging.info("Dividiendo el texto en chunks...")
            chunks = self._split_text(text)
            logging.info(f"Texto dividido en {len(chunks)} chunks.")

            if not chunks:
                logging.warning("La división del texto resultó en cero chunks.")
                return None, None

            embeddings = self._generate_embeddings_internal(chunks)

            if len(embeddings) != len(chunks):
                logging.error(
                    f"Desajuste entre el número de chunks ({len(chunks)}) y embeddings ({len(embeddings)})."
                )
                # Aca se indica si existe algun problema en la respuesta de la api
                return None, None

            return embeddings, chunks

        except APIError as e:
            logging.error(f"Falló la generación de embeddings debido a un error de la API: {e}")
            return None, None
        except Exception as e:
            logging.exception(
                f"Error inesperado durante el proceso de generación de embedding: {e}"
            )
            return None, None