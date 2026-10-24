#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py: Generador principal de Daily Digest.
Coordina la lectura de feeds, filtrado de 24h, deduplicación,
resúmenes mediante Gemini Flash (o fallback RSS), y compilación estática.
"""

import os
import re
import sys
import time
import random
import socket
import urllib.parse
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any

import yaml
import requests
import feedparser
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader

# Importar configuración y módulo de resumen
from config import (
    FEEDS_FILE,
    TEMPLATES_DIR,
    OUTPUT_DIR,
    ARCHIVE_DIR,
    CATEGORY_META,
    SUBTOPIC_LABELS,
    FEED_TIMEOUT,
    OG_TIMEOUT,
    HTTP_TIMEOUT,
    GEMINI_API_KEY,
    GEMINI_MODEL
)
from summarizer import (
    load_cache,
    summarize_category_batch,
    summarize_rss_fallback
)

# Timeout para sockets
socket.setdefaulttimeout(HTTP_TIMEOUT)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
HTTP_HEADERS = {"User-Agent": USER_AGENT}


# ==========================================
# 1. GENERADOR DE PLACEHOLDERS SVG
# ==========================================
def generate_svg_placeholder(category_id: str, subtopic: Optional[str] = None) -> str:
    """Genera imagen SVG vectorial con tema oscuro como respaldo."""
    meta = CATEGORY_META.get(category_id, {"title": "Noticias", "color": "#6366f1", "icon": "📰"})
    label = SUBTOPIC_LABELS.get(subtopic, meta.get("title", "Daily Digest"))
    color = meta.get("color", "#6366f1")

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="600" height="340" viewBox="0 0 600 340">
  <defs>
    <linearGradient id="grad" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#0f172a" />
      <stop offset="60%" stop-color="#1e293b" />
      <stop offset="100%" stop-color="{color}" stop-opacity="0.35" />
    </linearGradient>
    <radialGradient id="glow" cx="80%" cy="20%" r="50%">
      <stop offset="0%" stop-color="{color}" stop-opacity="0.25" />
      <stop offset="100%" stop-color="{color}" stop-opacity="0" />
    </radialGradient>
  </defs>
  <rect width="600" height="340" fill="url(#grad)" />
  <circle cx="480" cy="80" r="140" fill="url(#glow)" />
  <g transform="translate(40, 140)">
    <rect width="52" height="52" rx="12" fill="{color}" fill-opacity="0.2" stroke="{color}" stroke-opacity="0.5" stroke-width="1.5" />
    <text x="26" y="34" font-family="-apple-system, sans-serif" font-size="24" text-anchor="middle" fill="#ffffff">{meta.get('icon', '📰')}</text>
  </g>
  <text x="105" y="162" font-family="'Outfit', -apple-system, BlinkMacSystemFont, sans-serif" font-size="14" font-weight="700" fill="{color}" letter-spacing="1.5">{meta.get('title', 'DAILY DIGEST').upper()}</text>
  <text x="105" y="185" font-family="'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif" font-size="18" font-weight="600" fill="#f8fafc">{label}</text>
</svg>"""

    encoded = urllib.parse.quote(svg)
    return f"data:image/svg+xml;utf8,{encoded}"


# ==========================================
# 2. LIMPIEZA Y FECHAS
# ==========================================
def parse_entry_datetime(entry: Any) -> Optional[datetime]:
    """Extrae fecha de publicación en UTC."""
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        st = entry.get(key)
        if st:
            try:
                ts = time.mktime(st)
                return datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                pass

    for key in ("published", "updated", "pubDate", "date"):
        raw = entry.get(key)
        if raw:
            try:
                from dateutil import parser
                dt = parser.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except Exception:
                pass

    return None


def clean_url(url: str) -> str:
    """Limpia parámetros de rastreo de URLs."""
    if not url:
        return ""
    try:
        parsed = urllib.parse.urlparse(url)
        q = urllib.parse.parse_qs(parsed.query)
        filtered_q = {k: v for k, v in q.items() if not k.lower().startswith("utm_") and k.lower() not in ("ref", "fbclid", "igshid", "mc_cid")}
        new_query = urllib.parse.urlencode(filtered_q, doseq=True)
        return urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, ""))
    except Exception:
        return url.strip()


def normalize_title(title: str) -> str:
    """Normaliza texto del título para deduplicación."""
    cleaned = re.sub(r"[^\w\s]", "", title.lower())
    return " ".join(cleaned.split())


