"""
pipeline.py - 视频转 PDF 流程编排。
"""

from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from core.scanner import scan_videos
from core.extractor import extract_frames, check_ffmpeg
from core.dedup import dedup_frames
from core.pdf_builder import build_pdf, build_searchable_pdf
from utils.cleanup import TempDir

logger = logging.getLogger(__name__)


@dataclass
class VideoResult:
    video_name: str
    status: str = "pending"
    frames_extracted: int = 0
    frames_after_dedup: int = 0
    pdf_path: str = ""
    ocr_status: str = "OFF"
    elapsed: float = 0.0
    error: str = ""


@dataclass
class PipelineResult:
    total: int = 0
    success: int = 0
    skipped: int = 0
    failed: int = 0
    elapsed: float = 0.0
    videos: list = field(default_factory=list)


def _ensure_file_logger(log_dir: Path) -> None:
    root = logging.getLogger()
    has_file = any(isinstance(h, logging.FileHandler) for h in root.handlers)
    if has_file:
        return
    from utils.logger import setup_logger
    setup_logger(log_dir)


def run(args, progress_callback=None, log_callback=None) -> PipelineResult:
    """Execute the full pipeline."""
    input_dir = Path(args.input).resolve() if args.input else Path(".")
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    log_dir = Path(getattr(args, "log_dir", None) or Path(__file__).resolve().parent / "logs")
    _ensure_file_logger(log_dir)

    pipeline_start = time.time()
    result = PipelineResult()

    # FFmpeg check
    if log_callback:
        log_callback("scanning", "正在检查 FFmpeg...")
    try:
        ffmpeg_info = check_ffmpeg(getattr(args, "ffmpeg_path", None))
        if log_callback:
            log_callback("scanning", "FFmpeg 可用: " + ffmpeg_info[:60])
    except Exception as e:
        if log_callback:
            log_callback("error", "FFmpeg 不可用: " + str(e))
        raise

    # OCR
    ocr = getattr(args, "ocr", False)
    ocr_engine = None
    if ocr:
        if log_callback:
            log_callback("scanning", "OCR 已启用，正在检查引擎...")
        from core.ocr import get_ocr_engine
        ocr_engine = get_ocr_engine(getattr(args, "ocr_lang", "auto"))

    # Video list
    video_files = getattr(args, "video_files", None)
    if video_files:
        videos = [Path(v) for v in video_files]
        if log_callback:
            log_callback("scanning", "使用已选择的视频文件: %d 个" % len(videos))
    else:
        if log_callback:
            log_callback("scanning", "正在扫描: " + str(input_dir))
        videos = scan_videos(input_dir)
        if log_callback:
            log_callback("scanning", "扫描完成，找到 %d 个视频" % len(videos))

    if not videos:
        if log_callback:
            log_callback("error", "未找到视频文件")
        return result

    result.total = len(videos)

    # Initial progress: 0 / total
    if progress_callback:
        progress_callback(0, result.total, "")

    for idx, video_path in enumerate(videos, 1):
        logger.info("[%d/%d] Processing: %s", idx, result.total, video_path.name)

        vr = _process_one_video(
            video_path=video_path, output_dir=output_dir,
            fps=getattr(args, "fps", 1.0),
            pdf_mode=getattr(args, "pdf_mode", "compressed"),
            dedup=getattr(args, "dedup", True),
            dedup_mode=getattr(args, "dedup_mode", "consecutive"),
            dedup_threshold=getattr(args, "dedup_threshold", 10),
            ffmpeg_path=getattr(args, "ffmpeg_path", None),
            crop_ratio=getattr(args, "crop_ratio", None),
            crop_pixels=getattr(args, "crop_pixels", None),
            ocr_engine=ocr_engine,
            overwrite=getattr(args, "overwrite", "auto_rename"),
            log_callback=log_callback,
            current=idx,
            total=result.total,
        )
        result.videos.append(vr)
        if vr.status == "OK":
            result.success += 1
        elif vr.status == "skipped":
            result.skipped += 1
        else:
            result.failed += 1

        # Update progress AFTER completion
        if progress_callback:
            progress_callback(idx, result.total, video_path.name)

    result.elapsed = time.time() - pipeline_start
    if log_callback:
        parts = []
        parts.append("完成: %d 成功" % result.success)
        if result.skipped:
            parts.append("%d 跳过" % result.skipped)
        if result.failed:
            parts.append("%d 失败" % result.failed)
        parts.append("(%.1f秒)" % result.elapsed)
        log_callback("done", ", ".join(parts))
    return result


