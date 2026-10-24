#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
notify.py: Envío de notificaciones push de Daily Digest mediante ntfy.sh.
Lee las variables de entorno NTFY_TOPIC y SITE_URL sin imprimirlas en logs,
usa el formato JSON oficial de ntfy y maneja reintentos y alertas de error.
"""

import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv

# Reconfigurar salida para UTF-8 seguro
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

INDEX_HTML = BASE_DIR / "output" / "index.html"
NTFY_API_URL = "https://ntfy.sh"
DEFAULT_SITE_URL = "https://thefastag.github.io/daily-digest/"
MAX_RETRIES = 1
RETRY_DELAY = 3.0


def mask_secret(value: str) -> str:
    """Oculta el secreto mostrando solo los primeros caracteres para auditoría."""
    if not value:
        return "[NO CONFIGURADO]"
    if len(value) <= 4:
        return "****"
    return value[:3] + "*" * (len(value) - 3)


def extract_digest_summary() -> Tuple[bool, str, str]:
    """
    Lee output/index.html y extrae la fecha, la noticia de último minuto
    y los 4-5 titulares más relevantes de las demás secciones.
    """
    if not INDEX_HTML.exists():
        return False, "", ""

    try:
        with open(INDEX_HTML, "r", encoding="utf-8") as f:
            soup = BeautifulSoup(f.read(), "html.parser")

        # 1. Extraer fecha
        date_el = soup.find("span", class_="date-badge")
        date_str = date_el.text.strip() if date_el else ""

        # 2. Extraer titulares
        lines = []

        # Buscar si hay una noticia destacada del día
        featured_card = soup.find("article", class_="card-featured-day")
        featured_title = ""
        if featured_card:
            t_el = featured_card.find("h3", class_="card-title")
            if t_el:
                featured_title = t_el.text.strip()
                lines.append(f"⭐ Destacada: {featured_title[:80]}")

        # Secciones y sus etiquetas
        sections = [
            ("cat-ultimo_minuto", "⚡ Último Minuto"),
            ("cat-tecnologia", "💻 Tecnología"),
            ("cat-economia", "📈 Economía"),
            ("cat-sociedad", "🌍 Sociedad"),
            ("cat-local", "📍 Local"),
            ("cat-cultura_general", "✨ Cultura"),
        ]

        for sec_id, label in sections:
            sec = soup.find("section", id=sec_id)
            if not sec:
                continue

            cards = sec.find_all("article", class_="card")
            for card in cards:
                title_el = card.find("h3", class_="card-title")
                if not title_el:
                    continue
                title_text = title_el.text.strip()
                # Evitar duplicar la destacada si ya se incluyó
                if featured_title and title_text in featured_title:
                    continue
                lines.append(f"{label}: {title_text[:75]}")
                break

        if not lines:
            return False, "", ""

        message_body = "\n".join(lines[:6])
        return True, date_str, message_body

    except Exception as e:
        print(f"[Error] Fallo al parsear output/index.html: {e}", flush=True)
        return False, "", ""


def send_ntfy_notification(payload: Dict[str, Any]) -> bool:
    """
    Envía la petición POST a https://ntfy.sh en formato JSON puro
    para soportar emojis y tildes en español.
    """
    headers = {"Content-Type": "application/json"}

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.post(
                NTFY_API_URL,
                json=payload,
                headers=headers,
                timeout=12.0
            )
            if resp.status_code == 200:
                print(f"[ntfy] Notificación enviada con éxito (HTTP {resp.status_code}).", flush=True)
                return True
            else:
                print(f"[ntfy] Respuesta inesperada del servidor (HTTP {resp.status_code}): {resp.text[:120]}", flush=True)
        except Exception as e:
            print(f"[ntfy] Error de conexión (intento {attempt + 1}/{MAX_RETRIES + 1}): {type(e).__name__}", flush=True)

        if attempt < MAX_RETRIES:
            print(f"[ntfy] Reintentando envío en {RETRY_DELAY}s...", flush=True)
            time.sleep(RETRY_DELAY)

    return False


def main():
    print("=" * 60, flush=True)
    print("DAILY DIGEST - Servicio de Notificaciones (ntfy)", flush=True)
    print("=" * 60, flush=True)

    ntfy_topic = os.getenv("NTFY_TOPIC", "").strip()
    raw_site_url = os.getenv("SITE_URL", "").strip()

    # Si SITE_URL está vacío o contiene el placeholder de ejemplo 'tu-usuario',
    # usar la URL real oficial de GitHub Pages de TheFastag
    if not raw_site_url or "tu-usuario" in raw_site_url:
        site_url = DEFAULT_SITE_URL
    else:
        site_url = raw_site_url

    if not ntfy_topic:
        print("[Aviso] NTFY_TOPIC no está configurado en las variables de entorno. Notificación omitida.", flush=True)
        sys.exit(0)

    print(f"[ntfy] Topic destino: {mask_secret(ntfy_topic)}", flush=True)
    print(f"[ntfy] Enlace click (SITE_URL): {site_url}", flush=True)

    success, date_str, digest_summary = extract_digest_summary()

    if success and digest_summary:
        title = f"Tu resumen de hoy · {date_str}" if date_str else "Tu resumen de hoy"
        payload = {
            "topic": ntfy_topic,
            "title": title,
            "message": digest_summary,
            "priority": 3,
            "tags": ["newspaper", "memo", "sparkles"]
        }
        if site_url:
            payload["click"] = site_url

        print(f"[ntfy] Preparando envío con {len(digest_summary.splitlines())} titulares...", flush=True)
        ok = send_ntfy_notification(payload)
        if not ok:
            print("[ntfy] No se pudo entregar la notificación tras los reintentos.", flush=True)
            sys.exit(1)
    else:
        print("[Alerta] El archivo output/index.html no existe o está vacío. Enviando aviso de error...", flush=True)
        payload = {
            "topic": ntfy_topic,
            "title": "⚠️ Error en Daily Digest",
            "message": "No se pudo generar el resumen diario de hoy. Revisa la ejecución de GitHub Actions.",
            "priority": 4,
            "tags": ["warning", "x"]
        }
        if site_url:
            payload["click"] = site_url

        send_ntfy_notification(payload)
        sys.exit(1)


if __name__ == "__main__":
    main()
