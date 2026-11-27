package com.castrite.twobody;

import android.app.Activity;
import android.content.Intent;
import android.os.Build;
import android.os.Bundle;
import android.text.Editable;
import android.text.TextWatcher;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.widget.EditText;
import android.widget.ListView;

import java.util.ArrayList;
import java.util.List;

/**
 * 回忆页：只做导航，不建第二份存储。
 * 数据全部来自 chat.db 的 messages 表——按天的时间轴，或关键词搜索。
 */
public class RecallActivity extends Activity {

    private EditText query;
    private ChatDb db;
    private RecallAdapter adapter;
    private long agentId = 1;
    private final List<Object> data = new ArrayList<>();

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_recall);
        applyInsets();

        agentId = getIntent().getLongExtra("agent_id", 1);
        query = findViewById(R.id.query);
        ListView list = findViewById(R.id.list);
        db = new ChatDb(this);
        adapter = new RecallAdapter(this, data);
        list.setAdapter(adapter);

        showTimeline();

        query.addTextChangedListener(new TextWatcher() {
            @Override
            public void beforeTextChanged(CharSequence s, int start, int count, int after) {
            }

            @Override
            public void onTextChanged(CharSequence s, int start, int before, int count) {
            }

            @Override
            public void afterTextChanged(Editable s) {
                String kw = s.toString().trim();
                if (kw.isEmpty()) {
                    showTimeline();
                } else {
                    showSearch(kw);
                }
            }
        });

        list.setOnItemClickListener((parent, view, position, id) -> {
            Object o = data.get(position);
            long ts = (o instanceof TimelineDay)
                    ? ((TimelineDay) o).firstTs
                    : ((Message) o).ts;
            Intent r = new Intent();
            r.putExtra("ts", ts);
            setResult(RESULT_OK, r);
            finish();
        });

        findViewById(R.id.back).setOnClickListener(v -> finish());
    }

    private void showTimeline() {
        data.clear();
        data.addAll(db.timeline(agentId));
        adapter.notifyDataSetChanged();
    }

    private void showSearch(String kw) {
        data.clear();
        data.addAll(db.search(agentId, kw, 200));
        adapter.notifyDataSetChanged();
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
