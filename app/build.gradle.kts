import groovy.json.JsonSlurper
import java.nio.ByteBuffer
import java.security.MessageDigest
import java.security.cert.CertificateFactory
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.Properties

plugins {
    id("com.android.application") version "8.13.2"
    id("org.jetbrains.kotlin.android") version "2.2.21"
}

val releaseVersionCode = providers.gradleProperty("buddyVersionCode").map {
    require((it.toIntOrNull() ?: 0) in 15..2_100_000_000) { "buddyVersionCode must be between 15 and 2100000000" }
    it.toInt()
}
val releaseVersionName = providers.gradleProperty("buddyVersionName").map {
    require(it.matches(Regex("[0-9]+[.][0-9]+[.][0-9]+(?:-[a-zA-Z0-9.]+)?"))) {
        "buddyVersionName must be a semantic version"
    }
    it
}
require(releaseVersionCode.isPresent == releaseVersionName.isPresent) {
    "Provide buddyVersionCode and buddyVersionName together"
}
val v2Release = JsonSlurper().parse(file("v2-release.json")) as Map<*, *>
val v2Code = (v2Release["version_code"] as Number).toInt()
val pinDiagnostics = providers.gradleProperty("pinInitDiagnostics").orNull == "true"
val privateDevicePreset = providers.gradleProperty("privateDevicePreset").orNull == "true"
require(!privateDevicePreset || pinDiagnostics) { "Private device candidate requires explicit diagnostic candidate mode" }
val v2Name = (v2Release["version_name"] as String) +
    if (privateDevicePreset) ".pin.fix3.device1" else if (pinDiagnostics) ".pin.fix2" else ""
require(v2Code >= 15 && v2Name.matches(Regex("[0-9]+[.][0-9]+[.][0-9]+(?:-[a-zA-Z0-9.]+)?")))
androidComponents {
    onVariants(selector().withBuildType("v2Debug")) { variant ->
        variant.outputs.forEach { it.versionCode.set(v2Code); it.versionName.set(v2Name) }
    }
    onVariants(selector().withBuildType("release")) { variant ->
        variant.outputs.forEach { output ->
            if (releaseVersionCode.isPresent) {
                output.versionCode.set(releaseVersionCode)
                output.versionName.set(releaseVersionName)
            }
        }
    }
}

val v2Metadata = layout.buildDirectory.dir("generated/v2-release")
val prepareV2Metadata by tasks.registering(Exec::class) {
    workingDir(rootProject.projectDir)
    inputs.files(rootProject.fileTree("app/src") { exclude("test/**", "androidTest/**", "release/**") },
        rootProject.fileTree("assets/v2-default"),rootProject.fileTree("app/libs"),
        rootProject.fileTree("gradle/wrapper"),rootProject.file("app/v2-release.json"),
        rootProject.file("app/build.gradle.kts"),rootProject.file("scripts/v2-build-metadata.py"),
        rootProject.file("settings.gradle.kts"),rootProject.file("gradle.properties"))
    inputs.property("pinInitDiagnostics", pinDiagnostics)
    inputs.property("privateDevicePreset", privateDevicePreset)
    outputs.dir(v2Metadata)
    val arguments = mutableListOf("python3", "scripts/v2-build-metadata.py", "--output", v2Metadata.get().asFile.absolutePath)
    if (pinDiagnostics) arguments.add("--pin-init-diagnostics")
    if (privateDevicePreset) arguments.add("--private-device-preset")
    commandLine(arguments)
}
tasks.matching { it.name == "preV2DebugBuild" }.configureEach { dependsOn(prepareV2Metadata) }

// Local issued credential is deliberately outside tracked sources/public source inventory.
val privatePresetAssets = layout.buildDirectory.dir("generated/private-device-assets")
val preparePrivatePreset by tasks.registering(Copy::class) {
    onlyIf { privateDevicePreset }
    from(rootProject.file(".private-device/preset.bin")) { rename { "v2-device-preset.bin" } }
    into(privatePresetAssets)
    fileMode = 384; dirMode = 448 // 0600 / 0700
    doFirst { require(rootProject.file(".private-device/preset.bin").isFile) { "Private device input unavailable" } }
}
if (privateDevicePreset) tasks.matching { it.name == "preV2DebugBuild" }.configureEach { dependsOn(preparePrivatePreset) }

