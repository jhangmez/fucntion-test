import os 

import time 

import logging  

from functools import wraps 

 

import openai 

from openai import AzureOpenAI, RateLimitError, APIConnectionError, APIStatusError 

 

from src.domain.exceptions import OpenAIError 

 


 

ENV_KEY_OPENAI_API_KEY = "OPENAI_API_KEY" 

ENV_KEY_OPENAI_ENDPOINT= "OPENAI_ENDPOINT" 

ENV_KEY_OPENAI_API_VERSION= "OPENAI_API_VERSION" 

ENV_KEY_OPENAI_MODEL = "OPENAI_MODEL" 

ENV_KEY_DEPLOYMENT_NAME = "OPENAI_DEPLOYMENT" 

MAX_TOKENS = 2048 

TEMPERATURE = 0.2 

TOP_P=0.95 

FREQUENCY_PENALTY=0 

PRESENCE_PENALTY=0 

STOP=None 

STREAM=False 

 

class AzureOpenAIAdapter: 

    def __init__(self, 

                 api_key_env_var=ENV_KEY_OPENAI_API_KEY, 

                 endpoint_env_var= ENV_KEY_OPENAI_ENDPOINT, 

                 api_version_env_var=ENV_KEY_OPENAI_API_VERSION, 

                 model_env_var=ENV_KEY_OPENAI_MODEL, 

                 deployment_env_var=ENV_KEY_DEPLOYMENT_NAME): 

        self.api_key = os.environ.get(api_key_env_var) 

        self.endpoint = os.environ.get(endpoint_env_var) 

        self.api_version = os.environ.get(api_version_env_var) 

        self.model = os.environ.get(model_env_var), 

        self.deployment = os.environ.get(deployment_env_var) 

         

        if not all ([self.api_key, self.endpoint, self.api_version, self.model]): 

            raise ValueError("Falta valores requeridos para Azure OpenAI") 

         

        self.client = self._create_client() 

         

    def _create_client(self) -> AzureOpenAI: 

        """Crea y configura el cliente de Azure OpenAI""" 

        return AzureOpenAI( 

            api_key=self.api_key, 

            azure_endpoint=self.endpoint, 

            api_version=self.api_version 

        ) 

         

    def _retry_on_rate_limit(max_retries: int = 3, retry_delay: int=30): 

        """Decorador para reintentar llamdas a la API en caso de RateLimitError.""" 

        def decorator(func): 

            @wraps(func) 

            def wrapper(*args,**kwargs): 

                retries = 0 

                while retries < max_retries: 

                    try: 

                        return func(*args,**kwargs) 

                    except RateLimitError as e: 

                        retries += 1 

                        if retries< max_retries: 

                            wait_time = retry_delay*(2 ** (retries-1)) 

                            logging.warning(f"Ratio limite excedido. Intento {retries + 1} de {max_retries}. Intentando nuevamente en {wait_time} segundos.") 

                            time.sleep(wait_time) 

                        else: 

                            logging.error((f"Maximo de intentos excedidos para llamadas a la API de OpenAI: {e}")) 

                            raise OpenAIError(f"Limite excedido despues de multiplos intentos: {e}",e) 

                    except APIConnectionError as e: 

                        logging.error(f"Error al conectar a la API de OpenAI: {e}") 

                        raise OpenAIError(f"Conexión errónea: {e}",e) 

                    except APIStatusError as e: 

                        logging.error(f"La API de OpenAI retornó el status %s: %s",e.status_code,e.response) 

                        raise OpenAIError(f"Error API Status: {e}",e) 

                    except Exception as e: 

                        logging.error(f"Error durante al llamar a la API de OpenAI: {e}") 

                        raise OpenAIError(f"Error desconocido: {e}",e) 

            return wrapper 

        return decorator 

     

    @_retry_on_rate_limit() 

    def get_completion(self,system_message:str, user_message:str) ->str: 

        """Obtiene una completación de texto desde Azure OpenAI.""" 

        logging.info("Start: get_openai_completion") 

        message_text= [ 

            {"role":"system","content": system_message}, 

            {"role":"user","content": user_message}, 

        ] 

        return self._create_completion(message_text) 

     

    def _create_completion(self, messages: list[dict])->str: 

        """Función interna para crear la completación (evita duplicación).""" 

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

                stream=STREAM 

            ) 

            if completion.choices and completion.choices[0].message and completion.choices[0].message.content: 

                # Devuelve el contenido del mensaje como string 

                return completion.choices[0].message.content 

            else: 

                logging.warning("OpenAI no retornó ningún contenido en las opciones.") 

                # Lanza un error específico en lugar de una cadena vacía 

                raise OpenAIError("OpenAI no retornó opciones de finalización o contenido vacio.") 

 

        except Exception as e: 

            # El decorador maneja la mayoría de los errores de API y los convierte en OpenAIError. 

            # Este bloque captura errores que ocurran *después* de la llamada o si el decorador falla. 

            # También relanzamos como OpenAIError para consistencia. 

            # Comprobamos si ya es un OpenAIError para no envolverlo dos veces. 

            if isinstance(e, OpenAIError): 

                 raise # Si ya es OpenAIError (probablemente del decorador), relánzalo 

            else: 

                 logging.exception("Error durante la creación de la finalización o el progreso de OpenAI: %s", e) 

                 # Envuelve otras excepciones como OpenAIError 

                 raise OpenAIError(f"Error en proceso de finalización: {e}") from e 