#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grocy 鎵嬫満鎵爜褰曞叆 - 杞婚噺鍚庣 (绾?Python 鏍囧噯搴? 闆剁涓夋柟渚濊禆)
鐗堟湰: V2.01 (2026-07-27)
  V2.01: 鏂板 userfields 鍐欏叆 (PUT /api/userfields/products/{id}), 鏀寔 brand/category/manufacturer/net_content/feature 鑷畾涔夊瓧娈?鑱岃矗:
  1. 鎻愪緵 HTTPS (鑷璇佷功) -> 鎵嬫満娴忚鍣ㄦ墠鍏佽寮€鎽勫儚澶?  2. 浠ｇ悊 Grocy API (鏈嶅姟绔敞鍏?GROCY-API-KEY, 閬垮厤娴忚鍣ㄨ法鍩?+ 闅愯棌瀵嗛挜)
  3. 鏉＄爜鏌ヨ: 鍏堟煡搴撳唴浜у搧, 鏌ヤ笉鍒板垯瑙﹀彂澶栭儴鏉＄爜鎻掍欢(apizero) add=true 鑷姩寤烘。
  4. apizero 鍟嗗搧瀛楁鍐欏叆 Grocy 鑷畾涔夊瓧娈?(userfields), 涓嶅啀鎷艰繘 description
鐜鍙橀噺:
  GROCY_URL       Grocy 鍦板潃, 榛樿 http://172.17.0.1:9283 (docker 缃戝叧鍥炶繛瀹夸富鍙戝竷绔彛)
  GROCY_API_KEY   Grocy API 瀵嗛挜 (蹇呭～)
  PORT            鐩戝惉绔彛, 榛樿 9290
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
from rembg import remove

GROCY_URL = os.environ.get("GROCY_URL", "http://172.17.0.1:9283").rstrip("/")
API_KEY = os.environ.get("GROCY_API_KEY", "").strip()

# 鍔犺浇浜у搧鍒嗙被閰嶇疆
CATEGORY_CONFIG = {}
_cfg_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "category_config.json")
try:
    with open(_cfg_path, "r", encoding="utf-8") as _f:
        CATEGORY_CONFIG = json.load(_f)
except Exception:
    pass

PORT = int(os.environ.get("PORT", "9290"))
BASE = os.path.dirname(os.path.abspath(__file__))


