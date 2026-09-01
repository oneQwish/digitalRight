FROM python:3.11-slim

# Ставим Tesseract и системные библиотеки
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-rus \
    tesseract-ocr-eng \
    wget \
    poppler-utils \
    && apt-get clean

# Скачиваем "best" словари для максимальной точности в юридических текстах
RUN mkdir -p /usr/share/tesseract-ocr/5/tessdata/best && \
    wget -O /usr/share/tesseract-ocr/5/tessdata/best/rus.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/rus.traineddata && \
    wget -O /usr/share/tesseract-ocr/5/tessdata/best/eng.traineddata https://github.com/tesseract-ocr/tessdata_best/raw/main/eng.traineddata

ENV TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata/best

# CPU-сборка PyTorch (без CUDA-библиотек — это ~2 ГБ мёртвого веса на
# хосте без NVIDIA GPU, а сейчас его нигде нет). Ставится ДО easyocr, чтобы
# он не подтянул полную GPU-сборку сам. Когда на проде появится NVIDIA GPU —
# заменить эту строку на CUDA-сборку с pytorch.org (индекс зависит от версии
# CUDA на хосте) и включить GPU-секцию в docker-compose.yaml (см. ЭКСПЛУАТАЦИЯ.md §2).
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Предзагружаем модели EasyOCR (ru+en) на этапе сборки — иначе первый же
# запрос с engine=easyocr будет качать их из интернета в рантайме, а на
# сервере без исходящего доступа просто упадёт.
RUN python3 -c "import easyocr; easyocr.Reader(['ru', 'en'], gpu=False)"

COPY app.py /app.py
EXPOSE 9091
CMD ["python", "/app.py"]
