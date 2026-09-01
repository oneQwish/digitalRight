# Stage 1: vanilla Alpine — package manager intact, устанавливаем poppler-utils
FROM alpine:3.22 AS poppler-stage
RUN apk add --no-cache poppler-utils && \
    mkdir -p /export/usr/bin && \
    cp /usr/bin/pdftoppm /export/usr/bin/ && \
    # ldd даёт полный транзитивный список .so — копируем всё, кроме musl-загрузчика
    # (он уже есть в n8n-образе, т.к. Node.js тоже динамически скомпонован)
    ldd /usr/bin/pdftoppm 2>/dev/null \
        | grep -oE '(/usr/lib|/lib)/[^ ]+' \
        | grep -v 'ld-musl' \
        | sort -u \
        | while read lib; do \
            dest="/export$(dirname "$lib")"; \
            mkdir -p "$dest"; \
            cp -L "$lib" "$dest/$(basename "$lib")"; \
          done

# Stage 2: n8n Hardened Image — пакетного менеджера нет, инжектируем напрямую
FROM n8nio/n8n:latest
USER root
COPY --from=poppler-stage /export/ /
USER node