val imageAssets = layout.buildDirectory.dir("generated/v2-images")
val prepareV2Images by tasks.registering(Sync::class) {
    from(rootProject.file("assets")) { include("v2-default/manifest.json", "v2-default/png/*.png") }
    into(imageAssets)
    doFirst {
        val directory = rootProject.file("assets/v2-default")
        val rows = JsonSlurper().parse(directory.resolve("manifest.json")) as List<*>
        require(rows.size == 60)
        val ids = mutableSetOf<String>()
        for (row in rows) {
            val item = row as Map<*, *>
            val id = item["id"] as String
            require(id.matches(Regex("[a-z0-9-]{1,64}")) && ids.add(id))
            require(item["png"] == "png/$id.png" && item["width"] == 512 && item["height"] == 512)
            val bytes = directory.resolve("png/$id.png").readBytes()
            require(bytes.size in 24..1_048_576)
            val sha = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
            require(sha == item["png_sha256"]) { "Bundled image hash mismatch: $id" }
            require(bytes.take(8) == listOf(137,80,78,71,13,10,26,10).map { it.toByte() })
            val dimensions = ByteBuffer.wrap(bytes, 16, 8)
            require(dimensions.int == 512 && dimensions.int == 512)
        }
    }
}
tasks.matching { it.name == "preV2DebugBuild" }.configureEach { dependsOn(prepareV2Images) }

val wakeProbe = providers.gradleProperty("wakeProbe").map(String::toBoolean).orElse(false)
val familyPrompt = providers.environmentVariable("LITTLE_BUDDY_FAMILY_PROMPT")
val familyAssets = layout.buildDirectory.dir("generated/family-wake-assets")
val probeRes = layout.buildDirectory.dir("generated/wake-probe-res")

val prepareFamilyWake by tasks.registering {
    inputs.property("inputPath", familyPrompt.orElse(""))
    inputs.files(familyPrompt.map { listOf(file(it)) }.orElse(emptyList()))
    outputs.dir(familyAssets)
    doLast {
        val input = familyPrompt.orNull?.let(::file)
        require(input != null && input.isFile && !input.canonicalFile.toPath().startsWith(rootDir.canonicalFile.toPath())) {
            "Set LITTLE_BUDDY_FAMILY_PROMPT to the controlled PCM file outside the checkout"
        }
        require(input.length() == 96_960L) { "Family wake prompt size mismatch" }
        val pcm = input.readBytes()
        val digest = MessageDigest.getInstance("SHA-256").digest(pcm).joinToString("") { "%02x".format(it) }
        require(digest == "90eac1536ac74f27a1a9e9983d0db781097f97342c037d68cf9840d84f0b6a3f") {
            "Family wake prompt SHA-256 mismatch"
        }
        familyAssets.get().file("wake/prompt.pcm").asFile.apply {
            parentFile.mkdirs()
            writeBytes(pcm)
        }
    }
}

val sshProfile = providers.environmentVariable("LITTLE_BUDDY_SSH_PROFILE")
val sshAssets = layout.buildDirectory.dir("generated/ssh-transport-assets")
val prepareSshProfile by tasks.registering {
    inputs.files(sshProfile.map { listOf(file(it)) }.orElse(emptyList()))
    inputs.property("versionCode", releaseVersionCode.orElse(0))
    outputs.dir(sshAssets)
    doLast {
        require(releaseVersionCode.isPresent) { "Register a new buddyVersionCode and buddyVersionName for this release" }
        val profileDir = sshProfile.orNull?.let(::file)
        require(profileDir != null && profileDir.isDirectory) {
            "Set LITTLE_BUDDY_SSH_PROFILE to the directory containing ssh.properties and ca.pem"
        }
        val settings = Properties().apply {
            profileDir.resolve("ssh.properties").inputStream().use { load(it) }
        }
        require(settings.keys == setOf("host", "user", "hostKey"))
        val (host, user, key) = listOf("host", "user", "hostKey").map(settings::getProperty)
        val octets = host.split(".")
        require(octets.size == 4 && octets.all {
            val value = it.toIntOrNull()
            value != null && value in 0..255 && value.toString() == it
        }) { "Use the verified SSH server IPv4 address" }
        require(user.matches(Regex("[a-z_][a-z0-9_-]{0,30}")) && user != "root")
        val digest = MessageDigest.getInstance("SHA-256").digest(Base64.getDecoder().decode(key))
        require(Base64.getEncoder().withoutPadding().encodeToString(digest) ==
            "Z9Ty3OFZtTBeTMIS9iRfGhOIRaTJ0eRzxaMSxeggliI") { "SSH host key does not match the verified server" }

        val ca = profileDir.resolve("ca.pem").readText().trim()
        require(ca.matches(Regex("-----BEGIN CERTIFICATE-----[\\r\\nA-Za-z0-9+/=]+-----END CERTIFICATE-----")))
        val certificate = CertificateFactory.getInstance("X.509")
            .generateCertificate(ca.byteInputStream()) as X509Certificate
        require(certificate.basicConstraints >= 0) { "Use the project CA public certificate" }
        certificate.checkValidity()
        val destination = sshAssets.get().dir("transport").asFile
        destination.mkdirs()
        destination.resolve("ssh.properties").writeText("host=$host\nuser=$user\nhostKey=$key\n")
        destination.resolve("ca.pem").writeText(ca)
    }
}
tasks.matching { it.name == "preReleaseBuild" }.configureEach { dependsOn(prepareSshProfile) }

