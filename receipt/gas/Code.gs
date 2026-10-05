// 秘密（FOLDER_ID, APP_PIN）は Secrets.gs（git 管理外）で定義する。雛形は Secrets.gs.example。
//
// 防御の考え方: このアプリのURLは公開ページに載っている（家族が設定なしで使えるようにするため）。
// そのため、守りは「推測できない長さのPIN」と「PINを外したときの待ち時間」に一本化している。
// トークンは使わない（公開されても意味がないため）。

const MAX_BASE64_LENGTH = 14 * 1024 * 1024;   // 約10MBの画像まで
const FAIL_DELAY_MS = 3000;                    // PINを間違えたら、返事を3秒遅らせる（総当たりを非現実的にする）

// 保存の冪等化: クライアントが写真ごとに暗号学的乱数で作る識別ID（16進20桁=80bit）を保存名に含めて作成する。
// 作成の前に「このIDで、この保存先・保存名に作成を試みる」をスクリプトプロパティへ記録する（期限切れ・追い出しで消えない）。
// 記録を書けないときは作成しない。記録のあるIDは、保存先フォルダで同名ファイルを見つけるまで「未確認」と返し、
// 時間が経っても作り直さない（Driveの例外だけでは「作られていない」と証明できないため）。
// 記録は自動では消さない。容量（スクリプトプロパティ全体で500KB）が尽きたら作成せず「未確認」を返して止まる。
const REQUEST_ID_PATTERN = /^[0-9a-f]{20}$/;
const LOCK_WAIT_MS = 20000;                    // 同時送信はスクリプトロックで1件ずつ処理する
const UPLOAD_PROTOCOL = 2;                     // 応答に付ける版。クライアントはこの版の確認応答を得てから画像を送る
const RECORD_PREFIX = 'upload:';               // 試行記録のキー（upload:識別ID）

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

    if (body.action === 'checkUpload') {
      return makeResponse(checkUpload(body.requestId, body.folderId, body.filename));
    }

    return makeResponse(uploadReceipt(body.image, body.mimeType, body.filename, body.folderId, body.requestId));
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

