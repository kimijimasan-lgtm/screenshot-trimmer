#!/usr/bin/env python3
"""スクショトリマー ローカルサーバー
静的ファイル配信 + YouTube字幕取得API・チャプター取得API (yt-dlp)

起動のしかた（2つのモード）
  python server.py          … 配布モード（exe と同じ動き）
  python server.py --dev    … 開発モード（start.bat が使う）
  exe（PyInstaller でビルドしたもの）… いつも配布モード

  配布モード : ブラウザを自動で開く。画面からの合図が途切れたら自分で終了する。
               画面にはローカル動画モードを出さない。黒い画面には何も出さない。
  開発モード : 今までどおり。ブラウザは start.bat が開く。自動終了しない。
               ローカル動画モードも出る。黒い画面に状況を出す。
"""

import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from functools import partial

APP_ID = 'screenshot-trimmer'
APP_VERSION = '0.2'

DEFAULT_PORT = 8321
HOST = '127.0.0.1'
# ブラウザで開くときは localhost を使う。ホスト名が変わると、ブラウザの保存領域
# （localStorage のAPIキーなど）が別物になってしまうため、今までと同じにそろえる
OPEN_HOST = 'localhost'

# PyInstaller でビルドすると sys.frozen が立つ
FROZEN = getattr(sys, 'frozen', False)
DEV_MODE = (not FROZEN) and ('--dev' in sys.argv)
DIST_MODE = not DEV_MODE

# exe と同じフォルダ（開発中は server.py と同じフォルダ）。
# yt-dlp.exe や port.txt はこのフォルダにある
EXE_DIR = os.path.dirname(os.path.abspath(
    sys.executable if FROZEN else __file__))

# PyInstaller が index.html などを入れるフォルダ（_internal）。
# 開発中は server.py と同じフォルダなので、EXE_DIR と同じ
BUNDLE_DIR = getattr(sys, '_MEIPASS', EXE_DIR)

# 画面からの合図（ハートビート）が途切れたら、自分で終了する（配布モードだけ）
# テストのときだけ、環境変数で短くできる
HEARTBEAT_TIMEOUT = int(os.environ.get('ST_HEARTBEAT_TIMEOUT', 300))  # 5分
STARTUP_GRACE = int(os.environ.get('ST_STARTUP_GRACE', 120))          # 起動直後の猶予 2分
HEARTBEAT_CHECK = int(os.environ.get('ST_HEARTBEAT_CHECK', 10))       # 見張る間隔

# Windows で、yt-dlp を呼ぶたびに黒い窓が一瞬出るのを防ぐ
CREATE_NO_WINDOW = 0x08000000 if os.name == 'nt' else 0

# index.html に差し込む目印。ここをサーバーが書き換えて、画面にモードを伝える
MODE_MARK = b'<!--ST_MODE-->'

# yt-dlp がうまく動かなかったときの、やさしい案内（押したときだけ出る）
MSG_SUB_FAIL = ('字幕が取れませんでした。YouTube側の変更で、'
                '一時的に使えなくなることがあります。ほかの機能は、そのまま使えます')
MSG_CHAP_FAIL = ('チャプターが取れませんでした。YouTube側の変更で、'
                 '一時的に使えなくなることがあります。ほかの機能は、そのまま使えます')


def log(msg):
    """開発モードのときだけ、黒い画面に出す。
    配布モード（exe・console=False）では標準出力が無く、print が落ちることがあるので何もしない。
    """
    if not DEV_MODE:
        return
    try:
        sys.stdout.write(str(msg) + '\n')
        sys.stdout.flush()
    except Exception:
        pass


def show_error(text, title='スクショトリマー'):
    """利用者に見せるエラー。配布モードでは黒い画面が無いので、Windowsのダイアログで出す。"""
    if DEV_MODE:
        log(text)
        return
    if os.name == 'nt':
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)  # MB_ICONERROR
            return
        except Exception:
            pass
    log(text)


_ytdlp_cache = []


def ytdlp_cmd():
    """yt-dlp の場所を返す。見つからなければ None。
    同じフォルダに置いた yt-dlp.exe を優先し、無ければ今までどおり PATH から探す。
    """
    if _ytdlp_cache:
        return _ytdlp_cache[0]
    bundled = os.path.join(EXE_DIR, 'yt-dlp.exe')
    found = bundled if os.path.exists(bundled) else shutil.which('yt-dlp')
    _ytdlp_cache.append(found)
    return found


