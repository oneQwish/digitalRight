const crypto = require('crypto');
const fs = require('fs');

// Считаем хэш точно так же, как позже "PDF to Images" (sha256(fileName + реальный
// размер в байтах, из fs.statSync)). Раньше этот шаг делала встроенная нода
// n8n Crypto: она хэшировала fileName + $json.fileSize, а fileSize у
// Read/Write Files from Disk — отформатированная строка вида "1.42 kB", а не
// число байт. В итоге хэш из дедуп-проверки никогда не совпадал с тем, что
// реально лежит в file_hashes (он строился по числу байт) — дедупликация не
// работала ни разу, каждый запуск перерабатывал весь inbox/ заново.
return $input.all().map(item => {
  const fileName = item.json.fileName;
  const filePath = `/home/node/.n8n-files/lawyer_inbox/${fileName}`;
  const fileSize = fs.statSync(filePath).size;
  const name_hash = crypto.createHash('sha256').update(fileName + String(fileSize)).digest('hex');
  return { json: { ...item.json, name_hash } };
});
