# ChatScreen2PDF

批量将聊天录屏视频转换为 PDF 文件。完全本地运行，不上传任何数据。

## 版本状态

| 模式 | 版本 | 状态 |
|------|------|------|
| 普通 PDF | v0.3.5 | **已验收，当前主线** |
| 可搜索 PDF (OCR) | v0.3.5 | **Experimental** — 默认关闭，不推荐普通用户使用 |

## 功能

- 批量处理：扫描文件夹中所有视频，逐个转换
- 普通 PDF：视频抽帧 → aHash 去重 → 合成 PDF（**已验收**）
- 智能去重：aHash 感知哈希，consecutive / global 两种模式
- 多格式支持：MP4、MOV、AVI、MKV、WEBM
- Crop 裁剪：去除录屏中状态栏、导航栏等无关区域
- 输出覆盖保护：默认 auto_rename，不会覆盖已有 PDF
- 中文支持：中文文件名、中文路径

## 安装

### 依赖安装

```bash
pip install -r requirements.txt
```

### FFmpeg

源码版需要系统可访问 FFmpeg：

- **Windows**：下载 https://www.gyan.dev/ffmpeg/builds/ 并将 `bin/` 目录加入 PATH
- **Linux**：`sudo apt install ffmpeg`
- **macOS**：`brew install ffmpeg`

验证安装：

```bash
ffmpeg -version
```

## 使用

### GUI 启动

```bash
python gui_app.py
```

### CLI 启动

```bash
# 基本用法
python main.py --input ./videos --output ./pdfs

# 带裁剪（归一化比例，保留左侧10%到右侧90%）
python main.py --input ./videos --output ./pdfs --crop-ratio 0.1,0.0,0.9,1.0

# 带裁剪（像素坐标）
python main.py --input ./videos --output ./pdfs --crop-pixels 0:100:1080:1800
```

### 完整参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--input` | (必填) | 输入视频文件夹 |
| `--output` | (必填) | 输出 PDF 文件夹 |
| `--fps` | 1 | 抽帧频率（0.5/1/2/3/5） |
| `--dedup` | true | 是否去重 |
| `--dedup-mode` | consecutive | consecutive / global |
| `--dedup-threshold` | 10 | 去重阈值 |
| `--pdf-mode` | compressed | lossless / compressed |
| `--crop-ratio` | (无) | 归一化裁剪 x1,y1,x2,y2（0.0-1.0） |
| `--crop-pixels` | (无) | 像素裁剪 left:top:width:height |
| `--overwrite` | auto_rename | 输出冲突策略：auto_rename / overwrite / skip |
| `--ffmpeg-path` | (自动) | 手动指定 FFmpeg 路径 |
| `--ocr` | false | OCR is experimental and not recommended for normal use. |
| `--ocr-lang` | auto | zh/en/ja/auto |

### 输出路径说明

- **GUI 模式**：默认输出到视频所在目录或输入目录
- **CLI 模式**：输出到 `--output` 指定目录

### 输出覆盖规则

默认 **auto_rename**，不会覆盖已有 PDF：

- `auto_rename`（默认）：同名文件自动生成 `_1`、`_2`、`_3` 后缀
- `overwrite`：直接覆盖已有文件
- `skip`：跳过已有文件（不生成 PDF，不计入失败）

### OCR 限制

- OCR 是实验性功能（Experimental），默认关闭
- 不推荐普通用户使用
- 需额外安装 PaddleOCR：`pip install paddleocr paddlepaddle`
- Windows Portable 版不包含 OCR

## 常见错误

| 错误 | 原因 | 解决 |
|------|------|------|
| FFmpeg not found | 未安装 FFmpeg 或不在 PATH 中 | 安装 FFmpeg 并加入 PATH，或使用 `--ffmpeg-path` |
| No video files found | 输入目录无支持的视频文件 | 确认目录包含 .mp4/.mov/.avi/.mkv/.webm 文件 |
| 输出目录无权限 | 程序无写入权限 | 更换输出目录或以管理员身份运行 |
| ModuleNotFoundError: No module named 'PySide6' | 未安装 GUI 依赖 | `pip install PySide6` |
| OCREngineNotAvailableError | 启用了 OCR 但未安装 PaddleOCR | 关闭 OCR（默认关闭）或安装 PaddleOCR |

## 测试

```bash
# 自定义测试运行器
python run_tests.py

# pytest 运行
python -m pytest -q
```

## 打包

```bash
# Windows Portable（需安装 PyInstaller）
python scripts/build_exe.py

# 源码发布包
python scripts/build_release.py
```
