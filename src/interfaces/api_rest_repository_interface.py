from abc import ABC, abstractmethod
from src.domain.entities.api_credentials import ApiCredentials

class ApiRestRepositoryInterface(ABC):
    @abstractmethod
    def get_credentials(self) -> ApiCredentials:
        pass

    @abstractmethod
    def get(self, endpoint: str, params: dict = None, headers: dict = None) -> dict:
        pass

    @abstractmethod
    def post(self, endpoint: str, data: dict, headers: dict = None) -> dict:
        pass

    @abstractmethod
    def put(self, endpoint: str, data: dict, headers: dict = None) -> dict:
        pass

    @abstractmethod
    def patch(self, endpoint: str, data: dict, headers: dict = None) -> dict:
        pass

    @abstractmethod
    def delete(self, endpoint: str, headers: dict = None) -> dict:
        pass