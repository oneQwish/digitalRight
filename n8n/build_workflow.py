"""
Собирает импортируемый n8n-workflow из статического шаблона (workflow_template.json)
и версионируемого JS-кода (code/*.js), добавляя обработку ошибок на каждом
рискованном шаге (PDF→PNG, OCR, извлечение полей).

В отличие от старого db/patch_workflow_errors.py, скрипт не обращается к живому
n8n через REST API и не требует API-ключа — на выходе просто JSON-файл,
готовый к импорту через UI (Workflows → Import from File) или
`n8n import:workflow --input=...`.

Запуск:
    python3 n8n/build_workflow.py

Если меняется логика PDF→PNG / OCR-агрегации / извлечения полей — правьте
соответствующий файл в n8n/code/, а не итоговый JSON напрямую.
"""

import json
import uuid
from pathlib import Path

HERE     = Path(__file__).parent
TEMPLATE = HERE / "workflow_template.json"
CODE_DIR = HERE / "code"
OUTPUT   = HERE / "legal-pipeline.workflow.json"

CODE_FILES = {
    "PDF to Images": "pdf_to_images.js",
    "Aggregate text": "aggregate_text.js",
    "Extract Fields": "extract_fields.js",
}


def uid() -> str:
    return str(uuid.uuid4())


def make_if_error_node(node_name: str, x: int, y: int) -> dict:
    return {
        "id": uid(),
        "name": node_name,
        "type": "n8n-nodes-base.if",
        "typeVersion": 2,
        "position": [x, y],
        "parameters": {
            "conditions": {
                "options": {"caseSensitive": True, "leftValue": "", "typeValidation": "strict"},
                "conditions": [{
                    "id": uid(),
                    "leftValue": "={{ $json._error }}",
                    "rightValue": "",
                    "operator": {"type": "boolean", "operation": "true", "singleValue": True},
                }],
                "combinator": "and",
            }
        },
    }


def make_log_error_node(x: int, y: int) -> dict:
    return {
        "id": uid(),
        "name": "Log Error",
        "type": "n8n-nodes-base.postgres",
        "typeVersion": 2.5,
        "position": [x, y],
        "parameters": {
            "operation": "executeQuery",
            "query": (
                "INSERT INTO processing_log (filename, stage, status, message) "
                "VALUES ($1, $2, 'error', $3) ON CONFLICT DO NOTHING"
            ),
            "options": {
                "queryBatching": "independently",
                "queryReplacement": (
                    "={{ $json.source_filename || 'unknown' }},"
                    "={{ $json.stage || 'unknown' }},"
                    "={{ ($json.message || '').slice(0, 500) }}"
                ),
            },
        },
        "credentials": {"postgres": {"id": "", "name": "legal_db"}},
    }


def make_notify_node(node_name: str, topic: str, title_expr: str,
                      body_expr: str, priority: str, x: int, y: int) -> dict:
    return {
        "id": uid(),
        "name": node_name,
        "type": "n8n-nodes-base.httpRequest",
        "typeVersion": 4.2,
        "position": [x, y],
        "parameters": {
            "method": "POST",
            # Внутри docker-сети ntfy слушает 80, а не 8080 — 8080 это только
            # хостовый порт из docker-compose.yaml ("8080:80").
            "url": f"http://ntfy:80/{topic}",
            "sendBody": True,
            "contentType": "raw",
            "rawContentType": "text/plain",
            "body": body_expr,
            "options": {
                "headers": {
                    "values": [
                        {"name": "Title",    "value": title_expr},
                        {"name": "Priority", "value": priority},
                        {"name": "Tags",     "value": "legal"},
                    ]
                }
            },
        },
    }


def build() -> dict:
    with open(TEMPLATE, encoding="utf-8") as f:
        wf = json.load(f)

    nodes = wf["nodes"]
    conns = wf["connections"]

    # ── 1. Inject JS bodies + onError on risky nodes ─────────────────────────
    for n in nodes:
        if n["name"] in CODE_FILES:
            n["parameters"]["jsCode"] = (CODE_DIR / CODE_FILES[n["name"]]).read_text(encoding="utf-8").rstrip("\n")
        if n["name"] == "HTTP Request1":
            n["onError"] = "continueRegularOutput"
        if n["name"] == "Insert rows in a table2":
            n["onError"] = "continueRegularOutput"

    # ── 2. Add error-handling nodes ──────────────────────────────────────────
    if_pdf      = make_if_error_node("IF PDF Error",     1920,  80)
    if_extract  = make_if_error_node("IF Extract Error", 2600,  80)
    log_error   = make_log_error_node(2800, 280)
    notify_err  = make_notify_node(
        "Notify Error", "legal-errors",
        title_expr="={{ 'Ошибка: ' + ($json.stage || 'pipeline') }}",
        body_expr="={{ ($json.stage || '') + ': ' + ($json.message || '') + '\\nФайл: ' + ($json.source_filename || '') }}",
        priority="urgent", x=3040, y=280,
    )
    notify_ok = make_notify_node(
        "Notify Success", "legal-pipeline",
        title_expr="Документ обработан",
        body_expr="={{ ($json.source_filename || '') + ' — ' + ($json.document_type || 'unknown') }}",
        priority="low", x=2800, y=-240,
    )
    nodes.extend([if_pdf, if_extract, log_error, notify_err, notify_ok])

    # ── 3. Rewire connections around the new IF/Notify nodes ────────────────
    # PDF to Images → IF PDF Error → (error) Log Error / (ok) HTTP Request1
    conns["PDF to Images"]["main"][0] = [{"node": "IF PDF Error", "type": "main", "index": 0}]
    conns["IF PDF Error"] = {"main": [
        [{"node": "Log Error",     "type": "main", "index": 0}],
        [{"node": "HTTP Request1", "type": "main", "index": 0}],
    ]}

    # Extract Fields → IF Extract Error → (error) Log Error / (ok) Notify Success
    conns["Extract Fields"]["main"][0] = [{"node": "IF Extract Error", "type": "main", "index": 0}]
    conns["IF Extract Error"] = {"main": [
        [{"node": "Log Error",      "type": "main", "index": 0}],
        [{"node": "Notify Success", "type": "main", "index": 0}],
    ]}

    # Notify Success → Insert rows in a table2 (documents)
    conns["Notify Success"] = {"main": [
        [{"node": "Insert rows in a table2", "type": "main", "index": 0}],
    ]}

    # Log Error → Notify Error (dead-end, does not rejoin the main loop)
    conns["Log Error"] = {"main": [
        [{"node": "Notify Error", "type": "main", "index": 0}],
    ]}

    return wf


def main() -> None:
    wf = build()
    # Файл должен оставаться валидным JSON (иначе n8n не сможет его импортировать),
    # поэтому пояснение "сгенерировано, не редактировать руками" — только в докстринге
    # этого скрипта и в README, а не внутри самого JSON.
    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(wf, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"✓ {OUTPUT} written ({len(wf['nodes'])} nodes)")


if __name__ == "__main__":
    main()
