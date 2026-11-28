package com.castrite.twobody;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;

/**
 * 应用内更新：查 GitHub 最新 release → 下载 APK → 拉系统安装器。
 *
 * 签名已经固定（signing/ta.p12），所以覆盖安装即可，数据不会丢。
 */
public final class UpdateChecker {

    private static final String API =
            "https://api.github.com/repos/Z-Castrite/Cast/releases/latest";

    private UpdateChecker() {
    }

    public interface Callback {
        void onStatus(String text);
    }

    public static void checkAndInstall(Activity activity, Callback cb) {
        new Thread(() -> {
            try {
                cb.onStatus("检查中…");
                HttpURLConnection conn = (HttpURLConnection) new URL(API).openConnection();
                conn.setRequestProperty("User-Agent", "ta-app");
                conn.setRequestProperty("Accept", "application/vnd.github+json");
                conn.setConnectTimeout(15000);
                conn.setReadTimeout(20000);
                InputStream in = conn.getInputStream();
                String body = readAll(in);
                in.close();
                conn.disconnect();

                JSONObject rel = new JSONObject(body);
                String tag = rel.optString("tag_name", "");
                JSONArray assets = rel.optJSONArray("assets");
                if (assets == null) {
                    cb.onStatus("这个 release 没有包");
                    return;
                }
                // 先比版本：tag 是 v0.5 这种，当前是 0.5
                String latestVer = tag.startsWith("v") ? tag.substring(1) : tag;
                String curVer;
                try {
                    curVer = activity.getPackageManager()
                            .getPackageInfo(activity.getPackageName(), 0).versionName;
                } catch (Exception e) {
                    curVer = "";
                }
                if (!latestVer.isEmpty() && latestVer.equals(curVer)) {
                    cb.onStatus("已是最新（" + curVer + "）");
                    return;
                }
                cb.onStatus("发现新版本 " + tag + "（当前 " + curVer + "）");

                String apkUrl = null;
                String apkName = "ta-update.apk";
                for (int i = 0; i < assets.length(); i++) {
                    JSONObject a = assets.getJSONObject(i);
                    String name = a.optString("name", "");
                    if (name.endsWith(".apk")) {
                        apkUrl = a.optString("browser_download_url", "");
                        apkName = name;
                        break;
                    }
                }
                if (apkUrl == null) {
                    cb.onStatus("这个 release 没有 apk");
                    return;
                }

                String current = activity.getPackageManager()
                        .getPackageInfo(activity.getPackageName(), 0).versionName;
                cb.onStatus("最新 " + tag + "（当前 " + current + "），开始下载…");

                File out = new File(activity.getCacheDir(), apkName);
                download(apkUrl, out);

                cb.onStatus("下载完成，打开安装器…");
                install(activity, out);
            } catch (Exception e) {
                cb.onStatus("更新失败：" + e.getMessage());
            }
        }).start();
    }

    private static String readAll(InputStream in) throws Exception {
        BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = r.readLine()) != null) {
            sb.append(line);
        }
        r.close();
        return sb.toString();
    }

    private static void download(String urlStr, File out) throws Exception {
        HttpURLConnection conn = (HttpURLConnection) new URL(urlStr).openConnection();
        conn.setRequestProperty("User-Agent", "ta-app");
        conn.setConnectTimeout(15000);
        conn.setReadTimeout(60000);
        InputStream in = conn.getInputStream();
        try (FileOutputStream fos = new FileOutputStream(out)) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                fos.write(buf, 0, n);
            }
        } finally {
            in.close();
            conn.disconnect();
        }
    }

    private static void install(Activity activity, File apk) {
        try {
            android.util.Log.i("UpdateChecker", "install: " + apk.getAbsolutePath()
                    + " exists=" + apk.exists() + " len=" + apk.length());
            if (Build.VERSION.SDK_INT >= 26
                    && !activity.getPackageManager().canRequestPackageInstalls()) {
                android.util.Log.i("UpdateChecker", "no install permission, opening settings");
                // 没给「安装未知应用」就去设置页
                Intent i = new Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                        Uri.parse("package:" + activity.getPackageName()));
                activity.startActivity(i);
                return;
            }
            Uri uri = androidx.core.content.FileProvider.getUriForFile(
                    activity,
                    activity.getPackageName() + ".fileprovider",
                    apk);
            android.util.Log.i("UpdateChecker", "uri: " + uri);
            Intent i = new Intent(Intent.ACTION_VIEW);
            i.setDataAndType(uri, "application/vnd.android.package-archive");
            i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION
                    | Intent.FLAG_ACTIVITY_NEW_TASK);
            activity.startActivity(i);
            android.util.Log.i("UpdateChecker", "installer launched");
        } catch (Exception e) {
            android.util.Log.e("UpdateChecker", "install failed", e);
        }
    }
}
