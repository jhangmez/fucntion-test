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
    Adapter for interacting with Azure OpenAI service.  Handles authentication,
    retries, and error handling.
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
        Initializes the AzureOpenAIAdapter with API keys, endpoint, API version,
        model name, and deployment name.  Reads these values from environment variables.

        Args:
            api_key_env_var (str): Environment variable name for the OpenAI API key.
            endpoint_env_var (str): Environment variable name for the OpenAI endpoint.
            api_version_env_var (str): Environment variable name for the OpenAI API version.
            model_env_var (str): Environment variable name for the OpenAI Model.
            deployment_env_var (str): Environment variable name for the OpenAI deployment name.

        Raises:
            ValueError: If any of the required environment variables are missing.
        """
        self.api_key = os.environ.get(api_key_env_var)
        self.endpoint = os.environ.get(endpoint_env_var)
        self.api_version = os.environ.get(api_version_env_var)
        self.model = os.environ.get(model_env_var)
        self.deployment = os.environ.get(deployment_env_var)

        if not all([self.api_key, self.endpoint, self.api_version, self.model]):
            raise ValueError("Missing required values for Azure OpenAI")

        self.client = self._create_client()

    def _create_client(self) -> AzureOpenAI:
        """
        Creates and configures the Azure OpenAI client.

        Returns:
            AzureOpenAI: Configured AzureOpenAI client.
        """
        return AzureOpenAI(
            api_key=self.api_key, azure_endpoint=self.endpoint, api_version=self.api_version
        )

    def _retry_on_rate_limit(max_retries: int = 3, retry_delay: int = 30):
        """
        Decorator to retry API calls in case of RateLimitError.

        Args:
            max_retries (int): Maximum number of retries.
            retry_delay (int): Initial delay in seconds between retries.

        Returns:
            callable: Decorated function.
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
                                f"Rate limit exceeded. Retry {retries + 1} of {max_retries}. Retrying in {wait_time} seconds."
                            )
                            time.sleep(wait_time)
                        else:
                            logging.error(
                                f"Maximum retries exceeded for OpenAI API calls: {e}"
                            )
                            raise OpenAIError(
                                f"Rate limit exceeded after multiple retries: {e}", e
                            )
                    except APIConnectionError as e:
                        logging.error(f"Error connecting to OpenAI API: {e}")
                        raise OpenAIError(f"Connection error: {e}", e)
                    except APIStatusError as e:
                        logging.error(
                            f"OpenAI API returned status %s: %s",
                            e.status_code,
                            e.response,
                        )
                        raise OpenAIError(f"API Status Error: {e}", e)
                    except Exception as e:
                        logging.error(f"Error during OpenAI API call: {e}")
                        raise OpenAIError(f"Unknown error: {e}", e)

            return wrapper

        return decorator

    @_retry_on_rate_limit()
    def get_completion(self, system_message: str, user_message: str) -> str:
        """
        Obtains a text completion from Azure OpenAI.

        Args:
            system_message (str): The system message to guide the model.
            user_message (str): The user's message to generate a completion for.

        Returns:
            str: The text completion generated by the model.

        Raises:
            OpenAIError: If an error occurs during the API call or if the response is invalid.
        """
        logging.info("Start: get_openai_completion")
        message_text = [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ]
        return self._create_completion(message_text)

    def _create_completion(self, messages: list[dict]) -> str:
        """
        Internal function to create the completion (avoids duplication).

        Args:
            messages (list[dict]): List of message dictionaries.

        Returns:
            str: The content of the completion message.

        Raises:
            OpenAIError: If an error occurs during the API call or if the response is invalid.
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
                # Returns the content of the message as string
                return completion.choices[0].message.content
            else:
                logging.warning("OpenAI returned no content in the choices.")
                # Raises a specific error instead of an empty string
                raise OpenAIError(
                    "OpenAI returned no completion options or empty content."
                )

        except Exception as e:
            # The decorator handles most API errors and converts them into OpenAIError.
            # This block captures errors that occur *after* the call or if the decorator fails.
            # We also re-raise it as OpenAIError for consistency.
            # We check if it is already an OpenAIError to avoid wrapping it twice.
            if isinstance(e, OpenAIError):
                raise  # If it is already an OpenAIError (probably from the decorator), re-raise it
            else:
                logging.exception(
                    "Error during creation of completion or OpenAI progress: %s", e
                )
                # Wraps other exceptions as OpenAIError
                raise OpenAIError(f"Error in completion process: {e}") from e