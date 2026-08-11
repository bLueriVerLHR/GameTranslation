"""TyranoScript / TyranoBuilder (Electron-packaged) toolkit.

TyranoScript games ship as HTML5 projects (index.html + data/ + tyrano/)
often wrapped in an Electron app whose game files live in
resources/app.asar.  JoiPlay runs the plain HTML5 layout directly, so the
build extracts the asar, adjusts browser-incompatible settings (saves use
webstorage instead of the filesystem), re-encodes audio and cleans up.

Modules:
    asar.py    - extract Electron app.asar archives (via @electron/asar)
    build.py   - unpack + prepare a JoiPlay-ready HTML5 folder
    audio.py   - re-encode audio to Ogg Vorbis + rewrite script refs
    clean.py   - remove tool residues / junk files
    verify.py  - validate the built folder
"""
