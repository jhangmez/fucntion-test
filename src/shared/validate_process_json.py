import json
import logging
import string # Para obtener las letras mayúsculas A-Z
from typing import Dict, Optional, Tuple

# Conjunto de letras mayúsculas válidas para una búsqueda rápida (sin cambios)
VALID_LETTERS = set(string.ascii_uppercase)


def extract_and_validate_cv_data_from_json(
    json_string: str,
) -> Tuple[Optional[Dict[str, int]], Optional[str], Optional[str]]:
    """
    Parsea JSON de análisis de CV, extrae datos y valida 'cvScore' estrictamente
    esperando que sea un diccionario {'A': 100, 'B': 75, ...}.

    Busca 'cvScore', 'cvAnalysis', 'nameCandidate'.
    Valida que 'cvScore' sea un diccionario donde:
        - Las claves (keys) son strings de una sola letra mayúscula (A-Z).
        - Los valores (values) son enteros entre 0 y 100 (inclusive).

    Si 'cvScore' falta, no es un diccionario, o *cualquier* par clave-valor
    falla la validación, se devuelve None para el diccionario de puntuaciones.

    Args:
        json_string: La cadena de texto que contiene el JSON.

    Returns:
        Una tupla con tres elementos:
        1. El diccionario 'cvScore' original si es válido, o None si faltó o fue inválido.
        2. El valor de 'cvAnalysis' (string) o None si falta o no es string.
        3. El valor de 'nameCandidate' (string) o None si falta o no es string.

    Raises:
        json.JSONDecodeError: Si la cadena `json_string` no es un JSON válido.
        TypeError: Si el JSON parseado no es un diccionario raíz.
    """
    if not json_string:
        logging.warning(
            "Se recibió una cadena JSON vacía para extraer datos de CV."
        )
        return None, None, None

    try:
        parsed_data = json.loads(json_string)
    except json.JSONDecodeError as e:
        logging.error(f"Error al decodificar JSON: {e}")
        raise

    if not isinstance(parsed_data, dict):
        raise TypeError(
            f"El JSON parseado para CV no es un diccionario raíz. Tipo recibido: {type(parsed_data)}"
        )

    # --- Extracción inicial  ---
    raw_cv_score = parsed_data.get("cvScore")
    cv_analysis = parsed_data.get("cvAnalysis")
    candidate_name = parsed_data.get("nameCandidate")

    # --- Validación del Diccionario 'cvScore' ---
    validated_scores_dict: Optional[Dict[str, int]] = None

    if raw_cv_score is None:
        logging.warning("La clave 'cvScore' no se encontró en la respuesta JSON.")
    elif not isinstance(raw_cv_score, dict):
        logging.warning(
            f"La clave 'cvScore' se encontró pero NO es un diccionario (tipo: {type(raw_cv_score)}). Se considera inválida."
        )
    else:
        all_items_valid = True
        # --- Iterar sobre Clave-Valor ---
        for letter, result in raw_cv_score.items():
            item_is_valid = False
            error_msg = ""

            # 1. Validar la Clave (letter)
            if not isinstance(letter, str):
                error_msg = f"Clave '{letter}' no es un string."
            elif len(letter) != 1:
                error_msg = f"Clave '{letter}' no es un carácter único."
            elif letter not in VALID_LETTERS:
                error_msg = f"Clave '{letter}' no es una letra mayúscula A-Z."
            # 2. Validar el Valor (result) - solo si la clave es válida
            elif not isinstance(result, int) or isinstance(result, bool):
                error_msg = f"Valor para la clave '{letter}' no es un entero (tipo: {type(result)}, valor: {result})."
            elif not 0 <= result <= 100:
                error_msg = f"Valor para la clave '{letter}' ({result}) está fuera del rango [0, 100]."
            else:
                item_is_valid = True

            if not item_is_valid:
                logging.warning(
                    f"Validación fallida para el diccionario 'cvScore': {error_msg}"
                )
                all_items_valid = False
                break

        if all_items_valid:
            validated_scores_dict = raw_cv_score
            logging.info(
                f"El diccionario 'cvScore' con {len(validated_scores_dict)} claves ha sido validado exitosamente."
            )
        else:
            logging.warning(
                "El diccionario 'cvScore' contenía elementos inválidos y no será devuelto."
            )

    # --- Procesamiento final de otros campos ---

    # final_cv_score = str(raw_cv_score) if isinstance(raw_cv_score, str) else None
    # if raw_cv_score is not None and final_cv_score is None:
    #       logging.warning(f"'cvScore' no era un string (tipo: {type(raw_cv_score)}), se devuelve None.")

    final_analysis = str(cv_analysis) if isinstance(cv_analysis, str) else None
    if cv_analysis is not None and final_analysis is None:
        logging.warning(
            f"'cvAnalysis' no era un string (tipo: {type(cv_analysis)}), se devuelve None."
        )

    final_name = str(candidate_name) if isinstance(candidate_name, str) else None
    if candidate_name is not None and final_name is None:
        logging.warning(
            f"'nameCandidate' no era un string (tipo: {type(candidate_name)}), se devuelve None."
        )

    # --- Devolver los resultados ---
    return validated_scores_dict, final_analysis, final_name