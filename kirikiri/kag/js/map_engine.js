  // ---- KAG3 clickable maps: region actions, province images, hit test ----
  window.__kag3_maps = {};
  var __kag3_debug = function () {
    try { return window.localStorage.getItem('kag3debug') === '1'; } catch (e) { return false; }
  };
  var __kag3_log = function (msg) {
    try { if (__kag3_debug()) console.log('[kag3] ' + msg); } catch (e) {}
  };
  // KAG3 variable semantics: f/sf/tf/mp missing keys read as '' (KAG3
  // scripts universally test f.xxx=='' for unset values; Tyrano returns
  // undefined which fails those tests). Shared by the eval scopes and
  // the map action bodies.
  var __kag3_proxy = function (obj) {
    if (!obj) obj = {};
    return new Proxy(obj, {
      get: function (t, k) {
        var v = t[k];
        return v === undefined ? '' : v;
      },
      set: function (t, k, v) { t[k] = v; return true; },
    });
  };
  var __kag3_assets = function () { return window.__kag3_assets || {}; };
  var __kag3_assets_ma = function () { return window.__kag3_assets_ma || {}; };
  // Storage values resolved by the tag hook look like "../fgimage/x.png":
  // they are relative to the data/<folder>/ a tag prepends.  A consumer that
  // builds a URL itself (this shim, whose page is at the site root) must drop
  // the leading "../" or it escapes data/ entirely - measured: a bare
  // "../fgimage/TITLE.MA" was requested as "/fgimage/TITLE.MA" (404).
  var __kag3_data_url = function (rel) {
    return './data/' + String(rel == null ? '' : rel).replace(/^\.\.\//, '');
  };
  var __kag3_fetch_text = function (rel) {
    if (!rel) return null;
    // `rel` is a canonical path ("fgimage/x.ma") since each asset lives in
    // exactly one place; the ../ form a tag would carry must be normalised
    // because THIS consumer builds the URL from the page root.
    var clean = String(rel).replace(/^\.\.\//, '');
    var urls = [__kag3_data_url(clean)];
    if (clean.indexOf('/') < 0) {
      var folders = ['fgimage', 'bgimage', 'image', 'sound', 'bgm'];
      for (var i = 0; i < folders.length; i++) {
        urls.push('./data/' + folders[i] + '/' + clean);
      }
    }
    for (var u = 0; u < urls.length; u++) {
      try {
        var x = new XMLHttpRequest();
        x.open('GET', urls[u], false);
        x.send();
        if (x.status >= 200 && x.status < 400) return x.responseText;
      } catch (e) {}
    }
    return null;
  };
  var __kag3_ctx_fields = ['storage', 'target', 'onenter', 'onleave', 'hint',
                           'exp', 'cursor', 'countpage', 'autodisable'];
  var __kag3_run_body = function (body, ctx) {
    var kag = window.TYRANO && TYRANO.kag;
    if (!kag || !body) return;
    try {
      var TG = kag;
      var f = __kag3_proxy(kag.stat.f);
      var sf = __kag3_proxy(kag.variable.sf);
      var tf = __kag3_proxy(kag.variable.tf);
      var mp = __kag3_proxy(kag.stat.mp);
      // Pre-declare the province fields so `with` assigns into ctx: JS
      // `with` walks the scope chain when a property is absent and would
      // silently write globals (KAG3's incontextof always targets the
      // context object).
      for (var i = 0; i < __kag3_ctx_fields.length; i++) {
        ctx[__kag3_ctx_fields[i]] = undefined;
      }
      var source = String(body).replace(/\bkag\./g, 'TG.');
      // TJS switch comparisons coerce numeric and string values. JavaScript
      // uses strict equality, so a KAG action such as switch(sf.page) with
      // case "0" misses when the scenario stored numeric 0. Province action
      // expressions are simple identifiers/properties; stringify the switch
      // subject to preserve the source behavior used by gallery page maps.
      source = source.replace(/\bswitch\s*\(([^()]*)\)/g, 'switch(String($1))');
      eval('with (ctx) { ' + source + ' }');
    } catch (e) {}
  };
  var __kag3_parse_ma = function (text) {
    var actions = {};
    var lines = String(text).split(/\r?\n/);
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i].trim();
      if (!line || line.charAt(0) === ';') continue;
      var colon = line.indexOf(':');
      if (colon < 0) continue;
      var n = parseInt(line.substring(0, colon).trim(), 10);
      if (isNaN(n)) continue;
      actions[n] = line.substring(colon + 1);
    }
    return actions;
  };
  var __kag3_query = function (map, n) {
    if (!map || !map.actions) return null;
    if (n === 0) return null;
    var raw = map.actions[n];
    if (raw === undefined) return null;
    var ctx = {};
    __kag3_run_body(raw, ctx);
    if (ctx.storage === undefined && ctx.target === undefined && ctx.onenter === undefined &&
        ctx.onleave === undefined && ctx.hint === undefined && ctx.exp === undefined &&
        ctx.cursor === undefined && ctx.countpage === undefined && ctx.autodisable === undefined) {
      return null;
    }
    return ctx;
  };
  var __kag3_query0 = function (map) {
    if (!map || !map.actions) return null;
    var raw = map.actions[0];
    if (raw === undefined) return null;
    var ctx = {};
    __kag3_run_body(raw, ctx);
    return ctx;
  };
  var __kag3_region_of = function (map, x, y) {
    if (!map || !map.regionCtx || !map.regionCanvas) return 0;
    if (x < 0 || y < 0 || x >= map.regionCanvas.width || y >= map.regionCanvas.height) return 0;
    var d = map.regionCtx.getImageData(x, y, 1, 1).data;
    return d[3] === 0 ? 0 : d[0];
  };
  var __kag3_layer_img_rect = function (kag, layerName, verbose) {
    try {
      var lay = kag.layer.getLayer(layerName, 'fore');
      if (!lay || !lay.length) lay = kag.layer.getLayer(layerName, 'back');
      if (!lay || !lay.length) {
        if (verbose) __kag3_log('map rect: layer div missing ' + layerName);
        return null;
      }
      var el = lay.find('img')[0];
      var r = null;
      if (el) {
        r = el.getBoundingClientRect();
      } else {
        // base layers render via CSS background-image, not <img>:
        // accept the layer div itself when it (or its back twin) carries
        // a background image
        var bg = lay.css('background-image');
        if (!bg || bg === 'none') {
          var b = kag.layer.getLayer(layerName, 'back');
          if (b && b.length) {
            var bbg = b.css('background-image');
            if (bbg && bbg !== 'none') {
              lay = b;
              bg = bbg;
            }
          }
        }
        if (!bg || bg === 'none') {
          if (verbose) {
            __kag3_log('map rect: no img nor background in ' + layerName);
          }
          return null;
        }
        r = lay[0].getBoundingClientRect();
      }
      if (r.width <= 0 || r.height <= 0) {
        if (verbose) __kag3_log('map rect: zero-size ' + layerName);
        return null;
      }
      return r;
    } catch (e) { return null; }
  };
  var __kag3_map_set = function (layerName, actions, maRel) {
    var map = window.__kag3_maps[layerName] = window.__kag3_maps[layerName] || {};
    map.actions = actions;
    map.maRel = maRel || '';
    if (map.pointing === undefined) map.pointing = -1;
    return map;
  };
  var __kag3_map_clear = function (layerName) {
    delete window.__kag3_maps[layerName];
  };
  var __kag3_region_load = function (map, rel) {
    if (!rel) return;
    var folders = ['fgimage', 'bgimage', 'image'];
    var idx = 0;
    var try_load = function () {
      if (idx >= folders.length) {
        __kag3_log('region image FAILED: ' + rel);
        return;
      }
      var img = new Image();
      img.onload = function () {
        var c = document.createElement('canvas');
        c.width = img.naturalWidth;
        c.height = img.naturalHeight;
        var cx = c.getContext('2d');
        cx.drawImage(img, 0, 0);
        map.regionCanvas = c;
        map.regionCtx = cx;
        map.pointing = -1;
        __kag3_log('region image loaded: ' + rel + ' ' + c.width + 'x' + c.height);
      };
      img.onerror = function () { idx++; try_load(); };
      // canonical path first; the per-folder probes only matter for a bare
      // name.  A leading "../" must go: this URL is built from the page root,
      // so "../fgimage/x.png" would escape data/ (measured 404).
      var clean = String(rel).replace(/^\.\.\//, '');
      img.src = clean.indexOf('/') >= 0
        ? __kag3_data_url(clean)
        : './data/' + folders[idx++] + '/' + clean;
    };
    try_load();
  };
  // Map keys are bare basenames ("title_p"), while a storage value may now be
  // a full canonical path ("fgimage/TITLE.MA") or the resolved
  // "../<dir>/<file>" form.  Every place that derives a key from a path must
  // go through this, or the lookup silently misses - measured: the title
  // menu's region image was never found ("hasRegionCanvas: false"), so the
  // buttons rendered but no click could be hit-tested.
  var __kag3_stem = function (name) {
    return String(name == null ? '' : name)
      .replace(/^\.\.\//, '')
      .replace(/^.*[\\/]/, '')
      .replace(/\.[^.]+$/, '')
      .toLowerCase();
  };
  var __kag3_resolve = function (name, map) {
    var s = String(name == null ? '' : name);
    if (!s) return null;
    var key = s.replace(/^\.\.\//, '').toLowerCase();
    var r = map[key];
    if (!r) r = map[key.replace(/\.[^.]+$/, '')];
    if (!r) r = map[__kag3_stem(key)];
    return r || null;
  };
  var __kag3_jump_token = 0;
  var __kag3_jump = function (kag, storage, target) {
    try {
      // KAG3 map jump = window.process -> loadScenario+goToLabel+run,
      // which discards any pending scenario wait ([s]/[l] parked state,
      // wt skip arm, weak/strong stop). Mirror that: clear wait state
      // before jumping so a stale [l] cannot eat the next click.
      try {
        if (kag.tmp && kag.tmp.__kag3_wt_skip) { kag.tmp.__kag3_wt_skip = null; }
        try { kag.off('click-event.kag3wtskip'); } catch (e2) {}
        try { kag.off('click-event.kagwaitskip'); } catch (e2) {}
        kag.cancelWeakStop();
        kag.cancelStrongStop();
        if (kag.stat) {
          kag.stat.is_stop = false;
          kag.stat.is_wait = false;
          kag.stat.is_click_text = false;
        }
        if (kag.tmp && kag.tmp.wait_id) { clearTimeout(kag.tmp.wait_id); kag.tmp.wait_id = null; }
      } catch (e1) {}
      // The tag pump must not be re-entered from inside the click handler that
      // triggered the jump (defer one tick). NOTE: deferring did NOT fix the
      // "page unresponsive" wedge (measured 4/4 still wedged); the actual cause
      // was the fast-skip driver spinning on setTimeout(0). Kept because
      // re-entering the pump from inside an event handler is still wrong.
      var my = ++__kag3_jump_token;
      setTimeout(function () {
        if (my !== __kag3_jump_token) return;
        try {
          __kag3_log('jump ' + storage + ' ' + target);
          kag.ftag.startTag('jump', { storage: String(storage || ''), target: String(target || '') });
        } catch (e) {}
      }, 0);
    } catch (e) {}
  };
  var __kag3_target_is_ui = function (e) {
    var el = e && e.target ? e.target : null;
    while (el && el !== document) {
      if (el.id === 'kag3-mobile-panel' ||
          /^(BUTTON|INPUT|SELECT|TEXTAREA)$/.test(el.tagName || '')) return true;
      if (el.classList &&
          (el.classList.contains('event-setting-element') ||
           el.classList.contains('layer_event_click') ||
           el.classList.contains('layer_menu') ||
           el.classList.contains('layer_free'))) {
        return true;
      }
      el = el.parentNode;
    }
    return false;
  };
  var __kag3_map_click = function (e) {
    var kag = window.TYRANO && TYRANO.kag;
    if (!kag || __kag3_target_is_ui(e)) return false;
    var names = Object.keys(window.__kag3_maps);
    names.sort(function (a, b) {
      var na = parseInt(a, 10), nb = parseInt(b, 10);
      if (!isNaN(na) && !isNaN(nb)) return nb - na;
      if (isNaN(na) && isNaN(nb)) return 0;
      return isNaN(na) ? -1 : 1;
    });
    for (var i = 0; i < names.length; i++) {
      var name = names[i];
      var map = window.__kag3_maps[name];
      if (!map || !map.actions) continue;
      var r = __kag3_layer_img_rect(kag, name, true);
      if (!r) continue;
      var w = map.regionCanvas ? map.regionCanvas.width : r.width;
      var h = map.regionCanvas ? map.regionCanvas.height : r.height;
      var x = Math.floor((e.clientX - r.left) * w / r.width);
      var y = Math.floor((e.clientY - r.top) * h / r.height);
      var n = __kag3_region_of(map, x, y);
      __kag3_log('map click ' + name + ' @' + e.clientX + ',' + e.clientY + ' -> px ' + x + ',' + y +
                 ' region=' + n + (map.regionCanvas ? '' : ' (no region canvas)'));
      var action = __kag3_query(map, n);
      if (!action) continue;
      if (action.exp !== undefined) __kag3_run_body(action.exp, {});
      if (action.storage || action.target) {
        __kag3_log('map jump ' + name + ' -> ' + action.storage + ' ' + action.target);
        var q0 = __kag3_query0(map);
        if (!q0 || q0.autodisable === undefined || String(q0.autodisable) !== 'false') {
          __kag3_map_clear(name);
        }
        __kag3_jump(kag, action.storage, action.target);
        // Only a real jump may swallow the click: stopping propagation
        // here blocks the event layer's click-event, which would stall
        // any pending [wt canskip] wait. exp/onenter-only regions must
        // leave the click flowing to the engine.
        return true;
      }
      __kag3_log('map region ' + name + ' region=' + n +
                 ' (no jump, click passes through)');
    }
    return false;
  };
  var __kag3_map_hover = function (e) {
    var kag = window.TYRANO && TYRANO.kag;
    if (!kag) return;
    for (var name in window.__kag3_maps) {
      var map = window.__kag3_maps[name];
      if (!map || !map.actions) continue;
      var r = __kag3_layer_img_rect(kag, name, false);
      if (!r) continue;
      var w = map.regionCanvas ? map.regionCanvas.width : r.width;
      var h = map.regionCanvas ? map.regionCanvas.height : r.height;
      var x = Math.floor((e.clientX - r.left) * w / r.width);
      var y = Math.floor((e.clientY - r.top) * h / r.height);
      var n = __kag3_region_of(map, x, y);
      if (n === map.pointing) continue;
      if (map.pointing !== -1) {
        var old = __kag3_query(map, map.pointing);
        if (old && old.onleave !== undefined) __kag3_run_body(old.onleave, {});
      }
      map.pointing = n;
      if (n !== 0) {
        var act = __kag3_query(map, n);
        if (act && act.onenter !== undefined) {
          __kag3_log('map hover ' + name + ' -> region ' + n + ' (onenter)');
          __kag3_run_body(act.onenter, {});
        }
      }
    }
  };
  var __kag3_hook_input = function () {
    if (window.__kag3_input_hooked) return;
    window.__kag3_input_hooked = true;
    document.addEventListener('click', function (e) {
      try {
        __kag3_log('map click event @' + e.clientX + ',' + e.clientY +
                   ' target=' + ((e.target && e.target.tagName) || '?') + '.' +
                   ((e.target && e.target.className && e.target.className.baseVal !== undefined
                     ? e.target.className.baseVal : e.target && e.target.className) || ''));
        if (__kag3_map_click(e)) e.stopPropagation();
      } catch (err) {
        __kag3_log('map click ERROR: ' + err);
      }
    }, true);
    document.addEventListener('mousemove', function (e) {
      try { __kag3_map_hover(e); } catch (err) { __kag3_log('map hover ERROR: ' + err); }
    }, true);
  };
  tyrano.plugin.kag.tag['mapaction'] = {
    start: function (pm) {
      var kag = this.kag;
      var layerName = String(pm.layer || 'base');
      var rel = __kag3_resolve(pm.storage, __kag3_assets_ma()) || String(pm.storage || '');
      var text = __kag3_fetch_text(rel);
      var actions = text === null ? {} : __kag3_parse_ma(text);
      var map = __kag3_map_set(layerName, actions, rel);
      var base = __kag3_stem(rel);
      var reg = __kag3_assets()[base + '_p'];
      __kag3_log('mapaction ' + layerName + ' <- ' + rel + ' (' + Object.keys(actions).length +
                 ' regions' + (reg ? ', region ' + reg : ', no region image') + ')');
      if (reg) __kag3_region_load(map, reg);
      __kag3_hook_input();
      kag.ftag.nextOrder();
    },
  };
  tyrano.plugin.kag.tag['mapimage'] = {
    start: function (pm) {
      var layerName = String(pm.layer || 'base');
      var map = window.__kag3_maps[layerName] || __kag3_map_set(layerName, {}, '');
      var rel = __kag3_resolve(pm.storage, __kag3_assets()) || String(pm.storage || '');
      __kag3_region_load(map, rel);
      __kag3_hook_input();
      this.kag.ftag.nextOrder();
    },
  };
  tyrano.plugin.kag.tag['mapdisable'] = {
    start: function (pm) {
      __kag3_map_clear(String(pm.layer || 'base'));
      this.kag.ftag.nextOrder();
    },
  };

