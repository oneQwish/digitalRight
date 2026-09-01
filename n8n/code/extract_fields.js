let _source_filename = 'unknown';
try {

// ── Regex-экстрактор полей для российских судебных документов ────────────────
// Важно: \w в JS не матчит кириллицу — везде используем явные диапазоны [а-яёА-ЯЁ]

const items = $input.all();

const MONTHS = {
  'января':1,'февраля':2,'марта':3,'апреля':4,'мая':5,'июня':6,
  'июля':7,'августа':8,'сентября':9,'октября':10,'ноября':11,'декабря':12,
};

function firstMatch(text, patterns) {
  for (const { re, score } of patterns) {
    const m = text.match(re);
    if (m) {
      const val = (m[1] ?? m[0]).trim().replace(/\s{2,}/g, ' ');
      if (val) return { value: val, score };
    }
  }
  return { value: null, score: 0 };
}

function extractFields(raw) {
  const text = raw || '';
  const head = text.slice(0, 600);

  const docType = (() => {
    const h = head.toUpperCase().replace(/\s+/g, ' ');
    if (/АПЕЛЛЯЦИОННОЕ ОПРЕДЕЛЕНИЕ/.test(h))  return { value: 'апелляция',   score: 0.97 };
    if (/КАССАЦИОННОЕ ОПРЕДЕЛЕНИЕ/.test(h))   return { value: 'кассация',    score: 0.97 };
    if (/АПЕЛЛЯЦИОННОЕ РЕШЕНИЕ/.test(h))      return { value: 'апелляция',   score: 0.95 };
    if (/ИСКОВОЕ ЗАЯВЛЕНИЕ/.test(h))          return { value: 'иск',         score: 0.97 };
    if (/ПРЕТЕНЗИЯ/.test(h))                  return { value: 'претензия',   score: 0.95 };
    if (/Р\s*Е\s*Ш\s*Е\s*Н\s*И\s*Е/.test(h) || /\bРЕШЕНИЕ\b/.test(h))
                                              return { value: 'решение',     score: 0.95 };
    if (/О\s*П\s*Р\s*Е\s*Д\s*Е\s*Л\s*Е\s*Н\s*И\s*Е/.test(h) || /\bОПРЕДЕЛЕНИЕ\b/.test(h))
                                              return { value: 'определение', score: 0.95 };
    return { value: null, score: 0 };
  })();

  const caseNumber = firstMatch(text, [
    { re: /(?:дело|Дело)\s*№?\s*([АA]?\d{1,2}[-–]\d{3,7}[\/\-]\d{2,4})/i, score: 0.96 },
    { re: /\b([АA]\d{2}[-–]\d{3,7}[\/\-]\d{2,4})\b/,                       score: 0.93 },
    { re: /\b(\d{1,2}[-–]\d{3,7}[\/\-]\d{4})\b/,                           score: 0.88 },
  ]);

  const decisionDate = (() => {
    const re = /«?(\d{1,2})»?\s+(января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)\s+(\d{4})/i;
    const m  = text.match(re);
    if (m) {
      const mon = MONTHS[m[2].toLowerCase()];
      const iso = `${m[3]}-${String(mon).padStart(2,'0')}-${String(m[1]).padStart(2,'0')}`;
      return { value: iso, score: 0.96 };
    }
    return { value: null, score: 0 };
  })();

  const FIO_RU  = '[А-ЯЁ][а-яё]{2,}\\s+[А-ЯЁ]\\.[А-ЯЁ]\\.';
  const IO_FAM  = '[А-ЯЁ]\\.[А-ЯЁ]\\.\\s+[А-ЯЁ][а-яё]{2,}';
  const PRED    = 'председательствующ[а-яё]+\\s+судьи?';
  const SOSTAV  = 'в\\s+составе\\s+судьи?';
  const SUDYA   = '(?:^|\\n)\\s*[Сс]удья\\s+';

  const judgeName = firstMatch(text, [
    { re: new RegExp(`(?:${PRED}|${SOSTAV})\\s+(${FIO_RU})`),  score: 0.93 },
    { re: new RegExp(`(?:${PRED}|${SOSTAV})\\s+(${IO_FAM})`),  score: 0.93 },
    { re: new RegExp(`${SUDYA}(${FIO_RU})`, 'm'),               score: 0.90 },
    { re: new RegExp(`${SUDYA}(${IO_FAM})`, 'm'),               score: 0.90 },
    { re: /[Сс]удьи?\s*:?\s+([А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ]\.[А-ЯЁ]\.)/i, score: 0.83 },
    { re: /[Сс]удьи?\s*:?\s+([А-ЯЁ]\.[А-ЯЁ]\.\s+[А-ЯЁ][а-яё]{2,})/i, score: 0.83 },
  ]);

  const courtName = firstMatch(head, [
    { re: /([А-ЯЁ][а-яёА-ЯЁ\s\-]+?(?:районный|городской|арбитражный|апелляционный|кассационный)\s+суд(?:\s+(?:города?|г\.)\s+[А-ЯЁ][а-яё]+)?)/i, score: 0.82 },
  ]);

  const plaintiff = firstMatch(text, [
    { re: /(?:^|\n)\s*[Ии]стец[ыеуа]?\s*:?\s+([^\n,;]{5,120})/m, score: 0.82 },
    { re: /по\s+иску\s+([^,\n]{5,80}?)\s+к\s+/i,                 score: 0.74 },
  ]);
  const defendant = firstMatch(text, [
    { re: /(?:^|\n)\s*[Оо]тветчик[иа]?\s*:?\s+([^\n,;]{5,120})/m, score: 0.82 },
  ]);

  const amounts = (() => {
    const isSolidary = /солидарно/i.test(text);
    const normalize  = s => parseFloat(s.replace(/\s/g, '').replace(',', '.'));
    const re = /взыскать[^.;]{0,400}?([\d][\d\s]{1,15}(?:,\d{1,2})?)\s*(?:рублей|рубля|руб\.)/gi;
    const found = [];
    let m;
    while ((m = re.exec(text)) !== null) {
      const v = normalize(m[1]);
      if (!isNaN(v) && v > 0 && v < 1e10) found.push(v);
    }
    if (!found.length) return { value: null, total: null, is_solidary: isSolidary, score: 0 };
    const unique = [...new Set(found)];
    const total  = isSolidary ? Math.max(...unique) : unique.reduce((a, b) => a + b, 0);
    const score  = isSolidary         ? 0.52
                 : unique.length === 1 ? 0.78
                 :                       0.55;
    return { value: unique, total, is_solidary: isSolidary, score };
  })();

  const extracted_data = {
    case_number:         caseNumber.value,
    decision_date:       decisionDate.value,
    judge_name:          judgeName.value,
    court_name:          courtName.value,
    plaintiff:           plaintiff.value,
    defendant:           defendant.value,
    awarded_amounts_raw: amounts.value,
    awarded_total:       amounts.total,
    is_solidary:         amounts.is_solidary,
  };

  const extraction_confidence = {
    document_type: { value: docType.value,     score: docType.score,     method: 'regex' },
    case_number:   { value: caseNumber.value,  score: caseNumber.score,  method: 'regex' },
    decision_date: { value: decisionDate.value,score: decisionDate.score, method: 'regex' },
    judge_name:    { value: judgeName.value,   score: judgeName.score,   method: 'regex' },
    court_name:    { value: courtName.value,   score: courtName.score,   method: 'regex' },
    plaintiff:     { value: plaintiff.value,   score: plaintiff.score,   method: 'regex' },
    defendant:     { value: defendant.value,   score: defendant.score,   method: 'regex' },
    awarded_total: { value: amounts.total,     score: amounts.score,     method: 'regex' },
  };

  return { extracted_data, extraction_confidence, docType };
}

const result = items.map(item => {
  _source_filename = item.json.source_filename || 'unknown';
  const { extracted_data, extraction_confidence, docType } = extractFields(item.json.raw_text);
  const document_type = (docType.score >= 0.94)
    ? docType.value
    : (item.json.document_type || 'прочее');
  return { json: { ...item.json, document_type, extracted_data, extraction_confidence } };
});
return result;

} catch (e) {
  return [{ json: { _error: true, stage: 'extract_fields', message: e.message, source_filename: _source_filename } }];
}
