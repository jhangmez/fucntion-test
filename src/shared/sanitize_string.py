import logging
import re
from typing import Dict, Any, Optional, List, Tuple

def sanitize_for_id(text: str) -> str:
    """
    Sanitiza una cadena para usarla como parte de un ID en Azure AI Search.
    Reemplaza caracteres no alfanuméricos con guiones y convierte a minúsculas.
    """
    if not text:
        return "default-id"
    # Quitar caracteres que no sean letras, números o espacios/guiones
    text = re.sub(r"[^\w\s-]", "", text).strip()
    # Reemplazar espacios y guiones múltiples con un solo guión
    text = re.sub(r"[-\s]+", "-", text)
    # Convertir a minúsculas
    return text.lower()


def format_text_for_embedding(
    candidate_name: str,
    profile_name: str,
    cv_analysis: str,
    average_score: Optional[float],
) -> str:
    """
    Formatea la información del análisis para generar embeddings.
    """
    score_text = (
        f"{average_score:.2f}%" if average_score is not None else "No disponible"
    )
    formatted_text = f"""
    Evaluación del candidato: {candidate_name or 'Nombre no extraído'}
    Perfil evaluado: {profile_name or 'Perfil no especificado'}
    Puntuación promedio: {score_text}

    Análisis detallado:
    {cv_analysis or 'Análisis no disponible'}
    """
    return formatted_text.strip()
