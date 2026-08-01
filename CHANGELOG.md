# Changelog

## v1.0.0 - 2026-06-13

- 产品名更新为 `Framescreen2PDF`。
- 支持图片、长截图、视频帧转换为 PDF/Word。
- 新增 Word 证据文档导出（Full 版）：按页插图、图片自适应、可编号。
- 新增 Full / Lite 双版本打包：Lite 不含 Word 导出与水印选项。
- 新增 FFmpeg 视频组件 / PaddleOCR 可选安装附件构建脚本。
- PDF 水印改为斜向平铺样式。
- 视频抽帧保留首帧，并额外补抓视频末尾画面。
- OCR 改为可选能力，初始化异常时自动降级，不中断视频处理。
- 正式包不内置 FFmpeg，提供 FFmpeg 辅助安装附件。
- OCR 依赖不内置，提供 PaddleOCR/PaddlePaddle 可选安装附件。
- 打包改为无控制台窗口，并在页面提供“关闭程序”按钮。
