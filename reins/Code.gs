// ============================================================
//  不動産仕入れ候補管理テンプレート
//  使い方:
//    1. setupRealEstateTemplate() を一度だけ実行
//    2. 「デプロイ」→「新しいデプロイ」→ 種類: ウェブアプリ
//       実行ユーザー: 自分 / アクセス: 全員 → デプロイ
//    3. 発行されたURLをブックマークレットの SHEET_URL に貼る
// ============================================================

// ── 共通定数 ────────────────────────────────────────────────
const PROP_HEADERS = [
  "物件番号", "取引態様", "取引状況", "物件種目", "価格(万円)",
  "用途地域", "建ぺい率", "容積率",
  "土地面積(㎡)", "建物面積(㎡)", "㎡単価(万円)", "坪単価(万円)",
  "接道状況", "接道１",
  "所在地", "路線", "駅", "徒歩(分)", "バス",
  "商号", "電話番号", "取得日時", "図面/詳細", "フォルダ", "サムネイル"
];
const PROP_COL_WIDTHS = [
  130, 80, 100, 70, 90, 80, 70, 70,
  90, 90, 90, 90, 70, 110, 200, 130, 110, 70, 80,
  170, 110, 110, 60, 60, 160
];
const PROP_NUM_COLS = { E: "#,##0", I: "#,##0.00", J: "#,##0.00", K: "#,##0.0", L: "#,##0.0" };

// ── 行データ配列を生成（22列） ────────────────────────────────
function buildPropertyRows_(props) {
  return props.map(p => [
    p.reinsNo        || "",
    p.torihiki       || "",
    p.torihikiStatus || "",
    p.propertyType   || "",
    p.price          ? Number(p.price) : "",
    p.yoto           || "",
    p.kenpei         || "",
    p.yoseki         || "",
    p.landArea       ? Number(p.landArea) : "",
    p.buildingArea   ? Number(p.buildingArea) : "",
    p.sqmPrice       ? Number(p.sqmPrice) : "",
    p.tsuboPrice     ? Number(p.tsuboPrice) : "",
    p.setsuDoStatus  || "",
    p.setsuDo1       || "",
    p.address        || "",
    p.line           || "",
    p.station        || "",
    p.walkMinutes    ? Number(p.walkMinutes) : "",
    p.bus            || "",
    p.shogo          || "",
    p.phone          || "",
    p.fetchedAt      || "",
  ]);
}

// ── シートのヘッダー行を設定 ──────────────────────────────────
function setupSheetHeader_(sheet) {
  sheet.getRange(1, 1, 1, PROP_HEADERS.length)
    .setValues([PROP_HEADERS])
    .setBackground("#1a73e8")
    .setFontColor("#ffffff")
    .setFontWeight("bold")
    .setHorizontalAlignment("center");
  sheet.setFrozenRows(1);
  PROP_COL_WIDTHS.forEach((w, i) => sheet.setColumnWidth(i + 1, w));
}

