
  // ---------------------------------------------------------------------
  // Real implementations for tags whose no-op silently changed behaviour.
  // ---------------------------------------------------------------------

  // [layopt] is NOT a no-op: the engine has no [layopt] at all, so a no-op
  // swallowed layer visibility (2053 call sites: characters the scene had
  // finished with stayed on screen) .
  //
  // It is NOT a positioning tag either. The game writes the same offset on both
  //   [layopt layer=lay_ch_left left=&f.left_x top=&f.left_y]
  //   [image  layer=lay_ch_left left=&f.left_x top=&f.left_y storage=...]
  // and its own KAG3 docs (system/Config.tjs) describe [image] as the foreground
  // position while [position] carries left/top for MESSAGE layers (e.g.
  // `[position layer=message1 frame=name01_ti_0 left=0 top=599]`). Applying the
  // offset here compounded it (measured: a -800px layer offset on top of the
  // image offset), which pushed the side characters of a multi-character shot
  // almost completely out of frame. So: visibility/opacity/index only.
  (function () {
    var T = tyrano.plugin.kag.tag;
    var L = T["layopt"];
    if (!L || L.__kag3_real) return;        // engine implements it -> engine wins
    var isTrue = function (v) { return v === true || String(v) === "true"; };
    var isFalse = function (v) { return v === false || String(v) === "false"; };
    var num = function (v) {
      if (v === null || v === undefined || v === "") return NaN;
      var n = parseFloat(v);
      return isNaN(n) ? NaN : n;
    };
    L.__kag3_real = true;
    L.pm = { layer: "", page: "fore", visible: "", opacity: "", index: "" };
    L.start = function (pm) {
      var name = String(pm.layer == null ? "" : pm.layer);
      if (name !== "" && name !== "base") {
        var j = null;
        try { j = this.kag.layer.getLayer(name, pm.page || "fore"); } catch (e) { j = null; }
        if (j && j.length) {
          if (isTrue(pm.visible)) j.show();
          else if (isFalse(pm.visible)) j.hide();
          var op = num(pm.opacity);
          if (!isNaN(op)) j.css("opacity", Math.max(0, Math.min(1, op / 255)));
          var ix = num(pm.index);
          if (!isNaN(ix)) j.css("z-index", ix);
        }
      }
      this.kag.ftag.nextOrder();
    };
  })();

  // [ch text=X] writes text into the CURRENT message. This game composes both
  // dialogue and every choice item with it, so as a no-op the choice text never
  // appeared at all: [SELECT_NORMAL] emits
  //   [link storage=.. target=..][font color=0xFFFF00][ch text="%sel_1"]...
  // leaving the player an empty message plus invisible clickable areas.
  (function () {
    var T = tyrano.plugin.kag.tag;
    var ch = T["ch"];
    if (!ch || ch.__kag3_real) return;
    window.__kag3_font = window.__kag3_font || {};
    // Remember what the engine's own [font] tag was asked for, so appended runs
    // match the surrounding text.
    var f = T["font"];
    if (f && f.start && !f.__kag3_wrapped) {
      var _fs = f.start;
      f.__kag3_wrapped = true;
      f.start = function (pm) {
        if (pm) {
          if (pm.color != null && pm.color !== "") window.__kag3_font.color = String(pm.color);
          if (pm.size != null && pm.size !== "") window.__kag3_font.size = String(pm.size);
        }
        return _fs.call(this, pm);
      };
    }
    var cssColor = function (v) {
      if (v == null || v === "" || v === "default") return null;
      var s = String(v).replace(/^0x/i, "").replace(/^#/, "");
      return /^[0-9a-fA-F]{6}$/.test(s) ? ("#" + s) : null;
    };
    ch.__kag3_real = true;
    ch.pm = { text: "", layer: "", page: "" };
    ch.start = function (pm) {
      try {
        if (window.__kag3_prepare_message) window.__kag3_prepare_message(this.kag);
        var txt = (pm && pm.text != null) ? String(pm.text) : "";
        // An empty run must not open a paragraph: it would cost a whole line and
        // push later choice items past the window, where overflow:hidden clips them
        // (measured: items 80px apart in a 113px window -> only the first visible).
        if (txt.replace(/[\s\u3000]/g, "") === "") { this.kag.ftag.nextOrder(); return; }
        var $i = this.kag.getMessageInnerLayer();
        if (!$i.length) { this.kag.ftag.nextOrder(); return; }
        if (!$i.find("p").length) this.kag.setNewParagraph($i);
        // Keep the engine's single paragraph. [r] already appends a break;
        // extra paragraphs make setMessageCurrentSpan duplicate link regions.
        var $p = $i.find("p").last().addClass("kag3ch");
        // Mark this window as [ch]-composed so it is exempt from the hard clip:
        // choice items legitimately need more room than the 113px dialogue window.
        $i.addClass("kag3ch-msg");
        // Alignments held back because they arrived while the dialog layer was
        // still empty belong to the text being written now (see the [style]
        // wrapper above).
        if (window.__kag3_pending_align) {
          $i.css("text-align", window.__kag3_pending_align);
          $i.find("p").css("text-align", window.__kag3_pending_align);
          window.__kag3_pending_align = '';
        }
        var $current = this.kag.getMessageCurrentSpan();
        if (!$current.length) $current = this.kag.setMessageCurrentSpan();
        // A [ch] inside Tyrano's [link] span is a selectable item. Mark the
        // complete message layer once the first item appears so CSS can give
        // the prompt and every item one coherent, touch-friendly panel.
        var isChoice = $current.hasClass("event-setting-element") ||
          $current.closest(".event-setting-element").length > 0;
        if (isChoice) {
          $current.addClass("kag3-choice-item");
          $i.addClass("kag3-choice");
          $i.closest(".layer").addClass("kag3-choice-layer");
          $i.find("p>span").not(".event-setting-element,.kag3-choice-item")
            .each(function () {
              var $part = $(this);
              $part.addClass($.trim($part.text()) ? "kag3-choice-prompt" : "kag3-choice-gap");
            });
        } else {
          // Choice classes belong to one prompt only. A later plain [ch]
          // must restore the source message geometry before it appends text.
          $i.removeClass("kag3-choice");
          $i.closest(".layer").removeClass("kag3-choice-layer");
          $i.find(".kag3-choice-item,.kag3-choice-prompt,.kag3-choice-gap").remove();
        }
        var $prev = $current;
        var $s = $("<span></span>");
        if ($prev.length) {
          var st = $prev.attr("style");
          if (st) $s.attr("style", st);
        }
        var font = this.kag.stat.font || {};
        var col = cssColor(font.color);
        if (col) $s.css("color", col);
        $s.text(txt);
        if (font.size) $s.css("font-size", font.size + "px");
        if (font.face) $s.css("font-family", font.face);
        $current.append($s);
      } catch (e) {}
      this.kag.ftag.nextOrder();
    };
  })();

  // [r] (KAG3 newline) and [style align=..] have to work for the runs we append
  // from [ch], otherwise the choice prompt and the first item share one line
  // (owner: "第一个选项不要和描述放在同一行，换一下行吧") and every option loses
  // the alignment the macro asked for.
  //
  // KAG3 scopes [style] to the layer named by [current]; the engine reports the
  // inner of that layer.  The game uses that to align the *name* frame
  // (name.ks NAME_W: [current layer=message1] -> [locate] -> [style align=center])
  // but also emits a bare [style align=center] for the message layer right
  // before it draws a name (SELECT_CLEAR: [cm] [MES_SIZE] [style align=center])
  // -- measured: that wrote an inline text-align:center onto message0's inner
  // and every later line of dialogue stayed centred.owner: "选项之后的对话框
  // 内容全变成居中了").  An alignment request that lands on the dialogue layer
  // while that layer has no text yet is meant for the text that is about to be
  // written (in this game: the speaker name, one layer over), so hold it and
  // apply it to whatever [ch] writes next.  Text already on screen still gets
  // restyled immediately, which is what KAG3 does.
  (function () {
    var T = tyrano.plugin.kag.tag;
    var st = T["style"];
    if (st && st.start && !st.__kag3_wrapped) {
      var _ss = st.start;
      st.__kag3_wrapped = true;
      st.start = function (pm) {
        if (pm && pm.align) {
          var inner = this.kag.getMessageInnerLayer();
          var layer = String((this.kag.stat && this.kag.stat.current_layer) || '');
          var has_text = inner.length > 0 &&
            String(inner.text() || '').replace(/[\s\u3000]/g, '') !== '';
          if (inner.length > 0 && !has_text && layer === 'message0') {
            window.__kag3_pending_align = String(pm.align);
            return _ss.call(this, pm);
          }
          inner.css("text-align", String(pm.align));
          inner.find("p").css("text-align", String(pm.align));
        }
        return _ss.call(this, pm);
      };
    }
  })();

  // KAG3 message-layer positioning. Both tags were no-ops, which is why the
  // speaker name was centred instead of sitting at the window's top-left, the
  // message frame art was never drawn, and choice items lost their indentation.
  (function () {
    var T = tyrano.plugin.kag.tag;
    var num = function (v, d) {
      if (v === null || v === undefined || v === "") return d;
      var n = parseFloat(v);
      return isNaN(n) ? d : n;
    };
    var has = function (v) { return v !== null && v !== undefined && v !== ""; };

    var P = T["position"];
    if (P && P.start && !P.__kag3_wrapped) {
      var _ps = P.start;
      P.__kag3_wrapped = true;
      P.start = function (pm) {
        // Resolve once, then let the native tag size BOTH outer and inner boxes.
        // Never modify geometry asynchronously after native nextOrder().
        var owner = this;
        var args = Object.assign({}, pm);
        if (!args.layer) args.layer = this.kag.stat.current_layer;
        if (!args.page) args.page = this.kag.stat.current_page || "fore";
        var finish = function () {
          var result = _ps.call(owner, args);
          var layer = owner.kag.layer.getLayer(args.layer, args.page);
          var outer = layer.find(".message_outer");
          var inner = layer.find(".message_inner");
          outer.removeClass("kag3-dialog-frame kag3-name-frame kag3-aux-frame");
          inner.removeClass("kag3-dialog-text kag3-name-text kag3-aux-text");
          var w = num(args.width, outer.width());
          var h = num(args.height, outer.height());
          var canvasW = num(owner.kag.config.scWidth, 1024);
          var canvasH = num(owner.kag.config.scHeight, 768);
          if (h >= canvasH * 0.12 && w >= canvasW * 0.55) {
            outer.addClass("kag3-dialog-frame");
            inner.addClass("kag3-dialog-text");
          } else if (h <= canvasH * 0.12 && w >= canvasW * 0.18 &&
                     w <= canvasW * 0.55) {
            outer.addClass("kag3-name-frame");
            inner.addClass("kag3-name-text");
          } else if (h <= canvasH * 0.12 && w < canvasW * 0.18) {
            // These compact layers host the source game's desktop system row.
            // Its [button] tags are dropped on mobile, so retaining the empty
            // frame rectangles only obscures the dialogue.
            outer.addClass("kag3-aux-frame");
            inner.addClass("kag3-aux-text");
          }
          // Tyrano clears background-color whenever a frame image is used.
          // KAG3 layers the frame over its configured translucent backing.
          if (has(args.frame) && args.frame !== "none") {
            var color = has(args.color) ? args.color : owner.kag.config.frameColor;
            if (has(color)) {
              outer.css("background-color", $.convertColor(String(color)));
            }
          }
          return result;
        };
        if (!has(args.frame) || args.frame === "none") return finish();
        var path = typeof window.__kag3_asset_path === "function"
          ? window.__kag3_asset_path(String(args.frame)) : "";
        if (!path) return finish();
        // Native position prefixes relative frames with ./data/image/.
        args.frame = path.replace(/^\.\/data\//, "../");
        if (has(args.width) && has(args.height)) return finish();
        var probe = new Image();
        probe.onload = function () {
          if (!has(args.width)) args.width = String(probe.naturalWidth);
          if (!has(args.height)) args.height = String(probe.naturalHeight);
          finish();
        };
        probe.onerror = function () {
          console.warn("KAG3 position: frame could not load: " + path);
          finish();
        };
        probe.src = path.indexOf("../") === 0 ? "./data/image/" + path : path;
      };
    }

    var LO = T["locate"];
    if (LO && LO.start && !LO.__kag3_wrapped) {
      var _ls = LO.start;
      LO.__kag3_wrapped = true;
      LO.start = function (pm) {
        try {
          var $mi = $(".message_inner").filter(function () {
            return $(this).find("span").length > 0; }).last();
          var $p = $mi.find("p").last();
          if ($p.length) {
            if (has(pm.x)) $p.css("left", num(pm.x, 0) + "px");
            if (has(pm.y)) $p.css("top", num(pm.y, 0) + "px");
          }
        } catch (e) {}
        return _ls.call(this, pm);
      };
    }
  })();
})();

