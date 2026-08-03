#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GrocyScan 统一操作审计日志 (CSV + JSON)
记录所有库存操作: 硬件扫码 / 手机网页 / 语音出入库 / 建档 / 拆包。

每条记录字段:
  time        北京时间操作时间 (YYYY-MM-DD HH:MM:SS)
  source      来源: hardware / phone / voice / api
  operation   操作: in(入库) / out(出库) / split(拆包) / create(建档) / location(切换位置)
  barcode     条码号
  barcode_type 条码类型: ean13 / location / unknown
  product_id  商品ID
  product_name 商品名称
  amount      数量
  location_id 位置ID
  location_name 位置名称
  apizero     apizero 使用: none / paid / free
  auto_created 是否自动建档: true / false
  result      ok / fail
  detail      结果详情(成功消息或错误)

文件:
  /data/audit_log.csv   CSV (Excel可直接打开)
  /data/audit_log.jsonl JSON Lines (程序友好)
"""
import os
import json
import time
import csv
import threading

# 日志目录可被环境变量覆盖 (voice-service 等独立容器通过挂载同一目录并设此变量来写同一份日志)
AUDIT_DIR = os.environ.get("GROCYS_AUDIT_DIR") or os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(AUDIT_DIR, "audit_log.csv")
JSON_PATH = os.path.join(AUDIT_DIR, "audit_log.jsonl")

CSV_HEADER = [
    "time", "source", "operation", "barcode", "barcode_type",
    "product_id", "product_name", "amount", "location_id", "location_name",
    "apizero", "auto_created", "result", "detail",
]

_lock = threading.Lock()


def _now():
    # 本地时区时间(容器已设 TZ=Asia/Shanghai)
    return time.strftime("%Y-%m-%d %H:%M:%S")


def barcode_type(barcode):
    """判断条码类型。位置条码 9691000000 前缀 -> location。"""
    b = (barcode or "").strip()
    if not b:
        return "unknown"
    if b.startswith("9691000000") and len(b) == 13:
        return "location"
    if len(b) == 13 and b.isdigit():
        return "ean13"
    return "unknown"


def log_entry(entry):
    """写入一条审计记录。entry 为 dict。"""
    global CSV_PATH, JSON_PATH
    rec = {
        "time": _now(),
        "source": entry.get("source", "api"),
        "operation": entry.get("operation", ""),
        "barcode": entry.get("barcode", ""),
        "barcode_type": barcode_type(entry.get("barcode")),
        "product_id": entry.get("product_id", ""),
        "product_name": entry.get("product_name", ""),
        "amount": entry.get("amount", 1),
        "location_id": entry.get("location_id", ""),
        "location_name": entry.get("location_name", ""),
        "apizero": entry.get("apizero", "none"),
        "auto_created": "true" if entry.get("auto_created") else "false",
        "result": entry.get("result", "ok"),
        "detail": entry.get("detail", ""),
    }
    with _lock:
        try:
            need_header = not os.path.exists(CSV_PATH) or os.path.getsize(CSV_PATH) == 0
            with open(CSV_PATH, "a", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=CSV_HEADER)
                if need_header:
                    w.writeheader()
                w.writerow(rec)
        except Exception:
            pass
        try:
            with open(JSON_PATH, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            pass
    return rec
