#!/usr/bin/env python3
"""TubeLite - Backend server with yt-dlp audio extraction + streaming proxy"""

import json, os, urllib.parse, urllib.request, ssl, socket
from http.server import HTTPServer, BaseHTTPRequestHandler

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

PORT = int(os.environ.get('PORT', 8080))
DEPLOY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deploy')

MIME_TYPES = {
    '.html': 'text/html', '.css': 'text/css', '.js': 'application/javascript',
    '.json': 'application/json', '.png': 'image/png', '.svg': 'image/svg+xml',
    '.webmanifest': 'application/manifest+json', '.ico': 'image/x-icon',
    '.apk': 'application/vnd.android.package-archive',
}

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[REQ] {args[0]}", flush=True)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/api/extract':
            self.handle_extract(parsed.query)
        elif parsed.path == '/api/playlist':
            self.handle_playlist(parsed.query)
        elif parsed.path == '/api/stream':
            self.handle_stream(parsed.query)
        elif parsed.path == '/api/apk':
            self.handle_apk_download()
        else:
            self.serve_file(parsed.path)

    def serve_file(self, path):
        if path == '/': path = '/index.html'
        filepath = os.path.join(DEPLOY_DIR, path.lstrip('/'))
        filepath = os.path.normpath(filepath)
        if not filepath.startswith(DEPLOY_DIR):
            self.send_error(403); return
        if not os.path.isfile(filepath):
            self.send_error(404); return
        ext = os.path.splitext(filepath)[1]
        content_type = MIME_TYPES.get(ext, 'application/octet-stream')
        with open(filepath, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', len(data))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def handle_extract(self, query):
        params = urllib.parse.parse_qs(query)
        url = params.get('url', [''])[0]
        if not url:
            self.send_json(400, {'error': 'Missing url parameter'}); return
        try:
            if HAS_YTDLP:
                ydl_opts = {
                    'format': 'bestaudio/best',
                    'quiet': True,
                    'no_warnings': True,
                    'no_check_certificates': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    title = info.get('title', 'Unknown')
                    # Get the best audio URL
                    if 'entries' in info:
                        entry = info['entries'][0]
                        audio_url = entry.get('url', '')
                        title = entry.get('title', title)
                    else:
                        audio_url = info.get('url', '')
                    proxy_url = '/api/stream?u=' + urllib.parse.quote(audio_url, safe='')
                    self.send_json(200, {'title': title, 'url': proxy_url})
            else:
                self.send_json(500, {'error': 'yt-dlp not installed'})
        except Exception as e:
            self.send_json(500, {'error': str(e)[:200]})

    def handle_playlist(self, query):
        params = urllib.parse.parse_qs(query)
        url = params.get('url', [''])[0]
        if not url:
            self.send_json(400, {'error': 'Missing url parameter'}); return
        try:
            if HAS_YTDLP:
                ydl_opts = {
                    'flat_playlist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'no_check_certificates': True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                    videos = []
                    if 'entries' in info:
                        for e in info['entries']:
                            if e and e.get('id'):
                                videos.append({
                                    'id': e.get('id', ''),
                                    'title': e.get('title', e.get('id', ''))
                                })
                    self.send_json(200, {
                        'title': info.get('title', 'Playlist'),
                        'videos': videos
                    })
            else:
                self.send_json(500, {'error': 'yt-dlp not installed'})
        except Exception as e:
            self.send_json(500, {'error': str(e)[:200]})

    def handle_stream(self, query):
        params = urllib.parse.parse_qs(query)
        url = params.get('u', [''])[0]
        if not url:
            self.send_error(400); return
        try:
            req = urllib.request.Request(url)
            req.add_header('User-Agent', 'Mozilla/5.0')
            ctx = ssl.create_default_context()
            resp = urllib.request.urlopen(req, timeout=30, context=ctx)
            self.send_response(200)
            ct = resp.headers.get('Content-Type', 'audio/webm')
            cl = resp.headers.get('Content-Length')
            self.send_header('Content-Type', ct)
            self.send_header('Access-Control-Allow-Origin', '*')
            if cl:
                self.send_header('Content-Length', cl)
            self.end_headers()
            while True:
                chunk = resp.read(65536)
                if not chunk: break
                self.wfile.write(chunk)
                self.wfile.flush()
        except Exception as e:
            self.send_error(502)

    def handle_apk_download(self):
        apk_path = os.path.join(DEPLOY_DIR, 'tubelite.apk')
        if not os.path.isfile(apk_path):
            self.send_error(404); return
        with open(apk_path, 'rb') as f:
            data = f.read()
        self.send_response(200)
        self.send_header('Content-Type', 'application/vnd.android.package-archive')
        self.send_header('Content-Disposition', 'attachment; filename="TubeLite.apk"')
        self.send_header('Content-Length', len(data))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', PORT), Handler)
    print(f'TubeLite running on port {PORT}')
    server.serve_forever()
