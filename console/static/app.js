'use strict';

const $ = (id) => document.getElementById(id);
const names = { overview: '概览', library: '证据库', pack: '上下文工作台', sources: '数据接入' };
const sourceNames = { manual: '手动资料', notion: 'Notion', google_calendar: '日历', github: 'GitHub' };
let status = null;
let currentView = 'overview';
let offset = 0;
let searchSequence = 0;
let packText = '';
let toastTimer;
let lastDetailTrigger;

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
}

function toast(message, error = false) {
  clearTimeout(toastTimer);
  $('toast').textContent = message;
  $('toast').className = error ? 'error' : '';
  $('toast').hidden = false;
  toastTimer = setTimeout(() => { $('toast').hidden = true; }, error ? 7000 : 4500);
}

async function api(action, data) {
  const response = await fetch(`/api/${action}`, data === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || '工作台暂时不可用，请重试');
  return result;
}

function date(value, short = false) {
  if (!value || Number.isNaN(new Date(value).getTime())) return '时间未记录';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: '2-digit', day: '2-digit',
    ...(short ? {} : { year: 'numeric', hour: '2-digit', minute: '2-digit' }),
  }).format(new Date(value));
}

function empty(target, title, text, withAction = true) {
  const content = node('div', 'empty-state');
  content.append(node('div', 'empty-symbol', '▤'), node('h3', '', title), node('p', '', text));
  if (withAction) {
    const link = node('a', 'button secondary', '导入第一条资料 →');
    link.href = '#sources'; content.append(link);
  }
  $(target).replaceChildren(content);
}

function evidenceRow(item) {
  const button = node('button', 'evidence-row');
  button.type = 'button';
  button.setAttribute('aria-label', `打开证据：${item.title || item.item_id}`);
  const icon = node('span', 'evidence-icon', item.connector_id === 'notion' ? 'N' : item.connector_id === 'manual' ? '≡' : '▦');
  const info = node('div', 'evidence-info');
  info.append(node('h3', '', item.title || '未命名资料'));
  const meta = node('div', 'evidence-meta');
  meta.append(node('span', 'source-tag', sourceNames[item.connector_id] || item.connector_id));
  if (item.demo) meta.append(node('span', 'demo-tag', '演示资料'));
  else if (item.provenance === 'export') meta.append(node('span', '', '用户资料'));
  meta.append(node('span', '', date(item.captured_at)));
  info.append(meta);
  button.append(icon, info, node('span', 'row-arrow', '↗'));
  button.addEventListener('click', () => openItem(item.item_id, button));
  return button;
}

async function refreshStatus() {
  try {
    status = await api('status');
    $('stat-total').textContent = status.total;
    $('stat-sources').textContent = status.source_count;
    $('nav-count').textContent = status.total;
    $('demo-note').hidden = !status.demo_count;
    $('demo-note').textContent = `${status.demo_count} 条演示`;
    $('connection-text').textContent = '本机服务运行中';
    $('connection-dot').classList.remove('offline');
    $('last-sync').textContent = status.last_ingested_at ? `最近保存 ${date(status.last_ingested_at)}` : '尚未导入资料 · 本地工作空间';
    $('notion-state').textContent = status.notion.ok ? '● 已配置 · 可以同步已授权页面' : '○ 尚未配置 · 完成下方设置后重启服务';
    $('sync-notion').disabled = !status.notion.ok;
    $('notion-setup').hidden = status.notion.ok;
    const previousSource = $('search-source').value;
    $('search-source').replaceChildren(new Option('全部来源', ''));
    for (const id of [...new Set(status.sources.map((s) => s.connector_id))]) {
      $('search-source').append(new Option(sourceNames[id] || id, id));
    }
    $('search-source').value = previousSource;
    $('source-list').replaceChildren();
    if (!status.sources.length) $('source-list').append(node('p', 'source-empty', '尚无来源。保存资料后会显示在这里。'));
    for (const source of status.sources) {
      const record = node('div', 'source-record');
      const label = node('div', '', sourceNames[source.connector_id] || source.connector_id);
      label.append(node('small', '', source.source_id.startsWith('demo_') ? '演示资料' : source.source_id.startsWith('import_') ? '文件导入' : source.connector_id === 'manual' ? '手动保存' : '已授权接入'));
      record.append(label, node('span', '', `${source.item_count} 条`));
      $('source-list').append(record);
    }
  } catch (error) {
    $('connection-text').textContent = '服务连接中断';
    $('connection-dot').classList.add('offline');
    throw error;
  }
}

