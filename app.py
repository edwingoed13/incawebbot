import os
import json
import time
import google.generativeai as genai
from flask import Flask, request, Response, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
import re

# --- Cargar variables de entorno ---
load_dotenv()

app = Flask(__name__)
CORS(app, resources={r"/chat": {"origins": "*"}}) 

# --- Configuración de Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY no está configurada.")

genai.configure(api_key=GEMINI_API_KEY)

# Usamos gemini-1.5-flash por su velocidad y ventana de contexto
gemini_model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config={
        "temperature": 0.6, # Ligeramente menos creativo para mayor precisión
        "top_p": 0.95,      
        "top_k": 64,        
        "max_output_tokens": 8192, 
    },
    # Ajusta los safety_settings para producción según tus necesidades
    safety_settings=[
        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    ]
)

# === Función para Cargar Tours ===
def cargar_tours():
    """Carga la información de los tours desde el archivo JSON en inglés."""
    try:
        with open('tours_ingles.json', 'r', encoding='utf-8') as f:
            tours_data = json.load(f)
        print(f"✅ {len(tours_data)} tours cargados desde tours_ingles.json.")
        return tours_data
    except FileNotFoundError:
        print("❌ Error: tours_ingles.json no encontrado.")
        return [] 
    except json.JSONDecodeError:
        print("❌ Error al decodificar tours_ingles.json.")
        return [] 

tours_data_loaded = cargar_tours()
historial_global = {}
MAX_HISTORY_TURNS = 5 # Mantener 5 intercambios (user + model)

# === Configuraciones por idioma ===
LANGUAGE_CONFIGS = {
    'es': {
        'stopwords': {'de', 'a', 'el', 'la', 'los', 'las', 'un', 'una', 'y', 'o', 'pero', 'con', 'para', 'qué', 'quiero', 'tienes', 'hay', 'es'},
        'system_instruction': (
            "Eres un asistente de viajes amigable y experto de IncaLake. Tu tarea es responder al usuario en ESPAÑOL.\n"
            "Usa la información de 'Relevant Tour Information' proporcionada a continuación para responder. Esta información está en INGLÉS, pero debes responder en ESPAÑOL.\n"
            "Usa el historial de conversación para contexto. Siempre sé útil y natural.\n"
            "Cuando menciones un tour, DEBES incluir su 'More Info URL'.\n"
            "Si la información proporcionada no es suficiente, di que no tienes ese detalle específico y ofrece los tours disponibles.\n"
            "Para reservas o datos sensibles, dirige al usuario a WhatsApp +51982769453."
        ),
        'greeting': "¡Hola! Soy tu asistente de IncaLake. ¿En qué te puedo ayudar hoy?",
        'error_message': "Lo siento, ocurrió un error en el servidor. Por favor, intenta más tarde.",
        'no_tours_message': "No se encontró información de tours relevante para esta consulta."
    },
    'en': {
        'stopwords': {'the', 'a', 'an', 'and', 'or', 'but', 'with', 'for', 'what', 'want', 'have', 'is', 'are', 'to', 'of', 'in', 'on', 'at'},
        'system_instruction': (
            "You are a friendly and expert travel assistant for IncaLake. Your task is to answer the user in ENGLISH.\n"
            "Use the 'Relevant Tour Information' provided below to answer. This data is in ENGLISH, so you can use it directly.\n"
            "Use the conversation history for context. Always be helpful and natural.\n"
            "When you mention a tour, you MUST include its 'More Info URL'.\n"
            "If the provided information is not enough, say that you don't have that specific detail and offer the available tours.\n"
            "For reservations or sensitive data, refer the user to WhatsApp +51982769453."
        ),
        'greeting': "Hello! I'm your IncaLake assistant. How can I help you today?",
        'error_message': "Sorry, a server error occurred. Please try again later.",
        'no_tours_message': "No relevant tour information found for this query."
    }
}

# === Funciones de Búsqueda y Traducción Contextual ===

def obtener_keywords_contextuales(historial, pregunta_actual, language='es'):
    """Extrae palabras clave del contexto de la conversación según el idioma."""
    texto_a_procesar = pregunta_actual.lower()
    if historial:
        user_messages = [h['parts'][0] for h in historial if h['role'] == 'user']
        texto_a_procesar = " ".join(user_messages[-2:]) + " " + texto_a_procesar

    stopwords = LANGUAGE_CONFIGS[language]['stopwords']
    palabras = re.findall(r'\b\w{3,}\b', texto_a_procesar)
    keywords = {palabra for palabra in palabras if palabra not in stopwords}
    print(f"🔑 Keywords contextuales ({language.upper()}): {keywords}")
    return list(keywords)

