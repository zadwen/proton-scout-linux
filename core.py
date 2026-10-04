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

VERSION = '1.1.0'
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
    if variant in ('hotfix', 'protonhotfix', 'proton-hotfix'):
        version = 'Proton Hotfix'
    elif variant == 'experimental':
        version = 'Proton Experimental'
    elif variant in ('ge', 'notlisted', 'custom', 'other') or version.lower() in ('custom', 'other'):
        variant_note = note_fields.get('variant') if isinstance(note_fields, dict) else ''
        named = str(custom or variant_note or '').strip()
        # Free-form variant notes may be prose. Never treat an entire paragraph as a tool name.
        version = named if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_. +()\-]{0,79}', named) else 'Unknown'
    elif variant == 'native':
        version = 'native'
    version = canonical_version(version)
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
            'source': f'{SOURCE}/app/{appid}#' + urllib.parse.quote(str(row.get('id') or ''), safe=''), 'id': str(row.get('id') or ''),
            'contributor': str((row.get('contributor') or {}).get('id') or ''),
            'oob': response.get('verdictOob') == 'yes',
            'performanceFaults': response.get('performanceFaults') == 'yes',
            'launchOptions': launch, 'driver': str(steam.get('gpuDriver') or ''), 'kernel': str(steam.get('kernel') or '')}

# Display all report profiles; never execute community commands.
import shlex
import math


def canonical_version(version):
    value = version.strip()
    low = re.sub(r'[ _-]+', ' ', value.lower())
    if low in ('hotfix', 'proton hotfix'):
        return 'Proton Hotfix'
    if low in ('experimental', 'proton experimental'):
        return 'Proton Experimental'
    value = re.sub(r'[-_](?:x86_64|amd64)$', '', value, flags=re.I)
    value = re.sub(r'^GE[- ]?Proton', 'GE-Proton', value, flags=re.I)
    if re.fullmatch(r'Proton \d+(?:[.\-]\d+)+', value, re.I):
        value = value[7:]
    return value


def gpu_key(value):
    # Retain model/Super/Ti/XT/laptop qualifiers; never confuse the same vendor with the same GPU.
    low = value.lower()
    m = re.search(r'(?:rtx|gtx|rx|arc)\s*[ab]?\d{3,4}(?:\s*(?:ti|super|xtx|xt|mobile|laptop))*', low)
    return re.sub(r'\s+', '', m[0]) if m else ''


def match_gpu(gpu, hw):
    key = gpu_key(gpu)
    if key and any(gpu_key(g) == key for g in hw.get('gpus', [])):
        return 'model'
    vendor = gpu_vendor(gpu)
    return 'vendor' if vendor != 'Unknown' and any(gpu_vendor(g) == vendor for g in hw.get('gpus', [])) else 'other'


ENV = {'PROTON_NO_FSYNC', 'PROTON_NO_ESYNC', 'PROTON_NO_NTSYNC', 'PROTON_USE_WINED3D',
       'PROTON_DISABLE_NVAPI', 'PROTON_ENABLE_NVAPI', 'PROTON_HIDE_NVIDIA_GPU', 'PROTON_HEAP_DELAY_FREE',
       'PROTON_FORCE_LARGE_ADDRESS_AWARE', 'PROTON_NO_D3D11', 'PROTON_NO_D3D10', 'PROTON_LOG',
       'DXVK_FRAME_RATE', 'MANGOHUD', 'WINE_FULLSCREEN_FSR', 'WINE_FULLSCREEN_FSR_STRENGTH',
       'VKD3D_CONFIG', 'VKD3D_FEATURE_LEVEL', 'VKD3D_DISABLE_EXTENSIONS', 'DXVK_CONFIG',
       'DXVK_CONFIG_FILE', 'DXVK_HDR', 'PROTON_ENABLE_HDR', 'PROTON_ENABLE_WAYLAND',
       'WINEDLLOVERRIDES', 'WINE_CPU_TOPOLOGY', 'PROTON_FSR4_UPGRADE', 'PROTON_FSR4_RDNA3_UPGRADE',
       'ENABLE_LAYER_MESA_ANTI_LAG', '__NV_PRIME_RENDER_OFFLOAD', '__GLX_VENDOR_LIBRARY_NAME',
       '__VK_LAYER_NV_optimus', 'DRI_PRIME', 'SDL_VIDEODRIVER', 'TZ'}


