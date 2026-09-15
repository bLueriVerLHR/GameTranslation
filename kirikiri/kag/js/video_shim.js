  // ---- KAG3 video system (see VIDEO_SHIM_JS in convert_kag.py) ----
  var __kag3_vid = {
    layer: null, page: 'fore', top: 0, left: 0, width: 0, height: 0,
    loop: 'true', visible: false, file: null, playing: false, url: null,
    volume: null
  };
  var __kag3_vid_map = function () { return window.__kag3_videos || {}; };
  var __kag3_vid_resolve = function (name) {
    var s = String(name == null ? '' : name);
    if (!s) return null;
    var m = __kag3_vid_map();
    var stem = s.replace(/^.*[\/]/, '').replace(/\.[^.]+$/, '');
    return m[s.toLowerCase()] || m[stem.toLowerCase()] || s;
  };
  var __kag3_vid_el = function () {
    try { return $('.blendvideo, video.layer_blend_mode').last(); } catch (e) { return $(); }
  };
  var __kag3_vid_stop = function () {
    try {
      __kag3_vid_el().each(function () {
        try { this.pause(); this.removeAttribute('src'); this.load(); } catch (e) {}
        $(this).remove();
      });
    } catch (e) {}
    __kag3_vid.playing = false;
  };
  // Tyrano's [layermode_movie] sets `min-width/height: 100%` AFTER applying
  // width/height, so an explicit KAG3 box ([video width=800 height=600]) is
  // silently overridden and the movie fills the whole canvas.  Measured:
  // element 1024x768 (canvas) before, 800x600 after clearing min-*.  KAG3
  // scales the frame INTO the box, so object-fit: contain reproduces that
  // instead of stretching it.
  // window.__kag3_video_fill (converter --video-fit fill) instead scales the
  // movie to the whole game canvas: object-fit: contain keeps the frame
  // ratio, so a 4:3 movie letterboxes exactly onto a 4:3 canvas and simply
  // plays larger (owner preference for the gallery mpeg player, whose KAG3
  // box leaves a black strip on a larger canvas).
  var __kag3_vid_fit = function () {
    try {
      __kag3_vid_el().each(function () {
        if (window.__kag3_video_fill) {
          this.style.minWidth = '100%';
          this.style.minHeight = '100%';
          this.style.width = '100%';
          this.style.height = '100%';
          this.style.left = '0';
          this.style.top = '0';
          this.style.objectFit = 'contain';
        } else {
          this.style.minWidth = '0';
          this.style.minHeight = '0';
          this.style.objectFit = 'contain';
        }
      });
    } catch (e) {}
  };

  tyrano.plugin.kag.tag['video'] = {
    start: function (pm) {
      var v = __kag3_vid;
      if (pm.layer !== undefined) v.layer = String(pm.layer);
      if (pm.top !== undefined) v.top = parseInt(pm.top, 10) || 0;
      if (pm.left !== undefined) v.left = parseInt(pm.left, 10) || 0;
      if (pm.width !== undefined) v.width = parseInt(pm.width, 10) || 0;
      if (pm.height !== undefined) v.height = parseInt(pm.height, 10) || 0;
      if (pm.loop !== undefined) v.loop = String(pm.loop);
      if (pm.volume !== undefined) v.volume = String(pm.volume);
      if (pm.visible !== undefined) v.visible = String(pm.visible) === 'true';
      __kag3_log('video setup layer=' + v.layer + ' ' + v.left + ',' + v.top +
                 ' ' + v.width + 'x' + v.height + ' loop=' + v.loop);
      this.kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['videolayer'] = {
    start: function (pm) {
      var v = __kag3_vid;
      if (pm.layer !== undefined) v.layer = String(pm.layer);
      if (pm.page !== undefined) v.page = String(pm.page);
      __kag3_log('videolayer ' + v.layer + ' page=' + v.page);
      this.kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['preparevideo'] = {
    start: function (pm) { this.kag.ftag.nextOrder(); },
  };

  tyrano.plugin.kag.tag['openvideo'] = {
    start: function (pm) {
      var name = pm.storage || pm.file || '';
      __kag3_vid.file = __kag3_vid_resolve(name);
      __kag3_vid.playing = false;
      __kag3_log('openvideo ' + name + ' -> ' + __kag3_vid.file);
      this.kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['playvideo'] = {
    start: function (pm) {
      var v = __kag3_vid;
      var kag = this.kag;
      if (pm.storage) v.file = __kag3_vid_resolve(pm.storage);
      if (!v.file) {
        __kag3_log('playvideo: no file opened; skipped');
        kag.ftag.nextOrder();
        return;
      }
      var opt = { video: v.file, loop: v.loop, mode: 'normal', wait: 'false' };
      // Tyrano's movie layer defaults to a SILENT movie (kag.tag.js:
      // `else { video.volume = 0; }`), so a KAG3 [playvideo] with no volume
      // played the clip muted while only the BGM was audible (owner-reported
      // "动画鉴赏…背景音还是菜单的音乐").  KAG3 movies carry their own audio:
      // default to full volume, pass a game-specified volume through.
      opt.volume = (v.volume === null || v.volume === undefined || v.volume === '')
        ? '100' : String(v.volume);
      // layermode_movie prepends ./data/video/ itself, so pass a bare name.
      if (v.width) opt.width = v.width;
      if (v.height) opt.height = v.height;
      opt.top = v.top;
      opt.left = v.left;
      __kag3_log('playvideo ' + JSON.stringify(opt));
      __kag3_vid.playing = true;
      try {
        kag.ftag.startTag('layermode_movie', opt);
        __kag3_vid_fit();
      } catch (e) {
        __kag3_log('playvideo ERROR: ' + e);
        __kag3_vid.playing = false;
      }
      // KAG3 [playvideo] does not wait; [wv] does.
      kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['stopvideo'] = {
    start: function (pm) {
      __kag3_vid_stop();
      this.kag.ftag.nextOrder();
    },
  };

  tyrano.plugin.kag.tag['clearvideolayer'] = {
    start: function (pm) {
      __kag3_vid_stop();
      this.kag.ftag.nextOrder();
    },
  };

  // [wv]: wait for the movie.  Before playback that means "loaded", after it
  // means "finished"; a build with no video (or an already finished one) must
  // not stall, so both fall through to nextOrder.
  tyrano.plugin.kag.tag['wv'] = {
    start: function (pm) {
      var v = __kag3_vid;
      var kag = this.kag;
      if (!v.playing) {
        kag.ftag.nextOrder();
        return;
      }
      var el = __kag3_vid_el().get(0);
      if (!el || el.ended) {
        v.playing = false;
        kag.ftag.nextOrder();
        return;
      }
      var done = false;
      var finish = function (why) {
        if (done) return;
        done = true;
        v.playing = false;
        __kag3_log('wv finished (' + why + ')');
        kag.ftag.nextOrder();
      };
      $(el).one('ended', function () { finish('ended'); });
      $(el).one('error', function () { finish('error'); });
      // A loop video never ends: honour canskip by letting a click through
      // instead of blocking the scenario forever.
      if (v.loop === 'true') {
        var le = kag.layer && kag.layer.layer_event;
        if (le) {
          try { le.show(); } catch (e) {}
          kag.on('click-event.wv', function () { finish('click'); });
        }
      }
    },
  };

