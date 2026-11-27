package com.castrite.twobody;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

/**
 * 常驻服务：只干一件事——让进程活着。
 *
 * Android 会杀后台进程，锁屏后尤其积极。前台服务 + 常驻通知是唯一被系统
 * 认可的方式（比各种保活技巧干净）。Python 跑在同一个进程里，所以保进程
 * 就是保它的连续性。
 */
public class KeepAliveService extends Service {

    private static final String CHANNEL = "twobody_alive";
    private static final int NOTI_ID = 1;

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForeground(NOTI_ID, buildNotification());
        return START_STICKY;
    }

    private Notification buildNotification() {
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(
                    CHANNEL, "保持在线", NotificationManager.IMPORTANCE_LOW);
            ch.setDescription("让它在后台继续活着");
            NotificationManager nm = getSystemService(NotificationManager.class);
            if (nm != null) {
                nm.createNotificationChannel(ch);
            }
        }

        Intent i = new Intent(this, MainActivity.class);
        PendingIntent pi = PendingIntent.getActivity(this, 0, i,
                PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);

        Notification.Builder b = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(this, CHANNEL)
                : new Notification.Builder(this);

        return b.setContentTitle("烬衫")
                .setContentText("在线")
                .setSmallIcon(android.R.drawable.ic_menu_info_details)
                .setContentIntent(pi)
                .setOngoing(true)
                .build();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
