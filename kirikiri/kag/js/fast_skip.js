
(function () {
  // TYRANO.kag does not exist yet while plugins are being parsed, so resolve
  // it inside the tick rather than bailing out at load time.
  setInterval(function () {
    try {
      var kag = window.TYRANO && TYRANO.kag;
      if (!kag || !kag.stat || !kag.ftag) return;
      if (!kag.stat.is_skip) return;
      if (kag.stat.is_strong_stop || kag.stat.is_stop) return;
      if (kag.stat.is_adding_text || kag.stat.is_click_text) return;
      if (typeof kag.tmp.cut_nextorder === "function") return;
      var top = document.elementFromPoint(Math.round(window.innerWidth / 2),
                                        Math.round(window.innerHeight / 2));
      if (!top || String(top.className).indexOf("layer_event_click") < 0) return;
      kag.ftag.nextOrder();
    } catch (e) {}
  }, 25);
})();

