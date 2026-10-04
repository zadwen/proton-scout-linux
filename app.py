#!/usr/bin/env python3
"""Proton Scout: loopback-only desktop companion. No third-party dependencies."""
import argparse
import concurrent.futures
import json
import mimetypes
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from core import DataClient, analyze, hardware, steam_scan

WEB = Path(__file__).parent / 'web'

def make_handler(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, status, data, kind='application/json'):
            data = json.dumps(data).encode() if kind == 'application/json' else data
            self.send_response(status)
            self.send_header('Content-Type', kind + ('; charset=utf-8' if kind.startswith('text/') else ''))
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def authorized(self):
            expected_host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != expected_host:
                self.send(403, {'error': 'Invalid host'})
                return False
            if self.path.startswith('/api/') and not secrets.compare_digest(self.headers.get('X-Scout-Token', ''), state['token']):
                self.send(403, {'error': 'Open the address printed by the app to authorize this window.'})
                return False
            return True

        def do_GET(self):
            if not self.authorized():
                return
            url = urllib.parse.urlsplit(self.path)
            query = urllib.parse.parse_qs(url.query)
            try:
                if url.path == '/api/system':
                    self.send(200, {'hardware': state['hardware'], **state['steam']})
                elif url.path == '/api/search':
                    term = query.get('q', [''])[0][:150].strip()
                    local = [g for g in state['steam']['games'] if term.lower() in g['name'].lower() or term == g['id']]
                    error = ''
                    remote = []
                    if term:
                        try:
                            remote = state['client'].search(term)
                        except Exception as exc:
                            error = str(exc)
                    ids = {g['id'] for g in local}
                    self.send(200, {'games': local + [g for g in remote if g['id'] not in ids], 'error': error})
                elif url.path == '/api/game':
                    appid = query.get('id', [''])[0]
                    if not appid.isdigit() or len(appid) > 12:
                        raise ValueError('Enter a numeric Steam app ID')
                    summary, rows, errors, meta = state['client'].reports(appid, query.get('refresh') == ['1'])
                    self.send(200, {'id': appid, 'summary': summary, 'errors': errors, 'meta': meta,
                                    'analysis': analyze(rows, appid, state['hardware'])})
                elif url.path in ('/', '/app.js', '/style.css'):
                    p = WEB / ('index.html' if url.path == '/' else url.path[1:])
                    self.send(200, p.read_bytes(), mimetypes.guess_type(p)[0] or 'text/plain')
                else:
                    self.send(404, {'error': 'Not found'})
            except Exception as exc:
                self.send(400, {'error': str(exc)})

        def do_POST(self):
            if not self.authorized():
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 8_000_000:
                    raise ValueError('Request must be smaller than 8 MB')
                body = json.loads(self.rfile.read(length))
                if self.path == '/api/import':
                    appid = str(body.get('id', ''))
                    if not appid.isdigit() or len(appid) > 12:
                        raise ValueError('Select a game before importing')
                    rows = body.get('reports')
                    if not isinstance(rows, list) or len(rows) > 20000:
                        raise ValueError('Expected a reports array with up to 20,000 entries')
                    self.send(200, {'id': appid, 'summary': {}, 'meta': [],
                                    'errors': ['Imported file: provenance is user-supplied; this is not a live ProtonDB fetch.'],
                                    'analysis': analyze(rows, appid, state['hardware'])})
                elif self.path == '/api/rescan':
                    state['hardware'] = hardware()
                    state['steam'] = steam_scan(extra=state['extra'])
                    self.send(200, {'hardware': state['hardware'], **state['steam']})
                elif self.path == '/api/quit':
                    self.send(200, {'ok': True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                else:
                    self.send(404, {'error': 'Not found'})
            except Exception as exc:
                self.send(400, {'error': str(exc)})
    return Handler

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--steam-path', action='append', default=[], help='Additional Steam library root (contains steamapps)')
    args = parser.parse_args()
    with concurrent.futures.ThreadPoolExecutor() as pool:
        h = pool.submit(hardware)
        s = pool.submit(steam_scan, extra=args.steam_path)
        state = {'hardware': h.result(), 'steam': s.result(), 'client': DataClient(),
                 'token': secrets.token_urlsafe(32), 'extra': args.steam_path}
    server = ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(state))
    address = f'http://127.0.0.1:{server.server_port}/#' + state['token']
    print('Proton Scout is running locally. Open:\n' + address, flush=True)
    print('Use Quit in the app or Ctrl+C here to stop.', flush=True)
    if not args.no_browser:
        webbrowser.open(address)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    main()
