from abc import ABC, abstractmethod

from src.domain.entities.api_credentials import ApiCredentials


class ApiRestRepositoryInterface(ABC):
    @abstractmethod
    def get_credentials(self) -> ApiCredentials:
        pass

    @abstractmethod
    def get_ranking_criteria(self, profile_id: str) -> dict:
        """Obtiene los criterios de ranking para un perfil dado."""
        pass

    @abstractmethod
    def update_cv_analysis(self, cv_id: str, analysis_data: dict) -> dict:
        """Actualiza el análisis de un CV."""
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