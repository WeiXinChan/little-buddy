plugins {
    id("com.android.application") version "8.13.2"
    id("org.jetbrains.kotlin.android") version "2.2.21"
}

android {
    namespace = "com.littlebuddy"
    compileSdk = 36
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "com.littlebuddy.sim"
        minSdk = 26
        targetSdk = 36
        versionCode = 6
        versionName = "0.1.5-voice-lab"
        testInstrumentationRunner = "com.littlebuddy.SimUiRunner"
    }
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
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation("junit:junit:4.13.2")
    androidTestImplementation("androidx.test:runner:1.6.2")
}
