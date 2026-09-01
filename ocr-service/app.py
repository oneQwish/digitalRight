from flask import Flask, request
import pytesseract
from pdf2image import convert_from_bytes
from PIL import Image
import io
import os

app = Flask(__name__)

@app.route('/ocr', methods=['POST'])
def ocr():
    if 'file' not in request.files:
        return {"error": "No file part in the request"}, 400
    
    file = request.files['file']
    if file.filename == '':
        return {"error": "No selected file"}, 400

    try:
        file_bytes = file.read()
        
        # Если пришел PDF (судебное решение или иск)
        if file.filename.lower().endswith('.pdf'):
            # Конвертируем страницы PDF в изображения (нужен poppler-utils)
            images = convert_from_bytes(file_bytes)
            full_text = ""
            for img in images:
                # Распознаем текст с использованием русского и английского языков
                full_text += pytesseract.image_to_string(img, lang='rus+eng') + "\n"
        else:
            # Если пришла обычная картинка
            img = Image.open(io.BytesIO(file_bytes))
            full_text = pytesseract.image_to_string(img, lang='rus+eng')
            
        return {"text": full_text.strip()}
    
    except Exception as e:
        return {"error": str(e)}, 500

if __name__ == '__main__':
    # host='0.0.0.0' обязателен для Docker, чтобы принимать запросы извне

    app.run(host='0.0.0.0', port=9091)
