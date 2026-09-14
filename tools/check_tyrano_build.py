#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Play-test gate for a converted TyranoScript build.

Drives the running build in a real (headless) browser and asserts the visual
invariants that kept regressing between automated checks and play-testing:

  Z-ORDER    nothing may paint over the dialogue text (a sprite layer outranking
             the message layer; measured once as sprite z=4000 vs text z=1001)
  OVERSCALE  no image may be drawn larger than the game canvas
  OFFSCREEN  a character's art must not end up almost entirely outside the
             canvas (compounded layer+image offsets did exactly this)
  FIT        each message window must contain its own text (checked window by
             window, because the name plate is a separate message layer)
  FONTSIZE   one message must not mix font sizes (the old shrink-to-fit produced
             uneven sizes the owner rejected)
  SAFE       text must stay clear of the engine's bottom-right control bar

Usage:
    python tools/check_tyrano_build.py --port 9390 --states 30 [--json]
Start the build first (`tyrano/pipeline.py serve <dir> --port ...`) and launch a
browser with a remote-debugging port.  The CDP client (cdp_shot.py) is an
optional dependency: it is looked up in $VISUAL_CHECK_SCRIPTS first, then in
a repo-local tools/cdp/.  No machine path is ever embedded here, and a
missing helper is reported instead of failing obscurely.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time

log = logging.getLogger("check_tyrano_build")

SKIP_JS = r"""JSON.stringify((function(){var b=document.getElementById('tyrano_base');
 var g=b?b.getBoundingClientRect():null;var s=Math.min(innerWidth/1024,innerHeight/768);
 if(!g||g.width<50)g={left:(innerWidth-1024*s)/2,top:(innerHeight-768*s)/2,width:1024*s,height:768*s};
 return [Math.round(g.left+971*g.width/1024),Math.round(g.top+686*g.height/768)];})())"""

REGION_JS = r"""JSON.stringify((function(){var m=(window.__kag3_maps||{}).base;
 if(!m||!m.regionCanvas)return{ready:false};var cv=m.regionCanvas,w=cv.width,h=cv.height;
 var d=cv.getContext('2d').getImageData(0,0,w,h).data,acc={};
 for(var y=0;y<h;y+=3)for(var x=0;x<w;x+=3){var n=d[(y*w+x)*4];if(!n)continue;
   var a=acc[n]||(acc[n]=[0,0,0]);a[0]+=x;a[1]+=y;a[2]++;}
 var out=[];for(var k in acc)out.push([parseInt(k,10),Math.round(acc[k][0]/acc[k][2]),Math.round(acc[k][1]/acc[k][2])]);
 var b=document.getElementById('tyrano_base'),g=b?b.getBoundingClientRect():null;
 if(!g||g.width<50){var s=Math.min(innerWidth/w,innerHeight/h);
  g={left:(innerWidth-w*s)/2,top:(innerHeight-h*s)/2,width:w*s,height:h*s};}
 return {ready:true,regions:out,canvas:[w,h],rect:[g.left,g.top,g.width,g.height]};})())"""

