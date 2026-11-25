"""B proposal: typed enumeration only, never a fixture/transport authorization.

No entry point: a reviewed caller must supply an already guarded NativeReadOnly.
"""
import re
import time

BDF = r'[0-9a-f]{4}:[0-9a-f]{2}:[0-1][0-9a-f]\.[0-7]'
RELEASE = r'[0-9]+\.[0-9]+\.[0-9]+(?:[-+.][A-Za-z0-9_.+-]{1,96})?'
CARDS = '/proc/asound/cards'
PCM = '/proc/asound/pcm'
CAPTURE = re.compile(r'/proc/asound/card([0-7])/pcm([0-9]|[12][0-9]|3[01])c/sub([0-7])/(hw_params|status)')
PATHS = r'''for f in /proc/asound/card[0-7]/pcm[0-9]*c/sub[0-7]/hw_params /proc/asound/card[0-7]/pcm[0-9]*c/sub[0-7]/status; do [ ! -e "$f" ] || printf '%s\n' "$f"; done'''
PCI = r'''n_bdf=0; for d in /sys/bus/pci/devices/*; do [ -d "$d" ] || continue; n_bdf=$((n_bdf+1)); [ "$n_bdf" -le 64 ] || exit 46; c=$(cat "$d/class") || exit 45; case "$c" in 0x0403??) v=$(cat "$d/vendor") || exit 45; n=$(cat "$d/device") || exit 45; r=NONE; if [ -L "$d/driver" ]; then r=$(readlink -f "$d/driver") || exit 45; fi; printf '%s %s %s %s %s\n' "${d##*/}" "$c" "$v" "$n" "$r";; esac; done'''
LINKS = r'''for d in /sys/class/sound/card[0-7]; do [ -e "$d" ] || continue; p=$(readlink -f "$d/device") || exit 45; printf '%s %s\n' "${d##*/}" "$p"; done'''
MODULE = 'if [ -d /sys/module/snd_hda_intel ]; then printf PRESENT; else printf ABSENT; fi'


def state(value, **fields):
    return dict(state=value, **fields)


def alsa(path, text):
    if not text.strip():
        return state('EMPTY')
    if path == CARDS:
        if text.strip() == '--- no soundcards ---':
            return state('NO_SOUNDCARDS')
        rows = []
        for line in text.splitlines():
            m = re.fullmatch(r'\s*([0-7]) \[([A-Za-z0-9_-]{1,32}) *\]: ([A-Za-z0-9_-]{1,32}) - [A-Za-z0-9 _().:-]{1,120}', line)
            if m:
                rows.append(dict(card=int(m[1]),id=m[2],driver=m[3]))
            elif not re.fullmatch(r' +[A-Za-z0-9 _().:/,@+-]{1,180}', line):
                return state('UNRECOGNISED')
        return state('PARSED', cards=rows) if rows and len({r['card'] for r in rows}) == len(rows) else state('UNRECOGNISED')
    if path == PCM:
        rows = []
        for line in text.splitlines():
            m = re.fullmatch(r'([0-7][0-9]?)-([0-9]{2}): [A-Za-z0-9 _.,()/+-]{1,160}( : (?:playback|capture) [0-9]{1,2}){1,2}', line)
            if not m or int(m[1]) > 7 or int(m[2]) > 31:
                return state('UNRECOGNISED')
            rows.append(dict(card=int(m[1]),pcm=int(m[2]),capture=bool(re.search(r' : capture [1-9]',line)),playback=bool(re.search(r' : playback [1-9]',line))))
        return state('PARSED', pcm=rows)
    if not CAPTURE.fullmatch(path):
        return state('UNRECOGNISED')
    if text.strip() == 'closed':
        return state('PARSED', closed=True)
    values = {}
    for line in text.splitlines():
        m = re.fullmatch(r'(access|format|subformat|channels|rate|period_size|buffer_size|state|owner_pid|hw_ptr|appl_ptr|delay|avail|avail_max|trigger_time|tstamp|audio_tstamp):\s*(.{1,100})', line)
        if not m or m[1] in values:
            return state('UNRECOGNISED')
        key, value = m[1], m[2]
        if re.fullmatch(r'-?[0-9]{1,18}', value): values[key] = int(value)
        elif key == 'rate' and re.fullmatch(r'[0-9]{1,6} \([0-9]{1,6}/[0-9]{1,6}\)', value): values[key] = int(value.split()[0])
        elif key in ('trigger_time','tstamp','audio_tstamp') and re.fullmatch(r'[0-9]{1,12}\.[0-9]{1,9}', value): values[key] = value
        elif key == 'access' and value in ('RW_INTERLEAVED','RW_NONINTERLEAVED','MMAP_INTERLEAVED','MMAP_NONINTERLEAVED'): values[key] = value
        elif key == 'format' and value in ('S16_LE','S24_LE','S32_LE','FLOAT_LE'): values[key] = value
        elif key == 'subformat' and value == 'STD': values[key] = value
        elif key == 'state' and value in ('OPEN','SETUP','PREPARED','RUNNING','XRUN','DRAINING','PAUSED','SUSPENDED','DISCONNECTED'): values[key] = value
        else: return state('UNRECOGNISED')
    return state('PARSED',values=values)


