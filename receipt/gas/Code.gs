const FOLDER_ID = '1H6XpCOQC1TOmjrqhvgdn63So8XxSOuC5';
const SECRET_TOKEN = 'Ulzdc5gG18YLMASwWNGJvg';
const APP_PIN = '55238888';  // このPINを知っている人だけが保存できる（サーバー側で検証）

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);
    // トークン＋PINの両方が正しいときだけ許可（PINはクライアントに埋め込まない）
    if (body.token !== SECRET_TOKEN || String(body.pin) !== APP_PIN) {
      return makeResponse({ error: 'Unauthorized' });
    }

    if (body.action === 'getFolders') {
      return makeResponse(getFolders());
    }

    if (body.action === 'createFolder') {
      return makeResponse(createFolder(body.name, body.parentId));
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

  // 最上位（MICAREとその兄弟）を集める
  let topFolders = [];
  if (parents.hasNext()) {
    const parent = parents.next();
    const it = parent.getFolders();
    while (it.hasNext()) topFolders.push(it.next());
    topFolders.sort((a, b) => a.getName().localeCompare(b.getName(), 'ja'));
  } else {
    topFolders = [target];
  }

  // 各最上位フォルダと、その直下のサブフォルダ（depth=1）を並べる
  topFolders.forEach(function (f) {
    result.push({ id: f.getId(), name: f.getName(), isCurrent: f.getId() === FOLDER_ID, depth: 0 });
    const subs = [];
    const sit = f.getFolders();
    while (sit.hasNext()) subs.push(sit.next());
    subs.sort((a, b) => a.getName().localeCompare(b.getName(), 'ja'));
    subs.forEach(function (s) {
      result.push({ id: s.getId(), name: s.getName(), depth: 1, parent: f.getName() });
    });
  });

  return result;
}

function createFolder(name, parentId) {
  try {
    const folderName = (name || '').trim();
    if (!folderName) return { success: false, error: 'name required' };

    // parentId 指定があればその中に、なければ最上位（MICAREと同じ階層）に作成
    let parent;
    if (parentId) {
      parent = DriveApp.getFolderById(parentId);
    } else {
      const base = DriveApp.getFolderById(FOLDER_ID);
      const ps = base.getParents();
      parent = ps.hasNext() ? ps.next() : base;
    }

    // 同名フォルダがあれば再利用（重複作成を防ぐ）
    const existing = parent.getFoldersByName(folderName);
    const folder = existing.hasNext() ? existing.next() : parent.createFolder(folderName);

    return { success: true, id: folder.getId(), name: folder.getName(), parentId: parent.getId(), parentName: parent.getName() };
  } catch (err) {
    return { success: false, error: err.toString() };
  }
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
