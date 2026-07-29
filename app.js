/**
 * Grocy ????????? - ??????
 * ???: 2.3.0 (2026-07-28) - ????? */

const APP_VERSION = "2.3.0";
const VERSION_DATE = "2026-07-28";

const sh = (id, p, v) => { const e = document.getElementById(id); if (e && e.style) e.style[p] = v; };
const st = (id, v) => { const e = document.getElementById(id); if (e) e.textContent = String(v); };
const sv = (id, v) => { const e = document.getElementById(id); if (e) e.value = v; };
const si = (id, v) => { const e = document.getElementById(id); if (e) e.innerHTML = v; };
const ss = (id, v) => { const e = document.getElementById(id); if (e) e.src = v; };


const S = {
  mode: "in",
  qty: "each",
  busy: false,
  lastCode: "",
  lastTime: 0,
  pending: null,
  cam: null,
  camOn: false,
  camEngine: null,
  track: null,
  nativeDetectTimer: null,
  nativeVideoReady: false,
  quaggaInitialized: false,
  torchOn: false,
  engine: "auto",
};

const $ = (s) => document.querySelector(s);

const esc = (s) => String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");

const toast = (msg, type="info") => {
  try {
    const el = $("#toast");
    if (!el) return;
    el.className = "toast " + type + " show";
    el.textContent = msg;
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.className = "toast " + type; }, 2500);
  } catch(e) {}
};

const feedback = () => {
  if (navigator.vibrate) navigator.vibrate(120);
};

const nowStr = () => {
  const d = new Date();
  return d.toTimeString().slice(0, 5);
};

const setEngineBadge = (text) => {
  const b = document.getElementById("camEngine");
  if (b) b.textContent = text;
};

const setCamOffMsg = (show) => {
  const m = document.getElementById("camOffMsg");
  if (m) m.style.display = show ? "flex" : "none";
};

const setCamBtnState = (on) => {
  const btn = $("#btnCam");
  if (btn) btn.textContent = on ? "\uD83D\uDCF7 \u5173\u95ED\u6444\u50CF\u5934" : "\uD83D\uDCF7 \u5F00\u542F\u6444\u50CF\u5934";
};

const updateTorchBtn = () => {
  const btn = $("#btnTorch");
  if (btn) {
    btn.disabled = !S.camOn;
    btn.textContent = S.torchOn ? "\uD83D\uDD26 \u5173\u706F" : "\uD83D\uDD26 \u5F00\u706F";
  }
};

async function pollHealth() {
  while (true) {
    try {
      const r = await fetch("/api/health");
      const d = await r.json();
      $("#dot").classList.toggle("ok", d.ok);
      $("#conn").textContent = d.ok ? "\u5DF2\u8FDE\u63A5" : "\u8FDE\u63A5\u5931\u8D25";
    } catch(e) {
      $("#dot").classList.remove("ok");
      $("#conn").textContent = "\u8FDE\u63A5\u4E2D\u2026";
    }
    await new Promise(r => setTimeout(r, 3000));
  }
}

