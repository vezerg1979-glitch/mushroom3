package ru.gortenziya.moisad

import android.content.Context
import android.net.Uri
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.UUID

/** Supabase REST. The publishable/anon key is public; NEVER put a service-role key in an APK. */
class CloudAlbum(private val context: Context) {
    private val root = BuildConfig.SUPABASE_URL.trim().trimEnd('/')
    private val key = BuildConfig.SUPABASE_ANON_KEY.trim()
    val configured = root.matches(Regex("https://[a-zA-Z0-9.-]+(:[0-9]{2,5})?")) && key.isNotEmpty()
    private val prefs = context.getSharedPreferences("garden_community", Context.MODE_PRIVATE)
    private val bucket = "garden-photos"

    private fun req(method: String, path: String, bearer: String? = null, body: ByteArray? = null,
                    type: String = "application/json", prefer: String? = null): String {
        val conn = (URL(root + path).openConnection() as HttpURLConnection)
        try {
            conn.requestMethod = method
            conn.connectTimeout = 12000
            conn.readTimeout = 20000
            conn.instanceFollowRedirects = false
            conn.setRequestProperty("apikey", key)
            // Publishable keys are NOT JWTs. They belong only in the apikey header.
            if (bearer != null) conn.setRequestProperty("Authorization", "Bearer $bearer")
            else if (key.startsWith("eyJ")) conn.setRequestProperty("Authorization", "Bearer $key")
            conn.setRequestProperty("Accept", "application/json")
            if (prefer != null) conn.setRequestProperty("Prefer", prefer)
            if (body != null) {
                conn.doOutput = true
                conn.setRequestProperty("Content-Type", type)
                conn.outputStream.use { it.write(body) }
            }
            val status = conn.responseCode
            val bytes = (if (status in 200..299) conn.inputStream else conn.errorStream)
                ?.use { it.readBytes() } ?: ByteArray(0)
            if (status !in 200..299) {
                throw IllegalStateException("Сервер вернул ошибку $status. Проверьте подключение и права доступа.")
            }
            return bytes.toString(Charsets.UTF_8)
        } finally { conn.disconnect() }
    }

    private fun json(x: JSONObject) = x.toString().toByteArray(Charsets.UTF_8)
    private fun session(): String {
        check(configured) { "Общий альбом не настроен" }
        var access = prefs.getString("access", "") ?: ""
        val expires = prefs.getLong("expires", 0)
        if (access.isNotBlank() && System.currentTimeMillis() < expires - 60_000) return access
        val refresh = prefs.getString("refresh", "") ?: ""
        val response = if (refresh.isNotEmpty()) {
            try { req("POST", "/auth/v1/token?grant_type=refresh_token", body=json(JSONObject().put("refresh_token", refresh))) }
            catch (_: Exception) { req("POST", "/auth/v1/signup", body=json(JSONObject())) }
        } else req("POST", "/auth/v1/signup", body=json(JSONObject()))
        val result = JSONObject(response)
        access = result.getString("access_token")
        val userId = result.getJSONObject("user").getString("id")
        prefs.edit().putString("access", access).putString("refresh", result.getString("refresh_token"))
            .putString("uid", userId)
            .putLong("expires", System.currentTimeMillis() + result.optLong("expires_in", 3600) * 1000L).apply()
        return access
    }

    private fun uid() = prefs.getString("uid", "") ?: ""
    private fun id(raw: String): String {
        val parsed = UUID.fromString(raw)
        require(parsed.toString() == raw) { "Неверный идентификатор фотографии" }
        return raw
    }
    private fun text(value: String, max: Int) = value.trim().take(max)

