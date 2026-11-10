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
  const selectedManagementTag = $('member-management-select').value;
  const result = await api('/api/admin/members');
  adminMembers = result.members || [];
  const currentMembers = adminMembers.filter((member) => Number(member.is_current_clan) === 1);
  const options = currentMembers.map((member) => `<option value="${escapeHtml(member.player_tag)}">${escapeHtml(member.name)} · ${escapeHtml(member.player_tag)}</option>`).join('');
  document.querySelectorAll('.member-select').forEach((select) => {
    select.innerHTML = options || '<option value="">Keine Mitglieder vorhanden</option>';
  });
  $('member-management-select').innerHTML = options || '<option value="">Keine Mitglieder vorhanden</option>';
  if (currentMembers.some((member) => member.player_tag === selectedManagementTag)) {
    $('member-management-select').value = selectedManagementTag;
  }
  fillMemberStatus();
  renderMemberStatusList();
}

function parseMemberDate(str) {
  if (!str) return null;
  let clean = String(str).trim();
  if (clean.endsWith('Z') || /[+-]\d{2}:?\d{2}$/.test(clean)) {
    const d = new Date(clean);
    if (!Number.isNaN(d.getTime())) return d;
  }
  clean = clean.replace(' ', 'T');
  if (!clean.endsWith('Z') && !/[+-]\d{2}:?\d{2}$/.test(clean)) {
    clean += 'Z';
  }
  const d = new Date(clean);
  return Number.isNaN(d.getTime()) ? null : d;
}

function renderMemberStatusList() {
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const todayIso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  const members = adminMembers.filter((member) => Number(member.is_current_clan) === 1).sort((a, b) => a.name.localeCompare(b.name, 'de'));
  $('member-status-list').innerHTML = members.map((member) => {
    const currentlyAbsent = member.weekly_activity === 'abgemeldet' && (!member.absence_end || member.absence_end >= todayIso);
    let statusClass = 'active';
    let status = 'Aktiv';
    let daysInactive = 0;
    let daysText = '0 Tage (heute)';
    let daysClass = 'today';

    const lastActive = parseMemberDate(member.last_active_at || member.last_seen || member.joined_clan_at);
    if (lastActive) {
      const lastActiveMidnight = new Date(lastActive.getFullYear(), lastActive.getMonth(), lastActive.getDate());
      const diffDays = Math.floor((today.getTime() - lastActiveMidnight.getTime()) / (1000 * 60 * 60 * 24));
      daysInactive = Number.isNaN(diffDays) ? 0 : Math.max(0, diffDays);
      if (daysInactive === 0) {
        daysText = '0 Tage (heute)';
        daysClass = 'today';
      } else if (daysInactive === 1) {
        daysText = '1 Tag';
        daysClass = 'normal';
      } else if (daysInactive < 7) {
        daysText = `${daysInactive} Tage`;
        daysClass = daysInactive >= 4 ? 'warning' : 'normal';
      } else {
        daysText = `${daysInactive} Tage ⚠️`;
        daysClass = 'danger';
      }
    }

    if (currentlyAbsent) {
      statusClass = 'absent';
      status = `Abgemeldet bis ${member.absence_end ? formatIsoDate(member.absence_end) : 'unbegrenzt'}`;
    } else if (daysInactive >= 7) {
      statusClass = 'inactive';
      status = 'Inaktiv';
    }

    return `<div class="member-status-row"><span>${escapeHtml(member.name)}</span><span class="member-status-badge ${statusClass}">${escapeHtml(status)}</span><span class="inactivity-tag ${daysClass}">${escapeHtml(daysText)}</span></div>`;
  }).join('') || '<p class="empty-state">Keine aktiven Mitglieder vorhanden.</p>';
}

function fillMemberStatus() {
  const member = adminMembers.find((item) => item.player_tag === $('member-management-select').value);
  $('absence-end-input').value = member?.weekly_activity === 'abgemeldet' && member.absence_end ? formatIsoDate(member.absence_end) : '';
}

function formatIsoDate(value) {
  const [year, month, day] = value.split('-');
  return `${day}/${month}/${year}`;
}

function parseDisplayDate(value) {
  const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(value.trim());
  if (!match) return null;
  const [, day, month, year] = match;
  const parsed = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  if (parsed.getUTCFullYear() !== Number(year) || parsed.getUTCMonth() !== Number(month) - 1 || parsed.getUTCDate() !== Number(day)) return null;
  return `${year}-${month}-${day}`;
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
$('clear-absence').addEventListener('click', async () => {
  const playerTag = $('member-management-select').value;
  if (!playerTag) return;
  const button = $('clear-absence');
  button.disabled = true;
  try {
    await api('/api/admin/member-status', { method: 'PUT', body: JSON.stringify({ player_tag: playerTag, absence_end: null }) });
    showMessage($('member-status-message'), 'Abmeldung aufgehoben; Mitglied ist wieder aktiv.');
    await loadMembers();
  } catch (error) {
    showMessage($('member-status-message'), error.message, true);
  } finally {
    button.disabled = false;
  }
});
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
  const selectedTag = form.get('player_tag');
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
    formElement.elements.player_tag.value = selectedTag;
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
  const absenceEnd = parseDisplayDate(form.get('absence_end_display'));
  if (!absenceEnd) {
    showMessage($('member-status-message'), 'Bitte ein gültiges Datum im Format TT/MM/JJJJ eingeben.', true);
    return;
  }
  const payload = { player_tag: form.get('player_tag'), absence_end: absenceEnd };
  const button = event.currentTarget.querySelector('button[type="submit"]');
  button.disabled = true;
  try {
    await api('/api/admin/member-status', { method: 'PUT', body: JSON.stringify(payload) });
    showMessage($('member-status-message'), 'Abmeldung gespeichert.');
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
