#!/usr/bin/env python3
"""Compile the actual Kotlin core + JUnit using cached dependencies, without SDK/AVD/network.
Run under scripts/with-build-lock. All compilations are serial and use -Xmx768m.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(os.environ.get('GRADLE_USER_HOME', Path.home() / '.gradle')) / 'caches/modules-2/files-2.1'

def jar(group, artifact, version):
    found = list((CACHE / group / artifact / version).glob('*/*.jar'))
    if len(found) != 1:
        raise RuntimeError(f'Missing/ambiguous cached dependency: {group}:{artifact}:{version}')
    return str(found[0])

def run(command):
    result = subprocess.run(command, cwd=ROOT, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    print(result.stdout, end='', flush=True)
    return result.returncode, result.stdout

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--negative-controls', action='store_true')
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-ref', help='Read production sources from this immutable git revision')
    parser.add_argument('--case', help='Run exactly ClassName#method (preserves QA original assertion)')
    parser.add_argument('--android-jar', type=Path, help='Also compile Android factory using this existing jar')
    args = parser.parse_args()
    compiler = [jar('org.jetbrains.kotlin', name, version) for name, version in [
        ('kotlin-compiler-embeddable', '2.2.21'), ('kotlin-stdlib', '2.2.21'),
        ('kotlin-script-runtime', '2.2.21'), ('kotlin-reflect', '1.6.10'),
        ('kotlin-daemon-embeddable', '2.2.21')]]
    compiler += [jar('org.jetbrains.kotlinx', 'kotlinx-coroutines-core-jvm', '1.8.0'),
                 jar('org.jetbrains', 'annotations', '23.0.0')]
    runtime = [jar('org.jetbrains.kotlin', 'kotlin-stdlib', '2.2.21'),
               jar('junit', 'junit', '4.13.2'), jar('org.hamcrest', 'hamcrest-core', '1.3')]
    source_dir = ROOT / 'app/src/main/java/com/littlebuddy/v2/feedback'
    parent_dir = ROOT / 'app/src/main/java/com/littlebuddy/v2/parent'
    candidates = sorted(source_dir.glob('*.kt')) + sorted(parent_dir.glob('*.kt'))
    if args.source_ref:
        existing = set(subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', args.source_ref], cwd=ROOT, text=True).splitlines())
        candidates = [p for p in candidates if str(p.relative_to(ROOT)) in existing]
    android_sources = {'AndroidFeedbackVault.kt', 'AndroidFeedbackRuntime.kt', 'FeedbackPageFactory.kt', 'AndroidParentStore.kt'}
    sources = [p for p in candidates if args.android_jar or p.name not in android_sources]
    tests = sorted((ROOT / 'app/src/test/java/com/littlebuddy/v2/feedback').glob('*.kt'))
    if args.source_ref:
        if not args.case or '#' not in args.case:
            parser.error('--source-ref requires an explicit Class#method to avoid compiling newer dependent tests')
        tests = [p for p in tests if p.stem == args.case.split('#')[0]]
    source_bytes = {p: subprocess.check_output(['git', 'show', f'{args.source_ref}:{p.relative_to(ROOT)}'], cwd=ROOT)
                    if args.source_ref else p.read_bytes() for p in sources}
    if args.android_jar:
        runtime.append(str(args.android_jar.resolve()))
    jobs = [('baseline', None, None)]
    if args.negative_controls:
        jobs = [
            ('later-deadline', 'deadline', 'firstDayWithdrawalRejectsAtSecondDayBoundary'),
            ('missing-ledger', 'ledger', 'missingLedgerRejectsOldPreWithdrawalSnapshotL8701'),
            ('early-grant-submit', 'early-grant', 'staleGrantAfterBlockedDiskCannotAdmit'),
            ('early-grant-clear', 'early-grant', 'blockedClearRevocationPreservesDurableSourceLogs'),
            ('incomplete-deletion', 'delete', 'deleteFailureAndPartialReceiptNeverClaimAllCopiesDeleted'),
            ('expired-draft-copy', 'draft-expiry', 'Review39Probe#expiredSelectedDraftCopyMustBeReleasedBySweep'),
            ('route-borrows-new-grant', 'borrow-route', 'FeedbackFlowTest#routerDoesNotBorrowNewPageAuthorityForAlreadyRunningOldWork'),
            ('late-ui-restores-data', 'late-ui', 'FeedbackFlowTest#delayedUiCompletionAfterPauseCannotRestoreSensitiveSnapshot'),
            ('gate-boolean-without-decision', 'gate-boolean', 'FeedbackFlowTest#adapterCannotAcceptBooleanWithoutDecision'),
            ('expired-detail-cache', 'detail-cache', 'Review40Probe#systemSweepMustRetireDisplayedExpiredDetails'),
        ]
    report = {'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(source_bytes.get(p, p.read_bytes())).hexdigest()
                               for p in sources + tests}, 'results': [], 'source_ref': args.source_ref,
              'android_jar_sha256': hashlib.sha256(args.android_jar.read_bytes()).hexdigest() if args.android_jar else None,
              'scope': 'actual Kotlin core, synthetic clock/auth/provider, real files; no Android Keystore/device/platform'}
    build = ROOT / 'build/m09-core'; build.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='run-', dir=build) as temporary:
        directory = Path(temporary)
        runner = directory / 'Runner.kt'
        runner.write_text('''import org.junit.runner.JUnitCore
import org.junit.runner.Request
fun main(args: Array<String>) {
    val request = if (args[0] == "--method") Request.method(Class.forName(args[1]), args[2])
        else Request.classes(*args.map { Class.forName(it) }.toTypedArray())
    val result = JUnitCore().run(request)
    for (failure in result.failures) println(failure.toString() + "\\n" + failure.trace)
    println("RESULT ${result.runCount} ${result.failureCount} ${result.ignoreCount}")
    if (!result.wasSuccessful()) kotlin.system.exitProcess(1)
}
''')
        for name, mutant, method in jobs:
            job = directory / name; job.mkdir()
            copied = []
            for source in sources:
                value = source_bytes[source].decode()
                if mutant == 'deadline' and source.name == 'Contracts.kt':
                    value = value.replace('minOf(submitted?.plus(WEEK)', 'maxOf(submitted?.plus(WEEK)')
                if mutant == 'ledger' and source.name == 'Vault.kt':
                    value = value.replace('require(data != null && ledger != null)',
                                          'if (data != null && ledger == null) return crypt(data, false)\n            require(data != null && ledger != null)')
                if mutant == 'early-grant' and source.name == 'FeedbackCore.kt':
                    value = value.replace('val staged = vault.stage(candidate)', '''var oldBoolean = false
        authorizer.accept(intent, op, scope) { oldBoolean = true }
        val staged = vault.stage(candidate)''')
                    value = value.replace('authorizer.accept(intent, op, scope) {\n                // Irreversible',
                                          'if (oldBoolean) run {\n                // Irreversible')
                if mutant == 'delete' and source.name == 'FeedbackCore.kt':
                    value = value.replace('if (receipt.allCopiesDeleted) FeedbackState.DELETED else FeedbackState.DELETING',
                                          'FeedbackState.DELETED')
                if mutant == 'draft-expiry' and source.name == 'FeedbackCore.kt':
                    start = value.index('        // R87-01:')
                    end = value.index('        // End R87-01', start)
                    value = value[:start] + value[end:]
                if mutant == 'borrow-route' and source.name == 'FeedbackAuthority.kt':
                    value = value.replace('if (caller.get() !== owner) return null', '')
                if mutant == 'late-ui' and source.name == 'FeedbackEngine.kt':
                    value = value.replace('if (controller.matches(version)) {\n                    if (current(controller)) controller.deliverPending(version) else controller.pause()',
                                          'if (true) {\n                    controller.deliver(screen)')
                if mutant == 'detail-cache' and source.name == 'FeedbackEngine.kt':
                    value = value.replace('val previous = refresh ?: return', 'if (token == null) return\n        val previous = refresh ?: return')
                if mutant == 'gate-boolean' and source.name == 'FeedbackAuthority.kt':
                    value = value.replace('        gate.accept(domain, grant) {', '        val result = gate.accept(domain, grant) {')
                    value = value.replace('        return decided', '        if (result && !decided) { acceptance(); return true }\n        return decided')
                destination = job / source.name; destination.write_text(value); copied.append(str(destination))
            output = job / 'classes'
            code, _ = run(['java', '-Xmx768m', '-cp', os.pathsep.join(compiler),
                           'org.jetbrains.kotlin.cli.jvm.K2JVMCompiler', '-no-stdlib', '-no-reflect',
                           '-jvm-target', '17', '-classpath', os.pathsep.join(runtime), '-d', str(output)]
                          + copied + [str(test) for test in tests] + [str(runner)])
            if code:
                raise RuntimeError(f'{name}: compilation failed; NOT a valid negative-control detection')
            selected = args.case or method
            if selected:
                class_name, method_name = selected.split('#') if '#' in selected else ('FeedbackCoreTest', selected)
                cases = ['--method', 'com.littlebuddy.v2.feedback.' + class_name, method_name]
            else:
                cases = ['com.littlebuddy.v2.feedback.' + test.stem for test in tests]
            code, stdout = run(['java', '-Xmx256m', '-cp', os.pathsep.join([str(output)] + runtime),
                                'RunnerKt'] + cases)
            result_line = next(line for line in stdout.splitlines() if line.startswith('RESULT '))
            count, failures, skipped = map(int, result_line.split()[1:])
            success = (code != 0 and failures > 0 and count == 1) if mutant else code == 0 and failures == 0
            report['results'].append(dict(name=name, tests=count, failures=failures, skipped=skipped,
                                          expected_failure=bool(mutant), detected=success))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if all(row['detected'] for row in report['results']) else 1

if __name__ == '__main__':
    raise SystemExit(main())
