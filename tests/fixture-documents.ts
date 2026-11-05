/** Small, synthetic documents for parser and upload tests. No candidate data. */
export function pdfFixture(): Buffer {
  const content = "BT /F1 12 Tf 72 720 Td (Resume TypeScript React project improved performance 40 percent.) Tj ET";
  const objects = ["<< /Type /Catalog /Pages 2 0 R >>", "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>", `<< /Length ${content.length} >>\nstream\n${content}\nendstream`];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${index + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 6\n0000000000 65535 f \n${offsets.slice(1).map((offset) => `${offset.toString().padStart(10, "0")} 00000 n \n`).join("")}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(pdf);
}

function crc32(data: Buffer): number {
  let crc = 0xffffffff;
  for (const byte of data) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
  }
  return (crc ^ 0xffffffff) >>> 0;
}

export function docxFixture(text = "技能：TypeScript、React。项目：我主导前端重构，负责核心组件，性能提升40%。"): Buffer {
  const files: [string, string][] = [
    ["[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>'],
    ["_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>'],
    ["word/document.xml", `<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>${text.replace(/&/g, "&amp;").replace(/</g, "&lt;")}</w:t></w:r></w:p></w:body></w:document>`],
  ];
  const local: Buffer[] = [], central: Buffer[] = [];
  let offset = 0;
  for (const [name, content] of files) {
    const fileName = Buffer.from(name), data = Buffer.from(content), crc = crc32(data);
    const header = Buffer.alloc(30); header.writeUInt32LE(0x04034b50); header.writeUInt16LE(20, 4);
    header.writeUInt32LE(crc, 14); header.writeUInt32LE(data.length, 18); header.writeUInt32LE(data.length, 22); header.writeUInt16LE(fileName.length, 26);
    local.push(header, fileName, data);
    const index = Buffer.alloc(46); index.writeUInt32LE(0x02014b50); index.writeUInt16LE(20, 4); index.writeUInt16LE(20, 6);
    index.writeUInt32LE(crc, 16); index.writeUInt32LE(data.length, 20); index.writeUInt32LE(data.length, 24); index.writeUInt16LE(fileName.length, 28); index.writeUInt32LE(offset, 42);
    central.push(index, fileName); offset += header.length + fileName.length + data.length;
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50);
  end.writeUInt16LE(files.length, 8); end.writeUInt16LE(files.length, 10); end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, directory, end]);
}
