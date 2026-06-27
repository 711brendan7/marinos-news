const BOOKS_SHEET = 'Books';
const PAGES_SHEET = 'Pages';
const DRIVE_FOLDER = 'BookReader';

// GAS エディタで一度だけ実行してトークンを設定する
function initialSetup() {
  const props = PropertiesService.getScriptProperties();
  props.setProperty('TOKEN', 'E9mGkYlHqwpBwBqYMV5s_7BZIiNT1rqP');
  Logger.log('TOKEN を設定しました: ' + props.getProperty('TOKEN'));
}

function getToken() {
  return PropertiesService.getScriptProperties().getProperty('TOKEN');
}

function auth(params) {
  return params.token === getToken();
}

function authBody(body) {
  return body && body.token === getToken();
}

function ok(data) {
  return ContentService.createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}

// ── GET ──────────────────────────────────────────────────────────────
function doGet(e) {
  const p = e.parameter;

  if (!auth(p)) return ok({ error: 'unauthorized' });

  if (p.action === 'listBooks')  return ok(listBooks());
  if (p.action === 'listPages')  return ok(listPages(p.bookId));
  if (p.action === 'getPage')    return ok(getPage(p.pageId));
  if (p.action === 'deleteBook') return ok(deleteBook(p.bookId));
  if (p.action === 'deletePage') return ok(deletePage(p.pageId));
  if (p.action === 'transcribe') return ok(transcribePage(p.pageId));
  if (p.action === 'addBook')    return ok(addBook({ title: p.title, author: p.author, notes: p.notes }));
  if (p.action === 'editBook')   return ok(editBook({ bookId: p.bookId, title: p.title, author: p.author, notes: p.notes }));

  return ok({ error: 'unknown action' });
}

// ── POST ─────────────────────────────────────────────────────────────
function doPost(e) {
  let body;
  try { body = JSON.parse(e.postData.contents); } catch (_) { return ok({ error: 'invalid json' }); }
  if (!authBody(body)) return ok({ error: 'unauthorized' });

  if (body.action === 'addBook')  return ok(addBook(body));
  if (body.action === 'addPage')  return ok(addPage(body));
  if (body.action === 'editBook') return ok(editBook(body));

  return ok({ error: 'unknown action' });
}

// ── Folder / Sheet helpers ───────────────────────────────────────────
function getFolder() {
  const it = DriveApp.getFoldersByName(DRIVE_FOLDER);
  return it.hasNext() ? it.next() : DriveApp.createFolder(DRIVE_FOLDER);
}

function getSheet(name) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sh = ss.getSheetByName(name);
  if (sh) return sh;
  sh = ss.insertSheet(name);
  if (name === BOOKS_SHEET) sh.appendRow(['id','title','author','created','cover_file_id','cover_url','notes']);
  if (name === PAGES_SHEET) sh.appendRow(['id','book_id','page_num','file_id','image_url','transcript','created']);
  return sh;
}

// ── Books ────────────────────────────────────────────────────────────
function listBooks() {
  const rows = getSheet(BOOKS_SHEET).getDataRange().getValues();
  const books = [];
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    if (!r[0]) continue;
    books.push({ id: r[0], title: r[1], author: r[2], created: r[3], cover_url: r[5], notes: r[6] });
  }
  books.sort((a, b) => new Date(b.created) - new Date(a.created));
  return { books };
}

function addBook(body) {
  const id = Utilities.getUuid();
  const now = new Date().toISOString();
  let coverFileId = '', coverUrl = '';

  if (body.coverBase64) {
    const folder = getFolder();
    const blob = Utilities.newBlob(
      Utilities.base64Decode(body.coverBase64),
      body.coverMime || 'image/jpeg',
      `${id}_cover.jpg`
    );
    const f = folder.createFile(blob);
    f.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    coverFileId = f.getId();
    coverUrl = `https://drive.google.com/thumbnail?id=${coverFileId}&sz=w400`;
  }

  getSheet(BOOKS_SHEET).appendRow([id, body.title || '無題', body.author || '', now, coverFileId, coverUrl, body.notes || '']);
  return { success: true, bookId: id };
}

function editBook(body) {
  const sh = getSheet(BOOKS_SHEET);
  const rows = sh.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (rows[i][0] === body.bookId) {
      if (body.title  !== undefined) sh.getRange(i + 1, 2).setValue(body.title);
      if (body.author !== undefined) sh.getRange(i + 1, 3).setValue(body.author);
      if (body.notes  !== undefined) sh.getRange(i + 1, 7).setValue(body.notes);
      return { success: true };
    }
  }
  return { error: 'not found' };
}

