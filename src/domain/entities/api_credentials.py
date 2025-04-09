from dataclasses import dataclass
from typing import Optional
from datatime import datetime, timedelta

@dataclass(frozen=True)
class APICredentials:
  """Representa las credenciales de la API REST (token y expiración)."""
  token: str
  expiration_in: Optional[int] = None

  def is_valid(self, margin_seconds:int =60) -> bool:
    """Verifica si el token es válido, considerando un margen de seguridad."""
    if not self.token:
      return False
    if self.expiration_in is None:
      return True

    expiration_time = datetime.now() + timedelta(seconds=self.expiration_in)
    return datetime.now() + timedelta(seconds=margin_seconds) < expiration_time