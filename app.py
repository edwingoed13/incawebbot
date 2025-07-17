import os
import json
import time
import google.generativeai as genai
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
from dotenv import load_dotenv

# --- Cargar variables de entorno ---
load_dotenv()

app = Flask(__name__)
CORS(app) 

# --- Configuración de Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError(
        "GEMINI_API_KEY no está configurada en las variables de entorno. "
        "Asegúrate de crear un archivo .env con GEMINI_API_KEY='TU_API_KEY_DE_GEMINI'."
    )

genai.configure(api_key=GEMINI_API_KEY)

# Inicializar el modelo Gemini 2.5 Flash
gemini_model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config={
        "temperature": 0.7,  
        "top_p": 0.95,       
        "top_k": 64,         
        "max_output_tokens": 8192, 
    },
    safety_settings=[
        # Mantener BLOCK_NONE para depuración, pero recuerda cambiar para producción
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
    ]
)

# === Función para Cargar Tours ===
def cargar_tours():
    """Carga la información de los tours desde un archivo JSON."""
    try:
        with open('tours_ingles.json', 'r', encoding='utf-8') as f:
            tours_data = json.load(f)
        print(f"✅ {len(tours_data)} tours cargados correctamente.")
        return tours_data
    except FileNotFoundError:
        print("❌ Error: tours_ingles.json no encontrado. Asegúrate de que esté en el mismo directorio.")
        return [] 
    except json.JSONDecodeError:
        print("❌ Error al decodificar tours_ingles.json. Verifica el formato del archivo JSON.")
        return [] 

# === Función para Obtener Resumen de Tours ===
def obtener_resumen_tours(tours_list, user_query="", history=None, detailed_context=False):
    """
    Genera un resumen de los tours disponibles.
    Si detailed_context es True, genera un resumen detallado para tours relevantes.
    Si detailed_context es False, genera un resumen conciso de nombres/tipos de tours.
    """
    if history is None:
        history = []

    keywords = user_query.lower().split()
    
    relevant_tours = []
    
    # Primero, busca tours que contengan las palabras clave en el título o descripción
    for tour in tours_list:
        title_lower = tour.get("titulo_producto", "").lower()
        desc_lower = tour.get("descripcion_tab", "").lower()
        
        is_relevant = False
        for keyword in keywords:
            if len(keyword) > 2 and (keyword in title_lower or keyword in desc_lower):
                is_relevant = True
                break
        
        if is_relevant:
            relevant_tours.append(tour)

    # Si no se encontraron tours relevantes por palabra clave o si detailed_context es False
    # simplemente priorizamos por la prioridad numérica para una lista concisa o para un fallback
    if not relevant_tours or not detailed_context:
        # Si no queremos contexto detallado, o si no hay tours relevantes específicos,
        # nos quedamos con los de mayor prioridad (ej. <= 3) para una lista general.
        relevant_tours = [tour for tour in tours_list if tour.get("prioridad", 5) <= 3]

    # Ordenar por prioridad (más baja es mejor)
    # Se usa tuple(sorted(d.items())) para poder usar set() y eliminar duplicados de diccionarios
    # y luego se convierte de nuevo a lista de diccionarios.
    unique_relevant_tours = []
    seen = set()
    for tour in sorted(relevant_tours, key=lambda x: x.get("prioridad", 5)):
        tour_tuple = tuple(sorted(tour.items()))
        if tour_tuple not in seen:
            seen.add(tour_tuple)
            unique_relevant_tours.append(tour)

    resumen_partes = []
    
    if not detailed_context: # Modo resumen conciso (para el primer prompt)
        if not unique_relevant_tours:
            return "No tour information available."
        
        tour_names = [tour.get("titulo_producto", "Unknown Tour") for tour in unique_relevant_tours]
        return "Our main tours include: " + ", ".join(tour_names) + ". Ask us for more details about any of them!"

    else: # Modo resumen detallado (cuando se necesita más contexto)
        if not unique_relevant_tours:
            return "No relevant tour information found based on the query for detailed context."

        for tour in unique_relevant_tours:
            titulo = tour.get("titulo_producto", "No title")
            descripcion = tour.get("descripcion_tab", "No description")
            itinerario = tour.get("itinerario_ta", "No itinerary provided.")
            incluye = tour.get("incluye_tab", "No inclusions provided.")
            url = tour.get("url_servicio", "No URL available.") # <--- Aquí se obtiene la URL
            
            precios_raw = tour.get("precios_rango", "{}")
            precios = {}
            try:
                precios = json.loads(precios_raw)
            except json.JSONDecodeError:
                print(f"Advertencia: No se pudo decodificar precios_rango para {titulo}")
            
            precios_formateados = "Prices not available."
            if precios and isinstance(precios, dict) and \
               "desde" in precios and "hasta" in precios and "precio" in precios and \
               len(precios["desde"]) == len(precios["hasta"]) == len(precios["precio"]):
                
                price_entries = []
                for i in range(len(precios["desde"])):
                    p_desde = precios["desde"][i]
                    p_hasta = precios["hasta"][i]
                    p_precio = precios["precio"][i]
                    price_entries.append(f"For {p_desde} to {p_hasta} people: ${p_precio} USD per person.")
                precios_formateados = "\n".join(price_entries)

            resumen_partes.append(f"--- Tour: {titulo} (Prioridad: {tour.get('prioridad', 'N/A')}) ---\n"
                                 f"Description: {descripcion}\n"
                                 f"Itinerary: {itinerario}\n"
                                 f"Includes: {incluye}\n"
                                 f"Prices (per person): {precios_formateados}\n"
                                 f"**More Info URL: {url}**\n") # <--- Aquí se formatea la URL explícitamente
        
        return "\n".join(resumen_partes)

