# Framescreen2PDF v1.0.0

Framescreen2PDF 是一个本地 Web 工具，用于把图片、长截图、视频帧转换为 PDF 或 Word 文件。程序启动后会自动打开浏览器，所有处理都在本机完成，不上传文件、不需要账号、不依赖云服务。

## 启动方式

源码运行：

```bash
pip install -r requirements.txt
python web_app.py
```

Windows 便携版：

1. 解压发布包。
2. 双击 `Framescreen2PDF.exe`。
3. 浏览器自动打开 `http://127.0.0.1:18766/`。
4. 使用完成后，在页面右上角点击“关闭程序”。

## 功能

- 图片转 PDF/Word：多图上传、缩略图预览、删除、拖拽排序、布局、编号、页码、缩放模式、水印。
- 长截图转 PDF/Word：自动切片、缩略图预览、删除、拖拽排序、布局、编号、页码、水印。
- 视频转 PDF/Word：抽帧、首帧和尾帧保留、模糊过滤、可选图像去重、可选 OCR 辅助、手动框选主要区域、缩略图校对。
- PDF 导出：支持 A4 纵向、多布局、可选封面、哈希信息、斜向平铺水印。
- Word 导出：按页插入截图，图片自适应页面，支持编号。
- 任务历史：任务状态持久化，关闭/刷新浏览器或重启程序后可恢复下载列表（保留 7 天）。

## FFmpeg 视频组件

视频处理需要 FFmpeg。发布包不内置 FFmpeg。

普通用户推荐使用随附的 `FFmpeg-video-component-installer.zip`：

1. 解压附件。
2. 双击 `安装FFmpeg视频组件.bat`。
3. 按提示确认安装。
4. 安装完成后重新打开主程序。

官方地址：

- FFmpeg 官网: https://ffmpeg.org/
- 下载说明: https://ffmpeg.org/download.html

离线电脑可以让技术人员将 `ffmpeg.exe` 所在目录加入系统 PATH，或把 `ffmpeg.exe` 放到主程序同级的 `tools/ffmpeg/ffmpeg.exe`。

## OCR 可选组件

OCR 仅用于辅助视频帧筛选，不会把截图内容转换成文字稿。发布包不内置 OCR 依赖。

普通用户可使用随附的 `PaddleOCR-PaddlePaddle-optional-installer.zip`：

1. 解压附件到主程序 EXE 同级目录。
2. 双击 `安装PaddleOCR到程序目录.bat`。
3. 等待安装完成。
4. 重新打开主程序。

官方地址：

- PaddleOCR GitHub: https://github.com/PaddlePaddle/PaddleOCR
- PaddlePaddle 官网: https://www.paddlepaddle.org.cn/
- PaddleOCR PyPI: https://pypi.org/project/paddleocr/
- PaddlePaddle PyPI: https://pypi.org/project/paddlepaddle/

如果电脑不能联网，可在联网电脑运行安装脚本生成 `ocr/site-packages`，再把整个 `ocr` 文件夹复制到离线电脑的主程序 EXE 同级目录。

## 构建

源码包：

```bash
python scripts/build_release.py
```

Windows 包：

```bash
python scripts/build_exe.py --all
```

可选附件：

```bash
python scripts/build_ffmpeg_installer.py
python scripts/build_ocr_attachment.py
```
