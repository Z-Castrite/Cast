package com.castrite.twobody;

/** 回忆页时间轴的一行：某一天有几条消息、从什么时候到什么时候。 */
public class TimelineDay {

    public final String date;   // yyyy-MM-dd
    public final int count;
    public final long firstTs;
    public final long lastTs;

    public TimelineDay(String date, int count, long firstTs, long lastTs) {
        this.date = date;
        this.count = count;
        this.firstTs = firstTs;
        this.lastTs = lastTs;
    }
}
