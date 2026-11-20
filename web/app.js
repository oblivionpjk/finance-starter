let sessionId = null;
let cfg = null;
let inspectData = null;

const $ = (sel) => document.querySelector(sel);

function setStatus(text, kind = "info") {
  const el = $("#status");
  el.className = "status " + (kind === "error" ? "err" : kind === "ok" ? "ok" : "");
  el.textContent = text || "";
}

async function api(path, options = {}) {
  const res = await fetch(path, options);
  const type = res.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const e = (data && data.error) || {};
    const err = new Error(`[${e.code || res.status}] ${e.message || data.detail || res.statusText}` +
                          (e.detail ? ` — ${e.detail}` : ""));
    err.code = e.code || "";
    err.data = e.data || null;
    throw err;
  }
  return data;
}

function esc(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function fillSelect(el, items, defaultName) {
  el.innerHTML = "";
  for (const it of items) {
    const opt = document.createElement("option");
    opt.value = typeof it === "string" ? it : it.name;
    opt.textContent = typeof it === "string" ? it : it.label;
    el.appendChild(opt);
  }
  if (defaultName && items.some((it) => (typeof it === "string" ? it : it.name) === defaultName)) {
    el.value = defaultName;
  }
}

function artifactUrl(name) {
  return `/api/v1/sessions/${sessionId}/artifacts/${encodeURIComponent(name)}`;
}

// 下载图标：内联 SVG，不依赖外部图标库
const CHART_DOWNLOAD_ICON =
  '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
  '<path d="M12 3.5v10.8m0 0 4.2-4.2M12 14.3 7.8 10.1' +
  'M4.5 16.8v2.1a1.9 1.9 0 0 0 1.9 1.9h11.2a1.9 1.9 0 0 0 1.9-1.9v-2.1" ' +
  'fill="none" stroke="currentColor" stroke-width="1.8" ' +
  'stroke-linecap="round" stroke-linejoin="round"/></svg>';

function safeFileName(s) {
  return String(s)
    .replace(/[\\/:*?"<>|\u0000-\u001f]/g, "·")  // 文件名非法字符（如标题里的 /）换成中文间隔符
    .replace(/\s*·\s*/g, "·")                    // 去掉分隔符两侧空白
    .replace(/·{2,}/g, "·")
    .replace(/_{2,}/g, "_")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80)
    .replace(/[·_\s]+$/, "");                     // 截断后不留结尾分隔符
}

function chartFileName(subject, title) {
  return (safeFileName(`${subject || "财务分析"}_${title || "数据分析图"}`) || "数据分析图") + ".png";
}

async function downloadChart(link, chart, subject) {
  if (link.getAttribute("aria-busy") === "true") return;
  link.setAttribute("aria-busy", "true");
  try {
    // 先取成 blob：可捕获会话过期等错误，并给出可读的中文文件名
    const res = await fetch(artifactUrl(chart.name));
    if (!res.ok) {
      let msg = `HTTP ${res.status}`;
      try {
        const body = await res.json();
        msg = body.detail || (body.error && body.error.message) || msg;
      } catch (_) { /* 非 JSON 错误响应，保留 HTTP 状态码 */ }
      throw new Error(msg);
    }
    const blob = await res.blob();
    if (!blob.type.startsWith("image/")) {
      throw new Error(`返回内容不是图片（${blob.type || "未知类型"}）`);
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = chartFileName(subject, chart.title);
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 60000);
    setStatus(`已下载图表：${chart.title}`, "ok");
  } catch (e) {
    setStatus(`下载《${chart.title}》失败：${e.message}。若会话已过期，请重新生成报告。`, "error");
  } finally {
    link.removeAttribute("aria-busy");
  }
}

function renderMapping(data) {
  inspectData = data;
  const box = $("#mapping");
  box.innerHTML = "";
  const h = document.createElement("h2");
  h.textContent = "确认报表角色与科目映射";
  box.appendChild(h);

  const intro = document.createElement("p");
  intro.className = "meta";
  intro.textContent = `已解析 ${data.files.length} 张表；自动映射 ${data.mapped.length} 个科目，` +
    `${data.unmapped.length} 个可能需要指定。未指定的科目不参与分析。`;
  box.appendChild(intro);

  const h3 = document.createElement("h3");
  h3.textContent = "报表角色";
  box.appendChild(h3);
  for (const f of data.files) {
    const row = document.createElement("div");
    row.className = "map-row";
    const label = document.createElement("span");
    label.className = "raw";
    label.textContent = `${f.name}（${f.layout === "by_date" ? "报告日 × 科目" : "项目 × 期间"}，${f.labels} 个科目）`;
    const sel = document.createElement("select");
    for (const [v, t] of [["BS", "资产负债表"], ["IS", "利润表"], ["CF", "现金流量表"]]) {
      const o = document.createElement("option");
      o.value = v; o.textContent = t;
      sel.appendChild(o);
    }
    sel.value = f.role_guess;
    sel.dataset.role = f.name;
    row.append(label, sel);
    box.appendChild(row);
  }

  if (data.unmapped.length) {
    const h4 = document.createElement("h3");
    h4.textContent = "未自动映射的科目（可选指定）";
    box.appendChild(h4);
    for (const item of data.unmapped) {
      const row = document.createElement("div");
      row.className = "map-row";
      const label = document.createElement("span");
      label.className = "raw";
      label.textContent = item.raw;
      const sel = document.createElement("select");
      const ignore = document.createElement("option");
      ignore.value = ""; ignore.textContent = "忽略（不参与分析）";
      sel.appendChild(ignore);
      for (const s of item.suggestions || []) {
        const o = document.createElement("option");
        o.value = s.item_key; o.textContent = `${s.label}（相似度 ${s.score}）`;
        sel.appendChild(o);
      }
      sel.dataset.override = item.raw;
      row.append(label, sel);
      box.appendChild(row);
    }
  }

  const btn = document.createElement("button");
  btn.className = "primary";
  btn.id = "btn-analyze";
  btn.style.marginTop = "16px";
  btn.textContent = "确认并生成报告";
  btn.onclick = runUploadAnalysis;
  box.appendChild(btn);
  box.classList.remove("hidden");
}

async function runUploadAnalysis() {
  const btn = $("#btn-analyze");
  btn.disabled = true;
  setStatus("正在校验、计算指标并生成 PDF 报告…");
  const roles = {}, overrides = {};
  document.querySelectorAll("[data-role]").forEach((el) => { roles[el.dataset.role] = el.value; });
  document.querySelectorAll("[data-override]").forEach((el) => { overrides[el.dataset.override] = el.value; });
  try {
    const out = await api(`/api/v1/sessions/${sessionId}/analyze`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ unit: $("#unit").value, roles, overrides,
                             periods: Number($("#up-periods").value) }),
    });
    renderResult(out);
    setStatus("报告已生成。", "ok");
  } catch (e) {
    setStatus(e.message, "error");
  } finally {
    btn.disabled = false;
  }
}

