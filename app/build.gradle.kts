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
        versionCode = 1
        versionName = "0.1.0-sim"
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

dependencies { testImplementation("junit:junit:4.13.2") }
