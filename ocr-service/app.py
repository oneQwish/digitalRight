from flask import Flask, request
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
import io
import os
import numpy as np

app = Flask(__name__)

_easyocr_reader = None


def _get_easyocr_reader():
    """Ленивая инициализация — модели EasyOCR тяжёлые, грузим один раз при
    первом запросе с engine=easyocr, а не при каждом обращении."""
    global _easyocr_reader
    if _easyocr_reader is None:
        import easyocr
        # gpu=True запрашивает CUDA (Linux) / MPS (Apple Silicon) через PyTorch.
        # Если GPU/драйверов нет — EasyOCR молча откатывается на CPU, не падает.
        _easyocr_reader = easyocr.Reader(['ru', 'en'], gpu=True)
    return _easyocr_reader


def _ocr_tesseract(img):
    return pytesseract.image_to_string(img, lang='rus+eng')


def _ocr_easyocr(img):
    reader = _get_easyocr_reader()
    lines = reader.readtext(np.array(img.convert('RGB')), detail=0, paragraph=True)
    return "\n".join(lines)


# Движок выбирается полем "engine" в теле запроса (по умолчанию — tesseract).
# В n8n-пайплайне это значение приходит из ноды "OCR Engine" — так движок
# можно переключить прямо в workflow, без правки кода.
ENGINES = {
    'tesseract': _ocr_tesseract,
    'easyocr': _ocr_easyocr,
}


@app.route('/ocr', methods=['POST'])
def ocr():
    if 'file' not in request.files:
        return {"error": "No file part in the request"}, 400

    file = request.files['file']
    if file.filename == '':
        return {"error": "No selected file"}, 400

    engine_name = request.form.get('engine', 'tesseract')
    run_ocr = ENGINES.get(engine_name)
    if run_ocr is None:
        return {"error": f"Unknown engine '{engine_name}', expected one of {sorted(ENGINES)}"}, 400

    try:
        file_bytes = file.read()

        # Если пришел PDF (судебное решение или иск)
        if file.filename.lower().endswith('.pdf'):
            # Конвертируем страницы PDF в изображения (нужен poppler-utils)
            images = convert_from_bytes(file_bytes)
            full_text = ""
            for img in images:
                # Распознаем текст с использованием русского и английского языков
                full_text += run_ocr(img) + "\n"
        else:
            # Если пришла обычная картинка
            img = Image.open(io.BytesIO(file_bytes))
            full_text = run_ocr(img)

        return {"text": full_text.strip(), "engine": engine_name}

    except Exception as e:
        return {"error": str(e)}, 500

if __name__ == '__main__':
    # host='0.0.0.0' обязателен для Docker, чтобы принимать запросы извне

    app.run(host='0.0.0.0', port=9091)
