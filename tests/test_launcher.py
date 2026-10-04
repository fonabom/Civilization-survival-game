"""Launcher updater tests: a real zip served over a local HTTP server.

The updater copies real files and makes real backups, so the temp folders are
used for real: nothing here is mocked except the "GitHub" itself.
"""
import http.server
import socketserver
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import launcher
from shared.build import is_newer

def make_zip(path: Path, build: str, extra_files=None):
    with zipfile.ZipFile(path, 'w') as zf:
        zf.writestr('game-folder/build.txt', build + '\n')
        zf.writestr('game-folder/run_client.py', '# fake client entry point\n')
        zf.writestr('game-folder/client/game.py', '# fake game module\n')
        for name, content in (extra_files or {}).items():
            zf.writestr('game-folder/' + name, content)

def serve(directory: Path):
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(directory), **k)
    httpd = socketserver.TCPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]

def build_root(tmp: Path) -> Path:
    root = tmp / 'game'
    (root / 'client').mkdir(parents=True)
    (root / 'build.txt').write_text('b7\n')
    (root / 'run_client.py').write_text('# old client\n')
    (root / 'client' / 'game.py').write_text('# old game\n')
    (root / 'assets').mkdir()
    (root / 'assets' / 'tree.png').write_bytes(b'PNG')
    return root

def test_launcher_updater():
    """Runs the whole updater flow against a local HTTP server with real files."""
    results = []

    def check(name, cond, detail=''):
        results.append((name, bool(cond)))
        print(('[ok  ] ' if cond else '[FAIL] ') + name + ('' if cond else f'  {detail}'))

    tmp = Path(tempfile.mkdtemp())
    root = build_root(tmp)
    serve_dir = tmp / 'server'
    serve_dir.mkdir()
    make_zip(serve_dir / 'game.zip', 'b9')
    (serve_dir / 'build.txt').write_text('b9\n')
    httpd, port = serve(serve_dir)

    results = []
    def check(name, cond, detail=''):
        results.append((name, bool(cond)))
        print(('[ok  ] ' if cond else '[FAIL] ') + name + ('' if cond else f'  {detail}'))

    # 1. build id comparison
    check('b10 is newer than b9 but b9 is not newer than b7',
          is_newer('b10', 'b9') and is_newer('b9', 'b7') and not is_newer('b7', 'b7'))
    check('build ids keep counting past b9', is_newer('b11', 'b10'))
    local_build = (Path(__file__).resolve().parent.parent / 'build.txt').read_text(
        encoding='utf-8').strip()
    check('the launcher reads the local build id',
          launcher.read_build() == local_build, launcher.read_build())

    # 2. direct source over HTTP
    up = launcher.Updater(root=root, repo='', branch='', direct_zip_url=f'http://127.0.0.1:{port}/game.zip',
                          direct_version_url=f'http://127.0.0.1:{port}/build.txt')
    candidate, build = up.check()
    check('the updater found the local update source', candidate is not None, str(candidate))
    check('the remote build id is read from the source', build == 'b9', build)

    percentages = []
    archive = up.download(candidate, progress=percentages.append)
    check('the archive downloaded', archive.exists() and archive.stat().st_size > 0)
    check('progress was reported while downloading', percentages and percentages[-1] == 100,
          str(percentages[:3]))

    # 3. install
    _, installed_build = up.install(archive)
    check('the installed build id is b9', installed_build == 'b9', installed_build)
    check('build.txt in the game folder was updated', (root / 'build.txt').read_text().strip() == 'b9')
    check('existing files were replaced', (root / 'client' / 'game.py').read_text().startswith('# fake'))
    check('files that are not in the archive were kept', (root / 'assets' / 'tree.png').exists())
    backups = list(root.glob('backup_before_update_*'))
    check('a backup of the previous state was made', len(backups) == 1, str(backups))
    check('the backup holds the old files', backups and 'old client' in (backups[0] / 'run_client.py').read_text())

    # 4. up-to-date detection
    candidate2, build2 = up.check()
    check('a second check reports the same build (nothing newer)', build2 == 'b9')

    # 5. hostile archive
    bad = tmp / 'bad.zip'
    with zipfile.ZipFile(bad, 'w') as zf:
        zf.writestr('../../evil.txt', 'boom')
    try:
        launcher.safe_extract(bad, tmp / 'extract_me')
        check('an archive with ../ paths is refused', False, 'no exception')
    except ValueError as exc:
        check('an archive with ../ paths is refused', True, str(exc))
    check('nothing was written outside the extraction folder',
          not (tmp.parent / 'evil.txt').exists())

    # 6. archive without the game inside
    empty = tmp / 'empty.zip'
    with zipfile.ZipFile(empty, 'w') as zf:
        zf.writestr('readme.txt', 'nothing here')
    try:
        up.install(empty)
        check('an archive without run_client.py is refused', False, 'no exception')
    except ValueError as exc:
        check('an archive without run_client.py is refused', True, str(exc))

    # 7. build id from a github-style archive (nested folder)
    gh = tmp / 'github.zip'
    make_zip(gh, 'b42')
    check('the build id is read from a nested archive too',
          launcher.build_id_from_archive(gh) == 'b42', launcher.build_id_from_archive(gh))

    httpd.shutdown()
    failed = [name for name, ok in results if not ok]
    for name in failed:
        print("  FAILED:", name)
    assert not failed, f"{len(failed)} launcher check(s) failed: {failed}"


if __name__ == "__main__":
    test_launcher_updater()
    print("launcher updater checks passed")
