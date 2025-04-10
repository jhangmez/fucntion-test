import os
import logging
from azure.keyvault.secrets import SecretClient
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ResourceNotFoundError, ClientAuthenticationError

from src.domain.exceptions import (
    KeyVaultError,
    SecretNotFoundError,
)  # Necesitarás definir KeyVaultError y SecretNotFoundError en domain/exceptions.py

ENV_KEY_VAULT_URI = "KEY_VAULT_URI"  # Variable de entorno para la URI del Key Vault


class KeyVaultClient:
    """Cliente para interactuar con Azure Key Vault y obtener secretos."""

    def __init__(self, vault_uri_env_var: str = ENV_KEY_VAULT_URI):
        self.vault_uri = os.environ.get(vault_uri_env_var)
        if not self.vault_uri:
            logging.error(
                "CRITICAL: Key Vault URI environment variable ('%s') no se ha definido.",
                vault_uri_env_var,
            )
            raise ValueError(
                f"Key Vault URI environment variable '{vault_uri_env_var}' no se ha definido."
            )

        try:
            # DefaultAzureCredential intentará varios métodos de autenticación:
            # 1. Variables de entorno (AZURE_CLIENT_ID, AZURE_TENANT_ID, AZURE_CLIENT_SECRET)
            # 2. Identidad Administrada (si se ejecuta en Azure con Managed Identity habilitada)
            # 3. Credenciales de usuario logueado (Azure CLI, VS Code, etc. - para desarrollo local)
            credential = DefaultAzureCredential()
            # Verifica si la credencial es válida (intenta obtener un token silenciosamente)
            # Esto puede ayudar a detectar problemas de autenticación temprano
            # credential.get_token("https://vault.azure.net/.default")

            self.secret_client = SecretClient(
                vault_url=self.vault_uri, credential=credential
            )
            logging.info(
                "KeyVaultClient inicializada exitosamente por el vault: %s",
                self.vault_uri,
            )
        except Exception as e:
            logging.exception(
                "Error al inicializar el DefaultAzureCredential o SecretClient."
            )
            raise KeyVaultError(f"Error al inicializar el Key Vault del cliente: {e}") from e

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
        logging.debug("Attempting to retrieve secret: %s", secret_name)
        try:
            # Obtiene el secreto
            retrieved_secret = self.secret_client.get_secret(secret_name)
            logging.info("Secreto recuperado exitosamente: %s", secret_name)
            return retrieved_secret.value
        except ResourceNotFoundError:
            logging.error("Secreto no encontrado en el Key Vault: %s", secret_name)
            raise SecretNotFoundError(
                f"Secreto '{secret_name}' no encontrado en el Key Vault: {self.vault_uri}"
            )
        except ClientAuthenticationError as e:
            logging.error(
                "Error de autenticación al recuperar el secreto '%s': %s", secret_name, e
            )
            raise KeyVaultError(
                f"Error de autenticación al recuperar el secreto '{secret_name}': {e}"
            ) from e
        except Exception as e:
            # Captura otros posibles errores (ej. problemas de red con Key Vault)
            logging.exception(
                "Error al recuperar el secreto '%s' desde el Key Vault: %s",
                secret_name,
                e,
            )
            raise KeyVaultError(f"Error al recuperar el secreto '{secret_name}': {e}") from e