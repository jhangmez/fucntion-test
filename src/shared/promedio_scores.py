import logging
from typing import Dict, Optional


def calculate_average_score_from_dict(
    cv_scores_dict: Optional[Dict[str, int]]
) -> Optional[float]:
    """
    Calcula el promedio de las puntuaciones en un diccionario de scores de CV.

    Args:
        cv_scores_dict: Un diccionario donde las claves son letras (str)
                        y los valores son puntuaciones (int).
                        Se asume que este diccionario proviene de una validación
                        previa y solo contiene enteros válidos (0-100).
                        Puede ser None.

    Returns:
        El promedio de las puntuaciones con un máximo de 2 decimales,
        o None si el diccionario es None, no es un diccionario, o está vacío.
    """
    # --- Validación de Entrada ---
    if cv_scores_dict is None:
        logging.warning(
            "El diccionario de scores es None. No se puede calcular el promedio."
        )
        return None

    # Comprobación de tipo (robustez por si se llama incorrectamente)
    if not isinstance(cv_scores_dict, dict):
        logging.error(
            f"Se esperaba un diccionario, pero se recibió: {type(cv_scores_dict)}. No se puede calcular el promedio."
        )
        return None

    # Comprobación si el diccionario está vacío
    if not cv_scores_dict:  # Un diccionario vacío se evalúa como False
        logging.warning(
            "El diccionario de scores está vacío. No se puede calcular el promedio."
        )
        return None

    # --- Cálculo del Promedio ---
    scores = list(cv_scores_dict.values())

    total_score = sum(scores)
    count = len(scores)

    average_score = total_score / count
    formatted_average = round(average_score, 2)

    logging.info(
        f"El promedio de los {count} scores encontrados es: {formatted_average}"
    )
    return formatted_average