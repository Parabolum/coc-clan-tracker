if (window.location.protocol === 'file:') {
  window.location.replace('http://127.0.0.1:8001/admin');
} else {
let authorization = '';
let adminMembers = [];

const $ = (id) => document.getElementById(id);
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[character]);

function basicHeader(username, password) {
  const bytes = new TextEncoder().encode(`${username}:${password}`);
  let binary = '';
  bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
  return `Basic ${btoa(binary)}`;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.headers || {}), Authorization: authorization, ...(options.body ? { 'Content-Type': 'application/json' } : {}) }
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `Anfrage fehlgeschlagen (${response.status})`);
  return payload;
}

function showMessage(element, text, isError = false) {
  element.textContent = text;
  element.classList.toggle('error', isError);
}

function switchPanel(panelId) {
  document.querySelectorAll('.admin-tab').forEach((tab) => tab.classList.toggle('active', tab.dataset.panel === panelId));
  document.querySelectorAll('.admin-panel').forEach((panel) => {
    const active = panel.id === panelId;
    panel.classList.toggle('active', active);
    panel.hidden = !active;
  });
}

async function loadMembers() {
  const result = await api('/api/admin/members');
  adminMembers = result.members || [];
  const currentMembers = adminMembers.filter((member) => Number(member.is_current_clan) === 1);
  const options = currentMembers.map((member) => `<option value="${escapeHtml(member.player_tag)}">${escapeHtml(member.name)} · ${escapeHtml(member.player_tag)}</option>`).join('');
  document.querySelectorAll('.member-select').forEach((select) => {
    select.innerHTML = options || '<option value="">Keine Mitglieder vorhanden</option>';
  });
  $('member-management-select').innerHTML = adminMembers.map((member) => `<option value="${escapeHtml(member.player_tag)}">${escapeHtml(member.name)}${Number(member.is_current_clan) === 1 ? '' : ' · Ehemalig'} · ${escapeHtml(member.player_tag)}</option>`).join('') || '<option value="">Keine Mitglieder vorhanden</option>';
  fillMemberStatus();
  renderMemberStatusList();
}

function renderMemberStatusList() {
  const members = [...adminMembers].sort((a, b) => Number(b.is_current_clan) - Number(a.is_current_clan) || a.name.localeCompare(b.name, 'de'));
  $('member-status-list').innerHTML = members.map((member) => {
    const status = Number(member.is_current_clan) !== 1 ? 'Ehemalig' : (member.weekly_activity || 'inaktiv');
    const period = member.absence_start || member.absence_end
      ? `${member.absence_start ? new Date(`${member.absence_start}T00:00:00`).toLocaleDateString('de-DE') : '—'} bis ${member.absence_end ? new Date(`${member.absence_end}T00:00:00`).toLocaleDateString('de-DE') : 'offen'}`
      : '—';
    return `<div class="member-status-row"><b>${escapeHtml(member.name)}</b><span class="member-status-badge">${escapeHtml(status)}</span><span>${status === 'abgemeldet' ? period : (member.absence_start || member.absence_end ? period : 'Keine Abmeldung')}</span></div>`;
  }).join('') || '<p class="empty-state">Keine Mitglieder vorhanden.</p>';
}

function fillMemberStatus() {
  const member = adminMembers.find((item) => item.player_tag === $('member-management-select').value);
  if (!member) return;
  const form = $('member-status-form');
  form.elements.weekly_activity.value = member.weekly_activity || 'inaktiv';
  form.elements.absence_start.value = member.absence_start || '';
  form.elements.absence_end.value = member.absence_end || '';
  form.elements.admin_comment.value = member.admin_comment || '';
}

async function loadHistory(kind, containerId) {
  const result = await api(`/api/admin/history?limit=1000&kind=${kind}`);
  const entries = result.items || [];
  $(containerId).innerHTML = entries.map((entry) => {
    const points = Number(entry.points || 0);
    const deletable = entry.event_key.startsWith('manual:') || entry.event_key.startsWith('clangames:');
    const deleteButton = deletable ? `<button class="history-delete" type="button" data-entry-id="${Number(entry.id)}" aria-label="Buchung von ${escapeHtml(entry.name)} löschen">Löschen</button>` : '<span class="history-locked" title="Automatische Buchungen können nicht gelöscht werden">Automatisch</span>';
    return `<div class="history-row"><b>${escapeHtml(entry.name)}</b><span>${escapeHtml(entry.category)} · ${escapeHtml(entry.description)}</span><strong class="history-points ${points < 0 ? 'negative' : ''}">${points > 0 ? '+' : ''}${points}</strong><small>${new Date(`${entry.created_at}Z`).toLocaleString('de-DE')}</small>${deleteButton}</div>`;
  }).join('') || '<p class="empty-state">Noch keine Buchungen.</p>';
}

