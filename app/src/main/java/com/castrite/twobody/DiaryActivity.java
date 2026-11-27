package com.castrite.twobody;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Build;
import android.os.Bundle;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.widget.ArrayAdapter;
import android.widget.ListView;
import android.widget.TextView;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

/** 日记：读 files/agents/a<id>/diary/*.md，不经过 Python。 */
public class DiaryActivity extends Activity {

    private long agentId;
    private File dir;
    private ListView list;
    private ArrayAdapter<String> adapter;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_diary);
        applyInsets();

        agentId = getIntent().getLongExtra("agent_id", 1);
        dir = new File(getFilesDir(), "agents/a" + agentId + "/diary");

        list = findViewById(R.id.list);
        findViewById(R.id.back).setOnClickListener(v -> finish());

        refresh();

        list.setOnItemClickListener((parent, view, position, id) -> {
            String day = adapter.getItem(position);
            if (day != null) {
                showDiary(day);
            }
        });
    }

    private void refresh() {
        List<String> days = new ArrayList<>();
        String[] names = dir.exists() ? dir.list((d, n) -> n.endsWith(".md")) : null;
        if (names != null) {
            Arrays.sort(names, Collections.reverseOrder());
            for (String n : names) {
                days.add(n.substring(0, n.length() - 3));
            }
        }
        adapter = new ArrayAdapter<>(this, android.R.layout.simple_list_item_1, days);
        list.setAdapter(adapter);
    }

    private void showDiary(String day) {
        String text = read(new File(dir, day + ".md"));
        new AlertDialog.Builder(this)
                .setTitle(day)
                .setMessage(text)
                .setPositiveButton("关", null)
                .show();
    }

    private static String read(File f) {
        if (!f.exists()) {
            return "（没有）";
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
            return "（读不出来）";
        }
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
}
