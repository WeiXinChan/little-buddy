#!/usr/bin/env python3
"""Offline JVM checks using already cached Kotlin/JUnit, under with-build-lock.

No dependency downloads, APK, device, audio or production credentials required.
Optionally set PARENT_ANDROID_JAR to also compile the Android adapter against SDK.
"""
import glob
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
CACHE = Path.home() / ".gradle/caches/modules-2/files-2.1"


def jar(group, artifact, version):
    matches = glob.glob(str(CACHE / group / artifact / version / "*/*.jar"))
    if len(matches) != 1:
        raise SystemExit(f"Cached dependency unavailable: {artifact}:{version}")
    return matches[0]


compiler = [jar("org.jetbrains.kotlin", "kotlin-compiler-embeddable", "2.2.21"),
            jar("org.jetbrains.kotlin", "kotlin-stdlib", "2.2.21"),
            jar("org.jetbrains.kotlin", "kotlin-script-runtime", "2.2.21"),
            jar("org.jetbrains.kotlin", "kotlin-reflect", "1.6.10"),
            jar("org.jetbrains.kotlinx", "kotlinx-coroutines-core-jvm", "1.8.0"),
            jar("org.jetbrains", "annotations", "13.0")]
runtime = [compiler[1], jar("junit", "junit", "4.13.2"),
           jar("org.hamcrest", "hamcrest-core", "1.3")]
source = ROOT / "app/src/main/java/com/littlebuddy/v2/parent"
sources = [source / "PinDiagnostic.kt", source / "ParentDomain.kt", source / "ParentCodec.kt", source / "ParentEnvelope.kt",
           source / "SealedParentStore.kt", source / "ParentCommit.kt", source / "ParentPanelModel.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ParentDomainTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ParentKeyStoreTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/RevocationBoundaryTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ExtraKeyBoundaryTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/RevocationCommitTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/PreparedPublicationTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ExpiryCasTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ExpiryConfirmationTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ParentIntegrationTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ParentPanelModelTest.kt"]
sources += [source / "ParentFeedbackBinding.kt", source / "ParentRouteSlot.kt",
            ROOT / "app/src/main/java/com/littlebuddy/v2/feedback/FeedbackAuthority.kt",
            ROOT / "app/src/main/java/com/littlebuddy/v2/feedback/Contracts.kt"]
android = os.environ.get("PARENT_ANDROID_JAR")
if android:
    sources.append(source / "AndroidParentStore.kt")
    sources += [source / "ParentRoutes.kt", source / "ParentPanelView.kt", source / "AndroidParentPanel.kt",
                ROOT / "app/src/main/java/com/littlebuddy/v2/V2EyesView.kt"]
    sources += [p for p in (ROOT / "app/src/main/java/com/littlebuddy/v2/feedback").glob("*.kt")
                if p not in sources]
    runtime.append(android)
