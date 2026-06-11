const SHEET_NAME = 'TODO';
const SECRET_TOKEN = 'QzFA2VTLy0Bhkv3cc99DuZ1v';

function doGet(e) {
  const p = e.parameter;
  if (p.token !== SECRET_TOKEN) return makeResponse({ error: 'Unauthorized' });
  const action = p.action || 'list';
  if (action === 'list')      return makeResponse(listTodos());
  if (action === 'add')       return makeResponse(addTodo(p.text, p.category));
  if (action === 'done')      return makeResponse(doneTodo(p.id));
  if (action === 'delete')    return makeResponse(deleteTodo(p.id));
  if (action === 'edit')      return makeResponse(editTodo(p.id, p.text, p.category));
  if (action === 'reorder')   return makeResponse(reorderTodos(p.ids));
  if (action === 'detach')    return makeResponse(detachFile(p.id, p.fileId));
  if (action === 'important') return makeResponse(setImportant(p.id, p.value));
  return makeResponse({ error: 'Unknown action' });
}

function doPost(e) {
  let d;
  try { d = JSON.parse(e.postData.contents); } catch(err) { return makeResponse({ error: 'Invalid JSON' }); }
  if (d.token !== SECRET_TOKEN) return makeResponse({ error: 'Unauthorized' });
  if (d.action === 'attach') return makeResponse(attachFile(d.todoId, d.base64, d.mime, d.filename));
  return makeResponse({ error: 'Unknown action' });
}

function getSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(SHEET_NAME);
  if (!sheet) {
    sheet = ss.insertSheet(SHEET_NAME);
    sheet.appendRow(['id', 'text', 'status', 'created', 'done_at', 'category', 'order', 'attachments']);
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
      order: (r[6] !== '' && r[6] != null) ? Number(r[6]) : (i + 1) * 100,
      attachments: r[7] ? (function() { try { return JSON.parse(r[7]); } catch(e) { return []; } })() : [],
      important: r[8] === true || r[8] === 'TRUE'
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
  sheet.appendRow([id, text.trim(), 'pending', now, '', (category || '').trim(), maxOrd + 1, '']);
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
      // Delete attached Drive files
      try {
        const atts = data[i][7] ? JSON.parse(data[i][7]) : [];
        atts.forEach(a => { try { DriveApp.getFileById(a.id).setTrashed(true); } catch(e) {} });
      } catch(e) {}
      sheet.deleteRow(i + 1);
      return { success: true };
    }
  }
  return { error: 'Not found' };
}

function getAttachFolder() {
  const name = 'TODO_Attachments';
  const it = DriveApp.getFoldersByName(name);
  return it.hasNext() ? it.next() : DriveApp.createFolder(name);
}

function attachFile(todoId, base64, mime, filename) {
  if (!todoId || !base64) return { error: 'missing params' };
  try {
    const bytes = Utilities.base64Decode(base64);
    const file  = getAttachFolder().createFile(
      Utilities.newBlob(bytes, mime || 'application/octet-stream', filename || 'attachment')
    );
    file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
    const fileId = file.getId();
    const sheet  = getSheet();
    const data   = sheet.getDataRange().getValues();
    for (let i = 1; i < data.length; i++) {
      if (data[i][0] === todoId) {
        const list = data[i][7] ? (function() { try { return JSON.parse(data[i][7]); } catch(e) { return []; } })() : [];
        list.push({ id: fileId, name: filename, mime: mime });
        sheet.getRange(i + 1, 8).setValue(JSON.stringify(list));
        return { success: true, fileId };
      }
    }
    return { error: 'Todo not found' };
  } catch(e) {
    return { error: String(e) };
  }
}

function setImportant(id, value) {
  const sheet = getSheet();
  const data  = sheet.getDataRange().getValues();
  for (let i = 1; i < data.length; i++) {
    if (data[i][0] === id) {
      sheet.getRange(i + 1, 9).setValue(value === 'true');
      return { success: true };
    }
  }
  return { error: 'Not found' };
}

function detachFile(todoId, fileId) {
  try {
    const sheet = getSheet();
    const data  = sheet.getDataRange().getValues();
    for (let i = 1; i < data.length; i++) {
      if (data[i][0] === todoId) {
        const list    = data[i][7] ? JSON.parse(data[i][7]) : [];
        const updated = list.filter(f => f.id !== fileId);
        sheet.getRange(i + 1, 8).setValue(updated.length ? JSON.stringify(updated) : '');
        try { DriveApp.getFileById(fileId).setTrashed(true); } catch(e) {}
        return { success: true };
      }
    }
    return { error: 'Todo not found' };
  } catch(e) {
    return { error: String(e) };
  }
}

function makeResponse(data) {
  return ContentService
    .createTextOutput(JSON.stringify(data))
    .setMimeType(ContentService.MimeType.JSON);
}
