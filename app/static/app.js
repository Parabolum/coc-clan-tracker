const $ = (id) => document.getElementById(id);
const viewInfo = {
  overview: { title: 'Clan-Übersicht', subtitle: 'Punktestände und letzte Buchungen.', breadcrumb: 'Übersicht' },
  members: { title: 'Mitglieder', subtitle: 'Punkte nach Kategorie und Gesamtstand.', breadcrumb: 'Mitglieder' },
  rules: { title: 'Punktevergaberegeln', subtitle: 'So setzen sich die Punkte zusammen.', breadcrumb: 'Regeln' },
  history: { title: 'Punkteverlauf', subtitle: 'Buchungen nach Datum und Kategorie.', breadcrumb: 'Punkteverlauf' }
};

let allMembers = [];
let allHistory = [];
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (character) => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
})[character]);

function initials(name = '') {
  return name.trim().split(/\s+/).slice(0, 2).map((part) => part.charAt(0)).join('').toUpperCase() || '–';
}

function displayRole(role = '') {
  const roles = {
    leader: 'Anführer',
    coleader: 'Co-Anführer',
    admin: 'Ältester',
    elder: 'Ältester',
    member: 'Mitglied'
  };
  return roles[String(role).toLowerCase().replace(/[\s_-]/g, '')] || role || 'Mitglied';
}

function iconFor(category = '') {
  const value = category.toLowerCase();
  if (value.includes('krieg') || value.includes('cwl')) return { icon: '⚔', style: 'war' };
  if (value.includes('spiel')) return { icon: '✦', style: 'games' };
  if (value.includes('spend')) return { icon: '↗', style: '' };
  if (value.includes('überfall') || value.includes('raid')) return { icon: '⌖', style: 'raid' };
  return { icon: '✧', style: '' };
}

function displayCategory(category = '') {
  if (category === 'Krieg') return 'CK';
  if (category === 'Überfall-Wochenende') return 'Überfall-WE';
  if (category === 'Spenden') return 'Spende';
  if (category === 'Sonstiges') return 'Bonus';
  return category;
}

function memberRow(member, index) {
  return `<div class="member-row">
    <span class="rank ${index < 3 ? 'top' : ''}">${String(index + 1).padStart(2, '0')}</span>
    <span class="member-person"><span class="avatar">${escapeHtml(initials(member.name))}</span><span><b>${escapeHtml(member.name)}</b><small>${escapeHtml(displayRole(member.role))}</small></span></span>
    <span class="th">TH ${escapeHtml(member.town_hall_level ?? '—')}</span>
    <strong class="points">${Number(member.points || 0).toLocaleString('de-DE')}</strong>
  </div>`;
}

function directoryMemberRow(member, former = false) {
  const points = Number(member.points || 0);
  const atRisk = points <= 0;
  const categories = member.categories || {};
  const columns = ['CK', 'CWL', 'Überfall-WE', 'Spende', 'Clan-Spiele', 'Bonus'];
  const scoreCells = columns.map((category) => {
    const value = Number(categories[category] || 0);
    return `<td class="category-score ${value > 0 ? 'positive' : value < 0 ? 'negative' : ''}">${value > 0 ? '+' : ''}${value}</td>`;
  }).join('');
  return `<tr class="${former ? 'former-member-row' : ''}">
    <td class="member-name-cell"><span class="member-name">${escapeHtml(member.name)}</span><small>${former ? 'Ehemalig' : escapeHtml(displayRole(member.role))}</small></td>
    <td class="total-score">${points.toLocaleString('de-DE')}</td>
    ${scoreCells}
    <td><span class="kick-status ${atRisk ? 'at-risk' : 'safe'}" title="Keine Kickgefahr ab 1 Punkt">${atRisk ? '⚠ Kickgefahr' : '✓ Keine Gefahr'}</span></td>
  </tr>`;
}

