# Changelog

## v0.3.5 - 2026-06-10

### Fixed

- 版本一致性：__version__.py / README / CHANGELOG / GUI 标题统一为 v0.3.5
- OCR 状态处理：GUI 完全隐藏 OCR；CLI --ocr help 明确 Experimental 警告
- 输出文件覆盖保护：新增 `--overwrite` 参数（auto_rename / overwrite / skip），默认 auto_rename
- 测试运行器健壮化：单个测试模块 import 失败不影响其他模块运行
- README 补全真实使用说明（GUI/CLI 启动方式、FFmpeg 说明、常见错误等）

### Added

- `--overwrite` CLI 参数，三种输出冲突策略
- `PipelineResult.skipped` 字段，skip 策略时不计入 failed
- auto_rename 日志提示最终输出文件名

### Changed

- 默认输出策略从无声覆盖改为 auto_rename（自动改名）
- README 全面更新为 v0.3.5 主线

## v0.2.0 - 2026-06-10

### Added

- Built-in FFmpeg: Windows Portable version bundles ffmpeg.exe, no separate install needed
- Crop feature: `--crop-ratio x1,y1,x2,y2` (normalized 0.0-1.0) and `--crop-pixels left:top:width:height` (pixel coordinates)
- `--ffmpeg-path` parameter to manually specify FFmpeg location
- Windows Portable (onedir) packaging via PyInstaller
- Crop validation: rejects out-of-range, wrong-length, and reversed coordinates

### Changed

- Version bumped to 0.2.0
- OCR marked as Experimental (code retained, not actively developed)

### Known Limitations

- Windows Portable .exe size ~150MB (includes FFmpeg + Python runtime)
- OCR mode requires separate PaddleOCR installation and may have compatibility issues
- Linux/macOS Portable builds not yet supported

## v0.1.0 - 2026-06-10

### Added

- Batch video scanning (recursive, mp4/mov/avi/mkv/webm)
- FFmpeg frame extraction (configurable fps)
- aHash deduplication (consecutive and global modes)
- PDF generation (compressed and lossless modes)
- Chinese filename support
- Structured logging
- Temporary file cleanup
- CLI interface with --version support
