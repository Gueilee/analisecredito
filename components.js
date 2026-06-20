/* ═══════════════════════════════════════════════════════════════
   VENDEMMIA — Análise de Crédito  |  Component System
   Fonte única de verdade para sidebar, navegação e badges.

   ARQUITETURA SAAS — ROADMAP:
   ├── Fase 1 (atual):  localStorage via db.js
   ├── Fase 2 (próxima): substituir DB.* por fetch('/api/...') em db.js
   │                     — o resto do sistema não muda
   └── Fase 3 (produção): FastAPI + PostgreSQL + JWT + multi-tenant
   ═══════════════════════════════════════════════════════════════ */

const App = (() => {

  /* ── Ícones SVG — definidos uma única vez ──────────────── */
  const ICO = {
    dashboard:
      `<svg viewBox="0 0 24 24" fill="none"><rect x="3" y="3" width="7" height="7" rx="1.5" stroke="currentColor" stroke-width="1.7"/><rect x="14" y="3" width="7" height="7" rx="1.5" stroke="currentColor" stroke-width="1.7"/><rect x="3" y="14" width="7" height="7" rx="1.5" stroke="currentColor" stroke-width="1.7"/><rect x="14" y="14" width="7" height="7" rx="1.5" stroke="currentColor" stroke-width="1.7"/></svg>`,
    solicitacoes:
      `<svg viewBox="0 0 24 24" fill="none"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" stroke="currentColor" stroke-width="1.7"/><polyline points="14 2 14 8 20 8" stroke="currentColor" stroke-width="1.7"/></svg>`,
    nova:
      `<svg viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" stroke-width="1.7"/><line x1="12" y1="8" x2="12" y2="16" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><line x1="8" y1="12" x2="16" y2="12" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
    emAnalise:
      `<svg viewBox="0 0 24 24" fill="none"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    aprovadas:
      `<svg viewBox="0 0 24 24" fill="none"><polyline points="20 6 9 17 4 12" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    negadas:
      `<svg viewBox="0 0 24 24" fill="none"><line x1="18" y1="6" x2="6" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><line x1="6" y1="6" x2="18" y2="18" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>`,
    clientes:
      `<svg viewBox="0 0 24 24" fill="none"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><circle cx="9" cy="7" r="4" stroke="currentColor" stroke-width="1.7"/></svg>`,
    usuarios:
      `<svg viewBox="0 0 24 24" fill="none"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><circle cx="9" cy="7" r="4" stroke="currentColor" stroke-width="1.7"/><path d="M23 21v-2a4 4 0 0 0-3-3.87" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><path d="M16 3.13a4 4 0 0 1 0 7.75" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
    relatorios:
      `<svg viewBox="0 0 24 24" fill="none"><line x1="18" y1="20" x2="18" y2="10" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><line x1="12" y1="20" x2="12" y2="4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><line x1="6" y1="20" x2="6" y2="14" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
    historico:
      `<svg viewBox="0 0 24 24" fill="none"><path d="M3 3v5h5" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><polyline points="12 7 12 12 16 14" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
    comite:
      `<svg viewBox="0 0 24 24" fill="none"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>`,
    logout:
      `<svg viewBox="0 0 24 24" fill="none" width="15" height="15"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/><polyline points="16 17 21 12 16 7" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/><line x1="21" y1="12" x2="9" y2="12" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>`,
  };

  /* ── Contagens em tempo real do banco ─────────────────── */
  function counts() {
    const all = DB.solicitacoes.getAll();
    return {
      total:     all.length,
      pendente:  all.filter(s => s.status === 'pendente').length,
      emAnalise: all.filter(s => s.status === 'em_analise').length,
      aprovado:  all.filter(s => s.status === 'aprovado').length,
      negado:    all.filter(s => s.status === 'negado').length,
      emComite:  all.filter(s => s.status === 'em_comite').length,
    };
  }

  /* ── Helpers de renderização ───────────────────────────── */
  function badge(n, cls = '') {
    if (!n) return '';
    return `<span class="nav-badge${cls ? ' ' + cls : ''}">${n}</span>`;
  }

  function navItem(icon, label, href, active, badgeHtml = '', disabled = false) {
    const cls = 'nav-item' + (active ? ' active' : '') + (disabled ? ' disabled' : '');
    return `<a href="${href}" class="${cls}">${icon}${label}${badgeHtml}</a>`;
  }

  /* ── RBAC helpers ─────────────────────────────────────── */
  const _DECISION_ROLES = ['Financeiro', 'Administrador', 'Admin', 'Diretor'];
  const _ADMIN_ROLES    = ['Administrador', 'Admin'];
  function _canDecide(session) {
    return session && _DECISION_ROLES.some(r => (session.role || '').includes(r));
  }
  function _isAdmin(session) {
    return session && _ADMIN_ROLES.some(r => (session.role || '').includes(r));
  }

  /* ── HTML do sidebar completo ─────────────────────────── */
  function buildSidebar(page, session, c) {
    const showDecisionItems = _canDecide(session);
    const showAdminItems    = _isAdmin(session);
    return `
      <div class="sidebar-logo">
        <a href="index.html" title="Ir para o Dashboard" style="display:block;line-height:0;">
          <img src="logo.png" alt="Vendemmia Análise de Crédito" class="sidebar-logo-img" />
        </a>
      </div>

      <nav class="sidebar-nav">
        <span class="nav-section-label">Principal</span>
        ${navItem(ICO.dashboard,    'Dashboard',    'index.html',            page === 'dashboard')}
        ${navItem(ICO.solicitacoes, 'Solicitações', 'solicitacoes.html',     page === 'solicitacoes', badge(c.total, 'yellow'))}
        ${navItem(ICO.nova,         'Nova Análise', 'nova-solicitacao.html', page === 'nova')}

        <span class="nav-section-label">Análise</span>
        ${navItem(ICO.emAnalise, 'Em Análise', 'solicitacoes.html?status=em_analise', page === 'em_analise', badge(c.emAnalise))}
        ${showDecisionItems ? navItem(ICO.comite, 'Comitê de Crédito', 'comite-credito.html', page === 'comite', badge(c.emComite, ' yellow')) : ''}
        ${showDecisionItems ? navItem(ICO.aprovadas, 'Aprovadas', 'solicitacoes.html?status=aprovado', page === 'aprovado', badge(c.aprovado, ' green')) : ''}
        ${showDecisionItems ? navItem(ICO.negadas,   'Negadas',   'solicitacoes.html?status=negado',   page === 'negado',   badge(c.negado,   ' red'))   : ''}

        <span class="nav-section-label">Gestão</span>
        ${navItem(ICO.clientes,  'Consulta',  'clientes.html',  page === 'clientes')}
        ${showAdminItems ? navItem(ICO.usuarios, 'Usuários', 'usuarios.html', page === 'usuarios') : ''}
      </nav>

      <div class="sidebar-footer">
        <div class="user-card">
          <div class="user-avatar">${session.avatar || '??'}</div>
          <div class="user-info">
            <div class="user-name">${session.name || '—'}</div>
            <div class="user-role">${session.role || '—'}</div>
          </div>
          <button
            onclick="DB.auth.logout().then(() => { window.location.href='login.html'; })"
            style="background:none;border:none;cursor:pointer;color:var(--text-faint);padding:0;display:flex;align-items:center;gap:.35rem;transition:color .15s;"
            onmouseover="this.style.color='rgba(255,255,255,.55)'" onmouseout="this.style.color='var(--text-faint)'"
            title="Sair">
            ${ICO.logout}
            <span style="font-size:.72rem;font-weight:600;letter-spacing:.2px;">Sair</span>
          </button>
        </div>
      </div>`;
  }

  /* ══════════════════════════════════════════════════════════
     API PÚBLICA
     ══════════════════════════════════════════════════════════ */

  /**
   * Monta o sidebar no elemento <aside class="sidebar"> da página.
   * @param {string} page  — chave da página ativa:
   *   'dashboard' | 'solicitacoes' | 'nova' | 'em_analise' | 'aprovado' | 'negado'
   */
  let _activePage = 'solicitacoes';

  function _renderSidebar() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;
    sidebar.innerHTML = buildSidebar(_activePage, DB.auth.getSession() || {}, counts());
  }

  function mount(page) {
    _activePage = page;
    _renderSidebar();
    // Após sync com a API, re-renderiza com contagens corretas (corrige race condition)
    if (DB && DB.ready) DB.ready.then(_renderSidebar);
  }

  function refreshNav() {
    _renderSidebar();
  }

  /**
   * Preenche elementos de saudação com base no horário.
   * @param {string} id — id do elemento (ex: 'topbar-greeting')
   */
  function greeting(id) {
    const el = document.getElementById(id);
    if (!el) return;
    const h = new Date().getHours();
    const period = h < 12 ? 'Bom dia' : h < 18 ? 'Boa tarde' : 'Boa noite';
    const sess = DB.auth.getSession ? DB.auth.getSession() : (typeof session !== 'undefined' ? session : null);
    const nome = sess?.name ? ', ' + sess.name.split(' ')[0] : '';
    el.textContent = period + nome + ' 👋';
  }

  /**
   * Popula elementos de usuário na topbar com dados da sessão.
   * @param {{ avatar?, name?, role?, topbarName? }} ids — mapa de IDs de elementos
   */
  function initUser(ids = {}) {
    const s   = DB.auth.getSession() || {};
    const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val || '—'; };
    set(ids.avatar   || 'topbar-avatar', s.avatar);
    set(ids.name     || 'topbar-name',   s.name);
    if (ids.role)     set(ids.role,      s.role);
  }

  /**
   * Dispara notificação por e-mail via backend (fire-and-forget).
   * @param {'nova_solicitacao'|'analista_decisao'|'comite_decisao'} event
   * @param {object} data — campos do evento (empresa, cnpj, status, etc.)
   */
  function notifyEmail(event, data) {
    const base = window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : window.location.origin;
    fetch(`${base}/api/notify/email`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ event, ...data }),
    }).catch(() => {});
  }

  return { mount, refreshNav, greeting, initUser, notifyEmail };

})();