// ── HYPERLINK 式でリンク列を設定（col 23: 図面, col 24: フォルダ, col 25: サムネイル） ──
function applyRichTextLinks_(sheet, props, startRow) {
  props.forEach((p, idx) => {
    const row = idx + startRow;
    if (p.driveUrl) {
      const label = (p.fileType || "ファイル").replace(/"/g, "");
      sheet.getRange(row, 23).setFormula(`=HYPERLINK("${p.driveUrl}","${label}")`);

      // col 25: Drive サムネイルを IMAGE で表示（カーソルを乗せると拡大される）
      const m = p.driveUrl.match(/\/d\/([^\/\?]+)/);
      if (m) {
        const thumbUrl = `https://drive.google.com/thumbnail?id=${m[1]}&sz=w400`;
        sheet.getRange(row, 25).setFormula(`=IMAGE("${thumbUrl}",1)`);
      }
    }
    if (p.folderUrl) {
      sheet.getRange(row, 24).setFormula(`=HYPERLINK("${p.folderUrl}","フォルダ")`);
    }
  });
}

// ── 数値書式・縞模様を全データ行に適用 ──────────────────────────
function applySheetFormats_(sheet, newStartRow, newRowCount) {
  Object.entries(PROP_NUM_COLS).forEach(([col, fmt]) => {
    sheet.getRange(newStartRow, col.charCodeAt(0) - 64, newRowCount, 1).setNumberFormat(fmt);
  });
  const lastRow = sheet.getLastRow();
  const numData = lastRow - 1;
  if (numData > 0) {
    const bgs = Array.from({ length: numData }, (_, i) =>
      Array(PROP_HEADERS.length).fill(i % 2 === 0 ? "#f8f9fa" : "#ffffff")
    );
    sheet.getRange(2, 1, numData, PROP_HEADERS.length).setBackgrounds(bgs);
  }
}

// ── Web App エンドポイント（ブックマークレットから受信） ──────
function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);
    let result;
    if (payload.action === "appendToSheet") {
      const url = appendToPropertySheet(payload.properties, payload.spreadsheetId);
      result = url ? { status: "ok", sheetUrl: url } : { status: "notFound" };
    } else if (payload.action === "createSheet") {
      const url = createPropertySheet(payload.properties, payload.condition);
      result = { status: "ok", sheetUrl: url };
    } else if (payload.action === "createFolder") {
      const folder = createDriveFolder(payload.folderName);
      result = { status: "ok", folderId: folder.id, folderUrl: folder.url };
    } else if (payload.action === "uploadFile") {
      const fileUrl = uploadFileToDrive(payload.fileName, payload.base64, payload.mimeType, payload.folderId);
      result = { status: "ok", fileUrl: fileUrl };
    } else if (payload.action === "deleteRowByReinsNo") {
      const removed = deleteRowByReinsNo_(payload.spreadsheetId, payload.reinsNo);
      result = { status: "ok", removed: removed };
    } else if (payload.action === "storeViewerKey") {
      const key = "v" + Date.now();
      PropertiesService.getScriptProperties().setProperty(key, JSON.stringify(payload.ids));
      result = { status: "ok", key: key };
    } else if (payload.action === "createDoc") {
      const url = createPropertyDoc(payload.properties, payload.condition);
      result = { status: "ok", docUrl: url };
    } else {
      appendProperty(payload);
      result = { status: "ok" };
    }
    return ContentService
      .createTextOutput(JSON.stringify(result))
      .setMimeType(ContentService.MimeType.JSON);
  } catch (err) {
    return ContentService
      .createTextOutput(JSON.stringify({ status: "error", message: err.message }))
      .setMimeType(ContentService.MimeType.JSON);
  }
}

// ── Google Spreadsheet に物件一覧を新規作成（種別ごとにシート分割）─
function createPropertySheet(properties, condition) {
  const today = new Date().toLocaleDateString("ja-JP", { year:"numeric", month:"2-digit", day:"2-digit" });
  const title = `不動産仕入れ候補リスト_${condition}_${today.replace(/\//g, "")}`;
  const ss = SpreadsheetApp.create(title);

  const sorted = [...properties].sort((a, b) =>
    (b.fetchedAt || "").localeCompare(a.fetchedAt || ""));

  const typeOrder = [];
  const byType = {};
  sorted.forEach(p => {
    const type = p.propertyType || "その他";
    if (!byType[type]) { byType[type] = []; typeOrder.push(type); }
    byType[type].push(p);
  });

  const defaultSheet = ss.getSheets()[0];
  let usedDefault = false;

  typeOrder.forEach(type => {
    const props = byType[type];
    let sheet;
    if (!usedDefault) {
      sheet = defaultSheet;
      sheet.setName(type);
      usedDefault = true;
    } else {
      sheet = ss.insertSheet(type);
    }

    setupSheetHeader_(sheet);

    const rows = buildPropertyRows_(props);
    if (rows.length > 0) {
      sheet.getRange(2, 1, rows.length, 22).setValues(rows);
    }
    applyRichTextLinks_(sheet, props, 2);
    applySheetFormats_(sheet, 2, rows.length || 1);
    if (rows.length > 0) sheet.setRowHeights(2, rows.length, 120);
  });

  ss.setActiveSheet(ss.getSheets()[0]);
  return ss.getUrl();
}

// ── 既存スプレッドシートに新規物件を追記 ────────────────────────
function appendToPropertySheet(properties, spreadsheetId) {
  let ss;
  try {
    ss = SpreadsheetApp.openById(spreadsheetId);
  } catch (e) {
    return null;  // スプレッドシートが見つからない
  }

  const sorted = [...properties].sort((a, b) =>
    (b.fetchedAt || "").localeCompare(a.fetchedAt || ""));

  const typeOrder = [];
  const byType = {};
  sorted.forEach(p => {
    const type = p.propertyType || "その他";
    if (!byType[type]) { byType[type] = []; typeOrder.push(type); }
    byType[type].push(p);
  });

  typeOrder.forEach(type => {
    let sheet = ss.getSheetByName(type);
    if (!sheet) {
      sheet = ss.insertSheet(type);
      setupSheetHeader_(sheet);
    }

    const props = byType[type];
    // ヘッダー直後に行を挿入して既存データを下へ
    sheet.insertRowsBefore(2, props.length);

    const rows = buildPropertyRows_(props);
    sheet.getRange(2, 1, rows.length, 22).setValues(rows);
    applyRichTextLinks_(sheet, props, 2);
    applySheetFormats_(sheet, 2, rows.length);
    sheet.setRowHeights(2, rows.length, 120);
  });

  return ss.getUrl();
}