SNAP_JS = r"""
JSON.stringify((function () {
  function R(b){return [Math.round(b.left),Math.round(b.top),Math.round(b.right),Math.round(b.bottom)];}
  function rect(e){return R(e.getBoundingClientRect());}
  function z(e){var n=0,p=e;while(p&&p.nodeType===1){
    var v=parseInt(getComputedStyle(p).zIndex,10); if(!isNaN(v)){n=Math.max(n,v);} p=p.parentElement;} return n;}
  var base=document.getElementById('tyrano_base');
  var bb=base.getBoundingClientRect();
  var o={base:base?rect(base):null};
  var vis=[], fonts={};
  document.querySelectorAll('.message_inner span').forEach(function(s){
    var b=s.getBoundingClientRect();
    if(b.width>0&&b.height>0){vis.push(b);}
    var fs=getComputedStyle(s).fontSize; fonts[fs]=(fonts[fs]||0)+1;});
  o.fonts=fonts; o.chars=vis.length;
  if(vis.length){
    o.text=[Math.round(Math.min.apply(null,vis.map(function(b){return b.left}))),
            Math.round(Math.min.apply(null,vis.map(function(b){return b.top}))),
            Math.round(Math.max.apply(null,vis.map(function(b){return b.right}))),
            Math.round(Math.max.apply(null,vis.map(function(b){return b.bottom})))];}
  o.windows=[];
  document.querySelectorAll('.message_inner').forEach(function(mi){
    var mb=mi.getBoundingClientRect();
    var v=[]; mi.querySelectorAll('span').forEach(function(s){var b=s.getBoundingClientRect();
      if(b.width>0&&b.height>0)v.push(b);});
    if(!v.length) return;
    o.windows.push({rect:R(mb), z:z(mi),
      text:[Math.round(Math.min.apply(null,v.map(function(b){return b.left}))),
            Math.round(Math.min.apply(null,v.map(function(b){return b.top}))),
            Math.round(Math.max.apply(null,v.map(function(b){return b.right}))),
            Math.round(Math.max.apply(null,v.map(function(b){return b.bottom})))]});});
  o.innerZ=o.windows.reduce(function(a,w){return Math.max(a,w.z);},0);
  var imgs=[];
  document.querySelectorAll('#tyrano_base img').forEach(function(im){
    var b=im.getBoundingClientRect();
    if(b.width<8||b.height<8)return;
    var cs=getComputedStyle(im);
    if(cs.display==='none'||cs.visibility==='hidden'||parseFloat(cs.opacity)<0.05)return;
    if(!im.naturalWidth)return;
    var o={src:String(im.src).split('/').slice(-2).join('/'), rect:R(b), z:z(im),
           layerOff:(im.parentElement.style.left||'0px')+'/'+(im.parentElement.style.top||'0px'),
           imgOff:(im.style.left||'0px')+'/'+(im.style.top||'0px')};
    // how much of the ACTUAL art sits inside the canvas (alpha bounding box)
    if(/^[ayz]_t\d/.test(String(im.src).split('/').pop())){
      try{
        var w=160,h=120,cv=document.createElement('canvas');cv.width=w;cv.height=h;
        var g=cv.getContext('2d');g.drawImage(im,0,0,w,h);
        var d=g.getImageData(0,0,w,h).data,x0=w,x1=-1,y0=h,y1=-1;
        for(var yy=0;yy<h;yy++)for(var xx=0;xx<w;xx++){
          if(d[(yy*w+xx)*4+3]>24){if(xx<x0)x0=xx;if(xx>x1)x1=xx;if(yy<y0)y0=yy;if(yy>y1)y1=yy;}}
        if(x1>=0){
          var ax0=b.left+(x0/w)*b.width, ax1=b.left+((x1+1)/w)*b.width;
          var ay0=b.top+(y0/h)*b.height, ay1=b.top+((y1+1)/h)*b.height;
          var vw=Math.max(0,Math.min(ax1,bb.right)-Math.max(ax0,bb.left));
          var vh=Math.max(0,Math.min(ay1,bb.bottom)-Math.max(ay0,bb.top));
          o.artVis=Math.round(100*(vw*vh)/Math.max(1,(ax1-ax0)*(ay1-ay0)));
        }
      }catch(e){}
    }
    imgs.push(o);});
  o.imgs=imgs;
  var ctrl=[];
  document.querySelectorAll('#tyrano_base *').forEach(function(e){
    var b=e.getBoundingClientRect();
    if(b.width<14||b.width>220||b.height<14||b.height>90)return;
    if(b.left<innerWidth*0.72||b.top<innerHeight*0.78)return;
    var cs=getComputedStyle(e);
    if(cs.display==='none'||parseFloat(cs.opacity)<0.2)return;
    ctrl.push([(e.id||e.className||e.tagName).toString().slice(0,20),R(b)]);});
  o.ctrl=ctrl.slice(0,8);
  return o;})())
"""


def overlap(a, b):
    """True when two [left, top, right, bottom] boxes intersect."""
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def judge(snap):
    """Return the list of violations for one page snapshot."""
    notes = []
    tb = snap.get("text")
    bb = snap.get("base")
    if tb and bb:
        for im in snap["imgs"]:
            if im["z"] > snap["innerZ"] and overlap(im["rect"], tb):
                notes.append("Z-ORDER: %s(z=%d>%d) covers text" % (im["src"], im["z"], snap["innerZ"]))
        for im in snap["imgs"]:
            w, h = im["rect"][2] - im["rect"][0], im["rect"][3] - im["rect"][1]
            if w > (bb[2] - bb[0]) * 1.02 or h > (bb[3] - bb[1]) * 1.02:
                notes.append("OVERSCALE: %s %sx%s > canvas %sx%s" % (
                    im["src"], w, h, bb[2] - bb[0], bb[3] - bb[1]))
        # OFFSCREEN: a character whose actual art is almost entirely outside the
        # canvas (reported as \"the side characters of a multi-character shot are
        # not visible\"). layerOff/imgOff are reported: a compounded offset is the
        # usual cause.
        for im in snap["imgs"]:
            vis = im.get("artVis")
            if vis is not None and vis < 40:
                notes.append("OFFSCREEN: %s only %d%% of its art is on screen "
                             "(layerOff=%s imgOff=%s)" % (
                                 im["src"], vis, im.get("layerOff"), im.get("imgOff")))
        for win in snap.get("windows", []):
            wr, wt = win["rect"], win["text"]
            if wr[2] - wr[0] <= 20:
                continue  # hidden/zero-size: nothing to judge
            if (wt[0] < wr[0] - 2 or wt[2] > wr[2] + 2
                    or wt[1] < wr[1] - 2 or wt[3] > wr[3] + 2):
                notes.append("FIT: text %s outside window %s" % (wt, wr))
        for name, cr in snap["ctrl"]:
            if overlap(cr, tb):
                notes.append("SAFE: text overlaps control %s %s" % (name, cr))
    if len(snap.get("fonts") or {}) > 1:
        notes.append("FONTSIZE: one message mixes sizes %s" % snap["fonts"])
    return notes


