/* REITs 行情分析独立页面：上传 → 口径确认 → 质量/缺口 → 参数 → 生成 → 下载。 */
let sessionId = null;
let capabilities = null;
let lastState = null;
let lastMetrics = null;
let lastResult = null;

const $ = (id) => document.getElementById(id);

function esc(text) {
  return String(text == null ? '' : text).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function setStatus(message, kind) {
  const el = $('reit-status');
  el.textContent = message || '';
  el.className = 'status' + (kind ? ' ' + kind : '');
}

async function api(url, options) {
  const response = await fetch(url, options);
  let payload;
  try { payload = await response.json(); }
  catch (_) { throw new Error('服务返回了无法解析的内容，请检查服务端日志'); }
  if (!response.ok) {
    const error = payload.error || {};
    throw new Error(error.message || payload.detail || `请求失败（${response.status}）`);
  }
  return payload;
}

function artifactUrl(key, url) {
  // 后端在每次 generate 时返回带版本号的 URL，避免浏览器缓存上一版图表/PDF。
  return url || `/api/v1/reits/artifacts/${encodeURIComponent(key)}?session_id=${encodeURIComponent(sessionId)}`;
}

function pct(value) {
  return value == null ? '—' : (value * 100).toFixed(2) + '%';
}

function num(value, digits = 3) {
  return value == null ? '—' : Number(value).toFixed(digits);
}

async function init() {
  setStatus('正在初始化会话…');
  try {
    const [session, cap] = await Promise.all([
      api('/api/v1/reits/session', { method: 'POST' }),
      api('/api/v1/reits/capabilities'),
    ]);
    sessionId = session.session_id;
    capabilities = cap;
    setStatus('会话已就绪，请上传 WIND 导出的 Excel。', 'ok');
  } catch (error) {
    setStatus(error.message, 'err');
  }
}

function renderState(state) {
  lastState = state;
  const q = state.quality || {};
  const w = q.common_window || {};
  const chips = [
    `数据源：${esc(state.source_files.map((f) => f.original_name).join('、') || '—')}`,
    `数据时点：${esc(state.snapshot_date || '—')}`,
    `标的数：${state.series_count}`,
    `公共窗口：${esc(w.start || '—')} ~ ${esc(w.end || '—')}`,
  ];
  const basis = q.price_basis || state.price_basis || null;
  const counts = q.issue_counts || {};
  let html = `<div class="reit-chips">${chips.map((c) => `<span class="reit-chip">${c}</span>`).join('')}`;
  html += `<span class="reit-chip warn">阻断 ${counts.block || 0} / 告警 ${counts.warn || 0} / 说明 ${counts.info || 0}</span></div>`;
  if (basis) {
    html += `<div class="reit-notice">价格口径：${esc(basis.label)}。${esc(basis.source)}${esc(basis.basis)}</div>`;
  }
  html += `<p class="reit-note">${esc(q.note || '')}</p>`;

  const files = (state.source_files || []).filter((f) => f.dimension === 'attachments');
  if (files.length) {
    html += `<div class="reit-notice">以下文件未识别为专用维度，已作为附加数据表纳入「结构概览」；注册解析器后可升级为专项分析：${files
      .map((f) => esc(f.original_name)).join('、')}</div>`;
  }

  html += '<div class="reit-cols"><div><h3>质量提示</h3><div class="reit-scroll"><ul class="reit-list">';
  const issues = q.issues || [];
  html += issues.length
    ? issues.map((i) => `<li>[${esc(i.level)}] ${esc(i.message)}</li>`).join('')
    : '<li>无异常行，解析干净。</li>';
  html += '</ul></div></div><div><h3>数据缺口（做不到的维度不伪造）</h3><div class="reit-scroll"><ul class="reit-list">';
  const gaps = q.gaps || [];
  html += gaps.length
    ? gaps.map((g) => `<li><b>${esc(g.label)}</b>：${esc(g.reason)}</li>`).join('')
    : '<li>暂无已知缺口。</li>';
  html += '</ul></div></div></div>';
  $('reit-quality-body').innerHTML = html;
  $('reit-quality').classList.remove('hidden');

  const hasData = (state.datasets || []).length > 0;
  $('reit-options').classList.toggle('hidden', !hasData);
}

async function refreshMetrics() {
  if (!lastState || !(lastState.datasets || []).length) return;
  try {
    lastMetrics = await api(`/api/v1/reits/metrics?session_id=${encodeURIComponent(sessionId)}`);
    const quote = lastMetrics.quote;
    if (!quote) return;
    const select = $('reit-benchmark');
    const previous = select.value;
    select.innerHTML = quote.series.map((r) =>
      `<option value="${esc(r.code)}">${esc(r.name)}（${esc(r.code)}）</option>`).join('');
    select.value = quote.series.some((r) => r.code === previous)
      ? previous : quote.benchmark_code;
    $('reit-exclude').checked = !!quote.exclude_listing_day;
  } catch (error) {
    setStatus(error.message, 'err');
  }
}

function renderResult(out) {
  lastResult = out;
  const quote = lastMetrics && lastMetrics.quote;
  const bench = out.benchmark || (quote && quote.benchmark) || null;
  let html = `<div class="card"><h2>4. 报告与图表</h2><div class="download-bar">
    <a class="report-link" href="${artifactUrl(out.pdf.key, out.pdf.url)}" download="${esc(out.pdf.name)}">下载 PDF 报告</a>
    <a class="report-link secondary" href="${artifactUrl(out.quality.key, out.quality.url)}" download="${esc(out.quality.name)}">下载解析与质量 JSON</a>
    <span class="reit-note">登记数值 ${out.consistency.registered} 个，一致性校验通过</span>
  </div>`;

  if (bench) {
    const b = (quote && quote.benchmark && quote.benchmark.code === bench.code)
      ? quote.benchmark : null;
    html += `<h3>基准标的：${esc(bench.name)}（${esc(bench.code)}）—— 本报告与下方全部图表均以该标的为准</h3>`;
    if (b) {
      html += `<table class="reit-table"><thead><tr><th>期末收盘价</th><th>年初至今</th><th>上市至今</th><th>年化波动率</th><th>最大回撤</th><th>日均成交额</th></tr></thead>
      <tbody><tr><td>${num(b.snapshot_close)} 元</td><td>${pct(b.ytd_return)}</td>
      <td>${pct(b.since_listing_return)}</td><td>${pct(b.annualized_volatility)}</td>
      <td>${pct(b.max_drawdown)}</td><td>${num(b.avg_amount_million, 2)} 百万元</td></tr></tbody></table>`;
    }
    const ranks = (quote && quote.rankings) || {};
    const defs = [
      ['ytd_return', '年初至今', pct],
      ['window_return', '公共窗口收益', pct],
      ['annualized_volatility', '年化波动率', pct],
      ['max_drawdown', '最大回撤', pct],
      ['avg_amount_million', '日均成交额', (v) => num(v, 2) + ' 百万元'],
    ];
    html += '<h3>横向对标排名</h3><table class="reit-table"><thead><tr><th>指标</th><th>居前</th><th>数值</th><th>居后</th><th>数值</th></tr></thead><tbody>';
    for (const [key, label, fmt] of defs) {
      const rows = ranks[key] || [];
      if (!rows.length) continue;
      const top = rows[0], bottom = rows[rows.length - 1];
      html += `<tr><td>${label}</td><td>${esc(top.name)}</td><td>${fmt(top.value)}</td>
        <td>${esc(bottom.name)}</td><td>${fmt(bottom.value)}</td></tr>`;
    }
    html += '</tbody></table>';
  }

  const labels = {
    price_trend: '归一化累计收益走势', ytd_return: '年初至今涨跌幅',
    since_listing: '上市至今涨跌幅', close_price: '期末收盘价',
    vol_return_scatter: '风险收益散点', drawdown: '最大回撤',
    liquidity: '日均成交额', corr_heatmap: '日收益相关性热力图',
  };
  html += '<div class="reit-section-title">PNG 图表（点击右上角下载原图）</div><div class="grid">';
  for (const chart of out.charts) {
    const url = artifactUrl(chart.key, chart.url);
    html += `<figure>
      <a class="chart-download" href="${url}" download="${esc(chart.name)}" title="下载 ${esc(chart.name)}" aria-label="下载图片">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v3h16v-3"/></svg>
      </a>
      <img src="${url}" alt="${esc(labels[chart.key] || chart.key)}">
      <figcaption>${esc(labels[chart.key] || chart.key)}
        <span class="chart-hint">${esc(chart.name)}</span></figcaption>
    </figure>`;
  }
  html += '</div></div>';
  $('reit-result').innerHTML = html;
  $('reit-result').classList.remove('hidden');
  $('reit-result').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

$('reit-upload').addEventListener('click', async () => {
  const files = $('reit-files').files;
  if (!files.length) { setStatus('请先选择要上传的 Excel 文件。', 'err'); return; }
  const button = $('reit-upload');
  button.disabled = true;
  setStatus('正在上传并解析工作簿（大文件可能需要几秒）…');
  const form = new FormData();
  for (const file of files) form.append('files', file);
  try {
    const state = await api(`/api/v1/reits/upload?session_id=${encodeURIComponent(sessionId)}`,
      { method: 'POST', body: form });
    invalidateResult();
    renderState(state);
    await refreshMetrics();
    setStatus((state.notes || []).join('；') || '解析完成。', 'ok');
  } catch (error) {
    setStatus(error.message, 'err');
  } finally {
    button.disabled = false;
  }
});

function invalidateResult() {
  lastResult = null;
  $('reit-result').innerHTML = '';
  $('reit-result').classList.add('hidden');
}

async function regenerate(silent) {
  const button = $('reit-generate');
  button.disabled = true;
  if (!silent) setStatus('正在生成 PDF 报告与 8 张 PNG 图表…');
  try {
    const out = await api('/api/v1/reits/generate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: sessionId }),
    });
    await refreshMetrics();
    renderResult(out);
    const label = out.benchmark
      ? `${out.benchmark.name}（${out.benchmark.code}）` : '当前参数';
    setStatus(silent ? `已按基准 ${label} 重新生成报告与图表。`
                     : '报告与图表已生成，可逐项下载。', 'ok');
  } catch (error) {
    setStatus(error.message, 'err');
  } finally {
    button.disabled = false;
  }
}

async function applyOptions() {
  try {
    await api('/api/v1/reits/options', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        benchmark: $('reit-benchmark').value,
        exclude_listing_day: $('reit-exclude').checked,
      }),
    });
    if (lastResult) {
      // 已生成过结果：立即按新基准重算并刷新 PDF / 全部 PNG，避免下方停留在旧基准。
      await regenerate(true);
    } else {
      await refreshMetrics();
      setStatus('对标参数已更新，点击「生成」即可按当前基准出报告。', 'ok');
    }
  } catch (error) {
    setStatus(error.message, 'err');
  }
}

$('reit-benchmark').addEventListener('change', applyOptions);
$('reit-exclude').addEventListener('change', applyOptions);

$('reit-generate').addEventListener('click', () => regenerate(false));

window.addEventListener('pagehide', () => {
  if (sessionId) {
    try {
      fetch(`/api/v1/sessions/${sessionId}`, { method: 'DELETE', keepalive: true });
    } catch (_) { /* TTL 兜底 */ }
  }
});

init();