def traducir_keywords_a_ingles(keywords, source_language='es'):
    """Usa Gemini para traducir keywords al inglés si es necesario."""
    if not keywords: 
        return []
    
    # Si el idioma fuente ya es inglés, no necesitamos traducir
    if source_language == 'en':
        print(f"🌐 Keywords ya en inglés: {keywords}")
        return keywords
    
    # Traducir de español a inglés
    prompt = f"Translate the following Spanish travel keywords to English. Provide only the most relevant, single-word English equivalent for each. Return as a comma-separated list. Keywords: '{', '.join(keywords)}'"
    try:
        response = genai.GenerativeModel('gemini-1.5-flash').generate_content(prompt)
        english_keywords = [kw.strip() for kw in response.text.strip().lower().split(',')]
        print(f"🌐 Keywords traducidas (EN): {english_keywords}")
        return english_keywords
    except Exception as e:
        print(f"❌ Error en la traducción de keywords: {e}")
        return keywords  # Devolver keywords originales si falla la traducción

def buscar_tours_relevantes(keywords_en):
    """Busca en el JSON usando las palabras clave en inglés."""
    if not keywords_en: 
        return []
    
    scored_tours = []
    for tour in tours_data_loaded:
        score = 0
        texto_busqueda = (
            tour.get("titulo_producto", "") + " " + 
            tour.get("tipo_servicio", "") + " " + 
            tour.get("descripcion_tab", "")
        ).lower()
        
        for keyword in keywords_en:
            if keyword in texto_busqueda:
                # Dar más peso si está en el título
                score += 5 if keyword in tour.get("titulo_producto", "").lower() else 1
        
        if score > 0:
            # Ajustar score por prioridad
            score += (6 - tour.get("prioridad", 5))
            scored_tours.append((score, tour))
    
    # Ordenar por score descendente y devolver los 3 mejores
    scored_tours.sort(key=lambda x: x[0], reverse=True)
    return [tour for score, tour in scored_tours[:3]]

def formatear_contexto_detallado(tours, language='es'):
    """Crea un resumen detallado y bien formateado de los tours para el prompt."""
    if not tours: 
        return LANGUAGE_CONFIGS[language]['no_tours_message']
    
    resumen_partes = ["--- Relevant Tour Information (Data in English) ---"]
    for tour in tours:
        titulo = tour.get("titulo_producto", "No title")
        descripcion = tour.get("descripcion_tab", "No description")
        itinerario = tour.get("itinerario_ta", "No itinerary provided.")
        url = tour.get("url_servicio", "No URL available.")
        
        # Formatear precios
        precios_formateados = "Price on request."
        try:
            precios = json.loads(tour.get("precios_rango", "{}"))
            if precios and all(k in precios for k in ["desde", "hasta", "precio"]):
                price_entries = [
                    f"For {d}-{h} people: ${p} USD" 
                    for d, h, p in zip(precios["desde"], precios["hasta"], precios["precio"])
                ]
                precios_formateados = "\n".join(price_entries)
        except (json.JSONDecodeError, TypeError):
            pass

        resumen_partes.append(
            f"\nTour: {titulo}\n"
            f"Description: {descripcion}\n"
            f"Itinerary Summary: {itinerario[:200]}{'...' if len(itinerario) > 200 else ''}\n"
            f"Prices: {precios_formateados}\n"
            f"More Info URL: {url}"
        )
    
    return "\n".join(resumen_partes)

# === Función para construir el historial para Gemini ===

def construir_historial_gemini(historial_previo, instruccion_principal, contexto_detallado, pregunta_actual, language='es'):
    """Construye el historial completo para enviar a Gemini."""
    historial_para_gemini = []
    
    # Añadir instrucción principal como contexto del sistema
    historial_para_gemini.append({
        "role": "user", 
        "parts": [instruccion_principal]
    })
    
    # Añadir saludo inicial del bot
    historial_para_gemini.append({
        "role": "model", 
        "parts": [LANGUAGE_CONFIGS[language]['greeting']]
    })
    
    # Añadir historial previo
    historial_para_gemini.extend(historial_previo)
    
    # Añadir contexto y pregunta actual
    prompt_actual = f"{contexto_detallado}\n\nUser Question: {pregunta_actual}"
    historial_para_gemini.append({
        "role": "user", 
        "parts": [prompt_actual]
    })
    
    return historial_para_gemini