async function loadRecent() {
  const data = await api('search?limit=5');
  $('recent-items').replaceChildren(...data.items.map(evidenceRow));
  if (!data.items.length) empty('recent-items', '从第一条证据开始', '留下一段笔记，或导入你已有的资料。');
}

async function loadLibrary() {
  const sequence = ++searchSequence;
  const params = new URLSearchParams({ q: $('search-query').value, source: $('search-source').value, days: $('search-days').value, limit: '30', offset: String(offset) });
  $('search-summary').textContent = '正在查找…';
  const data = await api(`search?${params}`);
  if (sequence !== searchSequence) return;
  $('library-items').replaceChildren(...data.items.map(evidenceRow));
  $('search-summary').textContent = `共 ${data.total} 条证据`;
  $('prev-page').disabled = offset === 0;
  $('next-page').disabled = !data.has_more;
  $('page-label').textContent = data.total ? `${offset + 1}–${offset + data.count} / ${data.total}` : '0 条';
  if (!data.items.length) empty('library-items', '还没有找到相关证据', '换个关键词或调整筛选范围，也可以先导入新的资料。', !status?.total);
}

async function openItem(id, trigger) {
  try {
    const item = await api(`item?id=${encodeURIComponent(id)}`);
    lastDetailTrigger = trigger || document.activeElement;
    const content = $('detail-content');
    content.replaceChildren();
    const meta = node('div', 'detail-meta');
    meta.append(node('span', 'source-tag', sourceNames[item.connector_id] || item.connector_id), node('span', '', date(item.captured_at)));
    if (item.provenance?.demo) meta.append(node('span', 'demo-tag', '演示资料'));
    content.append(meta, node('h2', '', item.title || '未命名资料'));
    const sources = { platform: '已授权平台原文', export: '用户导入资料', agent: 'Agent 生成资料' };
    content.append(node('div', 'detail-provenance', `${sources[item.provenance?.source] || '来源未标记'} · ${item.provenance?.human_reviewed ? '已人工审核' : '未标记人工审核'}`));
    content.append(node('div', 'detail-body', item.text || '这条资料没有正文。'));
    try {
      const url = new URL(item.source_url);
      if (['http:', 'https:'].includes(url.protocol)) {
        const link = node('a', 'button secondary detail-source', '打开原始来源 ↗');
        link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; content.append(link);
      }
    } catch { /* Notes without an external source have no link. */ }
    const details = node('details', 'detail-integrity');
    details.append(node('summary', '', '查看证据标识与完整性信息'), node('pre', '', `ID: ${item.item_id}\nSHA-256: ${item.content_sha256 || '历史资料未记录'}\nRAW: ${item.raw_uri || '历史资料未记录'}`));
    content.append(details);
    if (!$('detail-dialog').open) $('detail-dialog').showModal();
    $('close-detail').focus();
  } catch (error) { toast(error.message, true); }
}

async function route() {
  const view = location.hash.slice(1) || 'overview';
  currentView = names[view] ? view : 'overview';
  for (const key of Object.keys(names)) $(`view-${key}`).hidden = key !== currentView;
  document.querySelectorAll('[data-view]').forEach((link) => {
    const active = link.dataset.view === currentView;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page'); else link.removeAttribute('aria-current');
    link.setAttribute('aria-label', names[link.dataset.view]);
  });
  $('breadcrumb-current').textContent = names[currentView];
  document.title = `${names[currentView]} · Evidplane`;
  try {
    if (currentView === 'overview') await loadRecent();
    if (currentView === 'library') { offset = 0; await loadLibrary(); }
  } catch (error) { toast(error.message, true); }
}

async function busy(button, work, message) {
  const label = button.textContent;
  button.disabled = true; button.textContent = '处理中…';
  try {
    const result = await work();
    toast(typeof message === 'function' ? message(result) : message);
    await refreshStatus();
    return result;
  } catch (error) { toast(error.message || '操作失败，请重试', true); }
  finally { button.textContent = label; button.disabled = false; }
}