async function handle(code) {
  if (S.busy) return;
  S.busy = true;
  try {
    const url = `/api/lookup?barcode=${encodeURIComponent(code)}`;
    const r = await fetch(url);
    const d = await r.json();

    const preview = document.getElementById("preview");
    if (preview) preview.style.display = "block";

    if (d.found) {
      S.pending = { product_id: d.product_id, name: d.name, amount: 1, mode: S.mode };
      document.getElementById("pvName").textContent = d.name;
      toast("\u626B\u7801\u6210\u529F: " + d.name, "info");
      sh("pvNew", "display", "none");
      const stk = d.stock_amount != null ? "\u5E93\u5B58: " + d.stock_amount + " " + (d.qu_stock || "") : "";
      document.getElementById("pvStock").textContent = stk;
      if (d.picture_file_name) {
        document.getElementById("pvImg").src = "/api/image?file=" + encodeURIComponent(d.picture_file_name);
      } else {
        document.getElementById("pvImg").src = "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 88 88' fill='%23eef1f4'%3E%3Crect width='88' height='88'/%3E%3Ctext x='44' y='52' text-anchor='middle' font-size='12' fill='%239aa7b4'%3E%E6%97%A0%E5%9B%BE%E7%89%87%3C/text%3E%3C/svg%3E";
      }
      if (d.description) {
        sh("pvDesc", "display", "block");
        document.getElementById("pvDesc").textContent = d.description;
      } else {
        sh("pvDesc", "display", "none");
      }
      // qty area
      sh("qtyArea", "display", "block");
      sh("createArea", "display", "none");
      const qUnit = document.getElementById("qUnit");
      qUnit.textContent = d.qu_stock || "";
      document.getElementById("qInput").value = 1;
      // mode label
      document.getElementById("pvModeLabel").textContent = (S.mode === "in" ? "\u2190 \u5165\u5e93" : "\u2192 \u51fa\u5e93");
      sh("pvModeLabel", "color", (S.mode === "in" ? "var(--in)" : "var(--out)"));
      // location selector
      var qloc = document.getElementById("qloc");
      if (qloc) {
        qloc.innerHTML = "<option value=''>\u4e0d\u6307\u5b9a\u4f4d\u7f6e</option>";
        (d.locations || []).forEach(function(l) {
          var opt = document.createElement("option");
          opt.value = l.id; opt.textContent = l.name; qloc.appendChild(opt);
        });
      }
    } else if (d.need_create) {
      S.pending = {
        barcode: d.barcode,
        locations: d.locations || [],
        quantity_units: d.quantity_units || [],
        suggest: d.suggest || {},
      };
      document.getElementById("pvName").textContent = "\u65B0\u5EFA: " + d.barcode;
      sh("pvNew", "display", "inline");
      document.getElementById("pvStock").textContent = "\u5E93\u5185\u65E0\u6B64\u6761\u7801";
      sh("pvDesc", "display", "none");
      sh("qtyArea", "display", "none");
      sh("createArea", "display", "block");
      const sug = d.suggest || {};
      document.getElementById("cName").value = sug.name || "";
      document.getElementById("cDesc").value = sug.description || "";
      // locations
      const locSel = document.getElementById("cLoc");
      locSel.innerHTML = "<option value=''>\u8BF7\u9009\u62E9\u4F4D\u7F6E</option>";
      (d.locations || []).forEach(l => {
        const opt = document.createElement("option");
        opt.value = l.id; opt.textContent = l.name; locSel.appendChild(opt);
      });
      // quantity units
      const quSel = document.getElementById("cQu");
      quSel.innerHTML = "<option value=''>\u8BF7\u9009\u62E9\u5355\u4F4D</option>";
      (d.quantity_units || []).forEach(q => {
        const opt = document.createElement("option");
        opt.value = q.id; opt.textContent = q.name; quSel.appendChild(opt);
      });
      // suggest image
      const cImg = document.getElementById("cImg");
      if (sug.image_url) {
        cImg.src = sug.image_url;
        if (cImg) cImg.style.display = "block";
      } else {
        if (cImg) cImg.style.display = "none";
      }
      document.getElementById("cQty").value = 1;
    } else {
      toast(d.error || "\u67E5\u8BE2\u5931\u8D25", "err");
      document.getElementById("mInput").value = code;
      if (preview) preview.style.display = "none";
      S.busy = false;
      return;
    }
  } catch(e) {
    console.error("[handle] error:", e, e && e.message);
    try { toast("\u67E5\u8BE2\u5931\u8D25: " + e.message, "err"); } catch(e2) {}
  }
  S.busy = false;
  // auto scroll to preview
  var pv = document.getElementById("preview");
  if (pv && pv.style.display !== "none") {
    setTimeout(function() { try { pv.scrollIntoView({ behavior: "auto", block: "center" }); } catch(e) {} }, 150);
  }
}

async function confirmStock() {
  if (!S.pending || !S.pending.product_id) return;
  const amount = parseFloat(document.getElementById("qInput").value) || 1;
  try {
    var locId = null;
    var qloc = document.getElementById("qloc");
    if (qloc && qloc.value) locId = parseInt(qloc.value);
    const r = await fetch("/api/stock", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        product_id: S.pending.product_id,
        amount: amount,
        mode: S.mode,
        location_id: locId,
      }),
    });
    const d = await r.json();
    if (d.ok) {
      addLogItem(S.mode, S.pending.name, amount);
      toast(S.mode === "in" ? "\u2705 \u5DF2\u5165\u5E93 " + S.pending.name + " \u00D7" + amount : "\u2705 \u5DF2\u51FA\u5E93 " + S.pending.name + " \u00D7" + amount, "ok");
      closePreview();
    } else {
      toast(d.error || "\u64CD\u4F5C\u5931\u8D25", "err");
    }
  } catch(e) {
    toast("\u8BF7\u6C42\u5931\u8D25: " + e.message, "err");
  }
}

