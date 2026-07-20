#!/usr/bin/env python3
"""TubeLite - Backend server with yt-dlp audio extraction + streaming proxy"""

import json, os, urllib.parse, urllib.request, ssl
from flask import Flask, request, Response, send_from_directory, jsonify

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

DEPLOY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'deploy')

app = Flask(__name__, static_folder=DEPLOY_DIR, static_url_path='')

@app.after_request
def add_cors(response):
    response.headers['Access-Control-Allow-Origin'] = '*'
    response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return response

@app.route('/')
def index():
    return send_from_directory(DEPLOY_DIR, 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory(DEPLOY_DIR, path)

@app.route('/api/extract')
def handle_extract():
    url = request.args.get('url', '')
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400
    try:
        if not HAS_YTDLP:
            return jsonify({'error': 'yt-dlp not installed'}), 500
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'no_check_certificates': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get('title', 'Unknown')
            if 'entries' in info:
                entry = info['entries'][0]
                audio_url = entry.get('url', '')
                title = entry.get('title', title)
            else:
                audio_url = info.get('url', '')
            proxy_url = '/api/stream?u=' + urllib.parse.quote(audio_url, safe='')
            return jsonify({'title': title, 'url': proxy_url})
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500

@app.route('/api/playlist')
def handle_playlist():
    url = request.args.get('url', '')
    if not url:
        return jsonify({'error': 'Missing url parameter'}), 400
    try:
        if not HAS_YTDLP:
            return jsonify({'error': 'yt-dlp not installed'}), 500
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
            return jsonify({
                'title': info.get('title', 'Playlist'),
                'videos': videos
            })
    except Exception as e:
        return jsonify({'error': str(e)[:200]}), 500

@app.route('/api/stream')
def handle_stream():
    url = request.args.get('u', '')
    if not url:
        return 'Bad request', 400
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0')
        ctx = ssl.create_default_context()
        resp = urllib.request.urlopen(req, timeout=30, context=ctx)
        ct = resp.headers.get('Content-Type', 'audio/webm')
        cl = resp.headers.get('Content-Length')
        def generate():
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                yield chunk
        headers = {'Content-Type': ct, 'Access-Control-Allow-Origin': '*'}
        if cl:
            headers['Content-Length'] = cl
        return Response(generate(), headers=headers)
    except Exception as e:
        return 'Bad gateway', 502

@app.route('/api/apk')
def handle_apk_download():
    apk_path = os.path.join(DEPLOY_DIR, 'tubelite.apk')
    if not os.path.isfile(apk_path):
        return 'Not found', 404
    with open(apk_path, 'rb') as f:
        data = f.read()
    return Response(data,
        mimetype='application/vnd.android.package-archive',
        headers={
            'Content-Disposition': 'attachment; filename="TubeLite.apk"',
            'Content-Length': len(data)
        })

if __name__ == '__main__':
    PORT = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=PORT, debug=False)
