# Legal Tech Pipeline

Автоматическая обработка PDF судебных документов: юрист кладёт файл в `inbox/`,
n8n прогоняет его через OCR (Tesseract или EasyOCR — переключается прямо в
workflow, см. `ЭКСПЛУАТАЦИЯ.md` §2) и regex-экстрактор полей, результат
попадает в PostgreSQL (`legal_db`, с pgvector и полнотекстовым поиском),
уведомления об успехе/ошибке приходят через ntfy.

Полный операционный справочник (архитектура, SQL-запросы, устранение
неисправностей, бэкапы) — в [ЭКСПЛУАТАЦИЯ.md](ЭКСПЛУАТАЦИЯ.md). Этот файл —
только быстрый старт.

## Быстрый старт

```bash
# 1. Настроить окружение
cp .env.example .env
# отредактировать .env: задать POSTGRES_PASSWORD и сгенерировать
# N8N_ENCRYPTION_KEY (openssl rand -hex 32)

# 2. Положить справочник судов из 1С (см. db/import_courts.py)
#    в data/Suds - TDSheet.csv — файл не в git, кладётся вручную

# 3. Поднять контейнеры
docker compose up -d
docker compose ps   # legal-postgres должен стать (healthy)

# 4. Импортировать справочник судов
python3 db/import_courts.py | docker exec -i legal-postgres psql -U "$POSTGRES_USER" -d legal_db

# 5. Импортировать workflow в n8n (без захода в браузер)
docker cp "n8n/legal-pipeline.workflow.json" legal-n8n:/tmp/legal-pipeline.workflow.json
docker exec legal-n8n n8n import:workflow --input=/tmp/legal-pipeline.workflow.json
#    затем в http://localhost:5678 создать Postgres-credential
#    (Credentials → New → Postgres, имя legal_db) и привязать её к четырём
#    Postgres-нодам workflow — credential не переносится автоматически.
#    Либо сразу собрать workflow с готовым id credential:
#    N8N_PG_CREDENTIAL_ID=<id> python3 n8n/build_workflow.py

# 6. Проверить пайплайн
#    положить тестовый PDF в inbox/, открыть workflow «legal-pipeline»,
#    нажать Execute workflow
```

## Структура проекта

```
├── docker-compose.yaml   # 4 контейнера: postgres, n8n, tesseract-api, ntfy
├── Dockerfile            # сборка n8n-образа (+ pdftoppm из poppler-utils)
├── ocr-service/          # Flask-обёртка: Tesseract + EasyOCR (сервис tesseract-api)
├── db/
│   ├── init.sql          # схема legal_db — единственный источник истины
│   ├── import_courts.py  # импорт справочника судов из выгрузки 1С
│   └── tests/
├── n8n/
│   ├── code/              # JS-логика Code-нод workflow (версионируется отдельно)
│   ├── build_workflow.py  # собирает n8n/legal-pipeline.workflow.json из шаблона + code/*.js
│   ├── workflow_template.json
│   └── legal-pipeline.workflow.json  # готовый к импорту в n8n workflow
└── data/                  # внешние данные (выгрузки 1С), не в git
```

Если меняется логика пайплайна в n8n — правьте файлы в `n8n/code/`, затем
пересоберите workflow:

```bash
python3 n8n/build_workflow.py
```

## Тесты

```bash
pip install -r ocr-service/requirements.txt pytest
python3 -m pytest db/tests ocr-service/tests
```
