"""Local hardware discovery and evidence-based Proton report ranking. Python 3.10+."""
import collections
import datetime as dt
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = '1.0.0'
SOURCE = 'https://www.protondb.com'

def read(path):
    try:
        return Path(path).read_text(errors='replace')
    except OSError:
        return ''

def run(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=7, check=False).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''

def vdf(text):
    """Parse nested Valve KeyValues, including quoted Windows-style path escapes."""
    tokens = re.findall(r'"((?:\\.|[^"\\])*)"|([{}])', re.sub(r'(?m)^\s*//.*$', '', text))
    root, stack, key = {}, [], None
    cur = root
    for quoted, brace in tokens:
        if brace == '{':
            child = {}
            if key is not None:
                cur[key] = child
            stack.append(cur)
            cur, key = child, None
        elif brace == '}':
            if stack:
                cur = stack.pop()
            key = None
        else:
            value = quoted.replace('\\"', '"').replace('\\\\', '\\')
            if key is None:
                key = value
            else:
                cur[key], key = value, None
    return root

def steam_scan(home=None, extra=()):
    home = Path(home or Path.home())
    roots = [home / '.local/share/Steam', home / '.steam/steam', home / '.steam/root',
             home / '.var/app/com.valvesoftware.Steam/.local/share/Steam', home / 'snap/steam/common/.local/share/Steam']
    roots += [Path(p).expanduser() for p in extra]
    libraries = set()
    for root in roots:
        if not root.is_dir():
            continue
        libraries.add(root.resolve())
        data = vdf(read(root / 'steamapps/libraryfolders.vdf')).get('libraryfolders', {})
        if isinstance(data, dict):
            for key, entry in data.items():
                path = entry.get('path') if isinstance(entry, dict) else entry if key.isdigit() else None
                if path and Path(path).is_dir():
                    libraries.add(Path(path).resolve())
    games, proton = {}, set()
    for lib in sorted(libraries):
        for f in (lib / 'steamapps').glob('appmanifest_*.acf'):
            data = vdf(read(f)).get('AppState', {})
            if not isinstance(data, dict):
                continue
            appid, name = data.get('appid', ''), data.get('name', '')
            if not str(appid).isdigit() or not name:
                continue
            if re.search(r'proton', name, re.I):
                proton.add(name)
                continue
            if name.startswith(('Steam Linux Runtime', 'Steamworks Common', 'Steamworks Shared')):
                continue
            games[str(appid)] = {'id': str(appid), 'name': name, 'installed': True, 'library': str(lib)}
        for base in [lib / 'compatibilitytools.d', lib / 'steamapps/compatibilitytools.d']:
            if base.is_dir():
                proton.update(p.name for p in base.iterdir() if p.is_dir())
    return {'games': sorted(games.values(), key=lambda g: g['name'].lower()),
            'protons': sorted(proton), 'libraries': [str(p) for p in sorted(libraries)]}

def gpu_vendor(value):
    value = value.lower()
    if 'nvidia' in value or 'geforce' in value or 'rtx' in value or 'gtx' in value:
        return 'NVIDIA'
    if 'amd' in value or 'radeon' in value or 'advanced micro' in value:
        return 'AMD'
    if 'intel' in value:
        return 'Intel'
    return 'Unknown'

