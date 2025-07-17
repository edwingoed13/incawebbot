# 🤖 Inca Lake - Asistente de Viajes con IA

Este proyecto implementa un asistente de chat inteligente para la agencia de viajes "Inca Lake". Utiliza un backend en **Flask (Python)** y una integración con la **API de Google Gemini** para proporcionar respuestas conversacionales y dinámicas basadas en la información de tours de la agencia.

## ✨ Características Principales

- **Backend Robusto con Flask:** Un servidor web ligero y eficiente que maneja la lógica de la aplicación.
- **Inteligencia Artificial Conversacional:** Integración con el modelo `gemini-2.5-flash` de Google para generar respuestas fluidas, contextuales y útiles.
- **Carga de Contexto Dinámico:** El sistema carga información detallada de tours desde un archivo `tours_ingles.json`, permitiendo al bot responder preguntas específicas sobre destinos, precios, itinerarios y más.
- **Inyección de Contexto Inteligente:** El backend analiza la consulta del usuario para inyectar solo la información más relevante del tour en el prompt de la IA, optimizando la precisión de la respuesta y el consumo de tokens.
- **Frontend Interactivo:** Una interfaz de chat creada con **HTML, Tailwind CSS y JavaScript** que consume los datos del backend.
- **Streaming de Respuestas:** El frontend recibe y muestra las respuestas del bot en tiempo real, mejorando la experiencia del usuario.
- **Gestión de Sesiones:** Mantiene un historial de conversación por sesión de usuario (usando `localStorage`), lo que permite al bot recordar el contexto de interacciones anteriores.
- **Diseño Moderno:** Estilizado con **Tailwind CSS** para una apariencia limpia y responsiva.

## 📁 Estructura del Proyecto

```
/
├── app.py                  # Servidor principal de Flask, lógica del bot y conexión con la API de Gemini.
├── index_2.html            # Interfaz de usuario del chat (frontend).
├── tours_ingles.json       # Base de datos en formato JSON con la información de los tours.
├── requirements.txt        # Dependencias de Python para el backend.
└── README.md               # Este archivo.
```

### Descripción de Archivos

- **`app.py`**: Es el corazón de la aplicación.
  - Define el endpoint `/chat` que recibe las preguntas del usuario.
  - Se comunica con la API de Google Gemini.
  - Carga los datos de `tours_ingles.json` para contextualizar las respuestas.
  - Gestiona el historial de la conversación para mantener el contexto.
- **`index_2.html`**:
  - Contiene la estructura HTML, los estilos de Tailwind CSS y el código JavaScript para la interacción del usuario.
  - Envía las solicitudes al backend y maneja la recepción de respuestas en tiempo real (streaming).
  - Muestra la información de contacto de la agencia.
- **`tours_ingles.json`**:
  - Almacena todos los datos de los tours que la agencia ofrece. Cada tour tiene detalles como título, descripción, itinerario, precios, etc.
- **`requirements.txt`**:
  - Lista las librerías de Python necesarias para que el backend funcione correctamente.

## 🛠️ Tecnologías Utilizadas

- **Backend:**
  - ![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
  - ![Flask](https://img.shields.io/badge/Flask-000000?style=for-the-badge&logo=flask&logoColor=white)
  - ![Google Gemini](https://img.shields.io/badge/Google%20Gemini-4285F4?style=for-the-badge&logo=google&logoColor=white)
- **Frontend:**
  - ![HTML5](https://img.shields.io/badge/HTML5-E34F26?style=for-the-badge&logo=html5&logoColor=white)
  - ![Tailwind CSS](https://img.shields.io/badge/Tailwind_CSS-38B2AC?style=for-the-badge&logo=tailwind-css&logoColor=white)
  - ![JavaScript](https://img.shields.io/badge/JavaScript-F7DF1E?style=for-the-badge&logo=javascript&logoColor=black)
- **Base de Datos:**
  - ![JSON](https://img.shields.io/badge/JSON-000000?style=for-the-badge&logo=json&logoColor=white)

## 🚀 Instalación y Uso

Sigue estos pasos para ejecutar el proyecto en tu entorno local.

### Prerrequisitos

- Tener [Python 3.8+](https://www.python.org/downloads/) instalado.
- Tener una **API Key de Google Gemini**. Puedes obtenerla en [Google AI Studio](https://aistudio.google.com/app/apikey).

### Pasos

1.  **Clonar el repositorio (si aplica) o tener la carpeta del proyecto.**

2.  **Crear un entorno virtual (recomendado):**
    ```bash
    python -m venv venv
    ```
    Y activarlo:
    - En Windows: `.\venv\Scripts\activate`
    - En macOS/Linux: `source venv/bin/activate`

3.  **Instalar las dependencias de Python:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configurar las variables de entorno:**
    - Crea un archivo llamado `.env` en la raíz del proyecto.
    - Añade tu API Key de Gemini de la siguiente manera:
      ```
      GEMINI_API_KEY='TU_API_KEY_DE_GEMINI'
      ```
    - Reemplaza `TU_API_KEY_DE_GEMINI` con tu clave real.

5.  **Ejecutar el servidor Flask:**
    ```bash
    python app.py
    ```
    El servidor se iniciará en `http://localhost:5000`.

6.  **Abrir la interfaz de chat:**
    - Abre el archivo `index_2.html` directamente en tu navegador web (por ejemplo, Chrome, Firefox).
    - ¡Comienza a chatear con el asistente!
---
Powered by Edwin Flores 