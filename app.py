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
# Permitir CORS para todas las rutas
CORS(app, resources={r"/*": {"origins": "*"}}) 

# --- Configuración de Gemini ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY no está configurada.")

genai.configure(api_key=GEMINI_API_KEY)

gemini_model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
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

# === Gestión de Sesiones basada en Archivos ===
# Obtenemos la ruta absoluta del directorio donde se encuentra app.py
basedir = os.path.abspath(os.path.dirname(__file__))
# Creamos la ruta completa y segura para la carpeta de sesiones
SESSIONS_DIR = os.path.join(basedir, "chat_sessions")

# Verificar que la carpeta de sesiones existe y tiene permisos
if not os.path.exists(SESSIONS_DIR):
    try:
        os.makedirs(SESSIONS_DIR)
        print(f"✅ Directorio de sesiones creado en: {SESSIONS_DIR}")
        # Dar permisos (Linux/Mac)
        print(f"Sistema operativo: {os.name}")
        if os.name != 'nt':  # Linux/Mac
            os.chmod(SESSIONS_DIR, 0o755)  # Cambiar a 755 en lugar de 777
        print("Permisos establecidos correctamente")
    except Exception as e:
        print(f"❌ Error crítico al crear directorio de sesiones: {e}")
        raise

# Verificar permisos de escritura
try:
    test_file = os.path.join(SESSIONS_DIR, 'test_permissions.txt')
    with open(test_file, 'w') as f:
        f.write('test')
    os.remove(test_file)
    print("✅ Permisos de escritura verificados correctamente")
except Exception as e:
    print(f"❌ Error de permisos en {SESSIONS_DIR}: {e}")
    raise

def load_session_history(session_id):
    """Carga el historial de un archivo JSON."""
    # Sanitizar el session_id para evitar problemas de path traversal
    safe_session_id = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
    filepath = os.path.join(SESSIONS_DIR, f"{safe_session_id}.json")
    
    print(f"🔍 Intentando cargar sesión desde: {filepath}")
    
    if os.path.exists(filepath):
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                print(f"✅ Sesión cargada exitosamente: {len(data)} mensajes")
                return data
        except (json.JSONDecodeError, IOError) as e:
            print(f"⚠️ Error al leer archivo de sesión {session_id}: {e}")
            return []
    else:
        print(f"ℹ️ Archivo de sesión no encontrado: {filepath}")
        return []

def save_session_history(session_id, history):
    """Guarda el historial en un archivo JSON."""
    # Sanitizar el session_id para evitar problemas de path traversal
    safe_session_id = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
    filepath = os.path.join(SESSIONS_DIR, f"{safe_session_id}.json")
    
    print(f"💾 Intentando guardar sesión en: {filepath}")
    print(f"📝 Contenido a guardar: {json.dumps(history, indent=2)}")
    
        # AGREGAR ESTA VERIFICACIÓN:
    try:
        # Crear directorio si no existe
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        print(f"✅ Sesión guardada exitosamente: {filepath}")
        return True
    except IOError as e:
        print(f"❌ Error grave al guardar sesión {session_id}: {e}")
        print(f"Ruta absoluta intentada: {os.path.abspath(filepath)}")
        print(f"Directorio padre existe: {os.path.exists(os.path.dirname(filepath))}")
        print(f"Permisos de escritura: {os.access(os.path.dirname(filepath), os.W_OK)}")
        return False

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
MAX_HISTORY_TURNS = 5