function renderMembers() {
  const isCurrent = (member) => member.is_current_clan === undefined || Number(member.is_current_clan) === 1;
  const current = allMembers.filter(isCurrent).sort((a, b) => Number(b.points || 0) - Number(a.points || 0));
  const former = allMembers.filter((member) => !isCurrent(member)).sort((a, b) => Number(b.points || 0) - Number(a.points || 0));
  $('member-label').textContent = `${current.length} ${current.length === 1 ? 'Mitglied' : 'Mitglieder'}`;
  $('former-member-label').textContent = `${former.length} ${former.length === 1 ? 'Mitglied' : 'Mitglieder'}`;
  $('members-preview').innerHTML = current.slice(0, 5).map(memberRow).join('') || '<div class="empty">Noch keine Mitglieder vorhanden.</div>';
  const query = $('member-search').value.trim().toLocaleLowerCase('de-DE');
  const filtered = current.filter((member) => `${member.name} ${member.role || ''}`.toLocaleLowerCase('de-DE').includes(query));
  const filteredFormer = former.filter((member) => `${member.name}`.toLocaleLowerCase('de-DE').includes(query));
  $('member-directory').innerHTML = filtered.map((member) => directoryMemberRow(member)).join('') || '<tr><td class="table-empty" colspan="9">Keine passenden Mitglieder gefunden.</td></tr>';
  $('former-member-directory').innerHTML = filteredFormer.map((member) => directoryMemberRow(member, true)).join('') || '<tr><td class="table-empty" colspan="9">Keine ehemaligen Mitglieder.</td></tr>';
}

function formatDate(value) {
  const date = new Date(`${value}Z`);
  return Number.isNaN(date.getTime()) ? '' : date.toLocaleDateString('de-DE', { day: '2-digit', month: 'short', year: 'numeric' });
}

function historyRow(entry) {
  const icon = iconFor(entry.category);
  const points = Number(entry.points || 0);
  return `<div class="history-row">
    <span class="activity-icon ${icon.style}">${icon.icon}</span>
    <span class="history-copy"><b>${escapeHtml(entry.name)} <span>·</span> ${escapeHtml(entry.description)}</b><small>${escapeHtml(displayCategory(entry.category))} <span>·</span> ${formatDate(entry.created_at)}</small></span>
    <strong class="gain ${points < 0 ? 'loss' : ''}">${points > 0 ? '+' : ''}${points}</strong>
  </div>`;
}

function renderHistory() {
  const selected = $('category-filter').value;
  const entries = allHistory.filter((entry) => !selected || displayCategory(entry.category) === selected);
  $('history-count').textContent = `${entries.length} ${entries.length === 1 ? 'Buchung' : 'Buchungen'}`;
  const html = entries.map(historyRow).join('');
  $('history-list').innerHTML = html || '<div class="empty">Für diese Auswahl gibt es noch keine Buchungen.</div>';
  $('activity-preview').innerHTML = allHistory.slice(0, 5).map((entry) => {
    const icon = iconFor(entry.category);
    const points = Number(entry.points || 0);
    return `<div class="activity-item"><span class="activity-icon ${icon.style}">${icon.icon}</span><span class="activity-copy"><b>${escapeHtml(entry.name)} · ${escapeHtml(entry.description)}</b><small>${escapeHtml(displayCategory(entry.category))} · ${formatDate(entry.created_at)}</small></span><strong class="gain ${points < 0 ? 'loss' : ''}">${points > 0 ? '+' : ''}${points}</strong></div>`;
  }).join('') || '<div class="empty">Noch keine Punktebuchungen vorhanden.</div>';
}

