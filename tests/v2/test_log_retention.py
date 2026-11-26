"""Temporary metadata archives and command stand-ins, never system journal actions."""
from contextlib import redirect_stdout,redirect_stderr
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import time
import unittest
from unittest.mock import patch
from backend.v2.release import LOG_POLICY_FILES,verify,selected

ROOT=Path(__file__).resolve().parents[2]
def load(name,file):
    spec=importlib.util.spec_from_file_location(name,ROOT/'backend/deploy'/file)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
LOG=load('log_fixture','v2-log-retention.py');CONTROL=load('log_control_fixture','v2-control.py')

class Archives:
    """A stand-in for journalctl's archived-file semantics, not actual journald."""
    def __init__(self,path,now):self.path=path;self.now=now;self.calls=[];self.fail=False;self.rotate_count=0
    def archive(self,name,first,last):
        (self.path/(name+'.archive')).write_text(json.dumps(dict(first=first,last=last)))
    def execute(self,args):
        self.calls.append(tuple(args))
        if args[0]=='/usr/bin/systemd-analyze':return (ROOT/'backend/deploy/v2-journald.conf').read_text()
        if args[0]=='/usr/bin/systemctl':return '\n'.join(['LogNamespace=little-buddy-v2','SyslogIdentifier=little-buddy-v2',
            'StandardOutput=journal','StandardError=journal',
            'Requires=little-buddy-v2-log-retention.service little-buddy-v2-log-retention.timer','After=little-buddy-v2-log-retention.service'])
        assert args[0]=='/usr/bin/journalctl' and '--namespace=little-buddy-v2' in args
        assert not any(a.startswith(('--directory','--file','--root','--namespace=*','--namespace=+')) for a in args)
        if '--rotate' in args:
            if self.fail:raise subprocess.CalledProcessError(1,args,stderr=b'PRIVATE_FAILURE')
            self.rotate_count+=1
            active=self.path/'active'
            if active.exists():active.rename(self.path/('rotate'+str(self.rotate_count)+'.archive'))
            for file in self.path.glob('*.archive'):
                if json.loads(file.read_text())['last']<self.now-6*LOG.DAY:file.unlink()
            return ''
        rows=[json.loads(p.read_text())['first'] for p in self.path.glob('*.archive')]
        until=next((a for a in args if a.startswith('--until=@')),None)
        if until is not None:rows=[t for t in rows if t<=float(until.split('@')[1])]
        return '' if not rows else json.dumps({'__REALTIME_TIMESTAMP':str(int(min(rows)*1000000)),
             '__CURSOR':'METADATA_ONLY','__MONOTONIC_TIMESTAMP':'10','_BOOT_ID':'SYNTHETIC'})+'\n'