const loadManualHistory = () => loadHistory('manual', 'manual-history');

async function loadPointsHistory() {
  const result = await api('/api/history?limit=1000');
  $('points-history').innerHTML = (result.items || []).map((entry) => {
    const points = Number(entry.points || 0);
    return `<div class="history-row"><b>${escapeHtml(entry.name)}</b><span>${escapeHtml(entry.category)} · ${escapeHtml(entry.description)}</span><strong class="history-points ${points < 0 ? 'negative' : ''}">${points > 0 ? '+' : ''}${points}</strong><small>${new Date(`${entry.created_at}Z`).toLocaleString('de-DE')}</small></div>`;
  }).join('') || '<p class="empty-state">Noch keine Buchungen.</p>';
}

async function openAdmin() {
  $('login-card').hidden = true;
  $('admin-app').hidden = false;
  await Promise.all([loadMembers(), loadManualHistory(), loadPointsHistory()]);
}

$('login-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  authorization = basicHeader(form.get('username'), form.get('password'));
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await api('/api/admin/session');
    await openAdmin();
  } catch (error) {
    authorization = '';
    showMessage($('login-message'), error.message, true);
  } finally {
    button.disabled = false;
  }
});

document.querySelectorAll('.admin-tab').forEach((tab) => tab.addEventListener('click', () => switchPanel(tab.dataset.panel)));
$('logout').addEventListener('click', () => { authorization = ''; window.location.reload(); });
$('reload-manual-history').addEventListener('click', loadManualHistory);
$('reload-member-status').addEventListener('click', loadMembers);
$('reload-points-history').addEventListener('click', loadPointsHistory);
$('member-management-select').addEventListener('change', fillMemberStatus);
async function deleteHistoryEntry(event, messageId, reload) {
  const button = event.target.closest('[data-entry-id]');
  if (!button) return;
  if (!window.confirm('Diese Buchung wirklich löschen?')) return;
  button.disabled = true;
  try {
    await api(`/api/admin/history/${button.dataset.entryId}`, { method: 'DELETE' });
    showMessage($(messageId), 'Buchung gelöscht.');
    await reload();
  } catch (error) {
    showMessage($(messageId), error.message, true);
    button.disabled = false;
  }
}
$('manual-history').addEventListener('click', (event) => deleteHistoryEntry(event, 'manual-action-message', loadManualHistory));

$('adjustment-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const formElement = event.currentTarget;
  const form = new FormData(formElement);
  const payload = {
    player_tag: form.get('player_tag'), event_key: `admin:${Date.now()}`,
    category: form.get('category'), description: form.get('description'), points: Number(form.get('points'))
  };
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await api('/api/admin/adjustments', { method: 'POST', body: JSON.stringify(payload) });
    showMessage($('adjustment-message'), 'Punktebuchung gespeichert.');
    formElement.reset();
    await loadManualHistory();
  } catch (error) {
    showMessage($('adjustment-message'), error.message, true);
  } finally {
    button.disabled = false;
  }
});

$('member-status-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = {
    player_tag: form.get('player_tag'), weekly_activity: form.get('weekly_activity'),
    absence_start: form.get('absence_start') || null, absence_end: form.get('absence_end') || null,
    admin_comment: form.get('admin_comment')
  };
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await api('/api/admin/member-status', { method: 'PUT', body: JSON.stringify(payload) });
    showMessage($('member-status-message'), 'Mitgliedsdaten gespeichert.');
    await loadMembers();
  } catch (error) {
    showMessage($('member-status-message'), error.message, true);
  } finally {
    button.disabled = false;
  }
});

$('sync-now').addEventListener('click', async () => {
  const button = $('sync-now');
  const resultPanel = $('sync-result');
  button.disabled = true;
  resultPanel.hidden = false;
  resultPanel.textContent = 'Synchronisierung läuft …';
  try {
    const result = await api('/api/admin/sync', { method: 'POST' });
    resultPanel.textContent = JSON.stringify(result, null, 2);
    await Promise.all([loadMembers(), loadManualHistory(), loadPointsHistory()]);
  } catch (error) {
    resultPanel.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

}
