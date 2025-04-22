# mock_api_strict.py
import os
import logging
from flask import Flask, request, jsonify, Response
import json
from datetime import datetime
from flask.wrappers import Request
from functools import wraps

# Configuración de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Crear la aplicación Flask
app = Flask(__name__)

# Nombre del archivo de log
LOG_FILE = "mock_api_strict_log.txt"

# --- Configuración del Mock (puedes ajustar estos valores) ---
FAKE_TOKEN = "este-es-un-token-falso-para-pruebas-locales-strict"
EXPECTED_USERNAME = os.environ.get("API_USERNAME", "testuser") # Obtener de env var o usar default
EXPECTED_PASSWORD = os.environ.get("API_PASSWORD", "testpass") # Obtener de env var o usar default
EXPECTED_ROLE = os.environ.get("API_ROLE", "TestRole")
EXPECTED_USER_APPLICATION = os.environ.get("API_USER_APPLICATION", "TestApp")

# --- Funciones Auxiliares ---

def log_to_file(endpoint: str, method: str, status_code: int, received_headers: dict, received_data: any = None, response_data: any = None):
    """Escribe la información detallada de la solicitud/respuesta en el archivo de log."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    separator = "\n" + "=" * 60 + "\n"  # Separador más visible

    log_entry = f"{separator}"
    log_entry += f"Timestamp  : {timestamp}\n"
    log_entry += f"Endpoint   : {endpoint}\n"
    log_entry += f"Method     : {method}\n"
    log_entry += f"Status Code: {status_code}\n"
    log_entry += f"Headers    : {json.dumps(dict(received_headers), indent=2, ensure_ascii=False)}\n"

    # Formatear datos recibidos si existen y son JSON, de lo contrario 'N/A' o raw
    if received_data is not None:
        try:
            log_entry += f"Received   : {json.dumps(received_data, indent=2, ensure_ascii=False)}\n"
        except TypeError:
            log_entry += f"Received   : {received_data}\n" # Log raw if not JSON serializable
    else:
        log_entry += f"Received   : N/A\n"

    # Formatear datos de respuesta
    if response_data is not None:
        try:
            log_entry += f"Response Body: {json.dumps(response_data, indent=2, ensure_ascii=False)}\n"
        except TypeError:
            log_entry += f"Response Body: {response_data}\n" # Log raw if not JSON serializable
    else:
        log_entry += f"Response Body: None (or non-JSON)\n"

    log_entry += "=" * 60 + "\n" # Cierre del separador

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_entry)
    except Exception as e:
        logging.error(f"ERROR CRITICO: No se pudo escribir en el archivo de log '{LOG_FILE}': {e}", exc_info=True)


def get_json_data(req: Request):
    """Intenta parsear el cuerpo de la solicitud como JSON, manejando errores."""
    try:
        data = req.get_json(silent=True)
        if data is None and req.data: # Si get_json falló pero hay datos, puede no ser JSON válido o Content-Type incorrecto
             logging.warning(f"Cuerpo de solicitud no es JSON válido o falta Content-Type: application/json. Datos crudos: {req.data}")
             return None # Indica fallo en parsing JSON
        if not isinstance(data, (dict, list)): # Asegurar que es un objeto JSON válido (dict o list)
             logging.warning(f"Cuerpo de solicitud no es un objeto JSON (dict/list): {data}")
             return None
        return data
    except Exception as e:
        logging.error(f"Error parsing JSON body: {e}", exc_info=True)
        return None # Indica fallo en parsing JSON


# --- Decorador para exigir Autenticación Bearer Token ---
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            error_msg = "Authentication required: Missing Authorization header."
            logging.warning(f"Auth Failed: {error_msg}")
            log_to_file(request.path, request.method, 401, request.headers, None, {"error": error_msg})
            return jsonify({"error": error_msg}), 401

        parts = auth_header.split()

        if parts[0].lower() != 'bearer':
            error_msg = "Authentication required: Authorization header must start with 'Bearer'."
            logging.warning(f"Auth Failed: {error_msg}")
            log_to_file(request.path, request.method, 401, request.headers, None, {"error": error_msg})
            return jsonify({"error": error_msg}), 401
        elif len(parts) == 1:
            error_msg = "Authentication required: Token not found."
            logging.warning(f"Auth Failed: {error_msg}")
            log_to_file(request.path, request.method, 401, request.headers, None, {"error": error_msg})
            return jsonify({"error": error_msg}), 401
        elif len(parts) > 2:
            error_msg = "Authentication required: Authorization header must be 'Bearer <token>'."
            logging.warning(f"Auth Failed: {error_msg}")
            log_to_file(request.path, request.method, 401, request.headers, None, {"error": error_msg})
            return jsonify({"error": error_msg}), 401

        token = parts[1]

        # En un mock simple, cualquier token Bearer se considera válido
        # Para un mock más avanzado, podrías verificar si token == FAKE_TOKEN
        if token != FAKE_TOKEN:
             error_msg = "Authentication failed: Invalid token."
             logging.warning(f"Auth Failed: {error_msg} - Provided token: {token}")
             log_to_file(request.path, request.method, 403, request.headers, None, {"error": error_msg})
             return jsonify({"error": error_msg}), 403


        logging.info(f"Authentication successful for {request.path}")
        return f(*args, **kwargs)

    return decorated_function


# --- Simulación de Endpoints ---

@app.route('/Account', methods=['POST'])
def authenticate_mock():
    """Simula la autenticación."""
    endpoint = "/Account"
    method = "POST"
    logging.info(f"[{endpoint}] Llamada recibida (Mock)")

    data = get_json_data(request)

    # Validar cuerpo de la solicitud JSON
    required_fields = ['username', 'password', 'role', 'userApplication']
    if data is None:
         error_msg = "Request body must be valid JSON."
         logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
         log_to_file(endpoint, method, 400, request.headers, request.data, {"error": error_msg}) # Log raw data if JSON parsing failed
         return jsonify({"error": error_msg}), 400

    if not isinstance(data, dict):
        error_msg = "Request body must be a JSON object (dictionary)."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    for field in required_fields:
        if field not in data:
            error_msg = f"Missing required field: '{field}' in request body."
            logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
            log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
            return jsonify({"error": error_msg}), 400
        if not isinstance(data[field], str) or not data[field]:
             error_msg = f"Field '{field}' must be a non-empty string."
             logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
             log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
             return jsonify({"error": error_msg}), 400

    # Simular validación de credenciales (simple check)
    if data.get('username') != EXPECTED_USERNAME or \
       data.get('password') != EXPECTED_PASSWORD or \
       data.get('role') != EXPECTED_ROLE or \
       data.get('userApplication') != EXPECTED_USER_APPLICATION:
       error_msg = "Invalid credentials."
       logging.error(f"[{endpoint}] Authentication Failed: {error_msg} - Provided data: {data}")
       log_to_file(endpoint, method, 401, request.headers, data, {"error": error_msg})
       return jsonify({"error": error_msg}), 401

    # Éxito
    logging.info(f"[{endpoint}] Authentication successful. Returning fake token.")
    status_code = 200
    # Devolver token como texto plano, NO JSON
    log_to_file(endpoint, method, status_code, request.headers, data, FAKE_TOKEN)
    return Response(FAKE_TOKEN, status=status_code, mimetype='text/plain') # Usar Response para texto plano


@app.route('/Resumen/<string:rank_id>', methods=['GET'])
@auth_required # Este endpoint requiere autenticación
def get_resumen_mock(rank_id: str):
    """Simula la obtención de datos de resumen por rank_id."""
    endpoint = f"/Resumen/{rank_id}"
    method = "GET"
    logging.info(f"[{endpoint}] Llamada recibida (Mock)")

    # Aquí podrías simular diferentes respuestas basadas en rank_id si necesitas
    # Para este mock simple, siempre devolvemos los mismos datos falsos

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
    logging.info(f"[{endpoint}] Devolviendo datos falsos para rank_id {rank_id}.")
    log_to_file(endpoint, method, status_code, request.headers, {"rank_id": rank_id}, response_data)
    return jsonify(response_data), status_code

# El endpoint /Resumen/AddScores es llamado con POST y expect_response_body=False
@app.route('/Resumen/AddScores', methods=['POST'])
@auth_required # Este endpoint requiere autenticación
def add_scores_mock():
    """Simula la adición de scores."""
    endpoint = "/Resumen/AddScores"
    method = "POST"
    logging.info(f"[{endpoint}] Llamada recibida (Mock)")

    data = get_json_data(request)

    # Validar cuerpo de la solicitud JSON
    required_fields = ['candidateId', 'scores']
    if data is None:
         error_msg = "Request body must be valid JSON."
         logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
         log_to_file(endpoint, method, 400, request.headers, request.data, {"error": error_msg})
         return jsonify({"error": error_msg}), 400

    if not isinstance(data, dict):
        error_msg = "Request body must be a JSON object (dictionary)."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    for field in required_fields:
        if field not in data:
            error_msg = f"Missing required field: '{field}' in request body."
            logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
            log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
            return jsonify({"error": error_msg}), 400

    # Validación específica para 'scores'
    if not isinstance(data['candidateId'], str) or not data['candidateId']:
        error_msg = "Field 'candidateId' must be a non-empty string."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    if not isinstance(data['scores'], dict):
        error_msg = "Field 'scores' must be a JSON object (dictionary)."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    # Validar que los valores dentro de scores sean ints
    for key, value in data['scores'].items():
        if not isinstance(value, int):
            error_msg = f"Value for score '{key}' must be an integer."
            logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
            log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
            return jsonify({"error": error_msg}), 400

    # Éxito
    candidate_id = data['candidateId']
    logging.info(f"[{endpoint}] Scores for candidate_id {candidate_id} received (simulated).")
    status_code = 200 # Puede ser 200 o 201
    # El adaptador espera expect_response_body=False, devolvemos JSON vacío
    log_to_file(endpoint, method, status_code, request.headers, data, {})
    return jsonify({}), status_code


# El endpoint /Resumen/Save es llamado con POST y expect_response_body=False
@app.route('/Resumen/Save', methods=['POST'])
@auth_required # Este endpoint requiere autenticación
def save_resumen_mock():
    """Simula el guardado de un resumen completo."""
    endpoint = "/Resumen/Save"
    method = "POST"
    logging.info(f"[{endpoint}] Llamada recibida (Mock)")

    data = get_json_data(request)

    # Validar cuerpo de la solicitud JSON
    required_fields = ["candidateId", "transcription", "score", "candidateName", "analysis"]
    if data is None:
         error_msg = "Request body must be valid JSON."
         logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
         log_to_file(endpoint, method, 400, request.headers, request.data, {"error": error_msg})
         return jsonify({"error": error_msg}), 400

    if not isinstance(data, dict):
        error_msg = "Request body must be a JSON object (dictionary)."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    for field in required_fields:
        if field not in data:
            error_msg = f"Missing required field: '{field}' in request body."
            logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
            log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
            return jsonify({"error": error_msg}), 400

    # Validación de tipos (más estricta)
    if not isinstance(data['candidateId'], str) or not data['candidateId']:
        error_msg = "Field 'candidateId' must be a non-empty string."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    if not isinstance(data['transcription'], str):
        error_msg = "Field 'transcription' must be a string."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    if not isinstance(data['score'], (int, float)):
        error_msg = "Field 'score' must be an integer or float."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    if not isinstance(data['candidateName'], str) or not data['candidateName']:
        error_msg = "Field 'candidateName' must be a non-empty string."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    if not isinstance(data['analysis'], str):
        error_msg = "Field 'analysis' must be a string."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400


    # Éxito
    candidate_id = data['candidateId']
    logging.info(f"[{endpoint}] Resumen for candidate_id {candidate_id} saved (simulated).")
    status_code = 200
    # El adaptador espera expect_response_body=False, devolvemos JSON vacío
    log_to_file(endpoint, method, status_code, request.headers, data, {})
    return jsonify({}), status_code


# El endpoint /Resumen es llamado con PUT y expect_response_body=False
@app.route('/Resumen', methods=['PUT'])
@auth_required # Este endpoint requiere autenticación
def update_candidate_mock():
    """Simula la actualización de estado de un candidato."""
    endpoint = "/Resumen"
    method = "PUT"
    logging.info(f"[{endpoint}] Llamada recibida (Mock)")

    data = get_json_data(request)

    # Validar cuerpo de la solicitud JSON
    # 'errorMessage' es opcional, pero 'candidateId' es requerido
    if data is None:
         error_msg = "Request body must be valid JSON."
         logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
         log_to_file(endpoint, method, 400, request.headers, request.data, {"error": error_msg})
         return jsonify({"error": error_msg}), 400

    if not isinstance(data, dict):
        error_msg = "Request body must be a JSON object (dictionary)."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    if 'candidateId' not in data:
        error_msg = "Missing required field: 'candidateId' in request body."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    if not isinstance(data['candidateId'], str) or not data['candidateId']:
        error_msg = "Field 'candidateId' must be a non-empty string."
        logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
        log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
        return jsonify({"error": error_msg}), 400

    # Check optional field type if present
    error_message = data.get('errorMessage')
    if error_message is not None and not isinstance(error_message, str):
         error_msg = "Field 'errorMessage' must be a string or null/missing."
         logging.error(f"[{endpoint}] Validation Failed: {error_msg}")
         log_to_file(endpoint, method, 400, request.headers, data, {"error": error_msg})
         return jsonify({"error": error_msg}), 400


    # Éxito
    candidate_id = data['candidateId']
    status_code = 200

    if error_message is None:
        logging.info(f"[{endpoint}] Status updated for candidate_id: {candidate_id} to SUCCESS (simulated).")
    else:
        logging.warning(f"[{endpoint}] Status updated for candidate_id: {candidate_id} to ERROR: '{error_message}' (simulated).")

    # El adaptador espera expect_response_body=False, devolvemos JSON vacío
    log_to_file(endpoint, method, status_code, request.headers, data, {})
    return jsonify({}), status_code


# --- Ejecutar la App ---
if __name__ == '__main__':
    print(f"Iniciando mock API strict en http://127.0.0.1:5001")
    print(f"Archivo de log: {LOG_FILE}")
    print(f"Credenciales esperadas para /Account:")
    print(f"  Username: {EXPECTED_USERNAME}")
    print(f"  Password: {EXPECTED_PASSWORD}")
    print(f"  Role: {EXPECTED_ROLE}")
    print(f"  UserApplication: {EXPECTED_USER_APPLICATION}")

    # Limpiar log anterior al iniciar (opcional)
    # if os.path.exists(LOG_FILE):
    #      print(f"Limpiando log anterior: {LOG_FILE}")
    #      try:
    #          os.remove(LOG_FILE)
    #      except Exception as e:
    #          print(f"ERROR: No se pudo limpiar el log anterior: {e}")


    # Ejecutar en puerto 5001 (o el que prefieras)
    # debug=True es útil durante el desarrollo, pero considera desactivarlo en producción
    app.run(host='127.0.0.1', port=5001, debug=True)