# La carga inicial de tours solo carga los datos
tours_data_loaded = cargar_tours()

# Diccionario para mantener el historial de conversación por sesión
historial_global = {}

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json()
    pregunta = data.get('message', '')
    session_id = data.get('session_id', 'default') 

    if not pregunta:
        return jsonify({"error": "El mensaje no puede estar vacío."}), 400

    instruccion = (
        "Eres un asistente de viajes útil para IncaLake, una agencia de viajes peruana. Tu objetivo es proporcionar información clara y amigable sobre los tours."
        "Da una Bienvenida cordial con preguntas abiertas: '¿Qué tour o paquete te interesa, para qué fecha, y cuántas personas viajan?'"
"Recolectar información de contacto (nombre completo, whatsapp y/o correo electrónico) al inicio."
"Si te pregunta cosas generales, como qué tour tomar, puedes tomar información del blog de incalake.com/blog para responder. No inventes información si no estás seguro."
"Si el usuario de la agencia de viajes hace preguntas relacionadas con reservas hechas, envía documentos sensibles (por ejemplo, pasaportes), o si no entiendes claramente el contexto de su mensaje, responde amablemente indicándole que en breve será atendido por un agente humano o puede whatsappearnos al +51982769453 para mayor información. No intentes resolver estos casos directamente."
"Utiliza estrictamente los datos de los tours proporcionados para responder preguntas. Al proporcionar información sobre un tour, incluye siempre la 'More Info URL' completa para el tour específico."
"Prioriza los tours con números de 'Prioridad' más bajos (siendo 1 el más alto y 5 el más bajo) al sugerir o describir tours."
"Si un usuario pregunta por precios, siempre consulta 'Prices (per person)' y proporciona el rango correcto. Si solicitan más detalles, consulta 'Description', 'Itinerary' o 'Includes'. Responde en el idioma del usuario y limita tu respuesta a 5 párrafos. Evita detalles innecesarios a menos que el usuario solicite más información."
    )

    if session_id not in historial_global:
        historial_global[session_id] = []

    historial = historial_global[session_id]

    full_prompt_for_gemini = "" # Se inicializa vacío

    if not historial: 
        # Primera interacción: Inyecta la instrucción y un RESUMEN CONCISO de tours
        resumen_inicial_conciso = obtener_resumen_tours(tours_data_loaded, detailed_context=False)
        full_prompt_for_gemini = f"{instruccion}\n\nAvailable tours summary: {resumen_inicial_conciso}\n\nUser query: {pregunta}"
        historial.append({"role": "user", "parts": [full_prompt_for_gemini]})
    else:
        # Interacciones subsiguientes:
        # AQUI ES DONDE INYECTAMOS EL CONTEXTO DETALLADO SI LA PREGUNTA ES ESPECÍFICA
        # Esto hace que el modelo tenga los detalles completos del tour RELEVANTE en el turno actual
        # sin cargar todo el catálogo en cada prompt.
        resumen_detallado_contextual = obtener_resumen_tours(tours_data_loaded, user_query=pregunta, detailed_context=True, history=historial)
        
        # Combinamos la instrucción (del primer turno, si es una nueva sesión) o un recordatorio
        # con el resumen detallado y la pregunta actual.
        # Es mejor incluir solo la pregunta del usuario en el historial principal de Gemini,
        # y usar el resumen detallado como parte del *primer* mensaje en cada turno, si es relevante.
        # Sin embargo, dado cómo se usa `send_message`, la mejor manera es inyectarlo en el prompt.

        # Adaptamos el último mensaje del historial (el del usuario)
        # para que incluya el resumen detallado si aplica.
        # Primero, removemos el último mensaje del usuario para modificarlo.
        last_user_message = historial.pop()
        
        # Aseguramos que el contenido sea una lista de partes
        content_parts = last_user_message.get("parts", [last_user_message.get("content", "")])
        
        # Agregamos el resumen detallado ANTES de la pregunta del usuario para el modelo.
        # Solo lo hacemos si el resumen detallado no es solo una frase genérica de "no se encontró".
        if resumen_detallado_contextual and "No relevant tour information found" not in resumen_detallado_contextual:
            # Añadimos una sección clara para el modelo
            content_parts.insert(0, f"Relevant detailed tour information for this query:\n{resumen_detallado_contextual}\n\n")
            # Podríamos también re-insertar la instrucción aquí si la conversación se vuelve larga
            # y queremos que el modelo siempre la tenga fresca.
            # content_parts.insert(0, instruccion + "\n\n")

        # Restauramos el mensaje del usuario modificado en el historial.
        historial.append({"role": "user", "parts": content_parts})
        # La `pregunta` que se envía a `send_message` sigue siendo la original del cliente.
        # La magia está en que el historial ya contiene el contexto "inyectado".


    # --- DEBUGGING ---
    print(f"\n--- Nueva Solicitud (Session ID: {session_id}) ---")
    print(f"DEBUG: Mensaje original del usuario: '{pregunta}'")
    if not historial: 
        print(f"DEBUG: Prompt completo inicial enviado a Gemini: '{full_prompt_for_gemini}'")
    else:
        # Imprime el historial que se enviará a Gemini para depuración de turnos subsiguientes
        print(f"DEBUG: Historial (con contexto inyectado) enviado a Gemini:\n{json.dumps(historial, indent=2)}")
    # --- FIN DEBUGGING ---

    def stream_response():
        respuesta_completa = ""
        text_yielded = False 

        try:
            gemini_chat_history = []
            # Construye el historial de chat para Gemini.
            # El último elemento del historial de Flask es la pregunta actual del usuario (posiblemente enriquecida).
            # Los elementos anteriores son interacciones previas.
            for entry in historial: 
                gemini_role = "model" if entry["role"] == "assistant" else "user"
                # Aseguramos que 'parts' sea siempre una lista de cadenas
                content = entry.get("content")
                parts_content = entry.get("parts")
                if parts_content is not None:
                    # Si ya es una lista de partes, úsala directamente
                    pass
                elif content is not None:
                    # Si es solo 'content', envuélvelo en una lista
                    parts_content = [content]
                else:
                    parts_content = [""] # Default empty if neither is present

                gemini_chat_history.append({"role": gemini_role, "parts": parts_content})

            chat_session = gemini_model.start_chat(history=gemini_chat_history)
            
            # Envía el último mensaje del usuario (el que Flask agregó al historial)
            # a la sesión de chat. Esto es lo que Gemini ve como el "turno actual".
            # Es importante que este sea *solo* el mensaje del usuario, no el prompt complejo.
            # El prompt complejo ya está en el historial.
            # Por lo tanto, `pregunta` es el valor correcto aquí.
            response_stream = chat_session.send_message(pregunta, stream=True)

            for chunk in response_stream:
                if chunk.prompt_feedback and chunk.prompt_feedback.safety_ratings:
                    safety_issues = []
                    for rating in chunk.prompt_feedback.safety_ratings:
                        if rating.blocked:
                            safety_issues.append(f"{rating.category} (umbral: {rating.threshold})")
                    if safety_issues:
                        error_msg = f"IncaLake: Lo siento, no puedo responder a eso. Contenido bloqueado por seguridad: {'; '.join(safety_issues)}"
                        print(f"DEBUG: {error_msg}")
                        yield error_msg
                        return 

                if chunk.text: 
                    parte = chunk.text
                    respuesta_completa += parte
                    yield parte 
                    time.sleep(0.01)
                    text_yielded = True 

            if not text_yielded:
                print("DEBUG: La respuesta del modelo está vacía o fue bloqueada al final del stream.")
                if hasattr(response_stream, 'candidates') and response_stream.candidates:
                    last_candidate = response_stream.candidates[0]
                    if hasattr(last_candidate, 'finish_reason') and last_candidate.finish_reason == 1: # SAFETY
                         yield "IncaLake: Lo siento, no pude generar una respuesta. La conversación ha sido bloqueada por motivos de seguridad."
                    else:
                        yield "IncaLake: Lo siento, no pude generar una respuesta para eso. Puede que el contenido sea sensible o no tenga información relevante."
                else:
                    yield "IncaLake: Lo siento, no pude generar una respuesta para eso. Puede que el contenido sea sensible o no tenga información relevante."
                return 

            historial.append({"role": "assistant", "content": respuesta_completa})

        except Exception as e:
            print(f"Error durante la generación de la respuesta: {e}")
            if "finish_reason" in str(e) and "1" in str(e) and "Part" in str(e):
                yield "IncaLake: Lo siento, no puedo responder a eso. El contenido fue bloqueado por razones de seguridad."
            else:
                yield "IncaLake: Lo siento, algo salió mal. Por favor, inténtalo de nuevo más tarde."

    return Response(stream_response(), mimetype='text/plain')

@app.route('/')
def index():
    return "¡La API de IncaLake con Gemini 2.5 Flash está funcionando! <a href='/chat'>Ir al chat</a>"

@app.route('/chat')
def chat_page():
    return app.send_static_file('index_2.html')

@app.route('/index_2.html')
def serve_index():
    return app.send_static_file('index_2.html')

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)