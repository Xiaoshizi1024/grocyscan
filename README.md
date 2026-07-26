# GrocyScan — 移动端条码/商品图像识别与出入库 Web 应用

> 基于 Grocy 的家庭库存管理配套扫描应用。
> 通过手机浏览器直接调用摄像头，扫描商品条形码并自动完成出入库。

---

## 核心架构：三引擎渐进降级

```
Native BarcodeDetector (浏览器原生)
  ↓ 不支持或失败
QuaggaJS (专用 1D 条码引擎)
  ↓ 不支持或失败
ZXing / html5-qrcode (通用 JS 引擎)
```

| 引擎 | 支持格式 | 优势 | 局限 |
|---|---|---|---|
| **BarcodeDetector** | EAN-13, QR, DataMatrix, PDF-417 | 浏览器原生，性能最佳 | Android 7+ Chrome/Edge 需信任 HTTPS 证书 |
| **QuaggaJS** | EAN-13, Code-128, UPC-A/E 等 | 专用 1D 引擎，ROI 区域扫描 | 2019 年停维护，部分浏览器 Web Worker 兼容性差 |
| **ZXing** | EAN-13, Code-128, QR 等 15+ 格式 | 纯 JS，最广泛兼容 | CPU 软解，4K 摄像头下可能卡顿 |

---

## 关键特性

- **HTTPS 自签证书**（端口 9290）：满足 BarcodeDetector 安全上下文要求
- **HTTP-only 端口**（端口 9291）：用于开发调试，自带 CORS 头
- **三引擎自动降级**：逐级回退，确保各浏览器下都有扫码能力
- **ROI 区域扫描**：Quagga 仅对取景框中心区域解码，提升速度
- **1D 条码优化**：ZXing 显式配置 EAN-13 格式 ID（修复默认不识别问题）
- **CORS 完整支持**：OPTIONS 预检请求处理，跨域调用无阻碍
- **`/update` 端点**：通过浏览器直接上传文件更新容器内应用
- **`/health` 端点**：状态检查，含 Grocy API Key 验证
- **ApiZero 直连查询**：跳过 Grocy 插件，直接调 ApiZero 查询商品信息并自动预填

---

## 部署方式

### 方式一：Docker（推荐）

```bash
docker run -d \
  --name grocyscan \
  -p 9290:9290 \
  -p 9291:9291 \
  -v $(pwd):/data \
  python:3.9-slim \
  sh -c "cd /data && python3 grocyscan_app.py"
```

### 方式二：直接运行

```bash
python3 grocyscan_app.py
```

### 方式三：Docker Compose

见 `docker-compose.yml`。

---

## 配置说明

应用支持**两种方式**提供配置，按优先级递减：

| 优先级 | 方式 | 说明 |
|---|---|---|
| 1 | **环境变量** | `GROCY_URL`、`GROCY_API_KEY`、`APIZERO_KEY` 等 |
| 2 | **配置文件** | `apizero_key` 文件（仅 ApiZero Key） |

### 环境变量（推荐）

复制 `.env.example` 为 `.env`，填入实际值后通过 Docker 或系统注入：

```bash
# 复制模板
cp .env.example .env

# 编辑 .env，填入 Grocy 和 ApiZero 信息
vim .env
```

**Docker Compose 方式**：在 `docker-compose.yml` 中通过 `env_file` 引用：

```yaml
services:
  grocyscan:
    build: .
    env_file: .env
    # ...
```

**直接 Docker run 方式**：

```bash
docker run -d \
  --name grocyscan \
  -p 9290:9290 -p 9291:9291 \
  --env-file .env \
  python:3.9-slim \
  sh -c "cd /data && python3 grocyscan_app.py"
```

### 文件方式（仅 ApiZero Key）

在应用同目录下创建 `apizero_key` 文件，内容就是你的 ApiZero Key：

```bash
# 复制模板
cp apizero_key.example apizero_key

# 编辑填入 Key
vim apizero_key
```

> 环境变量 `APIZERO_KEY` 优先级更高，如果两者都设置了，以环境变量为准。

### 配置文件示例

