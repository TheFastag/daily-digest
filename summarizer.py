import sys
try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
# -*- coding: utf-8 -*-
"""
summarizer.py: Módulo de resumen para daily-digest.
Integra la API oficial de Google Gemini (google-genai) con procesamiento por lote
por categoría, soporte de caché en JSON y fallback a RSS.
"""

import os
import re
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    CACHE_DIR,
    CACHE_FILE,
    MAX_RETRIES,
    RETRY_DELAY_SECONDS,
)

# Variable para almacenar el cliente de Gemini una vez inicializado
_genai_client = None


def get_gemini_client():
    """Inicializa y retorna el cliente oficial de Google GenAI si la clave existe."""
    global _genai_client
    if _genai_client is not None:
        return _genai_client

    if not GEMINI_API_KEY:
        return None

    try:
        from google import genai
        _genai_client = genai.Client(api_key=GEMINI_API_KEY)
        return _genai_client
    except Exception as e:
        print(f"  [Error] No se pudo inicializar google-genai Client: {e}", flush=True)
        return None


# ==========================================
# 1. GESTIÓN DE CACHÉ
# ==========================================
def load_cache() -> Dict[str, Dict[str, Any]]:
    """Carga los resúmenes cacheados desde el archivo JSON."""
    if not CACHE_FILE.exists():
        return {}
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  [Aviso Caché] No se pudo leer el archivo de caché: {e}", flush=True)
        return {}


def save_cache(cache_data: Dict[str, Dict[str, Any]]) -> None:
    """Guarda los resúmenes en el archivo JSON de caché."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  [Aviso Caché] Error guardando caché: {e}", flush=True)


def get_cached_summary(url: str, cache_data: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """Retorna el resumen cacheado si existe."""
    entry = cache_data.get(url)
    if entry and isinstance(entry, dict) and entry.get("summary"):
        return entry["summary"]
    return None


def cache_summary(url: str, summary: str, source: str, cache_data: Dict[str, Dict[str, Any]]) -> None:
    """Registra un nuevo resumen en la estructura de caché."""
    if not url or not summary:
        return
    cache_data[url] = {
        "summary": summary,
        "source": source,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


# ==========================================
# 2. RESUMEN DE RESPALDO (FALLBACK RSS)
# ==========================================
def summarize_rss_fallback(raw_text: str, max_chars: int = 185) -> str:
    """
    Función de fallback que limpia y recorta el texto original del RSS
    cuando no hay API key o cuando Gemini falla/agota su cuota.
    """
    if not raw_text:
        return "Haz clic en 'Leer nota' para consultar la información completa de esta publicación."

    # Limpiar etiquetas HTML
    text = re.sub(r"<[^>]+>", " ", raw_text)
    # Normalizar espacios en blanco
    text = " ".join(text.split()).strip()

    if len(text) <= max_chars:
        return text

    # Truncar limpiamente sin cortar palabras
    truncated = text[:max_chars]
    last_space = truncated.rfind(" ")
    if last_space > 50:
        truncated = truncated[:last_space]

    return truncated.rstrip(".,;:- ") + "..."


# ==========================================
# 3. LLAMADAS POR LOTE A GEMINI
# ==========================================
def clean_json_text(text: str) -> str:
    """Elimina delimitadores markdown tipo ```json ... ``` si el modelo los incluye."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def call_gemini_batch(prompt: str) -> Optional[Dict[str, Any]]:
    """
    Realiza la llamada a Gemini usando google-genai con reintento automático y backoff.
    Solicita formato application/json.
    """
    client = get_gemini_client()
    if not client:
        return None

    from google.genai import types

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.2,
    )

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config
            )
            raw_text = response.text or ""
            cleaned = clean_json_text(raw_text)
            data = json.loads(cleaned)
            return data
        except Exception as e:
            if attempt < MAX_RETRIES:
                print(f"  [Reintento IA] Error con Gemini ({type(e).__name__}: {e}). Esperando {RETRY_DELAY_SECONDS}s...", flush=True)
                time.sleep(RETRY_DELAY_SECONDS)
            else:
                print(f"  [Fallo IA] Gemini no pudo responder tras reintento: {e}", flush=True)
                return None
    return None


