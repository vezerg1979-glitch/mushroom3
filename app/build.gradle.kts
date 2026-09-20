import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}
val localSecrets = Properties().apply {
    val path = rootProject.file("supabase.properties")
    if (path.exists()) path.inputStream().use { load(it) }
}
fun cloudValue(env: String, prop: String): String =
    (System.getenv(env) ?: localSecrets.getProperty(prop) ?: "").trim()

android {
    buildFeatures { buildConfig = true }

    namespace = "ru.gortenziya.moisad"
    compileSdk = 35
    defaultConfig {
        applicationId = "ru.gortenziya.moisad"
        minSdk = 23
        targetSdk = 34
        versionCode = 5
        versionName = "1.4.0"
        buildConfigField("String", "SUPABASE_URL", "\"${cloudValue("SUPABASE_URL", "SUPABASE_URL").replace("\\", "\\\\").replace("\"", "\\\"")}\"")
        buildConfigField("String", "SUPABASE_ANON_KEY", "\"${cloudValue("SUPABASE_ANON_KEY", "SUPABASE_ANON_KEY").replace("\\", "\\\\").replace("\"", "\\\"")}\"")
    }
    buildTypes { release { isMinifyEnabled = false } }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
