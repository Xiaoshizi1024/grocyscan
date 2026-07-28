#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grocy 手机扫码录入 - 轻量后端 (纯 Python 标准库, 零第三方依赖)
版本: V2.01 (2026-07-27)
  V2.01: 新增 userfields 写入 (PUT /api/userfields/products/{id}), 支持 brand/category/manufacturer/net_content/feature 自定义字段
职责:
  1. 提供 HTTPS (自签证书) -> 手机浏览器才允许开摄像头
  2. 代理 Grocy API (服务端注入 GROCY-API-KEY, 避免浏览器跨域 + 隐藏密钥)
  3. 条码查询: 先查库内产品, 查不到则触发外部条码插件(apizero) add=true 自动建档
  4. apizero 商品字段写入 Grocy 自定义字段 (userfields), 不再拼进 description
环境变量:
  GROCY_URL       Grocy 地址, 默认 http://172.17.0.1:9283 (docker 网关回连宿主发布端口)
  GROCY_API_KEY   Grocy API 密钥 (必填)
  PORT            监听端口, 默认 9290
"""

VERSION = "2.01"
import os
import ssl
import json
import base64
import subprocess
import urllib.request
import urllib.parse
import urllib.error
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

GROCY_URL = os.environ.get("GROCY_URL", "http://172.17.0.1:9283").rstrip("/")
API_KEY = os.environ.get("GROCY_API_KEY", "").strip()
PORT = int(os.environ.get("PORT", "9290"))
BASE = os.path.dirname(os.path.abspath(__file__))


# ---------------- Grocy 请求封装 ----------------
def grocy(method, path, body=None, want_bytes=False):
    url = GROCY_URL + path
    headers = {"GROCY-API-KEY": API_KEY, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            raw = r.read()
            ct = r.headers.get("Content-Type", "")
            return r.status, ct, raw
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()
    except Exception as e:
        return 599, "text/plain", str(e).encode("utf-8")


def parse_details(raw):
    """解析 by-barcode 返回的产品详情"""
    try:
        j = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    prod = j.get("product") or {}
    if not prod.get("id"):
        return None
    return {
        "found": True,
        "product_id": prod.get("id"),
        "name": prod.get("name", ""),
        "description": prod.get("description", "") or "",
        "picture_file_name": prod.get("picture_file_name", "") or "",
        "stock_amount": j.get("stock_amount", 0),
        "qu_stock": (j.get("quantity_unit_stock") or {}).get("name", ""),
    }


def ensure_grocy_basics():
    """Grocy 外部条码插件的硬性前提: 至少存在一个"位置"和一个"数量单位"。
    若用户尚未配置, 这里自动建好默认值(默认位置/个), 让扫码做到零配置可用。
    任何一步失败都静默忽略 —— 失败时插件会抛清晰中文错误提示用户去配。
    """
    try:
        # 位置
        st, _, raw = grocy("GET", "/api/objects/locations")
        if st == 200:
            try:
                locs = json.loads(raw.decode("utf-8")) or []
            except Exception:
                locs = []
            if len(locs) == 0:
                grocy("POST", "/api/objects/locations",
                      {"name": "默认位置", "description": "扫码自动创建"})
        # 数量单位
        st2, _, raw2 = grocy("GET", "/api/objects/quantity_units")
        if st2 == 200:
            try:
                qus = json.loads(raw2.decode("utf-8")) or []
            except Exception:
                qus = []
            if len(qus) == 0:
                grocy("POST", "/api/objects/quantity_units",
                      {"name": "个", "name_plural": "个", "description": "扫码自动创建"})
    except Exception:
        pass


# ---------------- apizero 商品信息（带付费 Key 直连，不经过 Grocy 插件）----------------
def load_apizero_key():
    """从 环境变量 APIZERO_KEY 或 同目录 apizero_key 文件 读取付费 Key。
    优先级: 环境变量 > 文件。文件为空/不存在则返回空字符串(此时不调 apizero, 退回手动填表)。"""
    k = (os.environ.get("APIZERO_KEY") or "").strip()
    if k:
        return k
    p = os.path.join(BASE, "apizero_key")
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def _parse_apizero(j):
    """解析 apizero 返回: 兼容 PRO 版(barcode-gs1, 顶层字段) 与 免费版(barcode-lookup, 包在 data 内)。

    返回结构化数据:
      - name: 产品名称
      - image_url: 产品图片 URL
      - userfields: Grocy 自定义字段映射 (key-value, 对应 userfields 表的 name 字段)
        brand      -> 品牌
        category   -> 类别
        feature    -> 产品特征 (多行文本, 含规格/净含量/产地等)
        manufacturer -> 生产商列表
        net_content  -> 净含量
      - description: 备用文本 (兼容旧代码, 合并全部信息)
    """
    if not isinstance(j, dict):
        return None
    data = j.get("data") or {}
    src = data if data else j
    name = (src.get("name") or j.get("name") or "").strip()
    if not name:
        return None  # 未登记或无名称 -> 视为查不到

    brand = (src.get("brand") or "").strip()
    cat = (src.get("category") or "").strip()
    mf = (src.get("manufacturer") or "").strip()
    # 规格: gs1 用 specification, lookup 用 spec
    spec = (src.get("specification") or src.get("spec") or "").strip()
    net = (src.get("net_content") or "").strip()
    general_name = (src.get("general_name") or "").strip()
    country = (src.get("country") or "").strip()
    price = src.get("price")
    desc_raw = (src.get("description") or "").strip()
    # 列表价格 (lookup 返回 number, gs1 返回 string)
    if price is not None and price != "":
        price = str(price)

    imgs = src.get("images") or []
    img = imgs[0] if imgs else (src.get("image") or "")

    # --- userfields (写入 Grocy 自定义字段) ---
    uf = {}
    if brand:
        uf["brand"] = brand
    if cat:
        uf["category"] = cat
    if mf:
        uf["manufacturer"] = mf
    if net:
        uf["net_content"] = net
    # feature (产品特征, 多行文本): 通用名 + 规格 + 净含量 + 产地 + 参考价 + 附加描述
    feat_lines = []
    if general_name:
        feat_lines.append(general_name)
    if spec:
        feat_lines.append(spec)
    if net and net != spec:  # 避免与上面重复
        feat_lines.append("净含量: " + net)
    if country:
        feat_lines.append("产地: " + country)
    if price:
        feat_lines.append("参考价: " + price + " 元")
    if desc_raw:
        feat_lines.append(desc_raw)
    if feat_lines:
        uf["feature"] = "\n".join(feat_lines)

    # --- description (备用, 兼容旧代码) ---
    all_parts = []
    if brand:
        all_parts.append("品牌: " + brand)
    if cat:
        all_parts.append("分类: " + cat)
    if mf:
        all_parts.append("生产商: " + mf)
    spec_s = spec or net
    if spec_s:
        all_parts.append("规格: " + spec_s)
    if country:
        all_parts.append("产地: " + country)
    if price:
        all_parts.append("参考价: " + price + " 元")
    if desc_raw:
        all_parts.append(desc_raw)

    return {
        "name": name,
        "image_url": img,
        "userfields": uf,
        "description": "\n".join(all_parts),
    }


def apizero_lookup(barcode):
    """带付费 Key 查询 apizero。PRO 版优先, 失败回落免费版。无 Key 或查不到返回 None。"""
    key = load_apizero_key()
    if not key:
        return None
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


def lookup(barcode):
    bc = urllib.parse.quote(barcode)
    # 1) 先查库内
    st, ct, raw = grocy("GET", "/api/stock/products/by-barcode/" + bc)
    if st == 200:
        d = parse_details(raw)
        if d:
            d["created"] = False
            locs = []
            try:
                st_loc, _, raw_loc = grocy("GET", "/api/objects/locations")
                if st_loc == 200:
                    for l in (json.loads(raw_loc.decode("utf-8")) or []):
                        if l.get("id"): locs.append({"id": l["id"], "name": l.get("name", "")})
            except: pass
            d["locations"] = locs
            qus = []
            try:
                st_q, _, raw_q = grocy("GET", "/api/objects/quantity_units")
                if st_q == 200:
                    for q in (json.loads(raw_q.decode("utf-8")) or []):
                        if q.get("id"): qus.append({"id": q["id"], "name": q.get("name", "")})
            except: pass
            d["quantity_units"] = qus
            return d
    # 2) 库内无此条码 -> 直接拉取 Grocy 已有位置/数量单位, 让前端引导用户建档。
    #    不再调用外部 apizero 插件: 该插件在 Grocy 已有位置时仍会误报
    #    "Grocy 中还没有任何位置"(其 $this->locations 注入为空), 且 apizero 匿名额度已耗尽。
    locs = []
    st_loc, _, raw_loc = grocy("GET", "/api/objects/locations")
    if st_loc == 200:
        try:
            for l in (json.loads(raw_loc.decode("utf-8")) or []):
                if l.get("id"):
                    locs.append({"id": l["id"], "name": l.get("name", "")})
        except Exception:
            pass
    qus = []
    st_q, _, raw_q = grocy("GET", "/api/objects/quantity_units")
    if st_q == 200:
        try:
            for q in (json.loads(raw_q.decode("utf-8")) or []):
                if q.get("id"):
                    qus.append({"id": q["id"], "name": q.get("name", "")})
        except Exception:
            pass
    if not locs:
        return {"found": False, "need_create": False,
                "error": 'Grocy 中还没有任何"位置"。请在网页端 管理→位置 至少添加一个(如"储藏室")，或等扫码服务自动创建默认位置后重试'}
    if not qus:
        return {"found": False, "need_create": False,
                "error": 'Grocy 中还没有任何"数量单位"。请在网页端 管理→数量单位 至少添加一个(如"个")，或等扫码服务自动创建默认单位后重试'}
    # 3) 库内无此条码 -> 用 apizero 付费 Key 直连查询商品信息(成功则预填到新建表单)
    suggest = {}
    try:
        info = apizero_lookup(barcode)
        if info:
            suggest = {
                "name": info.get("name", ""),
                "description": info.get("description", ""),
                "image_url": info.get("image_url", ""),
                "userfields": info.get("userfields", {}),
            }
    except Exception:
        pass
    return {
        "found": False,
        "need_create": True,
        "barcode": barcode,
        "locations": locs,
        "quantity_units": qus,
        "suggest": suggest,
        "apizero_on": bool(load_apizero_key()),
    }


def http_get_bytes(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "grocyscan/1.0"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.read()
    except Exception:
        return b""


def upload_product_image(img_bytes, ext):
    """把图片字节上传到 Grocy 产品图片库, 返回 Grocy 内的文件名(失败返回空串)。"""
    if not img_bytes:
        return ""
    boundary = "----grocyscanboundary7Q8x"
    cd = ("Content-Disposition: form-data; name=\"file\"; filename=\"apizero.%s\"\r\n" % ext).encode("utf-8")
    body = (b"--" + boundary.encode() + b"\r\n") + cd + \
           b"Content-Type: image/jpeg\r\n\r\n" + img_bytes + b"\r\n" + \
           (b"--" + boundary.encode() + b"--\r\n")
    headers = {
        "GROCY-API-KEY": API_KEY,
        "Content-Type": ("multipart/form-data; boundary=%s" % boundary).encode("utf-8"),
    }
    req = urllib.request.Request(GROCY_URL + "/api/files/productpictures",
                                 data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            j = json.loads(r.read().decode("utf-8"))
            return j.get("filename") or j.get("file_name") or ""
    except Exception:
        return ""


def create_product(barcode, name, location_id, qu_id, description="", image_url="", userfields=None):
    """直接在 Grocy 建档并绑定条码, 不依赖外部插件。

    参数:
      barcode: 商品条码
      name: 产品名称
      location_id: 存放位置 id
      qu_id: 数量单位 id
      description: 描述/规格 (备用字段)
      image_url: 产品图片 URL (自动下载上传)
      userfields: dict, Grocy 自定义字段映射 (key=字段名, value=值)
        如 {"brand":"伊利","category":"奶酪","manufacturer":"xxx","net_content":"90克","feature":"..."}
        Grocy 自定义字段存储在 userfield_values 表中, 需通过独立端点 PUT /api/userfields/products/{id} 写入。

    返回 (product_id, error_msg); 成功时 error_msg 为空字符串。
    """
    body = {
        "name": name,
        "location_id": int(location_id),
        "qu_id_purchase": int(qu_id),
        "qu_id_stock": int(qu_id),
    }
    if description:
        body["description"] = description
    st, ct, raw = grocy("POST", "/api/objects/products", body)
    if st not in (200, 201):
        msg = ""
        try:
            msg = (json.loads(raw.decode("utf-8")) or {}).get("error_message", "")
        except Exception:
            msg = raw.decode("utf-8", "ignore")[:200]
        return None, (msg or ("建档失败 HTTP %s" % st))
    new_id = None
    try:
        j = json.loads(raw.decode("utf-8")) or {}
        new_id = j.get("created_object_id") or j.get("product_id")
    except Exception:
        pass
    if not new_id:
        return None, "建档成功但未返回产品ID"
    # 绑定条码到该产品
    grocy("POST", "/api/objects/product_barcodes",
          {"product_id": new_id, "barcode": barcode, "qu_id": int(qu_id)})

    # 写入 userfields (自定义字段) — 需通过独立端点 PUT /api/userfields/products/{id}
    # 格式: {"brand":"伊利","category":"奶酪"} (key-value, 不是 JSON 字符串)
    if userfields:
        try:
            uf = {}
            for key in ("brand", "category", "feature", "GDSInfo", "manufacturer", "net_content"):
                v = userfields.get(key)
                if v is not None and v != "":
                    uf[key] = str(v).strip()
            if uf:
                grocy("PUT", "/api/userfields/products/%s" % new_id, uf)
        except Exception:
            pass  # userfields 写入失败不影响建档成功

    # 自动下载 apizero 图片并上传到 Grocy(失败静默, 不影响建档)
    if image_url:
        try:
            ext = (image_url.rsplit(".", 1)[-1].split("?")[0] or "jpg").lower()
            if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                ext = "jpg"
            img = http_get_bytes(image_url)
            if img:
                fname = upload_product_image(img, ext)
                if fname:
                    grocy("PUT", "/api/objects/products/%s" % new_id,
                          {"picture_file_name": fname})
        except Exception:
            pass
    return new_id, ""


def change_stock(product_id, amount, mode, location_id=None):
    if mode == "out":
        path = "/api/stock/products/%s/consume" % product_id
        body = {"amount": amount, "transaction_type": "consume", "spoiled": False}
    else:
        path = "/api/stock/products/%s/add" % product_id
        body = {"amount": amount, "transaction_type": "purchase"}
    if location_id:
        body["location_id"] = int(location_id)
    st, ct, raw = grocy("POST", path, body)
    ok = st in (200, 201)
    msg = ""
    if not ok:
        try:
            msg = (json.loads(raw.decode("utf-8")) or {}).get("error_message", "")
        except Exception:
            msg = raw.decode("utf-8", "ignore")[:200]
    return ok, st, msg


# ---------------- CORS 配置 ----------------
CORS_ALLOWED_ORIGIN = "*"
CORS_ALLOWED_METHODS = "GET, POST, OPTIONS, PUT, DELETE"
CORS_ALLOWED_HEADERS = "Content-Type, GROCY-API-KEY, Authorization"

# ---------------- HTTP Handler ----------------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # 静默

    def _add_cors(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", CORS_ALLOWED_METHODS)
        self.send_header("Access-Control-Allow-Headers", CORS_ALLOWED_HEADERS)
        self.send_header("Access-Control-Max-Age", "86400")

    def do_OPTIONS(self):
        """CORS preflight request"""
        self.send_response(200)
        self._add_cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self._add_cors()
        self.end_headers()
        self.wfile.write(body)

    def _file(self, name, ctype):
        p = os.path.join(BASE, name)
        try:
            with open(p, "rb") as f:
                data = f.read()
        except Exception:
            self.send_response(404)
            self._add_cors()
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self._add_cors()
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        path = u.path
        qs = urllib.parse.parse_qs(u.query)
        if path == "/" or path == "/index.html":
            return self._file("index.html", "text/html; charset=utf-8")
        if path == "/html5-qrcode.min.js":
            return self._file("html5-qrcode.min.js", "application/javascript; charset=utf-8")
        # 通用静态文件路由: 允许 BASE 目录下任意 .js (如 quagga.min.js 专用一维码引擎)。
        # 仅匹配 [A-Za-z0-9_.\-] 文件名, 杜绝 ../ 目录穿越。
        if re.match(r"^/[A-Za-z0-9_.\-]+\.js$", path):
            return self._file(path.lstrip("/"), "application/javascript; charset=utf-8")
        if path == "/cert":
            # 供手机下载并安装为可信 CA 证书 (解决 Chrome/Edge 自签证书禁摄像头问题)
            p = os.path.join(BASE, "cert.pem")
            try:
                with open(p, "rb") as f:
                    data = f.read()
            except Exception:
                self.send_response(404); self._add_cors(); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", "application/x-x509-ca-cert")
            self.send_header("Content-Disposition", 'attachment; filename="grocyscan-ca.crt"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return
        if path == "/plugin":
            # 分发 Grocy 条码查询插件(已修复 BaseBarcodeLookupPlugin 命名空间)
            return self._file("ApiZeroBarcodeLookupPlugin.php", "application/octet-stream")
        if path == "/update":
            # 文件上传页 - 手机浏览器直接更新 index.html 等静态文件，免 SSH
            html = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>更新文件</title>'
                    '<style>body{font-family:sans-serif;max-width:480px;margin:40px auto;padding:20px;color:#333;}'
                    '.box{border:2px dashed #aaa;border-radius:12px;padding:30px;text-align:center;margin:20px 0;background:#fafafa;}'
                    'input[type=file]{font-size:16px;margin:10px 0;width:100%;}'
                    'button{background:#2e9e5b;color:#fff;border:0;border-radius:10px;padding:12px 30px;font-size:16px;cursor:pointer;width:100%;}'
                    'button:active{background:#25834b;}'
                    '.msg{margin-top:12px;font-size:14px;padding:10px;border-radius:8px;display:none;}'
                    '.msg.ok{background:#e8f5e9;color:#2e7d32;display:block;}'
                    '.msg.err{background:#fbe9e7;color:#c62828;display:block;}'
                    'h2{font-size:20px;}</style></head><body>'
                    '<h2>📝 更新文件</h2>'
                    '<form method="POST" action="/update" enctype="multipart/form-data">'
                    '<div class="box">'
                    '<p>选择文件上传（覆盖同名文件）</p>'
                    '<input type="file" name="file" id="f">'
                    '</div>'
                    '<button type="submit">上传</button>'
                    '</form>'
                    '<div class="msg" id="r"></div>'
                    '<script>document.querySelector("form").onsubmit=async(e)=>{'
                    'e.preventDefault();const fd=new FormData(e.target);'
                    'const r=document.getElementById("r");r.className="msg";'
                    'try{const res=await fetch("/update",{method:"POST",body:fd});'
                    'const j=await res.json();'
                    'if(j.ok){r.className="msg ok";r.textContent="✓ "+j.file+" 已更新 ("+j.size+" 字节)";}'
                    'else{r.className="msg err";r.textContent="✗ "+(j.error||"上传失败");}}'
                    'catch(err){r.className="msg err";r.textContent="✗ "+err;}};</script>'
                    '</body></html>')
            data = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self._add_cors()
            self.end_headers()
            self.wfile.write(data)
            return
        if path in ("/health", "/api/health"):
            return self._json({"ok": True, "grocy": GROCY_URL, "key_set": bool(API_KEY),
                               "apizero_on": bool(load_apizero_key()), "version": VERSION})
        if path == "/api/lookup":
            bc = (qs.get("barcode", [""])[0] or "").strip()
            if not bc:
                return self._json({"found": False, "error": "空条码"}, 400)
            return self._json(lookup(bc))
        if path == "/api/image":
            fn = (qs.get("file", [""])[0] or "").strip()
            if not fn:
                self.send_response(404); self._add_cors(); self.end_headers(); return
            b64 = base64.b64encode(fn.encode("utf-8")).decode("ascii")
            st, ct, raw = grocy("GET", "/api/files/productpictures/" + b64 + "?force_serve_as=picture", want_bytes=True)
            if st != 200:
                self.send_response(404); self._add_cors(); self.end_headers(); return
            self.send_response(200)
            self.send_header("Content-Type", ct or "image/jpeg")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "max-age=86400")
            self._add_cors()
            self.end_headers()
            self.wfile.write(raw)
            return
        if path == "/api/imgproxy":
            # 代理远程商品图(apizero 等外链), 避免自签 HTTPS 页的混内容拦截 / 外链防盗链。
            url = (qs.get("url", [""])[0] or "").strip()
            if not url or not url.startswith(("http://", "https://")):
                self.send_response(400); self._add_cors(); self.end_headers(); return
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 grocyscan"})
                with urllib.request.urlopen(req, timeout=12) as resp:
                    raw = resp.read()
                    ct = resp.headers.get("Content-Type", "image/jpeg")
                self.send_response(200)
                self.send_header("Content-Type", ct)
                self.send_header("Content-Length", str(len(raw)))
                self.send_header("Cache-Control", "max-age=86400")
                self._add_cors()
                self.end_headers()
                self.wfile.write(raw)
            except Exception:
                self.send_response(404); self._add_cors(); self.end_headers()
            return
        self.send_response(404); self._add_cors(); self.end_headers()

    def do_POST(self):
        u = urllib.parse.urlparse(self.path)
        if u.path == "/update":
            # 处理文件上传 - 覆盖 BASE 目录下的同名文件(仅允许安全文件名)
            ct = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ct:
                return self._json({"ok": False, "error": "需要 multipart/form-data"}, 400)
            ln = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(ln)
            boundary = ct.split("boundary=")[1].encode() if "boundary=" in ct else b""
            parts = raw.split(b"--" + boundary)
            for part in parts:
                if b"filename=" not in part:
                    continue
                hdr_end = part.find(b"\r\n\r\n")
                if hdr_end < 0:
                    continue
                header = part[:hdr_end].decode("utf-8", errors="ignore")
                fname_match = re.search(r'filename="([^"]+)"', header)
                if not fname_match:
                    continue
                fname = os.path.basename(fname_match.group(1))
                if not re.match(r'^[A-Za-z0-9_.\-]+$', fname):
                    return self._json({"ok": False, "error": "文件名不合法: " + fname}, 400)
                content = part[hdr_end + 4:]
                if content.endswith(b"\r\n"):
                    content = content[:-2]
                with open(os.path.join(BASE, fname), "wb") as f:
                    f.write(content)
                return self._json({"ok": True, "file": fname, "size": len(content)})
            return self._json({"ok": False, "error": "未找到文件"}, 400)
        if u.path == "/api/create":
            try:
                ln = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(ln).decode("utf-8"))
            except Exception as e:
                return self._json({"ok": False, "error": "请求体解析失败: " + str(e)}, 400)
            barcode = (body.get("barcode") or "").strip()
            name = (body.get("name") or "").strip()
            desc = (body.get("description") or "").strip()
            img_url = (body.get("image_url") or "").strip()
            uf = body.get("userfields") or {}
            try:
                loc = int(body.get("location_id"))
            except Exception:
                loc = 0
            try:
                qu = int(body.get("qu_id"))
            except Exception:
                qu = 0
            if not barcode or not name or loc <= 0 or qu <= 0:
                return self._json({"ok": False, "error": "参数错误(条码/名称/位置/单位必填)"}, 400)
            pid, msg = create_product(barcode, name, loc, qu, desc, img_url, userfields=uf)
            if pid:
                return self._json({"ok": True, "product_id": pid, "name": name})
            return self._json({"ok": False, "error": msg}, 400)
        if u.path != "/api/stock":
            self.send_response(404); self._add_cors(); self.end_headers(); return
        try:
            ln = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(ln).decode("utf-8"))
        except Exception as e:
            return self._json({"ok": False, "error": "请求体解析失败: " + str(e)}, 400)
        pid = body.get("product_id")
        try:
            amount = float(body.get("amount", 1))
        except Exception:
            amount = 1
        mode = body.get("mode", "in")
        loc_id = body.get("location_id")
        if not pid or amount <= 0:
            return self._json({"ok": False, "error": "参数错误"}, 400)
        ok, st, msg = change_stock(pid, amount, mode, loc_id)
        return self._json({"ok": ok, "status": st, "error": msg})


def ensure_cert():
    cert = os.path.join(BASE, "cert.pem")
    key = os.path.join(BASE, "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    # 自动补生成 (若容器内有 openssl)
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key,
             "-out", cert, "-days", "3650", "-nodes", "-subj", "/CN=grocyscan"],
            check=True)
        return cert, key
    except Exception as e:
        raise SystemExit("缺少 cert.pem/key.pem 且无法用 openssl 生成: %s" % e)


def main():
    import threading

    if not API_KEY:
        print("[警告] 未设置 GROCY_API_KEY, Grocy 接口会 401。请用 -e GROCY_API_KEY=... 传入。")
    cert, key = ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert, keyfile=key)

    # HTTPS server on PORT (9290) - for direct HTTPS access
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print("Grocy 扫码录入已启动: https://0.0.0.0:%d  ->  %s" % (PORT, GROCY_URL))

    # HTTP server on PORT+1 (9291) - for ngrok/HTTPS tunnel backends
    HTTP_PORT = PORT + 1
    httpd_plain = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), H)
    print("Grocy 扫码录入已启动: http://0.0.0.0:%d (plain HTTP for ngrok)" % HTTP_PORT)

    # Run both in threads
    def run_https():
        httpd.serve_forever()
    def run_http():
        httpd_plain.serve_forever()

    t1 = threading.Thread(target=run_https, daemon=True)
    t2 = threading.Thread(target=run_http, daemon=True)
    t1.start()
    t2.start()

    # Block main thread
    import time
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