# === Nuevas funciones para detección de intención ===
def detectar_intencion_consulta(pregunta, language='es'):
    """Detecta intención priorizando Puno/Titicaca como especialidad."""
    pregunta_lower = pregunta.lower()
    
    # Detectar mención de Puno/Titicaca (alta prioridad)
    puno_keywords = ['puno', 'titicaca', 'uros', 'taquile', 'amantani', 'floating islands', 'islas flotantes']
    menciona_puno = any(keyword in pregunta_lower for keyword in puno_keywords)
    
    # Patrones para preguntas muy generales
    patrones_generales = {
        'es': [
            r'\b(info|información)\s+(sobre\s+)?tours?\b',
            r'\btours?\s+(disponibles?|que\s+tienen?)\b',
            r'\bqué\s+tours?\s+(hay|tienen|ofrecen)\b',
            r'\bque\s+actividades?\s+(hay|tienen|ofrecen)\b',
            r'\bque\s+hacer\s+en\s+(perú|peru)\b',
            r'\bturismo\s+en\s+(perú|peru)\b',
            r'^(hola|hello|buenos?\s+días?|buenas?\s+tardes?)',
            r'\bpaquetes?\s+turísticos?\b',
            r'\brecomendaciones?\b'
        ],
        'en': [
            r'\binfo\s+(about\s+)?tours?\b',
            r'\btours?\s+(available|you\s+have)\b',
            r'\bwhat\s+tours?\s+(do\s+you\s+have|are\s+available)\b',
            r'\bwhat\s+activities?\s+(do\s+you\s+have|are\s+available)\b',
            r'\bwhat\s+to\s+do\s+in\s+peru\b',
            r'\btourism\s+in\s+peru\b',
            r'^(hi|hello|good\s+morning|good\s+afternoon)',
            r'\btravel\s+packages?\b',
            r'\brecommendations?\b'
        ]
    }
    
    if menciona_puno:
        return 'specific_puno'
    
    for patron in patrones_generales.get(language, patrones_generales['es']):
        if re.search(patron, pregunta_lower):
            return 'general'
    
    return 'specific'

