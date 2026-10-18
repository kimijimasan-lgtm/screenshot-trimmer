#!/usr/bin/env python3
"""スクショトリマー ローカルサーバー
静的ファイル配信 + YouTube字幕取得API (yt-dlp)
"""

import http.server
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse


def find_best_subtitle(video_id, tmpdir):
    """字幕を優先順位に従って取得する。
    日本語手動 → 日本語自動 → 英語手動 → 英語自動
    """
    url = f'https://www.youtube.com/watch?v={video_id}'
    strategies = [
        (['--write-sub'], 'ja', 'manual'),
        (['--write-auto-sub'], 'ja', 'auto'),
        (['--write-sub'], 'en', 'manual'),
        (['--write-auto-sub'], 'en', 'auto'),
    ]

    for flags, lang, sub_type in strategies:
        out_path = os.path.join(tmpdir, 'sub')
        srt_path = f'{out_path}.{lang}.srt'
        if os.path.exists(srt_path):
            os.remove(srt_path)

        cmd = [
            'yt-dlp', '--skip-download',
            '--sub-format', 'srt',
            '--sub-lang', lang,
            '-o', out_path,
        ] + flags + [url]

        try:
            subprocess.run(cmd, capture_output=True, timeout=30, cwd=tmpdir)
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


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == '/api/transcript':
            self.handle_transcript(parsed.query)
        elif parsed.path == '/api/health':
            self.send_json({'status': 'ok'})
        else:
            super().do_GET()

    def handle_transcript(self, query):
        params = urllib.parse.parse_qs(query)
        video_id = params.get('v', [None])[0]

        if not video_id:
            self.send_json({'error': '動画IDが指定されていません'}, 400)
            return

        if not re.match(r'^[A-Za-z0-9_-]{10,12}$', video_id):
            self.send_json({'error': '動画IDの形式が正しくありません'}, 400)
            return

        if not shutil.which('yt-dlp'):
            self.send_json(
                {'error': 'yt-dlpが見つかりません。インストールしてください'},
                500,
            )
            return

        with tempfile.TemporaryDirectory() as tmpdir:
            transcript, lang, sub_type = find_best_subtitle(video_id, tmpdir)

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

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    port = 8321
    host = '127.0.0.1'

    try:
        server = http.server.HTTPServer((host, port), Handler)
    except OSError as e:
        err = getattr(e, 'winerror', None) or getattr(e, 'errno', None)
        if err in (10048, 98):
            print(f'\nポート {port} は既に使用されています。')
            print('別のサーバーが動いている場合は閉じてから再起動してください。')
            print(f'または http://{host}:{port}/ を直接開いてください。')
        else:
            print(f'\nサーバーを起動できませんでした: {e}')
        input('\nEnterキーで閉じます...')
        sys.exit(1)

    print(f'\nスクショトリマー サーバー起動')
    print(f'  URL: http://{host}:{port}/')
    print(f'  終了: Ctrl+C\n')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nサーバーを停止しました')
        server.server_close()


if __name__ == '__main__':
    main()
