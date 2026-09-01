const fs = require('fs');

let fileName = 'unknown';
try {
  const items    = $input.all();
  const pdfItems = $('PDF to Images').all();

  const firstMeta = pdfItems[0]?.json ?? {};
  fileName        = firstMeta.sourceFile || '';
  const tmpDir    = firstMeta.tmpDir     || '';
  const nameHash  = firstMeta.name_hash  || '';

  // Split OCR results into successful and failed pages
  const okItems  = items.filter(i => !i.json.error && !i.json._error);
  const badItems = items.filter(i =>  i.json.error ||  i.json._error);

  if (okItems.length === 0) {
    if (tmpDir.startsWith('/tmp/')) {
      try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
    }
    throw new Error(`OCR провалился на всех ${items.length} страниц(е/ах)`);
  }

  const sorted = okItems.map((item, i) => ({
    ocrJson: item.json,
    page: pdfItems[i]?.json?.page ?? (i + 1),
  })).sort((a, b) => a.page - b.page);

  const fullText = sorted
    .map(pair => (pair.ocrJson.text ?? pair.ocrJson.body?.text ?? '').trim())
    .filter(t => t.length > 0)
    .join('\n\n');

  if (tmpDir.startsWith('/tmp/')) {
    try { fs.rmSync(tmpDir, { recursive: true, force: true }); } catch (_) {}
  }

  const dateMatch  = fileName.match(/^(\d{4}-\d{2}-\d{2})/);
  const receivedAt = dateMatch ? dateMatch[1] : null;

  const fl = fileName.toLowerCase();
  let documentType = 'прочее';
  if      (fl.includes('решени'))     documentType = 'решение';
  else if (fl.includes('апелляц'))    documentType = 'апелляция';
  else if (fl.includes('определени')) documentType = 'определение';
  else if (fl.includes('кассац'))     documentType = 'кассация';
  else if (fl.includes('иск'))        documentType = 'иск';

  return [{
    json: {
      document_type:       documentType,
      source_filename:     fileName,
      raw_text:            fullText,
      received_at:         receivedAt,
      total_pages:         pdfItems.length,
      name_hash:           nameHash,
      _ocr_partial:        badItems.length > 0,
      _ocr_failed_pages:   badItems.length,
    }
  }];

} catch (e) {
  return [{ json: { _error: true, stage: 'aggregate_text', message: e.message, source_filename: fileName } }];
}
