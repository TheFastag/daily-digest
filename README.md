# 📰 Daily Digest

Generador estático y ligero en Python que recopila noticias en español de las últimas 24 horas mediante feeds RSS organizados por categorías, elimina duplicados, **sintetiza resúmenes objetivos con la API oficial de Google Gemini (SDK `google-genai`)** y publica automáticamente el resumen diario en **GitHub Pages** (o **Netlify**), enviando una notificación push a tu móvil con **ntfy**.

---

## 🚀 Arquitectura y Características

- **Inteligencia Artificial con Google Gemini**:
  - Modelo Flash oficial (`gemini-3.5-flash`), rápido y en el free tier.
  - **1 llamada por categoría**: Envía todas las notas de cada sección en un único payload JSON para optimizar la cuota.
  - **Selección de la Noticia del Día**: En *Último Minuto*, Gemini analiza todos los titulares de la jornada y selecciona la noticia más relevante con su motivo de impacto (`⭐ Noticia del Día`).
  - **Caché persistente (`cache/summaries_cache.json`)**: No vuelve a resumir URLs ya procesadas.
  - **Tolerancia a fallos**: Reintento automático ante picos temporales (HTTP 503/429) y fallback a extractos del RSS si el servicio de IA no responde.
- **Fuentes RSS categorizadas (`feeds.yaml`)**:
  - `ultimo_minuto`: Noticias urgentes y de última hora.
  - `tecnologia`: Subtemas `ia`, `hardware`, `ciberseguridad`, `programacion`, `gadgets` y `emergentes` (máximo 2 consecutivas del mismo subtema).
  - `economia`: Finanzas y mercados.
  - `sociedad`: Actualidad en Iberoamérica.
  - `local`: Cobertura regional de México, Quintana Roo y Playa del Carmen.
  - `cultura_general`: 3 notas aleatorias de subtemas distintos cada día (`politica`, `musica`, `arte`, `biologia`, `ciencia`, `historia`, `filosofia`).
- **Pipeline Automatizado en GitHub Actions (`.github/workflows/daily-digest.yml`)**:
  - Se ejecuta automáticamente todos los días a las **7:00 AM hora de Quintana Roo / Cancún (12:00 UTC)**.
  - Permite ejecución manual bajo demanda mediante `workflow_dispatch`.
  - **Job 1 (build)**: Extrae noticias, resume con Gemini, genera la web en `output/`, hace commit automático de las copias históricas (`output/archive/`) y de la caché (`cache/`) a la rama principal con `github-actions[bot]`, y sube el artefacto de Pages.
  - **Job 2 (deploy)**: Despliega la web directamente en **GitHub Pages**.
  - **Job 3 (notify)**: Ejecuta `notify.py` para enviar la notificación push con titulares sin esperas artificiales.
- **Notificaciones Push con ntfy (`notify.py`)**:
  - Publica mediante JSON directo en `https://ntfy.sh` (garantizando soporte de emojis y tildes en español).
  - Incluye la noticia del día / último minuto y los titulares más relevantes de las demás secciones.
  - Abre la página del resumen al tocar la notificación (`click = SITE_URL`).
  - Si el digest falló, envía un aviso de alerta corto en lugar de silencio.

---

## 📂 Estructura del Proyecto

```text
daily-digest/
├── .github/
│   └── workflows/
│       └── daily-digest.yml   # Workflow de GitHub Actions (build, deploy, notify)
├── .env.example               # Plantilla de variables de entorno locales
├── .env                       # Variables protegidas locales (ignorado en git)
├── .gitignore                 # Excluye .env, .venv, __pycache__, etc.
├── config.py                  # Configuración centralizada de rutas y Gemini
├── summarizer.py              # Lógica de Gemini por lote, caché y fallback
├── notify.py                  # Cliente de notificaciones push con ntfy.sh
├── main.py                    # Orquestador: extracción, filtrado y compilación HTML
├── feeds.yaml                 # Definición de feeds RSS categorizados
├── requirements.txt           # Dependencias Python
├── netlify.toml               # Configuración opcional para Netlify
├── README.md                  # Esta documentación
├── templates/
│   ├── digest.html            # Plantilla del resumen diario
│   └── archive_index.html     # Plantilla del archivo histórico
├── tests/
│   └── test_summarizer.py     # Pruebas unitarias automatizadas
├── cache/                     # Caché persistente de resúmenes (versionado en git)
│   └── summaries_cache.json
└── output/                    # Sitio estático generado
    ├── index.html             # Edición de hoy
    └── archive/
        ├── index.html         # Lista de ediciones anteriores
        └── YYYY-MM-DD.html    # Archivos por fecha
```

