  // KAG3 [wait canskip=true] -> [kagwaitskip]: timed wait ended early by
  // a click (Tyrano [wait] hard-blocks clicks for its whole duration).
  tyrano.plugin.kag.tag['kagwaitskip'] = {
    start: function (pm) {
      var kag = this.kag;
      // Skip mode: the engine drops skippable waits outright while skipping
      // (kag.tag.js: `if (is_skip && pm.skippable === "true") nextOrder()`).
      // Without the same check here every [wait]/[wm]/[wt] ran its full
      // duration during skip, which is what made fast-forwarding feel slow.
      if (kag.stat.is_skip) { return kag.ftag.nextOrder(); }
      var ms = parseInt(pm.time) || 1000;
      var finished = false;
      var on_click = function () {
        if (finished) return;
        // Mirror the click handler's early-return checks: if it would
        // bail, keep the timer armed so the wait still ends.
        try {
          var le = kag.layer && kag.layer.layer_event;
          if (!le || le.css('display') === 'none') return;
          if (kag.key_mouse && kag.key_mouse.is_swipe) return;
          if (kag.stat.is_hide_message || kag.stat.is_adding_text ||
              kag.stat.is_click_text || kag.stat.is_stop) return;
        } catch (e) { return; }
        if (finished) return;
        finished = true;
        clearTimeout(kag.tmp.wait_id);
        try { kag.off('click-event.kagwaitskip'); } catch (e) {}
      };
      // KAG3 shows a clickable area during canskip waits; Tyrano's
      // event layer starts hidden, so show it for the click to land.
      try { kag.layer.showEventLayer(); } catch (e) {}
      kag.tmp.wait_id = setTimeout(function () {
        if (finished) return;
        finished = true;
        try { kag.off('click-event.kagwaitskip'); } catch (e) {}
        kag.cancelStrongStop();
        kag.cancelWeakStop();
        kag.stat.is_wait = false;
        kag.ftag.nextOrder();
      }, ms);
      kag.on('click-event.kagwaitskip', on_click);
    },
  };