async function confirmCreate() {
  if (!S.pending || !S.pending.barcode) return;
  const name = document.getElementById("cName").value.trim();
  const locId = parseInt(document.getElementById("cLoc").value);
  const quId = parseInt(document.getElementById("cQu").value);
  const qty = parseFloat(document.getElementById("cQty").value) || 1;
  if (!name) { toast("\u8BF7\u8F93\u5165\u4EA7\u54C1\u540D\u79F0", "err"); return; }
  if (!locId) { toast("\u8BF7\u9009\u62E9\u4F4D\u7F6E", "err"); return; }
  if (!quId) { toast("\u8BF7\u9009\u62E9\u5355\u4F4D", "err"); return; }

  try {
    const r = await fetch("/api/create", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        barcode: S.pending.barcode,
        name: name,
        location_id: locId,
        qu_id: quId,
        description: document.getElementById("cDesc").value.trim(),
        image_url: (S.pending.suggest && S.pending.suggest.image_url) || "",
      }),
    });
    const d = await r.json();
    if (d.ok) {
      // auto stock in
      const r2 = await fetch("/api/stock", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          product_id: d.product_id,
          amount: qty,
          mode: "in",
        }),
      });
      const d2 = await r2.json();
      if (d2.ok) {
        addLogItem("in", name, qty);
        toast("\u521B\u5EFA\u5E76\u5165\u5E93\u6210\u529F \u2713", "ok");
      } else {
        toast("\u5DF2\u521B\u5EFA\u4F46\u5165\u5E93\u5931\u8D25: " + (d2.error || ""), "info");
      }
      closePreview();
    } else {
      toast(d.error || "\u521B\u5EFA\u5931\u8D25", "err");
    }
  } catch(e) {
    toast("\u8BF7\u6C42\u5931\u8D25: " + e.message, "err");
  }
}

function closePreview() {
  document.getElementById("preview").style.display = "none";
  S.pending = null;
}

function addLogItem(mode, name, amount) {
  const box = document.getElementById("logList");
  if (!box) return;
  const el = document.createElement("div");
  el.className = "log-item";
  el.innerHTML =
    '<span><span class="' + (mode === "in" ? "tag-in" : "tag-out") + '">' +
    (mode === "in" ? "\u5165" : "\u51FA") +
    '</span> ' + esc(name) + " \u00D7" + amount +
    '</span><span class="t">' + nowStr() + '</span>';
  box.insertBefore(el, box.firstChild);
  while (box.children.length > 15) box.removeChild(box.lastChild);
}

async function startNativeEngine() {
  setEngineBadge("\u539F\u751F\u00B7\u542F\u52A8\u4E2D...");
  const stream = await navigator.mediaDevices.getUserMedia({
    video: { facingMode: "environment" },
    audio: false,
  });
  S.track = stream.getVideoTracks()[0];
  try {
    const [t] = stream.getVideoTracks();
    const c = t.getCapabilities();
    if (c.zoom) t.applyConstraints({ advanced: [{ zoom: Math.min(2.0, c.zoom.max) }] }).catch(() => {});
  } catch (e) {}

  const video = document.getElementById("scanVideo");
  video.style.display = "block";
  document.getElementById("reader").style.display = "none";
  video.srcObject = stream;
  try { await video.play(); } catch (e) {}

  let ready = false;
  await new Promise((r) => {
    const check = () => {
      if (video.readyState >= 2 && video.videoWidth > 0) { ready = true; r(); }
      else setTimeout(check, 50);
    };
    check();
    setTimeout(r, 2000);
  });
  S.nativeVideoReady = ready;
  if (!ready) throw new Error("\u89C6\u9891\u6D41\u5C31\u7EEA\u8D85\u65F6");

  try {
    if (typeof BarcodeDetector !== "undefined" && BarcodeDetector.getSupportedFormats) {
      var supported = await BarcodeDetector.getSupportedFormats();
      var barcodeFmts = ["ean_13", "ean_8", "code_128", "upc_a", "upc_e", "code_39", "code_93", "itf", "codabar"];
      var hasBarcode = barcodeFmts.some(function(f) { return supported.includes(f); });
      if (!hasBarcode) throw new Error("no linear barcode support");
    }
  } catch (e) {
    throw new Error("当前浏览器原生引擎不支持条形码");
  }

  const formats = ["ean_13", "ean_8", "code_128", "upc_a", "upc_e", "code_39", "code_93", "itf", "codabar"];
  let detector = null;
  try {
    detector = new BarcodeDetector({ formats: formats });
  } catch (e) {
    try { detector = new BarcodeDetector({ formats: ["ean_13", "ean_8", "code_128"] }); } catch (e2) {}
  }
  if (!detector) throw new Error("BarcodeDetector \u4E0D\u53EF\u7528");

  let cand = null, candN = 0;

  const tick = () => {
    if (!S.camOn || !S.nativeVideoReady || S.busy) {
      S.nativeDetectTimer = setTimeout(tick, 200);
      return;
    }
    try {
      detector.detect(video).then((codes) => {
        if (S.camOn) {
          const v = (codes && codes[0] && codes[0].rawValue) ? String(codes[0].rawValue).trim() : null;
          if (v) {
            if (v === cand) { candN++; } else { cand = v; candN = 1; }
            if (candN >= 2) { cand = null; candN = 0; onScan(v); }
          } else { cand = null; candN = 0; }
        }
        S.nativeDetectTimer = setTimeout(tick, 200);
      }).catch(() => {
        S.nativeDetectTimer = setTimeout(tick, 200);
      });
    } catch (e) {
      S.nativeDetectTimer = setTimeout(tick, 200);
    }
  };

  S.camOn = true;
  S.camEngine = "native";
  setCamBtnState(true);
  document.getElementById("btnTorch").disabled = false;
  setEngineBadge("\u539F\u751F\u00B7BarcodeDetector");
  setCamOffMsg(false);
  // Start first tick after delay
  setTimeout(function() { if (!S.busy) tick(); }, 200);
}

