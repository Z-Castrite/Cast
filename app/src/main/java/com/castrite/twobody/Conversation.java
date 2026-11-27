package com.castrite.twobody;

import java.util.ArrayList;
import java.util.List;

/** 一个会话：单聊（1 个 agent）或群聊（N 个）。 */
public class Conversation {

    public final long id;
    public final String title;
    public final List<Long> agentIds;
    public final boolean group;

    public Conversation(long id, String title, List<Long> agentIds, boolean group) {
        this.id = id;
        this.title = title;
        this.agentIds = agentIds;
        this.group = group;
    }

    /** "1,2" → [1, 2] */
    public static List<Long> parseIds(String s) {
        List<Long> out = new ArrayList<>();
        if (s == null || s.trim().isEmpty()) {
            return out;
        }
        for (String p : s.split(",")) {
            p = p.trim();
            if (p.isEmpty()) {
                continue;
            }
            try {
                out.add(Long.parseLong(p));
            } catch (NumberFormatException ignored) {
            }
        }
        return out;
    }

    public static String joinIds(List<Long> ids) {
        StringBuilder sb = new StringBuilder();
        for (int i = 0; i < ids.size(); i++) {
            if (i > 0) {
                sb.append(",");
            }
            sb.append(ids.get(i));
        }
        return sb.toString();
    }
}