def summarize_category_batch(
    category_id: str,
    articles: List[Dict[str, Any]],
    cache_data: Dict[str, Dict[str, Any]],
    all_other_titles: Optional[List[Dict[str, str]]] = None
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Procesa todas las notas de una categoría en UNA ÚNICA llamada a Gemini:
    - Primero verifica la caché.
    - Envía a Gemini únicamente las notas no cacheadas.
    - Para 'ultimo_minuto', además solicita la selección de la 'Noticia más importante del día'.
    - Si Gemini falla o no hay key, aplica el fallback RSS a las pendientes.
    - Retorna la lista de notas con sus resúmenes y los datos de la nota destacada (si aplica).
    """
    if not articles:
        return articles, None

    # 1. Separar notas cacheadas y pendientes
    pending_articles: List[Tuple[int, Dict[str, Any]]] = []
    cached_count = 0
    ai_count = 0
    fallback_count = 0

    for idx, item in enumerate(articles):
        cached = get_cached_summary(item["link"], cache_data)
        if cached:
            item["summary"] = cached
            item["summary_source"] = "cache"
            cached_count += 1
            print(f"  [Caché] '{item['title'][:45]}...'", flush=True)
        else:
            pending_articles.append((idx, item))

    top_story_data = None

    # Si hay notas pendientes o es 'ultimo_minuto' (para seleccionar la nota del día)
    needs_gemini = len(pending_articles) > 0 or (category_id == "ultimo_minuto" and all_other_titles)

    if needs_gemini:
        client = get_gemini_client()
        if not client:
            print(f"  [Aviso] GEMINI_API_KEY no configurada. Aplicando fallback RSS para {len(pending_articles)} notas en '{category_id}'.", flush=True)
            for _, item in pending_articles:
                item["summary"] = summarize_rss_fallback(item.get("raw_summary", ""))
                item["summary_source"] = "fallback"
                fallback_count += 1
                print(f"  [Fallback RSS] '{item['title'][:45]}...'", flush=True)
            return articles, None

        # Construir el prompt por lote
        news_payload = []
        for orig_idx, item in pending_articles:
            news_payload.append({
                "id": str(orig_idx),
                "titulo": item["title"],
                "texto_rss": item.get("raw_summary", "")[:500]
            })

        if category_id == "ultimo_minuto":
            # Incluir la selección de la noticia más importante del día
            system_instructions = (
                "Eres un editor periodístico jefe. Tienes dos responsabilidades:\n"
                "1. Para cada noticia en 'noticias_a_resumir', redacta un resumen conciso de exactamente 2 a 3 frases en español, "
                "claro, neutral y objetivo. No inventes hechos ni agregues datos que no estén en el texto provisto.\n"
                "2. Analiza todas las noticias del día (tanto las notas de Último Minuto como los titulares del resto de categorías) "
                "y selecciona cuál es la NOTICIA MÁS IMPORTANTE DEL DÍA a nivel global o nacional. Explica en 1 frase el motivo.\n"
                "Responde en formato JSON con la siguiente estructura exacta:\n"
                "{\n"
                '  "resumenes": [{"id": "0", "resumen": "..."}],\n'
                '  "noticia_mas_importante": {"titulo": "...", "categoria": "...", "motivo": "..."}\n'
                "}"
            )
            full_prompt = {
                "instrucciones": system_instructions,
                "noticias_a_resumir": news_payload,
                "titulares_otras_categorias": all_other_titles or []
            }
        else:
            system_instructions = (
                f"Eres un redactor periodístico profesional para la sección de {category_id.upper()}. "
                "Para cada una de las noticias en la lista, genera un resumen de 2 a 3 frases en español. "
                "El tono debe ser objetivo, informativo y neutral. No inventes datos que no aparezcan en el texto provisto.\n"
                "Responde estrictamente en formato JSON con la siguiente estructura:\n"
                "{\n"
                '  "resumenes": [{"id": "0", "resumen": "..."}]\n'
                "}"
            )
            full_prompt = {
                "instrucciones": system_instructions,
                "noticias_a_resumir": news_payload
            }

        print(f"  [IA - Gemini] Enviando {len(pending_articles)} notas de '{category_id}' a {GEMINI_MODEL}...", flush=True)
        resp_json = call_gemini_batch(json.dumps(full_prompt, ensure_ascii=False))

        if resp_json and isinstance(resp_json, dict):
            # Mapear los resúmenes devueltos
            returned_summaries = {}
            for entry in resp_json.get("resumenes", []):
                if isinstance(entry, dict) and "id" in entry and "resumen" in entry:
                    returned_summaries[str(entry["id"])] = entry["resumen"].strip()

            for orig_idx, item in pending_articles:
                key = str(orig_idx)
                if key in returned_summaries and len(returned_summaries[key]) > 20:
                    summary_text = returned_summaries[key]
                    item["summary"] = summary_text
                    item["summary_source"] = "ai"
                    cache_summary(item["link"], summary_text, "ai", cache_data)
                    ai_count += 1
                    print(f"  [IA - Éxito] '{item['title'][:45]}...'", flush=True)
                else:
                    # Si no vino esa ID específica, fallback
                    item["summary"] = summarize_rss_fallback(item.get("raw_summary", ""))
                    item["summary_source"] = "fallback"
                    fallback_count += 1
                    print(f"  [Fallback RSS (sin ID devuelta)] '{item['title'][:45]}...'", flush=True)

            if category_id == "ultimo_minuto" and "noticia_mas_importante" in resp_json:
                top_story_data = resp_json["noticia_mas_importante"]
                print(f"  [* Noticia del Día] {top_story_data.get('titulo')}: {top_story_data.get('motivo')}", flush=True)

            save_cache(cache_data)
        else:
            # Fallback en caso de que Gemini haya fallado
            print(f"  [Fallback RSS] Activando extractos locales para las {len(pending_articles)} notas de '{category_id}'.", flush=True)
            for _, item in pending_articles:
                item["summary"] = summarize_rss_fallback(item.get("raw_summary", ""))
                item["summary_source"] = "fallback"
                fallback_count += 1

    # Log resumen de la categoría
    total = len(articles)
    print(f"  -> Resumen '{category_id}': {total} notas (Caché: {cached_count}, Gemini IA: {ai_count}, Fallback: {fallback_count})\n", flush=True)

    return articles, top_story_data

