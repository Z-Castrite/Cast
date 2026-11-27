package com.castrite.twobody;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import java.util.ArrayList;
import java.util.List;

/** 会话登记：单聊和群聊都在这。 */
public class ConversationDb extends SQLiteOpenHelper {

    private static final String DB_NAME = "conversations.db";
    private static final int VERSION = 1;

    public ConversationDb(Context ctx) {
        super(ctx, DB_NAME, null, VERSION);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE conversations ("
                + "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                + "title TEXT NOT NULL,"
                + "agent_ids TEXT NOT NULL,"
                + "is_group INTEGER NOT NULL DEFAULT 0,"
                + "created_at INTEGER NOT NULL)");
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // 加字段时在这里补
    }

    public long create(String title, List<Long> agentIds, boolean group) {
        ContentValues v = new ContentValues();
        v.put("title", title);
        v.put("agent_ids", Conversation.joinIds(agentIds));
        v.put("is_group", group ? 1 : 0);
        v.put("created_at", System.currentTimeMillis());
        return getWritableDatabase().insert("conversations", null, v);
    }

    public Conversation get(long id) {
        Cursor c = getReadableDatabase().query("conversations",
                new String[]{"id", "title", "agent_ids", "is_group"},
                "id = ?", new String[]{String.valueOf(id)}, null, null, null);
        try {
            if (c.moveToFirst()) {
                return new Conversation(c.getLong(0), c.getString(1),
                        Conversation.parseIds(c.getString(2)), c.getInt(3) == 1);
            }
        } finally {
            c.close();
        }
        return null;
    }

    public void rename(long id, String title) {
        ContentValues v = new ContentValues();
        v.put("title", title);
        getWritableDatabase().update("conversations", v, "id = ?",
                new String[]{String.valueOf(id)});
    }

    public List<Conversation> groups() {
        List<Conversation> out = new ArrayList<>();
        Cursor c = getReadableDatabase().query("conversations",
                new String[]{"id", "title", "agent_ids", "is_group"},
                "is_group = 1", null, null, null, "created_at DESC");
        try {
            while (c.moveToNext()) {
                out.add(new Conversation(c.getLong(0), c.getString(1),
                        Conversation.parseIds(c.getString(2)), true));
            }
        } finally {
            c.close();
        }
        return out;
    }
}
