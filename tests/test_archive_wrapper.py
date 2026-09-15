"""The archive may store a folder's CONTENTS at its root (device-side shape).

Why: a device-side importer (JoiPlay) opens an archive whose root holds
index.html.  The historical 7z-compatible behaviour stores the folder under its
own basename (which ``deliver`` relies on), so flattening is opt-in and must not
leave the folder itself behind as an absolute-path entry.
"""

import os

from rpgmaker import archive


def _make_game(root):
    os.makedirs(os.path.join(root, 'tyrano', 'plugins'))
    with open(os.path.join(root, 'index.html'), 'w', encoding='utf-8') as f:
        f.write('<html></html>')
    with open(os.path.join(root, 'tyrano', 'plugins', 'kag.js'), 'w', encoding='utf-8') as f:
        f.write('// x\n')


def test_default_keeps_the_wrapper(tmp_path):
    game = tmp_path / 'mygame'
    game.mkdir()
    _make_game(str(game))
    out = archive.create(str(game), str(tmp_path / 'wrapped.7z'), level=1)
    names = [n.replace('\\', '/').lstrip('/') for n in archive.names(out)]
    assert 'mygame/index.html' in names
    assert 'index.html' not in names
    assert archive.verify(out) is True


def test_wrapper_false_puts_contents_at_the_root(tmp_path):
    game = tmp_path / 'mygame'
    game.mkdir()
    _make_game(str(game))
    out = archive.create(str(game), str(tmp_path / 'flat.7z'), level=1,
                         wrapper=False)
    names = [n.replace('\\', '/').lstrip('/') for n in archive.names(out)]
    assert 'index.html' in names
    assert 'tyrano/plugins/kag.js' in names
    # No entry may carry the source folder's absolute path.
    assert not any(n.startswith(tmp_path.as_posix().lstrip('/')) for n in names)
    assert not any(n.startswith('mygame/') for n in names)
    assert archive.verify(out) is True
