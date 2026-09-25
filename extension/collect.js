/*
 * 页面采集逻辑。既作为内容脚本被 chrome.scripting.executeScript({files:['collect.js']}) 注入到商品页，
 * 也被 dev/collect.test.html 用 <script src> 直接加载来测试其中的纯函数。
 * 所有逻辑挂在 globalThis.__OutfitCollect 上，不使用 ES module（避免需要构建工具）。
 */
(function (global) {
  'use strict';

  if (global.__OutfitCollect && global.__OutfitCollect.__loaded) {
    // 已经注入过，避免重复定义（popup 可能多次注入同一个 tab）
    return;
  }

  // ---- 平台识别，规则需和 server/resolvers/platforms.py 的 PLATFORMS 保持一致 ----
  var PLATFORMS = {
    taobao: ['taobao.com', 'tmall.com', 'tb.cn', 'alicdn.com'],
    jd: ['jd.com', '3.cn', 'jd.hk'],
    pdd: ['pinduoduo.com', 'yangkeduo.com'],
    douyin: ['douyin.com', 'iesdouyin.com'],
    vip: ['vip.com'],
    shein: ['shein.com'],
    shopee: ['shopee.'],
    lazada: ['lazada.'],
    zalora: ['zalora.'],
    amazon: ['amazon.', 'amzn.'],
    uniqlo: ['uniqlo.com'],
    zara: ['zara.com'],
    hm: ['hm.com'],
  };

  function detectPlatform(url) {
    if (!url) return 'unknown';
    var host;
    try {
      host = new URL(url).hostname.toLowerCase();
    } catch (e) {
      return 'unknown';
    }
    for (var name in PLATFORMS) {
      if (!Object.prototype.hasOwnProperty.call(PLATFORMS, name)) continue;
      var keys = PLATFORMS[name];
      for (var i = 0; i < keys.length; i++) {
        if (host.indexOf(keys[i]) !== -1) return name;
      }
    }
    return 'other';
  }

  // ---- 地址补全 ----
  function absolutizeUrl(url, baseUrl) {
    if (!url) return null;
    var trimmed = String(url).trim();
    if (!trimmed) return null;
    if (trimmed.indexOf('data:') === 0) return trimmed; // 已经是内联数据
    if (trimmed.indexOf('//') === 0) trimmed = 'https:' + trimmed;
    try {
      return new URL(trimmed, baseUrl || (global.location && global.location.href) || undefined).href;
    } catch (e) {
      return null;
    }
  }

  // ---- 缩略图后缀去除：规则写成可扩展列表 ----
  // 每条规则：test 命中才应用 replace；replace 是把命中部分替换为空或指定内容。
  var THUMBNAIL_SUFFIX_RULES = [
    // 淘宝/天猫：xxx.jpg_50x50.jpg / xxx.jpg_.webp / xxx.png_q90.jpg -> xxx.jpg
    // 注意：alicdn 真实图片文件名本身可能带下划线（如 O1CN01xxx_!!2217457947858.jpg），
    // 不能从第一个下划线开始整段截断，只能去掉"扩展名之后"的那一段缩略图后缀，
    // 否则会把文件名本身破坏掉导致图片 404（曾在真实淘宝页面上复现）。
    { test: /\.(jpg|jpeg|png|webp|gif|bmp)_[^/?#]*$/i, replace: /(\.(?:jpg|jpeg|png|webp|gif|bmp))_[^/?#]*$/i, with: '$1' },
    // 京东：xxx.jpg!q70 / xxx.jpg!cc_xxx -> xxx.jpg
    // 同上：必须紧跟在真实扩展名后面的 "!" 才当作京东后缀，否则会误伤文件名本身带 "!" 的地址
    // （例如 alicdn 的 xxx_!!shopId.jpg，去掉淘宝后缀后交给这条规则处理时曾把文件名切坏）。
    { test: /\.(jpg|jpeg|png|webp|gif|bmp)!\w[^/?#]*$/i, replace: /(\.(?:jpg|jpeg|png|webp|gif|bmp))!\w[^/?#]*$/i, with: '$1' },
    // 通用：文件名里带 _123x123 或 _123x123q90 的尺寸段（紧跟在扩展名前）-> 去掉尺寸段
    { test: /_\d{2,4}x\d{2,4}(?:q\d+)?(?=\.\w{2,5}(?:[?#].*)?$)/i, replace: /_\d{2,4}x\d{2,4}(?:q\d+)?(?=\.\w{2,5}(?:[?#].*)?$)/i, with: '' },
  ];

  function stripThumbnailSuffix(url) {
    if (!url) return url;
    var out = url;
    for (var i = 0; i < THUMBNAIL_SUFFIX_RULES.length; i++) {
      var rule = THUMBNAIL_SUFFIX_RULES[i];
      if (rule.test.test(out)) {
        out = out.replace(rule.replace, rule.with);
      }
    }
    return out;
  }

  // ---- 去重 + 按面积从大到小排序 ----
  function dedupeAndSortImages(images) {
    var byUrl = new Map();
    (images || []).forEach(function (img) {
      if (!img || !img.url) return;
      var area = (img.width || 0) * (img.height || 0);
      var existing = byUrl.get(img.url);
      if (!existing) {
        byUrl.set(img.url, { url: img.url, width: img.width || 0, height: img.height || 0 });
      } else {
        var existingArea = (existing.width || 0) * (existing.height || 0);
        if (area > existingArea) {
          existing.width = img.width || 0;
          existing.height = img.height || 0;
        }
      }
    });
    var list = Array.from(byUrl.values());
    list.sort(function (a, b) {
      return b.width * b.height - a.width * a.height;
    });
    return list;
  }

  function normalizeCandidate(rawUrl, baseUrl, width, height) {
    var abs = absolutizeUrl(rawUrl, baseUrl);
    if (!abs || abs.indexOf('data:') === 0) return null; // data URI 太占地方，不作为候选来源
    return { url: stripThumbnailSuffix(abs), width: width || 0, height: height || 0 };
  }

  // ---- JSON-LD Product 解析，逻辑对应 server/resolvers/generic_meta.py 的 _json_ld_products / parse_page ----
  function jsonLdProducts(doc) {
    var found = [];
    var scripts = doc.querySelectorAll('script[type="application/ld+json"]');
    scripts.forEach(function (el) {
      var data;
      try {
        data = JSON.parse(el.textContent);
      } catch (e) {
        return;
      }
      var stack = Array.isArray(data) ? data.slice() : [data];
      while (stack.length) {
        var item = stack.pop();
        if (!item || typeof item !== 'object') continue;
        if (Array.isArray(item['@graph'])) stack = stack.concat(item['@graph']);
        var types = item['@type'];
        types = Array.isArray(types) ? types : [types];
        if (types.indexOf('Product') !== -1 || types.indexOf('ProductGroup') !== -1) {
          found.push(item);
        }
      }
    });
    return found;
  }

  function metaContent(doc, prop) {
    var el = doc.querySelector('meta[property="' + prop + '"]') || doc.querySelector('meta[name="' + prop + '"]');
    return el ? el.getAttribute('content') : null;
  }

  function collectPageInfo(doc, baseUrl) {
    var title = null;
    var price = null;
    var jsonLdImages = [];

    var products = jsonLdProducts(doc);
    if (products.length) {
      var p = products[0];
      var imgs = p.image || [];
      imgs = Array.isArray(imgs) ? imgs : [imgs];
      jsonLdImages = imgs.map(function (i) {
        return typeof i === 'object' && i ? i.url : i;
      }).filter(Boolean);
      title = typeof p.name === 'string' ? p.name : null;
      var offers = p.offers || {};
      offers = Array.isArray(offers) ? (offers[0] || {}) : offers;
      if (offers && (offers.price || offers.lowPrice)) {
        var amount = offers.price || offers.lowPrice;
        var currency = offers.priceCurrency || '';
        price = (String(amount) + ' ' + currency).trim();
      }
    }

    var ogImage = metaContent(doc, 'og:image');
    if (!title) title = metaContent(doc, 'og:title');
    title = title || (doc.title || null);
    if (!price) price = metaContent(doc, 'product:price:amount');

    var candidateUrls = jsonLdImages.slice();
    if (ogImage) candidateUrls.push(ogImage);

    return {
      title: title,
      price: price,
      metaImageUrls: candidateUrls,
    };
  }

  // ---- 从 <img> 收集候选（懒加载属性列表可扩展） ----
  var LAZY_SRC_ATTRS = ['data-src', 'data-original', 'data-lazy-src', 'data-ks-lazyload', 'data-actualsrc', 'data-echo'];
  var MIN_RENDER_SIZE = 200;
  var MAX_CANDIDATES = 30;

  function collectImgElements(doc, baseUrl) {
    var out = [];
    var imgs = doc.querySelectorAll('img');
    imgs.forEach(function (img) {
      var w = img.offsetWidth || img.getBoundingClientRect().width || 0;
      var h = img.offsetHeight || img.getBoundingClientRect().height || 0;
      if (w < MIN_RENDER_SIZE || h < MIN_RENDER_SIZE) return;
      // 懒加载属性优先于 src：很多懒加载库会把 src 设成占位小图（例如跟踪像素 gif），
      // 真实大图地址放在 data-src 等属性里，只有 src 完全为空才去看懒加载属性会采到占位图
      // （曾在真实淘宝页面上复现：图文详情区的懒加载图片渲染尺寸很大，占位图被误当成主图选中）。
      var src = null;
      var fromLazyAttr = false;
      for (var i = 0; i < LAZY_SRC_ATTRS.length; i++) {
        var v = img.getAttribute(LAZY_SRC_ATTRS[i]);
        if (v) {
          src = v;
          fromLazyAttr = true;
          break;
        }
      }
      if (!src) src = img.currentSrc || img.getAttribute('src');
      if (!src) return;
      // 懒加载属性给的地址浏览器还没真正加载过，不知道真实分辨率；页面给懒加载占位框
      // 设置的展示尺寸经常比真正的主图还大（例如详情区大图），参与排序时如果直接用这个
      // 占位框尺寸计分，会把还没加载的详情图排到已经真实渲染出来的主图前面。按最低达标
      // 尺寸计分，让它们能被采到但不抢真正主图的排名（曾在真实淘宝页面上复现）。
      var scoreW = fromLazyAttr ? MIN_RENDER_SIZE : Math.round(w);
      var scoreH = fromLazyAttr ? MIN_RENDER_SIZE : Math.round(h);
      var cand = normalizeCandidate(src, baseUrl, scoreW, scoreH);
      if (cand) out.push(cand);
    });
    return out;
  }

  function collectPage() {
    var doc = global.document;
    var baseUrl = global.location.href;
    var info = collectPageInfo(doc, baseUrl);

    var candidates = [];
    info.metaImageUrls.forEach(function (u) {
      var cand = normalizeCandidate(u, baseUrl, 0, 0);
      if (cand) candidates.push(cand);
    });
    candidates = candidates.concat(collectImgElements(doc, baseUrl));

    var images = dedupeAndSortImages(candidates).slice(0, MAX_CANDIDATES);

    return {
      page: {
        url: baseUrl,
        title: info.title || null,
        price: info.price || null,
        platform: detectPlatform(baseUrl),
      },
      images: images,
    };
  }

  // ---- 发送前把图片转成 data_uri，兜底防盗链（在页面上下文里 fetch，带上页面自身的 Referer） ----
  var MAX_DATA_URI_BYTES = 8 * 1024 * 1024;

  function blobToDataURL(blob) {
    return new Promise(function (resolve, reject) {
      var reader = new FileReader();
      reader.onload = function () {
        resolve(reader.result);
      };
      reader.onerror = function () {
        reject(reader.error);
      };
      reader.readAsDataURL(blob);
    });
  }

  async function fetchAsDataUris(urls) {
    var results = [];
    for (var i = 0; i < urls.length; i++) {
      var url = urls[i];
      try {
        var resp = await fetch(url, { credentials: 'omit' });
        if (!resp.ok) {
          results.push({ url: url, data_uri: null });
          continue;
        }
        var blob = await resp.blob();
        if (blob.size > MAX_DATA_URI_BYTES) {
          results.push({ url: url, data_uri: null });
          continue;
        }
        var dataUri = await blobToDataURL(blob);
        results.push({ url: url, data_uri: dataUri });
      } catch (e) {
        results.push({ url: url, data_uri: null });
      }
    }
    return results;
  }

  global.__OutfitCollect = {
    __loaded: true,
    detectPlatform: detectPlatform,
    absolutizeUrl: absolutizeUrl,
    stripThumbnailSuffix: stripThumbnailSuffix,
    dedupeAndSortImages: dedupeAndSortImages,
    collectImgElements: collectImgElements,
    collectPage: collectPage,
    fetchAsDataUris: fetchAsDataUris,
  };
})(typeof window !== 'undefined' ? window : globalThis);