| 变量名 | 必填 | 说明 |
|---|---|---|
| `GROCY_URL` | 是 | Grocy 的 Web 访问地址，如 `http://192.168.1.100:9283` |
| `GROCY_API_KEY` | 是 | Grocy API Key，在 Grocy → 设置 → 系统 → API 中生成 |
| `APIZERO_KEY` | 否 | ApiZero 付费 Key，注册地址 [apizero.cn](https://www.apizero.cn/) |
| `PORT` | 否 | HTTPS 端口，默认 9290 |
| `HTTP_PORT` | 否 | HTTP-only 端口，默认 9291 |

---

## ApiZero 条码查询集成

### 为什么需要 ApiZero？

Grocy 扫描条码后，如果库内没有该商品，会弹出一个空白表单让你手动填写。有了 ApiZero：

```
扫描条码 → 库内无此商品 → 直连 ApiZero 查询 → 自动预填商品名称/品牌/规格/图片
```

**不再需要手动输入商品信息**，扫描即入库。

### 工作原理

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│  手机扫码     │ ──▶ │  grocyscan_app.py │ ──▶ │  ApiZero API │
│  获取条码     │     │  查询 ApiZero      │     │  返回商品信息 │
└──────────────┘     └──────────────────┘     └─────────────┘
                                │
                                ▼
                         ┌──────────────────┐
                         │  Grocy API       │
                         │  创建产品并入库   │
                         └──────────────────┘
```

### 代码集成说明

**Key 读取**（`grocyscan_app.py` 第 101-114 行）：

```python
def load_apizero_key():
    """从 环境变量 APIZERO_KEY 或 同目录 apizero_key 文件 读取付费 Key。
    优先级: 环境变量 > 文件。文件为空/不存在则返回空字符串(此时不调 apizero)。"""
    k = (os.environ.get("APIZERO_KEY") or "").strip()
    if k:
        return k
    # 回退到文件方式
    p = os.path.join(BASE, "apizero_key")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""
```

**查询逻辑**（`grocyscan_app.py` 第 149-171 行）：

```python
def apizero_lookup(barcode):
    """带付费 Key 查询 apizero。PRO 版优先, 失败回落免费版。无 Key 或查不到返回 None。"""
    key = load_apizero_key()
    if not key:
        return None
    # 尝试两个接口（PRO 版 barcode-gs1 优先，免费版 barcode-lookup 后备）
    candidates = [
        "https://v1.apizero.cn/api/barcode-gs1?code=%s&key=%s",
        "https://v1.apizero.cn/api/barcode-lookup?barcode=%s&key=%s",
    ]
    for tpl in candidates:
        url = tpl % (urllib.parse.quote(barcode), urllib.parse.quote(key))
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "grocyscan/1.0"})
            with urllib.request.urlopen(req, timeout=12) as r:
                j = json.loads(r.read().decode("utf-8"))
        except Exception:
            continue
        info = _parse_apizero(j)
        if info:
            return info
    return None
```

**信息解析**（`grocyscan_app.py` 第 116-147 行）：

兼容 ApiZero 两个版本的返回格式：
- **PRO 版**（`barcode-gs1`）：字段在顶层
- **免费版**（`barcode-lookup`）：字段包在 `data` 对象内

解析出 `name`（商品名）、`brand`（品牌）、`category`（分类）、`specification`（规格）、`image`（商品图）等信息。

**建档时自动预填**（`grocyscan_app.py` 第 208-215 行）：

```python
# 3) 库内无此条码 -> 用 apizero 付费 Key 直连查询商品信息(成功则预填到新建表单)
if st != 200:
    info = apizero_lookup(barcode)
    if info:
        product_name = info["name"]
        description = info.get("description", "")
        image_url = info.get("image_url", "")
        # ... 自动创建产品并入库
```

**图片下载与上传**（`grocyscan_app.py` 第 294-300 行）：

ApiZero 返回的商品图片 URL 会自动下载，上传到 Grocy 作为产品图片。

### 启用 ApiZero 只需两步

1. **注册并获取 Key**：访问 [apizero.cn](https://www.apizero.cn/) 注册，购买付费套餐（免费额度有限）
2. **配置 Key**：任选一种方式

   **方式 A（推荐）—— `.env` 文件**：
   ```bash
   cp .env.example .env
   # 编辑 .env，填入 APIZERO_KEY=你的Key
   ```

   **方式 B —— `apizero_key` 文件**：
   ```bash
   cp apizero_key.example apizero_key
   # 编辑 apizero_key，填入 Key
   ```

3. **重启容器**：
   ```bash
   docker restart grocyscan
   ```

4. **验证**：访问 `https://your-domain:9290/health`，返回 JSON 中 `apizero_on` 应为 `true`。

