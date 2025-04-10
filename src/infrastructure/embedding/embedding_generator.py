# src/infrastructure/embedding/embedding_generator.py
import logging
import os
import time
from typing import List, Tuple, Optional
from functools import wraps

try:
    from openai import AzureOpenAI, RateLimitError, APIError
except ImportError:
    logging.critical("OpenAI library not found. Please install 'openai'.")

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
    logging.warning("LangChain or TikToken not found. Using basic text splitting.")
    RecursiveCharacterTextSplitter = None  # Flag para usar alternativa


# Definir constantes para configuración
ENV_OPENAI_ENDPOINT = (
    "OPENAI_ENDPOINT"  # Reutilizar de openai_adapter si es el mismo
)
ENV_OPENAI_API_KEY = "OPENAI_API_KEY"  # Reutilizar
ENV_OPENAI_EMBEDDING_DEPLOYMENT = "OPENAI_EMBEDDING_DEPLOYMENT"
ENV_OPENAI_API_VERSION = (
    "OPENAI_API_VERSION"  # Podría ser diferente para embeddings
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
                            f"Embedding Rate Limit Exceeded (attempt {retries}/{max_retries}). Retrying in {wait_time} seconds: {e}"
                        )
                        time.sleep(wait_time)
                        delay *= (
                            2  # Exponential backoff para el siguiente intento si no hay retry_after
                        )
                    else:
                        logging.error(
                            "Max retries exceeded for OpenAI Embedding Rate Limit Error: %s",
                            e,
                        )
                        # Relanzar como error genérico de API para manejo externo
                        raise APIError(
                            f"Embedding Rate limit exceeded after multiple retries: {e}"
                        ) from e
                except APIError as e:  # Capturar otros errores de API (conexión, auth, etc.)
                    # Podríamos añadir reintento para errores 5xx si fuera necesario
                    logging.error(
                        f"OpenAI API Error during embedding generation: {e}"
                    )
                    raise  # Relanzar errores de API no relacionados con RateLimit
                except Exception as e:
                    # Errores inesperados no directamente de la API
                    logging.exception(
                        "Unexpected error during embedding generation wrapper: %s", e
                    )
                    raise  # Relanzar errores inesperados

            # Si el bucle termina (no debería pasar con los raise)
            raise APIError("Exceeded max retries for embedding generation.")

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
                f"Missing required environment variables for EmbeddingGenerator: {', '.join(missing_vars)}"
            )

        try:
            self.client = AzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version,
            )
            logging.info(
                "EmbeddingGenerator: AzureOpenAI client initialized for deployment '%s'.",
                self.deployment,
            )
        except Exception as e:
            logging.error(
                "EmbeddingGenerator: Failed to create Azure OpenAI client: %s", e
            )
            raise ValueError(
                f"Failed to initialize Azure OpenAI client for embeddings: {e}"
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
                    "Using LangChain RecursiveCharacterTextSplitter with TikToken."
                )
            except Exception as e:
                logging.warning(
                    f"Failed to initialize TikToken splitter ({e}), falling back to character splitter."
                )
                # Fallback a splitter basado en caracteres si Tiktoken falla o no está
                self.text_splitter = RecursiveCharacterTextSplitter(
                    chunk_size=self.chunk_size * 4,  # Aproximar tamaño de chunk en caracteres
                    chunk_overlap=self.chunk_overlap * 4,
                    length_function=len,
                )
                logging.info(
                    "Using LangChain RecursiveCharacterTextSplitter based on characters."
                )
        else:
            logging.warning(
                "LangChain not available. Using basic newline/character splitting."
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
            f"Generating embeddings for {len(text_chunks)} chunks using deployment '{self.deployment}'..."
        )
        response = self.client.embeddings.create(
            input=text_chunks,
            model=self.deployment,  # Usar el nombre del deployment de embedding
        )
        logging.info(f"Embeddings received. Usage: {response.usage}")

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
            logging.warning("Input text for embedding generation is empty.")
            return None, None

        try:
            logging.info("Splitting text into chunks...")
            chunks = self._split_text(text)
            logging.info(f"Text split into {len(chunks)} chunks.")

            if not chunks:
                logging.warning("Text splitting resulted in zero chunks.")
                return None, None

            embeddings = self._generate_embeddings_internal(chunks)

            if len(embeddings) != len(chunks):
                logging.error(
                    f"Mismatch between number of chunks ({len(chunks)}) and embeddings ({len(embeddings)})."
                )
                # Aca se indica si existe algun problema en la respuesta de la api
                return None, None

            return embeddings, chunks

        except APIError as e:
            logging.error(f"Failed to generate embeddings due to API error: {e}")
            return None, None
        except Exception as e:
            logging.exception(
                f"Unexpected error during embedding generation process: {e}"
            )
            return None, None