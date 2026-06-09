const SHEET_NAME = 'TODO';
const SECRET_TOKEN = 'QzFA2VTLy0Bhkv3cc99DuZ1v';

function doGet(e) {
  const p = e.parameter;
  if (p.token !== SECRET_TOKEN) return makeResponse({ error: 'Unauthorized' });

  const action = p.action || 'list';
  if (action === 'list')    return makeResponse(listTodos());
  if (action === 'add')     return makeResponse(addTodo(p.text, p.category));
  if (action === 'done')    return makeResponse(doneTodo(p.id));
  if (action === 'delete')  return makeResponse(deleteTodo(p.id));
  if (action === 'edit')    return makeResponse(editTodo(p.id, p.text, p.category));
  if (action === 'reorder') return makeResponse(reorderTodos(p.ids));

  return makeResponse({ error: 'Unknown action' });
}

function getSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(['id', 'text', 'status', 'created', 'done_at', 'category', 'order']);
    sheet.setFrozenRows(1);
  }
  return sheet;
}

function listTodos() {
  const sheet = getSheet();
  const rows  = sheet.getDataRange().getValues().slice(1);
  return {
    todos: rows.map((r, i) => ({
      id: r[0], text: r[1], status: r[2], created: r[3], done_at: r[4],
      category: r[5] || '',
      order: (r[6] !== '' && r[6] != null) ? Number(r[6]) : (i + 1) * 100
    }))
  };
}

function addTodo(text, category) {
  if (!text || !text.trim()) return { error: 'empty text' };
  const id    = Utilities.getUuid();
  const now   = Utilities.formatDate(new Date(), 'Asia/Tokyo', "yyyy-MM-dd'T'HH:mm:ss");
  const sheet = getSheet();
  const rows  = sheet.getDataRange().getValues().slice(1);
  const maxOrd = rows.length ? Math.max(...rows.map(r => Number(r[6]) || 0)) : 0;
  sheet.appendRow([id, text.trim(), 'pending', now, '', (category || '').trim(), maxOrd + 1]);
  return { success: true, id };
}

function doneTodo(id) {
  const sheet = getSheet();
  const data  = sheet.getDataRange().getValues();
  const now   = Utilities.formatDate(new Date(), 'Asia/Tokyo', "yyyy-MM-dd'T'HH:mm:ss");
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === id) {
      const newStatus = data[i][2] === 'done' ? 'pending' : 'done';
      sheet.getRange(i + 1, 3).setValue(newStatus);
      sheet.getRange(i + 1, 5).setValue(newStatus === 'done' ? now : '');
      return { success: true, status: newStatus };
    }
  }
  return { error: 'Not found' };
}

function editTodo(id, text, category) {
  const sheet = getSheet();
  const data  = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === id) {
      if (text !== undefined && text.trim()) sheet.getRange(i + 1, 2).setValue(text.trim());
      if (category !== undefined)            sheet.getRange(i + 1, 6).setValue(category.trim());
      return { success: true };
    }
  }
  return { error: 'Not found' };
}

function reorderTodos(idsStr) {
  if (!idsStr) return { error: 'no ids' };
  const ids   = idsStr.split(',').filter(Boolean);
  const sheet = getSheet();
  const data  = sheet.getDataRange().getValues();
  const rowMap = {};
  for (let i = 1; i < data.length; i++) rowMap[data[i][0]] = i + 1;
  ids.forEach((id, i) => {
    if (rowMap[id]) sheet.getRange(rowMap[id], 7).setValue(i + 1);
  });
  return { success: true };
}

function deleteTodo(id) {
  const sheet = getSheet();
  const data  = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === id) {
      sheet.deleteRow(i + 1);
      return { success: true };
    }
  }
  return { error: 'Not found' };
}

function makeResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
