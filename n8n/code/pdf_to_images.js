const { execFileSync } = require('child_process');
const fs = require('fs');
const crypto = require('crypto');

let fileName = 'unknown';
try {
  const item = $input.first();
  const binaryKey = Object.keys(item.binary)[0];
  const bin = item.binary[binaryKey];
  fileName = bin.fileName;

  if (!fileName) throw new Error('bin.fileName пустой');
  const pdfPath = `/home/node/.n8n-files/lawyer_inbox/${fileName}`;
  if (!fs.existsSync(pdfPath)) throw new Error(`PDF не найден: ${pdfPath}`);

  const fileSize = fs.statSync(pdfPath).size;
  const nameHash = crypto.createHash('sha256')
    .update(fileName + String(fileSize))
    .digest('hex');

  const shortHash = crypto.createHash('sha1').update(fileName).digest('hex').slice(0, 10);
  const tmpDir = `/tmp/n8n_pdf_${shortHash}`;
  const pagePrefix = `${tmpDir}/page`;

  if (fs.existsSync(tmpDir)) fs.rmSync(tmpDir, { recursive: true, force: true });
  fs.mkdirSync(tmpDir);

  try {
    execFileSync('pdftoppm', ['-r', '150', '-png', pdfPath, pagePrefix], { timeout: 300_000 });
  } catch (err) {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    const stderr = err.stderr instanceof Buffer ? err.stderr.toString() : (err.stderr ?? err.message);
    throw new Error(`pdftoppm: ${stderr || err.message}`);
  }

  const pngFiles = fs.readdirSync(tmpDir).filter(f => f.endsWith('.png')).sort();
  if (pngFiles.length === 0) {
    fs.rmSync(tmpDir, { recursive: true, force: true });
    throw new Error('pdftoppm не создал ни одного PNG');
  }

  return pngFiles.map((filename, i) => ({
    json: { page: i + 1, totalPages: pngFiles.length, sourceFile: fileName, tmpDir, name_hash: nameHash },
    binary: {
      data: {
        data: fs.readFileSync(`${tmpDir}/${filename}`).toString('base64'),
        mimeType: 'image/png',
        fileName: filename,
      },
    },
  }));

} catch (e) {
  return [{ json: { _error: true, stage: 'pdf_to_images', message: e.message, source_filename: fileName } }];
}
