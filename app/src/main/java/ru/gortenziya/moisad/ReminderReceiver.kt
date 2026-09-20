package ru.gortenziya.moisad

import android.app.AlarmManager
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import java.util.Calendar

/** Деликатное ежедневное напоминание проверить задачи, а не поливать по таймеру. */
class ReminderReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (!isEnabled(context)) return
        if (Build.VERSION.SDK_INT >= 33 && context.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) return
        val nm = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= 26) nm.createNotificationChannel(
            NotificationChannel("garden_care", "Забота о гортензиях", NotificationManager.IMPORTANCE_DEFAULT)
        )
        val open = PendingIntent.getActivity(
            context, 12, Intent(context, MainActivity::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = if (Build.VERSION.SDK_INT >= 26) {
            android.app.Notification.Builder(context, "garden_care")
        } else {
            @Suppress("DEPRECATION")
            android.app.Notification.Builder(context)
        }
        nm.notify(9001, notification.setSmallIcon(R.drawable.ic_notification)
            .setContentTitle("Ваш сад ждёт внимания 🌸")
            .setContentText("Загляните в календарь и проверьте влажность почвы у кустов.")
            .setAutoCancel(true).setContentIntent(open).build())
    }

    companion object {
        private const val PREFS = "garden_native"
        private const val ENABLED = "reminder_enabled"
        fun isEnabled(ctx: Context) = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(ENABLED, false)
        fun setEnabled(ctx: Context, enabled: Boolean) {
            ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(ENABLED, enabled).apply()
            if (enabled) schedule(ctx) else cancel(ctx)
        }
        private fun intent(ctx: Context) = PendingIntent.getBroadcast(
            ctx, 9001, Intent(ctx, ReminderReceiver::class.java),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        fun schedule(ctx: Context) {
            val calendar = Calendar.getInstance().apply {
                set(Calendar.HOUR_OF_DAY, 9); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
                if (timeInMillis <= System.currentTimeMillis()) add(Calendar.DAY_OF_MONTH, 1)
            }
            val alarm = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            alarm.setInexactRepeating(AlarmManager.RTC_WAKEUP, calendar.timeInMillis, AlarmManager.INTERVAL_DAY, intent(ctx))
        }
        fun cancel(ctx: Context) {
            val alarm = ctx.getSystemService(Context.ALARM_SERVICE) as AlarmManager
            alarm.cancel(intent(ctx))
        }
    }
}

class BootReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent?) {
        if (intent?.action == Intent.ACTION_BOOT_COMPLETED && ReminderReceiver.isEnabled(context)) {
            ReminderReceiver.schedule(context)
        }
    }
}