---

## 与 Grocy 的集成

### 条码查询流程

```
1. 扫描条码
2. 查询库内是否有此条码产品（GET /api/stock/products/by-barcode/{code}）
3. 有 → 返回产品 ID，进入出入库选择
4. 无 → 调用 ApiZero 查询商品信息 → 自动创建产品并预填表单
```

### 需要配置的 Grocy API Key

在 Grocy 中生成：

1. 打开 Grocy Web 界面
2. 进入 **设置 → 系统 → API**
3. 点击 **生成** 创建 API Key
4. 将此 Key 填入 `GROCY_API_KEY` 环境变量

### 条码查询插件

GrocyScan 内置了 ApiZero 直连查询，**无需额外安装 Grocy 插件**。

如果你需要在 Grocy 中直接安装 ApiZero 插件，仓库提供了示例插件文件：
- `ApiZeroBarcodeLookupPlugin.php` — 基础版
- `ApiZeroCombo.BarcodeLookupPlugin.php` — 组合版（含额外功能）

> 注意：使用 GrocyScan 直连时，Grocy 侧的插件并非必须，但保留插件可以在 Grocy Web 界面中也能自动查询商品信息。

---

## 更新应用

容器运行后，通过浏览器访问 `/update` 端点即可上传新文件并自动重载：
```
https://your-domain:9290/update
```

支持上传的文件类型：
- `.py` — 后端代码（自动重启）
- `.html` / `.js` — 前端文件（刷新浏览器即可）

---

## 关键坑（部署必看）

### 1. HTTPS 证书问题（最重要）
- Android 7+ 的 Chrome/Edge 对自签 HTTPS 证书**不信任**
- 解决方案：
  - 使用 **ngrok** / **cloudflared** 提供正规 HTTPS 证书
  - 或使用夸克/Firefox 浏览器（不严格校验自签证书）
- **`Connection: close` 响应头**：HTTP/1.0 服务器默认不关闭连接，`fetch` 会永远挂起，必须在响应头中加入 `Connection: close`

### 2. Python 字节码缓存
- 修改 `.py` 后如果 Python 使用了旧的 `__pycache__/*.pyc`，改动不会生效
- 每次修改后必须执行：`rm -rf __pycache__/` 再重启容器

### 3. 浏览器兼容性

| 浏览器 | BarcodeDetector | Quagga | ZXing | 推荐 |
|---|---|---|---|---|
| Chrome (Android) | ✅ | ✅ | ✅ | 最佳 |
| Edge (Android) | ✅ | ✅ | ✅ | 证书问题需注意 |
| 夸克 | ❌ | ❌ | ✅ | 用 ZXing |
| Firefox | ❌ | ⚠️ | ✅ | 用 ZXing |

### 4. 端口说明
- **9290（HTTPS）**：生产使用，需信任证书
- **9291（HTTP）**：开发调试，带 CORS，跨域访问无限制

---

## 文件结构

```
grocyscan/
├── grocyscan_app.py         # 后端 HTTP 服务器（含 TLS、CORS、API 代理）
├── index.html               # 扫码页面（三引擎 UI 集成）
├── scan-diag.html           # 浏览器能力诊断页
├── quagga.min.js            # QuaggaJS 引擎
├── html5-qrcode.min.js      # ZXing 引擎
├── ApiZeroBarcodeLookupPlugin.php  # Grocy 条码查询插件（基础版）
├── Dockerfile               # Docker 构建文件
├── docker-compose.yml       # Docker Compose 配置
├── .env.example             # 环境变量模板
├── apizero_key.example      # ApiZero Key 文件模板
├── .gitignore
└── README.md
```

---

## 相关项目

- [Grocy](https://github.com/grocy/grocy) — 家庭库存管理后端
- [osnsyc/GrocyCompanionCN](https://github.com/osnsyc/GrocyCompanionCN) — Grocy 中文配套应用
- [huzheyi/grocycompanioncn](https://github.com/huzheyi/grocycompanioncn) — 另一中文配套版本
- [ApiZero](https://www.apizero.cn/) — 商品条码数据库 API

---

## 许可证

MIT