function startQuaggaEngine() {
  return new Promise((resolve, reject) => {
    const rd = document.getElementById("reader");
    if (S.quaggaInitialized) {
      try { Quagga.stop(); } catch (e) {}
      S.quaggaInitialized = false;
    }

    const ps = (Quagga && Quagga.PatchSize) ? (Quagga.PatchSize.medium || 400) : 400;

    document.getElementById("reader").style.display = "block";
    document.getElementById("scanVideo").style.display = "none";
    function tryInit(workers) {
      Quagga.init({
        inputStream: {
          type: "LiveStream",
          constraints: { facingMode: "environment" },
          target: rd,
          area: { top: "33%", right: "90%", left: "10%", bottom: "67%" },
        },
        decoder: {
          readers: ["ean_reader", "ean_8_reader", "upc_reader", "upc_e_reader", "code_128_reader"],
          multiple: false,
        },
        locator: { patchSize: ps, halfSample: true },
        numOfWorkers: workers,
      }, function (err) {
        if (err) {
          if (workers === 1) { tryInit(0); return; }
          reject(new Error("Quagga init error: " + (err.message || err)));
          return;
        }
        S.quaggaInitialized = true;
        Quagga.onDetected(function (res) {
          const code = res && res.codeResult && res.codeResult.code;
          if (code) onScan(String(code).trim());
        });
        Quagga.start();
        setTimeout(() => {
          try {
            const v = document.querySelector("#reader video");
            if (v && v.srcObject) {
              const [t] = v.srcObject.getVideoTracks();
              S.track = t;
              try {
                const c = t.getCapabilities();
                if (c.zoom) t.applyConstraints({ advanced: [{ zoom: Math.min(2.0, c.zoom.max) }] }).catch(() => {});
              } catch (e) {}
            }
          } catch (e) {}
          resolve();
        }, 800);
      });
    }
    tryInit(1);
  });
}

async function startZXingEngine() {
  if (S.cam) {
    try { await S.cam.stop(); S.cam.clear(); } catch (e) {}
    S.cam = null;
  }

  setEngineBadge("ZXing\u00B7\u542F\u52A8\u4E2D...");

  document.getElementById("reader").style.display = "block";
  document.getElementById("scanVideo").style.display = "none";
  S.cam = new Html5Qrcode("reader", { verbose: false });
  const cfg = {
    fps: 8,
    qrbox: (vw, vh) => { const w = Math.floor(vw * 0.85); return { width: w, height: Math.floor(vw * 0.38) }; },
    aspectRatio: undefined,
  };

  await S.cam.start({ facingMode: "environment" }, cfg, onScan, function(err) { console.warn("[ZXing] qr error:", err); });

  try {
    const v = document.querySelector("#reader video");
    if (v && v.srcObject) { S.track = v.srcObject.getVideoTracks()[0]; }
  } catch (e) {}

  S.camOn = true;
  S.camEngine = "zxing";
  setCamBtnState(true);
  document.getElementById("btnTorch").disabled = false;
  setEngineBadge("\u8F6F\u89E3\u00B7ZXing");
  setCamOffMsg(false);
}

