"""Font and layout injection into the converted project.

`_inject_font()` applies the project's unified CJK font policy (font.css
@font-face + Config.tjs userFace); `_inject_portrait()` appends the portrait
layout CSS.  Both are idempotent, so re-running the converter (or
`--scenario-only`) never stacks duplicate blocks.
"""
import logging
import os
import re
import shutil

from kirikiri.kag.shims import PORTRAIT_CSS

log = logging.getLogger(__name__)


def _inject_font(out, font_path, family, log):
    """Install a CJK font into the Tyrano project as the default text face.

    - copies the font file to tyrano/fonts/
    - appends an @font-face to tyrano/css/font.css (../fonts/ resolves there)
    - prepends the family to Config.tjs `;userFace =` so text without an
      explicit face="" uses it (scene text faces are untouched)
    """
    base = os.path.basename(font_path)
    fonts_dir = os.path.join(out, "tyrano", "fonts")
    os.makedirs(fonts_dir, exist_ok=True)
    shutil.copy2(font_path, os.path.join(fonts_dir, base))

    css_path = os.path.join(out, "tyrano", "css", "font.css")
    if os.path.isfile(css_path):
        with open(css_path, "r", encoding="utf-8") as f:
            css = f.read()
        face = ('@font-face {\n'
                '    font-family: "%s";\n'
                '    src: url("../fonts/%s") format("opentype");\n'
                '    font-weight: normal;\n'
                '    font-style: normal;\n'
                '}\n') % (family, base)
        if face not in css:
            with open(css_path, "a", encoding="utf-8") as f:
                f.write("\n" + face)
            log.info("font.css: appended @font-face %s", family)

    cfg_path = os.path.join(out, "data", "system", "Config.tjs")
    if os.path.isfile(cfg_path):
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = f.read()
        m = re.search(r'(?m)^;userFace\s*=\s*(.*?);\s*$', cfg)
        if m and ('"%s"' % family) not in m.group(1):
            new = ';userFace = "%s", %s;' % (family, m.group(1).strip())
            cfg = cfg[:m.start()] + new + cfg[m.end():]
            with open(cfg_path, "w", encoding="utf-8") as f:
                f.write(cfg)
            log.info("Config.tjs: userFace prepended %s", family)


def _inject_portrait(out, log):
    """Append the portrait layout CSS to the engine's tyrano.css."""
    css_path = os.path.join(out, "tyrano", "css", "tyrano.css")
    if not os.path.isfile(css_path):
        css_path = os.path.join(out, "tyrano", "tyrano.css")
    if not os.path.isfile(css_path):
        log.warning("tyrano.css not found; portrait CSS not applied")
        return
    with open(css_path, "r", encoding="utf-8") as f:
        css = f.read()
    if "portrait layout (generated" in css:
        return
    with open(css_path, "a", encoding="utf-8") as f:
        f.write("\n" + PORTRAIT_CSS)
    log.info("tyrano.css: portrait layout appended")