class Retention(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup);self.path=Path(self.folder.name)
        self.now=20*LOG.DAY;self.fake=Archives(self.path,self.now)
    def invoke(self,argv):
        out,err=io.StringIO(),io.StringIO()
        with (patch.object(LOG,'checked_file'),patch.object(LOG,'execute',side_effect=self.fake.execute),
              patch.object(LOG.os,'geteuid',return_value=0),patch.object(LOG.time,'time',return_value=self.fake.now),
              redirect_stdout(out),redirect_stderr(err)):
            result=LOG.cli(argv)
        self.assertNotIn('PRIVATE',out.getvalue()+err.getvalue())
        return result,json.loads(out.getvalue())
    def test_check_is_read_only_and_every_mutating_command_has_exact_namespace(self):
        self.assertEqual(self.invoke(['check'])[0],0)
        self.assertTrue(all(c[0]!='/usr/bin/journalctl' for c in self.fake.calls))
        self.assertEqual(self.invoke(['sweep'])[0],0)
        commands=[c for c in self.fake.calls if c[0]=='/usr/bin/journalctl']
        self.assertEqual(len(commands),3)
        self.assertIn('--rotate',commands[0]);self.assertIn('--vacuum-time=6d',commands[0]);self.assertIn('--vacuum-size=32M',commands[0])
        self.assertIn('--output-fields=__REALTIME_TIMESTAMP',commands[1]);self.assertIn('--lines=+1',commands[2])
        self.assertIn('--until=@'+format(self.now-7*LOG.DAY+60,'.6f'),commands[1])
    def test_real_journal_sequence_metadata_is_accepted_but_message_is_rejected(self):
        row={'__REALTIME_TIMESTAMP':str(int((self.now-100)*1e6)),
             '__CURSOR':'metadata', '__MONOTONIC_TIMESTAMP':'10', '_BOOT_ID':'boot',
             '__SEQNUM':'1', '__SEQNUM_ID':'sequence'}
        for extra,expected in (({},0),({'MESSAGE':'PRIVATE'},2)):
            with (patch.object(LOG,'check'),patch.object(LOG.os,'geteuid',return_value=0),
                  patch.object(LOG.time,'time',return_value=self.now),
                  patch.object(LOG,'execute',side_effect=['','',json.dumps(row|extra)]),
                  redirect_stdout(io.StringIO()) as out):
                self.assertEqual(LOG.cli(['sweep']),expected)
            self.assertNotIn('PRIVATE',out.getvalue())

    def test_query_delay_crossing_deadline_cannot_return_success(self):
        clock=[self.now];entry=self.now-7*LOG.DAY+1
        def command(args):
            if '--rotate' in args:return ''
            if '--lines=1' in args:
                cutoff=float(next(a for a in args if a.startswith('--until=@')).split('@')[1])
                clock[0]+=2
                return json.dumps({'__REALTIME_TIMESTAMP':str(int(entry*1e6))}) if entry<=cutoff else ''
            return json.dumps({'__REALTIME_TIMESTAMP':str(int(clock[0]*1e6))})
        with patch.object(LOG,'check'),patch.object(LOG.os,'geteuid',return_value=0),patch.object(LOG.time,'time',side_effect=lambda:clock[0]),patch.object(LOG,'execute',side_effect=command):
            with self.assertRaises(LOG.Rejected) as caught:LOG.sweep()
        self.assertEqual(caught.exception.code,'retention_overdue')

    def test_clock_reversal_or_exhausted_observation_margin_fails_closed(self):
        for stamps in ([self.now,self.now-1], [self.now,self.now,self.now-1], [self.now,self.now,self.now+60]):
            with self.subTest(stamps=stamps),patch.object(LOG,'check'),patch.object(LOG.os,'geteuid',return_value=0),patch.object(LOG.time,'time',side_effect=stamps),patch.object(LOG,'execute',return_value=''):
                with self.assertRaises(LOG.Rejected) as caught:LOG.sweep()
                self.assertEqual(caught.exception.code,'clock_invalid')

    def test_receipt_uses_completion_age_and_conservative_margin_is_not_overdue(self):
        with patch.object(LOG,'check'),patch.object(LOG.os,'geteuid',return_value=0),patch.object(LOG.time,'time',side_effect=[self.now,self.now+2,self.now+4]),patch.object(LOG,'execute',side_effect=['','',json.dumps({'__REALTIME_TIMESTAMP':str(int((self.now-100)*1e6))})]):
            self.assertEqual(LOG.sweep()['oldest_age_seconds'],104)
        entry=self.now-7*LOG.DAY+30
        with patch.object(LOG,'check'),patch.object(LOG.os,'geteuid',return_value=0),patch.object(LOG.time,'time',return_value=self.now),patch.object(LOG,'execute',side_effect=['',json.dumps({'__REALTIME_TIMESTAMP':str(int(entry*1e6))}), '']):
            with self.assertRaises(LOG.Rejected) as caught:LOG.sweep()
            self.assertEqual(caught.exception.code,'retention_margin')

    def test_age_boundary_and_new_activity_never_renews_original_archive(self):
        self.fake.archive('old',self.now-8*LOG.DAY,self.now-7*LOG.DAY)
        self.fake.archive('recent',self.now-5*LOG.DAY,self.now-5*LOG.DAY)
        self.assertEqual(self.invoke(['sweep'])[0],0);self.assertFalse((self.path/'old.archive').exists())
        before=(self.path/'recent.archive').read_bytes()
        self.fake.now+=LOG.DAY
        self.fake.archive('new_activity',self.fake.now,self.fake.now)
        self.assertEqual(self.invoke(['sweep'])[0],0)
        self.assertEqual((self.path/'recent.archive').read_bytes(),before)
        self.fake.now+=1
        self.assertEqual(self.invoke(['sweep'])[0],0);self.assertFalse((self.path/'recent.archive').exists())
    def test_rotate_is_required_and_overdue_mixed_archive_cannot_claim_success(self):
        # File containing a 7-day-old entry and a recent tail won't be vacuumed
        # by newest-file-age. The independent oldest metadata gate must reject.
        (self.path/'active').write_text(json.dumps(dict(first=self.now-7*LOG.DAY,last=self.now)))
        code,report=self.invoke(['sweep']);self.assertEqual(code,2)
        self.assertEqual(report,{'v2_log_retention':'retention_overdue'});self.assertEqual(self.fake.rotate_count,1)
    def test_failure_and_recovery_do_not_write_success_receipt_or_change_original_time(self):
        self.fake.archive('expired',self.now-9*LOG.DAY,self.now-8*LOG.DAY)
        original=(self.path/'expired.archive').read_bytes();self.fake.fail=True
        code,report=self.invoke(['sweep']);self.assertEqual(code,2);self.assertEqual(report['v2_log_retention'],'sweep_failed')
        self.assertEqual((self.path/'expired.archive').read_bytes(),original)
        self.fake.fail=False;self.fake.now+=LOG.DAY
        code,report=self.invoke(['sweep']);self.assertEqual(code,0);self.assertFalse(report['all_copies_deleted'])
        self.assertFalse((self.path/'expired.archive').exists())
    def test_namespace_and_argument_injection_have_fixed_output_no_commands(self):
        for argv in (['sweep','--namespace','*'],['sweep','--namespace','+little-buddy-v2'],['sweep','--namespace','../PRIVATE'],
                     ['sweep','--directory','/PRIVATE'],['sweep','--file','/PRIVATE'],['sweep','--namespace','']):
            with self.subTest(argv=argv):
                code,report=self.invoke(argv);self.assertEqual(code,2);self.assertEqual(report,{'v2_log_retention':'arguments_invalid'})
        self.assertFalse(self.fake.calls)
    def test_effective_override_or_bad_route_blocks_before_any_vacuum(self):
        original=self.fake.execute
        for bad in ('ForwardToSyslog=yes','MaxRetentionSec=7day','ForwardToSocket=/PRIVATE'):
            def command(args):
                value=original(args)
                return value+'\n'+bad if args[0]=='/usr/bin/systemd-analyze' else value
            with patch.object(self.fake,'execute',side_effect=command):
                self.assertEqual(self.invoke(['sweep'])[1]['v2_log_retention'],'policy_invalid')
        self.assertFalse(any('--rotate' in c for c in self.fake.calls))
        def bad_route(args):
            result=original(args)
            return result.replace('LogNamespace=little-buddy-v2','LogNamespace=') if args[0]=='/usr/bin/systemctl' else result
        with patch.object(self.fake,'execute',side_effect=bad_route):
            self.assertEqual(self.invoke(['sweep'])[1]['v2_log_retention'],'route_invalid')
    def test_malformed_or_body_metadata_is_rejected_not_printed(self):
        original=self.fake.execute
        for value in ('not-json-PRIVATE','{"MESSAGE":"PRIVATE"}','{"__REALTIME_TIMESTAMP":true}',
                      '{"__REALTIME_TIMESTAMP":"-1"}',json.dumps({'__REALTIME_TIMESTAMP':str(int((self.now+100)*1000000))})):
            def command(args):return value if '--output=json' in args else original(args)
            with patch.object(self.fake,'execute',side_effect=command):
                code,report=self.invoke(['sweep']);self.assertEqual(code,2);self.assertEqual(report['v2_log_retention'],'metadata_invalid')
    def test_process_timeout_env_and_no_shell_or_raw_error_output(self):
        with patch.object(LOG.subprocess,'run',side_effect=subprocess.TimeoutExpired('PRIVATE',5)),redirect_stdout(io.StringIO()):
            with self.assertRaises(subprocess.TimeoutExpired):LOG.execute(['/usr/bin/journalctl','--namespace=little-buddy-v2'])
        with patch.object(LOG.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'')) as called:
            LOG.execute(['/usr/bin/systemd-analyze','cat-config','systemd/journald@little-buddy-v2.conf'])
        self.assertEqual(called.call_args.kwargs['timeout'],5);self.assertNotIn('shell',called.call_args.kwargs)
        self.assertNotIn('CREDENTIALS_DIRECTORY',called.call_args.kwargs['env'])

    def test_policy_permissions_symlink_hardlink_and_nonroot_unsafe_rejected(self):
        file=self.path/'config';file.write_text('safe');file.chmod(0o644)
        # A temporary /tmp ancestor is deliberately untrusted: production helper
        # must reject it rather than offer a directory override for testing.
        with self.assertRaises(LOG.Rejected):LOG.checked_file(file)
        link=self.path/'alias';link.symlink_to(file)
        with self.assertRaises(LOG.Rejected):LOG.checked_file(link)
        os.link(file,self.path/'hard')
        with self.assertRaises(LOG.Rejected):LOG.checked_file(file)

    def test_deploy_gate_and_timer_are_v2_only_and_remain_outside_current(self):
        helper=(ROOT/'backend/deploy/v2-log-retention.service').read_text();timer=(ROOT/'backend/deploy/v2-log-retention.timer').read_text()
        dropin=(ROOT/'backend/deploy/v2-log-retention.dropin.conf').read_text()
        self.assertIn('Persistent=true',timer);self.assertIn('OnCalendar=hourly',timer)
        self.assertIn('Before=little-buddy-v2.service',helper);self.assertIn('Requires=systemd-journald@little-buddy-v2.service',helper)
        self.assertIn('ExecStartPre=/usr/bin/python3 -B /opt/little-buddy-v2/log-policy/',dropin)
        self.assertIn('little-buddy-v2-log-retention.service little-buddy-v2-log-retention.timer',dropin)
        for text in (helper,timer,dropin):
            self.assertNotIn('/current/',text);self.assertNotIn('little-buddy-v1',text);self.assertNotIn('--namespace=*',text)
        self.assertNotIn('ReadWritePaths=/var/log/journal\n',helper)
        self.assertTrue(all(selected(path) for path in LOG_POLICY_FILES))
    def test_rollback_missing_or_mismatched_policy_rejected_before_select_or_stop(self):
        target=self.path/'release';target.mkdir();calls=[]
        with (patch.object(CONTROL,'checked_release',side_effect=ValueError('PRIVATE')),
              patch.object(CONTROL.os,'geteuid',return_value=0),patch.object(CONTROL,'run',side_effect=lambda *a,**k:calls.append(a)),
              patch.object(CONTROL,'select',side_effect=lambda *a:calls.append(a)),redirect_stdout(io.StringIO())):
            self.assertEqual(CONTROL.cli(['rollback','a'*40,'--apply']),2)
        self.assertEqual(calls,[])
        with self.assertRaises((ValueError,OSError)):CONTROL.checked_log_policy(target)

    def test_installed_policy_bytes_modes_and_real_check_command_are_required(self):
        target=self.path/'release';source=target/'backend/deploy';source.mkdir(parents=True)
        installed=self.path/'installed';installed.mkdir()
        mapping={}
        for name in CONTROL.LOG_FILES:
            shutil.copyfile(ROOT/'backend/deploy'/name,source/name)
            (installed/name).write_bytes((source/name).read_bytes());(installed/name).chmod(0o644)
            mapping[name]=installed/name
        original=Path.lstat
        def trusted(path):
            # Emulate root ownership and trusted ancestors in this isolated /tmp
            # fixture. Real byte/type/mode/link checks still execute; no host writes.
            info=original(path);values=list(info);values[4]=0
            if stat.S_ISDIR(info.st_mode):values[0]=stat.S_IFDIR|(stat.S_IMODE(info.st_mode)&~0o022)
            return os.stat_result(values)
        with patch.object(CONTROL,'LOG_FILES',mapping),patch.object(Path,'lstat',trusted),patch.object(CONTROL,'run') as command:
            CONTROL.checked_log_policy(target)
            self.assertEqual(command.call_args.args[0],['/usr/bin/python3','-B',str(mapping['v2-log-retention.py']),'check','--namespace','little-buddy-v2'])
            for changed in ('bytes','permissions','symlink','missing'):
                path=mapping['v2-journald.conf'];raw=(source/'v2-journald.conf').read_bytes()
                if changed=='bytes':path.write_text('ForwardToSyslog=yes')
                elif changed=='permissions':path.chmod(0o666)
                elif changed=='symlink':path.unlink();path.symlink_to(source/'v2-journald.conf')
                else:path.unlink()
                with self.assertRaises((ValueError,OSError)):CONTROL.checked_log_policy(target)
                if path.is_symlink():path.unlink()
                path.write_bytes(raw);path.chmod(0o644)
            self.assertEqual(command.call_count,1)

    def test_source_helper_permissions_positive_and_nonroot_sweep_never_vacuums(self):
        file=self.path/'config';file.write_text('safe');file.chmod(0o644);original=Path.lstat
        def trusted(path):
            info=original(path);values=list(info);values[4]=0
            if stat.S_ISDIR(info.st_mode):values[0]=stat.S_IFDIR|(stat.S_IMODE(info.st_mode)&~0o022)
            return os.stat_result(values)
        with patch.object(Path,'lstat',trusted):
            LOG.checked_file(file)
            file.chmod(0o640)
            with self.assertRaises(LOG.Rejected):LOG.checked_file(file)
        with patch.object(LOG,'check'),patch.object(LOG.os,'geteuid',return_value=1000),patch.object(LOG,'execute') as command:
            with self.assertRaises(LOG.Rejected) as failure:LOG.sweep()
            self.assertEqual(failure.exception.code,'root_required');command.assert_not_called()

    def test_expired_filter_is_checked_even_when_first_cursor_looks_recent(self):
        original=self.fake.execute
        def out_of_order(args):
            if '--lines=1' in args:return json.dumps({'__REALTIME_TIMESTAMP':str(int((self.now-8*LOG.DAY)*1000000))})
            if '--lines=+1' in args:return json.dumps({'__REALTIME_TIMESTAMP':str(int(self.now*1000000))})
            return original(args)
        with patch.object(self.fake,'execute',side_effect=out_of_order):
            code,report=self.invoke(['sweep']);self.assertEqual(code,2)
            self.assertEqual(report,{'v2_log_retention':'retention_overdue'})