def hardware():
    cpu = next((x.split(':', 1)[1].strip() for x in read('/proc/cpuinfo').splitlines() if x.startswith('model name')), platform.processor() or 'Unknown')
    mem = re.search(r'MemTotal:\s+(\d+)', read('/proc/meminfo'))
    osinfo = dict(re.findall(r'^(\w+)=(.*)$', read('/etc/os-release'), re.M))
    pci = run(['lspci', '-nn'])
    gpus = [line.split(': ', 1)[-1] for line in pci.splitlines() if re.search(r'VGA compatible|3D controller|Display controller', line)]
    if not gpus:
        for p in Path('/sys/class/drm').glob('card[0-9]*/device/vendor'):
            vendor = {'0x10de': 'NVIDIA', '0x1002': 'AMD', '0x8086': 'Intel'}.get(read(p).strip(), 'Unknown')
            gpus.append(vendor + ' GPU (install pciutils for model name)')
    nv = run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total', '--format=csv,noheader']) if shutil.which('nvidia-smi') else ''
    drivers = []
    for p in Path('/sys/class/drm').glob('card[0-9]*/device/driver'):
        try:
            drivers.append(p.resolve().name)
        except OSError:
            pass
    return {'cpu': cpu, 'ram': round(int(mem.group(1)) / 1024**2, 1) if mem else None,
            'gpus': gpus or ['GPU unavailable'], 'nvidia': nv, 'drivers': sorted(set(drivers)),
            'os': osinfo.get('PRETTY_NAME', platform.system()).strip('"'), 'kernel': platform.release(),
            'session': os.environ.get('XDG_SESSION_TYPE', 'Unknown'),
            'desktop': os.environ.get('XDG_CURRENT_DESKTOP', 'Unknown'),
            'gamemode': bool(shutil.which('gamemoderun')), 'mangohud': bool(shutil.which('mangohud'))}

class DataClient:
    def __init__(self, cache=None):
        self.cache = Path(cache or Path(os.environ.get('XDG_CACHE_HOME', Path.home() / '.cache')) / 'proton-scout')
        self.cache.mkdir(parents=True, exist_ok=True)

    def get(self, url, ttl=3600, refresh=False):
        path = self.cache / (hashlib.sha256(url.encode()).hexdigest() + '.json')
        old = None
        try:
            old = json.loads(path.read_text())
            if not refresh and time.time() - old['at'] < ttl:
                return old['data'], {'cached': True, 'stale': False, 'at': old['at']}
        except (OSError, ValueError, KeyError, TypeError):
            old = None
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'ProtonScout/1.0 (Linux compatibility helper)', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise ValueError('Response exceeds 8 MB limit')
            data = json.loads(raw)
            at = time.time()
            with tempfile.NamedTemporaryFile(mode='w', dir=self.cache, delete=False) as f:
                json.dump({'at': at, 'data': data}, f)
                tmp = f.name
            os.replace(tmp, path)
            return data, {'cached': False, 'stale': False, 'at': at}
        except Exception as exc:
            if old:
                return old['data'], {'cached': True, 'stale': True, 'at': old['at'], 'error': str(exc)}
            raise RuntimeError(f'Data unavailable: {exc}') from exc

    def search(self, term):
        if term.isdigit():
            return [{'id': term, 'name': 'Steam app ' + term, 'installed': False}]
        url = 'https://store.steampowered.com/api/storesearch/?' + urllib.parse.urlencode({'term': term, 'l': 'english', 'cc': 'US'})
        data, meta = self.get(url, ttl=86400)
        return [{'id': str(g['id']), 'name': g['name'], 'installed': False} for g in data.get('items', []) if str(g.get('id', '')).isdigit()]

    def reports(self, appid, refresh=False):
        summary, rows, errors, metas = {}, [], [], []
        try:
            summary, meta = self.get(f'{SOURCE}/api/v1/reports/summaries/{appid}.json', refresh=refresh)
            if not isinstance(summary, dict):
                raise ValueError('Unexpected summary schema')
            metas.append(meta)
        except Exception as exc:
            errors.append('Rating: ' + str(exc))
        # This is a public website data format, not a stable supported API.
        try:
            counts, meta = self.get(SOURCE + '/data/counts.json', ttl=180, refresh=refresh)
            metas.append(meta)
            for page in range(1, 4):
                key = report_hash(appid, counts['reports'], counts['timestamp'], page)
                payload, meta = self.get(f'{SOURCE}/data/reports/pc/app/{key}.json', ttl=3600, refresh=refresh)
                metas.append(meta)
                if not isinstance(payload, dict) or not isinstance(payload.get('reports'), list):
                    raise ValueError('Detailed-report format changed')
                rows.extend(payload['reports'])
                if len(rows) >= int(payload.get('total', len(rows))) or not payload['reports']:
                    break
        except Exception as exc:
            errors.append('Detailed reports: ' + str(exc) + '. Open ProtonDB or import a saved report JSON.')
        return summary, rows, errors, metas