// ── reinsNo(A列) で該当行を全シートから削除（空リンク行の手当て用）──
function deleteRowByReinsNo_(spreadsheetId, reinsNo) {
  const ss = SpreadsheetApp.openById(spreadsheetId);
  let removed = 0;
  ss.getSheets().forEach(sheet => {
    const last = sheet.getLastRow();
    if (last < 2) return;
    const col = sheet.getRange(2, 1, last - 1, 1).getValues();
    // 下から削除して行番号のズレを防ぐ
    for (let i = col.length - 1; i >= 0; i--) {
      if (String(col[i][0]) === String(reinsNo)) {
        sheet.deleteRow(i + 2);
        removed++;
      }
    }
  });
  return removed;
}

// ── Drive権限テスト（GASエディタで一度だけ実行して認証を通す） ──
function authorizeDrive() {
  DriveApp.getRootFolder();
  Logger.log("Drive認証完了");
}

// ── Google Drive フォルダ作成 ─────────────────────────────────
function createDriveFolder(name) {
  const folder = DriveApp.createFolder(name);
  folder.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return { id: folder.getId(), url: folder.getUrl() };
}

// ── Google Drive へファイルをアップロード ──────────────────────
function uploadFileToDrive(fileName, base64Content, mimeType, folderId) {
  const bytes = Utilities.base64Decode(base64Content);
  const blob = Utilities.newBlob(bytes, mimeType, fileName);
  const folder = DriveApp.getFolderById(folderId);
  const file = folder.createFile(blob);
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return file.getUrl();
}

// ── Google Docs に物件一覧を作成 ──────────────────────────────
function createPropertyDoc(properties, condition) {
  const today = new Date().toLocaleDateString("ja-JP", { year:"numeric", month:"2-digit", day:"2-digit" });
  const title = `不動産仕入れ候補リスト_${today.replace(/\//g, "")}`;
  const doc = DocumentApp.create(title);
  const body = doc.getBody();

  // タイトル
  const titlePara = body.appendParagraph(title);
  titlePara.setHeading(DocumentApp.ParagraphHeading.TITLE);

  // メタ情報
  body.appendParagraph(`作成日: ${today}`).setItalic(true);
  if (condition) {
    body.appendParagraph(`検索条件: ${condition}`).setItalic(true);
  }
  body.appendParagraph(`物件数: ${properties.length} 件`).setItalic(true);
  body.appendHorizontalRule();

  // 物件ごとに出力
  properties.forEach((p, i) => {
    const priceStr = p.price ? ` ${Number(p.price).toLocaleString()}万円` : "";
    const typeStr = p.propertyType ? `[${p.propertyType}] ` : "";
    const heading = body.appendParagraph(`${i + 1}. ${typeStr}${p.address || p.reinsNo || "物件" + (i + 1)}${priceStr}`);
    heading.setHeading(DocumentApp.ParagraphHeading.HEADING2);

    const kenpeiYoseki = [p.kenpei, p.yoseki].filter(Boolean).join(" / ") ||
                         (p.coverage || null);
    const traffic = [
      p.line, p.station,
      p.walkMinutes ? "徒歩" + p.walkMinutes + "分" : null,
      p.bus || null,
    ].filter(Boolean).join(" ");
    const lines = [
      p.torihiki || p.torihikiStatus
        ? `取引: ${[p.torihiki, p.torihikiStatus].filter(Boolean).join(" / ")}` : null,
      p.propertyType  ? `種別: ${p.propertyType}` : null,
      p.price         ? `価格: ${Number(p.price).toLocaleString()} 万円` : null,
      p.yoto || kenpeiYoseki
        ? `用途地域: ${p.yoto || ""}　建ぺい率/容積率: ${kenpeiYoseki || ""}` : null,
      p.landArea
        ? `土地面積: ${p.landArea} ㎡　㎡単価: ${p.sqmPrice ? p.sqmPrice + "万円" : "-"}　坪単価: ${p.tsuboPrice ? p.tsuboPrice + "万円" : "-"}` : null,
      p.setsuDoStatus || p.setsuDo1
        ? `接道: ${[p.setsuDoStatus, p.setsuDo1].filter(Boolean).join(" ")}` : null,
      p.buildingArea  ? `建物面積: ${p.buildingArea} ㎡` : null,
      p.builtAge      ? `築年数: ${p.builtAge} 年` : null,
      p.layout        ? `間取り: ${p.layout}` : null,
      p.address       ? `所在地: ${p.address}` : null,
      traffic         ? `交通: ${traffic}` : null,
      p.reinsNo       ? `REINS番号: ${p.reinsNo}` : null,
      p.company || p.phone
        ? `掲載会社: ${p.company || ""}${p.phone ? "　" + p.phone : ""}` : null,
      p.memo          ? `備考: ${p.memo}` : null,
    ].filter(Boolean);

    lines.forEach(line => body.appendParagraph(line).setIndentStart(20));
    body.appendHorizontalRule();
  });

  doc.saveAndClose();
  return doc.getUrl();
}

