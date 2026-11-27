package com.castrite.twobody;

/** 一条消息。mine=true 表示用户发的（右侧），false 表示它说的（左侧）。 */
public class Message {

    public final boolean mine;
    public final String text;
    public final long ts;
    public final String emotions;   // 情绪微标，可空
    public final String sender;     // 群聊里谁说的；单聊为 null

    public Message(boolean mine, String text, long ts, String emotions) {
        this(mine, text, ts, emotions, null);
    }

    public Message(boolean mine, String text, long ts, String emotions, String sender) {
        this.mine = mine;
        this.text = text;
        this.ts = ts;
        this.emotions = emotions;
        this.sender = sender;
    }
}
