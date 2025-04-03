import json
import logging
import string # Para obtener las letras mayúsculas A-Z
from typing import Dict, Any, Optional, List, Tuple

VALID_LETTERS = set(string.ascii_uppercase)

def extract_and_validate_cv_data_from_json(json_string: str) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str], Optional[str]]:
    """
    Parsea una cadena JSON de análisis de CV, extrae datos predefinidos y
    valida estrictamente la estructura y contenido de la lista 'cvScore'.

    Busca 'cvScore', 'cvAnalysis', 'nameCandidate'.
    Valida que 'cvScore' sea una lista donde cada elemento es un diccionario:
      - Con clave 'Letter': valor es un string de una sola letra mayúscula (A-Z).
      - Con clave 'Result': valor es un entero entre 0 y 100 (inclusive).

    Si 'cvScore' falta, no es una lista, o *cualquier* elemento falla la validación,
    se devuelve None para la lista de puntuaciones.

    Args:
        json_string: La cadena de texto que contiene el JSON de la respuesta de OpenAI.

    Returns:
        Una tupla con tres elementos:
        1. La lista 'cvScore' validada, o None si falta o es inválida.
        2. El valor de 'cvAnalysis' (string) o None si falta.
        3. El valor de 'nameCandidate' (string) o None si falta.

    Raises:
        json.JSONDecodeError: Si la cadena `json_string` no es un JSON válido.
        TypeError: Si el JSON parseado no es un diccionario (objeto JSON) en la raíz.
    """
    if not json_string:
        logging.warning("Se recibió una cadena JSON vacía para extraer datos de CV.")
        return None, None, None

    # Intentar parsear el JSON. Propagará JSONDecodeError si falla.
    parsed_data = json.loads(json_string)

    # Verificar que el resultado del parseo sea un diccionario raíz
    if not isinstance(parsed_data, dict):
        raise TypeError(f"El JSON parseado para CV no es un diccionario raíz. Tipo recibido: {type(parsed_data)}")

    # --- Extracción inicial ---
    raw_cv_score = parsed_data.get("cvScore")
    cv_analysis = parsed_data.get("cvAnalysis") # Se devolverá tal cual si existe
    candidate_name = parsed_data.get("nameCandidate") # Se devolverá tal cual si existe

    # --- Validación de cvScore ---
    validated_score_list: Optional[List[Dict[str, Any]]] = None # Variable para el resultado final de score

    if raw_cv_score is None:
        logging.warning("La clave 'cvScore' no se encontró en la respuesta JSON.")
    elif not isinstance(raw_cv_score, list):
        logging.warning(f"La clave 'cvScore' se encontró pero no es una lista (tipo: {type(raw_cv_score)}). Se considera inválida.")
    else:
        # Si es una lista, procedemos a validar cada item
        temp_validated_list = []
        all_items_valid = True # Asumimos que todo está bien hasta encontrar un error

        for index, item in enumerate(raw_cv_score):
            item_is_valid = False # Validez del item actual
            error_msg = ""

            if not isinstance(item, dict):
                error_msg = f"Item en índice {index} no es un diccionario."
            elif "Letter" not in item or "Result" not in item:
                error_msg = f"Item en índice {index} no contiene las claves 'Letter' y 'Result'."
            else:
                letter = item["Letter"]
                result = item["Result"]

                # Validar 'Letter'
                if not isinstance(letter, str):
                    error_msg = f"Item en índice {index}: 'Letter' no es un string (tipo: {type(letter)})."
                elif len(letter) != 1:
                     error_msg = f"Item en índice {index}: 'Letter' no es un carácter único ('{letter}')."
                elif letter not in VALID_LETTERS:
                    error_msg = f"Item en índice {index}: 'Letter' ('{letter}') no es una letra mayúscula A-Z."
                # Validar 'Result' (asumiendo que la letra era válida)
                elif not isinstance(result, int) or isinstance(result, bool): # Excluir True/False que son subclase de int
                    error_msg = f"Item en índice {index}: 'Result' no es un entero (tipo: {type(result)})."
                elif not 0 <= result <= 100:
                    error_msg = f"Item en índice {index}: 'Result' ({result}) está fuera del rango [0, 100]."
                else:
                    # Si todas las validaciones del item pasan
                    item_is_valid = True

            if item_is_valid:
                temp_validated_list.append(item) # Añadir solo si el item es completamente válido
            else:
                logging.warning(f"Validación fallida para 'cvScore': {error_msg}")
                all_items_valid = False
                break # Si un item falla, toda la lista 'cvScore' se considera inválida

        # Solo si todos los items pasaron la validación, asignamos la lista validada
        if all_items_valid:
            validated_score_list = temp_validated_list
            logging.info(f"La lista 'cvScore' con {len(validated_score_list)} elementos ha sido validada exitosamente.")
        else:
             logging.warning("La lista 'cvScore' contenía elementos inválidos y no será devuelta.")
             # validated_score_list ya es None o se queda como None

    # --- Devolver los resultados ---
    # Asegurarse de que analysis y name sean strings si existen, sino None
    final_analysis = str(cv_analysis) if isinstance(cv_analysis, str) else None
    if cv_analysis is not None and final_analysis is None:
         logging.warning(f"'cvAnalysis' no era un string (tipo: {type(cv_analysis)}), se devuelve None.")

    final_name = str(candidate_name) if isinstance(candidate_name, str) else None
    if candidate_name is not None and final_name is None:
         logging.warning(f"'nameCandidate' no era un string (tipo: {type(candidate_name)}), se devuelve None.")


    return validated_score_list, final_analysis, final_name