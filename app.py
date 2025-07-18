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
        "temperature": 0.6,
        "top_p": 0.95,      
        "top_k": 64,        
        "max_output_tokens": 8192, 
    },
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
MAX_HISTORY_TURNS = 5

# === Nuevas funciones para detección de intención ===

def detectar_intencion_consulta(pregunta, language='es'):
    """Detecta si la pregunta es muy general o específica."""
    pregunta_lower = pregunta.lower()
    
    # Patrones para preguntas muy generales
    patrones_generales = {
        'es': [
            r'\b(info|información)\s+(sobre\s+)?tours?\b',
            r'\btours?\s+(disponibles?|que\s+tienen?)\b',
            r'\bqué\s+tours?\s+(hay|tienen|ofrecen)\b',
            r'\bque\s+actividades?\s+(hay|tienen|ofrecen)\b',
            r'\bque\s+hacer\s+en\b',
            r'\bturismo\s+en\b',
            r'\bviajes?\s+a\b',
            r'\bdestinos?\s+(disponibles?|que\s+tienen?)\b',
            r'^(hola|hello|buenos?\s+días?|buenas?\s+tardes?)',
            r'\bpaquetes?\s+turísticos?\b'
        ],
        'en': [
            r'\binfo\s+(about\s+)?tours?\b',
            r'\btours?\s+(available|you\s+have)\b',
            r'\bwhat\s+tours?\s+(do\s+you\s+have|are\s+available)\b',
            r'\bwhat\s+activities?\s+(do\s+you\s+have|are\s+available)\b',
            r'\bwhat\s+to\s+do\s+in\b',
            r'\btourism\s+in\b',
            r'\btrips?\s+to\b',
            r'\bdestinations?\s+(available|you\s+have)\b',
            r'^(hi|hello|good\s+morning|good\s+afternoon)',
            r'\btravel\s+packages?\b'
        ]
    }
    
    for patron in patrones_generales.get(language, patrones_generales['es']):
        if re.search(patron, pregunta_lower):
            return 'general'
    
    return 'specific'

def obtener_destinos_disponibles():
    """Extrae los destinos únicos de los tours disponibles."""
    destinos = set()
    for tour in tours_data_loaded:
        # Extraer destino del título o tipo de servicio
        titulo = tour.get("titulo_producto", "").lower()
        tipo = tour.get("tipo_servicio", "").lower()
        
        # Mapear destinos comunes
        if any(word in titulo + " " + tipo for word in ['puno', 'titicaca', 'uros', 'taquile', 'amantani']):
            destinos.add('Puno')
        if any(word in titulo + " " + tipo for word in ['cusco', 'machu picchu', 'sacred valley']):
            destinos.add('Cusco')
        if any(word in titulo + " " + tipo for word in ['arequipa', 'colca', 'canyon']):
            destinos.add('Arequipa')
        if any(word in titulo + " " + tipo for word in ['uyuni', 'salar', 'bolivia']):
            destinos.add('Uyuni')
        if any(word in titulo + " " + tipo for word in ['lima']):
            destinos.add('Lima')
    
    return sorted(list(destinos))

def contar_tours_por_destino(destino):
    """Cuenta cuántos tours hay para un destino específico."""
    count = 0
    destino_lower = destino.lower()
    
    for tour in tours_data_loaded:
        titulo = tour.get("titulo_producto", "").lower()
        tipo = tour.get("tipo_servicio", "").lower()
        
        if destino_lower == 'puno' and any(word in titulo + " " + tipo for word in ['puno', 'titicaca', 'uros', 'taquile', 'amantani']):
            count += 1
        elif destino_lower == 'cusco' and any(word in titulo + " " + tipo for word in ['cusco', 'machu picchu', 'sacred valley']):
            count += 1
        elif destino_lower == 'arequipa' and any(word in titulo + " " + tipo for word in ['arequipa', 'colca', 'canyon']):
            count += 1
        elif destino_lower == 'uyuni' and any(word in titulo + " " + tipo for word in ['uyuni', 'salar', 'bolivia']):
            count += 1
    
    return count