def report_hash(appid, count, timestamp, page):
    a, c, t = int(appid), int(count), int(timestamp)
    # Equivalent to the site's 32-bit JavaScript hash of its public data key.
    s = f'p{c}p{a * (c % t)}*vRT{a}p{page * (a % t)}undefinedm'
    h = 0
    for char in s:
        h = (31 * h + ord(char)) & 0xffffffff
    return abs(h if h < 0x80000000 else h - 0x100000000)

def strings(value):
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in strings(v)]
    return []

def normalize(row, appid):
    if not isinstance(row, dict):
        return None
    response = row.get('responses') or {}
    device = row.get('device') or {}
    if not isinstance(response, dict) or not isinstance(device, dict):
        return None
    if device.get('hardwareType') in ('steamDeck', 'steam-deck', 'chromebook', 'chromeOs'):
        return None
    rawid = row.get('appId') or row.get('appid') or response.get('answerToWhatGame')
    if rawid and str(rawid) != str(appid):
        return None
    inferred = device.get('inferred') or {}
    steam = inferred.get('steam') or {} if isinstance(inferred, dict) else {}
    if not isinstance(steam, dict):
        steam = {}
    version = str(response.get('protonVersion') or row.get('protonVersion') or '').strip()
    note_fields = response.get('notes') or {}
    variant = str(response.get('variant') or '').lower()
    custom = response.get('customProtonVersion') or response.get('protonVersionCustom')
    if variant == 'experimental':
        version = 'Proton Experimental'
    elif variant in ('ge', 'notlisted', 'custom', 'other') or version.lower() in ('custom', 'other'):
        variant_note = note_fields.get('variant') if isinstance(note_fields, dict) else ''
        named = str(custom or variant_note or '').strip()
        # Free-form variant notes may be prose. Never treat an entire paragraph as a tool name.
        version = named if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. +()\-]{0,79}', named) else 'Unknown'
    elif variant == 'native':
        version = 'native'
    notes = '\n'.join(strings(note_fields) + strings(response.get('concludingNotes')) + strings(row.get('notes')))[:8000]
    launch = str(response.get('launchOptions') or '')[:2000]
    try:
        stamp = float(row.get('timestamp') or 0)
        if stamp > 1e12:
            stamp /= 1000
    except (ValueError, TypeError):
        stamp = 0
    verdict = str(response.get('verdict') or row.get('verdict') or '').lower()
    success = True if verdict in ('yes', 'true', 'platinum', 'gold') else False if verdict in ('no', 'false', 'borked') else None
    return {'version': version, 'success': success, 'timestamp': stamp, 'gpu': str(steam.get('gpu') or ''),
            'cpu': str(steam.get('cpu') or ''), 'os': str(steam.get('os') or ''), 'notes': notes,
            'source': f'{SOURCE}/app/{appid}', 'id': str(row.get('id') or ''),
            'launchOptions': launch, 'driver': str(steam.get('gpuDriver') or ''), 'kernel': str(steam.get('kernel') or '')}

# Copyable proposals contain only these known option names and restricted values.
# Community text is never evaluated or passed to a shell.
ENV = {'PROTON_NO_FSYNC', 'PROTON_NO_ESYNC', 'PROTON_NO_NTSYNC', 'PROTON_USE_WINED3D',
       'PROTON_DISABLE_NVAPI', 'PROTON_ENABLE_NVAPI', 'PROTON_HIDE_NVIDIA_GPU', 'PROTON_HEAP_DELAY_FREE',
       'PROTON_FORCE_LARGE_ADDRESS_AWARE', 'PROTON_NO_D3D11', 'PROTON_NO_D3D10', 'PROTON_LOG',
       'DXVK_FRAME_RATE', 'MANGOHUD', 'WINE_FULLSCREEN_FSR', 'WINE_FULLSCREEN_FSR_STRENGTH'}