def parse_profile(line, hw):
    line = line.strip().strip('`').strip()
    warnings = []
    if not line:
        return None
    try:
        # Reject shell operators outside quotes, substitutions even inside quotes, and newlines.
        lexer = shlex.shlex(line, posix=True, punctuation_chars=';&|<>()')
        lexer.whitespace_split = True
        tokens = list(lexer)
        if any(t and all(c in ';&|<>()' for c in t) for t in tokens) or any(c in line for c in ('$', '`', '\n', '\r')):
            raise ValueError('Shell syntax requires manual review')
        if '%command%' not in tokens:
            if tokens and all(t.startswith('-') for t in tokens):
                tokens.insert(0, '%command%')
            else:
                raise ValueError('No complete Steam launch command')
        if tokens.count('%command%') != 1:
            raise ValueError('Ambiguous launch command')
        prefix, args = tokens[:tokens.index('%command%')], tokens[tokens.index('%command%')+1:]
        assignments, wrappers = [], []
        for t in prefix:
            if t == 'env' and not assignments and not wrappers:
                continue
            if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.+', t):
                name, value = t.split('=', 1)
                if wrappers:
                    raise ValueError('Environment assignment after a wrapper; check ordering manually')
                if name not in ENV:
                    warnings.append('Unrecognized option: ' + name)
                if any(x in name for x in ('NVAPI', 'NVIDIA', '__NV_', '__GLX_')) and not any(gpu_vendor(g) == 'NVIDIA' for g in hw.get('gpus', [])):
                    warnings.append('NVIDIA-specific option; your selected GPU does not match')
                if name in ('PROTON_ENABLE_HDR', 'DXVK_HDR', 'PROTON_ENABLE_WAYLAND', 'WINE_CPU_TOPOLOGY', 'WINEDLLOVERRIDES', 'DRI_PRIME'):
                    warnings.append(name + ' needs setup-specific review')
                if name in ('PROTON_NO_ESYNC', 'PROTON_ENABLE_NVAPI', 'WINE_FULLSCREEN_FSR'):
                    warnings.append(name + ' is version-dependent; it may be obsolete or unnecessary')
                if any(a.split('=', 1)[0] == name for a in assignments):
                    raise ValueError('Duplicate environment assignment; review ordering manually')
                assignments.append(t)
            elif t in ('gamemoderun', 'mangohud'):
                wrappers.append(t)
                if not hw.get('gamemode' if t == 'gamemoderun' else 'mangohud'):
                    warnings.append(t + ' is not detected on this host')
            else:
                raise ValueError('Complex wrapper or command: review the original profile')
        if any(not re.fullmatch(r'[A-Za-z0-9_.:=,+/\-]+', t) for t in args):
            raise ValueError('Complex game arguments require manual review')
        normalized = ' '.join([shlex.quote(t) for t in sorted(assignments)] + wrappers + ['%command%'] + [shlex.quote(t) for t in args])
        return {'command': normalized, 'original': line, 'copyable': not warnings, 'warnings': list(dict.fromkeys(warnings))}
    except ValueError as exc:
        return {'command': line, 'original': line, 'copyable': False, 'warnings': [str(exc)]}


def safe_flags(notes, hw):
    return list(dict.fromkeys(p['command'] for line in notes.splitlines()
                             if (p := parse_profile(line, hw)) and p['copyable']))


