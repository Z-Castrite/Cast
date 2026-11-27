package com.castrite.twobody;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import java.util.ArrayList;
import java.util.List;

/**
 * 聊天记录（SQLite）。
 *
 * 只存给界面看的消息。它自己的记忆不在这里——那是各 agent 目录下的
 * memory_store/ JSONL，归 Python 管。
 *
 * v2 加 agent_id：每个智能体只看见自己的单聊记录。
 * v3 加 conversation_id + sender：群聊用 conversation_id 分池，
 *    sender 记谁说的（用户为 null，智能体为它的名字）。
 */
public class ChatDb extends SQLiteOpenHelper {

    private static final String DB_NAME = "chat.db";
    private static final int VERSION = 3;

    /** 单聊消息的 conversation_id。 */
    public static final long SINGLE = -1;

    public ChatDb(Context ctx) {
        super(ctx, DB_NAME, null, VERSION);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE messages ("
                + "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                + "agent_id INTEGER NOT NULL DEFAULT 1,"
                + "conversation_id INTEGER NOT NULL DEFAULT -1,"
                + "sender TEXT,"
                + "role TEXT NOT NULL,"
                + "content TEXT NOT NULL DEFAULT '',"
                + "ts INTEGER NOT NULL,"
                + "emotions TEXT,"
                + "image_uri TEXT,"
                + "source TEXT NOT NULL DEFAULT 'chat')");
        db.execSQL("CREATE INDEX idx_msg_ts ON messages(ts)");
        db.execSQL("CREATE INDEX idx_msg_agent ON messages(agent_id, ts)");
        db.execSQL("CREATE INDEX idx_msg_conv ON messages(conversation_id, ts)");
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if (oldVersion < 2) {
            db.execSQL("ALTER TABLE messages ADD COLUMN agent_id INTEGER NOT NULL DEFAULT 1");
            db.execSQL("CREATE INDEX IF NOT EXISTS idx_msg_agent ON messages(agent_id, ts)");
        }
        if (oldVersion < 3) {
            db.execSQL("ALTER TABLE messages ADD COLUMN conversation_id INTEGER NOT NULL DEFAULT -1");
            db.execSQL("ALTER TABLE messages ADD COLUMN sender TEXT");
            db.execSQL("CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conversation_id, ts)");
        }
    }

    // ------------------------------------------------------------ 单聊

    public void insert(long agentId, boolean mine, String content, long ts, String emotions) {
        ContentValues v = new ContentValues();
        v.put("agent_id", agentId);
        v.put("conversation_id", SINGLE);
        v.put("role", mine ? "user" : "assistant");
        v.put("content", content);
        v.put("ts", ts);
        v.put("emotions", emotions);
        v.put("source", "chat");
        getWritableDatabase().insert("messages", null, v);
    }

    /** 最近 limit 条，按时间正序返回。 */
    public List<Message> recent(long agentId, int limit) {
        List<Message> out = new ArrayList<>();
        String sql = "SELECT role, content, ts, emotions FROM ("
                + "SELECT role, content, ts, emotions FROM messages"
                + " WHERE agent_id = " + agentId + " AND conversation_id = " + SINGLE
                + " ORDER BY ts DESC LIMIT " + limit
                + ") ORDER BY ts ASC";
        Cursor c = getReadableDatabase().rawQuery(sql, null);
        try {
            while (c.moveToNext()) {
                out.add(new Message("user".equals(c.getString(0)), c.getString(1),
                        c.getLong(2), c.isNull(3) ? null : c.getString(3)));
            }
        } finally {
            c.close();
        }
        return out;
    }

    public List<TimelineDay> timeline(long agentId) {
        List<TimelineDay> out = new ArrayList<>();
        String sql = "SELECT date(ts/1000,'unixepoch','localtime') AS d,"
                + " count(*), min(ts), max(ts) FROM messages"
                + " WHERE agent_id = " + agentId + " AND conversation_id = " + SINGLE
                + " GROUP BY d ORDER BY d DESC";
        Cursor c = getReadableDatabase().rawQuery(sql, null);
        try {
            while (c.moveToNext()) {
                out.add(new TimelineDay(c.getString(0), c.getInt(1),
                        c.getLong(2), c.getLong(3)));
            }
        } finally {
            c.close();
        }
        return out;
    }

    public List<Message> search(long agentId, String keyword, int limit) {
        List<Message> out = new ArrayList<>();
        String sql = "SELECT role, content, ts, emotions FROM messages"
                + " WHERE agent_id = " + agentId + " AND conversation_id = " + SINGLE
                + " AND content LIKE ? ORDER BY ts DESC LIMIT " + limit;
        Cursor c = getReadableDatabase().rawQuery(sql, new String[]{"%" + keyword + "%"});
        try {
            while (c.moveToNext()) {
                out.add(new Message("user".equals(c.getString(0)), c.getString(1),
                        c.getLong(2), c.isNull(3) ? null : c.getString(3)));
            }
        } finally {
            c.close();
        }
        return out;
    }

    public void clear(long agentId) {
        getWritableDatabase().delete("messages",
                "agent_id = ? AND conversation_id = ?",
                new String[]{String.valueOf(agentId), String.valueOf(SINGLE)});
    }

    // ------------------------------------------------------------ 群聊

    public void insertGroup(long convId, boolean mine, String content, long ts,
                            String emotions, String sender) {
        ContentValues v = new ContentValues();
        v.put("agent_id", 0);
        v.put("conversation_id", convId);
        v.put("sender", sender);
        v.put("role", mine ? "user" : "assistant");
        v.put("content", content);
        v.put("ts", ts);
        v.put("emotions", emotions);
        v.put("source", "group");
        getWritableDatabase().insert("messages", null, v);
    }

    public List<Message> groupMessages(long convId, int limit) {
        List<Message> out = new ArrayList<>();
        String sql = "SELECT role, content, ts, emotions, sender FROM ("
                + "SELECT role, content, ts, emotions, sender FROM messages"
                + " WHERE conversation_id = " + convId
                + " ORDER BY ts DESC LIMIT " + limit
                + ") ORDER BY ts ASC";
        Cursor c = getReadableDatabase().rawQuery(sql, null);
        try {
            while (c.moveToNext()) {
                out.add(new Message("user".equals(c.getString(0)), c.getString(1),
                        c.getLong(2), c.isNull(3) ? null : c.getString(3),
                        c.isNull(4) ? null : c.getString(4)));
            }
        } finally {
            c.close();
        }
        return out;
    }
}
