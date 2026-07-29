# GrocyScan · 手机扫码出入库

基于 Grocy 的库存管理配套扫描应用。通过手机浏览器直接调用摄像头，扫描商品条码自动完成出入库。

## 版本

**v2.3.1** (2026-07-29) — 稳定性修复版本

## 新增功能 (v2.3.x)

- 扫码成功 Toast 提示（含商品名称）
- 预览区显示模式标签（← 入库 / → 出库）
- 已有商品可选位置（location selector）
- 无图片时显示 SVG 占位图
- 确认写入时显示商品名×数量
- 自动滚动到预览区域
- 镜头不再反复重启（消除卡顿）
- 原生引擎连续扫码不再卡死
- ZXing/Quagga 引擎画面正确显示
- 全部 DOM 操作空值保护，消除随机崩溃
- 引擎切换前清理摄像头资源
- Cache busting（`?v=N`）解决缓存问题
- `/api/health` 健康检查端点

## 核心架构：三引擎渐进降级

```
Native BarcodeDetector (浏览器原生)
  ↓ 不支持或失败 → QuaggaJS (专用 1D)
  ↓ 不支持或失败 → ZXing / html5-qrcode (通用 JS)
```

| 引擎 | 优势 | 局限 |
|---|---|---|
| **BarcodeDetector** | 浏览器原生，性能最佳 | 需 HTTPS + 特定浏览器版本 |
| **QuaggaJS** | ROI 区域扫描，1D 条码专用 | 2019 年停维护，Web Worker 兼容性差 |
| **ZXing** | 纯 JS，最广泛兼容，15+ 格式 | 软件解码，低端机可能卡顿 |

## 快速开始

### 环境变量

| 变量 | 说明 | 必填 |
|---|---|---|
| `GROCY_URL` | Grocy 地址，默认 `http://172.17.0.1:9283` | 否 |
| `GROCY_API_KEY` | Grocy API 密钥 | **是** |
| `APIZERO_KEY` | ApiZero 付费 Key（商品信息自动填充） | 否 |
| `PORT` | HTTPS 端口，默认 9290 | 否 |

### Docker 运行

```bash
docker run -d --restart unless-stopped --name grocyscan \
  -p 9290:9290 -p 9291:9291 \
  -e GROCY_API_KEY=你的密钥 \
  -e GROCY_URL=http://192.168.1.x:9283 \
  -v /path/to/data:/data \
  leo000/grocyscan
```

- 9290: HTTPS（自签证书，摄像头扫码用）
- 9291: HTTP（用于 cloudflared/ngrok 隧道）

### Cloudflare Tunnel

```bash
cloudflared tunnel --url http://localhost:9291
```

首次访问需信任自签 CA 证书：`https://你的地址:9290/cert`

## 文件说明

| 文件 | 用途 |
|---|---|
| `grocyscan_app.py` | Python 后端（HTTPS + HTTP + Grocy 代理） |
| `app.js` | 前端 JavaScript（扫码引擎 + UI） |
| `index.html` | 前端页面 |
| `html5-qrcode.min.js` | ZXing 扫码引擎 |
| `quagga.min.js` | QuaggaJS 扫码引擎 |
| `cert.pem` / `key.pem` | 自签 SSL 证书 |
| `apizero_key` | ApiZero 付费密钥文件 |

## 端口说明

- **9290** — HTTPS（自带自签证书），主扫码端口
- **9291** — HTTP-only，专用于 cloudflared/ngrok 等隧道后端

## 更新

通过浏览器访问 `/update` 端点可直接上传文件更新容器内应用，无需 SSH。

## License

MIT
