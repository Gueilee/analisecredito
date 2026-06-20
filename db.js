/* ═══════════════════════════════════════════════════════
   VENDEMMIA — Análise de Crédito  |  Data Layer
   Bridge cache: leitura síncrona via localStorage,
   escrita dispara API em background (fire-and-forget).
   ═══════════════════════════════════════════════════════ */

const DB = (() => {

  /* ── HELPERS ────────────────────────────────────────── */
  const uid     = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  const now     = () => new Date().toISOString();
  const fmt     = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  };
  const fmtDate  = (iso) => (!iso ? '—' : new Date(iso).toLocaleDateString('pt-BR'));
  const fmtMoney = (val) => {
    if (!val) return '—';
    const n = parseFloat(String(val).replace(/\./g, '').replace(',', '.'));
    return isNaN(n) ? val : 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2 });
  };

  const read  = (key) => { try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; } };
  const write = (key, val) => { try { localStorage.setItem(key, JSON.stringify(val)); } catch {} };

  const KEYS = {
    SESSION:     'vd_session',
    SOL_CACHE:   'vd_sol_cache',
    DELETED_IDS: 'vd_deleted_ids',
    SOL_LEGACY:  'vd_solicitacoes',
  };

  const _apiBase = () => window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : window.location.origin;
  const _fetch   = (path, opts = {}) => fetch(_apiBase() + path, { credentials: 'include', ...opts });

  const _trackDeleted = (id) => {
    const arr = read(KEYS.DELETED_IDS) || [];
    if (!arr.includes(id)) { arr.push(id); write(KEYS.DELETED_IDS, arr); }
  };

  /* ── AUTH ───────────────────────────────────────────── */
  const auth = {
    async login(email, password) {
      try {
        const resp = await _fetch('/api/auth/login', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email, password }),
        });
        const data = await resp.json();
        if (!resp.ok) return { ok: false, error: data.detail || 'E-mail ou senha incorretos.' };
        const session = {
          userId:  data.user.id,
          name:    data.user.name,
          email:   data.user.email,
          role:    data.user.role,
          avatar:  data.user.avatar,
          loginAt: now(),
        };
        write(KEYS.SESSION, session);
        return { ok: true, user: session };
      } catch (err) {
        return { ok: false, error: 'Erro de conexão: ' + (err?.message || String(err)) };
      }
    },
    async logout() {
      try { await _fetch('/api/auth/logout', { method: 'POST' }); } catch (_) {}
      localStorage.removeItem(KEYS.SESSION);
    },
    getSession()  { return read(KEYS.SESSION); },
    requireAuth() {
      if (!read(KEYS.SESSION)) { window.location.href = 'login.html'; return null; }
      return read(KEYS.SESSION);
    },
  };

  /* ── SOLICITAÇÕES (localStorage bridge cache + API) ─── */
  const solicitacoes = {
    // Pré-populado do cache local ao carregar (síncrono)
    _cache: (() => {
      try { return JSON.parse(localStorage.getItem(KEYS.SOL_CACHE) || 'null') || null; }
      catch { return null; }
    })(),

    _saveCache() {
      try { localStorage.setItem(KEYS.SOL_CACHE, JSON.stringify(this._cache)); } catch {}
    },

    async sync() {
      try {
        const r = await _fetch('/api/solicitacoes');
        if (r.ok) {
          const d = await r.json();
          this._cache = d.items || [];
          this._saveCache();
          localStorage.removeItem(KEYS.SOL_LEGACY); // remove localStorage legado após sync
          // Atualiza badges do sidebar com contagens corretas pós-sync
          if (typeof App !== 'undefined' && App.refreshNav) App.refreshNav();
        } else if (r.status === 401) {
          this._cache = [];
        }
      } catch {
        // Fallback: usa dados legados do localStorage se API falhar
        if (!this._cache) {
          const legacy = read(KEYS.SOL_LEGACY);
          this._cache = legacy || [];
        }
      }
    },

    getAll()    { return (this._cache || []).sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt)); },
    getById(id) { return (this._cache || []).find(s => s.id === id) || null; },

    create(data) {
      const session = read(KEYS.SESSION);
      const record = {
        ...data,
        id:              data.id || uid(),
        status:          data.status || 'pendente',
        solicitante:     session?.userId || 'u1',
        solicitanteNome: session?.name   || 'Usuário',
        createdAt:       now(),
        updatedAt:       now(),
      };
      if (!this._cache) this._cache = [];
      this._cache.unshift(record);
      this._saveCache();
      _fetch('/api/solicitacoes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(record),
      }).catch(() => {});
      return record;
    },

    update(id, data) {
      if (!this._cache) this._cache = [];
      const idx = this._cache.findIndex(s => s.id === id);
      let updated;
      if (idx !== -1) {
        updated = { ...this._cache[idx], ...data, id, updatedAt: now() };
        this._cache[idx] = updated;
      } else {
        updated = { ...data, id, updatedAt: now() };
        this._cache.push(updated);
      }
      this._saveCache();
      _fetch(`/api/solicitacoes/${id}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updated),
      }).catch(() => {});
      return updated;
    },

    delete(id) {
      if (!this._cache) return false;
      const prev = this._cache.length;
      this._cache = this._cache.filter(s => s.id !== id);
      this._saveCache();
      _trackDeleted(id);
      _fetch(`/api/solicitacoes/${id}`, { method: 'DELETE' }).catch(() => {});
      return this._cache.length < prev;
    },

    getStats() {
      const all    = solicitacoes.getAll();
      const counts = { total: all.length, aprovado: 0, negado: 0, em_analise: 0, pendente: 0, em_comite: 0 };
      let volumeTotal = 0;
      all.forEach(s => {
        if (counts[s.status] !== undefined) counts[s.status]++;
        if (s.status === 'aprovado' && s.limiteAprovado) {
          const n = parseFloat(s.limiteAprovado.replace(/\./g, '').replace(',', '.')) || 0;
          volumeTotal += n;
        }
      });
      counts.volumeTotal = volumeTotal;
      counts.taxaAprovacao = counts.total ? Math.round(counts.aprovado / counts.total * 100) : 0;
      return counts;
    },
  };

  /* ── LABEL HELPERS ──────────────────────────────────── */
  const statusLabel    = { aprovado: 'Aprovado', negado: 'Negado', em_analise: 'Em Análise', pendente: 'Pendente', novo: 'Novo', em_comite: 'Em Comitê' };
  const statusBadge    = { aprovado: 'aprovado', negado: 'negado', em_analise: 'em-analise', pendente: 'pendente', novo: 'novo', em_comite: 'em-comite' };
  const modalLabel     = { aereo: 'Aéreo', maritimo: 'Marítimo', rodoviario: 'Rodoviário', multimodal: 'Multimodal' };
  const integradoLabel = { logistica: 'Logística', trade: 'Trade', armazem: 'Armazém', multiplos: 'Múltiplos' };
  const tipoOpLabel    = { encomenda: 'Encomenda', 'conta-ordem': 'Conta e Ordem', gestao: 'Gestão' };

  function calcValidadeStatus(solObj) {
    const dias = parseInt(solObj.validadeDias, 10);
    const at   = solObj.decisao_at;
    if (!dias || !at) return null;
    const expiry = new Date(at);
    expiry.setDate(expiry.getDate() + dias);
    const today = new Date(); today.setHours(0,0,0,0); expiry.setHours(0,0,0,0);
    const diff = Math.round((expiry - today) / 86400000);
    if (diff < 0)   return { label: 'VENCIDO',                                    color: '#ef4444', bg: 'rgba(239,68,68,.1)',   border: 'rgba(239,68,68,.3)',   days: diff, expiry };
    if (diff <= 30) return { label: `VENCENDO EM ${diff} DIA${diff!==1?'S':''}`,  color: '#f59e0b', bg: 'rgba(245,158,11,.1)', border: 'rgba(245,158,11,.3)', days: diff, expiry };
    return              { label: 'ATIVO',                                          color: '#22c55e', bg: 'rgba(34,197,94,.1)',  border: 'rgba(34,197,94,.3)',  days: diff, expiry };
  }
  function validadeBadgeHtml(solObj) {
    const vs = calcValidadeStatus(solObj);
    if (!vs) return '';
    const expiryStr = vs.expiry.toLocaleDateString('pt-BR');
    return `<div style="display:inline-flex;align-items:center;gap:.45rem;background:${vs.bg};border:1px solid ${vs.border};border-radius:6px;padding:.38rem .75rem;margin-top:.5rem;">` +
      `<svg viewBox="0 0 24 24" fill="none" width="11" height="11"><circle cx="12" cy="12" r="10" stroke="${vs.color}" stroke-width="2"/><polyline points="12 6 12 12 16 14" stroke="${vs.color}" stroke-width="1.8" stroke-linecap="round"/></svg>` +
      `<span style="font-size:.7rem;font-weight:800;color:${vs.color};letter-spacing:.4px;text-transform:uppercase;">${vs.label}</span>` +
      `<span style="font-size:.67rem;color:${vs.color};opacity:.75;">· válido até ${expiryStr}</span></div>`;
  }

  const deletedIds = {
    getAll() { return new Set(read(KEYS.DELETED_IDS) || []); },
    add(id)  { _trackDeleted(id); },
  };

  // Inicia sync com a API (Promise pública — páginas de lista esperam por ela)
  const ready = solicitacoes.sync();

  return {
    auth,
    solicitacoes,
    deletedIds,
    ready,
    utils: { uid, now, fmt, fmtDate, fmtMoney, statusLabel, statusBadge, modalLabel, integradoLabel, tipoOpLabel, calcValidadeStatus, validadeBadgeHtml },
  };
})();
