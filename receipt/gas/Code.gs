// 秘密（FOLDER_ID, APP_PIN）は Secrets.gs（git 管理外）で定義する。雛形は Secrets.gs.example。
//
// 防御の考え方: このアプリのURLは公開ページに載っている（家族が設定なしで使えるようにするため）。
// そのため、守りは「推測できない長さのPIN」と「PINを外したときの待ち時間」に一本化している。
// トークンは使わない（公開されても意味がないため）。

const MAX_BASE64_LENGTH = 14 * 1024 * 1024;   // 約10MBの画像まで
const FAIL_DELAY_MS = 3000;                    // PINを間違えたら、返事を3秒遅らせる（総当たりを非現実的にする）

function doPost(e) {
  try {
    const body = JSON.parse(e.postData.contents);

    if (!isPinValid(body.pin)) {
      Utilities.sleep(FAIL_DELAY_MS);
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
    return makeResponse({ success: false, error: String(err) });
  }
}

// 比較は全桁を見る（途中で打ち切らない）
function isPinValid(pin) {
  const given = String(pin == null ? '' : pin);
  const correct = String(APP_PIN);
  let diff = given.length ^ correct.length;
  for (let i = 0; i < correct.length; i++) {
    diff |= (given.charCodeAt(i) || 0) ^ correct.charCodeAt(i);
  }
  return diff === 0;
}

// 保存先として許可するフォルダ: getFolders() が返す一覧（MICAREとその兄弟、直下のサブフォルダ）だけ
function allowedFolderIds() {
  const cache = CacheService.getScriptCache();
  const cached = cache.get('allowedFolderIds');
  if (cached) return JSON.parse(cached);
  const ids = getFolders().map(function (f) { return f.id; });
  cache.put('allowedFolderIds', JSON.stringify(ids), 300);
  return ids;
}

function isAllowedFolder(id) {
  return allowedFolderIds().indexOf(id) !== -1;
}

function uploadReceipt(base64Image, mimeType, filename, folderId) {
  try {
    if (typeof base64Image !== 'string' || !base64Image || base64Image.length > MAX_BASE64_LENGTH) {
      return { success: false, error: 'invalid image' };
    }
    if (!/^image\/(jpe?g|png|webp|heic|heif|gif)$/i.test(String(mimeType))) {
      return { success: false, error: 'invalid mimeType' };
    }
    const targetFolderId = folderId || FOLDER_ID;
    if (!isAllowedFolder(targetFolderId)) {
      return { success: false, error: 'folder not allowed' };
    }
    const name = String(filename || buildFilenameFromNow('.jpg')).replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_').slice(0, 120);
    const decoded = Utilities.base64Decode(base64Image);
    const blob = Utilities.newBlob(decoded, mimeType, name);
    const folder = DriveApp.getFolderById(targetFolderId);
    const file = folder.createFile(blob);
    return { success: true, url: file.getUrl(), name: file.getName() };
  } catch (err) {
    return { success: false, error: String(err) };
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
    const folderName = String(name || '').trim().slice(0, 100);
    if (!folderName) return { success: false, error: 'name required' };

    // parentId 指定があれば（許可された一覧の中のみ）その中に、なければ最上位（MICAREと同じ階層）に作成
    let parent;
    if (parentId) {
      if (!isAllowedFolder(parentId)) return { success: false, error: 'folder not allowed' };
      parent = DriveApp.getFolderById(parentId);
    } else {
      const base = DriveApp.getFolderById(FOLDER_ID);
      const ps = base.getParents();
      parent = ps.hasNext() ? ps.next() : base;
    }

    // 同名フォルダがあれば再利用（重複作成を防ぐ）
    const existing = parent.getFoldersByName(folderName);
    const folder = existing.hasNext() ? existing.next() : parent.createFolder(folderName);

    // 新しいフォルダを許可一覧に反映させる
    CacheService.getScriptCache().remove('allowedFolderIds');

    return { success: true, id: folder.getId(), name: folder.getName(), parentId: parent.getId(), parentName: parent.getName() };
  } catch (err) {
    return { success: false, error: String(err) };
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