def kernel(kind, text):
    pattern = RELEASE if kind == 'release' else 'Linux version ('+RELEASE+r') [^\r\n]{0,1900}'
    m = re.fullmatch(pattern, text.strip())
    return state('PARSED',release=m[0] if kind == 'release' else m[1]) if m else state('UNRECOGNISED')


def pci(text):
    if not text.strip(): return state('EMPTY')
    rows = []
    for line in text.splitlines():
        m = re.fullmatch('('+BDF+r') (0x0403[0-9a-f]{2}) (0x[0-9a-f]{4}) (0x[0-9a-f]{4}) (NONE|/sys/bus/pci/drivers/[A-Za-z0-9_-]{1,48})',line)
        if not m or len(rows) == 16 or any(r['bdf']==m[1] for r in rows): return state('UNRECOGNISED')
        rows.append(dict(bdf=m[1],class_id=m[2],vendor=m[3],device=m[4],driver=m[5]))
    return state('PARSED',devices=rows)


def card_links(text):
    rows=[]
    for line in text.splitlines():
        m=re.fullmatch(r'card([0-7]) /sys/devices/pci[0-9a-f]{4}:[0-9a-f]{2}/('+BDF+r')',line)
        if not m or any(r['card']==int(m[1]) for r in rows): return state('UNRECOGNISED')
        rows.append(dict(card=int(m[1]),bdf=m[2]))
    return state('PARSED',links=rows) if rows else state('EMPTY')


def read_row(run, command, parser, deadline, limit=4096, clock=time.monotonic):
    start=clock();remaining=deadline-start
    if remaining<=0: return state('COMMAND_FAILED',reason='TOTAL_BUDGET')
    try:
        raw,meta=run(['adb','-s','emulator-5554','shell',command],limit=limit,seconds=min(1,remaining))
        if meta.get('capped') or len(raw)>=limit: return state('TRUNCATED')
        if meta.get('exit_code')==44: return state('UNREADABLE')
        if command==PCI and meta.get('exit_code')==46: return state('COMMAND_FAILED',reason='PCI_BDF_LIMIT')
        if meta.get('exit_code')!=0 or meta.get('eof') is not True or meta.get('status')!='AVAILABLE': return state('COMMAND_FAILED')
        if clock()>deadline: return state('COMMAND_FAILED',reason='TOTAL_BUDGET')
        try: result=parser(raw.decode('utf-8','strict'))
        except (UnicodeError,ValueError): return state('UNRECOGNISED')
        return result
    except Exception: return state('COMMAND_FAILED',reason='RUNNER_EXCEPTION')


def file_command(path):
    if path not in (CARDS,PCM,'/proc/version') and not CAPTURE.fullmatch(path): raise ValueError('PATH_NOT_ALLOWED')
    return '[ -r '+path+' ] || exit 44; cat '+path


def collect(run, deadline, clock=time.monotonic):
    # deadline is supplied by the guarded caller; collection cannot extend it.
    def read(cmd, parser, limit=4096): return read_row(run,cmd,parser,deadline,limit,clock)
    files={p:read(file_command(p),lambda t,p=p:alsa(p,t)) for p in (CARDS,PCM)}
    def capture_paths(text):
        paths=text.splitlines()
        if len(paths)>32 or len(set(paths))!=len(paths) or any(not CAPTURE.fullmatch(p) for p in paths): return state('UNRECOGNISED')
        return state('PARSED',paths=paths) if paths else state('EMPTY')
    paths=read(PATHS,capture_paths)
    row=dict(mode='METADATA_ONLY',fixture_authorization=False,alsa=files,capture_path_inventory=paths,
        kernel_release=read('uname -r',lambda t:kernel('release',t),2048),
        proc_version=read(file_command('/proc/version'),lambda t:kernel('version',t),2048),
        pci_audio=read(PCI,pci,8192),card_links=read(LINKS,card_links),
        snd_hda_intel=read(MODULE,lambda t:state('PARSED',present=t=='PRESENT') if t in ('PRESENT','ABSENT') else state('UNRECOGNISED'),128))
    # Enumeration first; optional per-stream details cannot starve kernel/PCI facts.
    for path in paths.get('paths',[]): files[path]=read(file_command(path),lambda t,p=path:alsa(p,t),2048)
    devices={d['bdf']:d for d in row['pci_audio'].get('devices',[])}
    row['card_pci_associations']=[dict(**link,pci_audio_present=link['bdf'] in devices) for link in row['card_links'].get('links',[])]
    return row
