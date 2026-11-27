package com.castrite.twobody;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;

import java.util.ArrayList;
import java.util.List;

/**
 * 智能体登记表。
 *
 * 它只管"有谁"这件事。真正的身体（persona / config / memory_store）在
 * files/agents/a<id>/ 里，一套一个，物理隔离。
 */
public class AgentDb extends SQLiteOpenHelper {

    private static final String DB_NAME = "agents.db";
    private static final int VERSION = 1;

    public AgentDb(Context ctx) {
        super(ctx, DB_NAME, null, VERSION);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        db.execSQL("CREATE TABLE agents ("
                + "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                + "name TEXT NOT NULL,"
                + "avatar_uri TEXT,"
                + "created_at INTEGER NOT NULL,"
                + "last_used_at INTEGER NOT NULL)");
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // 加字段时在这里补
    }

    /** 一张表都没有的时候，建第一个它。返回 id。 */
    public long ensureDefault(String name) {
        List<Agent> all = all();
        if (all.isEmpty()) {
            return create(name);
        }
        // 默认打开最早建的那个（all() 是按最近使用排的，这里要的是"第一个它"）
        long earliest = all.get(0).id;
        for (Agent a : all) {
            if (a.id < earliest) {
                earliest = a.id;
            }
        }
        return earliest;
    }

    public long create(String name) {
        ContentValues v = new ContentValues();
        long now = System.currentTimeMillis();
        v.put("name", name);
        v.put("created_at", now);
        v.put("last_used_at", now);
        return getWritableDatabase().insert("agents", null, v);
    }

    public List<Agent> all() {
        List<Agent> out = new ArrayList<>();
        Cursor c = getReadableDatabase().query("agents",
                new String[]{"id", "name"}, null, null, null, null, "last_used_at DESC");
        try {
            while (c.moveToNext()) {
                out.add(new Agent(c.getLong(0), c.getString(1)));
            }
        } finally {
            c.close();
        }
        return out;
    }

    public Agent get(long id) {
        Cursor c = getReadableDatabase().query("agents",
                new String[]{"id", "name"}, "id = ?",
                new String[]{String.valueOf(id)}, null, null, null);
        try {
            if (c.moveToFirst()) {
                return new Agent(c.getLong(0), c.getString(1));
            }
        } finally {
            c.close();
        }
        return null;
    }

    public void touch(long id) {
        ContentValues v = new ContentValues();
        v.put("last_used_at", System.currentTimeMillis());
        getWritableDatabase().update("agents", v, "id = ?",
                new String[]{String.valueOf(id)});
    }

    public void rename(long id, String name) {
        ContentValues v = new ContentValues();
        v.put("name", name);
        getWritableDatabase().update("agents", v, "id = ?",
                new String[]{String.valueOf(id)});
    }
}
