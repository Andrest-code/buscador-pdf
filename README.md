# Buscador de PDF

Aplicación web hecha con Flask para subir PDF, indexar su contenido y buscar en ellos desde el navegador. También detecta archivos repetidos para mantener tu biblioteca ordenada.

## Características

- Subida de uno o varios PDF desde el navegador (hasta 200 MB por solicitud).
- Indexación del contenido de cada PDF con PyMuPDF.
- Búsqueda de palabras en los documentos indexados.
- Detección de duplicados mediante hash SHA-256 y revisión manual en una pantalla aparte.
- Eliminación de documentos y limpieza de repetidos.
- Visualización de los PDF directamente desde la aplicación.

## Tecnologías

- Python
- Flask
- PyMuPDF (`pymupdf`)
- SQLite

## Instalación

Requisitos: Python 3 y Git.

```bash
git clone https://github.com/Andrest-code/Buscador_pdf.git
cd Buscador_pdf
python -m venv venv
source venv/Scripts/activate   # Windows (Git Bash)
# source venv/bin/activate     # Linux / macOS
pip install -r requirements.txt
```

## Uso

```bash
python app.py
```

Luego abre en el navegador: http://127.0.0.1:5000

La aplicación crea automáticamente la carpeta `uploads/` para guardar los PDF subidos.

## Estructura del proyecto

```
Buscador_pdf/
├── app.py              # Aplicación Flask (rutas y lógica)
├── requirements.txt    # Dependencias
├── static/             # Estilos (CSS)
├── templates/          # Plantillas HTML (index, duplicados)
├── uploads/            # PDF subidos (no se versiona)
└── buscador.db         # Base de datos SQLite local (no se versiona)
```

## Próximas mejoras

- Agregar capturas de pantalla de la aplicación.

## Autor

Andrés Torres - [GitHub](https://github.com/Andrest-code)
