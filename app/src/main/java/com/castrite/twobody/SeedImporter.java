package com.castrite.twobody;

import android.content.Context;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Arrays;

/**
 * 第一次启动时，把打包在 assets 里的两套记忆导进来。
 *
 *   assets/seed/chen/     陈长生的 memory_store + persona
 *   assets/seed/jinshan/  烬衫的 memory_store + persona
 *
 * 一套一个目录，各自独立。只在 agents 表为空时跑一次。
 */
public final class SeedImporter {

    private SeedImporter() {
    }

    /** 显示名。目录名是安全的 ASCII，名字这里给中文。 */
    private static String displayName(String folder) {
        if ("chen".equals(folder)) {
            return "陈长生";
        }
        if ("jinshan".equals(folder)) {
            return "烬衫";
        }
        return folder;
    }

    public static void seedIfNeeded(Context ctx) {
        AgentDb agentDb = new AgentDb(ctx);
        if (!agentDb.all().isEmpty()) {
            return;   // 已经有智能体了，不覆盖
        }

        String[] folders;
        try {
            folders = ctx.getAssets().list("seed");
        } catch (IOException e) {
            return;
        }
        if (folders == null || folders.length == 0) {
            return;
        }
        // 稳定顺序：chen 先，jinshan 后
        Arrays.sort(folders);

        for (String folder : folders) {
            long id = agentDb.create(displayName(folder));
            File dir = new File(ctx.getFilesDir(), "agents/a" + id);
            dir.mkdirs();

            try {
                copyTree(ctx, "seed/" + folder + "/memory_store",
                        new File(dir, "memory_store"));
                copyTree(ctx, "seed/" + folder + "/persona.txt",
                        new File(dir, "persona.txt"));
            } catch (IOException ignored) {
                // 某一套坏了不影响另一套
            }

            // 每个智能体都要有自己的 config.json
            File cfg = new File(dir, "config.json");
            if (!cfg.exists()) {
                try {
                    copyTree(ctx, "config.json", cfg);
                } catch (IOException ignored) {
                }
            }
        }
    }

    /** 递归复制一个 asset 目录（或单个文件）到本地磁盘。 */
    private static void copyTree(Context ctx, String assetPath, File dest)
            throws IOException {
        String[] children = ctx.getAssets().list(assetPath);
        if (children != null && children.length > 0) {
            if (!dest.exists() && !dest.mkdirs()) {
                throw new IOException("mkdir failed: " + dest);
            }
            for (String child : children) {
                copyTree(ctx, assetPath + "/" + child, new File(dest, child));
            }
        } else {
            File parent = dest.getParentFile();
            if (parent != null && !parent.exists() && !parent.mkdirs()) {
                throw new IOException("mkdir failed: " + parent);
            }
            try (InputStream in = ctx.getAssets().open(assetPath);
                 FileOutputStream out = new FileOutputStream(dest)) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) {
                    out.write(buf, 0, n);
                }
            }
        }
    }
}
