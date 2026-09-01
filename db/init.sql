-- =============================================================
--  legal_db — Data Lake для юридического отдела
--  Выполняется автоматически при первом запуске контейнера.
-- =============================================================

CREATE DATABASE legal_db;
\c legal_db;

CREATE EXTENSION IF NOT EXISTS vector;    -- pgvector: семантический поиск
CREATE EXTENSION IF NOT EXISTS pg_trgm;   -- триграммы: нечёткий полнотекстовый поиск
CREATE EXTENSION IF NOT EXISTS "uuid-ossp"; -- gen_random_uuid() fallback

-- =============================================================
--  СУДЫ
-- =============================================================
CREATE TABLE courts (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT NOT NULL,
    court_type   TEXT,         -- районный | арбитражный | апелляционный | кассационный
    city         TEXT,
    region       TEXT,
    yurait_id    TEXT UNIQUE,  -- ID в 1С Юрайт (для синхронизации)
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX courts_name_trgm ON courts USING GIN (name gin_trgm_ops);

-- Реконсиляция: вызывается вручную после загрузки courts из 1С.
-- auto_threshold=0.65 → court_id проставляется автоматически.
-- suggest_threshold=0.40 → слишком слабые совпадения игнорируются.
CREATE OR REPLACE FUNCTION reconcile_court_names(
    auto_threshold    REAL DEFAULT 0.65,
    suggest_threshold REAL DEFAULT 0.40
)
RETURNS TABLE(document_id UUID, raw_ocr TEXT, matched_court TEXT, sim REAL, action TEXT)
AS $$
BEGIN
    RETURN QUERY
    WITH matches AS (
        SELECT d.id AS doc_id,
               d.extracted_data->>'court_name' AS raw_ocr,
               c.id   AS court_id,
               c.name AS court_name,
               similarity(c.name, d.extracted_data->>'court_name') AS sim
        FROM documents d
        CROSS JOIN LATERAL (
            SELECT id, name, similarity(name, d.extracted_data->>'court_name') AS s
            FROM courts ORDER BY s DESC LIMIT 1
        ) c
        WHERE d.extracted_data->>'court_name' IS NOT NULL AND d.court_id IS NULL
    )
    UPDATE documents d
    SET court_id = CASE WHEN m.sim >= auto_threshold THEN m.court_id ELSE NULL END,
        extraction_confidence = jsonb_set(
            extraction_confidence, '{court_name}',
            jsonb_build_object(
                'value',  m.court_name,
                'score',  m.sim,
                'method', CASE WHEN m.sim >= auto_threshold
                               THEN 'fuzzy_auto' ELSE 'fuzzy_suggest' END,
                'raw',    m.raw_ocr
            )
        )
    FROM matches m
    WHERE d.id = m.doc_id AND m.sim >= suggest_threshold
    RETURNING d.id, m.raw_ocr, m.court_name, m.sim,
        CASE WHEN m.sim >= auto_threshold THEN 'auto_matched' ELSE 'suggested' END;
END;
$$ LANGUAGE plpgsql;


-- =============================================================
--  СТОРОНЫ (физ- и юрлица)
-- =============================================================
CREATE TABLE parties (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name        TEXT NOT NULL,
    inn         VARCHAR(12),
    party_type  TEXT,   -- физ | юр
    created_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX parties_name_trgm ON parties USING GIN (name gin_trgm_ops);

-- =============================================================
--  ДЕЛА
-- =============================================================
CREATE TABLE cases (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number TEXT UNIQUE,
    court_id    UUID REFERENCES courts(id),
    case_type   TEXT,           -- гражданское | административное | арбитражное
    yurait_id   TEXT UNIQUE,    -- ID объекта в 1С Юрайт
    opened_at   DATE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX cases_yurait ON cases (yurait_id);

-- =============================================================
--  ДОКУМЕНТЫ (все типы)
-- =============================================================
CREATE TABLE documents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID REFERENCES cases(id),
    court_id        UUID REFERENCES courts(id),
    document_type   TEXT NOT NULL,
    -- Значения: решение | иск | определение | апелляция | кассация | прочее
    received_at     DATE,
    source_filename TEXT,
    raw_text        TEXT,           -- полный OCR-текст
    extracted_data        JSONB,     -- структурированные поля (regex + Ollama)
    extraction_confidence JSONB,     -- { field: { value, score, method } } — уверенность по каждому полю
    embedding             vector(768), -- nomic-embed-text: 768-мерный вектор
    ocr_confidence        REAL,
    processed_at          TIMESTAMPTZ, -- когда Ollama заполнила extracted_data
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Полнотекстовый поиск по-русски
CREATE INDEX documents_fts ON documents
    USING GIN (to_tsvector('russian', COALESCE(raw_text, '')));

-- Триграммный поиск (для нечётких совпадений)
CREATE INDEX documents_trgm ON documents
    USING GIN (raw_text gin_trgm_ops);

CREATE INDEX documents_case  ON documents (case_id);
CREATE INDEX documents_court ON documents (court_id) WHERE court_id IS NULL;

-- Векторный индекс HNSW (быстрый поиск ближайших соседей)
-- Создаётся ПОСЛЕ заполнения данных командой:
--   CREATE INDEX CONCURRENTLY documents_embedding_hnsw ON documents
--   USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- =============================================================
--  СТОРОНЫ ПО ДОКУМЕНТУ
-- =============================================================
CREATE TABLE document_parties (
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    party_id    UUID REFERENCES parties(id),
    role        TEXT,   -- истец | ответчик | третье_лицо | эксперт | представитель
    PRIMARY KEY (document_id, party_id, role)
);

-- =============================================================
--  ДЕТАЛИ СУДЕБНЫХ РЕШЕНИЙ
-- =============================================================
CREATE TABLE decisions (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id             UUID UNIQUE REFERENCES documents(id) ON DELETE CASCADE,
    outcome                 TEXT,           -- удовлетворить | отказать | частично
    claimed_amount          NUMERIC(15,2),
    awarded_amount          NUMERIC(15,2),
    penalty_claimed         NUMERIC(15,2),
    penalty_awarded         NUMERIC(15,2),
    -- Процент снижения штрафа — вычислимое поле, основа для поисковых запросов типа
    -- "решения, где штраф снижен более чем на 50%"
    penalty_reduction_pct   REAL GENERATED ALWAYS AS (
        CASE WHEN penalty_claimed > 0
             THEN ROUND(((penalty_claimed - penalty_awarded) / penalty_claimed * 100)::NUMERIC, 1)
             ELSE NULL
        END
    ) STORED,
    judge_name              TEXT,
    decision_date           DATE
);
CREATE INDEX decisions_reduction ON decisions (penalty_reduction_pct);
CREATE INDEX decisions_outcome   ON decisions (outcome);
CREATE INDEX decisions_date      ON decisions (decision_date);

-- =============================================================
--  ЗАСЕДАНИЯ (календарь)
-- =============================================================
CREATE TABLE hearings (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id         UUID REFERENCES cases(id),
    scheduled_at    TIMESTAMPTZ NOT NULL,
    location        TEXT,
    hearing_type    TEXT,   -- предварительное | основное | апелляция
    status          TEXT DEFAULT 'scheduled',
    -- Значения: scheduled | completed | postponed | cancelled
    yurait_sync_id  TEXT,   -- ID заседания в 1С Юрайт
    notes           TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX hearings_scheduled ON hearings (scheduled_at);
CREATE INDEX hearings_case      ON hearings (case_id);
CREATE INDEX hearings_yurait    ON hearings (yurait_sync_id);

-- =============================================================
--  БАЗА ЗНАНИЙ
-- =============================================================
CREATE TABLE knowledge_articles (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       TEXT NOT NULL,
    content     TEXT,
    category    TEXT,       -- шаблоны | практика | процессуальное | прочее
    tags        TEXT[],
    embedding   vector(768),
    created_by  TEXT,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX knowledge_fts ON knowledge_articles
    USING GIN (to_tsvector('russian', COALESCE(title, '') || ' ' || COALESCE(content, '')));
CREATE INDEX knowledge_tags ON knowledge_articles USING GIN (tags);
-- Векторный индекс — создать ПОСЛЕ первичного заполнения:
--   CREATE INDEX CONCURRENTLY knowledge_embedding_hnsw ON knowledge_articles
--   USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- =============================================================
--  ДЕДУПЛИКАЦИЯ ВХОДЯЩИХ ФАЙЛОВ
--  Хэш = SHA256(fileName + fileSize), вычисляется n8n Crypto-нодой.
--  Файл обрабатывается только если его хэша нет в этой таблице.
-- =============================================================
CREATE TABLE file_hashes (
    id         SERIAL PRIMARY KEY,
    hash       TEXT NOT NULL UNIQUE,
    filename   TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX file_hashes_hash_idx ON file_hashes (hash);

-- =============================================================
--  ЛОГ ОБРАБОТКИ (аудит n8n-пайплайна)
--  Каждый этап пишет строку start/success/error.
--  document_id = NULL если ошибка до INSERT в documents.
-- =============================================================
CREATE TABLE processing_log (
    id           SERIAL PRIMARY KEY,
    document_id  UUID REFERENCES documents(id) ON DELETE SET NULL,
    filename     TEXT NOT NULL,
    stage        TEXT NOT NULL,   -- ocr | extraction | embedding | reconcile
    status       TEXT NOT NULL,   -- started | success | error
    message      TEXT,
    created_at   TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX processing_log_doc   ON processing_log (document_id);
CREATE INDEX processing_log_stage ON processing_log (stage, status);

-- =============================================================
--  ВСПОМОГАТЕЛЬНАЯ ФУНКЦИЯ: обновление updated_at
-- =============================================================
CREATE OR REPLACE FUNCTION touch_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
$$;

CREATE TRIGGER cases_updated_at
    BEFORE UPDATE ON cases
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER hearings_updated_at
    BEFORE UPDATE ON hearings
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

CREATE TRIGGER knowledge_updated_at
    BEFORE UPDATE ON knowledge_articles
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