// 写真の保存。返事の status:
//   'saved'       … Driveに保存済み（今回作成 or 同じIDで保存済みだったもの。duplicate で区別）
//   'rejected'    … 保存前の検査で拒否（この送信では何も作っていない）
//   'unconfirmed' … 保存できたか確認できない（未保存と断言しない。試行記録のあるIDは見つかるまで作り直さない）
// （'not_found' は checkUpload だけが返す: このIDの保存も作成の試みも無い＝画像を送ってよい）
function uploadReceipt(base64Image, mimeType, filename, folderId, requestId) {
  // requestId なし＝旧クライアント。照合はできないが従来どおり保存できるよう、ここでIDを作る
  const legacy = requestId == null || requestId === '';
  const rid = legacy ? newServerRequestId() : String(requestId).slice(0, 64);
  if (!REQUEST_ID_PATTERN.test(rid)) return rejectedResult(rid, 'invalid requestId');
  if (typeof base64Image !== 'string' || !base64Image || base64Image.length > MAX_BASE64_LENGTH) {
    return rejectedResult(rid, 'invalid image');
  }
  if (!/^image\/(jpe?g|png|webp|heic|heif|gif)$/i.test(String(mimeType))) {
    return rejectedResult(rid, 'invalid mimeType');
  }
  const targetFolderId = folderId || FOLDER_ID;
  try {
    if (!isAllowedFolder(targetFolderId)) return rejectedResult(rid, 'folder not allowed');
  } catch (err) {
    return unconfirmedResult(rid, 'folder check failed: ' + err);
  }
  const name = buildStoredName(filename || (legacy ? buildFilenameFromNow('.jpg') : 'receipt.jpg'), rid);
  let blob;
  try {
    blob = Utilities.newBlob(Utilities.base64Decode(base64Image), mimeType, name);
  } catch (err) {
    return rejectedResult(rid, 'invalid image');
  }

  let lock;
  try {
    lock = LockService.getScriptLock();
    if (!lock.tryLock(LOCK_WAIT_MS)) return unconfirmedResult(rid, 'busy (lock timeout)');
  } catch (err) {
    return unconfirmedResult(rid, 'lock failed: ' + err);
  }
  try {
    let rec;
    try {
      rec = readRecord(rid);
    } catch (err) {
      return unconfirmedResult(rid, 'record unreadable: ' + err);   // 読めない・壊れている＝試行済みかもしれない
    }
    if (rec && !isBoundTo(rec, targetFolderId, name)) return rejectedResult(rid, 'requestId is bound to another folder/name');
    let folder;
    let existing;
    try {
      folder = DriveApp.getFolderById(targetFolderId);
      existing = findSavedFile(folder, targetFolderId, name, rec);
    } catch (err) {
      return unconfirmedResult(rid, 'lookup failed: ' + err);
    }
    if (existing) return confirmSaved(rid, rec, targetFolderId, name, existing, true);
    // 記録がある＝以前このIDで作成を試みた。検索反映待ち・移動・削除の可能性があるので、見つかるまで作り直さない
    if (rec) return unconfirmedResult(rid, rec.state === 'saved' ? 'saved file not found in folder' : 'previous attempt unconfirmed');

    try {
      writeRecord(rid, { state: 'attempt', folderId: targetFolderId, name: name, fileId: '', ts: Date.now() });
    } catch (err) {
      return unconfirmedResult(rid, 'attempt record failed: ' + err);   // 記録できなければ作成しない
    }
    let file;
    try {
      file = folder.createFile(blob);
    } catch (err) {
      // 例外でも作成済みのことがある。もう一度照合し、見つからなければ「未確認」（試行記録が残るので以後も作り直さない）
      let again = null;
      try { again = findSavedFile(folder, targetFolderId, name, null); } catch (e2) { again = null; }
      if (again) return confirmSaved(rid, null, targetFolderId, name, again, false);
      return unconfirmedResult(rid, 'create failed: ' + err);
    }
    return confirmSaved(rid, null, targetFolderId, name, file, false);
  } finally {
    try { lock.releaseLock(); } catch (err) { /* 実行終了時に自動で解放される */ }
  }
}

// 読み取り専用の保存状態確認（Driveへの作成・変更も、記録の書き込みもしない）。
// クライアントは画像を送る前にこれを呼び、not_found（このIDの保存も作成の試みも無い）のときだけ画像を送る
function checkUpload(requestId, folderId, filename) {
  const rid = String(requestId == null ? '' : requestId).slice(0, 64);
  if (!REQUEST_ID_PATTERN.test(rid)) return rejectedResult(rid, 'invalid requestId');
  try {
    const targetFolderId = folderId || FOLDER_ID;
    if (!isAllowedFolder(targetFolderId)) return rejectedResult(rid, 'folder not allowed');
    const name = buildStoredName(filename || 'receipt.jpg', rid);
    let rec;
    try {
      rec = readRecord(rid);
    } catch (err) {
      return unconfirmedResult(rid, 'record unreadable: ' + err);
    }
    if (rec && !isBoundTo(rec, targetFolderId, name)) return rejectedResult(rid, 'requestId is bound to another folder/name');
    const found = findSavedFile(DriveApp.getFolderById(targetFolderId), targetFolderId, name, rec);
    if (found) return savedResult(rid, found, name, true);
    if (rec) return unconfirmedResult(rid, rec.state === 'saved' ? 'saved file not found in folder' : 'previous attempt unconfirmed');
    return { success: false, status: 'not_found', protocol: UPLOAD_PROTOCOL, requestId: rid, name: name };
  } catch (err) {
    return unconfirmedResult(rid, 'check failed: ' + err);
  }
}

