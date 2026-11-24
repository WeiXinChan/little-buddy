"""Durable stage journal for SHA-validated synthetic fixtures; never Android PCM."""
import json, subprocess, time, wave
from pathlib import Path

def play_fixture(path, metadata, directory=Path('render'), *, start=subprocess.Popen,
                 query=subprocess.run, sleep=time.sleep, monitor=False):
    directory.mkdir(parents=True, exist_ok=True)
    target=directory / ('mic-route-'+metadata['nonce']+'.json')
    journal=dict(metadata, event='synthetic_route', source=str(path), playback_exit=None, playback_pid=None, stages=[])
    playback=None
    host_monitor=None
    primary=None
    def save(stage, **fields):
        journal.update(fields)
        journal['stage']=stage
        journal['stages'].append(dict(stage=stage, unix_ns=time.time_ns(), monotonic_ns=time.monotonic_ns()))
        temp=target.with_suffix('.json.tmp')
        temp.write_text(json.dumps(journal, ensure_ascii=False, indent=2))
        temp.replace(target)
    def text(value):
        if isinstance(value, bytes):value=value.decode('utf-8', errors='replace')
        return value[-65536:] if value else ''
    save('before_fixture')  # exists even if WAV parsing or process creation fails
    try:
        with wave.open(str(path)) as wav:
            save('fixture_ready', fixture=dict(rate=wav.getframerate(), channels=wav.getnchannels(),
                 sample_bytes=wav.getsampwidth(), samples=wav.getnframes(), seconds=wav.getnframes()/wav.getframerate()))
        if monitor:
            save('before_host_monitor')
            try:
                from monitor_probe import MonitorProbe
                host_monitor=MonitorProbe(metadata,directory)
                save('host_monitor_started', host_monitor=host_monitor.info)
            except Exception as error:
                save('host_monitor_unavailable', host_monitor_error=type(error).__name__)
                # Optional host observation must not prevent the production guest experiment.
        save('before_playback')
        playback=start(['paplay','--device=m06_input',str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        save('playback_started', playback_pid=playback.pid)
        sleep(.2)
        for kind in ['clients','sources','source-outputs','sink-inputs']:
            save('query_'+kind, playback_poll=playback.poll())
            state=query(['pactl','-f','json','list',kind], capture_output=True, text=True, timeout=5)
            row=dict(exit=state.returncode, stdout=text(state.stdout), stderr=text(state.stderr),
                     unix_ns=time.time_ns(), monotonic_ns=time.monotonic_ns())
            journal[kind]=row
            save('received_'+kind)  # preserve raw output before JSON decoding
            state.check_returncode()
            row['data']=json.loads(state.stdout)
            save('parsed_'+kind)
        save('before_communicate', playback_poll=playback.poll())
        stdout,stderr=playback.communicate(timeout=20)
        save('playback_exited', playback_exit=playback.returncode, playback_stdout=text(stdout), playback_stderr=text(stderr))
        if playback.returncode:raise subprocess.CalledProcessError(playback.returncode, 'paplay', stdout, stderr)
        save('completed')
        return journal
    except BaseException as error:
        primary=error
        save('failed', failed_stage=journal['stage'], error=type(error).__name__, timeout=isinstance(error,subprocess.TimeoutExpired),
             failure_stdout=text(getattr(error,'stdout',None)), failure_stderr=text(getattr(error,'stderr',None)))
        raise
    finally:
        if host_monitor is not None:
            try:save('host_monitor_done', host_monitor=host_monitor.finish())
            except BaseException as error:
                save('host_monitor_failed', host_monitor_error=type(error).__name__)
                # Optional monitor cannot replace the guest/primary failure.
        if playback is not None:
            try:
                save('cleanup_begin', playback_poll=playback.poll())
                if playback.poll() is None:playback.terminate()
                try:stdout,stderr=playback.communicate(timeout=5)
                except subprocess.TimeoutExpired:
                    save('cleanup_kill', cleanup_timeout=True)
                    playback.kill();stdout,stderr=playback.communicate(timeout=5)
                save('cleanup_done', playback_exit=playback.returncode, playback_stdout=text(stdout), playback_stderr=text(stderr))
            except BaseException as cleanup:
                save('cleanup_failed', cleanup_error=type(cleanup).__name__)
                if primary is None:raise
