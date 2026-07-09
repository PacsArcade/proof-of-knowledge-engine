/*!
 * scar-adapter.js — SCAR portal ↔ POKE node admin API adapter
 * ------------------------------------------------------------
 * Drop-in client for the contract in ADMIN-PORTAL-INTEGRATION.md (§2, §3, §10).
 * Zero dependencies, offline-first, plain <script> or ES-module friendly.
 *
 *   const scar = new PokeAdminClient({
 *     baseUrl: 'http://127.0.0.1:4001',
 *     onAuthFail: () => showTokenGate(),          // 401 → re-prompt (§10.1)
 *   });
 *   scar.setToken(tokenFromOperator);            // never a bot token (§2)
 *
 *   scar.startPolling({
 *     onFleet:  (fleet)  => renderDutyRoster(fleet),   // ~5s heavy snapshot
 *     onEvents: (events) => appendLiveTail(events),    // ~2s tail, cursor-managed
 *     onError:  (err)    => flashPanel(err),
 *   });
 *
 *   await scar.actions.claim('T-0042', '@pacsarcade-ops');
 *
 * House rules honored: "fren" never "friend"; missions not tickets in UI copy
 * (the API says tickets — map at the render layer); runes are etched, never minted.
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.PokeAdminClient = factory();
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var TOKEN_KEY = 'poke_admin_token'; // same slot the reference admin.html uses (§0)

  /** Map of SCAR tabs → the GET endpoints that feed them (§3a / §10.3). */
  var PANEL_ENDPOINTS = {
    bridge:     ['/stats', '/events', '/system/history?window=60'],
    dutyRoster: ['/fleet', '/roster'],
    botDeck:    ['/extensions'],
    fleetMap:   ['/nodes'],
    simulator:  ['/modules'],          // course/escalation loop closes via Duty Roster (§5)
    health:     ['/health', '/system'],
  };

  /** Network safety badge mapping (SCAR brief §1 + spec §4 Fun Budget.network). */
  var NETWORK_BADGES = {
    regtest:  { label: 'SIMULATION MODE / PLAY MONEY', tone: 'safe',    blink: false },
    testnet4: { label: 'SIMULATION MODE / PLAY MONEY', tone: 'caution', blink: false },
    mainnet:  { label: 'SOVEREIGN MAINNET (LIVE ASSETS)', tone: 'danger', blink: true },
  };

  function PokeAdminClient(opts) {
    opts = opts || {};
    this.baseUrl = (opts.baseUrl || 'http://127.0.0.1:4001').replace(/\/+$/, '');
    this.onAuthFail = opts.onAuthFail || function () {};
    this.fetchImpl = opts.fetch || (typeof fetch !== 'undefined' ? fetch.bind(globalThis) : null);
    this.storage = opts.storage !== undefined ? opts.storage
      : (typeof localStorage !== 'undefined' ? localStorage : null);
    this._timers = [];
    this._eventCursor = 0;

    // Mainnet guard: when the node reports network=mainnet, every action requires
    // this async confirm to resolve true (full-page modal per the SCAR brief §1).
    // Ensign clearance should pass a confirm that always returns false.
    this.confirmMainnet = opts.confirmMainnet || function () { return Promise.resolve(true); };
    this._network = 'regtest';

    var actions = this._buildActions();
    this.actions = actions;
  }

  // ── token ────────────────────────────────────────────────────────────────
  PokeAdminClient.prototype.getToken = function () {
    if (this._token) return this._token;
    return this.storage ? (this.storage.getItem(TOKEN_KEY) || '') : '';
  };
  PokeAdminClient.prototype.setToken = function (token) {
    this._token = token || '';
    if (this.storage) {
      if (token) this.storage.setItem(TOKEN_KEY, token);
      else this.storage.removeItem(TOKEN_KEY);
    }
  };
  PokeAdminClient.prototype.clearToken = function () { this.setToken(''); };

  // ── transport ────────────────────────────────────────────────────────────
  PokeAdminClient.prototype._request = function (method, path, body) {
    var self_ = this;
    var headers = { 'X-POKE-Admin-Token': this.getToken() };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    return this.fetchImpl(this.baseUrl + path, {
      method: method,
      headers: headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
    }).then(function (res) {
      if (res.status === 401) {
        // §2/§10.1: clear token, re-show the gate.
        self_.clearToken();
        self_.onAuthFail();
        var err = new Error('401 — admin token rejected');
        err.status = 401;
        throw err;
      }
      if (!res.ok) {
        return res.text().then(function (t) {
          var err = new Error('HTTP ' + res.status + ' ' + path + (t ? ' — ' + t.slice(0, 200) : ''));
          err.status = res.status;
          throw err;
        });
      }
      return res.json();
    });
  };

  PokeAdminClient.prototype.get = function (path) { return this._request('GET', path); };

  PokeAdminClient.prototype.post = function (path, body) {
    var self_ = this;
    if (this._network === 'mainnet') {
      // SCAR brief §1: full-page confirmation before any action on live assets.
      return Promise.resolve(this.confirmMainnet(path, body)).then(function (ok) {
        if (!ok) {
          var err = new Error('Blocked: mainnet action not confirmed (' + path + ')');
          err.blocked = true;
          throw err;
        }
        return self_._request('POST', path, body || {});
      });
    }
    return this._request('POST', path, body || {});
  };

  // ── read snapshots (§3a) ─────────────────────────────────────────────────
  PokeAdminClient.prototype.stats = function () { return this.get('/stats'); };
  PokeAdminClient.prototype.systemHistory = function (windowS) {
    return this.get('/system/history?window=' + (windowS || 60));
  };
  PokeAdminClient.prototype.fleet = function () {
    var self_ = this;
    return this.get('/fleet').then(function (f) {
      if (f && f.budget && f.budget.network) self_._network = f.budget.network;
      return f;
    });
  };
  PokeAdminClient.prototype.roster = function (status) {
    return this.get('/roster' + (status ? '?status=' + encodeURIComponent(status) : ''));
  };
  PokeAdminClient.prototype.rosterTimeline = function (id) {
    return this.get('/roster/' + encodeURIComponent(id) + '/timeline');
  };
  PokeAdminClient.prototype.ranks = function () { return this.get('/ranks'); };
  PokeAdminClient.prototype.leaderboard = function () { return this.get('/leaderboard'); };
  PokeAdminClient.prototype.budget = function () {
    var self_ = this;
    return this.get('/budget').then(function (b) {
      if (b && b.network) self_._network = b.network;
      return b;
    });
  };
  PokeAdminClient.prototype.nodes = function () { return this.get('/nodes'); };
  PokeAdminClient.prototype.health = function () { return this.get('/health'); };
  PokeAdminClient.prototype.system = function () { return this.get('/system'); };
  PokeAdminClient.prototype.extensions = function () { return this.get('/extensions'); };
  PokeAdminClient.prototype.modules = function () { return this.get('/modules'); };
  PokeAdminClient.prototype.playerHistory = function (name) {
    return this.get('/players/' + encodeURIComponent(name) + '/history');
  };
  /** Event tail with managed since-cursor (§3a /events). */
  PokeAdminClient.prototype.events = function () {
    var self_ = this;
    return this.get('/events?since=' + this._eventCursor).then(function (payload) {
      if (payload && typeof payload.next === 'number') self_._eventCursor = payload.next;
      return payload;
    });
  };

  // ── actions (§3b) — thin, named, human-only guards documented ───────────
  PokeAdminClient.prototype._buildActions = function () {
    var c = this;
    return {
      // Duty Roster (missions, in UI copy)
      raise:   function (fields)            { return c.post('/roster', fields); },
      claim:   function (id, officer)       { return c.post('/roster/' + id + '/claim', { officer: officer }); },
      resolve: function (id, officer, disposition) {
        return c.post('/roster/' + id + '/resolve', { officer: officer, disposition: disposition });
      },
      vouch:   function (id, voter)         { return c.post('/roster/' + id + '/vouch', { voter: voter }); }, // human-only (§2)
      commend: function (recipient, points, reason) {
        return c.post('/commend', { recipient: recipient, points: points, reason: reason });
      },
      setBudget: function (allocated_sats, spent_sats) {
        return c.post('/budget', { allocated_sats: allocated_sats, spent_sats: spent_sats });
      },
      engineerAudit: function ()            { return c.post('/engineer/audit'); },
      // Ingest
      knowledgeFlag: function (topic, quote, by) {
        return c.post('/knowledge/flag', { topic: topic, quote: quote, by: by });
      },
      // Moderation & ops (guarded ones stay guarded server-side)
      broadcast: function (msg)             { return c.post('/broadcast', { msg: msg }); },
      kick:    function (name)              { return c.post('/kick', { name: name }); },
      mute:    function (name)              { return c.post('/mute', { name: name }); },
      timeout: function (name, minutes)     { return c.post('/timeout', { name: name, minutes: minutes }); },
      ban:     function (name)              { return c.post('/ban', { name: name }); },
      unban:   function (name)              { return c.post('/unban', { name: name }); },
      toggleExtension: function (id, enabled) { return c.post('/extensions', { id: id, enabled: enabled }); },
      reboot:  function ()                  { return c.post('/reboot'); },   // guarded
      shutdown: function ()                 { return c.post('/shutdown'); }, // guarded, Admiral-only in SCAR UI
    };
  };

  /**
   * Optimistic action helper (§10.4): apply() paints the hopeful state,
   * the POST runs, then refetch() reconciles; rollback() on failure.
   *   scar.optimistic({
   *     apply:    () => markClaimed(id),
   *     action:   () => scar.actions.claim(id, me),
   *     refetch:  () => scar.fleet().then(renderDutyRoster),
   *     rollback: () => unmarkClaimed(id),
   *   });
   */
  PokeAdminClient.prototype.optimistic = function (spec) {
    if (spec.apply) spec.apply();
    return spec.action().then(function (r) {
      return spec.refetch ? Promise.resolve(spec.refetch()).then(function () { return r; }) : r;
    }).catch(function (err) {
      if (spec.rollback) spec.rollback();
      throw err;
    });
  };

  // ── polling (§2: heavy ~5s, tail ~2s) ───────────────────────────────────
  PokeAdminClient.prototype.startPolling = function (handlers) {
    handlers = handlers || {};
    var c = this;
    var onError = handlers.onError || function () {};
    this.stopPolling();

    function safe(fn, cb) {
      return function () { fn.call(c).then(cb || function () {}).catch(onError); };
    }
    if (handlers.onFleet) {
      var f = safe(c.fleet, handlers.onFleet); f();
      this._timers.push(setInterval(f, handlers.fleetMs || 5000));
    }
    if (handlers.onEvents) {
      var e = safe(c.events, handlers.onEvents); e();
      this._timers.push(setInterval(e, handlers.eventsMs || 2000));
    }
    if (handlers.onStats) {
      var s = safe(c.stats, handlers.onStats); s();
      this._timers.push(setInterval(s, handlers.statsMs || 5000));
    }
    if (handlers.onHistory) {
      var h = safe(c.systemHistory, handlers.onHistory); h();
      this._timers.push(setInterval(h, handlers.historyMs || 5000));
    }
  };
  PokeAdminClient.prototype.stopPolling = function () {
    this._timers.forEach(clearInterval);
    this._timers = [];
  };

  // ── SCAR helpers ─────────────────────────────────────────────────────────
  /** Header safety badge props from the last-seen network (SCAR brief §1). */
  PokeAdminClient.prototype.networkBadge = function () {
    return Object.assign({ network: this._network },
      NETWORK_BADGES[this._network] || NETWORK_BADGES.regtest);
  };
  PokeAdminClient.PANEL_ENDPOINTS = PANEL_ENDPOINTS;
  PokeAdminClient.NETWORK_BADGES = NETWORK_BADGES;
  PokeAdminClient.TOKEN_KEY = TOKEN_KEY;

  return PokeAdminClient;
}));