def run_ytdlp(args, timeout, cwd=None):
    """yt-dlp を呼ぶ。黒い窓を出さない。見つからなければ None を返す。"""
    exe = ytdlp_cmd()
    if not exe:
        return None
    return subprocess.run([exe] + args, capture_output=True, timeout=timeout,
                          cwd=cwd, creationflags=CREATE_NO_WINDOW)


# 字幕の種類ごとの yt-dlp の指定
SUB_FLAGS = {'manual': ['--write-sub'], 'auto': ['--write-auto-sub']}
DEFAULT_PREFER = 'auto'   # 既定は自動生成を優先（手動字幕は動画とずれていることがあるため）


def subtitle_order(prefer):
    """字幕を探す順番を返す。prefer の種類を、言語ごとに先に試す。
    日本語を2種類とも試してから、英語に移る。
    """
    other = 'manual' if prefer == 'auto' else 'auto'
    return [(prefer, 'ja'), (other, 'ja'), (prefer, 'en'), (other, 'en')]


def find_best_subtitle(video_id, tmpdir, prefer=DEFAULT_PREFER):
    """字幕を優先順位に従って取得する。
    prefer='auto'（既定）: 日本語の自動生成 → 日本語の手動 → 英語の自動生成 → 英語の手動
    prefer='manual'      : 日本語の手動 → 日本語の自動生成 → 英語の手動 → 英語の自動生成
    指定した種類が無いときは、もう一方の種類を使う（上の順番のとおり）。
    """
    url = f'https://www.youtube.com/watch?v={video_id}'
    strategies = [(SUB_FLAGS[t], lang, t) for t, lang in subtitle_order(prefer)]

    for flags, lang, sub_type in strategies:
        out_path = os.path.join(tmpdir, 'sub')
        srt_path = f'{out_path}.{lang}.srt'
        if os.path.exists(srt_path):
            os.remove(srt_path)

        args = [
            '--skip-download',
            '--sub-format', 'srt',
            '--sub-lang', lang,
            '-o', out_path,
        ] + flags + [url]

        try:
            run_ytdlp(args, timeout=30, cwd=tmpdir)
        except (subprocess.TimeoutExpired, OSError):
            continue

        if os.path.exists(srt_path):
            with open(srt_path, 'r', encoding='utf-8') as f:
                srt_content = f.read()
            transcript = srt_to_transcript(srt_content)
            if transcript:
                return transcript, lang, sub_type

    return None, None, None


def srt_to_transcript(srt_text):
    """SRTをアプリの字幕解析処理が読める形式に変換する。
    出力形式: タイムスタンプ行(M:SS or H:MM:SS)と本文行が交互に並ぶ
    """
    entries = parse_srt(srt_text)
    entries = deduplicate(entries)
    if not entries:
        return None

    lines = []
    for sec, text in entries:
        if sec >= 3600:
            ts = f'{sec // 3600}:{(sec % 3600) // 60:02d}:{sec % 60:02d}'
        else:
            ts = f'{sec // 60}:{sec % 60:02d}'
        lines.append(ts)
        lines.append(text)

    return '\n'.join(lines)


def parse_srt(srt_text):
    """SRTテキストを (開始秒, テキスト) のリストに変換する。"""
    entries = []
    blocks = re.split(r'\n\n+', srt_text.strip())

    for block in blocks:
        block_lines = block.strip().split('\n')
        if len(block_lines) < 2:
            continue

        time_line = None
        text_start = 0
        for i, line in enumerate(block_lines):
            if '-->' in line:
                time_line = line
                text_start = i + 1
                break

        if not time_line:
            continue

        m = re.match(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})', time_line)
        if not m:
            continue

        sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        text = ' '.join(
            l.strip() for l in block_lines[text_start:] if l.strip()
        )
        text = re.sub(r'<[^>]+>', '', text).strip()

        if text:
            entries.append((sec, text))

    return entries


def deduplicate(entries):
    """自動生成字幕で起きる重複テキストを除去する。"""
    if not entries:
        return entries

    result = [entries[0]]
    for sec, text in entries[1:]:
        prev = result[-1][1]
        if text == prev:
            continue
        if text in prev:
            continue
        if prev in text:
            result[-1] = (result[-1][0], text)
            continue
        result.append((sec, text))

    return result


# チャプター情報のメモリ内キャッシュ（動画ID → {'chapters': [...], 'duration': 秒}）
_chapters_cache = {}
_chapters_lock = threading.Lock()