// 保存名 = 元の名前（日付_金額…）+ "_" + 識別ID + 拡張子（最大120文字）。
// 識別IDが名前に入るので、同じ日付・金額の別の領収書とは名前が一致しない
function buildStoredName(filename, rid) {
  const clean = String(filename).replace(/[\\/:*?"<>|\u0000-\u001f]/g, '_');
  const m = clean.match(/^(.*?)(\.[A-Za-z0-9]{1,5})?$/);
  const ext = m[2] || '.jpg';
  const suffix = '_' + rid;
  const base = (m[1] || 'receipt').slice(0, 120 - suffix.length - ext.length);
  return base + suffix + ext;
}

// 保存名が完全一致し、ゴミ箱に入っておらず、実際の親が保存先フォルダであるファイルを探す。
// 作成直後は名前検索に出ないことがあるため、記録したfileIdでも確かめる（同じ確認をする）。
// 試行記録の無い、更新前に作られたID付きファイルも名前検索で見つかる
function findSavedFile(folder, folderId, name, rec) {
  const it = folder.getFilesByName(name);
  while (it.hasNext()) {
    const f = it.next();
    if (!f.isTrashed() && isInFolder(f, folderId)) return f;
  }
  if (rec && rec.fileId) {
    let f = null;
    try { f = DriveApp.getFileById(rec.fileId); } catch (err) { f = null; }   // 削除済みなど（記録があるので作り直しはしない）
    if (f && !f.isTrashed() && f.getName() === name && isInFolder(f, folderId)) return f;
  }
  return null;
}

function isInFolder(file, folderId) {
  const it = file.getParents();
  while (it.hasNext()) {
    if (it.next().getId() === folderId) return true;
  }
  return false;
}

// ---- 試行記録（スクリプトプロパティ）: { state: 'attempt' | 'saved', folderId, name, fileId, ts } ----
// 記録なしは null。読めない・壊れているときは例外（呼び出し側で「未確認」にする）
function readRecord(rid) {
  const raw = PropertiesService.getScriptProperties().getProperty(RECORD_PREFIX + rid);
  if (raw == null) return null;
  const rec = JSON.parse(raw);
  if (!rec || (rec.state !== 'attempt' && rec.state !== 'saved') ||
      typeof rec.folderId !== 'string' || typeof rec.name !== 'string') {
    throw new Error('record corrupted');
  }
  return rec;
}

// 書いた値を読み戻して確かめる。書けなければ例外
function writeRecord(rid, rec) {
  const props = PropertiesService.getScriptProperties();
  const value = JSON.stringify(rec);
  props.setProperty(RECORD_PREFIX + rid, value);
  if (props.getProperty(RECORD_PREFIX + rid) !== value) throw new Error('record not persisted');
}

function isBoundTo(rec, folderId, name) {
  return rec.folderId === folderId && rec.name === name;
}

// 保存を確認できたら記録を「保存済み」とfileIdに更新する（書けなくても保存済みは変えない。記録は残るので作り直さない）
function confirmSaved(rid, rec, folderId, name, file, duplicate) {
  const result = savedResult(rid, file, name, duplicate);
  if (!rec || rec.state !== 'saved' || (result.fileId && rec.fileId !== result.fileId)) {
    try {
      writeRecord(rid, { state: 'saved', folderId: folderId, name: name, fileId: result.fileId || (rec && rec.fileId) || '', ts: Date.now() });
    } catch (err) { /* 保存は済んでいる */ }
  }
  return result;
}

// 保存済みの返事。URLなどの補助情報が取れなくても「保存済み」は変えない
function savedResult(rid, file, name, duplicate) {
  const result = { success: true, status: 'saved', protocol: UPLOAD_PROTOCOL, requestId: rid, name: name, fileId: '', url: '', duplicate: duplicate };
  try { result.fileId = file.getId(); } catch (err) { result.warning = 'metadata unavailable'; }
  try { result.url = file.getUrl(); } catch (err) { result.warning = 'metadata unavailable'; }
  return result;
}

function rejectedResult(rid, error) {
  return { success: false, status: 'rejected', protocol: UPLOAD_PROTOCOL, requestId: rid, error: error };
}

function unconfirmedResult(rid, error) {
  return { success: false, status: 'unconfirmed', protocol: UPLOAD_PROTOCOL, requestId: rid, error: String(error) };
}

function newServerRequestId() {
  return Utilities.getUuid().replace(/-/g, '').toLowerCase().slice(0, 20);
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