function appendProperty(d) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("物件リスト");
  if (!sheet) throw new Error("物件リストシートが見つかりません");

  // 最終行の次に追記
  const lastRow = Math.max(sheet.getLastRow() + 1, 2);

  // 列順: B登録日, C-E管理系, F種別, G-I住所, J-L交通, M価格, N土地, P建物, Q築年数, R構造, S間取り
  //       T REINS番号, U掲載会社, V担当者, W電話, X仕入れ価格, AC問合せ日, AG備考
  const row = [
    "",                       // A: 管理番号（計算式で自動）
    new Date(),               // B: 登録日
    d.status || "検討中",     // C: ステータス
    d.priority || "中",       // D: 優先度
    "",                       // E: 社内担当者
    d.propertyType || "",     // F: 物件種別
    d.prefecture || "",       // G: 都道府県
    d.city || "",             // H: 市区町村
    d.address || "",          // I: 番地
    d.station || "",          // J: 最寄り駅
    d.line || "",             // K: 路線名
    d.walkMinutes || "",      // L: 徒歩（分）
    d.price || "",            // M: 販売価格
    d.landArea || "",         // N: 土地面積
    "",                       // O: 坪数（計算式）
    d.buildingArea || "",     // P: 建物面積
    d.builtAge || "",         // Q: 築年数
    d.structure || "",        // R: 構造
    d.layout || "",           // S: 間取り
    d.reinsNo || "",          // T: REINS番号
    d.company || "",          // U: 掲載会社名
    d.contact || "",          // V: 先方担当者名
    d.phone || "",            // W: 電話番号
    "",                       // X: 想定仕入れ価格
    "",                       // Y: 想定売価
    "",                       // Z: 粗利（計算式）
    "",                       // AA: 粗利率（計算式）
    "",                       // AB: 表面利回り
    new Date(),               // AC: 問合せ日
    "",                       // AD: 内見日
    "",                       // AE: 次回アクション
    "",                       // AF: 次回アクション期限
    d.memo || "",             // AG: 備考
  ];

  sheet.getRange(lastRow, 1, 1, row.length).setValues([row]);

  // 管理番号の計算式を再セット
  sheet.getRange(lastRow, 1).setFormula(`=IF(B${lastRow}="","",TEXT(ROW()-1,"000"))`);
  sheet.getRange(lastRow, 15).setFormula(`=IF(N${lastRow}="","",N${lastRow}/3.3058)`);
  sheet.getRange(lastRow, 26).setFormula(`=IF(OR(X${lastRow}="",Y${lastRow}=""),"",Y${lastRow}-X${lastRow})`);
  sheet.getRange(lastRow, 27).setFormula(`=IF(OR(Y${lastRow}="",Y${lastRow}=0),"",Z${lastRow}/Y${lastRow})`);
}