# === Ruta Principal del Chat ===

@app.route('/chat', methods=['POST', 'OPTIONS'])
def chat():
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200

    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        pregunta = data.get('message', '').strip()
        session_id = data.get('session_id', 'default_session')
        language = data.get('language', 'es')  # Obtener idioma del frontend
        
        # Validar idioma
        if language not in LANGUAGE_CONFIGS:
            language = 'es'  # Fallback a español
            
        print(f"🌍 Idioma detectado: {language}")
        print(f"💬 Pregunta: {pregunta}")

        if not pregunta:
            return jsonify({"error": "El mensaje no puede estar vacío."}), 400

        # 1. Obtener historial (o inicializarlo)
        historial = historial_global.get(session_id, [])

        # 2. Lógica de búsqueda contextual y formateo
        keywords = obtener_keywords_contextuales(historial, pregunta, language)
        keywords_en = traducir_keywords_a_ingles(keywords, language)
        tours_relevantes = buscar_tours_relevantes(keywords_en)
        contexto_detallado = formatear_contexto_detallado(tours_relevantes, language)
        
        # 3. Obtener configuración del idioma
        config = LANGUAGE_CONFIGS[language]
        
        # 4. Construir historial para Gemini
        historial_para_gemini = construir_historial_gemini(
            historial, 
            config['system_instruction'], 
            contexto_detallado, 
            pregunta, 
            language
        )

        def stream_response():
            respuesta_completa = ""
            try:
                # Generar respuesta con streaming
                response_stream = gemini_model.generate_content(
                    historial_para_gemini,
                    stream=True
                )
                
                for chunk in response_stream:
                    if chunk.text:
                        respuesta_completa += chunk.text
                        yield chunk.text
                        time.sleep(0.01)  # Pequeña pausa para mejor UX
                
                # 5. Actualizar historial global después de una respuesta exitosa
                current_historial = historial_global.get(session_id, [])
                current_historial.append({"role": "user", "parts": [pregunta]})
                current_historial.append({"role": "model", "parts": [respuesta_completa]})
                
                # Mantener solo el historial más reciente
                if len(current_historial) > MAX_HISTORY_TURNS * 2:
                    current_historial = current_historial[-(MAX_HISTORY_TURNS * 2):]
                
                historial_global[session_id] = current_historial
                print(f"✅ Historial actualizado para sesión {session_id}")

            except Exception as e:
                print(f"❌ Error al generar respuesta de Gemini: {e}")
                yield config['error_message']

        return Response(stream_response(), mimetype='text/plain')
    
    except Exception as e:
        print(f"❌ Error general en /chat: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500

# === Ruta para obtener información de sesión (opcional) ===

@app.route('/session/<session_id>', methods=['GET'])
def get_session_info(session_id):
    """Obtiene información de una sesión específica."""
    historial = historial_global.get(session_id, [])
    return jsonify({
        "session_id": session_id,
        "messages_count": len(historial),
        "last_activity": time.time() if historial else None
    })

# === Ruta para limpiar historial (opcional) ===

@app.route('/session/<session_id>/clear', methods=['POST'])
def clear_session(session_id):
    """Limpia el historial de una sesión específica."""
    if session_id in historial_global:
        del historial_global[session_id]
        return jsonify({"message": f"Historial de sesión {session_id} limpiado."})
    return jsonify({"message": "Sesión no encontrada."}), 404

# === Ruta principal ===

@app.route('/')
def index():
    return jsonify({
        "message": "API de IncaLake Chatbot funcionando",
        "version": "2.0",
        "supported_languages": list(LANGUAGE_CONFIGS.keys()),
        "endpoints": {
            "chat": "/chat",
            "session_info": "/session/<session_id>",
            "clear_session": "/session/<session_id>/clear"
        }
    })

# === Ruta de salud ===

@app.route('/health')
def health_check():
    """Endpoint de health check para monitoring."""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "tours_loaded": len(tours_data_loaded),
        "active_sessions": len(historial_global)
    })

if __name__ == '__main__':
    print("🚀 Iniciando IncaLake Chatbot API...")
    print(f"📚 Tours cargados: {len(tours_data_loaded)}")
    print(f"🌍 Idiomas soportados: {list(LANGUAGE_CONFIGS.keys())}")
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv("PORT", 5000)))