package com.castrite.twobody;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.speech.tts.UtteranceProgressListener;
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

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

public class MainActivity extends Activity {

    private static final int REQ_RECALL = 100;
    private static final int REQ_PICK_IMAGE = 200;
    private static final int REQ_MIC = 300;
    private static final int REQ_NOTI = 400;
    private static final int REQ_CAM = 500;

    private final Handler ui = new Handler(Looper.getMainLooper());

    private File files;
    private AgentDb agentDb;
    private long currentAgentId = 1;
    private final Map<Long, PyObject> engines = new HashMap<>();

    private PyObject engine;
    private ChatDb db;
    private MessageAdapter adapter;
    private ListView list;
    private EditText input;
    private Button send;
    private Button callBtn;
    private TextView status;
    private TextView nameView;
    private boolean busy = false;

    private TextToSpeech tts;
    private boolean ttsReady = false;
    private SpeechRecognizer recognizer;
    private boolean callMode = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);
        applyInsets();

        files = getFilesDir();
        list = findViewById(R.id.messages);
        input = findViewById(R.id.input);
        send = findViewById(R.id.send);
        status = findViewById(R.id.status);
        callBtn = findViewById(R.id.call);
        nameView = findViewById(R.id.name);

        adapter = new MessageAdapter(this);
        list.setAdapter(adapter);

        // 第一次启动：把打包进来的两套记忆导出来（陈长生 / 烬衫）
        SeedImporter.seedIfNeeded(this);

        // 谁在说话：登记表 + 各自独立的目录
        agentDb = new AgentDb(this);
        currentAgentId = agentDb.ensureDefault("烬衫");
        migrateToAgent(currentAgentId);

        Agent me = agentDb.get(currentAgentId);
        nameView.setText(me == null ? "烬衫" : me.name);
        nameView.setOnClickListener(v -> showAgentPicker());

        db = new ChatDb(this);
        loadHistory(currentAgentId);
        startEngine(currentAgentId);

        initTts();

        send.setOnClickListener(v -> send());
        findViewById(R.id.peek).setOnClickListener(v -> peek());
        findViewById(R.id.pick).setOnClickListener(v -> pickImage());
        findViewById(R.id.settings).setOnClickListener(v -> openSettings());
        findViewById(R.id.recall).setOnClickListener(v -> openRecall());
        callBtn.setOnClickListener(v -> toggleCall());
        findViewById(R.id.diary).setOnClickListener(v -> openDiary());

        startKeepAlive();

        // 摄像头权限：它想自己看一眼的时候要用
        if (checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAM);
        }

        // 每晚 21 点后写日记
        startDiaryScheduler();

        // 主动搭话：后台攒着的消息，拉出来显示
        startProactivePoller();
    }

    /** 每 30 秒问一次引擎：有没有它自己开口说的话。 */
    private void startProactivePoller() {
        new Thread(() -> {
            while (true) {
                try {
                    Thread.sleep(30 * 1000L);
                    final PyObject eng = engine;
                    if (eng == null) {
                        continue;
                    }
                    PyObject out = eng.callAttr("poll");
                    int n = out.callAttr("__len__").toInt();
                    for (int i = 0; i < n; i++) {
                        PyObject m = out.callAttr("__getitem__", i);
                        String text = m.callAttr("get", "text").toString();
                        String emo = m.callAttr("get", "emotions_text").toString();
                        final String e = (emo == null || emo.equals("None") || emo.isEmpty())
                                ? null : emo;
                        final String t = (text == null) ? "" : text;
                        if (!t.isEmpty()) {
                            ui.post(() -> addMessage(new Message(false, t,
                                    System.currentTimeMillis(), e), true));
                        }
                    }
                } catch (Throwable ignored) {
                }
            }
        }).start();
    }

    private void openDiary() {
        Intent i = new Intent(this, DiaryActivity.class);
        i.putExtra("agent_id", currentAgentId);
        startActivity(i);
    }

    /** 用户的名字：写日记时「致：」后面用。设置页可改，默认铸豊。 */
    private String readUserName() {
        File f = new File(getFilesDir(), "user_name.txt");
        if (f.exists()) {
            try {
                String s = new String(java.nio.file.Files.readAllBytes(f.toPath()), "UTF-8").trim();
                if (!s.isEmpty()) {
                    return s;
                }
            } catch (Exception ignored) {
            }
        }
        return "铸豊";
    }

    /** 21 点后检查一次：今天没写就让它写。每 5 分钟看一眼，写完就跳过。 */
    private void startDiaryScheduler() {
        new Thread(() -> {
            while (true) {
                try {
                    java.util.Calendar c = java.util.Calendar.getInstance();
                    if (c.get(java.util.Calendar.HOUR_OF_DAY) >= 21) {
                        String today = new java.text.SimpleDateFormat(
                                "yyyy-MM-dd", java.util.Locale.US).format(new java.util.Date());
                        File f = new File(getFilesDir(),
                                "agents/a" + currentAgentId + "/diary/" + today + ".md");
                        if (!f.exists() && engine != null) {
                            PyObject r = engine.callAttr("write_diary", readUserName());
                            String ok = r.callAttr("get", "ok").toString();
                            if ("True".equals(ok)) {
                                ui.post(() -> addMessage(new Message(false,
                                        "（今晚的日记写好了）",
                                        System.currentTimeMillis(), null), false));
                            }
                        }
                    }
                    Thread.sleep(5 * 60 * 1000L);
                } catch (Throwable e) {
                    try {
                        Thread.sleep(60 * 1000L);
                    } catch (InterruptedException ignored) {
                    }
                }
            }
        }).start();
    }

    @Override
    protected void onResume() {
        super.onResume();
        // 从设置页改名回来，顶栏要跟上
        if (agentDb != null && nameView != null) {
            Agent a = agentDb.get(currentAgentId);
            if (a != null) {
                nameView.setText(a.name);
                adapter.setPeerName(a.name);
                adapter.notifyDataSetChanged();
            }
        }
    }

    @Override
    protected void onDestroy() {
        if (tts != null) {
            tts.stop();
            tts.shutdown();
        }
        if (recognizer != null) {
            recognizer.destroy();
        }
        super.onDestroy();
    }

    // ------------------------------------------------------------ 智能体

    private File agentDir(long id) {
        return new File(files, "agents/a" + id);
    }

    /** 第一次升级到多智能体时，把老的单体目录搬进来。 */
    private void migrateToAgent(long id) {
        File dir = agentDir(id);
        dir.mkdirs();

        File cfg = new File(dir, "config.json");
        if (!cfg.exists()) {
            File old = new File(files, "config.json");
            if (old.exists() && !old.renameTo(cfg)) {
                copyAsset("config.json", cfg);
            } else if (!cfg.exists()) {
                copyAsset("config.json", cfg);
            }
        }

        File persona = new File(dir, "persona.txt");
        if (!persona.exists()) {
            File old = new File(files, "persona.txt");
            if (old.exists() && !old.renameTo(persona)) {
                copyAsset("persona.txt", persona);
            } else if (!persona.exists()) {
                copyAsset("persona.txt", persona);
            }
        }

        File store = new File(dir, "memory_store");
        if (!store.exists()) {
            File old = new File(files, "memory_store");
            if (old.exists() && !old.renameTo(store)) {
                // 搬不动就算了，Python 会重建
            }
        }
    }

    private void startEngine(long agentId) {
        if (engines.containsKey(agentId)) {
            engine = engines.get(agentId);
            setStatus("空闲");
            return;
        }
        setStatus("加载中…");
        final File dir = agentDir(agentId);
        new Thread(() -> {
            try {
                if (!Python.isStarted()) {
                    Python.start(new AndroidPlatform(MainActivity.this));
                }
                PyObject eng = Python.getInstance()
                        .getModule("engine")
                        .callAttr("Engine", dir.getAbsolutePath());
                PyObject st = eng.callAttr("start");
                // 把拍照器交给它——主意识自己想看的时候调 look
                try {
                    eng.callAttr("set_camera", new CameraCapture(MainActivity.this));
                } catch (Throwable ignored) {
                }
                String total = st.callAttr("get", "total").toString();
                engines.put(agentId, eng);
                ui.post(() -> {
                    if (agentId == currentAgentId) {
                        engine = eng;
                        setStatus("空闲");
                        addMessage(new Message(false,
                                "引擎就绪，记忆 " + total + " 条。",
                                System.currentTimeMillis(), null), false);
                    }
                });
            } catch (Throwable e) {
                ui.post(() -> {
                    if (agentId == currentAgentId) {
                        setStatus("启动失败");
                        addMessage(new Message(false, "引擎启动失败：" + describe(e),
                                System.currentTimeMillis(), null), false);
                    }
                });
            }
        }).start();
    }

    private void loadHistory(long agentId) {
        Agent a = agentDb.get(agentId);
        adapter.setPeerName(a == null ? "" : a.name);
        adapter.clear();
        for (Message m : db.recent(agentId, 200)) {
            adapter.add(m);
        }
        adapter.notifyDataSetChanged();
        if (adapter.getCount() > 0) {
            list.setSelection(adapter.getCount() - 1);
        }
    }

    private void switchAgent(long id) {
        currentAgentId = id;
        agentDb.touch(id);
        Agent a = agentDb.get(id);
        nameView.setText(a == null ? "烬衫" : a.name);
        engine = engines.get(id);
        loadHistory(id);
        if (engine == null) {
            startEngine(id);
        } else {
            setStatus(callMode ? "通话中" : "空闲");
        }
    }

    private void showAgentPicker() {
        final List<Agent> agents = agentDb.all();
        final List<Conversation> groups = new ConversationDb(this).groups();
        final int n = agents.size() + groups.size() + 2;

        String[] names = new String[n];
        int k = 0;
        for (Agent a : agents) {
            names[k++] = a.name;
        }
        for (Conversation c : groups) {
            names[k++] = "👥 " + c.title;
        }
        names[k++] = "＋ 新建一个";
        names[k] = "👥 新建群聊";

        new AlertDialog.Builder(this)
                .setTitle("和谁说话")
                .setItems(names, (dialog, which) -> {
                    if (which < agents.size()) {
                        switchAgent(agents.get(which).id);
                    } else if (which < agents.size() + groups.size()) {
                        openGroup(groups.get(which - agents.size()).id);
                    } else if (which == n - 1) {
                        promptNewGroup();
                    } else {
                        promptNewAgent();
                    }
                })
                .show();
    }

    private void openGroup(long convId) {
        Intent i = new Intent(this, GroupChatActivity.class);
        i.putExtra("conv_id", convId);
        startActivity(i);
    }

    private void promptNewGroup() {
        final List<Agent> agents = agentDb.all();
        if (agents.size() < 2) {
            new AlertDialog.Builder(this)
                    .setMessage("至少要两个它才能建群。先点「＋ 新建一个」。")
                    .setPositiveButton("好", null)
                    .show();
            return;
        }
        String[] names = new String[agents.size()];
        final boolean[] checked = new boolean[agents.size()];
        for (int i = 0; i < agents.size(); i++) {
            names[i] = agents.get(i).name;
        }
        new AlertDialog.Builder(this)
                .setTitle("选几个它进群")
                .setMultiChoiceItems(names, checked,
                        (dialog, which, isChecked) -> checked[which] = isChecked)
                .setPositiveButton("建群", (dialog, which) -> {
                    List<Long> ids = new ArrayList<>();
                    for (int i = 0; i < checked.length; i++) {
                        if (checked[i]) {
                            ids.add(agents.get(i).id);
                        }
                    }
                    if (ids.size() < 2) {
                        return;
                    }
                    ConversationDb cdb = new ConversationDb(MainActivity.this);
                    long convId = cdb.create("群聊", ids, true);
                    Intent i = new Intent(MainActivity.this, GroupChatActivity.class);
                    i.putExtra("conv_id", convId);
                    startActivity(i);
                })
                .setNegativeButton("取消", null)
                .show();
    }

    private void promptNewAgent() {
        final EditText et = new EditText(this);
        et.setHint("名字");
        new AlertDialog.Builder(this)
                .setTitle("新建智能体")
                .setView(et)
                .setPositiveButton("创建", (dialog, which) -> {
                    String name = et.getText().toString().trim();
                    if (name.isEmpty()) {
                        return;
                    }
                    long id = agentDb.create(name);
                    File dir = agentDir(id);
                    dir.mkdirs();
                    copyAsset("config.json", new File(dir, "config.json"));
                    copyAsset("persona.txt", new File(dir, "persona.txt"));
                    switchAgent(id);
                })
                .setNegativeButton("取消", null)
                .show();
    }

    // ------------------------------------------------------------ 系统栏

    /** 让内容铺到状态栏和导航栏后面，只留安全边距——这样刘海那一条不再是一条灰带。 */
    private void applyInsets() {
        final View toolbar = findViewById(R.id.toolbar);
        final View inputRow = findViewById(R.id.input_row);

        if (Build.VERSION.SDK_INT >= 30) {
            getWindow().setDecorFitsSystemWindows(false);
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                // 背景固定纯黑，系统栏图标永远用亮色（白）。
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
            toolbar.setPadding(toolbar.getPaddingLeft(), top,
                    toolbar.getPaddingRight(), toolbar.getPaddingBottom());
            // 键盘弹起：输入区整体上移到键盘顶，列表底部同步让出同样高度。
            // 不用 padding 硬撑输入区（会重排、断输入法连接），用 translationY。
            int lift = Math.max(0, ime);
            inputRow.setPadding(inputRow.getPaddingLeft(), inputRow.getPaddingTop(),
                    inputRow.getPaddingRight(), bottom);
            inputRow.setTranslationY(-lift);
            View msgs = findViewById(R.id.messages);
            if (msgs != null) {
                msgs.setPadding(msgs.getPaddingLeft(), msgs.getPaddingTop(),
                        msgs.getPaddingRight(), lift);
            }
            return insets;
        });
    }

    // ------------------------------------------------------------ 语音

    private void initTts() {
        tts = new TextToSpeech(this, status -> {
            ttsReady = status == TextToSpeech.SUCCESS;
            if (!ttsReady) {
                return;
            }
            tts.setLanguage(Locale.CHINA);
            tts.setOnUtteranceProgressListener(new UtteranceProgressListener() {
                @Override
                public void onStart(String utteranceId) {
                }

                @Override
                public void onError(String utteranceId) {
                    ui.post(() -> {
                        if (callMode) {
                            startListening();
                        }
                    });
                }

                @Override
                public void onDone(String utteranceId) {
                    // 说完一句，接着听——像打电话那样
                    ui.post(() -> {
                        if (callMode) {
                            startListening();
                        }
                    });
                }
            });
        });
    }

    private void toggleCall() {
        if (callMode) {
            stopCall();
            return;
        }
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.RECORD_AUDIO}, REQ_MIC);
            return;
        }
        startCall();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions,
                                           int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_MIC && grantResults.length > 0
                && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
            startCall();
        }
    }

    private void startCall() {
        callMode = true;
        callBtn.setText("⏹");
        setStatus("通话中");
        addMessage(new Message(false, "（通话已接通，说话就行）",
                System.currentTimeMillis(), null), false);
        startListening();
    }

    private void stopCall() {
        callMode = false;
        callBtn.setText("🎧");
        if (recognizer != null) {
            try {
                recognizer.stopListening();
            } catch (Exception ignored) {
            }
        }
        if (ttsReady) {
            tts.stop();
        }
        setStatus("空闲");
    }

    private void startListening() {
        if (!callMode) {
            return;
        }
        if (recognizer == null) {
            recognizer = SpeechRecognizer.createSpeechRecognizer(this);
            recognizer.setRecognitionListener(new RecognitionListener() {
                @Override
                public void onReadyForSpeech(Bundle params) {
                }

                @Override
                public void onBeginningOfSpeech() {
                }

                @Override
                public void onRmsChanged(float rmsdB) {
                }

                @Override
                public void onBufferReceived(byte[] buffer) {
                }

                @Override
                public void onEndOfSpeech() {
                }

                @Override
                public void onError(int error) {
                    // 没听清/超时：过一会儿再听，别死循环
                    ui.postDelayed(() -> {
                        if (callMode) {
                            startListening();
                        }
                    }, 1200);
                }

                @Override
                public void onResults(Bundle results) {
                    ArrayList<String> list = results.getStringArrayList(
                            SpeechRecognizer.RESULTS_RECOGNITION);
                    if (list == null || list.isEmpty()) {
                        return;
                    }
                    String text = list.get(0);
                    if (text == null || text.trim().isEmpty()) {
                        return;
                    }
                    ui.post(() -> {
                        input.setText(text.trim());
                        send();
                    });
                }

                @Override
                public void onPartialResults(Bundle partialResults) {
                }

                @Override
                public void onEvent(int eventType, Bundle params) {
                }
            });
        }
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL,
                RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "zh-CN");
        try {
            recognizer.startListening(i);
        } catch (Exception ignored) {
        }
    }

    // ------------------------------------------------------------ 常驻

    /** 常驻服务：进程活着，Python 的连续性才在。 */
    private void startKeepAlive() {
        if (Build.VERSION.SDK_INT >= 33
                && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS)
                != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS}, REQ_NOTI);
        }
        Intent svc = new Intent(this, KeepAliveService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            startForegroundService(svc);
        } else {
            startService(svc);
        }
    }

    // ------------------------------------------------------------ 对话

    /** 人在输入区点「👁」：拍一张，让它看，然后针对看到的说一句。 */
    private void peek() {
        if (busy || engine == null) {
            return;
        }
        busy = true;
        setStatus("正在看…");
        new Thread(() -> {
            try {
                PyObject r = engine.callAttr("peek");
                String reply = r.callAttr("get", "reply").toString();
                String emo = r.callAttr("get", "emotions_text").toString();
                ui.post(() -> {
                    busy = false;
                    setStatus("空闲");
                    String e = (emo == null || emo.equals("None") || emo.isEmpty())
                            ? null : emo;
                    String text = (reply == null || reply.isEmpty() || "None".equals(reply))
                            ? "（看完了，没什么想说的）" : reply;
                    addMessage(new Message(false, text,
                            System.currentTimeMillis(), e), true);
                });
            } catch (Throwable e) {
                ui.post(() -> {
                    busy = false;
                    setStatus("空闲");
                    addMessage(new Message(false, "（看不了：" + e + "）",
                            System.currentTimeMillis(), null), false);
                });
            }
        }).start();
    }

    private void pickImage() {
        if (busy) {
            return;
        }
        Intent i = new Intent(Intent.ACTION_PICK);
        i.setType("image/*");
        startActivityForResult(i, REQ_PICK_IMAGE);
    }

    private void openSettings() {
        Intent i = new Intent(this, SettingsActivity.class);
        i.putExtra("agent_id", currentAgentId);
        startActivity(i);
    }

    private void openRecall() {
        Intent i = new Intent(this, RecallActivity.class);
        i.putExtra("agent_id", currentAgentId);
        startActivityForResult(i, REQ_RECALL);
    }

    private void send() {
        if (busy) {
            return;
        }
        String text = input.getText().toString().trim();
        if (text.isEmpty() || engine == null) {
            return;
        }

        input.setText("");
        addMessage(new Message(true, text, System.currentTimeMillis(), null), true);

        busy = true;
        setStatus("正在想…");
        if (callMode && recognizer != null) {
            try {
                recognizer.stopListening();
            } catch (Exception ignored) {
            }
        }

        new Thread(() -> runTurn(text, null)).start();
    }

    private void sendImage(Uri uri) {
        if (busy || engine == null) {
            return;
        }
        final byte[] bytes = compress(uri);
        if (bytes == null) {
            return;
        }

        addMessage(new Message(true, "（发了一张图片）", System.currentTimeMillis(), null), true);

        busy = true;
        setStatus("正在看…");
        if (callMode && recognizer != null) {
            try {
                recognizer.stopListening();
            } catch (Exception ignored) {
            }
        }

        new Thread(() -> runTurn("", bytes)).start();
    }

    /** 一轮对话的公共收尾：调引擎、判情绪、落库、回填界面。 */
    private void runTurn(String text, byte[] imageBytes) {
        try {
            PyObject r = imageBytes == null
                    ? engine.callAttr("turn", text)
                    : engine.callAttr("turn", text, imageBytes);
            String reply = r.callAttr("get", "reply").toString();
            String err = r.callAttr("get", "error").toString();
            String emo = r.callAttr("get", "emotions_text").toString();

            ui.post(() -> {
                busy = false;
                boolean failed = err != null && !err.isEmpty() && !err.equals("None");
                if (failed) {
                    setStatus(callMode ? "通话中" : "出错");
                    addMessage(new Message(false, "（" + err + "）",
                            System.currentTimeMillis(), null), false);
                    if (callMode) {
                        startListening();
                    }
                } else {
                    setStatus(callMode ? "通话中" : "空闲");
                    String e = (emo == null || emo.equals("None") || emo.isEmpty())
                            ? null : emo;
                    addMessage(new Message(false, reply,
                            System.currentTimeMillis(), e), true);
                    if (callMode && ttsReady) {
                        tts.speak(reply, TextToSpeech.QUEUE_FLUSH, null, "reply");
                    }
                }
            });
        } catch (Throwable e) {
            ui.post(() -> {
                busy = false;
                setStatus("断线");
                addMessage(new Message(false, "（调用失败：" + describe(e) + "）",
                        System.currentTimeMillis(), null), false);
                if (callMode) {
                    startListening();
                }
            });
        }
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (resultCode != RESULT_OK || data == null) {
            return;
        }
        if (requestCode == REQ_RECALL) {
            long ts = data.getLongExtra("ts", 0);
            if (ts > 0) {
                for (int i = 0; i < adapter.getCount(); i++) {
                    Message m = (Message) adapter.getItem(i);
                    if (m.ts >= ts) {
                        list.setSelection(i);
                        break;
                    }
                }
            }
        } else if (requestCode == REQ_PICK_IMAGE) {
            Uri uri = data.getData();
            if (uri != null) {
                sendImage(uri);
            }
        }
    }

    /** 相册图可能几千万像素，缩到 1024 以内再送——省流量也省 token。 */
    private byte[] compress(Uri uri) {
        try {
            InputStream in = getContentResolver().openInputStream(uri);
            Bitmap bmp = BitmapFactory.decodeStream(in);
            if (bmp == null) {
                return null;
            }
            int w = bmp.getWidth();
            int h = bmp.getHeight();
            int max = 1024;
            if (w > max || h > max) {
                float s = Math.min((float) max / w, (float) max / h);
                bmp = Bitmap.createScaledBitmap(bmp,
                        Math.max(1, (int) (w * s)), Math.max(1, (int) (h * s)), true);
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            bmp.compress(Bitmap.CompressFormat.JPEG, 80, out);
            return out.toByteArray();
        } catch (Exception e) {
            return null;
        }
    }

    private void addMessage(Message m, boolean persist) {
        adapter.add(m);
        adapter.notifyDataSetChanged();
        if (persist && db != null) {
            db.insert(currentAgentId, m.mine, m.text, m.ts, m.emotions);
        }
        list.smoothScrollToPosition(adapter.getCount() - 1);
    }

    private void setStatus(String s) {
        status.setText(s);
    }

    private String describe(Throwable e) {
        String msg = e.getMessage();
        return e.getClass().getSimpleName() + (msg == null ? "" : ": " + msg);
    }

    private void copyAsset(String name, File dest) {
        if (dest.exists()) {
            return;
        }
        try (InputStream in = getAssets().open(name);
             FileOutputStream out = new FileOutputStream(dest)) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
            }
        } catch (IOException ignored) {
            // 没有这个 asset 就算了，Python 侧有兜底
        }
    }
}
