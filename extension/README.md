# 穿搭试衣助手 - 浏览器插件

在任意电商商品页上，点击插件图标 → 勾选商品图 → 一键加入穿搭试衣工具的衣橱。纯原生 JavaScript（Manifest V3），不需要 Node.js、不需要构建。

## 安装（开发者模式）

1. Chrome 打开 `chrome://extensions`（Edge 打开 `edge://extensions`）。
2. 右上角打开"开发者模式"。
3. 点击"加载已解压的扩展程序"，选择本目录 `extension/`。
4. 安装后点击浏览器工具栏的插件图标，右键"选项"（或在插件详情页点"扩展程序选项"）可以打开设置页，填服务器地址和访问令牌。

## 使用

1. 打开一个商品页。
2. 点击插件图标，弹窗会自动读取当前页面的候选图片，默认勾选面积最大的一张。
3. 需要的话，给每张图选一个类型（不选 / 上衣 / 外套 / 裤子 / 半身裙 / 连衣裙）；不选的话由后端 AI 识别。
4. 点击"加入衣橱"。成功后会显示已加入的件数和"打开衣橱"链接。

## 权限说明

- `activeTab`：只在你点击插件图标时读取当前这一个页面，不在后台运行。
- `scripting`：往当前页面注入采集脚本 `collect.js`。
- `storage`：保存服务器地址和访问令牌（`chrome.storage.sync`）。
- `host_permissions` 固定包含 `http://127.0.0.1/*` 和 `http://localhost/*`（默认服务器地址）。
- 如果在设置页填了其他服务器地址（比如局域网 IP 或域名），保存时会弹出浏览器自己的权限确认框，只授权这一个地址（`optional_host_permissions`），不会申请访问所有网站。
- 不申请 `tabs`、`history`、`cookies`、`webRequest`。

## 目录结构

```
extension/
  manifest.json                 Manifest V3 配置
  _locales/{zh_CN,en}/messages.json   插件名称/描述的中英文
  popup.html / popup.css / popup.js   点击图标弹出的主界面
  options.html / options.js           设置页：服务器地址、令牌、测试连接
  collect.js                          注入页面的采集逻辑（地址补全/去缩略图后缀/去重排序等纯函数 + DOM 采集 + 防盗链兜底 fetch）
  icons/                               图标（PNG，脚本手工生成，未使用网络素材）
  dev/mock_server.py                   开发测试用的假服务器
  dev/collect.test.html                collect.js 纯函数的浏览器内断言测试
```

## 本地测试

### 1. 启动假服务器
```bash
python extension/dev/mock_server.py
# 或者测试鉴权：python extension/dev/mock_server.py --token secret123
```
默认监听 `http://127.0.0.1:8000`，实现了 `GET /api/status` 和 `POST /api/import/images`，收到请求会把摘要（图片数量、每张是 url 还是 data_uri、source）打印到控制台。设置页填的服务器地址、访问令牌要和这里的端口/`--token` 对上。

### 2. 纯函数测试（地址补全、去缩略图后缀、去重排序、平台识别）
用任意本地 HTTP 服务器打开 `extension/dev/collect.test.html`（直接用 `file://` 打开会因为脚本跨域限制无法加载 `../collect.js`，必须走 http）：
```bash
python -m http.server 8901 --directory extension
# 浏览器打开 http://127.0.0.1:8901/dev/collect.test.html，页面会显示每条断言的通过/失败
```
已验证 19/19 通过。

### 3. 加载插件、真实商品页测试
在开发者模式下加载 `extension/` 后，建议至少测试这三类页面：
- 优衣库商品页，例如 <https://www.uniqlo.com/us/en/products/E422992-000/00>（海外站，`generic_meta` 类思路应该能拿到 JSON-LD/og 图）。
- 一个淘宝或天猫商品页（这类页面通常有登录/验证拦截，服务端解析不了，正是插件要覆盖的场景）。
- 一个非商品页（比如普通新闻页或 `chrome://` 页面），确认弹窗给出"没有找到可用的商品图"之类的友好提示，而不是报错。

## 已知限制

- 缩略图后缀去除规则是按淘宝/天猫（`_WxH`/`_.webp` 后缀）、京东（`!q70` 后缀）和通用 `_WxH` 模式写的可扩展列表（见 `collect.js` 的 `THUMBNAIL_SUFFIX_RULES`），遇到新平台的新规则需要继续往列表里加。
- 图片防盗链兜底是在页面上下文里 `fetch()` 转 `data_uri`，遇到服务器发送严格 CSP（`connect-src` 限制）的页面时可能会被页面自己的 CSP 拦截而失败；这种情况会自动退回只发 `url`，交给后端下载。
- 懒加载图片属性列表（`data-src` 等）覆盖常见命名，遇到新站点用了列表之外的属性名需要继续扩展 `LAZY_SRC_ATTRS`。