    fun execute(action: String, input: JSONObject, localPhotos: File): JSONObject {
        check(configured) { "Общий альбом не настроен" }
        val token = session()
        return when (action) {
            "list" -> {
                val columns = "id,owner_id,nickname,variety,caption,storage_path,status,created_at"
                val q1 = "/rest/v1/garden_photos?select=$columns&status=eq.approved&order=created_at.desc&limit=30"
                val q2 = "/rest/v1/garden_photos?select=$columns&owner_id=eq.${uid()}&status=eq.pending&order=created_at.desc&limit=10"
                val approved = JSONArray(req("GET", q1, token))
                val pending = JSONArray(req("GET", q2, token))
                val all = JSONArray()
                for (i in 0 until pending.length()) all.put(pending.getJSONObject(i))
                for (i in 0 until approved.length()) all.put(approved.getJSONObject(i))
                val paths = JSONArray()
                for (i in 0 until all.length()) paths.put(all.getJSONObject(i).getString("storage_path"))
                val signed = if (paths.length() == 0) JSONArray() else JSONArray(req("POST", "/storage/v1/object/sign/$bucket", token,
                    json(JSONObject().put("expiresIn", 3600).put("paths", paths))))
                val output = JSONArray()
                for (i in 0 until all.length()) {
                    val item = all.getJSONObject(i)
                    // Send only display fields to WebView: no owner ID and no storage path.
                    val sign = if (i < signed.length()) signed.getJSONObject(i).optString("signedURL") else ""
                    val url = if (sign.startsWith("/object/sign/$bucket/")) root + "/storage/v1" + sign else ""
                    output.put(JSONObject().put("id", item.getString("id"))
                        .put("nickname", item.optString("nickname")).put("variety", item.optString("variety"))
                        .put("caption", item.optString("caption")).put("created_at", item.optString("created_at"))
                        .put("status", item.optString("status")).put("mine", item.optString("owner_id") == uid())
                        .put("url", url))
                }
                JSONObject().put("items", output)
            }
            "upload" -> {
                require(input.optBoolean("consent", false)) { "Подтвердите согласие на публикацию" }
                val nick = text(input.optString("nickname"), 24)
                require(nick.isNotBlank()) { "Укажите псевдоним" }
                val photoId = id(input.getString("photoId"))
                val file = File(localPhotos, "$photoId.jpg")
                require(file.canonicalFile.parentFile == localPhotos.canonicalFile && file.isFile) { "Локальная фотография не найдена" }
                val bytes = file.readBytes()
                require(bytes.size in 100..1_000_000) { "Фото должно быть меньше 1 МБ" }
                val postId = UUID.randomUUID().toString()
                val path = "${uid()}/$postId.jpg"
                val row = JSONObject().put("id", postId).put("owner_id", uid()).put("storage_path", path)
                    .put("nickname", nick).put("variety", text(input.optString("variety"), 60))
                    .put("caption", text(input.optString("caption"), 180))
                req("POST", "/rest/v1/garden_photos", token, json(row), prefer="return=minimal")
                try {
                    req("POST", "/storage/v1/object/$bucket/$path", token, bytes, "image/jpeg")
                } catch (e: Exception) {
                    // Upload failure: remove the pending DB row so it does not remain forever.
                    try { req("DELETE", "/rest/v1/garden_photos?id=eq.$postId&owner_id=eq.${uid()}", token) } catch (_: Exception) {}
                    throw e
                }
                JSONObject().put("id", postId).put("status", "pending")
            }
            "remove" -> {
                val postId=id(input.getString("id"))
                val rows = JSONArray(req("GET", "/rest/v1/garden_photos?select=storage_path&id=eq.$postId&owner_id=eq.${uid()}&limit=1", token))
                require(rows.length() == 1) { "Не удалось найти вашу публикацию" }
                val path=rows.getJSONObject(0).getString("storage_path")
                req("DELETE", "/storage/v1/object/$bucket", token, json(JSONObject().put("prefixes", JSONArray().put(path))))
                req("DELETE", "/rest/v1/garden_photos?id=eq.$postId&owner_id=eq.${uid()}", token)
                JSONObject().put("removed", true)
            }
            "report" -> {
                val postId=id(input.getString("id"))
                req("POST", "/rest/v1/garden_reports", token,
                    json(JSONObject().put("photo_id", postId).put("reporter_id", uid())), prefer="return=minimal")
                JSONObject().put("sent", true)
            }
            else -> throw IllegalArgumentException("Неизвестная операция")
        }
    }
}