def _resolve_output_path(output_dir: Path, stem: str, strategy: str) -> tuple:
    """
    根据覆盖策略计算输出路径。
    Returns: (Path, suffix_message) 其中 suffix_message 是显示给用户的说明。
    """
    if strategy == "overwrite":
        return output_dir / (stem + ".pdf"), ""

    if strategy == "skip":
        target = output_dir / (stem + ".pdf")
        if target.exists():
            return None, ""
        return target, ""

    if strategy == "auto_rename":
        target = output_dir / (stem + ".pdf")
        if not target.exists():
            return target, ""
        for i in range(1, 1000):
            target = output_dir / f"{stem}_{i}.pdf"
            if not target.exists():
                return target, f"文件已存在，自动改名为：{target.name}"
        return output_dir / f"{stem}_999.pdf", ""

    raise ValueError("Unknown overwrite strategy: " + str(strategy))


def _process_one_video(
    video_path, output_dir, fps, pdf_mode,
    dedup, dedup_mode, dedup_threshold,
    ffmpeg_path, crop_ratio, crop_pixels,
    ocr_engine, overwrite, log_callback, current, total,
) -> VideoResult:
    vr = VideoResult(video_name=video_path.name)
    start = time.time()
    try:
        # Resolve output path with overwrite strategy
        pdf_path, rename_msg = _resolve_output_path(output_dir, video_path.stem, overwrite)
        if pdf_path is None:
            # skip: file exists, skip this video
            vr.status = "skipped"
            vr.elapsed = time.time() - start
            if log_callback:
                log_callback("info", "  文件已存在，已跳过：%s" % video_path.name)
            logger.info("Skipped (file exists): %s", video_path.name)
            return vr

        if log_callback:
            log_callback("extracting", "正在处理 %d/%d: %s" % (current, total, video_path.name))

        with TempDir() as tmp:
            if log_callback:
                log_callback("extracting", "  正在抽帧...")
            frames = extract_frames(
                video_path, fps, tmp,
                ffmpeg_path=ffmpeg_path,
                crop_ratio=crop_ratio,
                crop_pixels=crop_pixels,
            )
            vr.frames_extracted = len(frames)
            if log_callback:
                log_callback("extracting", "  抽帧完成: %d 帧" % len(frames))

            if dedup:
                if log_callback:
                    log_callback("dedup", "  正在去重...")
                frames = dedup_frames(frames, dedup_threshold, dedup_mode)
                vr.frames_after_dedup = len(frames)
                if log_callback:
                    log_callback("dedup", "  去重完成: %d -> %d 帧" % (vr.frames_extracted, len(frames)))
            else:
                vr.frames_after_dedup = len(frames)

            if log_callback:
                log_callback("pdf", "  正在生成 PDF...")

            if ocr_engine is not None:
                ocr_results = [ocr_engine.recognize(f) for f in frames]
                build_searchable_pdf(frames, ocr_results, pdf_path, pdf_mode=pdf_mode)
                vr.ocr_status = "OK"
            else:
                build_pdf(frames, pdf_path, pdf_mode=pdf_mode)
                vr.ocr_status = "OFF"

            vr.pdf_path = str(pdf_path)
            vr.status = "OK"
            if log_callback:
                log_callback("pdf", "  PDF 完成: " + pdf_path.name)
            if rename_msg:
                if log_callback:
                    log_callback("info", "  " + rename_msg)
                logger.info("%s: %s", video_path.name, rename_msg)

    except Exception as e:
        vr.status = "ERROR"
        vr.error = str(e)
        logger.error("Failed: %s: %s", video_path.name, e)
        if log_callback:
            log_callback("error", "  错误: " + video_path.name + ": " + str(e))

    vr.elapsed = time.time() - start
    return vr