function deleteBook(bookId) {
  const psh = getSheet(PAGES_SHEET);
  const prows = psh.getDataRange().getValues();
  const toDelete = [];
  for (let i = prows.length - 1; i >= 1; i--) {
    if (prows[i][1] === bookId) {
      toDelete.push(i + 1);
      tryTrash(prows[i][3]);
    }
  }
  toDelete.forEach(r => psh.deleteRow(r));

  const bsh = getSheet(BOOKS_SHEET);
  const brows = bsh.getDataRange().getValues();
  for (let i = 1; i < brows.length; i++) {
    if (brows[i][0] === bookId) {
      tryTrash(brows[i][4]);
      bsh.deleteRow(i + 1);
      break;
    }
  }
  return { success: true };
}

function findOrCreateBookId(title, author) {
  const sh = getSheet(BOOKS_SHEET);
  const rows = sh.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (rows[i][1] === title) return rows[i][0];
  }
  return addBook({ title, author: author || '' }).bookId;
}

// ── Pages ────────────────────────────────────────────────────────────
function listPages(bookId) {
  const rows = getSheet(PAGES_SHEET).getDataRange().getValues();
  const pages = [];
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    if (!r[0] || r[1] !== bookId) continue;
    pages.push({ id: r[0], book_id: r[1], page_num: r[2], image_url: r[4], transcript: r[5], created: r[6] });
  }
  pages.sort((a, b) => a.page_num - b.page_num);
  return { pages };
}

function getPage(pageId) {
  const rows = getSheet(PAGES_SHEET).getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    const r = rows[i];
    if (r[0] === pageId) return { id: r[0], book_id: r[1], page_num: r[2], file_id: r[3], image_url: r[4], transcript: r[5], created: r[6] };
  }
  return { error: 'not found' };
}

function addPage(body) {
  if (!body.imageBase64) return { error: 'imageBase64 required' };

  const bookId = body.bookId || findOrCreateBookId(body.title || '無題', body.author);
  const id = Utilities.getUuid();
  const now = new Date().toISOString();
  const folder = getFolder();

  const blob = Utilities.newBlob(
    Utilities.base64Decode(body.imageBase64),
    body.imageMime || 'image/jpeg',
    `${id}_page.jpg`
  );
  const f = folder.createFile(blob);
  f.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  const fileId = f.getId();
  const imageUrl = `https://drive.google.com/thumbnail?id=${fileId}&sz=w800`;

  // OCR (requires Drive Advanced Service enabled)
  let transcript = '';
  if (body.ocr !== false) {
    transcript = runOcr(blob, id, body.ocrLanguage || 'ja');
  }

  const sh = getSheet(PAGES_SHEET);
  const rows = sh.getDataRange().getValues();
  let maxPageNum = 0;
  for (let i = 1; i < rows.length; i++) {
    if (rows[i][1] === bookId && rows[i][2] > maxPageNum) maxPageNum = rows[i][2];
  }
  const pageNum = body.pageNum || (maxPageNum + 1);

  sh.appendRow([id, bookId, pageNum, fileId, imageUrl, transcript, now]);
  return { success: true, pageId: id, bookId, transcript };
}

function deletePage(pageId) {
  const sh = getSheet(PAGES_SHEET);
  const rows = sh.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (rows[i][0] === pageId) {
      tryTrash(rows[i][3]);
      sh.deleteRow(i + 1);
      return { success: true };
    }
  }
  return { error: 'not found' };
}

function runOcr(blob, id, lang) {
  try {
    const resource = { title: `${id}_ocr`, mimeType: 'application/vnd.google-apps.document' };
    const ocrFile = Drive.Files.insert(resource, blob, { ocr: true, ocrLanguage: lang || 'ja' });
    const docId = ocrFile.getId();
    const exportUrl = `https://docs.google.com/feeds/download/documents/export/Export?id=${docId}&exportFormat=txt`;
    const text = UrlFetchApp.fetch(exportUrl, {
      headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() }
    }).getContentText('UTF-8').trim();
    DriveApp.getFileById(docId).setTrashed(true);
    return text;
  } catch (err) {
    Logger.log('OCR error: ' + err);
    return '';
  }
}

function transcribePage(pageId) {
  const sh = getSheet(PAGES_SHEET);
  const rows = sh.getDataRange().getValues();
  for (let i = 1; i < rows.length; i++) {
    if (rows[i][0] === pageId) {
      const fileId = rows[i][3];
      try {
        const blob = DriveApp.getFileById(fileId).getBlob();
        const transcript = runOcr(blob, pageId, 'ja');
        sh.getRange(i + 1, 6).setValue(transcript);
        return { success: true, transcript };
      } catch (err) {
        return { error: err.toString() };
      }
    }
  }
  return { error: 'not found' };
}

function tryTrash(fileId) {
  if (!fileId) return;
  try { DriveApp.getFileById(fileId).setTrashed(true); } catch (_) {}
}
