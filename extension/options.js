'use strict';

var DEFAULT_SERVER = 'http://127.0.0.1:8000';

var els = {
  serverUrl: document.getElementById('serverUrl'),
  token: document.getElementById('token'),
  saveBtn: document.getElementById('saveBtn'),
  testBtn: document.getElementById('testBtn'),
  msg: document.getElementById('msg'),
};

function showMsg(text, kind) {
  els.msg.textContent = text;
  els.msg.className = kind || '';
}

function load() {
  chrome.storage.sync.get({ serverUrl: DEFAULT_SERVER, token: '' }, function (items) {
    els.serverUrl.value = items.serverUrl;
    els.token.value = items.token;
  });
}

function originPatternFor(url) {
  try {
    var u = new URL(url);
    return u.protocol + '//' + u.host + '/*';
  } catch (e) {
    return null;
  }
}

function isBuiltinAllowedOrigin(url) {
  try {
    var u = new URL(url);
    return u.hostname === '127.0.0.1' || u.hostname === 'localhost';
  } catch (e) {
    return false;
  }
}

async function ensureHostPermission(serverUrl) {
  if (isBuiltinAllowedOrigin(serverUrl)) return true;
  var pattern = originPatternFor(serverUrl);
  if (!pattern) return false;
  var already = await chrome.permissions.contains({ origins: [pattern] });
  if (already) return true;
  return chrome.permissions.request({ origins: [pattern] });
}

async function save() {
  var serverUrl = (els.serverUrl.value || DEFAULT_SERVER).trim().replace(/\/$/, '');
  var token = els.token.value.trim();

  var granted = await ensureHostPermission(serverUrl);
  if (!granted) {
    showMsg('需要授权访问该服务器地址才能保存，请重试并允许权限请求。', 'err');
    return;
  }

  chrome.storage.sync.set({ serverUrl: serverUrl, token: token }, function () {
    showMsg('已保存。', 'ok');
  });
}

async function testConnection() {
  var serverUrl = (els.serverUrl.value || DEFAULT_SERVER).trim().replace(/\/$/, '');
  var token = els.token.value.trim();

  var granted = await ensureHostPermission(serverUrl);
  if (!granted) {
    showMsg('需要授权访问该服务器地址才能测试连接。', 'err');
    return;
  }

  showMsg('正在测试…', '');
  var headers = {};
  if (token) headers['Authorization'] = 'Bearer ' + token;

  try {
    var resp = await fetch(serverUrl + '/api/status', { headers: headers });
    if (resp.ok) {
      showMsg('连接成功。', 'ok');
    } else if (resp.status === 401) {
      showMsg('连接成功，但令牌不正确（401）。', 'err');
    } else {
      showMsg('服务器返回错误（' + resp.status + '）。', 'err');
    }
  } catch (e) {
    showMsg('无法连接，请确认穿搭工具正在运行，且服务器地址正确。', 'err');
  }
}

els.saveBtn.addEventListener('click', save);
els.testBtn.addEventListener('click', testConnection);

load();
