import os
import logging
import requests
from typing import Dict, Optional

from src.domain.entities.api_credentials import ApiCredentials
from src.domain.exceptions import APIError, AuthenticationError
from src.interfaces.api_rest_repository_interface import ApiRestRepositoryInterface

ENV_API_USERNAME = "API_USERNAME"
ENV_API_PASSWORD = "API_PASSWORD"
ENV_API_ROLE = "API_ROLE"
ENV_API_USER_APPLICATION = "API_USER_APPLICATION"
ENV_API_BASE_URL = "API_BASE_URL"
TOKEN_EXPIRATION_MINUTES = 20
TOKEN_EXPIRATION_SECONDS = TOKEN_EXPIRATION_MINUTES * 60


class RestApiAdapter(ApiRestRepositoryInterface):
    def __init__(
        self,
        base_url_env_var: str = ENV_API_BASE_URL,
        username_env_var: str = ENV_API_USERNAME,
        password_env_var: str = ENV_API_PASSWORD,
        role_env_var: str = ENV_API_ROLE,
        user_app_env_var: str = ENV_API_USER_APPLICATION,
    ):
        self.base_url = os.environ.get(base_url_env_var)
        self.username = os.environ.get(username_env_var)
        self.password = os.environ.get(password_env_var)
        self.role = os.environ.get(role_env_var)
        self.user_application = os.environ.get(user_app_env_var)
        self._credentials: Optional[ApiCredentials] = None

        if not all(
            [
                self.base_url,
                self.username,
                self.password,
                self.role,
                self.user_application,
            ]
        ):
            raise ValueError("Faltan variables requeridas para el REST API")

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
        try:
            response = requests.post(
                url, headers=headers, json=data, verify=True
            )
            response.raise_for_status()

            token = response.text.strip()

            if not token:
                logging.error("API returned an empty token.")
                raise AuthenticationError("API returned an empty token.")

            return ApiCredentials(
                token=token, expires_in=TOKEN_EXPIRATION_SECONDS
            )

        except requests.exceptions.RequestException as e:
            logging.exception("Error during authentication: %s", e)
            raise AuthenticationError(f"Authentication failed: {e}") from e

    def get_credentials(self) -> ApiCredentials:
        """Obtiene las credenciales válidas (autenticando si es necesario)."""
        if self._credentials is None or not self._credentials.is_valid():
            logging.info("Autenticando con la API...")
            self._credentials = self._authenticate()
            logging.info("Verificación realizada.")
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
        """Realiza una petición a la API, manejando la autenticación."""

        credentials = self.get_credentials()
        auth_headers = {"Authorization": f"Bearer {credentials.token}"}

        if headers:
            headers.update(auth_headers)
        else:
            headers = auth_headers

        url = f"{self.base_url}{endpoint}"

        try:
            response = requests.request(
                method, url, params=params, json=data, headers=headers, verify=verify
            )
            # Esto verifica el estado HTTP (2xx es éxito, otros lanzan excepción)
            response.raise_for_status()

            # Si no esperamos cuerpo de respuesta O si la respuesta es 204 No Content (sin cuerpo)
            if not expect_response_body or response.status_code == 204:
                 logging.debug(f"Request to {url} succeeded with status {response.status_code}. No response body expected/processed.")
                 return None

            # Si esperamos cuerpo de respuesta Y hay contenido
            if response.content:
                 logging.debug(f"Request to {url} succeeded with status {response.status_code}. Processing response body.")
                 return response.json() # Procesamos y devolvemos el diccionario
            else:
                 logging.warning(f"Request to {url} succeeded with status {response.status_code}, but no content was returned despite expecting a body.")
                 return None

        except requests.exceptions.RequestException as e:
            logging.exception("Error during API request to %s: %s", url, e)
            if isinstance(e, requests.exceptions.HTTPError) and e.response is not None:
                logging.error("Response content on error: %s", e.response.text)
            raise APIError(f"API request failed: {e}") from e

    def get(self, endpoint: str, params: dict = None, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        """Realiza una petición GET a la API."""
        return self._make_request("GET", endpoint, params=params, headers=headers, verify=True, expect_response_body=expect_response_body)

    def post(self, endpoint: str, data: dict, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        """Realiza una petición POST a la API."""
        return self._make_request("POST", endpoint, data=data, headers=headers, expect_response_body=expect_response_body)

    def put(self, endpoint: str, data: dict, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        """Realiza una petición PUT a la API."""
        return self._make_request("PUT", endpoint, data=data, headers=headers, expect_response_body=expect_response_body)

    def patch(self, endpoint: str, data: dict, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        """Realiza una petición PATCH a la API."""
        return self._make_request("PATCH", endpoint, data=data, headers=headers, expect_response_body=expect_response_body)

    def delete(self, endpoint: str, headers: dict = None, expect_response_body: bool = True) -> Optional[dict]:
        """Realiza una petición DELETE a la API."""
        return self._make_request("DELETE", endpoint, headers=headers, expect_response_body=expect_response_body)

    # -----------------------------------------------------------------------------------------------
    # --- /Profile ---
    def get_profile_id(self, id: str) -> dict:
        """Obtiene un profile por ID (GET /Profile/{id})."""
        endpoint = f"/Profile/{id}"
        return self.get(endpoint)

    # -----------------------------------------------------------------------------------------------
    # --- /Resumen ---

    def get_resumen(self, id: str) -> dict:
        """Obtiene un resumen por ID (GET /Resumen/{id})."""
        endpoint = f"/Resumen/{id}"
        return self.get(endpoint)

    def add_scores(self, candidate_id: str, scores: Dict[str, int]) -> None:
        """Agrega puntuaciones a un candidato (POST /Resumen/AddScores).
           No espera cuerpo de respuesta, solo éxito HTTP."""
        endpoint = "/Resumen/AddScores"
        data = {
            "candidateId": candidate_id,
            "scores": scores,
        }
        self.post(endpoint, data=data, expect_response_body=False)

    def save_resumen(
        self,
        candidate_id: str,
        transcription: str,
        score: float,
        candidate_name: str,
        analysis: str,
    ) -> None:
        """Guarda un resumen (POST /Resumen/Save).
           No espera cuerpo de respuesta, solo éxito HTTP."""
        endpoint = "/Resumen/Save"
        data = {
            "candidateId": candidate_id,
            "transcription": transcription,
            "score": score,
            "analysis": analysis,
            "candidateName": candidate_name,
        }
        self.post(endpoint, data=data, expect_response_body=False)


    def update_candidate(
        self, candidate_id: str, error_message: Optional[str] = None
    ) -> None:
        """Actualiza un candidato (PUT /Resumen).
           No espera cuerpo de respuesta, solo éxito HTTP."""
        endpoint = "/Resumen"
        data = {
            "candidateId": candidate_id,
            "errorMessage": error_message,
        }
        self.put(endpoint, data=data, expect_response_body=False)