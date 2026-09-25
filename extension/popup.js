'use strict';

var CATEGORY_OPTIONS = [
  { value: '', label: '不选' },
  { value: 'top', label: '上衣' },
  { value: 'outer', label: '外套' },
  { value: 'bottom', label: '裤子' },
  { value: 'skirt', label: '半身裙' },
  { value: 'dress', label: '连衣裙' },
];

var DEFAULT_SERVER = 'http://127.0.0.1:8000';

var els = {
  status: document.getElementById('status'),
  grid: document.getElementById('grid'),
  emptyState: document.getElementById('emptyState'),
  submitBtn: document.getElementById('submitBtn'),
  resultMsg: document.getElementById('resultMsg'),
  openOptions: document.getElementById('openOptions'),
};

var state = {
  pageInfo: null,
  items: [], // { url, width, height, selected, category }
};

els.openOptions.addEventListener('click', function () {
  chrome.runtime.openOptionsPage();
});

function getSettings() {
  return new Promise(function (resolve) {
    chrome.storage.sync.get({ serverUrl: DEFAULT_SERVER, token: '' }, function (items) {
      resolve(items);
    });
  });
}

function getActiveTab() {
  return new Promise(function (resolve, reject) {
    chrome.tabs.query({ active: true, currentWindow: true }, function (tabs) {
      if (chrome.runtime.lastError || !tabs || !tabs[0]) {
        reject(new Error('no_active_tab'));
        return;
      }
      resolve(tabs[0]);
    });
  });
}

function execFiles(tabId, files) {
  return chrome.scripting.executeScript({ target: { tabId: tabId }, files: files });
}

function execFunc(tabId, func, args) {
  return chrome.scripting.executeScript({ target: { tabId: tabId }, func: func, args: args || [] });
}

function setResult(text, kind) {
  els.resultMsg.hidden = !text;
  els.resultMsg.className = 'result-msg' + (kind ? ' ' + kind : '');
  els.resultMsg.innerHTML = text || '';
}

function updateSubmitState() {
  var count = state.items.filter(function (i) {
    return i.selected;
  }).length;
  els.submitBtn.disabled = count === 0;
  els.submitBtn.textContent = count > 0 ? '加入衣橱（' + count + '）' : '加入衣橱';
}

function renderGrid() {
  els.grid.innerHTML = '';
  state.items.forEach(function (item, index) {
    var cell = document.createElement('div');
    cell.className = 'cell' + (item.selected ? ' selected' : '');

    var check = document.createElement('div');
    check.className = 'check';
    check.textContent = item.selected ? '✓' : '';
    cell.appendChild(check);

    var img = document.createElement('img');
    img.src = item.url;
    img.loading = 'lazy';
    img.addEventListener('error', function () {
      cell.style.display = 'none';
    });
    cell.appendChild(img);

    var select = document.createElement('select');
    CATEGORY_OPTIONS.forEach(function (opt) {
      var optEl = document.createElement('option');
      optEl.value = opt.value;
      optEl.textContent = opt.label;
      if (opt.value === item.category) optEl.selected = true;
      select.appendChild(optEl);
    });
    select.addEventListener('click', function (e) {
      e.stopPropagation();
    });
    select.addEventListener('change', function () {
      item.category = select.value;
    });
    cell.appendChild(select);

    cell.addEventListener('click', function () {
      item.selected = !item.selected;
      cell.classList.toggle('selected', item.selected);
      check.textContent = item.selected ? '✓' : '';
      updateSubmitState();
    });

    els.grid.appendChild(cell);
  });
}

async function init() {
  var tab;
  try {
    tab = await getActiveTab();
  } catch (e) {
    els.status.textContent = '无法获取当前页面。';
    return;
  }

  if (!tab.url || !/^https?:/i.test(tab.url)) {
    els.status.hidden = true;
    els.emptyState.hidden = false;
    els.emptyState.textContent = '这个页面没有找到可用的商品图。';
    return;
  }

  var collected;
  try {
    await execFiles(tab.id, ['collect.js']);
    var results = await execFunc(tab.id, function () {
      return window.__OutfitCollect ? window.__OutfitCollect.collectPage() : null;
    });
    collected = results && results[0] && results[0].result;
  } catch (e) {
    els.status.textContent = '这个页面无法读取（插件权限不足或页面受限）。';
    return;
  }

  if (!collected || !collected.images || collected.images.length === 0) {
    els.status.hidden = true;
    els.emptyState.hidden = false;
    return;
  }

  state.pageInfo = collected.page;
  state.items = collected.images.map(function (img, idx) {
    return { url: img.url, width: img.width, height: img.height, selected: idx === 0, category: '' };
  });

  els.status.hidden = true;
  els.grid.hidden = false;
  renderGrid();
  updateSubmitState();
}

async function submit() {
  var selected = state.items.filter(function (i) {
    return i.selected;
  });
  if (selected.length === 0) return;

  els.submitBtn.disabled = true;
  setResult('正在发送…', '');

  var settings = await getSettings();
  var tab;
  try {
    tab = await getActiveTab();
  } catch (e) {
    setResult('无法获取当前页面。', 'err');
    els.submitBtn.disabled = false;
    return;
  }

  var dataUriMap = {};
  try {
    await execFiles(tab.id, ['collect.js']);
    var urls = selected.map(function (i) {
      return i.url;
    });
    var results = await execFunc(
      tab.id,
      function (urlList) {
        return window.__OutfitCollect.fetchAsDataUris(urlList);
      },
      [urls]
    );
    var fetched = (results && results[0] && results[0].result) || [];
    fetched.forEach(function (item) {
      if (item && item.data_uri) dataUriMap[item.url] = item.data_uri;
    });
  } catch (e) {
    // 兜底转换失败也不影响发送，服务端会自己下载 url
  }

  var images = selected.map(function (i) {
    var entry = dataUriMap[i.url] ? { data_uri: dataUriMap[i.url] } : { url: i.url };
    if (i.category) entry.category = i.category;
    return entry;
  });

  var body = {
    images: images,
    source: {
      url: state.pageInfo.url,
      title: state.pageInfo.title,
      platform: state.pageInfo.platform,
      price: state.pageInfo.price,
    },
  };

  var serverUrl = (settings.serverUrl || DEFAULT_SERVER).replace(/\/$/, '');
  var headers = { 'Content-Type': 'application/json' };
  if (settings.token) headers['Authorization'] = 'Bearer ' + settings.token;

  try {
    var resp = await fetch(serverUrl + '/api/import/images', {
      method: 'POST',
      headers: headers,
      body: JSON.stringify(body),
    });
    if (resp.ok) {
      var data = await resp.json();
      var count = (data.items || []).length;
      setResult('已加入 ' + count + ' 件，识别中… <a href="' + serverUrl + '/" target="_blank">打开衣橱</a>', 'ok');
    } else {
      var err;
      try {
        err = await resp.json();
      } catch (e) {
        err = null;
      }
      var message = (err && err.error && err.error.message) || '发送失败（' + resp.status + '）。';
      setResult(message, 'err');
    }
  } catch (e) {
    setResult('请确认穿搭工具正在运行，或在设置里检查服务器地址。', 'err');
  } finally {
    els.submitBtn.disabled = false;
  }
}

els.submitBtn.addEventListener('click', submit);

init();
