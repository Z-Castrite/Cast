# twobody-app

手机上跑的 twobody。白板实验版：能对话、能记忆、能判情绪、能自己翻记忆、能看图。

## 现在到哪一步

**M1**：只验证一件事——GitHub Actions 能不能把这个工程打成 APK。

工程目前是空的：一个 Activity，屏幕上只有一行 `twobody · hello`。没有 Python，没有界面，没有任何业务。

## 构建

推上去之后，GitHub 会自动跑 `build-apk`。也可以在仓库的 **Actions** 页手动点 **Run workflow**。

构建成功后在这次运行的 **Artifacts** 里下载 `twobody-debug-apk`，解压得到 `app-debug.apk`，传手机装上。

## 目录

```
app/src/main/java/com/castrite/twobody/MainActivity.java   M1 的入口
app/src/main/res/layout/activity_main.xml                  一屏 hello
.github/workflows/build.yml                                CI
UI-SPEC.md                                                 界面规格（已定稿）
design/ui-sketch-2026-11-28.png                            手绘原图
```

## 版本

| 项 | 版本 | 为什么不升 |
|---|---|---|
| JDK | 17 | AGP 8.5 要求 |
| Gradle | 8.7 | 和 AGP 8.5 配套 |
| AGP | 8.5.2 | 稳 |
| compileSdk | 34 | 对应 AGP 8.5 |
| minSdk | 26 | 8.0，够老也不用兼容太多 |

---

> 本项目由 AI 创作（陈长生，基于 DeepSeek）。
> 代码、UI、提示词、构建配置均由 AI 根据对话需求生成。

