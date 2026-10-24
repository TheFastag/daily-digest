# -*- coding: utf-8 -*-
"""
config.py: Configuración centralizada para daily-digest.
Carga variables de entorno, rutas y configuración de Gemini.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Rutas base
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

FEEDS_FILE = BASE_DIR / "feeds.yaml"
TEMPLATES_DIR = BASE_DIR / "templates"
OUTPUT_DIR = BASE_DIR / "output"
ARCHIVE_DIR = OUTPUT_DIR / "archive"
CACHE_DIR = BASE_DIR / "cache"
CACHE_FILE = CACHE_DIR / "summaries_cache.json"

# Configuración de Google Gemini API
# Lee la clave de la variable de entorno GEMINI_API_KEY
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()

# Modelo Flash vigente del Free Tier de Google
# Opciones disponibles en el Free Tier: "gemini-3.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash").strip()

# Parámetros de resiliencia y límites del free tier
MAX_RETRIES = 1
RETRY_DELAY_SECONDS = 5.0
HTTP_TIMEOUT = 4.0
FEED_TIMEOUT = 3.5
OG_TIMEOUT = 1.8

# Metadatos estéticos por categoría
CATEGORY_META = {
    "ultimo_minuto": {
        "title": "Último Minuto",
        "icon": "⚡",
        "color": "#f43f5e",
        "badge": "En Vivo"
    },
    "tecnologia": {
        "title": "Tecnología",
        "icon": "💻",
        "color": "#06b6d4",
        "badge": "Tech"
    },
    "economia": {
        "title": "Economía y Finanzas",
        "icon": "📈",
        "color": "#10b981",
        "badge": "Economía"
    },
    "sociedad": {
        "title": "Sociedad y Actualidad",
        "icon": "🌍",
        "color": "#8b5cf6",
        "badge": "Sociedad"
    },
    "local": {
        "title": "Local (México, Quintana Roo y Riviera Maya)",
        "icon": "📍",
        "color": "#f59e0b",
        "badge": "Local"
    },
    "cultura_general": {
        "title": "Cultura y Saberes (3 Notas del Día)",
        "icon": "✨",
        "color": "#ec4899",
        "badge": "Cultura"
    }
}

SUBTOPIC_LABELS = {
    "ia": "Inteligencia Artificial",
    "hardware": "Hardware",
    "ciberseguridad": "Ciberseguridad",
    "programacion": "Programación",
    "gadgets": "Gadgets",
    "emergentes": "Innovación",
    "mexico": "México",
    "quintana_roo": "Quintana Roo",
    "playa_del_carmen": "Playa del Carmen",
    "politica": "Política",
    "musica": "Música",
    "arte": "Arte",
    "biologia": "Biología",
    "ciencia": "Ciencia",
    "historia": "Historia",
    "filosofia": "Filosofía"
}

