const FOLDER_ID = '1H6XpCOQC1TOmjrqhvgdn63So8XxSOuC5';
const SECRET_TOKEN = 'Ulzdc5gG18YLMASwWNGJvg';

function doGet(e) {
  return HtmlService.createHtmlOutputFromFile('index')
    .setTitle('領収書スキャン')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1.0, maximum-scale=1.0');
}

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    if (body.token !== SECRET_TOKEN) return makeResponse({ error: 'Unauthorized' });

    if (body.action === 'getFolders') {
      return makeResponse(getFolders());
    }

    return makeResponse(uploadReceipt(body.image, body.mimeType, body.filename, body.folderId));
  } catch (err) {
    return makeResponse({ success: false, error: err.toString() });
  }
}

function uploadReceipt(base64Image, mimeType, filename, folderId) {
  try {
    const name = filename || buildFilenameFromNow('.jpg');
    const targetFolderId = folderId || FOLDER_ID;
    const decoded = Utilities.base64Decode(base64Image);
    const blob = Utilities.newBlob(decoded, mimeType, name);
    const folder = DriveApp.getFolderById(targetFolderId);
    const file = folder.createFile(blob);
    return { success: true, url: file.getUrl(), name: file.getName() };
  } catch (err) {
    return { success: false, error: err.toString() };
  }
}

function getFolders() {
  const target = DriveApp.getFolderById(FOLDER_ID);
  const parents = target.getParents();
  const result = [];

  if (parents.hasNext()) {
    const parent = parents.next();
    const siblings = parent.getFolders();
    while (siblings.hasNext()) {
      const f = siblings.next();
      result.push({ id: f.getId(), name: f.getName(), isCurrent: f.getId() === FOLDER_ID });
    }
    result.sort((a, b) => a.name.localeCompare(b.name, 'ja'));
  } else {
    result.push({ id: FOLDER_ID, name: target.getName(), isCurrent: true });
  }

  return result;
}

function buildFilenameFromNow(ext) {
  const now = new Date();
  return Utilities.formatDate(now, 'Asia/Tokyo', 'yyyyMMdd_HHmm') + '_receipt' + ext;
}

function makeResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