# ---------------- Grocy 璇锋眰灏佽 ----------------
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
    """瑙ｆ瀽 by-barcode 杩斿洖鐨勪骇鍝佽鎯?""
    try:
        j = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    prod = j.get("product") or {}
    if not prod.get("id"):
        return None
    pid = prod.get("id")
    # fetch custom fields (userfields)
    uf = {}
    st_uf, _, raw_uf = grocy("GET", "/api/userfields/products/" + str(pid))
    if st_uf == 200:
        try:
            uf_data = json.loads(raw_uf.decode("utf-8"))
            if isinstance(uf_data, dict):
                for k in ("brand", "category", "manufacturer", "net_content", "feature"):
                    v = uf_data.get(k)
                    if v is not None and v != "":
                        uf[k] = str(v)
        except: pass
    return {
        "found": True,
        "product_id": pid,
        "name": prod.get("name", ""),
        "description": prod.get("description", "") or "",
        "picture_file_name": prod.get("picture_file_name", "") or "",
        "stock_amount": j.get("stock_amount", 0),
        "qu_stock": (j.get("quantity_unit_stock") or {}).get("name", ""),
        "userfields": uf,
    }


def ensure_grocy_basics():
    """Grocy 澶栭儴鏉＄爜鎻掍欢鐨勭‖鎬у墠鎻? 鑷冲皯瀛樺湪涓€涓?浣嶇疆"鍜屼竴涓?鏁伴噺鍗曚綅"銆?    鑻ョ敤鎴峰皻鏈厤缃? 杩欓噷鑷姩寤哄ソ榛樿鍊?榛樿浣嶇疆/涓?, 璁╂壂鐮佸仛鍒伴浂閰嶇疆鍙敤銆?    浠讳綍涓€姝ュけ璐ラ兘闈欓粯蹇界暐 鈥斺€?澶辫触鏃舵彃浠朵細鎶涙竻鏅颁腑鏂囬敊璇彁绀虹敤鎴峰幓閰嶃€?    """
    try:
        # 浣嶇疆
        st, _, raw = grocy("GET", "/api/objects/locations")
        if st == 200:
            try:
                locs = json.loads(raw.decode("utf-8")) or []
            except Exception:
                locs = []
            if len(locs) == 0:
                grocy("POST", "/api/objects/locations",
                      {"name": "榛樿浣嶇疆", "description": "鎵爜鑷姩鍒涘缓"})
        # 鏁伴噺鍗曚綅
        st2, _, raw2 = grocy("GET", "/api/objects/quantity_units")
        if st2 == 200:
            try:
                qus = json.loads(raw2.decode("utf-8")) or []
            except Exception:
                qus = []
            if len(qus) == 0:
                grocy("POST", "/api/objects/quantity_units",
                      {"name": "涓?, "name_plural": "涓?, "description": "鎵爜鑷姩鍒涘缓"})
    except Exception:
        pass


# ---------------- apizero 鍟嗗搧淇℃伅锛堝甫浠樿垂 Key 鐩磋繛锛屼笉缁忚繃 Grocy 鎻掍欢锛?---------------
def load_apizero_key():
    """浠?鐜鍙橀噺 APIZERO_KEY 鎴?鍚岀洰褰?apizero_key 鏂囦欢 璇诲彇浠樿垂 Key銆?    浼樺厛绾? 鐜鍙橀噺 > 鏂囦欢銆傛枃浠朵负绌?涓嶅瓨鍦ㄥ垯杩斿洖绌哄瓧绗︿覆(姝ゆ椂涓嶈皟 apizero, 閫€鍥炴墜鍔ㄥ～琛?銆?""
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
    """瑙ｆ瀽 apizero 杩斿洖: 鍏煎 PRO 鐗?barcode-gs1, 椤跺眰瀛楁) 涓?鍏嶈垂鐗?barcode-lookup, 鍖呭湪 data 鍐?銆?
    杩斿洖缁撴瀯鍖栨暟鎹?
      - name: 浜у搧鍚嶇О
      - image_url: 浜у搧鍥剧墖 URL
      - userfields: Grocy 鑷畾涔夊瓧娈垫槧灏?(key-value, 瀵瑰簲 userfields 琛ㄧ殑 name 瀛楁)
        brand      -> 鍝佺墝
        category   -> 绫诲埆
        feature    -> 浜у搧鐗瑰緛 (澶氳鏂囨湰, 鍚鏍?鍑€鍚噺/浜у湴绛?
        manufacturer -> 鐢熶骇鍟嗗垪琛?        net_content  -> 鍑€鍚噺
      - description: 澶囩敤鏂囨湰 (鍏煎鏃т唬鐮? 鍚堝苟鍏ㄩ儴淇℃伅)
    """
    if not isinstance(j, dict):
        return None
    data = j.get("data") or {}
    src = data if data else j
    name = (src.get("name") or j.get("name") or "").strip()
    if not name:
        return None  # 鏈櫥璁版垨鏃犲悕绉?-> 瑙嗕负鏌ヤ笉鍒?
    brand = (src.get("brand") or "").strip()
    cat = (src.get("category") or "").strip()
    mf = (src.get("manufacturer") or "").strip()
    # 瑙勬牸: gs1 鐢?specification, lookup 鐢?spec
    spec = (src.get("specification") or src.get("spec") or "").strip()
    net = (src.get("net_content") or "").strip()
    general_name = (src.get("general_name") or "").strip()
    country = (src.get("country") or "").strip()
    price = src.get("price")
    desc_raw = (src.get("description") or "").strip()
    # 鍒楄〃浠锋牸 (lookup 杩斿洖 number, gs1 杩斿洖 string)
    if price is not None and price != "":
        price = str(price)

    imgs = src.get("images") or []
    img = imgs[0] if imgs else (src.get("image") or "")
    # Fix: gds.org.cn images are often 404, use apizero lookup image instead
    if img and "gds.org.cn" in img:
        img = "https://v1.apizero.cn/api/barcode-lookup?mode=image&barcode=" + src.get("barcode", j.get("barcode", ""))
    elif not img and (src.get("barcode") or j.get("barcode")):
        img = "https://v1.apizero.cn/api/barcode-lookup?mode=image&barcode=" + (src.get("barcode") or j.get("barcode", ""))

    # --- userfields (鍐欏叆 Grocy 鑷畾涔夊瓧娈? ---
    uf = {}
    if brand:
        uf["brand"] = brand
    if cat:
        uf["category"] = cat
    if mf:
        uf["manufacturer"] = mf
    if net:
        uf["net_content"] = net
    # feature (浜у搧鐗瑰緛, 澶氳鏂囨湰): 閫氱敤鍚?+ 瑙勬牸 + 鍑€鍚噺 + 浜у湴 + 鍙傝€冧环 + 闄勫姞鎻忚堪
    feat_lines = []
    if general_name:
        feat_lines.append(general_name)
    if spec:
        feat_lines.append(spec)
    if net and net != spec:  # 閬垮厤涓庝笂闈㈤噸澶?        feat_lines.append("鍑€鍚噺: " + net)
    if country:
        feat_lines.append("浜у湴: " + country)
    if price:
        feat_lines.append("鍙傝€冧环: " + price + " 鍏?)
    if desc_raw:
        feat_lines.append(desc_raw)
    if feat_lines:
        uf["feature"] = "\n".join(feat_lines)

    # --- description (澶囩敤, 鍏煎鏃т唬鐮? ---
    all_parts = []
    if brand:
        all_parts.append("鍝佺墝: " + brand)
    if cat:
        all_parts.append("鍒嗙被: " + cat)
    if mf:
        all_parts.append("鐢熶骇鍟? " + mf)
    spec_s = spec or net
    if spec_s:
        all_parts.append("瑙勬牸: " + spec_s)
    if country:
        all_parts.append("浜у湴: " + country)
    if price:
        all_parts.append("鍙傝€冧环: " + price + " 鍏?)
    if desc_raw:
        all_parts.append(desc_raw)

    return {
        "name": name,
        "image_url": img,
        "userfields": uf,
        "description": "\n".join(all_parts),
    }


def apizero_lookup(barcode):
    """甯︿粯璐?Key 鏌ヨ apizero銆侾RO 鐗堜紭鍏? 澶辫触鍥炶惤鍏嶈垂鐗堛€傛棤 Key 鎴栨煡涓嶅埌杩斿洖 None銆?""
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
    # 1) 鍏堟煡搴撳唴
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
    # 2) 搴撳唴鏃犳鏉＄爜 -> 鐩存帴鎷夊彇 Grocy 宸叉湁浣嶇疆/鏁伴噺鍗曚綅, 璁╁墠绔紩瀵肩敤鎴峰缓妗ｃ€?    #    涓嶅啀璋冪敤澶栭儴 apizero 鎻掍欢: 璇ユ彃浠跺湪 Grocy 宸叉湁浣嶇疆鏃朵粛浼氳鎶?    #    "Grocy 涓繕娌℃湁浠讳綍浣嶇疆"(鍏?$this->locations 娉ㄥ叆涓虹┖), 涓?apizero 鍖垮悕棰濆害宸茶€楀敖銆?    locs = []
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
                "error": 'Grocy 涓繕娌℃湁浠讳綍"浣嶇疆"銆傝鍦ㄧ綉椤电 绠＄悊鈫掍綅缃?鑷冲皯娣诲姞涓€涓?濡?鍌ㄨ棌瀹?)锛屾垨绛夋壂鐮佹湇鍔¤嚜鍔ㄥ垱寤洪粯璁や綅缃悗閲嶈瘯'}
    if not qus:
        return {"found": False, "need_create": False,
                "error": 'Grocy 涓繕娌℃湁浠讳綍"鏁伴噺鍗曚綅"銆傝鍦ㄧ綉椤电 绠＄悊鈫掓暟閲忓崟浣?鑷冲皯娣诲姞涓€涓?濡?涓?)锛屾垨绛夋壂鐮佹湇鍔¤嚜鍔ㄥ垱寤洪粯璁ゅ崟浣嶅悗閲嶈瘯'}
    # 3) 搴撳唴鏃犳鏉＄爜 -> 鐢?apizero 浠樿垂 Key 鐩磋繛鏌ヨ鍟嗗搧淇℃伅(鎴愬姛鍒欓濉埌鏂板缓琛ㄥ崟)
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


def upload_product_image(img_bytes, product_id):
    """忙聤聤氓聸戮莽聣聡氓颅聴猫聤聜盲赂聤盲录聽氓聢掳 Grocy 盲潞搂氓聯聛氓聸戮莽聣聡氓潞聯, 猫驴聰氓聸聻 Grocy 氓聠聟莽職聞忙聳聡盲禄露氓聬聧(氓陇卤猫麓楼猫驴聰氓聸聻莽漏潞盲赂虏)茫聙聜"""
    if not img_bytes:
        return ""
    pic_name = "%s.jpg" % product_id
    b64fn = base64.b64encode(pic_name.encode("ascii")).decode("ascii")
    headers = {
        "GROCY-API-KEY": API_KEY,
        "Content-Type": "image/jpeg",
    }
    req = urllib.request.Request(GROCY_URL + "/api/files/productpictures/" + b64fn,
                                 data=img_bytes, headers=headers, method="PUT")
    try:
        with urllib.request.urlopen(req, timeout=20):
            return pic_name
    except Exception:
        return ""
def create_product(barcode, name, location_id, qu_id, description="", image_url="", userfields=None):
    """鐩存帴鍦?Grocy 寤烘。骞剁粦瀹氭潯鐮? 涓嶄緷璧栧閮ㄦ彃浠躲€?
    鍙傛暟:
      barcode: 鍟嗗搧鏉＄爜
      name: 浜у搧鍚嶇О
      location_id: 瀛樻斁浣嶇疆 id
      qu_id: 鏁伴噺鍗曚綅 id
      description: 鎻忚堪/瑙勬牸 (澶囩敤瀛楁)
      image_url: 浜у搧鍥剧墖 URL (鑷姩涓嬭浇涓婁紶)
      userfields: dict, Grocy 鑷畾涔夊瓧娈垫槧灏?(key=瀛楁鍚? value=鍊?
        濡?{"brand":"浼婂埄","category":"濂堕叒","manufacturer":"xxx","net_content":"90鍏?,"feature":"..."}
        Grocy 鑷畾涔夊瓧娈靛瓨鍌ㄥ湪 userfield_values 琛ㄤ腑, 闇€閫氳繃鐙珛绔偣 PUT /api/userfields/products/{id} 鍐欏叆銆?
    杩斿洖 (product_id, error_msg); 鎴愬姛鏃?error_msg 涓虹┖瀛楃涓层€?    """
    body = {
        "name": name,
        "location_id": int(location_id),
        "qu_id_purchase": int(qu_id),
        "qu_id_stock": int(qu_id),
    }
    if description:
        body["description"] = description
    pg_name = None
    if userfields and userfields.get("category"):
        raw_cat = str(userfields["category"])
        idx_paren = raw_cat.find("(")
        pg_name = raw_cat[:idx_paren].strip() if idx_paren > 0 else raw_cat.strip()
        pg_id = _ensure_product_group(pg_name)
        if pg_id:
            body["product_group_id"] = pg_id
    bb_days = _guess_best_before_days(name, (userfields or {}).get("category") or pg_name)
    if bb_days:
        body["default_best_before_days"] = bb_days
    st, ct, raw = grocy("POST", "/api/objects/products", body)
    if st not in (200, 201):
        msg = ""
        try:
            msg = (json.loads(raw.decode("utf-8")) or {}).get("error_message", "")
        except Exception:
            msg = raw.decode("utf-8", "ignore")[:200]
        return None, (msg or ("寤烘。澶辫触 HTTP %s" % st))
    new_id = None
    try:
        j = json.loads(raw.decode("utf-8")) or {}
        new_id = j.get("created_object_id") or j.get("product_id")
    except Exception:
        pass
    if not new_id:
        return None, "寤烘。鎴愬姛浣嗘湭杩斿洖浜у搧ID"
    # 缁戝畾鏉＄爜鍒拌浜у搧
    grocy("POST", "/api/objects/product_barcodes",
          {"product_id": new_id, "barcode": barcode, "qu_id": int(qu_id)})

    # 鍐欏叆 userfields (鑷畾涔夊瓧娈? 鈥?闇€閫氳繃鐙珛绔偣 PUT /api/userfields/products/{id}
    # 鏍煎紡: {"brand":"浼婂埄","category":"濂堕叒"} (key-value, 涓嶆槸 JSON 瀛楃涓?
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
            pass  # userfields 鍐欏叆澶辫触涓嶅奖鍝嶅缓妗ｆ垚鍔?
    # 鑷姩涓嬭浇 apizero 鍥剧墖骞朵笂浼犲埌 Grocy(澶辫触闈欓粯, 涓嶅奖鍝嶅缓妗?
    if image_url:
        def _try_dl(url):
            try:
                ext = (url.rsplit(".", 1)[-1].split("?")[0] or "jpg").lower()
                if ext not in ("jpg", "jpeg", "png", "gif", "webp"):
                    ext = "jpg"
                img = http_get_bytes(url)
                if img and len(img) > 100:
                    try:
                        img = remove(img)
                    except Exception:
                        pass
                    fname = upload_product_image(img, new_id)
                    if fname:
                        grocy("PUT", "/api/objects/products/%s" % new_id,
                              {"picture_file_name": fname})
                        return True
            except Exception:
                pass
            return False
        if not _try_dl(image_url) and "gds.org.cn" in image_url:
            parts = image_url.split("/")
            bc_candidate = ""
            for p in parts:
                if p.isdigit() and len(p) >= 8:
                    bc_candidate = p
                    break
            if bc_candidate:
                _try_dl("https://v1.apizero.cn/api/barcode-lookup?mode=image&barcode=" + bc_candidate)
    return new_id, ""


def _ensure_product_group(name):
    """纭繚浜у搧鍒嗙粍瀛樺湪, 涓嶅瓨鍦ㄥ垯鍒涘缓銆備粠鍒嗙被閰嶇疆涓煡鎵惧垎缁勫悕绉般€?""
    if not name:
        return None
    # 浠庨厤缃腑鏌ユ壘鍒嗙粍鍚?    pg_name = name
    for cfg_key, cfg_val in CATEGORY_CONFIG.items():
        if cfg_key == name or (cfg_val.get("product_group") or "") == name:
            pg_name = cfg_val.get("product_group") or name
            break
    try:
        st, _, raw = grocy("GET", "/api/objects/product_groups")
        if st == 200:
            groups = json.loads(raw.decode("utf-8")) or []
            for g in groups:
                if (g.get("name") or "").strip().lower() == pg_name.strip().lower():
                    return g["id"]
        st2, _, raw2 = grocy("POST", "/api/objects/product_groups", {"name": pg_name})
        if st2 in (200, 201):
            j2 = json.loads(raw2.decode("utf-8")) or {}
            return j2.get("created_object_id")
    except Exception:
        pass
    return None

def _guess_best_before_days(name, category):
    """浠庡垎绫婚厤缃枃浠朵腑鏌ユ壘淇濊川鏈? 鏈尮閰嶅垯杩?瀛ｅ害榛樿365澶┿€?""
    if category and category in CATEGORY_CONFIG:
        return CATEGORY_CONFIG[category].get("best_before_days", 365)
    text = (name + " " + (category or "")).lower()
    for cfg_key, cfg_val in CATEGORY_CONFIG.items():
        if cfg_key.lower() in text:
            return cfg_val.get("best_before_days", 365)
    return 365

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


# ---------------- CORS 閰嶇疆 ----------------
CORS_ALLOWED_ORIGIN = "*"
CORS_ALLOWED_METHODS = "GET, POST, OPTIONS, PUT, DELETE"
CORS_ALLOWED_HEADERS = "Content-Type, GROCY-API-KEY, Authorization"

# ---------------- HTTP Handler ----------------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass  # 闈欓粯

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
        # 閫氱敤闈欐€佹枃浠惰矾鐢? 鍏佽 BASE 鐩綍涓嬩换鎰?.js (濡?quagga.min.js 涓撶敤涓€缁寸爜寮曟搸)銆?        # 浠呭尮閰?[A-Za-z0-9_.\-] 鏂囦欢鍚? 鏉滅粷 ../ 鐩綍绌胯秺銆?        if re.match(r"^/[A-Za-z0-9_.\-]+\.js$", path):
            return self._file(path.lstrip("/"), "application/javascript; charset=utf-8")
        if path == "/cert":
            # 渚涙墜鏈轰笅杞藉苟瀹夎涓哄彲淇?CA 璇佷功 (瑙ｅ喅 Chrome/Edge 鑷璇佷功绂佹憚鍍忓ご闂)
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
            # 鍒嗗彂 Grocy 鏉＄爜鏌ヨ鎻掍欢(宸蹭慨澶?BaseBarcodeLookupPlugin 鍛藉悕绌洪棿)
            return self._file("ApiZeroBarcodeLookupPlugin.php", "application/octet-stream")
        if path == "/update":
            # 鏂囦欢涓婁紶椤?- 鎵嬫満娴忚鍣ㄧ洿鎺ユ洿鏂?index.html 绛夐潤鎬佹枃浠讹紝鍏?SSH
            html = ('<!DOCTYPE html><html><head><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width,initial-scale=1">'
                    '<title>鏇存柊鏂囦欢</title>'
                    '<style>body{font-family:sans-serif;max-width:480px;margin:40px auto;padding:20px;color:#333;}'
                    '.box{border:2px dashed #aaa;border-radius:12px;padding:30px;text-align:center;margin:20px 0;background:#fafafa;}'
                    'input[type=file]{font-size:16px;margin:10px 0;width:100%;}'
                    'button{background:#2e9e5b;color:#fff;border:0;border-radius:10px;padding:12px 30px;font-size:16px;cursor:pointer;width:100%;}'
                    'button:active{background:#25834b;}'
                    '.msg{margin-top:12px;font-size:14px;padding:10px;border-radius:8px;display:none;}'
                    '.msg.ok{background:#e8f5e9;color:#2e7d32;display:block;}'
                    '.msg.err{background:#fbe9e7;color:#c62828;display:block;}'
                    'h2{font-size:20px;}</style></head><body>'
                    '<h2>馃摑 鏇存柊鏂囦欢</h2>'
                    '<form method="POST" action="/update" enctype="multipart/form-data">'
                    '<div class="box">'
                    '<p>閫夋嫨鏂囦欢涓婁紶锛堣鐩栧悓鍚嶆枃浠讹級</p>'
                    '<input type="file" name="file" id="f">'
                    '</div>'
                    '<button type="submit">涓婁紶</button>'
                    '</form>'
                    '<div class="msg" id="r"></div>'
                    '<script>document.querySelector("form").onsubmit=async(e)=>{'
                    'e.preventDefault();const fd=new FormData(e.target);'
                    'const r=document.getElementById("r");r.className="msg";'
                    'try{const res=await fetch("/update",{method:"POST",body:fd});'
                    'const j=await res.json();'
                    'if(j.ok){r.className="msg ok";r.textContent="鉁?"+j.file+" 宸叉洿鏂?("+j.size+" 瀛楄妭)";}'
                    'else{r.className="msg err";r.textContent="鉁?"+(j.error||"涓婁紶澶辫触");}}'
                    'catch(err){r.className="msg err";r.textContent="鉁?"+err;}};</script>'
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
                return self._json({"found": False, "error": "绌烘潯鐮?}, 400)
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
            # 浠ｇ悊杩滅▼鍟嗗搧鍥?apizero 绛夊閾?, 閬垮厤鑷 HTTPS 椤电殑娣峰唴瀹规嫤鎴?/ 澶栭摼闃茬洍閾俱€?            url = (qs.get("url", [""])[0] or "").strip()
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
            # 澶勭悊鏂囦欢涓婁紶 - 瑕嗙洊 BASE 鐩綍涓嬬殑鍚屽悕鏂囦欢(浠呭厑璁稿畨鍏ㄦ枃浠跺悕)
            ct = self.headers.get("Content-Type", "")
            if "multipart/form-data" not in ct:
                return self._json({"ok": False, "error": "闇€瑕?multipart/form-data"}, 400)
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
                    return self._json({"ok": False, "error": "鏂囦欢鍚嶄笉鍚堟硶: " + fname}, 400)
                content = part[hdr_end + 4:]
                if content.endswith(b"\r\n"):
                    content = content[:-2]
                with open(os.path.join(BASE, fname), "wb") as f:
                    f.write(content)
                return self._json({"ok": True, "file": fname, "size": len(content)})
            return self._json({"ok": False, "error": "鏈壘鍒版枃浠?}, 400)
        if u.path == "/api/create":
            try:
                ln = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(ln).decode("utf-8"))
            except Exception as e:
                return self._json({"ok": False, "error": "璇锋眰浣撹В鏋愬け璐? " + str(e)}, 400)
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
                return self._json({"ok": False, "error": "鍙傛暟閿欒(鏉＄爜/鍚嶇О/浣嶇疆/鍗曚綅蹇呭～)"}, 400)
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
            return self._json({"ok": False, "error": "璇锋眰浣撹В鏋愬け璐? " + str(e)}, 400)
        pid = body.get("product_id")
        try:
            amount = float(body.get("amount", 1))
        except Exception:
            amount = 1
        mode = body.get("mode", "in")
        loc_id = body.get("location_id")
        if not pid or amount <= 0:
            return self._json({"ok": False, "error": "鍙傛暟閿欒"}, 400)
        ok, st, msg = change_stock(pid, amount, mode, loc_id)
        return self._json({"ok": ok, "status": st, "error": msg})


def ensure_cert():
    cert = os.path.join(BASE, "cert.pem")
    key = os.path.join(BASE, "key.pem")
    if os.path.exists(cert) and os.path.exists(key):
        return cert, key
    # 鑷姩琛ョ敓鎴?(鑻ュ鍣ㄥ唴鏈?openssl)
    try:
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-keyout", key,
             "-out", cert, "-days", "3650", "-nodes", "-subj", "/CN=grocyscan"],
            check=True)
        return cert, key
    except Exception as e:
        raise SystemExit("缂哄皯 cert.pem/key.pem 涓旀棤娉曠敤 openssl 鐢熸垚: %s" % e)


def main():
    import threading

    if not API_KEY:
        print("[璀﹀憡] 鏈缃?GROCY_API_KEY, Grocy 鎺ュ彛浼?401銆傝鐢?-e GROCY_API_KEY=... 浼犲叆銆?)
    cert, key = ensure_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=cert, keyfile=key)

    # HTTPS server on PORT (9290) - for direct HTTPS access
    httpd = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    print("Grocy 鎵爜褰曞叆宸插惎鍔? https://0.0.0.0:%d  ->  %s" % (PORT, GROCY_URL))

    # HTTP server on PORT+1 (9291) - for ngrok/HTTPS tunnel backends
    HTTP_PORT = PORT + 1
    httpd_plain = ThreadingHTTPServer(("0.0.0.0", HTTP_PORT), H)
    print("Grocy 鎵爜褰曞叆宸插惎鍔? http://0.0.0.0:%d (plain HTTP for ngrok)" % HTTP_PORT)

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