with tempfile.TemporaryDirectory(prefix="parent-tests-", dir=ROOT) as output:
    composition = "--composition-only" in sys.argv
    combined = "--combined" in sys.argv
    repair = "--r86-04" in sys.argv
    binding_mutant = next((arg.split("=", 1)[1] for arg in sys.argv if arg.startswith("--binding-mutant=")), None)
    if composition or binding_mutant or combined or repair:
        sources.append(ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ParentFeedbackCompositionTest.kt")
        sources.append(ROOT / "app/src/test/java/com/littlebuddy/v2/parent/IndependentCompositionTest.kt")
        sources.append(ROOT / "app/src/test/java/com/littlebuddy/v2/parent/RecoveryBoundaryTest.kt")
        sources.append(ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ParentRouteSlotReentryTest.kt")
        sources += [p for p in (ROOT / "app/src/main/java/com/littlebuddy/v2/feedback").glob("*.kt")
                    if p not in sources and p.name in {"Contracts.kt", "Vault.kt", "FeedbackCore.kt", "FeedbackAuthority.kt", "FeedbackEngine.kt"}]
    if combined:
        sources += list((ROOT / "app/src/test/java/com/littlebuddy/v2/feedback").glob("*.kt"))
    binding_case = {"borrow": "bindingGateRejectsForeignDomainAndNewGrantOnOldBinding",
                    "scope": "returnRotatesGrantBeforeOldCloseAndSettingsStillSaves",
                    "expiry": "expiryDuringStagingRejectsAtFinalGateEvenWithoutHostTick",
                    "recovery": "failedMountMustKeepRenderedCancelOperable",
                    "reentry": "factoryReentryMustNotOverwriteNewHandleOrLoseRelease",
                    "dispose-reentry": "oldCloseReentryPreemptsOuterFactoryBeforeConstruction"}
    if binding_mutant:
        runner = Path(output) / "BindingMutationRunner.kt"
        runner.write_text("""import org.junit.runner.JUnitCore
import org.junit.runner.Request
fun main(args: Array<String>) {
    val result = JUnitCore().run(Request.method(Class.forName(args[1]), args[0]))
    result.failures.forEach { println(it.toString() + "\\n" + it.trace) }
    println("RESULT ${result.runCount} ${result.failureCount} ${result.ignoreCount}")
    if (!result.wasSuccessful()) kotlin.system.exitProcess(1)
}
""")
        sources.append(runner)
        original = source / ("ParentRouteSlot.kt" if binding_mutant in {"reentry", "dispose-reentry"} else
                             "ParentPanelModel.kt" if binding_mutant == "recovery" else "ParentFeedbackBinding.kt")
        contents = original.read_text()
        if binding_mutant == "reentry":
            contents = subprocess.check_output(["git", "show", "29317ba8a3ae7b4f7c32b6e458b8c2aaf92293c0:app/src/main/java/com/littlebuddy/v2/parent/ParentRouteSlot.kt"], cwd=ROOT, text=True)
        elif binding_mutant == "dispose-reentry":
            checked = "owner = next // reserve before old disposal; a later reentrant request wins\n        retire(old)"
            assert contents.count(checked) == 1
            contents = contents.replace(checked, "retire(old)\n        owner = next")
        elif binding_mutant == "borrow":
            contents = contents.replace("token !== grant || ", "").replace("domain.acceptProtected(grant)", "domain.acceptProtected(token)")
        elif binding_mutant == "scope":
            contents = contents.replace("domain.revokePage(grant)", "domain.revoke()")
        elif binding_mutant == "recovery":
            checked = "if (revision.get() != retired || active) return\n        active = true"
            assert contents.count(checked) == 1
            contents = contents.replace(checked, "if (revision.get() != retired || active) return\n        active = false")
        elif binding_mutant == "expiry":
            contents = contents.replace("domain.acceptProtected(grant) {", "run {")
            contents = contents.replace("if (alive.get()) { decision(); published = true }", "if (alive.get()) { decision(); published = true }; true")
        else:
            raise SystemExit("unknown binding mutant")
        mutant = Path(output) / original.name
        mutant.write_text(contents)
        sources[sources.index(original)] = mutant
    negative = "--r86-key-loss-negative-control" in sys.argv
    revoke_negative = "--r86-revoke-negative-control" in sys.argv
    expiry_negative = "--r86-expiry-negative-control" in sys.argv
    ui_negative = "--ui-stale-view-negative-control" in sys.argv
    if ui_negative:
        original = source / "ParentPanelModel.kt"
        contents = original.read_text()
        checked = "if (!active || token != viewRevision.get()) return false"
        assert contents.count(checked) == 1
        mutant = Path(output) / original.name
        mutant.write_text(contents.replace(checked, "if (!active) return false"))
        sources[sources.index(original)] = mutant
    if expiry_negative:
        original = source / "ParentCommit.kt"
        contents = original.read_text()
        checked = "if (!confirm()) reject()"
        assert contents.count(checked) == 1
        mutant = Path(output) / original.name
        mutant.write_text(contents.replace(checked, "// post-CAS confirmation deliberately removed"))
        sources[sources.index(original)] = mutant
    if revoke_negative:
        original = source / "ParentDomain.kt"
        contents = original.read_text()
        checked = "fun revoke() { epoch.revoke() }"
        assert contents.count(checked) == 1
        mutant = Path(output) / original.name
        mutant.write_text(contents.replace(checked,
            "fun revoke() { worker.lock(); try { epoch.revoke() } finally { worker.unlock() } }"))
        sources[sources.index(original)] = mutant
    if negative:
        # Deliberately restore key regeneration in a TEMPORARY COPY, never production source.
        original = source / "SealedParentStore.kt"
        contents = original.read_text()
        checked = 'val existing = checkNotNull(keys.existing()) { "parent key unavailable" }'
        assert contents.count(checked) == 1
        mutant = Path(output) / original.name
        mutant.write_text(contents.replace(checked, "val existing = keys.existing() ?: keys.create()"))
        sources[sources.index(original)] = mutant
    subprocess.run(["java", "-Xmx512m", "-cp", os.pathsep.join(compiler),
                    "org.jetbrains.kotlin.cli.jvm.K2JVMCompiler", "-no-stdlib", "-no-reflect",
                    "-jvm-target", "17", "-classpath", os.pathsep.join(runtime),
                    "-d", output, *map(str, sources)], check=True)
    if "--compile-only" not in sys.argv:
        tests = ["com.littlebuddy.v2.parent.ParentKeyStoreTest"]
        if composition or binding_mutant:
            tests = ["com.littlebuddy.v2.parent.ParentFeedbackCompositionTest", "com.littlebuddy.v2.parent.IndependentCompositionTest",
                     "com.littlebuddy.v2.parent.RecoveryBoundaryTest", "com.littlebuddy.v2.parent.ParentRouteSlotReentryTest"]
        elif ui_negative:
            tests = ["com.littlebuddy.v2.parent.ParentPanelModelTest"]
        elif expiry_negative:
            tests = ["com.littlebuddy.v2.parent.ExpiryCasTest"]
        elif revoke_negative:
            tests = ["com.littlebuddy.v2.parent.RevocationBoundaryTest"]
        elif not negative and "--r86-only" not in sys.argv:
            tests.insert(0, "com.littlebuddy.v2.parent.ParentDomainTest")
            tests += ["com.littlebuddy.v2.parent.ExtraKeyBoundaryTest",
                      "com.littlebuddy.v2.parent.RevocationBoundaryTest",
                      "com.littlebuddy.v2.parent.RevocationCommitTest",
                      "com.littlebuddy.v2.parent.PreparedPublicationTest",
                      "com.littlebuddy.v2.parent.ExpiryCasTest",
                      "com.littlebuddy.v2.parent.ExpiryConfirmationTest",
                      "com.littlebuddy.v2.parent.ParentIntegrationTest",
                      "com.littlebuddy.v2.parent.ParentPanelModelTest"]
        if combined or repair:
            tests += ["com.littlebuddy.v2.parent.ParentFeedbackCompositionTest", "com.littlebuddy.v2.parent.IndependentCompositionTest",
                     "com.littlebuddy.v2.parent.RecoveryBoundaryTest", "com.littlebuddy.v2.parent.ParentRouteSlotReentryTest"]
        if combined:
            tests += ["com.littlebuddy.v2.feedback." + p.stem
                      for p in sorted((ROOT / "app/src/test/java/com/littlebuddy/v2/feedback").glob("*.kt"))]
        command = ["java", "-Xmx256m", "-cp", os.pathsep.join([output, *runtime]),
                   "org.junit.runner.JUnitCore", *tests]
        if binding_mutant:
            command = command[:-len(tests)-1] + ["BindingMutationRunnerKt", binding_case[binding_mutant],
                "com.littlebuddy.v2.parent." + ("RecoveryBoundaryTest" if binding_mutant == "reentry" else
                  "ParentRouteSlotReentryTest" if binding_mutant == "dispose-reentry" else "ParentFeedbackCompositionTest")]
        if negative or revoke_negative or expiry_negative or ui_negative or binding_mutant:
            result = subprocess.run(command, text=True, capture_output=True)
            print(result.stdout, end="")
            print(result.stderr, end="")
            expected = ("Tests run: 16,  Failures: 1" if ui_negative else
                        "Tests run: 2,  Failures: 1" if revoke_negative or expiry_negative else "Tests run: 11,  Failures: 2")
            if binding_mutant:
                target = binding_case[binding_mutant]
                assert result.returncode == 1 and target in result.stdout and "RESULT 1 1 0" in result.stdout
                expected = "binding " + binding_mutant + " detected by " + target
            else:
                assert result.returncode == 1 and expected in result.stdout
            print("R86 negative control detected as expected: " + expected)
        else:
            subprocess.run(command, check=True)
print("Android adapter: " + ("SDK compile only" if android else "NOT compiled (no PARENT_ANDROID_JAR)"))
