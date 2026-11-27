package com.castrite.twobody;

import android.app.Activity;
import android.app.AlertDialog;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.View;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.widget.Button;
import android.widget.EditText;
import android.widget.ListView;
import android.widget.TextView;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

/**
 * 群聊：一个会话里几个它。
 *
 * 节奏（按定稿）：
 *   - 用户说话后，不是全员点名，而是随机一个先接
 *   - 之后它们自己互相接话，不想接就回「算了」
 *   - 互相搭话总共不超过 20 句（防止无限循环）
 *   - 每个它用自己的 Engine 判情绪、查记忆，记忆各存各的
 */
public class GroupChatActivity extends Activity {

    private static final int MAX_REPLIES = 20;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private final Map<Long, PyObject> engines = new HashMap<>();
    private final Random random = new Random();

    private long convId;
    private Conversation conv;
    private AgentDb agentDb;
    private ChatDb chatDb;
    private MessageAdapter adapter;
    private ListView list;
    private EditText input;
    private boolean busy = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_group);
        applyInsets();

        convId = getIntent().getLongExtra("conv_id", 0);
        new ConversationDb(this);
        agentDb = new AgentDb(this);
        chatDb = new ChatDb(this);

        conv = new ConversationDb(this).get(convId);
        TextView title = findViewById(R.id.title);
        if (conv != null) {
            title.setText(conv.title + " · " + conv.agentIds.size() + " 人");
        }
        title.setOnClickListener(v -> renameGroup());

        list = findViewById(R.id.messages);
        input = findViewById(R.id.input);

        adapter = new MessageAdapter(this);
        list.setAdapter(adapter);

        loadHistory();

        findViewById(R.id.back).setOnClickListener(v -> finish());
        findViewById(R.id.send).setOnClickListener(v -> send());

        greeting();
    }

    private void renameGroup() {
        if (conv == null) {
            return;
        }
        final EditText et = new EditText(this);
        et.setText(conv.title);
        et.setSelection(et.getText().length());
        new AlertDialog.Builder(this)
                .setTitle("群聊名")
                .setView(et)
                .setPositiveButton("保存", (dialog, which) -> {
                    String t = et.getText().toString().trim();
                    if (t.isEmpty()) {
                        return;
                    }
                    new ConversationDb(GroupChatActivity.this).rename(convId, t);
                    conv = new ConversationDb(GroupChatActivity.this).get(convId);
                    TextView title = findViewById(R.id.title);
                    if (conv != null) {
                        title.setText(conv.title + " · " + conv.agentIds.size() + " 人");
                    }
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private File agentDir(long id) {
        return new File(getFilesDir(), "agents/a" + id);
    }

    private String nameOf(long id) {
        Agent a = agentDb.get(id);
        return a == null ? ("a" + id) : a.name;
    }

    private PyObject engineFor(long agentId) {
        PyObject cached = engines.get(agentId);
        if (cached != null) {
            return cached;
        }
        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }
        PyObject eng = Python.getInstance()
                .getModule("engine")
                .callAttr("Engine", agentDir(agentId).getAbsolutePath());
        eng.callAttr("start");
        engines.put(agentId, eng);
        return eng;
    }

    private void loadHistory() {
        adapter.clear();
        for (Message m : chatDb.groupMessages(convId, 200)) {
            adapter.add(m);
        }
        adapter.notifyDataSetChanged();
        if (adapter.getCount() > 0) {
            list.setSelection(adapter.getCount() - 1);
        }
    }

    /** 进群提示：每个它都该知道"有人进来了"。 */
    private void greeting() {
        if (adapter.getCount() > 0 || conv == null) {
            return;
        }
        StringBuilder sb = new StringBuilder();
        for (Long id : conv.agentIds) {
            sb.append(nameOf(id)).append(" 进入了群聊\n");
        }
        addMessage(new Message(false, sb.toString().trim(), System.currentTimeMillis(),
                null, "系统"), true);
    }

    private void send() {
        if (busy || conv == null) {
            return;
        }
        String text = input.getText().toString().trim();
        if (text.isEmpty()) {
            return;
        }
        input.setText("");
        addMessage(new Message(true, text, System.currentTimeMillis(), null), true);

        // 解析 @：被点名的那位先接，没点名就随机
        String atName = null;
        for (Long id : conv.agentIds) {
            String nm = nameOf(id);
            if (text.contains("@" + nm)) {
                atName = nm;
                break;
            }
        }
        final String at = atName;

        busy = true;
        new Thread(() -> runGroupTurn(at)).start();
    }

    /**
     * 一轮群聊：
     *   1. 被 @ 的那位先接（没 @ 就随机挑一个）
     *   2. 然后它们互相搭话，直到连续两个不想接，或者到 20 句上限
     */
    private void runGroupTurn(String atName) {
        int spoken = 0;
        try {
            List<Long> ids = conv.agentIds;
            if (ids.isEmpty()) {
                return;
            }

            // 第一句：被 @ 的优先，否则随机。这一句不允许「算了」。
            Long firstId = null;
            if (atName != null) {
                for (Long id : ids) {
                    if (nameOf(id).equals(atName)) {
                        firstId = id;
                        break;
                    }
                }
            }
            if (firstId == null) {
                firstId = ids.get(random.nextInt(ids.size()));
            }
            int first = ids.indexOf(firstId);

            Message head = askForced(firstId, buildContext(nameOf(firstId), true, atName));
            if (head != null) {
                post(head);
                spoken++;
            }

            // 之后：它们互相聊，这时候允许不想接
            int idx = first + 1;
            int silent = 0;
            while (spoken < MAX_REPLIES && silent < 2 && idx < 80) {
                Long agentId = ids.get(idx % ids.size());
                Message m = ask(agentId, buildContext(nameOf(agentId), false, null));
                if (m == null) {
                    silent++;
                } else {
                    silent = 0;
                    post(m);
                    spoken++;
                }
                idx++;
            }

            if (spoken >= MAX_REPLIES) {
                final Message limit = new Message(false,
                        "（他们聊到 " + MAX_REPLIES + " 句，先停一下。）",
                        System.currentTimeMillis(), null, "系统");
                ui.post(() -> addMessage(limit, true));
            }
        } catch (Throwable e) {
            final Message err = new Message(false, "（群里出了点问题：" + e + "）",
                    System.currentTimeMillis(), null, "系统");
            ui.post(() -> addMessage(err, false));
        } finally {
            ui.post(() -> busy = false);
        }
    }

    /** 第一句用：用户说话必须接，只过滤空回复。 */
    private Message askForced(long agentId, String ctx) {
        PyObject r = engineFor(agentId).callAttr("turn_group", ctx, "群聊记录");
        String err = r.callAttr("get", "error").toString();
        if (err != null && !err.isEmpty() && !err.equals("None")) {
            return null;
        }
        String reply = r.callAttr("get", "reply").toString();
        if (reply == null) {
            return null;
        }
        String t = reply.trim();
        if (t.isEmpty() || "None".equals(t)) {
            return null;
        }
        String emo = r.callAttr("get", "emotions_text").toString();
        String e = (emo == null || emo.equals("None") || emo.isEmpty()) ? null : emo;
        return new Message(false, t, System.currentTimeMillis(), e, nameOf(agentId));
    }

    /** 问一个它：这句话你想接吗。不想接会把「算了」吞掉，返回 null。 */
    private Message ask(long agentId, String ctx) {
        PyObject r = engineFor(agentId).callAttr("turn_group", ctx, "群聊记录");
        String err = r.callAttr("get", "error").toString();
        if (err != null && !err.isEmpty() && !err.equals("None")) {
            return null;
        }
        String reply = r.callAttr("get", "reply").toString();
        if (reply == null) {
            return null;
        }
        String t = reply.trim();
        if (t.isEmpty()) {
            return null;
        }
        String clean = t.replaceAll("[。，！!？?、\\s\"'「」]", "");
        if (clean.equals("算了")) {
            return null;
        }
        String emo = r.callAttr("get", "emotions_text").toString();
        String e = (emo == null || emo.equals("None") || emo.isEmpty()) ? null : emo;
        return new Message(false, t, System.currentTimeMillis(), e, nameOf(agentId));
    }

    private void post(Message m) {
        ui.post(() -> addMessage(m, true));
    }

    /**
     * 群上下文：视角化——「我」是它自己说过的，名字是别人的。
     * 不视角化的话，它会分不清哪句是自己说的、哪句是别人说的。
     */
    private String buildContext(String meName, boolean replyToUser, String atName) {
        StringBuilder sb = new StringBuilder("【群聊记录】\n");
        List<Message> recent = chatDb.groupMessages(convId, 24);
        for (Message m : recent) {
            if (m.sender != null && "系统".equals(m.sender)) {
                continue;
            }
            String who;
            if (m.sender == null) {
                who = "用户";
            } else if (m.sender.equals(meName)) {
                who = "我";
            } else {
                who = m.sender;
            }
            sb.append(who).append("：").append(m.text).append("\n");
        }
        sb.append("\n（我在群里，名字是 ").append(meName).append("。");
        if (atName != null && atName.equals(meName)) {
            sb.append("用户 @ 了我，点名让我说。");
        } else if (atName != null) {
            sb.append("用户 @ 了 ").append(atName).append("。");
        } else if (replyToUser) {
            sb.append("用户刚说了话，接一句。");
        } else {
            sb.append("想接就接一句，不想接就只回两个字：算了。");
        }
        sb.append("）");
        return sb.toString();
    }

    private void addMessage(Message m, boolean persist) {
        adapter.add(m);
        adapter.notifyDataSetChanged();
        if (persist) {
            chatDb.insertGroup(convId, m.mine, m.text, m.ts, m.emotions, m.sender);
        }
        list.smoothScrollToPosition(adapter.getCount() - 1);
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
        final View inputRow = findViewById(R.id.input_row);
        final View root = findViewById(R.id.root);
        root.setOnApplyWindowInsetsListener((v, insets) -> {
            int top;
            int bottom;
            int ime = 0;
            if (Build.VERSION.SDK_INT >= 30) {
                android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
                top = bars.top;
                bottom = bars.bottom;
                ime = insets.getInsets(WindowInsets.Type.ime()).bottom;
            } else {
                top = insets.getSystemWindowInsetTop();
                bottom = insets.getSystemWindowInsetBottom();
            }
            // 顶部用 padding（布局不变），键盘用 translationY——不在回调里改高度，
            // 免得布局重排把输入法连接重置掉（mServedView=null 那个坑）。
            v.setPadding(0, top, 0, 0);
            if (inputRow != null) {
                int nav = bottom;
                inputRow.setPadding(inputRow.getPaddingLeft(), inputRow.getPaddingTop(),
                        inputRow.getPaddingRight(), nav);
                inputRow.setTranslationY(-Math.max(0, ime - nav));
            }
            return insets;
        });
    }
}
