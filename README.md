# Generador de Guías SENA — ProfeNaturales

Aplicativo Streamlit que genera automáticamente **tres documentos** en formato oficial **GFPI-F-135** del SENA:

1. **Guía del Aprendiz** — el documento que reciben los estudiantes.
2. **Guía del Instructor** — orientaciones didácticas, respuestas esperadas, errores comunes.
3. **Rúbricas de Evaluación** — una rúbrica por cada actividad (3.1 a 3.4) con 4 niveles.

Todos preservan el encabezado institucional (código GFPI-F-135, versión, logo SENA).

---

## 🚀 Cómo desplegar

### Opción A: Streamlit Community Cloud (recomendado, gratis, en internet)

Esta opción permite que otros instructores accedan a la app por URL sin instalar nada.

1. Ve a [github.com](https://github.com) y crea una cuenta si no tienes.
2. Crea un repositorio nuevo (puede ser privado) llamado por ejemplo `generador-guias-sena`.
3. Sube esta carpeta completa al repositorio (arrastra los archivos desde la interfaz web de GitHub o usa `git`).
4. Ve a [share.streamlit.io](https://share.streamlit.io) e inicia sesión con la misma cuenta de GitHub.
5. Click en **"New app"**, selecciona el repositorio, la rama (`main`) y el archivo principal (`app.py`).
6. Click en **"Deploy"**. En 2–3 minutos tu app estará en línea en una URL como:

   ```
   https://generador-guias-sena-tuusuario.streamlit.app
   ```

7. Comparte esa URL con tus colegas instructores.

### Opción B: Localmente (para uso personal)

Requiere Python 3.9 o superior instalado en tu computador.

```bash
# Descomprimir el proyecto
cd generador_guias

# Instalar dependencias (solo la primera vez)
pip install -r requirements.txt

# Ejecutar la app
streamlit run app.py
```

Se abrirá automáticamente en tu navegador en `http://localhost:8501`.

---

## 📋 Cómo usar la app

### Primera vez
1. En el menú lateral entra a **⚙️ Cargar competencias**.
2. Sube tu Excel de competencias, o pega el enlace público de Google Drive donde lo tienes.
3. Mapea las columnas del Excel (Programa, Código, Competencia, etc).

### Cada nueva guía
1. Entra a **🆕 Nueva guía**.
2. Selecciona programa y competencia (aparecen desde el Excel).
3. Llena los datos del proyecto formativo y los RAPs (la primera vez los transcribes; después ya quedan guardados por competencia).
4. Diligencia las 4 actividades (3.1 a 3.4).
5. Click en **🎯 Generar los 3 documentos** y descarga los archivos.

### Ver historial
- **💾 Guías guardadas**: lista de todas las guías generadas.
- **📚 RAPs guardados**: RAPs transcritos por competencia (reutilizables).

---

## 📁 Estructura del proyecto

```
generador_guias/
├── app.py                          # Aplicativo principal Streamlit
├── requirements.txt                # Dependencias Python
├── README.md                       # Este archivo
├── templates/
│   └── GFPI-F-135.docx             # Plantilla oficial SENA (con encabezado, código, logo)
├── generadores/
│   ├── __init__.py
│   ├── utils_docx.py               # Utilidades compartidas de docx
│   ├── guia_aprendizaje.py         # Genera guía del aprendiz
│   ├── guia_instructor.py          # Genera guía del instructor
│   └── rubricas.py                 # Genera rúbricas de evaluación
├── data/
│   ├── raps_guardados.json         # RAPs por competencia (se llena automáticamente)
│   └── guias_guardadas.json        # Historial de guías generadas
├── ejemplos/
│   └── competencias_ejemplo.xlsx   # Ejemplo de estructura del Excel
└── .streamlit/
    └── config.toml                 # Tema visual print-safe
```

---

## 📊 Estructura sugerida del Excel de competencias

Revisa `ejemplos/competencias_ejemplo.xlsx` para ver un ejemplo. Columnas recomendadas:

| Programa | Código Programa | Competencia | Código Competencia | Fase Sugerida |
|---|---|---|---|---|
| Técnico en Integración de Operaciones Logísticas | 137136 | Aplicar conocimientos de las ciencias naturales | 220201501 | Planear |

Los nombres exactos de las columnas no importan — la app te deja mapearlas cuando cargas el Excel.

---

## 🔐 Sobre la persistencia de datos

Los RAPs transcritos y el historial de guías se guardan en la carpeta `data/`:

- **En uso local**: se conservan permanentemente en tu computador.
- **En Streamlit Cloud**: se conservan mientras el servidor no se reinicia. Para persistencia 100% garantizada en la nube, se puede conectar a Google Sheets como backend. Avísame si quieres agregar esa integración.

---

## 🎨 Personalización

- **Paleta**: la app usa la paleta monocromática print-safe (DARK `#2C2C2C`, MID `#D0D0D0`, LIGHT `#F0F0F0`).
- **Contenido por defecto**: las rúbricas y orientaciones didácticas tienen contenido por defecto sensato que puedes personalizar editando los archivos en `generadores/`.

---

## ❓ Preguntas frecuentes

**¿Puedo usar mi propia plantilla en vez de GFPI-F-135?**
Sí, reemplaza `templates/GFPI-F-135.docx` por tu plantilla (mantén el mismo nombre de archivo).

**¿La app funciona en celular?**
Sí, Streamlit es responsivo.

**¿Puedo generar guías para universidad (no SENA)?**
El formato actual es específico de SENA. Se puede adaptar para Uniguajira u otras — avísame.

---

*ProfeNaturales SENA — Competencia 220201501 · Julio 2026*