async function stopCam() {
  if (S.torchOn) { try { await setTorch(false); } catch (e) {} }

  if (S.nativeDetectTimer) { clearTimeout(S.nativeDetectTimer); S.nativeDetectTimer = null; }
  S.nativeVideoReady = false;

  if (S.quaggaInitialized) {
    try { Quagga.stop(); } catch (e) {}
    S.quaggaInitialized = false;
  }

  if (S.cam) {
    try { await S.cam.stop(); S.cam.clear(); } catch (e) {}
    S.cam = null;
  }

  if (S.track) {
    try { S.track.stop(); } catch (e) {}
    S.track = null;
  }

  const v = document.getElementById("scanVideo");
  if (v) { v.srcObject = null; v.style.display = "none"; }
  const rd = document.getElementById("reader");
  if (rd) { rd.innerHTML = ""; rd.style.display = "none"; }

  S.camOn = false;
  S.camEngine = null;
  setCamBtnState(false);
  document.getElementById("btnTorch").disabled = true;
  updateTorchBtn();

  setEngineBadge("\u672A\u5F00\u542F");
  setCamOffMsg(true);
}

const QR_FORMATS = [7, 6, 14, 15, 4, 3, 5, 2, 1, 0, 8, 9, 10, 11, 12, 13];
function onScan(code) {
  const t = Date.now();
  if (S.busy) return;
  if (code === S.lastCode && (t - S.lastTime) < 1500) return;
  S.lastCode = code;
  S.lastTime = t;
  console.log("[onScan] detected:", code);
  feedback();
  handle(code);
}

async function setTorch(on) {
  if (!S.track) return;
  try {
    await S.track.applyConstraints({ advanced: [{ torch: on }] });
    S.torchOn = on;
    updateTorchBtn();
  } catch (e) {
    console.warn("[Torch] failed:", e);
    toast("\u624B\u7535\u7B52\u4E0D\u53EF\u7528", "info");
  }
}

async function startCam() {
  const engineMode = S.engine || "auto";
  setCamOffMsg(false);

  try {
    if (engineMode === "native" || engineMode === "auto") {
      if (typeof BarcodeDetector !== "undefined" || typeof window.BarcodeDetector !== "undefined") {
        try {
          await startNativeEngine();
          return;
        } catch (e) {
          console.warn("[Cam] native failed:", e.message || e);
          await stopCam();
          if (engineMode === "native") {
            toast("\u539F\u751F\u5F15\u64CE\u4E0D\u53EF\u7528: " + (e && e.message || e), "err");
            setCamOffMsg(true);
            return;
          }
        }
      } else {
        if (engineMode === "native") {
          toast("\u5F53\u524D\u6D4F\u89C8\u5668\u4E0D\u652F\u6301\u539F\u751F\u6761\u7801\u8BC6\u522B", "err");
          setCamOffMsg(true);
          return;
        }
      }
    }

    if (engineMode === "quagga") {
      try {
        await startQuaggaEngine();
        return;
      } catch (e) {
        console.warn("[Cam] Quagga failed:", e.message || e);
        await stopCam();
        toast("Quagga \u521D\u59CB\u5316\u5931\u8D25, \u56DE\u9000 ZXing", "info");
      }
    }

    await startZXingEngine();
  } catch (e) {
    let msg = "\u65E0\u6CD5\u6253\u5F00\u6444\u50CF\u5934";
    if (e && e.name) {
      if (e.name === "NotAllowedError") msg = "\u6444\u50CF\u5934\u6743\u9650\u88AB\u62D2\u7EDD";
      else if (e.name === "NotFoundError") msg = "\u672A\u627E\u5230\u6444\u50CF\u5934\u8BBE\u5907";
      else if (e.name === "NotReadableError") msg = "\u6444\u50CF\u5934\u88AB\u5176\u4ED6\u5E94\u7528\u5360\u7528";
      else msg = "\u65E0\u6CD5\u6253\u5F00\u6444\u50CF\u5934: " + (e.message || e.name);
    } else if (e) { msg = "\u65E0\u6CD5\u6253\u5F00\u6444\u50CF\u5934: " + (e.message || e); }
    toast(msg, "err");
    setCamOffMsg(true);
  }
}

