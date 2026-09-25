# web：网页前端

React 19 + TypeScript + Vite，中英双语、深浅色主题、手机端适配。构建产物 `dist/` 由后端直接托管（`http://127.0.0.1:8000`）。

```powershell
npm install
npm run dev          # 开发服务器，接口默认指向同源后端
npm run build        # 生成 dist/，后端会自动托管
npm run lint         # oxlint
$env:VITE_MOCK="1"; npm run dev   # 使用内置假接口，不需要启动后端
```

| 目录 | 内容 |
|---|---|
| `src/api/` | 接口客户端（字段与 `server/api/schemas.py` 一致）与假接口 `mock.ts` |
| `src/pages/` | 衣橱、搭配台、结果、历史、设置、关于页 |
| `src/components/` `src/hooks/` | 通用组件、任务轮询等 |
| `src/i18n/` `src/theme/` `src/auth/` | 多语言、主题、邀请码登录 |