def fetch_chapters(video_id):
    """yt-dlp で動画の情報だけを取得し、チャプターと長さを返す（ダウンロードはしない）。
    失敗時は (None, エラーメッセージ) を返す。チャプターが無い動画は chapters=[] で成功扱い。
    """
    url = f'https://www.youtube.com/watch?v={video_id}'
    # lang=ja：YouTubeが日本語の動画のチャプター題名を英語に自動翻訳して返すのを防ぐ
    # （Accept-Languageヘッダーでは効かず、extractor-argsで指定すると原文の題名になる）
    args = ['--skip-download', '--dump-single-json',
            '--no-playlist', '--no-warnings',
            '--extractor-args', 'youtube:lang=ja', url]
    try:
        proc = run_ytdlp(args, timeout=45)
    except subprocess.TimeoutExpired:
        return None, 'チャプターの取得に時間がかかりすぎました。しばらくしてからやり直してください'
    except OSError:
        return None, MSG_CHAP_FAIL

    if proc is None or proc.returncode != 0:
        return None, MSG_CHAP_FAIL

    try:
        info = json.loads(proc.stdout.decode('utf-8', errors='replace'))
    except ValueError:
        return None, MSG_CHAP_FAIL

    duration = info.get('duration')
    duration = int(duration) if isinstance(duration, (int, float)) else 0
    chapters = []
    for ch in info.get('chapters') or []:
        start = ch.get('start_time')
        if not isinstance(start, (int, float)):
            continue
        end = ch.get('end_time')
        if not isinstance(end, (int, float)):
            end = duration
        chapters.append({
            'start': int(start),
            'end': int(end),
            'title': str(ch.get('title') or '').strip(),
        })
    return {'chapters': chapters, 'duration': duration}, None


# 画面からの合図（ハートビート）の、最後に届いた時刻
_last_ping = [time.time()]
_ping_lock = threading.Lock()


def touch_ping():
    with _ping_lock:
        _last_ping[0] = time.time()


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        # 配布モードでは何も出さない（開発モードは今までどおり）
        if DEV_MODE:
            super().log_message(fmt, *args)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path in ('/', '/index.html'):
            self.serve_index()
        elif parsed.path == '/api/transcript':
            self.handle_transcript(parsed.query)
        elif parsed.path == '/api/chapters':
            self.handle_chapters(parsed.query)
        elif parsed.path == '/api/ping':
            touch_ping()
            self.send_json({'status': 'ok'})
        elif parsed.path == '/api/health':
            self.send_json({
                'status': 'ok',
                'app': APP_ID,
                'version': APP_VERSION,
                'mode': 'dist' if DIST_MODE else 'dev',
            })
        else:
            super().do_GET()

    def serve_index(self):
        """index.html に、今のモードを差し込んでから返す。
        画面側は、これを見てローカル動画モードの出し分けと、合図の送信を決める。
        """
        path = os.path.join(BUNDLE_DIR, 'index.html')
        try:
            with open(path, 'rb') as f:
                body = f.read()
        except OSError:
            self.send_error(404, 'index.html not found')
            return

        mode = 'dist' if DIST_MODE else 'dev'
        inject = ("<script>window.__ST_MODE__='" + mode + "';"
                  "document.documentElement.className+=' st-" + mode + "';"
                  "</script>").encode('utf-8')
        body = body.replace(MODE_MARK, inject, 1)

        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def handle_transcript(self, query):
        params = urllib.parse.parse_qs(query)
        video_id = params.get('v', [None])[0]

        if not video_id:
            self.send_json({'error': '動画IDが指定されていません'}, 400)
            return

        if not re.match(r'^[A-Za-z0-9_-]{10,12}$', video_id):
            self.send_json({'error': '動画IDの形式が正しくありません'}, 400)
            return

        if not ytdlp_cmd():
            self.send_json({'error': MSG_SUB_FAIL}, 500)
            return

        # prefer=auto（既定）/ manual。変な値が来たら既定に倒す
        prefer = params.get('prefer', [DEFAULT_PREFER])[0]
        if prefer not in SUB_FLAGS:
            prefer = DEFAULT_PREFER

        with tempfile.TemporaryDirectory() as tmpdir:
            transcript, lang, sub_type = find_best_subtitle(
                video_id, tmpdir, prefer)

        if not transcript:
            self.send_json(
                {'error': 'この動画には利用できる字幕がありません'},
                404,
            )
            return

        self.send_json({
            'transcript': transcript,
            'lang': lang,
            'type': sub_type,
        })

    def handle_chapters(self, query):
        params = urllib.parse.parse_qs(query)
        video_id = params.get('v', [None])[0]

        if not video_id:
            self.send_json({'error': '動画IDが指定されていません'}, 400)
            return

        if not re.match(r'^[A-Za-z0-9_-]{10,12}$', video_id):
            self.send_json({'error': '動画IDの形式が正しくありません'}, 400)
            return

        with _chapters_lock:
            cached = _chapters_cache.get(video_id)
        if cached is not None:
            self.send_json(cached)
            return

        if not ytdlp_cmd():
            self.send_json({'error': MSG_CHAP_FAIL}, 500)
            return

        result, error = fetch_chapters(video_id)
        if error:
            self.send_json({'error': error}, 502)
            return

        with _chapters_lock:
            _chapters_cache[video_id] = result
        self.send_json(result)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def read_port():
    """ポートは 8321 に固定。ただし、同じフォルダに port.txt があれば、その番号を使う
    （ほかのソフトと本当にぶつかったときの、逃げ道）。
    ※ポートを変えると、ブラウザの保存領域（APIキーなど）が別物になります。
    """
    path = os.path.join(EXE_DIR, 'port.txt')
    try:
        with open(path, 'r', encoding='utf-8') as f:
            n = int(f.read().strip())
        if 1024 <= n <= 65535:
            return n
    except Exception:
        pass
    return DEFAULT_PORT


