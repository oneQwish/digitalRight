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

COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

COPY app.py /app.py
EXPOSE 9091
CMD ["python", "/app.py"]
