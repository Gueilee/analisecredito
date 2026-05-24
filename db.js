/* ═══════════════════════════════════════════════════════
   VENDEMMIA — Análise de Crédito  |  Data Layer (localStorage)
   ═══════════════════════════════════════════════════════ */

const DB = (() => {

  const KEYS = {
    SOLICITACOES: 'vd_solicitacoes',
    SESSION:      'vd_session',
    USERS:        'vd_users',
    DB_VERSION:   'vd_db_version',
    DELETED_IDS:  'vd_deleted_ids',
  };

  const DB_VERSION = 4;

  /* ── HELPERS ────────────────────────────────────────── */
  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

  const now = () => new Date().toISOString();

  const _trackDeleted = (id) => {
    const arr = read(KEYS.DELETED_IDS) || [];
    if (!arr.includes(id)) { arr.push(id); write(KEYS.DELETED_IDS, arr); }
  };

  const fmt = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  };

  const fmtDate = (iso) => {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('pt-BR');
  };

  const read = (key) => {
    try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch { return null; }
  };

  const write = (key, val) => localStorage.setItem(key, JSON.stringify(val));

  /* Usuários gerenciados pelo backend (api/users.json + bcrypt).
     Limpa quaisquer usuários com senha em texto plano que possam ter ficado. */
  const clearLegacyUsers = () => {
    const users = read(KEYS.USERS);
    if (users) localStorage.removeItem(KEYS.USERS);
  };

  /* CNPJs removidos em migrações anteriores */
  const FAKE_CNPJS = [
    '12.345.678/0001-99',
    '23.456.789/0001-11',
    '34.567.890/0001-22',
    '45.678.901/0001-33',
    '56.789.012/0001-44',
    '67.890.123/0001-55',
    '78.901.234/0001-66',
  ];

  /* CNPJs dos dados de exemplo removidos na migração v4 */
  const SEED_CNPJS_V4 = [
    '36.519.537/0002-90',  // A.R.Z Indústria de Luminárias
    '08.601.690/0001-??',  // Acrilsul
  ];

  const seedSolicitacoes = () => {
    if (read(KEYS.SOLICITACOES)) return;
    write(KEYS.SOLICITACOES, []);
  };

  /* ── SEED CLIENTES REAIS (dados.xlsx) ───────────────── */
  const seedClientesReais = () => {
    const currentVersion = read(KEYS.DB_VERSION) || 0;
    if (currentVersion >= DB_VERSION) return;

    let list = read(KEYS.SOLICITACOES) || [];

    // Backup defensivo antes de qualquer migração
    if (list.length > 0) {
      try { localStorage.setItem('vd_solicitacoes_backup_v' + currentVersion, JSON.stringify(list)); } catch (_) {}
    }

    // v3: remover clientes fictícios de demo
    list = list.filter(s => !FAKE_CNPJS.includes(s.cnpj));

    // v4: remover dados de exemplo que foram inseridos pelo seed anterior
    list = list.filter(s => !SEED_CNPJS_V4.includes(s.cnpj));

    // v4: migrar campos do formato antigo para o novo
    list = list.map(s => {
      const upd = { ...s };

      // Prazo Invoice
      if (upd.prazoInvoice !== undefined && upd.prazoInvoiceData === undefined) {
        delete upd.prazoInvoice;
        upd.prazoInvoiceData    = '';
        upd.prazoPrepEmbarque   = upd.prazoPrepEmbarque   ?? 10;
        upd.prazoEmbarque       = parseInt(upd.prazoEmbarque) || 10;
        upd.prazoTransit        = parseInt(upd.prazoTransit)  || 30;
        upd.prazoDesembaraco    = upd.prazoDesembaraco    ?? 2;
        upd.prazoFaturamento    = upd.prazoFaturamento    ?? 3;
        upd.prazoPagtoVendemmia = upd.prazoPagtoVendemmia ?? 60;
      }

      // qtdEmbarquesMes1/2/3/4 → qtdEmbarques
      if (upd.qtdEmbarquesMes1 !== undefined && upd.qtdEmbarques === undefined) {
        upd.qtdEmbarques = [upd.qtdEmbarquesMes1, upd.qtdEmbarquesMes2, upd.qtdEmbarquesMes3, upd.qtdEmbarquesMes4]
          .filter(Boolean).join(', ') || '';
        delete upd.qtdEmbarquesMes1;
        delete upd.qtdEmbarquesMes2;
        delete upd.qtdEmbarquesMes3;
        delete upd.qtdEmbarquesMes4;
      }

      // exportadores (array) → exportador (string)
      if (Array.isArray(upd.exportadores) && upd.exportador === undefined) {
        upd.exportador = upd.exportadores.filter(Boolean).join(', ') || '';
        delete upd.exportadores;
      }

      // pagtoExportadores (array) → pagtoExportadorParcelas
      if (Array.isArray(upd.pagtoExportadores) && upd.pagtoExportadorParcelas === undefined) {
        upd.pagtoExportadorParcelas = {};
        delete upd.pagtoExportadores;
      }

      // prazosExportador — removido no novo formato
      if (upd.prazosExportador !== undefined) delete upd.prazosExportador;

      // tipoAnalise
      if (!upd.tipoAnalise) upd.tipoAnalise = 'trade';

      // clienteIntegradoMultiplos
      if (upd.clienteIntegradoMultiplos === undefined) upd.clienteIntegradoMultiplos = [];

      return upd;
    });

    write(KEYS.SOLICITACOES, list);
    write(KEYS.DB_VERSION, DB_VERSION);
  };

  /* ── AUTH ───────────────────────────────────────────── */
  const _apiBase = () => window.location.protocol === 'file:' ? 'http://127.0.0.1:8000' : window.location.origin;

  const auth = {
    async login(email, password) {
      try {
        const resp = await fetch(`${_apiBase()}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
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
      } catch (_) {
        return { ok: false, error: 'Erro de conexão. Verifique se o servidor está ativo.' };
      }
    },
    async logout() {
      try {
        await fetch(`${_apiBase()}/api/auth/logout`, { method: 'POST', credentials: 'include' });
      } catch (_) {}
      localStorage.removeItem(KEYS.SESSION);
    },
    getSession() { return read(KEYS.SESSION); },
    requireAuth() {
      if (!read(KEYS.SESSION)) { window.location.href = 'login.html'; return null; }
      return read(KEYS.SESSION);
    },
  };

  /* ── SOLICITAÇÕES CRUD ──────────────────────────────── */
  const solicitacoes = {
    getAll() {
      return (read(KEYS.SOLICITACOES) || []).sort((a, b) => new Date(b.createdAt) - new Date(a.createdAt));
    },
    getById(id) {
      return (read(KEYS.SOLICITACOES) || []).find(s => s.id === id) || null;
    },
    create(data) {
      const list = read(KEYS.SOLICITACOES) || [];
      const session = read(KEYS.SESSION);
      const record = {
        ...data,
        id:              uid(),
        status:          data.status || 'pendente',
        solicitante:     session?.userId || 'u1',
        solicitanteNome: session?.name   || 'Usuário',
        createdAt:       now(),
        updatedAt:       now(),
      };
      list.unshift(record);
      write(KEYS.SOLICITACOES, list);
      return record;
    },
    update(id, data) {
      const list = read(KEYS.SOLICITACOES) || [];
      const idx  = list.findIndex(s => s.id === id);
      if (idx === -1) return null;
      list[idx] = { ...list[idx], ...data, id, updatedAt: now() };
      write(KEYS.SOLICITACOES, list);
      return list[idx];
    },
    delete(id) {
      const list = read(KEYS.SOLICITACOES) || [];
      const next = list.filter(s => s.id !== id);
      write(KEYS.SOLICITACOES, next);
      _trackDeleted(id);
      return next.length < list.length;
    },
    getStats() {
      const all    = solicitacoes.getAll();
      const counts = { total: all.length, aprovado: 0, negado: 0, em_analise: 0, pendente: 0, em_comite: 0 };
      let volumeTotal = 0;
      all.forEach(s => {
        if (counts[s.status] !== undefined) counts[s.status]++;
        if (s.status === 'aprovado' && s.limiteAprovado) {
          const n = parseFloat(s.limiteAprovado.replace(/\./g,'').replace(',','.')) || 0;
          volumeTotal += n;
        }
      });
      counts.volumeTotal = volumeTotal;
      counts.taxaAprovacao = counts.total ? Math.round(counts.aprovado / counts.total * 100) : 0;
      return counts;
    },
  };

  /* ── LABEL HELPERS ──────────────────────────────────── */
  const statusLabel = { aprovado: 'Aprovado', negado: 'Negado', em_analise: 'Em Análise', pendente: 'Pendente', novo: 'Novo', em_comite: 'Em Comitê' };
  const statusBadge = { aprovado: 'aprovado', negado: 'negado', em_analise: 'em-analise', pendente: 'pendente', novo: 'novo', em_comite: 'em-comite' };

  const modalLabel = { aereo: 'Aéreo', maritimo: 'Marítimo', rodoviario: 'Rodoviário', multimodal: 'Multimodal' };
  const integradoLabel = { logistica: 'Logística', trade: 'Trade', armazem: 'Armazém', multiplos: 'Múltiplos' };
  const tipoOpLabel = { encomenda: 'Encomenda', 'conta-ordem': 'Conta e Ordem', gestao: 'Gestão' };

  const fmtMoney = (val) => {
    if (!val) return '—';
    const n = parseFloat(String(val).replace(/\./g,'').replace(',','.'));
    if (isNaN(n)) return val;
    return 'R$ ' + n.toLocaleString('pt-BR', { minimumFractionDigits: 2 });
  };

  /* ── INIT ───────────────────────────────────────────── */
  const init = () => { clearLegacyUsers(); seedSolicitacoes(); seedClientesReais(); };

  init();

  const deletedIds = {
    getAll() { return new Set(read(KEYS.DELETED_IDS) || []); },
    add(id)  { _trackDeleted(id); },
  };

  return {
    auth,
    solicitacoes,
    deletedIds,
    utils: { uid, now, fmt, fmtDate, fmtMoney, statusLabel, statusBadge, modalLabel, integradoLabel, tipoOpLabel },
  };
})();