def cdp_helper_dir():
    """Directory that holds the external `cdp_shot.py` CDP helper, or None.

    $VISUAL_CHECK_SCRIPTS wins (an installed visual-check skill, wherever it
    lives); otherwise a repo-local tools/cdp/ is used.  A per-machine path
    must never be baked into this file - it leaks the author's home layout
    and breaks every other checkout.
    """
    env = os.environ.get("VISUAL_CHECK_SCRIPTS")
    if env:
        return env
    local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cdp")
    return local if os.path.isdir(local) else None


def load_cdp():
    scripts = cdp_helper_dir()
    found = scripts and os.path.isfile(os.path.join(scripts, "cdp_shot.py"))
    if not found:
        raise SystemExit(
            "error: the CDP helper (cdp_shot.py) is not available.\n"
            "  looked in: %s\n"
            "  set VISUAL_CHECK_SCRIPTS to the directory that holds it "
            "(a visual-check skill's scripts/ dir), or drop it in "
            "tools/cdp/ - this gate needs it to read the page over CDP."
            % (scripts or "<none>"))
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    try:
        import cdp_shot
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise SystemExit("error: cannot import cdp_shot from %s: %s"
                         % (scripts, exc))
    return cdp_shot


def run(port, states, shots_dir):
    c = load_cdp()
    page = c.pick_page(port)
    cdp = c.CDP(page["webSocketDebuggerUrl"])
    cdp.eval_js("location.reload()")
    for _ in range(60):
        time.sleep(1)
        try:
            if cdp.eval_js("!!(window.TYRANO && TYRANO.kag && TYRANO.kag.ftag)") == "true":
                break
        except Exception:
            pass
    width, height = int(cdp.eval_js("innerWidth")), int(cdp.eval_js("innerHeight"))
    # enter the story: click the game's own skip button, then the menu region
    deadline = time.time() + 60
    plan = {"ready": False}
    while time.time() < deadline and not plan.get("ready"):
        sx, sy = json.loads(cdp.eval_js(SKIP_JS))
        cdp.click(sx, sy)
        time.sleep(2)
        plan = json.loads(cdp.eval_js(REGION_JS))
    if plan.get("ready"):
        r, cw, ch = plan["rect"], plan["canvas"][0], plan["canvas"][1]
        by = {x[0]: x for x in plan["regions"]}
        tgt = by.get(1) or list(by.values())[0]
        cdp.click(int(r[0] + tgt[1] * r[2] / cw), int(r[1] + tgt[2] * r[3] / ch))
        time.sleep(4)
    if shots_dir:
        os.makedirs(shots_dir, exist_ok=True)
    fails = []
    seen = 0
    for i in range(states):
        try:
            snap = json.loads(cdp.eval_js(SNAP_JS))
        except Exception as exc:
            # Locate the failure: which state, and on which page/port.
            log.error("state %d/%d: page probe failed on port %s: %s: %s "
                      "- stopping the run here (states seen=%d)",
                      i, states, port, type(exc).__name__, exc, seen)
            print("  [%02d] probe failed: %s" % (i, str(exc)[:60]))
            break
        seen = i + 1
        notes = judge(snap)
        print("  [%02d] %s chars=%-3d innerZ=%-6d imgs=%d %s" % (
            i, "OK " if not notes else "!! ", snap["chars"], snap["innerZ"],
            len(snap["imgs"]), " | ".join(notes)))
        if notes:
            fails.append({"state": i, "notes": notes})
            if shots_dir:
                cdp.screenshot(os.path.join(shots_dir, "fail_%02d.png" % i))
        cdp.click(width // 2, int(height * 0.7))
        time.sleep(1.4)
    if shots_dir:
        cdp.screenshot(os.path.join(shots_dir, "last.png"))
    cdp.ws.close()
    print("\n  %d state(s) with problems out of %d" % (len(fails), seen))
    return fails, seen


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=9390, help="browser debug port")
    ap.add_argument("--states", type=int, default=30, help="messages to advance through")
    ap.add_argument("--shots", default=None, metavar="DIR",
                    help="save a screenshot for every failing state")
    ap.add_argument("--json", action="store_true", help="machine-readable result")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="DEBUG diagnostics (per-state probes)")
    args = ap.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s")
    fails, seen = run(args.port, args.states, args.shots)
    if args.json:
        print(json.dumps({"states": seen, "failures": fails}, ensure_ascii=False, indent=2))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
