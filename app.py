import asyncio
import re
import subprocess
from pathlib import Path
import tempfile

import streamlit as st
import edge_tts
from pypdf import PdfReader


VOZ = "es-CL-CatalinaNeural"
CARACTERES_POR_PARTE = 3000


def limpiar_texto(texto: str) -> str:
    texto = texto.replace("\x00", " ")
    texto = re.sub(r"-\n", "", texto)
    texto = re.sub(r"\n+", "\n", texto)
    texto = re.sub(r"[ \t]+", " ", texto)
    texto = re.sub(r"TEOLOGÍA SISTEMÁTICA:.*?\d+", "", texto, flags=re.IGNORECASE)
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def extraer_texto_pdf(ruta_pdf: str) -> str:
    reader = PdfReader(ruta_pdf)
    paginas = []

    for i, page in enumerate(reader.pages, start=1):
        texto_pagina = page.extract_text() or ""
        texto_pagina = limpiar_texto(texto_pagina)

        if texto_pagina:
            paginas.append(f"Página {i}. {texto_pagina}")

    return limpiar_texto(" ".join(paginas))


def dividir_texto(texto: str, max_caracteres: int) -> list[str]:
    partes = []
    texto = texto.strip()

    while len(texto) > max_caracteres:
        corte = texto.rfind(". ", 0, max_caracteres)

        if corte == -1:
            corte = texto.rfind(" ", 0, max_caracteres)

        if corte == -1:
            corte = max_caracteres

        partes.append(texto[:corte + 1].strip())
        texto = texto[corte + 1:].strip()

    if texto:
        partes.append(texto)

    return partes


async def generar_audio_parte(texto: str, archivo_salida: Path, velocidad: str):
    communicate = edge_tts.Communicate(
        text=texto,
        voice=VOZ,
        rate=velocidad,
        pitch="+0Hz"
    )
    await communicate.save(str(archivo_salida))


def unir_mp3_con_ffmpeg(carpeta: Path, archivo_final: Path):
    archivos = sorted(carpeta.glob("parte_*.mp3"))

    if not archivos:
        raise RuntimeError("No se encontraron audios parciales para unir.")

    lista_txt = carpeta / "lista_archivos.txt"

    with open(lista_txt, "w", encoding="utf-8") as f:
        for archivo in archivos:
            f.write(f"file '{archivo.resolve().as_posix()}'\n")

    comando = [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", str(lista_txt),
        "-c", "copy",
        str(archivo_final)
    ]

    subprocess.run(comando, check=True)


async def procesar_pdf(ruta_pdf: Path, carpeta: Path, velocidad: str, barra):
    texto = extraer_texto_pdf(str(ruta_pdf))

    if not texto:
        raise RuntimeError("No se pudo extraer texto desde el PDF.")

    partes = dividir_texto(texto, CARACTERES_POR_PARTE)

    for idx, parte in enumerate(partes, start=1):
        archivo = carpeta / f"parte_{idx:04d}.mp3"
        await generar_audio_parte(parte, archivo, velocidad)

        avance = idx / len(partes)
        barra.progress(avance, text=f"Generando audio {idx}/{len(partes)}")

        await asyncio.sleep(0.3)

    salida = carpeta / "audiolibro_catalina.mp3"
    unir_mp3_con_ffmpeg(carpeta, salida)

    return salida, len(partes)


st.set_page_config(
    page_title="PDF a MP3 - Audiolibro",
    page_icon="🎧",
    layout="centered"
)

st.title("🎧 PDF a MP3 con voz chilena")
st.write("Convierte un PDF en audiolibro usando la voz **es-CL-CatalinaNeural**.")

archivo_pdf = st.file_uploader("Sube tu archivo PDF", type=["pdf"])

velocidad = st.selectbox(
    "Velocidad de lectura",
    ["-20%", "-10%", "+0%", "+10%", "+20%"],
    index=2
)

if archivo_pdf is not None:
    st.info(f"Archivo cargado: {archivo_pdf.name}")

if archivo_pdf is not None and st.button("Generar MP3"):
    with tempfile.TemporaryDirectory() as tmp:
        carpeta = Path(tmp)
        ruta_pdf = carpeta / archivo_pdf.name
        ruta_pdf.write_bytes(archivo_pdf.read())

        barra = st.progress(0, text="Iniciando generación del audio...")

        try:
            salida, total_partes = asyncio.run(
                procesar_pdf(ruta_pdf, carpeta, velocidad, barra)
            )

            audio_bytes = salida.read_bytes()

            st.success(f"MP3 generado correctamente. Partes procesadas: {total_partes}")
            st.audio(audio_bytes, format="audio/mp3")

            st.download_button(
                label="Descargar MP3",
                data=audio_bytes,
                file_name="audiolibro_catalina.mp3",
                mime="audio/mp3"
            )

        except FileNotFoundError:
            st.error("No se encontró FFmpeg. Revisa que el archivo packages.txt contenga solamente: ffmpeg")
        except subprocess.CalledProcessError:
            st.error("FFmpeg tuvo un problema al unir los audios.")
        except Exception as e:
            st.error(f"Ocurrió un error: {e}")
