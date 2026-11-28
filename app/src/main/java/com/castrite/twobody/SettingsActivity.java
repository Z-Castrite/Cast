package com.castrite.twobody;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.widget.Button;
import android.widget.EditText;
import android.widget.Switch;
import android.widget.TextView;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * 设置页：改的是「当前这个智能体」的 key、人设和记忆，不是全局的。
 * 改完要重启 App 才生效（engine 已经加载过配置）。
 */
public class SettingsActivity extends Activity {

    private EditText keyInput;
    private EditText personaInput;
    private EditText nameInput;
    private EditText userInput;
    private Switch hbSwitch;
    private Switch consSwitch;
    private TextView tip;
    private long agentId;
    private File dir;
    private AgentDb agentDb;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_settings);
        applyInsets();

        agentId = getIntent().getLongExtra("agent_id", 1);
        dir = new File(getFilesDir(), "agents/a" + agentId);
        dir.mkdirs();
        agentDb = new AgentDb(this);

        keyInput = findViewById(R.id.api_key);
        personaInput = findViewById(R.id.persona);
        nameInput = findViewById(R.id.agent_name);
        userInput = findViewById(R.id.user_name);
        hbSwitch = findViewById(R.id.hb_switch);
        consSwitch = findViewById(R.id.cons_switch);
        tip = findViewById(R.id.tip);

        Agent me = agentDb.get(agentId);
        nameInput.setText(me == null ? "" : me.name);
        userInput.setText(read(new File(getFilesDir(), "user_name.txt")));

        try {
            JSONObject o = new JSONObject(read(new File(dir, "config.json")));
            keyInput.setText(o.getJSONObject("api").optString("api_key", ""));
            JSONObject hb = o.optJSONObject("heartbeat");
            hbSwitch.setChecked(hb == null || hb.optBoolean("enabled", true));
            JSONObject cons = o.optJSONObject("consolidate");
            consSwitch.setChecked(cons == null || cons.optBoolean("enabled", true));
        } catch (Exception ignored) {
        }

        try {
            JSONObject o = new JSONObject(read(new File(dir, "config.json")));
            keyInput.setText(o.getJSONObject("api").optString("api_key", ""));
        } catch (Exception ignored) {
        }
        personaInput.setText(read(new File(dir, "persona.txt")));

        Button save = findViewById(R.id.save);
        Button wipe = findViewById(R.id.wipe);
        save.setOnClickListener(v -> save());
        wipe.setOnClickListener(v -> wipe());
        findViewById(R.id.update).setOnClickListener(v -> {
            tip.setText("检查更新…");
            UpdateChecker.checkAndInstall(SettingsActivity.this,
                    msg -> runOnUiThread(() -> tip.setText(msg)));
        });
    }

    private void applyInsets() {
        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                c.setSystemBarsAppearance(0,
                        WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS
                                | WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION);
        }
        final View root = findViewById(R.id.root);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int top;
            int bottom;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                top = bars.top;
                bottom = bars.bottom;
            } else {
                top = insets.getSystemWindowInsetTop();
                bottom = insets.getSystemWindowInsetBottom();
            }
            v.setPadding(0, top, 0, bottom);
            return insets;
        });
    }

    private void save() {
        try {
            String newName = nameInput.getText().toString().trim();
            if (!newName.isEmpty()) {
                agentDb.rename(agentId, newName);
            }

            // 共用 key + 主动开关：所有智能体都写一遍（记忆还是各自的）
            String key = keyInput.getText().toString().trim();
            for (Agent a : agentDb.all()) {
                File f = new File(getFilesDir(), "agents/a" + a.id + "/config.json");
                if (!f.exists()) {
                    continue;
                }
                try {
                    JSONObject o = new JSONObject(read(f));
                    o.getJSONObject("api").put("api_key", key);
                    if (o.optJSONObject("heartbeat") != null) {
                        o.getJSONObject("heartbeat").put("enabled", hbSwitch.isChecked());
                    }
                    if (o.optJSONObject("consolidate") != null) {
                        o.getJSONObject("consolidate").put("enabled", consSwitch.isChecked());
                    }
                    write(f, o.toString(2));
                } catch (Exception ignored) {
                }
            }

            write(new File(dir, "persona.txt"), personaInput.getText().toString());
            write(new File(getFilesDir(), "user_name.txt"),
                    userInput.getText().toString().trim());
            tip.setText("已保存。重启 App 生效。");
        } catch (Exception e) {
            tip.setText("保存失败：" + e);
        }
    }

    private void wipe() {
        new ChatDb(this).clear(agentId);
        deleteDir(new File(dir, "memory_store"));
        tip.setText("这一个的空白板已清：记忆库和聊天记录都没了。重启 App。");
    }

    private static void deleteDir(File f) {
        if (f == null || !f.exists()) {
            return;
        }
        File[] kids = f.listFiles();
        if (kids != null) {
            for (File k : kids) {
                deleteDir(k);
            }
        }
        //noinspection ResultOfMethodCallIgnored
        f.delete();
    }

    private static String read(File f) {
        if (!f.exists()) {
            return "";
        }
        try (FileInputStream in = new FileInputStream(f)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
            }
            return out.toString("UTF-8");
        } catch (IOException e) {
            return "";
        }
    }

    private static void write(File f, String text) {
        try (FileOutputStream out = new FileOutputStream(f)) {
            out.write(text.getBytes(StandardCharsets.UTF_8));
        } catch (IOException ignored) {
        }
    }
}