$('search-form').addEventListener('submit', (event) => { event.preventDefault(); offset = 0; loadLibrary().catch((e) => toast(e.message, true)); });
for (const id of ['search-source', 'search-days']) $(id).addEventListener('change', () => $('search-form').requestSubmit());
$('prev-page').addEventListener('click', () => { offset = Math.max(0, offset - 30); loadLibrary().catch((e) => toast(e.message, true)); });
$('next-page').addEventListener('click', () => { offset += 30; loadLibrary().catch((e) => toast(e.message, true)); });
$('close-detail').addEventListener('click', () => $('detail-dialog').close());
$('detail-dialog').addEventListener('close', () => lastDetailTrigger?.focus());
$('detail-dialog').addEventListener('click', (event) => { if (event.target === $('detail-dialog') && event.clientX < $('detail-dialog').getBoundingClientRect().left) $('detail-dialog').close(); });

document.querySelectorAll('[data-tab]').forEach((button) => button.addEventListener('click', () => {
  document.querySelectorAll('[data-tab]').forEach((tab) => {
    const selected = tab === button;
    tab.setAttribute('aria-selected', String(selected));
    $(`tab-${tab.dataset.tab}`).hidden = !selected;
  });
}));

$('text-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const result = await busy(event.submitter, () => api('import-text', { title: $('note-title').value, text: $('note-text').value, url: $('note-url').value || null }), (r) => r.inserted ? '资料已保存，打开证据库即可查看' : '相同资料已存在，已完成去重');
  if (result) { $('text-form').reset(); location.hash = '#library'; }
});
$('import-file').addEventListener('change', () => { $('file-name').textContent = $('import-file').files[0]?.name || '选择需要导入的文件'; });
$('file-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const file = $('import-file').files[0];
  if (!file || file.size > 2 * 1024 * 1024) { toast('请选择不超过 2 MB 的 JSON 文件', true); return; }
  const result = await busy(event.submitter, async () => api('import-file', JSON.parse(await file.text())), (r) => `已导入 ${r.upserted} 条资料（新增 ${r.inserted} 条）`);
  if (result) { $('file-form').reset(); location.hash = '#library'; }
});
$('import-demo').addEventListener('click', async (event) => {
  const result = await busy(event.currentTarget, () => api('import-demo', {}), '演示资料已导入，所有示例均已标记');
  if (result) location.hash = '#library';
});
$('sync-notion').addEventListener('click', (event) => busy(event.currentTarget, () => api('sync-notion', {}), (r) => r.partial ? `部分同步：保存 ${r.upserted} 条，${r.failed} 条失败，请检查源权限后重试` : `同步完成：新增 ${r.inserted} 条，更新 ${r.updated} 条，未变 ${r.unchanged} 条`));

$('pack-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  await busy($('generate-pack'), async () => {
    const params = new URLSearchParams({ budget: $('pack-budget').value, days: $('pack-days').value });
    const pack = await api(`pack?${params}`);
    packText = pack.text;
    $('pack-empty').hidden = true;
    $('pack-meta').hidden = false;
    $('pack-meta').textContent = `${pack.item_count} 条证据 · 估算 ${pack.token_estimate} / ${pack.budget_tokens} tokens · 最近 ${pack.since_days} 天`;
    $('pack-text').textContent = pack.item_count ? pack.text : '所选时间范围内没有资料。请扩大时间范围，或先导入一些资料。';
    $('pack-text').hidden = false;
    $('copy-pack').disabled = !pack.item_count;
    $('pack-citations').hidden = !pack.cites.length;
    $('citation-items').replaceChildren(...pack.cites.map((cite, index) => {
      const button = node('button', 'citation-button');
      button.append(node('span', '', `${String(index + 1).padStart(2, '0')}  ${cite.title}${cite.demo ? ' · 演示' : ''}`), node('span', '', '↗'));
      button.addEventListener('click', () => openItem(cite.item_id, button));
      return button;
    }));
    return pack;
  }, (r) => r.item_count ? '上下文已生成，引用可逐条回查' : '当前时间范围内暂无证据');
});
$('copy-pack').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText(packText); toast('已复制上下文正文'); }
  catch { toast('无法访问剪贴板，请选择正文后复制', true); }
});

window.addEventListener('hashchange', route);
refreshStatus().then(route).catch((error) => toast(error.message, true));