function renderResult(out) {
  const el = $("#result");
  el.innerHTML = "";
  const card = document.createElement("div");
  card.className = "card";
  const title = document.createElement("h2");
  title.textContent = `${out.subject} · 财务分析结果`;
  card.appendChild(title);
  if (out.company_name) {
    const cn = document.createElement("p");
    cn.className = "meta";
    cn.textContent = `公司名称：${out.company_name} ｜ 名称来源：${out.name_source || "本地证券简称表"}`;
    card.appendChild(cn);
  }
  const meta = document.createElement("p");
  meta.className = "meta";
  meta.textContent = `报告期：${out.periods.join("、")} ｜ 图表 ${out.charts.length} 张 ｜ ` +
    `数字一致性校验：${out.consistency.passed ? "通过" : "未通过"}（登记 ${out.consistency.registered_numbers} 个数值）`;
  card.appendChild(meta);
  if (out.note) {
    const note = document.createElement("p");
    note.className = "meta"; note.textContent = out.note;
    card.appendChild(note);
  }
  const link = document.createElement("a");
  link.className = "report-link";
  link.href = artifactUrl(out.report.name);
  link.target = "_blank";
  link.rel = "noopener";
  link.textContent = "打开 / 下载 PDF 报告";
  link.style.margin = "10px 0";
  card.appendChild(link);
  const retention = document.createElement("p");
  retention.className = "hint"; retention.textContent = out.retention;
  card.appendChild(retention);
  el.appendChild(card);

  const sum = document.createElement("div");
  sum.className = "card";
  sum.innerHTML = "<h2>结论摘要</h2>";
  const ul = document.createElement("ul");
  ul.className = "tight";
  for (const i of out.insights) {
    const li = document.createElement("li");
    li.textContent = i.text;
    if (i.level === "warn") li.style.color = "#9a5b00";
    ul.appendChild(li);
  }
  sum.appendChild(ul);
  el.appendChild(sum);

  if (out.quality && out.quality.length) {
    const q = document.createElement("div");
    q.className = "card";
    q.innerHTML = "<h2>数据质量</h2>";
    const table = document.createElement("table");
    table.innerHTML = "<thead><tr><th>级别</th><th>说明</th><th>明细</th></tr></thead>";
    const body = document.createElement("tbody");
    for (const item of out.quality) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(item.level)}</td><td>${esc(item.message)}</td><td>${esc(item.detail)}</td>`;
      body.appendChild(tr);
    }
    table.appendChild(body); q.appendChild(table); el.appendChild(q);
  }

  const charts = document.createElement("div");
  charts.className = "card";
  const chartTitle = document.createElement("h2");
  chartTitle.textContent = "数据分析图";
  const chartHint = document.createElement("span");
  chartHint.className = "chart-hint";
  chartHint.textContent = "点击每张图右上角的下载图标，可单独保存 PNG 图片";
  chartTitle.appendChild(chartHint);
  charts.appendChild(chartTitle);
  const grid = document.createElement("div");
  grid.className = "grid";
  for (const c of out.charts) {
    const fig = document.createElement("figure");
    const img = document.createElement("img");
    img.src = artifactUrl(c.name);
    img.alt = c.title;
    img.loading = "lazy";
    const dl = document.createElement("a");
    dl.className = "chart-download";
    dl.href = artifactUrl(c.name);   // JS 失效时仍可右键另存为 / 直接下载
    dl.download = chartFileName(out.subject, c.title);
    dl.title = `下载《${c.title}》PNG 图片`;
    dl.setAttribute("aria-label", dl.title);
    dl.innerHTML = CHART_DOWNLOAD_ICON;
    dl.addEventListener("click", (ev) => {
      ev.preventDefault();           // 走 fetch，便于捕获会话过期等错误
      downloadChart(dl, c, out.subject);
    });
    const cap = document.createElement("figcaption");
    cap.textContent = c.caption;
    fig.append(img, dl, cap);
    grid.appendChild(fig);
  }
  charts.appendChild(grid);
  el.appendChild(charts);
  el.classList.remove("hidden");
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function init() {
  try {
    const [c, s] = await Promise.all([
      api("/api/v1/config"),
      api("/api/v1/sessions", { method: "POST" }),
    ]);
    cfg = c; sessionId = s.session_id;
    fillSelect($("#source"), c.sources, c.default_source);
    fillSelect($("#unit"), c.units, c.default_unit || "元");
    $("#periods").value = c.default_periods;
    $("#up-periods").value = c.default_periods;
    setStatus("已就绪。", "ok");
  } catch (e) {
    setStatus(e.message, "error");
  }
}

// 代码输入框：输满 6 位时实时显示对应的公司名称与名称来源
const companyNameCache = new Map();
let companyNameSeq = 0;

async function showCodeName() {
  const code = $("#code").value.trim();
  const el = $("#code-name");
  if (!/^\d{6}$/.test(code)) {
    el.textContent = "";
    el.className = "hint";
    return;
  }
  const seq = ++companyNameSeq;
  el.textContent = `正在查询 ${code} 对应的公司名称…`;
  el.className = "hint";
  if (!companyNameCache.has(code)) {
    try {
      companyNameCache.set(code, await api(`/api/v1/company-name/${code}`));
    } catch (_) {
      // in_name_table=null 表示查询失败、状态未知，避免误报「无效代码」
      companyNameCache.set(code, { company_name: null, name_source: "", in_name_table: null });
    }
  }
  if (seq !== companyNameSeq) return;   // 输入已变化，丢弃过期响应
  const info = companyNameCache.get(code);
  const nameText = info.company_name
    ? `对应公司：${info.company_name}（${code}）` : `未取得 ${code} 的证券简称`;
  if (info.in_name_table === false) {
    // 简称表缺失只说明「本地表未收录」，不等于代码无效：新股 / 快照过期时，
    // 在线接口仍可能有数据。输入阶段不预判在线结果，避免误导用户。
    el.textContent = `${code} 未收录于本地简称表（可能是新股或快照未更新）；`
      + `可切换在线源尝试取数，或刷新简称表后重试。`;
    el.className = "hint name-miss";
  } else if (info.local_statement_available) {
    el.textContent = info.company_name
      ? `${nameText}｜名称来源：${info.name_source}`
      : `${nameText}，报告将仅显示代码。`;
    el.className = info.company_name ? "hint name-ok" : "hint name-miss";
  } else {
    el.textContent = `${nameText}｜本地快照未收录其财报，需切换在线源或上传报表。`;
    el.className = "hint name-warn";
  }
}

$("#code").addEventListener("input", showCodeName);

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    tab.classList.add("active");
    $("#panel-code").classList.toggle("hidden", tab.dataset.tab !== "code");
    $("#panel-upload").classList.toggle("hidden", tab.dataset.tab !== "upload");
  });
});

function renderLocalMissCard(e, code) {
  const el = $("#result");
  el.innerHTML = "";
  const card = document.createElement("div");
  card.className = "card error-card";
  const h = document.createElement("h2");
  h.textContent = `本地快照未收录 ${code} 的财报`;
  card.appendChild(h);
  const p = document.createElement("p");
  p.className = "meta";
  const missing = (e.data && e.data.missing_files) || [];
  p.textContent = `缺少 ${missing.join("、") || "三大报表文件"}。本地离线源只收录有限标的，`
    + "切换到在线数据源或上传三大报表即可继续分析。";
  card.appendChild(p);
  const actions = document.createElement("div");
  actions.className = "error-actions";
  const sel = $("#source");
  const hasOnline = !!sel.querySelector('option[value="akshare"]');
  const retry = document.createElement("button");
  retry.className = "primary";
  retry.textContent = hasOnline ? "切换到在线数据源重试" : "重新尝试";
  retry.onclick = () => {
    if (hasOnline) sel.value = "akshare";
    runCodeAnalysis();
  };
  const upload = document.createElement("button");
  upload.className = "secondary";
  upload.textContent = "改用上传三大报表";
  upload.onclick = () => {
    const tab = document.querySelector('.tab[data-tab="upload"]');
    if (tab) tab.click();
    $("#panel-upload").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  actions.append(retry, upload);
  card.appendChild(actions);
  el.appendChild(card);
  el.classList.remove("hidden");
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderOnlineNotFoundCard(e, code) {
  const el = $("#result");
  el.innerHTML = "";
  const card = document.createElement("div");
  card.className = "card error-card";
  const h = document.createElement("h2");
  h.textContent = `在线数据源未取得 ${code} 的财报`;
  card.appendChild(h);
  const p = document.createElement("p");
  p.className = "meta";
  const data = e.data || {};
  const known = data.known_name ? `（证券简称表记录的名称：${data.known_name}）` : "";
  p.textContent = (data.reason || "该代码可能不是有效的沪深 A 股代码")
    + `${known}。请核对 6 位代码是否正确；重试无法解决。`
    + "若你确实持有该公司的三大报表，可改用上传方式生成报告。";
  card.appendChild(p);
  const actions = document.createElement("div");
  actions.className = "error-actions";
  const recheck = document.createElement("button");
  recheck.className = "primary";
  recheck.textContent = "返回核对代码";
  recheck.onclick = () => {
    const input = $("#code");
    input.scrollIntoView({ behavior: "smooth", block: "center" });
    input.focus();
    input.select();
  };
  const upload = document.createElement("button");
  upload.className = "secondary";
  upload.textContent = "改用上传三大报表";
  upload.onclick = () => {
    const tab = document.querySelector('.tab[data-tab="upload"]');
    if (tab) tab.click();
    $("#panel-upload").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  actions.append(recheck, upload);
  card.appendChild(actions);
  el.appendChild(card);
  el.classList.remove("hidden");
  el.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function runCodeAnalysis() {
  const btn = $("#btn-code");
  const code = $("#code").value.trim();
  if (!/^\d{6}$/.test(code)) { setStatus("请输入 6 位数字代码。", "error"); return; }
  btn.disabled = true;
  const resultEl = $("#result");
  resultEl.innerHTML = "";
  resultEl.classList.add("hidden");
  setStatus("正在获取财报、校验并生成报告…");
  try {
    const out = await api(`/api/v1/sessions/${sessionId}/analyze-code`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code, source: $("#source").value,
                             periods: Number($("#periods").value) }),
    });
    renderResult(out);
    setStatus("报告已生成。", "ok");
  } catch (e) {
    if (e.code === "LOCAL_SNAPSHOT_MISS") {
      setStatus(`本地快照未收录 ${code} 的财报。`, "error");
      renderLocalMissCard(e, code);
    } else if (e.code === "ONLINE_CODE_NOT_FOUND") {
      setStatus(`在线数据源未取得 ${code} 的财报。`, "error");
      renderOnlineNotFoundCard(e, code);
    } else {
      setStatus(e.message, "error");
    }
  } finally {
    btn.disabled = false;
  }
}

$("#btn-code").addEventListener("click", runCodeAnalysis);

$("#btn-upload").addEventListener("click", async () => {
  const files = $("#files").files;
  if (!files.length) { setStatus("请先选择报表文件。", "error"); return; }
  const btn = $("#btn-upload");
  btn.disabled = true;
  setStatus("正在上传并解析表格…");
  const fd = new FormData();
  for (const f of files) fd.append("files", f);
  try {
    const data = await api(`/api/v1/sessions/${sessionId}/upload`, { method: "POST", body: fd });
    renderMapping(data);
    setStatus("请确认报表角色与科目映射后生成报告。", "ok");
  } catch (e) {
    setStatus(e.message, "error");
  } finally {
    btn.disabled = false;
  }
});

window.addEventListener("pagehide", () => {
  if (sessionId) {
    try {
      fetch(`/api/v1/sessions/${sessionId}`, { method: "DELETE", keepalive: true });
    } catch (_) { /* 页面关闭时清理失败由服务端 TTL 兜底 */ }
  }
});

init();
