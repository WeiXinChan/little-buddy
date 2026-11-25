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
sources = [source / "ParentDomain.kt", source / "ParentCodec.kt", source / "ParentEnvelope.kt",
           source / "SealedParentStore.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ParentDomainTest.kt",
           ROOT / "app/src/test/java/com/littlebuddy/v2/parent/ParentKeyStoreTest.kt"]
android = os.environ.get("PARENT_ANDROID_JAR")
if android:
    sources.append(source / "AndroidParentStore.kt")
    runtime.append(android)
with tempfile.TemporaryDirectory(prefix="parent-tests-", dir=ROOT) as output:
    negative = "--r86-key-loss-negative-control" in sys.argv
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
        if not negative and "--r86-only" not in sys.argv:
            tests.insert(0, "com.littlebuddy.v2.parent.ParentDomainTest")
        command = ["java", "-Xmx256m", "-cp", os.pathsep.join([output, *runtime]),
                   "org.junit.runner.JUnitCore", *tests]
        if negative:
            result = subprocess.run(command, text=True, capture_output=True)
            print(result.stdout, end="")
            print(result.stderr, end="")
            assert result.returncode == 1 and "Tests run: 11,  Failures: 2" in result.stdout
            print("R86 negative control: two key-loss regressions detected as expected")
        else:
            subprocess.run(command, check=True)
print("Android adapter: " + ("SDK compile only" if android else "NOT compiled (no PARENT_ANDROID_JAR)"))
