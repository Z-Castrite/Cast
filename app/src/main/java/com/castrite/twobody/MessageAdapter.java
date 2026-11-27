package com.castrite.twobody;

import android.content.Context;
import android.graphics.drawable.GradientDrawable;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.BaseAdapter;
import android.widget.TextView;

import java.util.ArrayList;
import java.util.List;

/** 消息列表适配器。两种条目：左边（它）、右边（你）。头像用圆底首字。 */
public class MessageAdapter extends BaseAdapter {

    private static final int[] COLORS = {
            0xFF2563EB, 0xFF7C3AED, 0xFFDB2777, 0xFFEA580C,
            0xFF16A34A, 0xFF0891B2, 0xFFCA8A04, 0xFF4B5563
    };

    private final Context ctx;
    private final List<Message> items = new ArrayList<>();
    private String peerName = "";

    public MessageAdapter(Context ctx) {
        this.ctx = ctx;
    }

    public void setPeerName(String name) {
        this.peerName = name == null ? "" : name;
    }

    public void add(Message m) {
        items.add(m);
    }

    public void clear() {
        items.clear();
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
        return items.get(position).mine ? 1 : 0;
    }

    @Override
    public View getView(int position, View convert, ViewGroup parent) {
        Message m = items.get(position);

        if (convert == null) {
            int layout = m.mine ? R.layout.item_msg_right : R.layout.item_msg_left;
            convert = LayoutInflater.from(ctx).inflate(layout, parent, false);
        }

        TextView time = convert.findViewById(R.id.time);
        TextView bubble = convert.findViewById(R.id.bubble);
        TextView emotions = convert.findViewById(R.id.emotions);
        TextView avatar = convert.findViewById(R.id.avatar);

        time.setText(m.sender != null && !m.sender.isEmpty()
                ? TimeFmt.format(m.ts) + " · " + m.sender
                : TimeFmt.format(m.ts));
        bubble.setText(m.text);

        if (m.emotions != null && !m.emotions.isEmpty()) {
            emotions.setVisibility(View.VISIBLE);
            emotions.setText(m.emotions);
        } else {
            emotions.setVisibility(View.GONE);
        }

        bindAvatar(avatar, avatarLabel(m));
        return convert;
    }

    private String avatarLabel(Message m) {
        if (m.mine) {
            return "你";
        }
        if (m.sender != null && !m.sender.isEmpty()) {
            return m.sender;
        }
        return peerName;
    }

    private void bindAvatar(TextView tv, String label) {
        if (tv == null) {
            return;
        }
        if (label == null || label.isEmpty()) {
            tv.setVisibility(View.GONE);
            return;
        }
        tv.setVisibility(View.VISIBLE);
        tv.setText(label.substring(0, 1));

        GradientDrawable bg = new GradientDrawable();
        bg.setShape(GradientDrawable.OVAL);
        bg.setColor(colorFor(label));
        tv.setBackground(bg);
    }

    private int colorFor(String label) {
        if ("你".equals(label)) {
            return 0xFF374151;
        }
        if ("系统".equals(label)) {
            return 0xFF6B7280;
        }
        return COLORS[Math.abs(label.hashCode()) % COLORS.length];
    }
}