function showView(name, updateHash = true) {
  const selected = viewInfo[name] ? name : 'overview';
  document.querySelectorAll('[data-page]').forEach((view) => view.classList.toggle('active', view.dataset.page === selected));
  document.querySelectorAll('.nav-link').forEach((link) => {
    const active = link.dataset.view === selected;
    link.classList.toggle('active', active);
    if (active) link.setAttribute('aria-current', 'page');
    else link.removeAttribute('aria-current');
  });
  $('page-title').textContent = viewInfo[selected].title;
  $('page-subtitle').textContent = viewInfo[selected].subtitle;
  $('breadcrumb-title').textContent = viewInfo[selected].breadcrumb;
  if (updateHash && location.hash !== `#${selected}`) history.replaceState(null, '', `#${selected}`);
}

async function loadDashboard() {
  loadSupportContact();
  const button = $('refresh');
  button.disabled = true;
  try {
    const [dashboardResponse, healthResponse, historyResponse, tableResponse] = await Promise.all([
      fetch('/api/dashboard'), fetch('/api/health'), fetch('/api/history?limit=500'), fetch('/api/member-table')
    ]);
    if (!dashboardResponse.ok || !healthResponse.ok) throw new Error('Dashboard konnte nicht geladen werden.');
    const dashboard = await dashboardResponse.json();
    const health = await healthResponse.json();
    const table = tableResponse.ok ? await tableResponse.json() : null;
    allMembers = table?.members || dashboard.members || [];
    allHistory = historyResponse.ok ? ((await historyResponse.json()).items || []) : (dashboard.recent || []);
    $('status').textContent = health.api_configured ? 'Automatische Synchronisierung' : 'API nicht konfiguriert';
    $('status').closest('.clan-status').querySelector('.status-dot').classList.toggle('connected', Boolean(health.api_configured));
    const currentMembers = allMembers.filter((member) => member.is_current_clan === undefined || Number(member.is_current_clan) === 1);
    $('total').textContent = currentMembers.reduce((sum, member) => sum + Number(member.points || 0), 0).toLocaleString('de-DE');
    $('count').textContent = currentMembers.length.toLocaleString('de-DE');
    $('leader').textContent = currentMembers[0]?.name || '—';
    $('leader-points').textContent = `${Number(currentMembers[0]?.points || 0).toLocaleString('de-DE')} Punkte`;
    renderMembers();
    renderHistory();
  } catch (error) {
    allMembers = [];
    allHistory = [];
    $('status').textContent = 'Server nicht erreichbar';
    $('status').closest('.clan-status').querySelector('.status-dot').classList.remove('connected');
    $('total').textContent = allMembers.reduce((sum, member) => sum + member.points, 0).toLocaleString('de-DE');
    $('count').textContent = allMembers.length.toLocaleString('de-DE');
    $('leader').textContent = '—';
    $('leader-points').textContent = '— Punkte';
    renderMembers();
    renderHistory();
  } finally {
    button.disabled = false;
  }
}

async function loadSupportContact() {
  const contact = $('support-contact');
  try {
    const response = await fetch('/api/config');
    if (!response.ok) throw new Error('Konfiguration nicht verfügbar');
    const config = await response.json();
    const name = String(config.support_discord || '').trim();
    const text = name ? `Bei Problemen mit der Website per Discord an ${name} wenden.` : '';
    contact.textContent = text;
    contact.hidden = !name;
    $('support-contact-footer').textContent = text;
    $('support-contact-footer').hidden = !name;
  } catch {
    contact.textContent = '';
    contact.hidden = true;
    $('support-contact-footer').textContent = '';
    $('support-contact-footer').hidden = true;
  }
}

document.querySelectorAll('[data-view]').forEach((link) => link.addEventListener('click', (event) => {
  event.preventDefault();
  showView(link.dataset.view);
}));
$('member-search').addEventListener('input', renderMembers);
$('category-filter').addEventListener('change', renderHistory);
$('refresh').addEventListener('click', loadDashboard);
window.addEventListener('hashchange', () => showView(location.hash.slice(1), false));
$('today').textContent = new Date().toLocaleDateString('de-DE', { weekday: 'short', day: 'numeric', month: 'long' });
showView(location.hash.slice(1) || 'overview', false);
loadDashboard();
