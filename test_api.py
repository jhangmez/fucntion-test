# mock_api.py
import os
import logging
from flask import Flask, request, jsonify
import json  # Importar json para formatear el body
from datetime import datetime  # Para añadir timestamp al log

# Configuración básica de logging (opcional, Flask ya loguea a consola)
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Crear la aplicación Flask
app = Flask(__name__)

# Nombre del archivo de log
LOG_FILE = "mock_api_log.txt"

# Función auxiliar para escribir en el archivo de log
def log_to_file(endpoint: str, method: str, received_data: any, response_data: any, status_code: int):
    """Escribe la información de la solicitud/respuesta en el archivo de log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    separator = "\n" + "#" * 50 + "\n"  # Separador más visible

    log_entry = f"{separator}"
    log_entry += f"Timestamp: {timestamp}\n"
    log_entry += f"Endpoint : {endpoint}\n"
    log_entry += f"Method   : {method}\n"
    log_entry += f"Received : {json.dumps(received_data, indent=2, ensure_ascii=False) if received_data else 'N/A'}\n"  # Formatear JSON
    log_entry += f"Response : Status={status_code}, Body={json.dumps(response_data, indent=2, ensure_ascii=False) if isinstance(response_data, (dict, list)) else response_data}\n"  # Formatear JSON si es dict/list

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:  # Modo 'a' para añadir (append)
            f.write(log_entry)
    except Exception as e:
        print(f"ERROR: No se pudo escribir en el archivo de log '{LOG_FILE}': {e}")  # Log de error a consola si falla escritura


# --- Simulación de Endpoints ---

@app.route('/Account', methods=['POST'])
def authenticate_mock():
    data = request.json
    endpoint = "/Account"
    method = "POST"
    logging.info(f"Llamada recibida a {endpoint} (Mock)")
    logging.info(f"  -> Datos recibidos: {data}")

    fake_token = "este-es-un-token-falso-para-pruebas-locales"
    status_code = 200
    # Loguear antes de retornar
    log_to_file(endpoint, method, data, fake_token, status_code)
    logging.info(f"  <- Devolviendo token falso.")
    return fake_token, status_code

@app.route('/Resumen/<string:rank_id>', methods=['GET'])
def get_resumen_mock(rank_id: str):
    endpoint = f"/Resumen/{rank_id}"
    method = "GET"
    logging.info(f"Llamada recibida a {endpoint} (Mock)")

    # --- DATOS FALSOS REALISTAS ---
    fake_profile_description = "Data Scientist"
    fake_variables_content = """