# === Configuraciones por idioma actualizadas ===
LANGUAGE_CONFIGS = {
    'es': {
        'stopwords': {'de', 'a', 'el', 'la', 'los', 'las', 'un', 'una', 'y', 'o', 'pero', 'con', 'para', 'qué', 'quiero', 'tienes', 'hay', 'es'},
        'system_instruction': (
            "Eres un asistente de viajes amigable y experto de IncaLake. Tu tarea es responder al usuario en ESPAÑOL.\n"
            "IMPORTANTE: Analiza si la pregunta del usuario es GENERAL o ESPECÍFICA:\n\n"
            "- Si es GENERAL (como 'info sobre tours', 'qué tours tienen', 'turismo en Perú'), responde de manera CONSULTIVA:\n"
            "  * Saluda cordialmente\n"
            "  * Menciona que tienes tours en varios destinos\n"
            "  * Lista los destinos principales (Puno, Cusco, Arequipa, Uyuni, etc.)\n"
            "  * Pregunta por cuál destino le gustaría más información\n"
            "  * NO des detalles específicos de tours todavía\n\n"
            "- Si es ESPECÍFICA (menciona destinos, actividades concretas, fechas), usa la información de 'Relevant Tour Information' para dar detalles completos.\n"
            "- Cuando menciones un tour específico, SIEMPRE incluye su 'More Info URL'.\n"
            "- Para reservas, dirige al usuario a WhatsApp +51982769453.\n"
            "- Mantén un tono amigable y profesional siempre."
        ),
        'greeting': "¡Hola! Soy tu asistente de IncaLake. ¿En qué te puedo ayudar hoy?",
        'error_message': "Lo siento, ocurrió un error en el servidor. Por favor, intenta más tarde.",
        'no_tours_message': "No se encontró información de tours relevante para esta consulta.",
        'general_response_template': (
            "¡Perfecto! En IncaLake tenemos tours increíbles en varios destinos del sur de Perú y Bolivia:\n\n"
            "🏔️ **Puno**: Tours al Lago Titicaca, Islas Flotantes de los Uros, Taquile y Amantani\n"
            "🏛️ **Cusco**: Machu Picchu, Valle Sagrado y tours arqueológicos\n"
            "🌋 **Arequipa**: Cañón del Colca y tours de aventura\n"
            "🧂 **Uyuni**: Salar de Uyuni y tours por el desierto boliviano\n\n"
            "¿Te gustaría que te cuente más sobre tours en algún destino específico? 😊"
        )
    },
    'en': {
        'stopwords': {'the', 'a', 'an', 'and', 'or', 'but', 'with', 'for', 'what', 'want', 'have', 'is', 'are', 'to', 'of', 'in', 'on', 'at'},
        'system_instruction': (
            "You are a friendly and expert travel assistant for IncaLake. Your task is to answer the user in ENGLISH.\n"
            "IMPORTANT: Analyze if the user's question is GENERAL or SPECIFIC:\n\n"
            "- If it's GENERAL (like 'info about tours', 'what tours do you have', 'tourism in Peru'), respond CONSULTATIVELY:\n"
            "  * Greet cordially\n"
            "  * Mention that you have tours in several destinations\n"
            "  * List the main destinations (Puno, Cusco, Arequipa, Uyuni, etc.)\n"
            "  * Ask which destination they'd like more information about\n"
            "  * DON'T give specific tour details yet\n\n"
            "- If it's SPECIFIC (mentions destinations, concrete activities, dates), use the 'Relevant Tour Information' to give complete details.\n"
            "- When mentioning a specific tour, ALWAYS include its 'More Info URL'.\n"
            "- For reservations, refer to WhatsApp +51982769453.\n"
            "- Always maintain a friendly and professional tone."
        ),
        'greeting': "Hello! I'm your IncaLake assistant. How can I help you today?",
        'error_message': "Sorry, a server error occurred. Please try again later.",
        'no_tours_message': "No relevant tour information found for this query.",
        'general_response_template': (
            "Perfect! At IncaLake we have amazing tours in several destinations in southern Peru and Bolivia:\n\n"
            "🏔️ **Puno**: Lake Titicaca tours, Floating Islands of Uros, Taquile and Amantani\n"
            "🏛️ **Cusco**: Machu Picchu, Sacred Valley and archaeological tours\n"
            "🌋 **Arequipa**: Colca Canyon and adventure tours\n"
            "🧂 **Uyuni**: Uyuni Salt Flats and Bolivian desert tours\n\n"
            "Would you like me to tell you more about tours in any specific destination? 😊"
        )
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
    
    if source_language == 'en':
        print(f"🌐 Keywords ya en inglés: {keywords}")
        return keywords
    
    prompt = f"Translate the following Spanish travel keywords to English. Provide only the most relevant, single-word English equivalent for each. Return as a comma-separated list. Keywords: '{', '.join(keywords)}'"
    try:
        response = genai.GenerativeModel('gemini-1.5-flash').generate_content(prompt)
        english_keywords = [kw.strip() for kw in response.text.strip().lower().split(',')]
        print(f"🌐 Keywords traducidas (EN): {english_keywords}")
        return english_keywords
    except Exception as e:
        print(f"❌ Error en la traducción de keywords: {e}")
        return keywords

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
                score += 5 if keyword in tour.get("titulo_producto", "").lower() else 1
        
        if score > 0:
            score += (6 - tour.get("prioridad", 5))
            scored_tours.append((score, tour))
    
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

def construir_historial_gemini(historial_previo, instruccion_principal, contexto_detallado, pregunta_actual, language='es', intencion='specific'):
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
    
    # Construir prompt según la intención
    if intencion == 'general':
        # Para consultas generales, no necesitamos contexto detallado
        destinos = obtener_destinos_disponibles()
        prompt_actual = f"CONSULTA GENERAL DETECTADA. Destinos disponibles: {', '.join(destinos)}\n\nUser Question: {pregunta_actual}"
    else:
        # Para consultas específicas, incluir contexto detallado
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
        language = data.get('language', 'es')
        
        if language not in LANGUAGE_CONFIGS:
            language = 'es'
            
        print(f"🌍 Idioma detectado: {language}")
        print(f"💬 Pregunta: {pregunta}")

        if not pregunta:
            return jsonify({"error": "El mensaje no puede estar vacío."}), 400

        # 1. Obtener historial
        historial = historial_global.get(session_id, [])

        # 2. Detectar intención de la consulta
        intencion = detectar_intencion_consulta(pregunta, language)
        print(f"🎯 Intención detectada: {intencion}")

        # 3. Procesar según la intención
        if intencion == 'general':
            # Para consultas generales, no buscar tours específicos
            tours_relevantes = []
            contexto_detallado = ""
        else:
            # Para consultas específicas, buscar tours relevantes
            keywords = obtener_keywords_contextuales(historial, pregunta, language)
            keywords_en = traducir_keywords_a_ingles(keywords, language)
            tours_relevantes = buscar_tours_relevantes(keywords_en)
            contexto_detallado = formatear_contexto_detallado(tours_relevantes, language)
        
        # 4. Obtener configuración del idioma
        config = LANGUAGE_CONFIGS[language]
        
        # 5. Construir historial para Gemini
        historial_para_gemini = construir_historial_gemini(
            historial, 
            config['system_instruction'], 
            contexto_detallado, 
            pregunta, 
            language,
            intencion
        )

        def stream_response():
            respuesta_completa = ""
            try:
                response_stream = gemini_model.generate_content(
                    historial_para_gemini,
                    stream=True
                )
                
                for chunk in response_stream:
                    if chunk.text:
                        respuesta_completa += chunk.text
                        yield chunk.text
                        time.sleep(0.01)
                
                # Actualizar historial global
                current_historial = historial_global.get(session_id, [])
                current_historial.append({"role": "user", "parts": [pregunta]})
                current_historial.append({"role": "model", "parts": [respuesta_completa]})
                
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

# === Rutas adicionales ===

@app.route('/session/<session_id>', methods=['GET'])
def get_session_info(session_id):
    """Obtiene información de una sesión específica."""
    historial = historial_global.get(session_id, [])
    return jsonify({
        "session_id": session_id,
        "messages_count": len(historial),
        "last_activity": time.time() if historial else None
    })

@app.route('/session/<session_id>/clear', methods=['POST'])
def clear_session(session_id):
    """Limpia el historial de una sesión específica."""
    if session_id in historial_global:
        del historial_global[session_id]
        return jsonify({"message": f"Historial de sesión {session_id} limpiado."})
    return jsonify({"message": "Sesión no encontrada."}), 404

@app.route('/destinations', methods=['GET'])
def get_destinations():
    """Endpoint para obtener destinos disponibles."""
    destinos = obtener_destinos_disponibles()
    destinos_con_conteo = []
    
    for destino in destinos:
        count = contar_tours_por_destino(destino)
        destinos_con_conteo.append({
            "destination": destino,
            "tour_count": count
        })
    
    return jsonify({
        "destinations": destinos_con_conteo,
        "total_destinations": len(destinos)
    })

@app.route('/')
def index():
    return jsonify({
        "message": "API de IncaLake Chatbot funcionando",
        "version": "2.1",
        "supported_languages": list(LANGUAGE_CONFIGS.keys()),
        "features": [
            "Detección de intención consultiva",
            "Respuestas graduales según especificidad",
            "Soporte multiidioma",
            "Gestión de sesiones"
        ],
        "endpoints": {
            "chat": "/chat",
            "session_info": "/session/<session_id>",
            "clear_session": "/session/<session_id>/clear",
            "destinations": "/destinations"
        }
    })

@app.route('/health')
def health_check():
    """Endpoint de health check para monitoring."""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "tours_loaded": len(tours_data_loaded),
        "active_sessions": len(historial_global),
        "destinations_available": len(obtener_destinos_disponibles())
    })

if __name__ == '__main__':
    print("🚀 Iniciando IncaLake Chatbot API...")
    print(f"📚 Tours cargados: {len(tours_data_loaded)}")
    print(f"🌍 Idiomas soportados: {list(LANGUAGE_CONFIGS.keys())}")
    print(f"🎯 Destinos disponibles: {obtener_destinos_disponibles()}")
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv("PORT", 5000)))