// ── PDF/図面ビューア（ブラウザから GET でアクセス） ────────────
function doGet(e) {
  const p       = e.parameter || {};
  const idsParam = p.ids || "";          // カンマ区切り Drive ファイルID（新着限定モード）
  const folderId = p.folderId || "";
  const fileId   = p.fileId  || "";
  let   idx      = parseInt(p.i || "0");

  let files = [];

  // ?k=xxx → PropertiesService からIDリストを復元
  const keyParam = p.k || "";
  if (keyParam && !idsParam) {
    const stored = PropertiesService.getScriptProperties().getProperty(keyParam);
    if (stored) {
      const ids = JSON.parse(stored);
      for (const id of ids) {
        try {
          const f    = DriveApp.getFileById(id);
          const mime = f.getMimeType();
          files.push({ id, name: f.getName(), isPdf: mime === MimeType.PDF });
        } catch (_) {}
      }
    }
    // baseParam をキーベースに設定してナビゲーションに引き継ぐ
    const safeIdx2   = Math.max(0, Math.min(idx, files.length - 1));
    const total2     = files.length;
    if (total2 === 0) return HtmlService.createHtmlOutput("<p style='font-family:sans-serif;padding:20px'>ファイルが見つかりません</p>");
    const cur2       = files[safeIdx2];
    const serviceUrl2 = ScriptApp.getService().getUrl();
    const previewHtml2 = cur2.isPdf
      ? `<div style="flex:1;position:relative"><iframe src="https://drive.google.com/file/d/${cur2.id}/preview" allowfullscreen style="position:absolute;inset:0;width:100%;height:100%;border:none"></iframe><div id="sw" style="position:absolute;inset:0;z-index:10"></div></div>`
      : `<img src="https://drive.google.com/thumbnail?id=${cur2.id}&sz=w1200" style="flex:1;max-width:100%;object-fit:contain" alt="${cur2.name}">`;
    const html2 = `<!DOCTYPE html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>図面 ${safeIdx2+1}/${total2}</title><style>*{box-sizing:border-box;margin:0;padding:0}body{font-family:sans-serif;display:flex;flex-direction:column;height:100vh;background:#222}.nav{display:flex;align-items:center;background:#1a73e8;color:#fff;padding:8px 12px;gap:8px;flex-shrink:0}.btn{background:rgba(255,255,255,.25);border:none;color:#fff;font-size:22px;padding:8px 20px;border-radius:6px;cursor:pointer;line-height:1}.btn:disabled{opacity:.3;cursor:default}.info{flex:1;text-align:center;min-width:0;overflow:hidden}.name{font-size:11px;opacity:.85;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.count{font-size:15px;font-weight:bold}</style></head><body><nav class="nav"><button class="btn" onclick="go(-1)" ${safeIdx2<=0?"disabled":""}>←</button><div class="info"><div class="name">${cur2.name}</div><div class="count">${safeIdx2+1} / ${total2}</div></div><button class="btn" onclick="go(1)" ${safeIdx2>=total2-1?"disabled":""}>→</button></nav>${previewHtml2}<script>function go(d){const next=${safeIdx2}+d;if(next<0||next>=${total2})return;location.href="${serviceUrl2}?k=${keyParam}&i="+next;}(function(){const el=document.getElementById('sw')||document;let sx=0,sy=0;el.addEventListener('touchstart',e=>{sx=e.touches[0].clientX;sy=e.touches[0].clientY;},{passive:true});el.addEventListener('touchend',e=>{const dx=e.changedTouches[0].clientX-sx,dy=e.changedTouches[0].clientY-sy;if(Math.abs(dx)>Math.abs(dy)&&Math.abs(dx)>40)go(dx<0?1:-1);});})();</script></body></html>`;
    return HtmlService.createHtmlOutput(html2).setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  }

  if (idsParam) {
    // ids 指定: 指定IDのファイルのみ順番通りに表示
    const ids = idsParam.split(",").map(s => s.trim()).filter(Boolean);
    for (const id of ids) {
      try {
        const f    = DriveApp.getFileById(id);
        const mime = f.getMimeType();
        files.push({ id, name: f.getName(), isPdf: mime === MimeType.PDF });
      } catch (_) {}
    }
  } else if (folderId) {
    // folderId 指定: フォルダ内全ファイルを日付降順
    let folder;
    try { folder = DriveApp.getFolderById(folderId); }
    catch (_) {
      return HtmlService.createHtmlOutput(
        "<p style='font-family:sans-serif;padding:20px'>フォルダが見つかりません</p>"
      );
    }
    const iter = folder.getFiles();
    while (iter.hasNext()) {
      const f    = iter.next();
      const mime = f.getMimeType();
      if (mime === MimeType.PDF || mime === "image/png" || mime === "image/jpeg") {
        files.push({ id: f.getId(), name: f.getName(), date: f.getLastUpdated().getTime(), isPdf: mime === MimeType.PDF });
      }
    }
    files.sort((a, b) => b.date - a.date);
    if (fileId) {
      const fi = files.findIndex(f => f.id === fileId);
      if (fi >= 0) idx = fi;
    }
  } else {
    return HtmlService.createHtmlOutput(
      "<p style='font-family:sans-serif;padding:20px'>ids または folderId パラメータが必要です</p>"
    );
  }

  const total = files.length;
  if (total === 0) {
    return HtmlService.createHtmlOutput(
      "<p style='font-family:sans-serif;padding:20px'>ファイルが見つかりません</p>"
    );
  }

  const safeIdx    = Math.max(0, Math.min(idx, total - 1));
  const cur        = files[safeIdx];
  const serviceUrl = ScriptApp.getService().getUrl();
  // ナビゲーションURLの共通パラメータ（ids or folderId を引き継ぐ）
  const baseParam  = idsParam ? `ids=${encodeURIComponent(idsParam)}` : `folderId=${folderId}`;

  const previewHtml = cur.isPdf
    ? `<div style="flex:1;position:relative"><iframe src="https://drive.google.com/file/d/${cur.id}/preview" allowfullscreen style="position:absolute;inset:0;width:100%;height:100%;border:none"></iframe><div id="sw" style="position:absolute;inset:0;z-index:10"></div></div>`
    : `<img src="https://drive.google.com/thumbnail?id=${cur.id}&sz=w1200" style="flex:1;max-width:100%;object-fit:contain" alt="${cur.name}">`;

  const html = `<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>図面 ${safeIdx + 1}/${total}</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:sans-serif;display:flex;flex-direction:column;height:100vh;background:#222}
.nav{display:flex;align-items:center;background:#1a73e8;color:#fff;padding:8px 12px;gap:8px;flex-shrink:0}
.btn{background:rgba(255,255,255,.25);border:none;color:#fff;font-size:22px;padding:8px 20px;border-radius:6px;cursor:pointer;line-height:1}
.btn:disabled{opacity:.3;cursor:default}
.info{flex:1;text-align:center;min-width:0;overflow:hidden}
.name{font-size:11px;opacity:.85;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.count{font-size:15px;font-weight:bold}
</style>
</head>
<body>
<nav class="nav">
  <button class="btn" onclick="go(-1)" ${safeIdx <= 0 ? "disabled" : ""}>←</button>
  <div class="info">
    <div class="name">${cur.name}</div>
    <div class="count">${safeIdx + 1} / ${total}</div>
  </div>
  <button class="btn" onclick="go(1)" ${safeIdx >= total - 1 ? "disabled" : ""}>→</button>
</nav>
${previewHtml}
<script>
function go(d){
  const next=${safeIdx}+d;
  if(next<0||next>=${total})return;
  location.href="${serviceUrl}?${baseParam}&i="+next;
}
(function(){
  const el=document.getElementById('sw')||document;
  let sx=0,sy=0;
  el.addEventListener('touchstart',e=>{sx=e.touches[0].clientX;sy=e.touches[0].clientY;},{passive:true});
  el.addEventListener('touchend',e=>{
    const dx=e.changedTouches[0].clientX-sx;
    const dy=e.changedTouches[0].clientY-sy;
    if(Math.abs(dx)>Math.abs(dy)&&Math.abs(dx)>40)go(dx<0?1:-1);
  });
})();
</script>
</body>
</html>`;

  return HtmlService.createHtmlOutput(html)
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu("不動産管理")
    .addItem("テンプレート初期化", "setupRealEstateTemplate")
    .addSeparator()
    .addItem("▶ Drive権限を認証（初回のみ）", "authorizeDrive")
    .addSeparator()
    .addItem("ダッシュボード更新", "updateDashboard")
    .addItem("期限切れアクション確認", "checkDeadlines")
    .addToUi();
}