function closeSettings() {
  document.getElementById("sheetSettings").classList.remove("show");
  document.getElementById("sheetOverlay").classList.remove("show");
}

document.addEventListener("DOMContentLoaded", function () {
  pollHealth();

  document.querySelectorAll("#chipEngine .chip").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll("#chipEngine .chip").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      S.engine = b.dataset.v;
      var name = b.textContent.trim();
      if (S.camOn) {
        toast("已切换至 " + name + " 引擎，重吩摄像头...", "info");
        stopCam().then(function() { setTimeout(function() { startCam(); }, 300); });
      } else {
        toast("已切换至 " + name + " 引擎", "info");
      }
    });
  });

  document.getElementById("btnTorch").addEventListener("click", () => {
    if (!S.camOn) { toast("\u8BF7\u5148\u5F00\u542F\u6444\u50CF\u5934", "info"); return; }
    setTorch(!S.torchOn);
  });

  document.getElementById("btnCam").addEventListener("click", () => {
    if (S.camOn) stopCam();
    else startCam();
  });

  document.getElementById("mGo").addEventListener("click", () => {
    const v = document.getElementById("mInput").value.trim();
    if (v) handle(v);
  });
  document.getElementById("mInput").addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      const v = e.target.value.trim();
      if (v) { handle(v); e.target.select(); }
    }
  });

  document.getElementById("pConfirm").addEventListener("click", confirmStock);
  document.getElementById("pCancel").addEventListener("click", closePreview);

  document.getElementById("qInput").addEventListener("change", function () {
    if (S.pending) S.pending.amount = parseFloat(this.value) || 1;
  });
  document.getElementById("qMinus").addEventListener("click", () => {
    const inp = document.getElementById("qInput");
    const v = parseFloat(inp.value) || 1;
    if (v > 0.001) inp.value = Math.max(0.001, v - 1);
  });
  document.getElementById("qPlus").addEventListener("click", () => {
    const inp = document.getElementById("qInput");
    const v = parseFloat(inp.value) || 1;
    inp.value = v + 1;
  });

  document.getElementById("cMinus").addEventListener("click", () => {
    const inp = document.getElementById("cQty");
    const v = parseFloat(inp.value) || 1;
    if (v > 0.001) inp.value = Math.max(0.001, v - 1);
  });
  document.getElementById("cPlus").addEventListener("click", () => {
    const inp = document.getElementById("cQty");
    const v = parseFloat(inp.value) || 1;
    inp.value = v + 1;
  });

  document.getElementById("btnCreate").addEventListener("click", confirmCreate);
  document.getElementById("btnCNCancel").addEventListener("click", closePreview);

  // FIX 1: Settings panel - use 'show' class, toggle overlay, close button
  document.getElementById("btnSettings").addEventListener("click", () => {
    document.getElementById("sheetSettings").classList.add("show");
    document.getElementById("sheetOverlay").classList.add("show");
  });
  document.getElementById("btnCloseSheet").addEventListener("click", closeSettings);
  document.getElementById("sheetOverlay").addEventListener("click", closeSettings);

  // FIX 2: Mode toggle - move .on between buttons
  document.querySelectorAll("#segMode button").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll("#segMode button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      S.mode = b.dataset.v;
      document.getElementById("segMode").classList.toggle("out", S.mode === "out");
      var ml = document.getElementById("pvModeLabel");
      if (ml) {
        ml.textContent = S.mode === "in" ? "\u2190 \u5165\u5e93" : "\u2192 \u51fa\u5e93";
        ml.style.color = S.mode === "in" ? "var(--in)" : "var(--out)";
      }
    });
  });

  // FIX 3: Qty mode buttons - use 'button' not '.chip'
  document.querySelectorAll("#segQty button").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll("#segQty button").forEach((x) => x.classList.remove("on"));
      b.classList.add("on");
      S.qty = b.dataset.v;
      var ql = document.getElementById("pvQtyLabel");
      if (ql) ql.textContent = S.qty === "each" ? "\u9010\u4ef6" : "\u6570\u91cf";
    });
  });

  // sound/vibration toggle
  document.getElementById("btnSnd").addEventListener("click", function () {
    this.classList.toggle("on");
  });
  document.getElementById("btnVib").addEventListener("click", function () {
    this.classList.toggle("on");
  });
});

