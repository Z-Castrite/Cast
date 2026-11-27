package com.castrite.twobody;

import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.Locale;

/**
 * 消息时间格式。按 UI-SPEC 4.1：
 *   今天 → 14:30 / 昨天 → 昨天 14:30 / 今年更早 → 11-27 14:30 / 跨年 → 2025-12-31 14:30
 */
public final class TimeFmt {

    private TimeFmt() {
    }

    public static String format(long ts) {
        Calendar now = Calendar.getInstance();
        Calendar t = Calendar.getInstance();
        t.setTimeInMillis(ts);

        String hm = new SimpleDateFormat("HH:mm", Locale.getDefault())
                .format(new Date(ts));

        if (now.get(Calendar.YEAR) != t.get(Calendar.YEAR)) {
            return new SimpleDateFormat("yyyy-MM-dd HH:mm", Locale.getDefault())
                    .format(new Date(ts));
        }
        if (sameDay(now, t)) {
            return hm;
        }
        Calendar yesterday = (Calendar) now.clone();
        yesterday.add(Calendar.DAY_OF_YEAR, -1);
        if (sameDay(yesterday, t)) {
            return "昨天 " + hm;
        }
        return new SimpleDateFormat("MM-dd HH:mm", Locale.getDefault())
                .format(new Date(ts));
    }

    private static boolean sameDay(Calendar a, Calendar b) {
        return a.get(Calendar.YEAR) == b.get(Calendar.YEAR)
                && a.get(Calendar.DAY_OF_YEAR) == b.get(Calendar.DAY_OF_YEAR);
    }
}