# ==========================================
# 3. IMÁGENES
# ==========================================
def extract_image_from_entry(entry: Any) -> Optional[str]:
    """Extrae imagen desde los campos estándar del RSS."""
    for m in entry.get("media_content", []):
        if isinstance(m, dict) and m.get("url"):
            return m["url"]

    for m in entry.get("media_thumbnail", []):
        if isinstance(m, dict) and m.get("url"):
            return m["url"]

    for enc in entry.get("enclosures", []):
        if isinstance(enc, dict):
            url = enc.get("href") or enc.get("url")
            enc_type = enc.get("type", "")
            if url and (enc_type.startswith("image/") or any(url.lower().endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp"))):
                return url

    html_sources = []
    if "content" in entry and isinstance(entry["content"], list):
        for c in entry["content"]:
            if isinstance(c, dict) and "value" in c:
                html_sources.append(c["value"])
    if "summary" in entry:
        html_sources.append(entry["summary"])
    if "description" in entry:
        html_sources.append(entry["description"])

    for html_txt in html_sources:
        if html_txt and "<img" in html_txt:
            try:
                soup = BeautifulSoup(html_txt, "html.parser")
                img = soup.find("img")
                if img and img.get("src") and img["src"].startswith("http"):
                    return img["src"]
            except Exception:
                pass

    return None


def fetch_og_image(url: str) -> Optional[str]:
    """Consulta la metaetiqueta og:image con timeout controlado."""
    if not url or not url.startswith("http"):
        return None
    try:
        resp = requests.get(url, headers=HTTP_HEADERS, timeout=OG_TIMEOUT, allow_redirects=True)
        if resp.status_code == 200 and "text/html" in resp.headers.get("Content-Type", ""):
            soup = BeautifulSoup(resp.text[:40000], "html.parser")
            og_img = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
            if og_img and og_img.get("content") and og_img["content"].strip().startswith("http"):
                return og_img["content"].strip()
            tw_img = soup.find("meta", attrs={"name": "twitter:image"}) or soup.find("meta", property="twitter:image")
            if tw_img and tw_img.get("content") and tw_img["content"].strip().startswith("http"):
                return tw_img["content"].strip()
    except Exception:
        pass
    return None


def resolve_item_images(articles: List[Dict[str, Any]]) -> None:
    """Resuelve imágenes para los artículos seleccionados."""
    for item in articles:
        if not item.get("image"):
            og_img = fetch_og_image(item["link"])
            item["image"] = og_img if og_img else item["fallback_image"]


# ==========================================
# 4. EXTRACCIÓN Y LÓGICA DE CATEGORÍAS
# ==========================================
def fetch_feed_items(feed_url: str, source_name: str, category_id: str, subtopic: Optional[str],
                     cutoff_time: datetime, seen_urls: set, seen_titles: set) -> List[Dict[str, Any]]:
    """Descarga y filtra notas de un feed RSS individual."""
    items = []
    try:
        resp = requests.get(feed_url, headers=HTTP_HEADERS, timeout=FEED_TIMEOUT)
        if resp.status_code != 200:
            return []
        feed = feedparser.parse(resp.content)
    except Exception:
        return []

    for entry in feed.entries:
        title = entry.get("title", "").strip()
        link = clean_url(entry.get("link", "").strip())

        if not title or not link:
            continue

        norm_title = normalize_title(title)
        if link in seen_urls or norm_title in seen_titles:
            continue

        pub_dt = parse_entry_datetime(entry)
        if pub_dt and pub_dt < cutoff_time:
            continue

        seen_urls.add(link)
        seen_titles.add(norm_title)

        rss_image = extract_image_from_entry(entry)
        fallback_placeholder = generate_svg_placeholder(category_id, subtopic)
        raw_summary = entry.get("summary") or entry.get("description") or ""

        if pub_dt:
            delta = datetime.now(timezone.utc) - pub_dt
            hours = int(delta.total_seconds() // 3600)
            if hours < 1:
                minutes = max(1, int(delta.total_seconds() // 60))
                time_label = f"Hace {minutes} min"
            elif hours < 24:
                time_label = f"Hace {hours} h"
            else:
                time_label = "Hace 1 día"
        else:
            time_label = "Hoy"

        items.append({
            "title": title,
            "link": link,
            "source": source_name,
            "category_id": category_id,
            "subtopic": subtopic,
            "subtopic_label": SUBTOPIC_LABELS.get(subtopic, subtopic.title() if subtopic else ""),
            "image": rss_image,
            "fallback_image": fallback_placeholder,
            "raw_summary": raw_summary,
            "summary": "",  # Se llenará en la etapa de resumen
            "summary_source": "pending",
            "is_top_story": False,
            "top_story_reason": None,
            "published_at": pub_dt,
            "published_label": time_label
        })

    return items


def mix_technology_subtopics(subtopics_dict: Dict[str, List[Dict[str, Any]]], max_consecutive: int = 2) -> List[Dict[str, Any]]:
    """Garantiza no más de 2 notas seguidas del mismo subtema en tecnología."""
    pools = {k: list(v) for k, v in subtopics_dict.items() if v}
    mixed = []
    last_subtopic = None
    consecutive_count = 0

    total_items = sum(len(v) for v in pools.values())
    for _ in range(total_items):
        valid_candidates = []
        for sub, items in pools.items():
            if not items:
                continue
            if sub == last_subtopic and consecutive_count >= max_consecutive:
                continue
            valid_candidates.append(sub)

        if not valid_candidates:
            valid_candidates = [sub for sub, items in pools.items() if items]
            if not valid_candidates:
                break

        different = [s for s in valid_candidates if s != last_subtopic]
        if different:
            chosen_sub = max(different, key=lambda s: len(pools[s]))
        else:
            chosen_sub = valid_candidates[0]

        item = pools[chosen_sub].pop(0)
        mixed.append(item)

        if chosen_sub == last_subtopic:
            consecutive_count += 1
        else:
            last_subtopic = chosen_sub
            consecutive_count = 1

    return mixed


def select_cultura_general(cultura_dict: Dict[str, List[Dict[str, Any]]], today_date_str: str) -> List[Dict[str, Any]]:
    """Elige 3 notas de 3 subtemas distintos cada día de forma determinista."""
    rng = random.Random(today_date_str)
    subtopics_with_news = [s for s, items in cultura_dict.items() if items]

    if not subtopics_with_news:
        return []

    if len(subtopics_with_news) <= 3:
        chosen_subtopics = subtopics_with_news
    else:
        chosen_subtopics = rng.sample(subtopics_with_news, 3)

    selected = []
    for sub in chosen_subtopics:
        items = cultura_dict[sub]
        picked_item = rng.choice(items)
        selected.append(picked_item)

    return selected


# ==========================================
# 5. RECONSTRUCCIÓN DEL ARCHIVO HISTÓRICO
# ==========================================
def rebuild_archive_index(archive_dir: Any, env: Environment) -> None:
    """Genera output/archive/index.html con la lista de días anteriores."""
    date_regex = re.compile(r"^(\d{4}-\d{2}-\d{2})\.html$")
    archives = []

    for fname in os.listdir(archive_dir):
        match = date_regex.match(fname)
        if match:
            date_str = match.group(1)
            filepath = os.path.join(archive_dir, fname)
            count = 0
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    content = f.read()
                    match_count = re.search(r"<strong>(\d+)</strong> notas seleccionadas", content)
                    if match_count:
                        count = int(match_count.group(1))
            except Exception:
                pass

            try:
                dt = datetime.strptime(date_str, "%Y-%m-%d")
                d_formatted = format_spanish_date(dt)
            except Exception:
                d_formatted = date_str

            archives.append({
                "filename": fname,
                "date_iso": date_str,
                "date_formatted": d_formatted,
                "total_articles": count
            })

    archives.sort(key=lambda x: x["date_iso"], reverse=True)

    template = env.get_template("archive_index.html")
    rendered = template.render(archives=archives)

    index_archive_path = os.path.join(archive_dir, "index.html")
    with open(index_archive_path, "w", encoding="utf-8") as f:
        f.write(rendered)
    print(f"[OK] Archivo histórico actualizado: {index_archive_path} ({len(archives)} ediciones)", flush=True)


def format_spanish_date(dt: datetime) -> str:
    """Formatea la fecha en español."""
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
    dia_sem = dias[dt.weekday()]
    mes = meses[dt.month - 1]
    return f"{dia_sem}, {dt.day} de {mes} de {dt.year}"


# ==========================================
# 6. EJECUCIÓN PRINCIPAL
# ==========================================
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print("=" * 65, flush=True)
    print("DAILY DIGEST - Resumen Diario de Noticias con Google Gemini Flash", flush=True)
    print("=" * 65, flush=True)

    if not os.path.exists(FEEDS_FILE):
        print(f"Error: No se encontró {FEEDS_FILE}", flush=True)
        sys.exit(1)

    with open(FEEDS_FILE, "r", encoding="utf-8") as f:
        config_feeds = yaml.safe_load(f)

    now_utc = datetime.now(timezone.utc)
    cutoff_time = now_utc - timedelta(hours=24)
    today_iso = now_utc.strftime("%Y-%m-%d")
    today_formatted = format_spanish_date(now_utc)

    print(f"Fecha: {today_formatted} ({today_iso})", flush=True)
    print(f"Filtro 24h: Noticias desde {cutoff_time.strftime('%Y-%m-%d %H:%M:%S')} UTC", flush=True)
    print(f"Configuración IA: Modelo '{GEMINI_MODEL}' | Clave presente: {bool(GEMINI_API_KEY)}\n", flush=True)

    seen_urls = set()
    seen_titles = set()

    processed_categories = {
        "ultimo_minuto": {"title": CATEGORY_META["ultimo_minuto"]["title"], "icon": CATEGORY_META["ultimo_minuto"]["icon"], "articles": []},
        "tecnologia": {"title": CATEGORY_META["tecnologia"]["title"], "icon": CATEGORY_META["tecnologia"]["icon"], "articles": []},
        "economia": {"title": CATEGORY_META["economia"]["title"], "icon": CATEGORY_META["economia"]["icon"], "articles": []},
        "sociedad": {"title": CATEGORY_META["sociedad"]["title"], "icon": CATEGORY_META["sociedad"]["icon"], "articles": []},
        "local": {"title": CATEGORY_META["local"]["title"], "icon": CATEGORY_META["local"]["icon"], "articles": []},
        "cultura_general": {"title": CATEGORY_META["cultura_general"]["title"], "icon": CATEGORY_META["cultura_general"]["icon"], "articles": []}
    }

    # 1. Extracción de feeds
    print("-> 1. Extrayendo feeds RSS...", flush=True)
    # Último Minuto
    for feed_info in config_feeds.get("ultimo_minuto", []):
        items = fetch_feed_items(feed_info["url"], feed_info["name"], "ultimo_minuto", None,
                                 cutoff_time, seen_urls, seen_titles)
        processed_categories["ultimo_minuto"]["articles"].extend(items)
    processed_categories["ultimo_minuto"]["articles"] = processed_categories["ultimo_minuto"]["articles"][:9]

    # Tecnología (subtemas)
    tech_config = config_feeds.get("tecnologia", {})
    tech_by_subtopic = {}
    for sub, feed_list in tech_config.items():
        tech_by_subtopic[sub] = []
        for feed_info in feed_list:
            items = fetch_feed_items(feed_info["url"], feed_info["name"], "tecnologia", sub,
                                     cutoff_time, seen_urls, seen_titles)
            tech_by_subtopic[sub].extend(items)
    mixed_tech = mix_technology_subtopics(tech_by_subtopic, max_consecutive=2)
    processed_categories["tecnologia"]["articles"] = mixed_tech[:12]

    # Economía
    for feed_info in config_feeds.get("economia", []):
        items = fetch_feed_items(feed_info["url"], feed_info["name"], "economia", None,
                                 cutoff_time, seen_urls, seen_titles)
        processed_categories["economia"]["articles"].extend(items)
    processed_categories["economia"]["articles"] = processed_categories["economia"]["articles"][:6]

    # Sociedad
    for feed_info in config_feeds.get("sociedad", []):
        items = fetch_feed_items(feed_info["url"], feed_info["name"], "sociedad", None,
                                 cutoff_time, seen_urls, seen_titles)
        processed_categories["sociedad"]["articles"].extend(items)
    processed_categories["sociedad"]["articles"] = processed_categories["sociedad"]["articles"][:6]

    # Local
    local_config = config_feeds.get("local", {})
    local_items = []
    for sub, feed_list in local_config.items():
        sub_items = []
        for feed_info in feed_list:
            items = fetch_feed_items(feed_info["url"], feed_info["name"], "local", sub,
                                     cutoff_time, seen_urls, seen_titles)
            sub_items.extend(items)
        local_items.extend(sub_items[:3])
    processed_categories["local"]["articles"] = local_items

    # Cultura General
    cultura_config = config_feeds.get("cultura_general", {})
    cultura_by_subtopic = {}
    for sub, feed_list in cultura_config.items():
        cultura_by_subtopic[sub] = []
        for feed_info in feed_list:
            items = fetch_feed_items(feed_info["url"], feed_info["name"], "cultura_general", sub,
                                     cutoff_time, seen_urls, seen_titles)
            cultura_by_subtopic[sub].extend(items)
    selected_cultura = select_cultura_general(cultura_by_subtopic, today_iso)
    processed_categories["cultura_general"]["articles"] = selected_cultura

    total_articles = sum(len(c["articles"]) for c in processed_categories.values())
    print(f"   Total de notas seleccionadas: {total_articles}\n", flush=True)

    # 2. Resúmenes por lote con Gemini (1 llamada por categoría + caché)
    print("-> 2. Generando resúmenes (Gemini Flash + Caché)...", flush=True)
    cache_data = load_cache()

    # Recopilar todos los titulares de las otras secciones para dárselos a Último Minuto
    all_other_titles = []
    for cat_key in ["tecnologia", "economia", "sociedad", "local", "cultura_general"]:
        for art in processed_categories[cat_key]["articles"]:
            all_other_titles.append({
                "categoria": CATEGORY_META.get(cat_key, {}).get("title", cat_key),
                "titulo": art["title"]
            })

    # Procesar Último Minuto (con selección de Noticia del Día)
    print("[Procesando categoría: ultimo_minuto]", flush=True)
    articles_um, top_story_info = summarize_category_batch(
        "ultimo_minuto",
        processed_categories["ultimo_minuto"]["articles"],
        cache_data,
        all_other_titles=all_other_titles
    )
    processed_categories["ultimo_minuto"]["articles"] = articles_um

    # Procesar las demás categorías en llamadas por lote separadas
    for cat_key in ["tecnologia", "economia", "sociedad", "local", "cultura_general"]:
        print(f"[Procesando categoría: {cat_key}]", flush=True)
        articles_cat, _ = summarize_category_batch(
            cat_key,
            processed_categories[cat_key]["articles"],
            cache_data
        )
        processed_categories[cat_key]["articles"] = articles_cat

    # Si se identificó una noticia más importante del día, marcarla en la lista
    if top_story_info and "titulo" in top_story_info:
        top_title = top_story_info["titulo"].strip().lower()
        matched = False
        for cat_data in processed_categories.values():
            for art in cat_data["articles"]:
                art_title = art["title"].strip().lower()
                if top_title in art_title or art_title in top_title:
                    art["is_top_story"] = True
                    art["top_story_reason"] = top_story_info.get("motivo")
                    matched = True
                    break
            if matched:
                break
        if not matched and processed_categories["ultimo_minuto"]["articles"]:
            # Si no hubo coincidencia exacta de título, destacar la primera de Último Minuto
            first_art = processed_categories["ultimo_minuto"]["articles"][0]
            first_art["is_top_story"] = True
            first_art["top_story_reason"] = top_story_info.get("motivo", "Nota de mayor trascendencia de la jornada.")

    # 3. Resolución de imágenes
    print("\n-> 3. Optimizando imágenes para notas seleccionadas...", flush=True)
    for cat_data in processed_categories.values():
        resolve_item_images(cat_data["articles"])

    # 4. Renderizado con Jinja2
    print("\n-> 4. Compilando páginas HTML estáticas...", flush=True)
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    digest_template = env.get_template("digest.html")

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(ARCHIVE_DIR, exist_ok=True)

    today_context = {
        "page_title": f"Resumen Diario · {today_formatted}",
        "date_formatted": today_formatted,
        "date_iso": today_iso,
        "total_articles": total_articles,
        "categories": processed_categories,
        "is_archive": False,
        "archive_url": "archive/index.html",
        "home_url": "index.html"
    }

    html_today = digest_template.render(**today_context)
    index_file = os.path.join(OUTPUT_DIR, "index.html")
    with open(index_file, "w", encoding="utf-8") as f:
        f.write(html_today)
    print(f"[OK] Resumen principal generado: {index_file}", flush=True)

    archive_context = dict(today_context)
    archive_context["is_archive"] = True
    archive_context["archive_url"] = "index.html"
    archive_context["home_url"] = "../index.html"
    archive_context["page_title"] = f"Archivo {today_iso} · {today_formatted}"

    html_archive = digest_template.render(**archive_context)
    archive_day_file = os.path.join(ARCHIVE_DIR, f"{today_iso}.html")
    with open(archive_day_file, "w", encoding="utf-8") as f:
        f.write(html_archive)
    print(f"[OK] Copia histórica guardada: {archive_day_file}", flush=True)

    rebuild_archive_index(ARCHIVE_DIR, env)
    print("\n[FIN] Digest completado con éxito.", flush=True)


if __name__ == "__main__":
    main()