def obtener_destinos_disponibles():
    """Extrae los destinos únicos de los tours disponibles."""
    destinos = set()
    for tour in tours_data_loaded:
        titulo = tour.get("titulo_producto", "").lower()
        tipo = tour.get("tipo_servicio", "").lower()
        
        if any(word in titulo + " " + tipo for word in ['puno', 'titicaca', 'uros', 'taquile', 'amantani']):
            destinos.add('Puno')
        if any(word in titulo + " " + tipo for word in ['cusco', 'machu picchu', 'sacred valley']):
            destinos.add('Cusco')
        if any(word in titulo + " " + tipo for word in ['arequipa', 'colca', 'canyon']):
            destinos.add('Arequipa')
        if any(word in titulo + " " + tipo for word in ['uyuni', 'salar', 'bolivia']):
            destinos.add('Uyuni')
    
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
            "Eres un asistente de viajes especializado de IncaLake, una agencia peruana experta en Puno y Lago Titicaca. 🏔️ Utiliza emojis para hacer la conversación más amena.\n\n"
            "🎯 ESPECIALIZACIÓN DE INCALAKE:\n"
            "1. DESTINO PRINCIPAL: Puno y Lago Titicaca (nuestra especialidad) 🌊\n"
            "2. Destinos secundarios: Bolivia, Arequipa, Cusco\n"
            "3. Siempre prioriza tours con 'prioridad' más baja (1 = máxima prioridad, 5 = mínima)\n"
            "4. Para experiencias auténticas, sugiere homestays o tours de 2d1n\n\n"
            "📝 FLUJO DE CONVERSACIÓN:\n"
            "- Los datos de contacto ya fueron recolectados previamente ✅\n"
            "- Para consultas GENERALES, pregunta: '¿Para qué fecha planeas viajar y cuántas personas van?' 🗓️👥\n"
            "- Para consultas ESPECÍFICAS, usa 'Relevant Tour Information' y luego consulta fecha/personas si es necesario\n"
            "- SIEMPRE recomienda Puno/Titicaca como primera opción cuando sea relevante\n\n"
            "🌊 INFORMACIÓN CLAVE DE PUNO:\n"
            "- Lago Titicaca: 3,812 msnm - Recomendamos 1 día de aclimatación en Puno\n"
            "- Menciona nuestras islas especializadas: Uros, Taquile, Amantani\n"
            "- Destaca experiencias únicas como homestays con familias locales\n\n"
            "💰 PRESENTACIÓN DE TOURS:\n"
            "- SIEMPRE incluye URL clickeable: [Ver más información](URL_COMPLETA)\n"
            "- Consulta 'Prices (per person)' para rangos exactos\n"
            "- Máximo 3 párrafos, sé conciso y directo\n"
            "- Formato: título, descripción breve, precios, URL clickeable\n\n"
            "🚀 PROCESO DE RESERVA:\n"
            "Para reservar, comparte la URL clickeable e indica:\n"
            "1️⃣ Seleccionar fecha del tour\n"
            "2️⃣ Elegir hora de inicio\n"
            "3️⃣ Indicar número de personas\n"
            "4️⃣ Presionar 'Comprar' y completar pago\n"
            "⚠️ Si hay algún percance o la opción 'Comprar' no funciona, contactar WhatsApp +51982769453\n\n"
            "❓ CONSULTAS ESPECIALES:\n"
            "Para reservas existentes, documentos sensibles o consultas complejas:\n"
            "'Para este tipo de consulta tan específica, uno de mis compañeros humanos te ayudará. En breve se pondrán en contacto contigo. Si prefieres, puedes escribirnos directamente a nuestro WhatsApp +51982769453 para una atención inmediata.' 📞\n\n"
            "🌐 Para recomendaciones generales, usa información del blog incalake.com/blog\n"
            "⚠️ NUNCA redirijas a otras agencias de viajes"
        ),
        'greeting': "¡Hola! 👋 Soy tu asistente especializado de IncaLake. ¿En qué aventura por Puno y el Lago Titicaca te puedo ayudar hoy? 🌊✨",
        'error_message': "Lo siento, ocurrió un error en el servidor. Por favor, intenta más tarde o contáctanos al +51982769453 😔",
        'no_tours_message': "No encontré información específica para esa consulta, pero puedo ayudarte con nuestros tours en Puno y Lago Titicaca 🌊",
        'general_response_template': (
            "¡Perfecto! 🎉 Como especialistas en Puno y Lago Titicaca, tenemos las mejores experiencias:\n\n"
            "🌊 **PUNO - LAGO TITICACA** (Nuestra especialidad):\n"
            "• Islas Flotantes de los Uros - Experiencia única en totora 🛶\n"
            "• Isla Taquile - Cultura viva y textilería ancestral 🧵\n"
            "• Isla Amantani - Homestays auténticos con familias locales 🏠\n"
            "• Tours de 2d1n para experiencias completas\n"
            "*Altitud: 3,812 msnm - Recomendamos 1 día de aclimatación*\n\n"
            "🌟 **Otros destinos disponibles**:\n"
            "🧂 Bolivia: Salar de Uyuni | 🌋 Arequipa: Cañón del Colca | 🏛️ Cusco: Machu Picchu\n\n"
            "Para recomendarte la experiencia perfecta: **¿Para qué fecha planeas viajar y cuántas personas van?** 📅👥"
        ),
        'puno_priority_message': "🌊 Como especialistas en Puno y Lago Titicaca, te recomiendo especialmente nuestros tours a las islas. ¿Te interesan las experiencias en Uros, Taquile o Amantani?"
    },
    'en': {
        'stopwords': {'the', 'a', 'an', 'and', 'or', 'but', 'with', 'for', 'what', 'want', 'have', 'is', 'are', 'to', 'of', 'in', 'on', 'at'},
        'system_instruction': (
            "You are a specialized travel assistant for IncaLake, a Peruvian agency expert in Puno and Lake Titicaca. 🏔️ Use emojis to make conversations more enjoyable.\n\n"
            "🎯 INCALAKE SPECIALIZATION:\n"
            "1. MAIN DESTINATION: Puno and Lake Titicaca (our specialty) 🌊\n"
            "2. Secondary destinations: Bolivia, Arequipa, Cusco\n"
            "3. Always prioritize tours with lower 'priority' numbers (1 = highest priority, 5 = lowest)\n"
            "4. For authentic experiences, suggest homestays or 2d1n tours\n\n"
            "📝 CONVERSATION FLOW:\n"
            "- Contact information was already collected previously ✅\n"
            "- For GENERAL queries, ask: 'What date are you planning to travel and how many people are going?' 🗓️👥\n"
            "- For SPECIFIC queries, use 'Relevant Tour Information' then ask for date/people if needed\n"
            "- ALWAYS recommend Puno/Titicaca as first option when relevant\n\n"
            "🌊 KEY PUNO INFORMATION:\n"
            "- Lake Titicaca: 3,812 masl - We recommend 1 day acclimatization in Puno\n"
            "- Mention our specialized islands: Uros, Taquile, Amantani\n"
            "- Highlight unique experiences like homestays with local families\n\n"
            "💰 TOUR PRESENTATION:\n"
            "- ALWAYS include clickable URL: [More information](COMPLETE_URL)\n"
            "- Check 'Prices (per person)' for exact ranges\n"
            "- Maximum 3 paragraphs, be concise and direct\n"
            "- Format: title, brief description, prices, clickable URL\n\n"
            "🚀 BOOKING PROCESS:\n"
            "To book, share clickable URL and indicate:\n"
            "1️⃣ Select tour date\n"
            "2️⃣ Choose start time\n"
            "3️⃣ Indicate number of people\n"
            "4️⃣ Press 'Buy' and complete payment\n"
            "⚠️ If there's any issue or 'Buy' option doesn't work, contact WhatsApp +51982769453\n\n"
            "❓ SPECIAL QUERIES:\n"
            "For existing bookings, sensitive documents or complex queries:\n"
            "'For this specific type of query, one of my human colleagues will help you. They will contact you shortly. If you prefer, you can write directly to our WhatsApp +51982769453 for immediate assistance.' 📞\n\n"
            "🌐 For general recommendations, use information from incalake.com/blog\n"
            "⚠️ NEVER redirect to other travel agencies"
        ),
        'greeting': "Hello! 👋 I'm your specialized IncaLake assistant. What Puno and Lake Titicaca adventure can I help you with today? 🌊✨",
        'error_message': "Sorry, a server error occurred. Please try again later or contact us at +51982769453 😔",
        'no_tours_message': "I couldn't find specific information for that query, but I can help you with our Puno and Lake Titicaca tours 🌊",
        'general_response_template': (
            "Perfect! 🎉 As specialists in Puno and Lake Titicaca, we have the best experiences:\n\n"
            "🌊 **PUNO - LAKE TITICACA** (Our specialty):\n"
            "• Floating Islands of Uros - Unique totora reed experience 🛶\n"
            "• Taquile Island - Living culture and ancestral textiles 🧵\n"
            "• Amantani Island - Authentic homestays with local families 🏠\n"
            "• 2d1n tours for complete experiences\n"
            "*Altitude: 3,812 masl - We recommend 1 day acclimatization*\n\n"
            "🌟 **Other available destinations**:\n"
            "🧂 Bolivia: Uyuni Salt Flats | 🌋 Arequipa: Colca Canyon | 🏛️ Cusco: Machu Picchu\n\n"
            "To recommend the perfect experience: **What date are you planning to travel and how many people are going?** 📅👥"
        ),
        'puno_priority_message': "🌊 As specialists in Puno and Lake Titicaca, I especially recommend our island tours. Are you interested in experiences at Uros, Taquile or Amantani?"
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

def buscar_tours_relevantes(keywords_en, intencion='specific'):
    """Busca tours priorizando Puno/Titicaca según la especialización."""
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
        
        puno_bonus = 0
        if any(keyword in texto_busqueda for keyword in ['puno', 'titicaca', 'uros', 'taquile', 'amantani']):
            puno_bonus = 10 
        
        for keyword in keywords_en:
            if keyword in texto_busqueda:
                score += 5 if keyword in tour.get("titulo_producto", "").lower() else 1
        
        if score > 0 or puno_bonus > 0:
            score += puno_bonus
            score += (6 - tour.get("prioridad", 5))
            scored_tours.append((score, tour))
    
    scored_tours.sort(key=lambda x: x[0], reverse=True)
    
    if intencion == 'specific_puno':
        puno_tours = [tour for score, tour in scored_tours if score >= 10] 
        return puno_tours[:3] if puno_tours else [tour for score, tour in scored_tours[:2]]
    
    return [tour for score, tour in scored_tours[:3]]

def formatear_contexto_detallado(tours, language='es'):
    """Formatea tours con URLs clickeables y prioridad visible."""
    if not tours: 
        return LANGUAGE_CONFIGS[language]['no_tours_message']
    
    resumen_partes = ["--- Relevant Tour Information ---"]
    for tour in tours:
        titulo = tour.get("titulo_producto", "No title")
        descripcion = tour.get("descripcion_tab", "No description")
        itinerario = tour.get("itinerario_ta", "No itinerary provided.")
        url = tour.get("url_servicio", "")
        prioridad = tour.get("prioridad", 5)
        
        precios_formateados = "Price on request."
        try:
            precios = json.loads(tour.get("precios_rango", "{}"))
            if precios and all(k in precios for k in ["desde", "hasta", "precio"]):
                price_entries = [
                    f"For {d}-{h} people: ${p} USD" 
                    for d, h, p in zip(precios["desde"], precios["hasta"], precios["precio"])
                ]
                precios_formateados = " | ".join(price_entries)
        except (json.JSONDecodeError, TypeError):
            pass
        
        es_puno = any(keyword in titulo.lower() + descripcion.lower() for keyword in ['puno', 'titicaca', 'uros', 'taquile', 'amantani'])
        especialidad_nota = " ⭐ (NUESTRA ESPECIALIDAD)" if es_puno else ""
        
        resumen_partes.append(
            f"\n🎯 Tour: {titulo}{especialidad_nota}\n"
            f"Priority: {prioridad}/5 (1=highest priority)\n"
            f"Description: {descripcion}\n"
            f"Brief Itinerary: {itinerario[:150]}{'...' if len(itinerario) > 150 else ''}\n"
            f"Prices per person: {precios_formateados}\n"
            f"Booking URL: {url}\n"
            f"IMPORTANT: Make URL clickable as: [Ver más información]({url}) (Spanish) or [More information]({url}) (English)"
        )
    
    return "\n".join(resumen_partes)

def construir_historial_gemini(historial_previo, instruccion_principal, contexto_detallado, pregunta_actual, language='es', intencion='specific'):
    """Construye historial optimizado para especialización en Puno."""
    historial_para_gemini = []
    
    historial_para_gemini.append({
        "role": "user", 
        "parts": [instruccion_principal]
    })
    
    es_primera_interaccion = len(historial_previo) == 0
    
    if es_primera_interaccion:
        historial_para_gemini.append({
            "role": "model", 
            "parts": [LANGUAGE_CONFIGS[language]['greeting']]
        })
    else:
        historial_para_gemini.append({
            "role": "model", 
            "parts": ["¡Hola de nuevo! ¿En qué más te puedo ayudar? 😊" if language == 'es' else "Hello again! How else can I help you? 😊"]
        })
    
    historial_para_gemini.extend(historial_previo)
    
    if intencion == 'general' and es_primera_interaccion:
        destinos = obtener_destinos_disponibles()
        prompt_actual = f"CONSULTA GENERAL - PRIMERA INTERACCIÓN. Especialidad: Puno/Titicaca. Otros destinos: {', '.join(destinos)}. Necesita consultar fecha y número de personas.\n\nUser Question: {pregunta_actual}"
    elif intencion == 'specific_puno':
        prompt_actual = f"CONSULTA ESPECÍFICA SOBRE PUNO/TITICACA (nuestra especialidad) 🌊:\n{contexto_detallado}\n\nRecuerda mencionar nuestra experiencia especializada en esta región.\n\nUser Question: {pregunta_actual}"
    elif intencion == 'specific':
        prompt_actual = f"{contexto_detallado}\n\nSi es relevante, menciona también nuestros tours especialidad en Puno/Titicaca.\n\nUser Question: {pregunta_actual}"
    else:
        prompt_actual = f"Consulta general. Recuerda que somos especialistas en Puno/Titicaca. Necesita fecha y número de personas.\n\nUser Question: {pregunta_actual}"
    
    historial_para_gemini.append({
        "role": "user", 
        "parts": [prompt_actual]
    })
    
    return historial_para_gemini

# === Ruta Principal del Chat ===
# === Ruta Principal del Chat CORREGIDA ===
@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
            
        pregunta = data.get('message', '').strip()
        session_id = data.get('session_id', 'default_session')
        language = data.get('language', 'es')
        
        if language not in LANGUAGE_CONFIGS:
            language = 'es'
            
        print(f"\n--- Nueva Petición ---")
        print(f"ID de Sesión: {session_id}")
        print(f"Idioma: {language}")
        print(f"Pregunta: {pregunta}")

        if not pregunta:
            return jsonify({"error": "El mensaje no puede estar vacío."}), 400

        # MOVER ESTA LÍNEA ANTES DE LA FUNCIÓN stream_response()
        historial = load_session_history(session_id)
        intencion = detectar_intencion_consulta(pregunta, language)
        print(f"Intención Detectada: {intencion}")

        contexto_detallado = ""
        if intencion != 'general':
            keywords = obtener_keywords_contextuales(historial, pregunta, language)
            keywords_en = traducir_keywords_a_ingles(keywords, language)
            tours_relevantes = buscar_tours_relevantes(keywords_en)
            contexto_detallado = formatear_contexto_detallado(tours_relevantes, language)

        config = LANGUAGE_CONFIGS[language]
        historial_para_gemini = construir_historial_gemini(
            historial, config['system_instruction'], contexto_detallado, pregunta, language, intencion
        )

        def stream_response():
            # USAR nonlocal PARA ACCEDER A LA VARIABLE DEL SCOPE EXTERIOR
            nonlocal historial
            respuesta_completa = ""
            try:
                response_stream = gemini_model.generate_content(
                    historial_para_gemini, stream=True
                )
                
                for chunk in response_stream:
                    if chunk.text:
                        respuesta_completa += chunk.text
                        yield chunk.text
                        time.sleep(0.01)
                
                # Actualizar y guardar historial en archivo
                historial.append({"role": "user", "parts": [pregunta]})
                historial.append({"role": "model", "parts": [respuesta_completa]})
                
                if len(historial) > MAX_HISTORY_TURNS * 2:
                    historial = historial[-(MAX_HISTORY_TURNS * 2):]
                
                save_session_history(session_id, historial)
                print(f"✅ Historial guardado para sesión {session_id}")

            except Exception as e:
                print(f"❌ Error al generar respuesta de Gemini: {e}")
                yield config['error_message']

        return Response(stream_response(), mimetype='text/event-stream')
    
    except Exception as e:
        print(f"❌ Error general en /chat: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500

# === Rutas Adicionales ===
@app.route('/session/<session_id>/history', methods=['GET'])
def get_session_history(session_id):
    """Obtiene el historial de chat de una sesión desde su archivo."""
    historial = load_session_history(session_id)
    
    return jsonify({
        "session_id": session_id,
        "historial": historial if historial else [],
        "message": "Historial cargado exitosamente" if historial else "Nueva sesión sin historial previo"
    })

@app.route('/session/<session_id>/clear', methods=['POST'])
def clear_session(session_id):
    """Limpia el historial de una sesión eliminando su archivo."""
    safe_session_id = re.sub(r'[^a-zA-Z0-9_-]', '', session_id)
    filepath = os.path.join(SESSIONS_DIR, f"{safe_session_id}.json")
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            print(f"🗑️ Historial de sesión {session_id} limpiado.")
            return jsonify({"message": f"Historial de sesión {session_id} limpiado."})
        except OSError as e:
            print(f"❌ Error limpiando sesión {session_id}: {e}")
            return jsonify({"error": "No se pudo limpiar la sesión"}), 500
    return jsonify({"message": "Sesión no encontrada."}), 404

@app.route('/destinations', methods=['GET'])
def get_destinations():
    """Endpoint para obtener destinos disponibles."""
    destinos = obtener_destinos_disponibles()
    destinos_con_conteo = [
        {"destination": destino, "tour_count": contar_tours_por_destino(destino)}
        for destino in destinos
    ]
    return jsonify({
        "destinations": destinos_con_conteo,
        "total_destinations": len(destinos)
    })

@app.route('/')
def index():
    return jsonify({
        "message": "API de IncaLake Chatbot funcionando",
        "version": "2.2-persistent",
        "active_sessions_files": len(os.listdir(SESSIONS_DIR)),
    })

@app.route('/health')
def health_check():
    """Endpoint de health check para monitoring."""
    return jsonify({
        "status": "healthy",
        "timestamp": time.time(),
        "tours_loaded": len(tours_data_loaded),
        "active_sessions_files": len(os.listdir(SESSIONS_DIR)),
    })

if __name__ == '__main__':
    print("🚀 Iniciando IncaLake Chatbot API...")
    print(f"📚 Tours cargados: {len(tours_data_loaded)}")
    print(f"🌍 Idiomas soportados: {list(LANGUAGE_CONFIGS.keys())}")
    print(f"🎯 Destinos disponibles: {obtener_destinos_disponibles()}")
    print(f"📂 Directorio de sesiones: '{SESSIONS_DIR}'")
    print(f"📂 Directorio de trabajo: {os.getcwd()}")
    print(f"📁 Directorio de sesiones: {SESSIONS_DIR}")
    print(f"📁 Directorio existe: {os.path.exists(SESSIONS_DIR)}")
    print(f"📁 Permisos de escritura: {os.access(SESSIONS_DIR, os.W_OK) if os.path.exists(SESSIONS_DIR) else 'N/A'}")
    app.run(debug=True, host='0.0.0.0', port=int(os.getenv("PORT", 5000)))