A. Años de experiencia total.
- 5 o más años: asígnale 100%
- 4 años: asígnale 75%
- 3 años: asígnale 30%
- Menos de 2 años: asígnale 0%
B. Años de experiencia en Modelos Predictivos.
- 5 o más años: asígnale 100%
- 4 años: asígnale 75%
- 3 años: asígnale 30%
- Menos de 2 años: asígnale 0%
C. Años de experiencia en MLops.
- 3 o más años: asígnale 100%
- 2 años: asígnale 75%
- 1 año: asígnale 45%
- Menos de 1 año: asígnale 0%
D. Años de experiencia en la nube (AZURE, AWS, GCP)
- Si tiene experiencia en Azure, GCP y AWS: asígnale 100%
- Si tiene experiencia en Azure y AWS: asígnale 80%
- Si solo tiene experiencia en Azure: asígnale 50%
- Si no tiene experiencia en Azure: asígnale 0%
E. Años de experiencia en bases de datos estructuradas.
- 5 o más años: asígnale 100%
- 4 años: asígnale 75%
- 3 años: asígnale 30%
- Menos de 2 años: asígnale 0%
F. Años de experiencia en análisis de datos con Python.
- 5 o más años: asígnale 100%
- 4 años: asígnale 75%
- 3 años: asígnale 30%
- Menos de 2 años: asígnale 0%
G. Años de experiencia en framework de procesamiento de datos Spark.
- 3 o más años: asígnale 100%
- 2 años: asígnale 75%
- 1 año: asígnale 45%
- Menos de 1 año: asígnale 0%
"""
    response_data = {
        "profileDescription": fake_profile_description,
        "variablesContent": fake_variables_content
    }
    status_code = 200
    log_to_file(endpoint, method, {"rank_id": rank_id}, response_data, status_code)  # Loguear el ID recibido
    logging.info(f"  <- Devolviendo datos falsos para rank_id {rank_id}.")
    return jsonify(response_data), status_code

@app.route('/Resumen/AddScores', methods=['POST'])
def add_scores_mock():
    data = request.json
    endpoint = "/Resumen/AddScores"
    method = "POST"
    logging.info(f"Llamada recibida a {endpoint} (Mock)")
    logging.info(f"  -> Datos recibidos: {data}")

    if not data or 'candidateId' not in data or 'scores' not in data:
        logging.error("  <- Datos inválidos recibidos en AddScores.")
        response_data = {"error": "Datos inválidos"}
        status_code = 400
        log_to_file(endpoint, method, data, response_data, status_code)
        return jsonify(response_data), status_code

    candidate_id = data.get('candidateId')
    response_data = {"message": f"Scores para {candidate_id} recibidos (simulado)"}
    status_code = 201
    log_to_file(endpoint, method, data, response_data, status_code)
    logging.info(f"  <- Scores recibidos para candidate_id: {candidate_id}.")
    return jsonify(response_data), status_code

@app.route('/Resumen/Save', methods=['POST'])
def save_resumen_mock():
    data = request.json
    endpoint = "/Resumen/Save"
    method = "POST"
    logging.info(f"Llamada recibida a {endpoint} (Mock)")
    # Loguear solo datos clave para no llenar el log si transcription/analysis son largos
    log_data_received = {
        "candidateId": data.get('candidateId'),
        "score": data.get('score'),
        "candidateName": data.get('candidateName'),
        "analysis_length": len(data.get('analysis', '')) if data else 0,
        "transcription_length": len(data.get('transcription', '')) if data else 0
    }
    logging.info(f"  -> Datos recibidos (resumen): {log_data_received}")


    if not data or not all(k in data for k in ["candidateId", "transcription", "score", "candidateName", "analysis"]):
         logging.error("  <- Datos inválidos recibidos en SaveResumen.")
         response_data = {"error": "Datos inválidos"}
         status_code = 400
         log_to_file(endpoint, method, data, response_data, status_code)  # Loguear el error
         return jsonify(response_data), status_code

    candidate_id = data.get('candidateId')
    response_data = {"message": f"Resumen para {candidate_id} guardado (simulado)"}
    status_code = 200  # O 201
    log_to_file(endpoint, method, data, response_data, status_code)  # Loguear éxito
    logging.info(f"  <- Resumen guardado para candidate_id: {candidate_id}.")
    return jsonify(response_data), status_code

@app.route('/Resumen', methods=['PUT'])
def update_candidate_mock():
    data = request.json
    endpoint = "/Resumen"
    method = "PUT"
    logging.info(f"Llamada recibida a {endpoint} (Mock)")
    logging.info(f"  -> Datos recibidos: {data}")

    if not data or 'candidateId' not in data:
        logging.error("  <- Datos inválidos recibidos en UpdateCandidate.")
        response_data = {"error": "Datos inválidos"}
        status_code = 400
        log_to_file(endpoint, method, data, response_data, status_code)
        return jsonify(response_data), status_code

    candidate_id = data.get('candidateId')
    error_message = data.get('errorMessage')
    response_data = {"message": f"Estado para {candidate_id} actualizado (simulado)"}
    status_code = 200

    if error_message is None:
        logging.info(f"  <- Estado actualizado para candidate_id: {candidate_id} a ÉXITO.")
    else:
        logging.warning(f"  <- Estado actualizado para candidate_id: {candidate_id} a ERROR: '{error_message}'.")

    log_to_file(endpoint, method, data, response_data, status_code)
    return jsonify(response_data), status_code

# --- Ejecutar la App ---
if __name__ == '__main__':
    # Limpiar log anterior al iniciar (opcional)
    if os.path.exists(LOG_FILE):
         print(f"Limpiando log anterior: {LOG_FILE}")
         # os.remove(LOG_FILE) # Descomenta si quieres empezar con archivo vacío cada vez

    # Ejecutar en puerto 5001 (o el que prefieras que no sea el de Functions)
    app.run(host='127.0.0.1', port=5001, debug=True)