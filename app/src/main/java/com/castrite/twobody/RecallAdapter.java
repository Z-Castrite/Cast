package com.castrite.twobody;

import android.content.Context;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.TextView;

import java.text.SimpleDateFormat;
import java.util.Calendar;
import java.util.Date;
import java.util.List;
import java.util.Locale;

/** 回忆页列表：日期行 + 消息行混排。 */
public class RecallAdapter extends BaseAdapter {

    private final Context ctx;
    private final List<Object> items;

    public RecallAdapter(Context ctx, List<Object> items) {
        this.ctx = ctx;
        this.items = items;
    }

    @Override
    public int getCount() {
        return items.size();
    }

    @Override
    public Object getItem(int position) {
        return items.get(position);
    }

    @Override
    public long getItemId(int position) {
        return position;
    }

    @Override
    public int getViewTypeCount() {
        return 2;
    }

    @Override
    public int getItemViewType(int position) {
        return (items.get(position) instanceof TimelineDay) ? 0 : 1;
    }

    @Override
    public View getView(int position, View convert, ViewGroup parent) {
        Object o = items.get(position);

        if (o instanceof TimelineDay) {
            if (convert == null) {
                convert = LayoutInflater.from(ctx)
                        .inflate(R.layout.item_recall_day, parent, false);
            }
            TimelineDay d = (TimelineDay) o;
            TextView day = convert.findViewById(R.id.day);
            TextView meta = convert.findViewById(R.id.meta);
            day.setText(dayLabel(d.date));
            String a = new SimpleDateFormat("HH:mm", Locale.getDefault())
                    .format(new Date(d.firstTs));
            String b = new SimpleDateFormat("HH:mm", Locale.getDefault())
                    .format(new Date(d.lastTs));
            meta.setText(d.count + " 条 · " + a + "–" + b);
        } else {
            if (convert == null) {
                convert = LayoutInflater.from(ctx)
                        .inflate(R.layout.item_recall_msg, parent, false);
            }
            Message m = (Message) o;
            TextView time = convert.findViewById(R.id.time);
            TextView content = convert.findViewById(R.id.content);
            time.setText(TimeFmt.format(m.ts));
            content.setText(m.text);
        }
        return convert;
    }

    /** "2026-11-28" → "今天" / "昨天" / "11-28"。 */
    private String dayLabel(String date) {
        try {
            Date d = new SimpleDateFormat("yyyy-MM-dd", Locale.US).parse(date);
            Calendar c = Calendar.getInstance();
            c.setTime(d);
            Calendar now = Calendar.getInstance();
            Calendar y = (Calendar) now.clone();
            y.add(Calendar.DAY_OF_YEAR, -1);
            if (sameDay(now, c)) {
                return "今天";
            }
            if (sameDay(y, c)) {
                return "昨天";
            }
            return date.substring(5);
        } catch (Exception e) {
            return date;
        }
    }

    private boolean sameDay(Calendar a, Calendar b) {
        return a.get(Calendar.YEAR) == b.get(Calendar.YEAR)
                && a.get(Calendar.DAY_OF_YEAR) == b.get(Calendar.DAY_OF_YEAR);
    }
}