// ── メインセットアップ ────────────────────────────────────────
function setupRealEstateTemplate() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();

  setupListSheet(ss);
  setupDashboardSheet(ss);

  ss.setActiveSheet(ss.getSheetByName("物件リスト"));
  SpreadsheetApp.getUi().alert("✅ セットアップ完了！\n「不動産管理」メニューから各機能を利用できます。");
}

// ── 物件リストシート ──────────────────────────────────────────
function setupListSheet(ss) {
  let sheet = ss.getSheetByName("物件リスト") || ss.insertSheet("物件リスト");
  sheet.clearContents();
  sheet.clearFormats();
  sheet.clearConditionalFormatRules();

  const headers = [
    "管理番号", "登録日", "ステータス", "優先度", "社内担当者",
    "物件種別", "都道府県", "市区町村", "番地・号",
    "最寄り駅", "路線名", "徒歩（分）",
    "販売価格（万円）", "土地面積（㎡）", "土地坪数",
    "建物面積（㎡）", "築年数", "構造", "間取り",
    "REINS番号", "掲載会社名", "先方担当者名", "電話番号",
    "想定仕入れ価格（万円）", "想定売価（万円）",
    "想定粗利（万円）", "粗利率（%）", "表面利回り（%）",
    "問合せ日", "内見日", "次回アクション", "次回アクション期限", "備考"
  ];

  // ヘッダー
  const headerRange = sheet.getRange(1, 1, 1, headers.length);
  headerRange.setValues([headers])
             .setBackground("#1a73e8")
             .setFontColor("#ffffff")
             .setFontWeight("bold")
             .setHorizontalAlignment("center");
  sheet.setFrozenRows(1);

  // 列幅
  const colWidths = [
    90, 100, 110, 70, 90,
    90, 80, 100, 120,
    100, 100, 80,
    120, 110, 80,
    110, 80, 80, 80,
    110, 140, 110, 130,
    140, 120,
    120, 90, 110,
    100, 100, 160, 120, 200
  ];
  colWidths.forEach((w, i) => sheet.setColumnWidth(i + 1, w));

  // 縞模様
  for (let r = 2; r <= 201; r++) {
    sheet.getRange(r, 1, 1, headers.length)
         .setBackground(r % 2 === 0 ? "#f8f9fa" : "#ffffff");
  }

  // ドロップダウン
  const dropdowns = {
    C: ["検討中", "問合せ済", "内見済", "交渉中", "成約", "見送り"],
    D: ["高", "中", "低"],
    F: ["土地", "戸建", "マンション", "収益物件（一棟）", "収益物件（区分）", "その他"],
    R: ["木造", "軽量鉄骨", "重量鉄骨", "RC", "SRC", "その他"],
  };
  Object.entries(dropdowns).forEach(([col, items]) => {
    const range = sheet.getRange(2, col.charCodeAt(0) - 64, 200, 1);
    range.setDataValidation(
      SpreadsheetApp.newDataValidation()
        .requireValueInList(items, true)
        .setAllowInvalid(false)
        .build()
    );
  });

  // 日付書式
  ["B", "AC", "AD", "AF"].forEach(col => {
    sheet.getRange(2, col.charCodeAt(0) - 64, 200, 1).setNumberFormat("yyyy/mm/dd");
  });

  // 数値書式
  ["M", "N", "P", "X", "Y", "Z"].forEach(col => {
    sheet.getRange(2, col.charCodeAt(0) - 64, 200, 1).setNumberFormat("#,##0");
  });
  ["O", "Q", "L"].forEach(col => {
    sheet.getRange(2, col.charCodeAt(0) - 64, 200, 1).setNumberFormat("0.00");
  });
  ["AA", "AB"].forEach(col => {
    sheet.getRange(2, col.charCodeAt(0) - 64, 200, 1).setNumberFormat("0.0%");
  });

  // 計算式（200行分）
  for (let r = 2; r <= 201; r++) {
    sheet.getRange(r, 1) .setFormula(`=IF(B${r}="","",TEXT(ROW()-1,"000"))`);       // A: 管理番号
    sheet.getRange(r, 15).setFormula(`=IF(N${r}="","",N${r}/3.3058)`);              // O: 坪数
    sheet.getRange(r, 26).setFormula(`=IF(OR(X${r}="",Y${r}=""),"",Y${r}-X${r})`); // Z: 粗利
    sheet.getRange(r, 27).setFormula(`=IF(OR(Y${r}="",Y${r}=0),"",Z${r}/Y${r})`);  // AA: 粗利率
  }

  // 条件付き書式（ステータス列）
  const statusRange = sheet.getRange("C2:C201");
  const cfRules = [
    { value: "成約",    bg: "#d4edda", font: "#155724" },
    { value: "見送り",  bg: "#f8d7da", font: "#721c24" },
    { value: "交渉中",  bg: "#fff3cd", font: "#856404" },
    { value: "問合せ済", bg: "#d1ecf1", font: "#0c5460" },
    { value: "内見済",  bg: "#e2d9f3", font: "#4a235a" },
  ].map(({ value, bg, font }) =>
    SpreadsheetApp.newConditionalFormatRule()
      .whenTextEqualTo(value)
      .setBackground(bg)
      .setFontColor(font)
      .setRanges([statusRange])
      .build()
  );
  sheet.setConditionalFormatRules(cfRules);

  // 期限切れアクションを赤くする（AF列）
  const deadlineRange = sheet.getRange("AF2:AF201");
  const deadlineRule = SpreadsheetApp.newConditionalFormatRule()
    .whenDateBefore(SpreadsheetApp.RelativeDate.TODAY)
    .setBackground("#f8d7da")
    .setFontColor("#721c24")
    .setRanges([deadlineRange])
    .build();
  sheet.setConditionalFormatRules([...cfRules, deadlineRule]);
}