def is_our_server(port):
    """そのポートで動いているのが、スクショトリマー自身かどうかを調べる。"""
    try:
        url = f'http://{HOST}:{port}/api/health'
        with urllib.request.urlopen(url, timeout=2) as r:
            data = json.loads(r.read().decode('utf-8', errors='replace'))
        return data.get('app') == APP_ID
    except Exception:
        return False


def open_browser(port):
    try:
        webbrowser.open(f'http://{OPEN_HOST}:{port}/')
    except Exception:
        pass


def watchdog(server, started_at):
    """画面からの合図が途切れたら、サーバーを終わらせる（配布モードだけ）。"""
    while True:
        time.sleep(HEARTBEAT_CHECK)
        now = time.time()
        if now - started_at < STARTUP_GRACE:
            continue
        with _ping_lock:
            last = _last_ping[0]
        if now - max(last, started_at) > HEARTBEAT_TIMEOUT:
            log('画面からの合図が途切れたので、終了します')
            try:
                server.shutdown()
            except Exception:
                pass
            return


class Server(http.server.ThreadingHTTPServer):
    # Windows では、これを True のままにすると、すでに使われているポートにも
    # 束ねられてしまい、二重起動を見つけられない。必ず False にする
    allow_reuse_address = False


def main():
    port = read_port()

    # すでにスクショトリマーが動いていれば、画面をもう1枚開くだけにする
    if is_our_server(port):
        if DIST_MODE:
            open_browser(port)          # 画面をもう1枚開くだけ
        else:
            log(f'すでに起動しています（ポート {port}）')
        sys.exit(0)

    try:
        handler = partial(Handler, directory=BUNDLE_DIR)
        server = Server((HOST, port), handler)
    except OSError as e:
        err = getattr(e, 'winerror', None) or getattr(e, 'errno', None)
        if err in (10048, 98):
            if is_our_server(port):
                # すでにスクショトリマーが動いている。画面をもう1枚開くだけにする
                if DIST_MODE:
                    open_browser(port)
                else:
                    log(f'すでに起動しています（ポート {port}）')
                sys.exit(0)
            show_error(
                f'ポート {port} が、ほかのソフトに使われているため、'
                '起動できませんでした。\n\n'
                'そのソフトを閉じてから、もう一度お試しください。'
            )
            sys.exit(1)
        show_error(f'サーバーを起動できませんでした。\n\n{e}')
        sys.exit(1)

    started_at = time.time()
    touch_ping()

    if DIST_MODE:
        threading.Thread(target=watchdog, args=(server, started_at),
                         daemon=True).start()
        open_browser(port)
    else:
        log('\nスクショトリマー サーバー起動（開発モード）')
        log(f'  URL: http://{OPEN_HOST}:{port}/')
        log('  終了: Ctrl+C\n')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log('\nサーバーを停止しました')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
