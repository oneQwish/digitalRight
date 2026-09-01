"""
Read `Suds - TDSheet.csv` (1С counterparties export) and write SQL to stdout
that seeds the `courts` table in legal_db.

Usage:
    python3 db/import_courts.py | docker exec -i legal-postgres psql -U oneqwish -d legal_db

Idempotent: rows with yurait_id are upserted; rows without yurait_id are
inserted only when no court with the same name already exists.
"""

import csv
import re
import sys
from pathlib import Path

CSV_PATH = Path(__file__).parent.parent / "data" / "Suds - TDSheet.csv"

# Bailiff offices share the word "суд" — exclude them by abbreviation or keyword
BAILIFF_RE = re.compile(
    r"пристав|ФССП|УФССП|РОСП|МОСП|ГОСП|РПСП|ОУПД|ОУПДС|СОСП"
    r"|реестр.*юридических лиц"          # FSSSP debt-collector registry dept
    r"|порядка деятельности судов",       # bailiff "order in courts" units
    re.I,
)
# Name must start or contain an explicit court-type phrase,
# not merely "суд" as part of a city/district name (Судак, Суджанский, etc.)
COURT_RE = re.compile(
    r"(?:арбитражный|районный|городской|областной|краевой|окружной"
    r"|апелляционный|кассационный|мировой|военный|верховный)\s+суд"
    r"|судебный\s+участок"
    r"|(?:^|,\s*)суд\b",   # standalone word "суд" at line start or after comma
    re.I,
)


def infer_court_type(name: str) -> str | None:
    n = name.lower()
    if "кассационный" in n:
        return "кассационный"
    if "апелляционный" in n:
        return "апелляционный"
    if "арбитражный" in n:
        return "арбитражный"
    if "верховный" in n:
        return "верховный"
    if "областной" in n or "краевой" in n:
        return "областной"
    if "районный" in n or "городской" in n:
        return "районный"
    if "судебный участок" in n or "мировой" in n:
        return "мировой"
    if "военный" in n:
        return "военный"
    return None


def csv_field(s: str | None) -> str:
    if s is None:
        return r"\N"  # unquoted \N → psql COPY CSV NULL token
    escaped = s.replace("\\", "\\\\").replace('"', '""')
    return f'"{escaped}"'


def collect_courts() -> list[tuple[str | None, str, str | None]]:
    rows: list[tuple[str | None, str, str | None]] = []
    seen_ids: set[str] = set()
    seen_names: set[str] = set()
    with open(CSV_PATH, newline="", encoding="utf-8") as fh:
        reader = csv.reader(fh)
        next(reader)  # skip header
        for row in reader:
            if len(row) < 3:
                continue
            code  = row[0].strip()
            name  = row[1].strip()
            etype = row[2].strip()
            inn   = row[3].strip() if len(row) > 3 else ""

            if etype != "Юр. лицо":
                continue
            if inn:
                continue
            if not COURT_RE.search(name):
                continue
            if BAILIFF_RE.search(name):
                continue

            yurait_id = code if code else None
            if yurait_id:
                if yurait_id in seen_ids:
                    continue
                seen_ids.add(yurait_id)
            else:
                if name in seen_names:
                    continue
                seen_names.add(name)

            rows.append((yurait_id, name, infer_court_type(name)))
    return rows


def main() -> None:
    rows = collect_courts()

    out = sys.stdout
    out.write("BEGIN;\n\n")
    out.write(
        "CREATE TEMP TABLE courts_import (\n"
        "    yurait_id  TEXT,\n"
        "    name       TEXT NOT NULL,\n"
        "    court_type TEXT\n"
        ");\n\n"
    )
    out.write("COPY courts_import (yurait_id, name, court_type) FROM STDIN CSV NULL '\\N';\n")
    for yurait_id, name, court_type in rows:
        out.write(",".join(csv_field(f) for f in (yurait_id, name, court_type)) + "\n")
    out.write("\\.\n\n")

    out.write(
        "INSERT INTO courts (yurait_id, name, court_type)\n"
        "SELECT yurait_id, name, court_type FROM courts_import\n"
        "WHERE yurait_id IS NOT NULL\n"
        "ON CONFLICT (yurait_id) DO UPDATE\n"
        "    SET name = EXCLUDED.name,\n"
        "        court_type = EXCLUDED.court_type;\n\n"
    )
    out.write(
        "INSERT INTO courts (name, court_type)\n"
        "SELECT ci.name, ci.court_type\n"
        "FROM courts_import ci\n"
        "WHERE ci.yurait_id IS NULL\n"
        "  AND NOT EXISTS (SELECT 1 FROM courts c WHERE c.name = ci.name);\n\n"
    )
    out.write("COMMIT;\n")

    print(f"-- {len(rows)} courts written", file=sys.stderr)


if __name__ == "__main__":
    main()