def analyze(raw, appid, hw, now=None):
    now = now or time.time()
    rows, seen, people = [], set(), set()
    parsed = [r for x in raw if (r := normalize(x, appid))]
    for row in sorted(parsed, key=lambda r: r['timestamp'], reverse=True):
        sig = row['id'] or hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
        if sig in seen or (row['contributor'] and row['contributor'] in people):
            continue
        seen.add(sig)
        if row['contributor']:
            people.add(row['contributor'])
        age = (now - row['timestamp']) / 86400 if row['timestamp'] else None
        row['ageDays'] = max(0, round(age)) if age is not None else None
        row['eligible'] = age is not None and 0 <= age <= 180
        row['matchLevel'] = match_gpu(row['gpu'], hw)
        row['match'] = row['matchLevel'] != 'other'
        row['flags'] = safe_flags(row['launchOptions'], hw)
        rows.append(row)
    groups = {}
    for row in rows:
        version = row['version']
        if not row['eligible'] or row['success'] is None or not version or version.lower() in ('custom', 'other', 'unknown', 'native'):
            continue
        g = groups.setdefault(version, dict(version=version, positive=0, negative=0, weightYes=0., weightNo=0., matching=0, exact=0, recent=0, recentNo=0, newest=0, rolling=('experimental' in version.lower() or 'hotfix' in version.lower()), performanceIssues=0))
        weight = math.exp(-row['ageDays'] / 45) * {'model':3, 'vendor':1.5, 'other':.5}[row['matchLevel']]
        g['positive' if row['success'] else 'negative'] += 1
        g['weightYes' if row['success'] else 'weightNo'] += weight
        g['matching'] += int(row['match'])
        g['exact'] += int(row['matchLevel'] == 'model')
        g['recent'] += int(row['success'] and row['ageDays'] <= 30 and row['match'])
        g['recentNo'] += int(not row['success'] and row['ageDays'] <= 30 and row['match'])
        g['performanceIssues'] += int(row['performanceFaults'])
        g['newest'] = max(g['newest'], row['timestamp'])
    ranking = list(groups.values())
    for g in ranking:
        g['score'] = round((g['weightYes']+1)/(g['weightYes']+g['weightNo']+2), 3)
        required = 3 if g['rolling'] else 2
        g['eligible'] = g['recent'] >= required and g['recent'] > 2*g['recentNo'] and g['score'] >= .65
        g['reason'] = ('Eligible recent candidate' if g['eligible'] else
                       'Needs at least ' + str(required) + ' recent positive GPU-matched reports and limited conflicting evidence')
        if g['rolling']:
            g['reason'] += '. Rolling channel: the build tested in a report may differ from today’s build.'
    ranking.sort(key=lambda g: (g['eligible'], g['exact'] > 0, g['score'], g['recent'], g['newest']), reverse=True)
    candidates = [g for g in ranking if g['eligible']]
    winner = candidates[0] if candidates else None
    warnings = []
    if winner and len(candidates) > 1 and abs(winner['score'] - candidates[1]['score']) < .07 and bool(winner['exact']) == bool(candidates[1]['exact']):
        warnings.append('The leading versions are too close to establish one clear recommendation. Compare the alternatives.')
        winner = None
    if winner and winner['rolling']:
        warnings.append('This is a rolling channel, not a fixed version. Update it in Steam and inspect the newest reports before switching.')
    if winner and winner['performanceIssues']:
        warnings.append('Some successful reports still describe performance problems; a working game is not evidence of best FPS.')
    # Preserve every explicit profile, even single reports, old profiles and rejected strings.
    profiles = {}
    for row in rows:
        texts = [(row['launchOptions'], False)] if row['launchOptions'].strip() else []
        texts += [(line, True) for line in row['notes'].splitlines() if '%command%' in line]
        local_seen = set()
        for text, discussion in texts:
            p = parse_profile(text, hw)
            if p and discussion:
                p['copyable'] = False
                p['warnings'].append('Mentioned in discussion: may be conditional or describe a failed attempt. Read the full context.')
            if not p or p['command'] == '%command%' or p['command'] in local_seen:
                continue
            local_seen.add(p['command'])
            key = (row['version'], p['command'], discussion)
            item = profiles.setdefault(key, dict(version=row['version'], command=p['command'], copyable=p['copyable'], warnings=p['warnings'], positive=0, negative=0, matching=0, recent=0, newest=0, sources=[]))
            item['positive'] += int(row['success'] is True)
            item['negative'] += int(row['success'] is False)
            item['matching'] += int(row['match'])
            item['recent'] += int(row['success'] is True and row['eligible'] and row['ageDays'] <= 90 and row['match'])
            item['newest'] = max(item['newest'], row['timestamp'])
            item['sources'].append({'url':row['source'], 'gpu':row['gpu'], 'date':row['timestamp'], 'match':row['matchLevel'], 'notes':row['notes'][:1200]})
    profile_list = sorted(profiles.values(), key=lambda p:(p['recent'], p['matching'], p['newest']), reverse=True)
    for p in profile_list:
        if re.search(r'(?:DXVK|VKD3D)_FRAME_RATE=', p['command']):
            p['warnings'].append('Contains a reported FPS cap; this is not a maximum-FPS boost.')
        if 'MANGOHUD=' in p['command'] or 'mangohud' in p['command']:
            p['warnings'].append('MangoHud is a monitoring overlay, not evidence of a game fix.')
        p['label'] = 'Repeated recent reports' if p['recent'] >= 2 else 'Single / limited report evidence'
        if p['negative']:
            p['warnings'] = p['warnings'] + ['Also present in unsuccessful reports']
        if p['newest'] and now-p['newest'] > 90*86400:
            p['warnings'] = p['warnings'] + ['Older than 90 days']
    supported = [p for p in profile_list if winner and p['version']==winner['version'] and p['recent']>=2 and p['copyable'] and p['negative']==0]
    selected = supported[0] if len(supported)==1 else None
    oob = sum(r['success'] is True and r['oob'] and not r['launchOptions'].strip() and r['eligible'] for r in rows)
    if profile_list:
        flag_status = 'Reported launch options found'
        flag_message = 'Compare the complete profiles below. Options from one report are not automatically required for your PC. Do not combine different profiles.'
    elif oob:
        flag_status = 'Some users explicitly reported out-of-box success'
        flag_message = f'{oob} recent reports explicitly say the game worked out of the box and list no options. This is not a guarantee for your setup.'
    else:
        flag_status = 'Launch-option evidence unavailable'
        flag_message = 'No explicit launch profiles were found in this sample. This does not mean the game needs no flags.'
    return {'recommendation':winner['version'] if winner else None, 'confidence':'Recent community evidence' if winner else 'No clear recent winner',
            'flags':selected['command'] if selected else '', 'flagReports':selected['recent'] if selected else 0,
            'flagStatus':flag_status, 'flagMessage':flag_message, 'profiles':profile_list, 'warnings':warnings,
            'ranking':ranking, 'reports':rows, 'sample':len(rows),
            'explanation':'Only explicit version fields are used. Reports are deduplicated by contributor, weighted by age and GPU model/vendor. Candidates need recent matching successes; Hotfix and Experimental need stronger evidence. Compatibility is not an FPS benchmark.',
            'fallback':'No version meets the recent hardware-matched evidence threshold, or the leading candidates are too close. Review the comparisons and report dates before changing Proton.' if not winner else ''}
