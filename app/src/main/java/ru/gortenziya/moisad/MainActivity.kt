package ru.gortenziya.moisad

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.net.Uri
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Build
import android.os.Bundle
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.Toast
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.UUID

/** Offline diary + explicitly opted-in photo album. No broad gallery permissions. */
class MainActivity : Activity() {
    private lateinit var web: WebView
    private lateinit var cloudAlbum: CloudAlbum
    private val exportRequest = 501
    private val importRequest = 502
    private val notificationRequest = 503
    private val photoRequest = 504
    private var pendingExport = ""
    private var pendingPlant = ""
    private val photos by lazy { File(filesDir, "garden_photos").also { it.mkdirs() } }
    private val photoIdPattern = Regex("[a-f0-9-]{36}")

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        cloudAlbum = CloudAlbum(this)
        window.statusBarColor = Color.rgb(247, 247, 242)
        window.navigationBarColor = Color.WHITE
        window.decorView.systemUiVisibility = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR or android.view.View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR
        else android.view.View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true
        web.settings.allowFileAccess = true // Only our packaged local UI is loaded.
        web.settings.allowContentAccess = false
        web.settings.cacheMode = WebSettings.LOAD_NO_CACHE
        web.settings.mixedContentMode = WebSettings.MIXED_CONTENT_NEVER_ALLOW
        web.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView?, request: WebResourceRequest?): Boolean =
                request?.url.toString() != "file:///android_asset/index.html"
            @Deprecated("Android 6 compatibility")
            override fun shouldOverrideUrlLoading(view: WebView?, url: String?): Boolean =
                url != "file:///android_asset/index.html"
            override fun shouldInterceptRequest(view: WebView?, request: WebResourceRequest?): WebResourceResponse? {
                val uri = request?.url ?: return null
                if (uri.scheme == "https" && uri.host == "garden.local" && uri.path?.startsWith("/photo/") == true) {
                    val id = uri.lastPathSegment?.removeSuffix(".jpg") ?: ""
                    if (!photoIdPattern.matches(id) || uri.lastPathSegment != "$id.jpg") return WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", mapOf(), "".byteInputStream())
                    val f = File(photos, "$id.jpg")
                    if (!f.isFile) return WebResourceResponse("text/plain", "UTF-8", 404, "Not Found", mapOf(), "".byteInputStream())
                    return WebResourceResponse("image/jpeg", null, 200, "OK", mapOf("Cache-Control" to "no-store"), f.inputStream())
                }
                return null
            }
        }
        web.addJavascriptInterface(Bridge(), "GardenAndroid")
        setContentView(web)
        web.loadUrl("file:///android_asset/index.html")
        if (ReminderReceiver.isEnabled(this)) ReminderReceiver.schedule(this)
    }

    private fun js(method: String, vararg args: String) {
        runOnUiThread { if (::web.isInitialized) web.evaluateJavascript(
            "window.$method && window.$method(${args.joinToString(",") { JSONObject.quote(it) }});", null) }
    }

    inner class Bridge {
        @JavascriptInterface fun cloudConfigured() = cloudAlbum.configured
        @JavascriptInterface fun cloud(action: String, payload: String, requestId: String) {
            if (!Regex("r[0-9]{1,8}").matches(requestId) || payload.length > 3000) return
            Thread {
                val result = try {
                    val value=cloudAlbum.execute(action, JSONObject(payload), photos)
                    value.put("ok", true)
                } catch (e: Exception) {
                    JSONObject().put("ok", false).put("error", e.message?.take(140) ?: "Ошибка соединения")
                }
                js("cloudResponse", requestId, result.toString())
            }.start()
        }
        @JavascriptInterface fun pickPhoto(plantId: String) {
            if (plantId.length !in 1..70) return
            if (plantId.startsWith("catalog:") && !Regex("catalog:(?:b(?:[0-9]|1[01])|v-[a-z0-9-]{8,64})").matches(plantId)) return
            runOnUiThread {
                pendingPlant = plantId
                val intent = Intent(Intent.ACTION_GET_CONTENT).apply {
                    type = "image/*"
                    addCategory(Intent.CATEGORY_OPENABLE)
                }
                startActivityForResult(Intent.createChooser(intent, "Выбрать фото гортензии"), photoRequest)
            }
        }
        @JavascriptInterface fun openPhotoSource(url: String) {
            val uri = try { Uri.parse(url) } catch (_: Exception) { return }
            if (uri.scheme != "https" || uri.host != "commons.wikimedia.org" ||
                uri.path?.startsWith("/wiki/File:") != true || url.length > 600) return
            runOnUiThread { startActivity(Intent(Intent.ACTION_VIEW, uri)) }
        }
        @JavascriptInterface fun deleteLocalPhoto(photoId: String) {
            if (photoIdPattern.matches(photoId)) File(photos, "$photoId.jpg").delete()
        }
        @JavascriptInterface fun setReminderEnabled(enabled: Boolean) {
            runOnUiThread {
                if (enabled && Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED)
                    requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), notificationRequest)
                else { ReminderReceiver.setEnabled(this@MainActivity, enabled); reportReminderState() }
            }
        }
        @JavascriptInterface fun getReminderState() = ReminderReceiver.isEnabled(this@MainActivity)
        @JavascriptInterface fun exportBackup(data: String) {
            if (data.length > 1_000_000) return
            runOnUiThread {
                pendingExport = data
                startActivityForResult(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                    addCategory(Intent.CATEGORY_OPENABLE); type = "application/json"
                    putExtra(Intent.EXTRA_TITLE, "gortenziya-moy-sad.json")
                }, exportRequest)
            }
        }
        @JavascriptInterface fun importBackup() {
            runOnUiThread { startActivityForResult(Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE); type = "application/json"
            }, importRequest) }
        }
    }

    private fun reportReminderState() {
        web.evaluateJavascript("window.nativeReminderStatus && window.nativeReminderStatus(${ReminderReceiver.isEnabled(this)});", null)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == notificationRequest) {
            val allowed = grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED
            ReminderReceiver.setEnabled(this, allowed); reportReminderState()
            if (!allowed) Toast.makeText(this, "Разрешите уведомления в настройках", Toast.LENGTH_LONG).show()
        }
    }

    private fun addPhoto(data: Intent) {
        val uri = data.data ?: return
        // Decode with sampling: do not load a full-size camera image into memory.
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        require(bounds.outWidth in 1..20000 && bounds.outHeight in 1..20000) { "Неподходящий размер фотографии" }
        var sample=1
        while (bounds.outWidth/sample > 1600 || bounds.outHeight/sample > 1600) sample*=2
        val options=BitmapFactory.Options().apply { inSampleSize=sample; inPreferredConfig=Bitmap.Config.RGB_565 }
        val bitmap=contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, options) }
            ?: throw IllegalArgumentException("Фотография не открылась")
        val ratio=minOf(1.0, 1600.0/maxOf(bitmap.width,bitmap.height))
        val scaled=if (ratio < 1.0) Bitmap.createScaledBitmap(bitmap, (bitmap.width*ratio).toInt().coerceAtLeast(1),
            (bitmap.height*ratio).toInt().coerceAtLeast(1), true) else bitmap
        // Re-encode pixels to JPEG: EXIF location, camera metadata and filenames are not copied.
        val out=ByteArrayOutputStream()
        scaled.compress(Bitmap.CompressFormat.JPEG, 76, out)
        val bytes=out.toByteArray()
        if (scaled !== bitmap) scaled.recycle()
        bitmap.recycle()
        require(bytes.size in 100..1_000_000) { "Фото слишком большое после обработки" }
        val photoId=UUID.randomUUID().toString()
        File(photos, "$photoId.jpg").writeBytes(bytes)
        js("nativePhotoAdded", pendingPlant, photoId)
    }

    @Deprecated("Android 6+ compatible document picker")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (resultCode != RESULT_OK || data?.data == null) return
        try {
            when (requestCode) {
                photoRequest -> addPhoto(data)
                exportRequest -> {
                    contentResolver.openOutputStream(data.data!!)?.use { it.write(pendingExport.toByteArray(Charsets.UTF_8)) }
                        ?: throw IllegalStateException("Не удалось записать резервную копию")
                    pendingExport=""; Toast.makeText(this, "Резервная копия сохранена", Toast.LENGTH_SHORT).show()
                }
                importRequest -> {
                    val bytes=contentResolver.openInputStream(data.data!!)?.use { it.readBytes() } ?: return
                    require(bytes.size <= 1_000_000) { "Файл слишком большой" }
                    js("receiveImportBackup", bytes.toString(Charsets.UTF_8))
                }
            }
        } catch (e: Exception) {
            if (requestCode == photoRequest) js("nativePhotoError", e.message ?: "Не удалось обработать фото")
            else Toast.makeText(this, "Не удалось прочитать или сохранить файл", Toast.LENGTH_LONG).show()
        }
    }
    @Deprecated("Back button bridge")
    override fun onBackPressed() {
        web.evaluateJavascript("window.gardenBack ? window.gardenBack() : 'exit';") { if(it == "\"exit\"" || it == "null") finish() }
    }
    override fun onDestroy() {
        web.removeJavascriptInterface("GardenAndroid")
        web.destroy()
        super.onDestroy()
    }
}
