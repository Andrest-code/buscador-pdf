import hashlib
import logging
import os
import sys
import time
import re
import sqlite3
import uuid
from html import escape
from urllib.parse import quote

import pymupdf as fitz  # PyMuPDF (nombre nuevo, quita el aviso)
from flask import (Flask, flash, redirect, render_template, request,
                   send_from_directory, url_for)
from flask_wtf.csrf import CSRFProtect

BASE = os.path.dirname(os.path.abspath(__file__))
UPLOADS = os.path.join(BASE, "uploads")
PENDIENTES = os.path.join(UPLOADS, "pendientes")
DB = os.path.join(BASE, "buscador.db")
os.makedirs(PENDIENTES, exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY") or os.urandom(24).hex()
CSRFProtect(app)
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
logging.getLogger("werkzeug").setLevel(logging.ERROR)
def log(texto):
    """Mensaje corto en la terminal con la hora."""
    print(f"[{time.strftime('%H:%M:%S')}] {texto}", flush=True)  


# ---------- BASE DE DATOS ----------
def conectar():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def hash_archivo(ruta):
    h = hashlib.sha256()
    with open(ruta, "rb") as f:
        for bloque in iter(lambda: f.read(1024 * 1024), b""):
            h.update(bloque)
    return h.hexdigest()


def crear_tablas():
    con = conectar()
    con.execute("""
        CREATE TABLE IF NOT EXISTS documentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            archivo TEXT NOT NULL UNIQUE,
            paginas INTEGER
        )
    """)
    columnas = [c["name"] for c in con.execute("PRAGMA table_info(documentos)")]
    if "hash" not in columnas:
        con.execute("ALTER TABLE documentos ADD COLUMN hash TEXT")

    con.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS paginas USING fts5(
            texto,
            documento_id UNINDEXED,
            pagina UNINDEXED,
            tokenize = 'unicode61 remove_diacritics 2'
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS pendientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT,
            archivo TEXT,
            hash TEXT,
            existente_id INTEGER
        )
    """)

    # Calcula el hash de los documentos que ya tenías cargados
    sin_hash = con.execute(
        "SELECT id, archivo FROM documentos WHERE hash IS NULL").fetchall()
    for d in sin_hash:
        ruta = os.path.join(UPLOADS, d["archivo"])
        if os.path.exists(ruta):
            con.execute("UPDATE documentos SET hash = ? WHERE id = ?",
                        (hash_archivo(ruta), d["id"]))
    con.commit()
    con.close()


def indexar_pdf(ruta, nombre_original, hash_pdf):
    inicio = time.time()
    doc = fitz.open(ruta)
    total = len(doc)
    con = conectar()
    cur = con.execute(
        "INSERT INTO documentos (nombre, archivo, paginas, hash) VALUES (?, ?, ?, ?)",
        (nombre_original, os.path.basename(ruta), total, hash_pdf),
    )
    doc_id = cur.lastrowid
    con_texto = 0
    for num, pagina in enumerate(doc, start=1):
        texto = pagina.get_text()
        if texto.strip():
            con_texto += 1
            con.execute(
                "INSERT INTO paginas (texto, documento_id, pagina) VALUES (?, ?, ?)",
                (texto, doc_id, num),
            )
    con.commit()
    con.close()
    doc.close()
    log(f"SUBIDO    {nombre_original} | {total} págs. ({con_texto} con texto) | {time.time() - inicio:.1f}s")
    if con_texto < total:
        log(f"AVISO     {nombre_original}: {total - con_texto} pág(s). sin texto (posible imagen escaneada)")

def eliminar_documento(doc_id):
    con = conectar()
    fila = con.execute("SELECT nombre, archivo FROM documentos WHERE id = ?",
                       (doc_id,)).fetchone()
    if fila:
        con.execute("DELETE FROM paginas WHERE CAST(documento_id AS INTEGER) = ?",
                    (doc_id,))
        con.execute("DELETE FROM documentos WHERE id = ?", (doc_id,))
        con.commit()
        ruta = os.path.join(UPLOADS, fila["archivo"])
        if os.path.exists(ruta):
            os.remove(ruta)
        log(f"ELIMINADO {fila['nombre']}")
    con.close()


def buscar_repetido(hash_pdf, nombre):
    con = conectar()
    fila = con.execute(
        "SELECT id FROM documentos WHERE hash = ? OR nombre = ?",
        (hash_pdf, nombre)).fetchone()
    con.close()
    return fila["id"] if fila else None


def guardar_pendiente(nombre, archivo, hash_pdf, existente_id):
    con = conectar()
    con.execute(
        "INSERT INTO pendientes (nombre, archivo, hash, existente_id) VALUES (?, ?, ?, ?)",
        (nombre, archivo, hash_pdf, existente_id))
    con.commit()
    con.close()


def limpiar_pendientes():
    con = conectar()
    for p in con.execute("SELECT archivo FROM pendientes").fetchall():
        ruta = os.path.join(PENDIENTES, p["archivo"])
        if os.path.exists(ruta):
            os.remove(ruta)
    con.execute("DELETE FROM pendientes")
    con.commit()
    con.close()


def buscar(q):
    palabras = re.findall(r"\w+", q)
    if not palabras:
        return []

    consulta = " ".join(f'"{p}"*' for p in palabras)

    con = conectar()
    filas = con.execute("""
        SELECT d.nombre, d.archivo, h.pagina, h.fragmento
        FROM (
            SELECT CAST(documento_id AS INTEGER) AS doc_id,
                   CAST(pagina AS INTEGER) AS pagina,
                   snippet(paginas, 0, '[[', ']]', ' ... ', 25) AS fragmento
            FROM paginas
            WHERE paginas MATCH ?
        ) h
        JOIN documentos d ON d.id = h.doc_id
        ORDER BY d.nombre, h.pagina
    """, (consulta,)).fetchall()
    con.close()

    resultados = []
    for f in filas:
        fragmento = escape(f["fragmento"]).replace("\n", " ")
        fragmento = fragmento.replace("[[", "<mark>").replace("]]", "</mark>")
        url = (url_for("ver_pdf", archivo=f["archivo"])
               + f"#page={f['pagina']}&search={quote(palabras[0])}")
        resultados.append({
            "nombre": f["nombre"],
            "pagina": f["pagina"],
            "fragmento": fragmento,
            "url": url,
        })
    docs_con_resultado = len({r["nombre"] for r in resultados})
    log(f"BUSQUEDA  \"{q}\" -> {len(resultados)} coincidencia(s) en {docs_con_resultado} documento(s)")
    return resultados


# ---------- RUTAS ----------
@app.route("/")
def index():
    q = request.args.get("q", "").strip()
    resultados = buscar(q) if q else []

    con = conectar()
    docs = con.execute("SELECT * FROM documentos ORDER BY nombre").fetchall()
    pendientes = con.execute("SELECT COUNT(*) AS n FROM pendientes").fetchone()["n"]
    con.close()

    hashes = [d["hash"] for d in docs if d["hash"]]
    repetidos = len(hashes) - len(set(hashes))

    return render_template("index.html", q=q, resultados=resultados, docs=docs,
                           pendientes=pendientes, repetidos=repetidos)


@app.route("/subir", methods=["POST"])
def subir():
    limpiar_pendientes()
    nuevos = 0
    repetidos = 0

    recibidos = [f for f in request.files.getlist("pdfs")
                 if f and f.filename.lower().endswith(".pdf")]
    log(f"RECIBIDOS {len(recibidos)} archivo(s) PDF")

    for f in recibidos:
        archivo = uuid.uuid4().hex + ".pdf"
        ruta_temp = os.path.join(PENDIENTES, archivo)
        f.save(ruta_temp)
        with open(ruta_temp, "rb") as chk:
            es_pdf = b"%PDF-" in chk.read(1024)
        if not es_pdf:
            os.remove(ruta_temp)
            log(f"RECHAZADO {f.filename}: no es un PDF válido")
            flash(f"{f.filename} no es un PDF válido.")
            continue
        h = hash_archivo(ruta_temp)

        existente = buscar_repetido(h, f.filename)
        if existente:
            guardar_pendiente(f.filename, archivo, h, existente)
            repetidos += 1
            log(f"REPETIDO  {f.filename} (ya existe, esperando decisión)")
            continue

        ruta = os.path.join(UPLOADS, archivo)
        os.replace(ruta_temp, ruta)
        try:
            indexar_pdf(ruta, f.filename, h)
            nuevos += 1
        except Exception as e:
            os.remove(ruta)
            log(f"ERROR     {f.filename}: {e}")
            flash(f"No se pudo leer {f.filename}: {e}")

    log(f"RESUMEN   {nuevos} nuevo(s), {repetidos} repetido(s)")
    if nuevos:
        flash(f"{nuevos} documento(s) agregados.")
    if repetidos:
        return redirect(url_for("duplicados"))
    if not nuevos:
        flash("No se agregó ningún documento.")
    return redirect(url_for("index"))

@app.route("/duplicados", methods=["GET", "POST"])
def duplicados():
    con = conectar()
    pendientes = con.execute("""
        SELECT p.id, p.nombre, p.archivo, p.hash, d.nombre AS existente
        FROM pendientes p
        LEFT JOIN documentos d ON d.id = p.existente_id
        ORDER BY p.nombre
    """).fetchall()
    con.close()

    if not pendientes:
        return redirect(url_for("index"))

    if request.method == "POST":
        if request.form.get("accion") == "reemplazar":
            hechos = 0
            for p in pendientes:
                viejo = buscar_repetido(p["hash"], p["nombre"])
                while viejo:
                    eliminar_documento(viejo)
                    viejo = buscar_repetido(p["hash"], p["nombre"])
                origen = os.path.join(PENDIENTES, p["archivo"])
                destino = os.path.join(UPLOADS, p["archivo"])
                os.replace(origen, destino)
                try:
                    indexar_pdf(destino, p["nombre"], p["hash"])
                    hechos += 1
                except Exception as e:
                    os.remove(destino)
                    flash(f"No se pudo leer {p['nombre']}: {e}")
            con = conectar()
            con.execute("DELETE FROM pendientes")
            con.commit()
            con.close()
            log(f"REEMPLAZO {hechos} documento(s) reemplazados")
            flash(f"{hechos} documento(s) reemplazados.")
        else:
            limpiar_pendientes()
            log("OMITIDO   archivos repetidos descartados")
            flash("Se omitieron los archivos repetidos.")
        return redirect(url_for("index"))

    return render_template("duplicados.html", pendientes=pendientes)


@app.route("/eliminar/<int:doc_id>", methods=["POST"])
def eliminar(doc_id):
    eliminar_documento(doc_id)
    flash("Documento eliminado.")
    return redirect(url_for("index"))


@app.route("/quitar-repetidos", methods=["POST"])
def quitar_repetidos():
    con = conectar()
    filas = con.execute("SELECT id, hash FROM documentos ORDER BY id").fetchall()
    con.close()

    vistos = set()
    borrar = []
    for f in filas:
        if not f["hash"]:
            continue
        if f["hash"] in vistos:
            borrar.append(f["id"])
        else:
            vistos.add(f["hash"])

    for doc_id in borrar:
        eliminar_documento(doc_id)
    log(f"LIMPIEZA  {len(borrar)} documento(s) repetidos eliminados")
    flash(f"{len(borrar)} documento(s) repetidos eliminados.")
    return redirect(url_for("index"))


@app.route("/pdf/<archivo>")
def ver_pdf(archivo):
    return send_from_directory(UPLOADS, archivo)


if __name__ == "__main__":
    import flask.cli
    flask.cli.show_server_banner = lambda *args, **kwargs: None  # oculta el banner

    crear_tablas()
    con = conectar()
    total = con.execute("SELECT COUNT(*) AS n FROM documentos").fetchone()["n"]
    con.close()
    log(f"INICIO    {total} documento(s) en el sistema")
    log("ACTIVO    http://127.0.0.1:5000")
    app.run(debug=False)