---

## 🔐 Configuración de Secrets en GitHub

Para que la automatización en GitHub Actions funcione, agrega los siguientes **Repository Secrets**:

1. En tu repositorio de GitHub, dirígete a:
   **Settings > Secrets and variables > Actions > New repository secret**.
2. Agrega los 3 secretos:

| Secret | Descripción | Ejemplo de Valor |
| :--- | :--- | :--- |
| `GEMINI_API_KEY` | Tu clave de API gratuita de [Google AI Studio](https://aistudio.google.com/) | `AQ.Ab8RN6...` |
| `NTFY_TOPIC` | Nombre único y privado para tu canal en [ntfy.sh](https://ntfy.sh) | `daily-digest-emp-7294` |
| `SITE_URL` | URL donde está publicado tu digest (GitHub Pages o Netlify) | `https://thefastag.github.io/daily-digest/` |

> 🔒 **Seguridad**: Los scripts y el workflow nunca imprimen los valores de los secrets en los logs de consola.

---

## 🚀 Despliegue en GitHub Pages (Recomendado)

1. En tu repositorio de GitHub, ve a **Settings > Pages**.
2. En **Build and deployment > Source**, selecciona:
   **`GitHub Actions`**.
3. ¡Listo! Cada día a las 7:00 AM (hora de Quintana Roo / UTC-5) el workflow se disparará automáticamente, publicará tu sitio y enviará la notificación a tu móvil.

---

## 🌐 Alternativa: Conexión con Netlify

Si prefieres usar Netlify para servir el sitio:
1. En Netlify, haz clic en **Add new site > Import an existing project**.
2. Conecta tu repositorio de GitHub.
3. Deja los ajustes de compilación como sigue:
   - **Build command**: *(Dejar vacío, ya que GitHub Actions compila el sitio y persiste el histórico)*
   - **Publish directory**: `output`
4. En **Site configuration > Environment variables**, puedes agregar tu `SITE_URL` con el dominio que te dé Netlify (ej. `https://mi-daily-digest.netlify.app/`).

---

## 📲 Recibir Notificaciones en tu Móvil con ntfy

1. Descarga la aplicación gratuita **ntfy** en tu teléfono ([Android en Google Play / F-Droid](https://play.google.com/store/apps/details?id=io.heckel.ntfy) o [iOS en App Store](https://apps.apple.com/app/ntfy/id1625396347)).
2. Abre la app, toca en **+ (Suscribirse a tema)**.
3. Escribe exactamente el mismo nombre de tema que configuraste en `NTFY_TOPIC` (por ejemplo: `daily-digest-emp-7294`).
4. Cada mañana a las 7:00 AM recibirás una notificación push con los titulares más destacados y, al tocarla, se abrirá directamente tu resumen en el navegador.

---

## 🧪 Cómo Probar Manualmente

### 1. En GitHub Actions (`workflow_dispatch`):
1. En GitHub, haz clic en la pestaña **Actions**.
2. En la lista izquierda, selecciona **Daily Digest Pipeline**.
3. Haz clic en el botón **Run workflow** > **Run workflow**.
4. Podrás seguir los 3 jobs en tiempo real:
   - `build`: Extrae notas, consulta Gemini y persiste los cambios.
   - `deploy`: Publica en GitHub Pages.
   - `notify`: Envía la notificación push a tu teléfono.

### 2. Localmente en tu computadora:
```powershell
cd C:\Users\EMP\Documents\THE-FASTAG\daily-digest

# Ejecutar el generador:
.\.venv\Scripts\python.exe main.py

# Probar el envío de notificación local (si definiste NTFY_TOPIC en .env):
.\.venv\Scripts\python.exe notify.py

# Abrir el resultado en el navegador:
Start-Process output\index.html
```

---

## 📄 Licencia
Código abierto bajo licencia MIT.