if (wakeProbe.get()) {
    val caPath = providers.gradleProperty("wakeProbeCa")
    val prepareWakeProbeTls by tasks.registering {
        inputs.files(caPath.map { listOf(file(it)) }.orElse(emptyList()))
        outputs.dir(probeRes)
        doLast {
            val certificate = caPath.orNull?.let(::file)
            require(certificate != null && certificate.isFile) { "Provide -PwakeProbeCa with the loopback fixture CA" }
            val raw = probeRes.get().file("raw/wake_probe_ca.pem").asFile
            raw.parentFile.mkdirs()
            certificate.copyTo(raw, overwrite = true)
            val xml = probeRes.get().file("xml/wake_probe_network_security.xml").asFile
            xml.parentFile.mkdirs()
            xml.writeText("""
                <network-security-config>
                    <domain-config cleartextTrafficPermitted="false">
                        <domain>localhost</domain>
                        <domain>127.0.0.1</domain>
                        <trust-anchors><certificates src="@raw/wake_probe_ca" /></trust-anchors>
                    </domain-config>
                </network-security-config>
            """.trimIndent())
        }
    }
    tasks.matching { it.name == "preDebugBuild" }.configureEach { dependsOn(prepareWakeProbeTls) }
}
tasks.matching { it.name == "preReleaseBuild" }.configureEach { dependsOn(prepareFamilyWake) }

android {
    buildFeatures.buildConfig = true
    namespace = "com.littlebuddy"
    compileSdk = 36
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "com.littlebuddy.sim"
        minSdk = 26
        targetSdk = 36
        versionCode = 13
        versionName = "0.1.12-animal-private"
        buildConfigField("boolean", "PIN_INIT_DIAGNOSTICS", "false")
        buildConfigField("boolean", "V2_DEVICE_PRESET", "false")
        buildConfigField("boolean", "BUDDY_SSH", "false")
        testInstrumentationRunner = "com.littlebuddy.SimUiRunner"
    }
    testBuildType = if (providers.gradleProperty("v2Test").isPresent) "v2Debug" else "debug"
    buildTypes {
        val release = getByName("release") {
            buildConfigField("boolean", "BUDDY_SSH", "true")
            ndk.abiFilters += "arm64-v8a"
        }
        create("v2Debug") {
            initWith(getByName("debug"))
            buildConfigField("boolean", "PIN_INIT_DIAGNOSTICS", pinDiagnostics.toString())
            buildConfigField("boolean", "V2_DEVICE_PRESET", privateDevicePreset.toString())
            applicationIdSuffix = ".v2"
            ndk.abiFilters += "arm64-v8a"
            matchingFallbacks += "debug"
        }
        create("ciRelease") {
            initWith(release)
            buildConfigField("boolean", "BUDDY_SSH", "false")
            applicationIdSuffix = ".ci"
        }
        getByName("debug") {
            if (wakeProbe.get()) {
                applicationIdSuffix = ".wakeprobe"
                ndk.abiFilters += "arm64-v8a"
            }
            manifestPlaceholders["debugVoiceSecurity"] =
                if (wakeProbe.get()) "wake_probe_network_security" else "voice_debug_network_security"
        }
    }
    sourceSets {
        getByName("release").assets.srcDirs(familyAssets, sshAssets)
        getByName("v2Debug") {
            java.srcDir("src/debug/java")
            res.srcDir("src/debug/res")
            assets.srcDir("src/debug/assets")
            assets.srcDir(imageAssets)
            assets.srcDir(v2Metadata)
            if (privateDevicePreset) assets.srcDir(privatePresetAssets)
        }
        getByName("ciRelease") {
            java.srcDir("src/release/java")
            manifest.srcFile("src/release/AndroidManifest.xml")
            assets.srcDir("src/debug/assets")
        }
        if (wakeProbe.get()) getByName("debug").res.srcDir(probeRes)
    }
    packaging.resources.excludes += "META-INF/versions/**"
    packaging.jniLibs.excludes += setOf("**/libsherpa-onnx-c-api.so", "**/libsherpa-onnx-cxx-api.so")
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    testOptions.unitTests.all {
        it.maxHeapSize = "256m"
        it.maxParallelForks = 1
    }
}

kotlin { jvmToolchain(17) }

dependencies {
    implementation(files("libs/sherpa-onnx-1.12.27.aar"))
    implementation("com.github.mwiede:jsch:2.28.8") {
        version { strictly("2.28.8") }
    }
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    testImplementation("com.google.code.gson:gson:2.11.0") { isTransitive = false } // JVM-only JSON ports; cached standalone jar
    androidTestImplementation("androidx.test:runner:1.6.2")
}
