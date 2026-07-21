// 物件情報ビューア用 読み取り専用 GAS Web App
// realestate スクレイパーが書き込む「物件情報」シートを JSON で返す。
// スタンドアロン運用: スプレッドシートIDを直接指定して openById で開く。

const SPREADSHEET_ID = '1luaTrRO6D-AcqPu4u9JM1vrOVOdtatldOZEK7SfP3nQ';
const SHEET_NAME     = '物件情報';
const SECRET_TOKEN   = 'WQZpZzGK4gsxUwha59j-xTcC';

const HEADERS = ['取得日時', '会社名', '物件名・タイトル', '価格・賃料', '所在地', '面積・間取り', '物件URL', '会社URL'];

const CONTROL_SHEET = '制御';
// 制御シートのセル: B1=リクエスト時刻(ms) B2=状態メッセージ B3=最終処理リクエスト(ms、Mac側が書く)

function doGet(e) {
  const p = e.parameter;
  if (p.token !== SECRET_TOKEN) return makeResponse({ error: 'Unauthorized' });
  const action = p.action || 'list';
  if (action === 'list')          return makeResponse(listProperties());
  if (action === 'requestScrape') return makeResponse(requestScrape());
  if (action === 'scrapeStatus')  return makeResponse(scrapeStatus());
  return makeResponse({ error: 'Unknown action' });
}

// ── 手動スクレイプ・トリガー（フラグ方式） ──────────────────
function getControlSheet() {
  const ss = SpreadsheetApp.openById(SPREADSHEET_ID);
  let sh = ss.getSheetByName(CONTROL_SHEET);
  if (!sh) {
    sh = ss.insertSheet(CONTROL_SHEET);
    sh.getRange('A1').setValue('巡回リクエスト時刻');
    sh.getRange('A2').setValue('状態');
    sh.getRange('A3').setValue('最終処理リクエスト');
  }
  return sh;
}

function requestScrape() {
  const sh = getControlSheet();
  const now = Date.now();
  sh.getRange('B1').setValue(now);
  sh.getRange('B2').setValue('🕐 リクエスト受付（実行待ち）');
  return { ok: true, requested: now, status: '🕐 リクエスト受付（実行待ち）' };
}

function scrapeStatus() {
  const sh = getControlSheet();
  const requested = Number(sh.getRange('B1').getValue()) || 0;
  const processed = Number(sh.getRange('B3').getValue()) || 0;
  return {
    status: String(sh.getRange('B2').getValue() || '💤 待機中'),
    requested: requested,
    processed: processed,
    pending: requested > processed,
  };
}

function listProperties() {
  const ss    = SpreadsheetApp.openById(SPREADSHEET_ID);
  const sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) return { properties: [] };
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return { properties: [] };

  // ヘッダー行を探す（先頭が「取得日時」の行）
  let headerIdx = 0;
  for (let i = 0; i < values.length; i++) {
    if (values[i][0] === '取得日時') { headerIdx = i; break; }
  }
  const rows = values.slice(headerIdx + 1);

  const props = rows
    .filter(r => String(r[6] || '').trim())  // 物件URL がある行のみ
    .map(r => {
      const ts = toTimestamp(r[0]);
      return {
        date:    fmtDate(r[0]),
        _ts:     ts,
        company: String(r[1] || ''),
        title:   String(r[2] || ''),
        price:   String(r[3] || ''),
        address: String(r[4] || ''),
        layout:  String(r[5] || ''),
        url:     String(r[6] || ''),
        source:  String(r[7] || ''),
        priceChange: String(r[8] || '')
      };
    });

  // 取得日時の新しい順（パースできない行は末尾）
  props.sort((a, b) => b._ts - a._ts);
  props.forEach(p => { delete p._ts; });
  return { properties: props, count: props.length };
}

// 取得日時をパースして Date を返す（Date / JS文字列 / "yyyy/MM/dd HH:mm:ss" に対応）
function parseAny(v) {
  if (v instanceof Date) return v;
  const s = String(v || '').trim();
  if (!s) return null;
  // "Sun Jun 07 2026 18:47:00 GMT+0900 (日本標準時)" の末尾括弧を除去
  const d = new Date(s.replace(/\s*\(.*\)\s*$/, ''));
  return isNaN(d.getTime()) ? null : d;
}
function toTimestamp(v) {
  const d = parseAny(v);
  return d ? d.getTime() : -1;
}
// 取得日時を "yyyy-MM-dd HH:mm:ss"（Asia/Tokyo）に正規化
function fmtDate(v) {
  const d = parseAny(v);
  return d ? Utilities.formatDate(d, 'Asia/Tokyo', 'yyyy-MM-dd HH:mm:ss') : String(v || '');
}

function makeResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