def safe_flags(notes, hw):
    results = []
    for line in notes.splitlines():
        line = line.strip().strip('`').strip()
        if '%command%' not in line:
            if line.startswith('-'):
                line = '%command% ' + line
            else:
                continue
        # Accept full command lines only. Do not splice parts of different reports.
        parts = line.split()
        if parts.count('%command%') != 1:
            continue
        split = parts.index('%command%')
        if any(not re.fullmatch(r'--?[A-Za-z][A-Za-z0-9_-]*(?:=[A-Za-z0-9_.-]+)?', p) for p in parts[split+1:]):
            continue
        ok = True
        wrapper_seen = False
        for p in parts[:split]:
            if p in ('gamemoderun', 'mangohud'):
                wrapper_seen = True
                if not hw.get('gamemode' if p == 'gamemoderun' else 'mangohud'):
                    ok = False
            else:
                match = re.fullmatch(r'([A-Z][A-Z0-9_]*)=([0-9]+)', p)
                if wrapper_seen or not match or match[1] not in ENV:
                    ok = False
                elif 'NVAPI' in match[1] or 'NVIDIA' in match[1]:
                    if not any(gpu_vendor(g) == 'NVIDIA' for g in hw.get('gpus', [])):
                        ok = False
        if ok:
            results.append(' '.join(parts))
    return list(dict.fromkeys(results))

def analyze(raw, appid, hw, now=None):
    now = now or time.time()
    rows, seen = [], set()
    for rawrow in raw:
        row = normalize(rawrow, appid)
        if row:
            sig = row['id'] or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
            if sig not in seen:
                seen.add(sig)
                rows.append(row)
    vendors = {gpu_vendor(g) for g in hw.get('gpus', [])} - {'Unknown'}
    groups = {}
    for row in rows:
        age = (now - row['timestamp']) / 86400 if row['timestamp'] else 99999
        row['ageDays'] = round(age) if age != 99999 else None
        row['match'] = gpu_vendor(row['gpu']) in vendors
        row['flags'] = safe_flags(row['launchOptions'] + '\n' + row['notes'], hw)
        version = row['version']
        if age < -1 or age > 365 or row['success'] is None or not version or version.lower() in ('custom', 'other', 'unknown', 'native'):
            continue
        weight = (2 if row['match'] else 1) * (1 if age <= 90 else .6 if age <= 180 else .3)
        g = groups.setdefault(version, {'version': version, 'positive': 0, 'negative': 0, 'weightYes': 0, 'weightNo': 0, 'matching': 0, 'recent': 0, 'newest': 0})
        field = 'positive' if row['success'] else 'negative'
        g[field] += 1
        g['weightYes' if row['success'] else 'weightNo'] += weight
        g['matching'] += int(row['match'])
        g['recent'] += int(age <= 180 and row['success'])
        g['newest'] = max(g['newest'], row['timestamp'])
    ranking = []
    for g in groups.values():
        # Smoothed evidence score, not FPS prediction or success probability.
        g['score'] = round((g['weightYes'] + 1) / (g['weightYes'] + g['weightNo'] + 2), 3)
        ranking.append(g)
    ranking.sort(key=lambda g: (g['score'], g['matching'], g['newest']), reverse=True)
    candidates = [g for g in ranking if g['positive'] >= 2 and g['score'] >= .6 and g['recent'] >= 1]
    winner = candidates[0] if candidates else None
    flags, count = '', 0
    if winner:
        counts = collections.Counter(f for r in rows if r['version'] == winner['version'] and r['success'] is True and r['ageDays'] is not None and 0 <= r['ageDays'] <= 180 and r['match'] for f in r['flags'])
        if counts:
            possible, n = counts.most_common(1)[0]
            if n >= 2:
                flags, count = possible, n
    confidence = 'Limited evidence'
    if winner:
        confidence = 'Moderate evidence' if winner['positive'] >= 5 and winner['matching'] >= 3 and winner['score'] >= .75 else 'Limited evidence'
    return {'recommendation': winner['version'] if winner else None, 'confidence': confidence,
            'flags': flags, 'flagReports': count, 'ranking': ranking,
            'reports': sorted(rows, key=lambda r: r['timestamp'], reverse=True), 'sample': len(rows),
            'explanation': 'Ranked by successful and unsuccessful reports, age, and GPU vendor match. This is compatibility evidence, not an FPS benchmark. CPU, driver and game updates can change the result.',
            'fallback': 'Keep Steam’s default compatibility tool and leave launch options empty as an initial baseline. No supported version recommendation could be established from this sample.' if not winner else ''}
