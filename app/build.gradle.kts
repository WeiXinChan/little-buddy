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
androidComponents {
    onVariants(selector().withBuildType("release")) { variant ->
        variant.outputs.forEach { output ->
            if (releaseVersionCode.isPresent) {
                output.versionCode.set(releaseVersionCode)
                output.versionName.set(releaseVersionName)
            }
        }
    }
}

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
            applicationIdSuffix = ".v2"
            versionNameSuffix = "-v2-m04"
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
    androidTestImplementation("androidx.test:runner:1.6.2")
}
