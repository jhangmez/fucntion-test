from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

@dataclass(frozen=True)
class ApiCredentials:
    """Representa las credenciales de acceso a la API REST (token y expiración)."""
    token: str
    expires_in: Optional[int] = None

    def is_valid(self, margin_seconds: int = 60) -> bool:
        """Verifica si el token es válido, considerando un margen de seguridad."""
        if not self.token:
            return False

        if self.expires_in is None:
            return True

        expiration_time = datetime.now() + timedelta(seconds=self.expires_in)
        return datetime.now() + timedelta(seconds=margin_seconds) < expiration_time