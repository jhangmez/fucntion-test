class DomainError(Exception): 

    """Clase base para excepciones específicas del domino.""" 

    pass 

class InvalidCVError(DomainError): 

    """Se lanza cuando un CV no es valido, por ejemplo, texto vacio.""" 

    pass 

class CVAnalysisError(DomainError): 

    """Clase base para errores relacionados con el análisis de CV.""" 

    pass 

class OpenAIError(CVAnalysisError): 

    """Se lanza cuando hay un error en la comunicación con OpenAI""" 

    pass 

class JSONValidationError(CVAnalysisError): 

    """Se lanza cuando la respuesta JSON de OpenAI no es válida.""" 

    pass 

class FileProcessingError(DomainError): 

    """Se lanza cuando hay un error al procesar un archivo, por ejemplo, al eliminar un PDF""" 

    pass 

class DocumentIntelligenceError(CVAnalysisError): 

    """Se lanza cuando hay un error al interactar con Document Intelligence""" 

    pass 

class NoContentExtractedError(CVAnalysisError): 

    """Se lanza cuando el Document Intelligence o extrae contenido de un documento.""" 

    pass 

class APIError(DomainError): 

    """Se lanza cuando hay un error al interactuar con la API Rest""" 

    pass 

class AuthenticationError(DomainError): 

    """Se lanza cuando hay un error de autenticación con la API Rest""" 

    pass 

class KeyVaultError(DomainError): 

    """Clase base para errores relacionados con Azure Key Vault.""" 

    pass 

class SecretNotFoundError(KeyVaultError): 

    """Se lanza cuando un secreto específico no se encuentra en Key Vault.""" 

    pass 