// ── ダッシュボードシート ──────────────────────────────────────
function setupDashboardSheet(ss) {
  let dash = ss.getSheetByName("ダッシュボード") || ss.insertSheet("ダッシュボード", 0);
  dash.clearContents();
  dash.clearFormats();

  // タイトル
  dash.getRange("A1").setValue("不動産仕入れ管理ダッシュボード")
      .setFontSize(16).setFontWeight("bold").setFontColor("#1a73e8");
  dash.getRange("A2").setValue(`最終更新: ${new Date().toLocaleDateString("ja-JP")}`)
      .setFontColor("#888888");

  // ステータス別集計
  dash.getRange("A4").setValue("ステータス別件数").setFontWeight("bold").setBackground("#e8f0fe");
  const statuses = ["検討中", "問合せ済", "内見済", "交渉中", "成約", "見送り"];
  statuses.forEach((s, i) => {
    const row = 5 + i;
    dash.getRange(row, 1).setValue(s);
    dash.getRange(row, 2).setFormula(`=COUNTIF(物件リスト!C:C,"${s}")`);
    dash.getRange(row, 3).setValue("件");
  });
  dash.getRange(5 + statuses.length, 1).setValue("合計").setFontWeight("bold");
  dash.getRange(5 + statuses.length, 2).setFormula(`=SUM(B5:B${4 + statuses.length})`);

  // 優先度別集計
  dash.getRange("D4").setValue("優先度別件数").setFontWeight("bold").setBackground("#e8f0fe");
  const priorities = ["高", "中", "低"];
  priorities.forEach((p, i) => {
    const row = 5 + i;
    dash.getRange(row, 4).setValue(p);
    dash.getRange(row, 5).setFormula(`=COUNTIF(物件リスト!D:D,"${p}")`);
    dash.getRange(row, 6).setValue("件");
  });

  // 物件種別集計
  dash.getRange("A13").setValue("物件種別集計").setFontWeight("bold").setBackground("#e8f0fe");
  const types = ["土地", "戸建", "マンション", "収益物件（一棟）", "収益物件（区分）", "その他"];
  types.forEach((t, i) => {
    const row = 14 + i;
    dash.getRange(row, 1).setValue(t);
    dash.getRange(row, 2).setFormula(`=COUNTIF(物件リスト!F:F,"${t}")`);
    dash.getRange(row, 3).setValue("件");
  });

  // 収益サマリー（成約物件）
  dash.getRange("D13").setValue("成約物件サマリー").setFontWeight("bold").setBackground("#e8f0fe");
  const summaryRows = [
    ["成約件数",   `=COUNTIF(物件リスト!C:C,"成約")`],
    ["平均粗利（万円）", `=IFERROR(AVERAGEIF(物件リスト!C:C,"成約",物件リスト!Z:Z),"-")`],
    ["平均粗利率", `=IFERROR(TEXT(AVERAGEIF(物件リスト!C:C,"成約",物件リスト!AA:AA),"0.0%"),"-")`],
    ["合計粗利（万円）", `=IFERROR(SUMIF(物件リスト!C:C,"成約",物件リスト!Z:Z),"-")`],
  ];
  summaryRows.forEach(([label, formula], i) => {
    dash.getRange(14 + i, 4).setValue(label);
    dash.getRange(14 + i, 5).setFormula(formula);
  });

  // 列幅
  [200, 60, 40, 220, 80, 40].forEach((w, i) => dash.setColumnWidth(i + 1, w));
}

// ── ダッシュボード更新 ────────────────────────────────────────
function updateDashboard() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const dash = ss.getSheetByName("ダッシュボード");
  if (!dash) {
    SpreadsheetApp.getUi().alert("ダッシュボードシートが見つかりません。先にテンプレートを初期化してください。");
    return;
  }
  dash.getRange("B2").setValue(`最終更新: ${new Date().toLocaleDateString("ja-JP")}`);
  SpreadsheetApp.flush();
  SpreadsheetApp.getUi().alert("ダッシュボードを更新しました。");
}

// ── 期限切れアクション確認 ────────────────────────────────────
function checkDeadlines() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getSheetByName("物件リスト");
  if (!sheet) return;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const data = sheet.getDataRange().getValues();
  const overdue = [];

  for (let i = 1; i < data.length; i++) {
    const deadline = data[i][31]; // AF列: 次回アクション期限
    const status = data[i][2];    // C列: ステータス
    if (!deadline || status === "成約" || status === "見送り") continue;

    const d = new Date(deadline);
    d.setHours(0, 0, 0, 0);
    if (d <= today) {
      overdue.push(`No.${data[i][0]} ${data[i][6]}${data[i][7]} [${status}] → ${data[i][30]}`);
    }
  }

  if (overdue.length === 0) {
    SpreadsheetApp.getUi().alert("期限切れのアクションはありません。");
  } else {
    SpreadsheetApp.getUi().alert(
      `⚠️ 期限切れアクション ${overdue.length}件:\n\n` + overdue.join("\n")
    );
  }
}
