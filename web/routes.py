"""
web/routes.py — FastAPI 路由：图片上传、PDF 生成、状态查询、下载。
"""

import logging
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from core.pdf_builder import build_grid_pdf

logger = logging.getLogger(__name__)

# FastAPI 应用
app = FastAPI(title="ChatScreen2PDF", version="1.0.0-ocr-ready")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter()

# 支持的图片扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}

# 临时文件根目录
TEMP_ROOT = Path(tempfile.gettempdir()) / "chatScreen2pdf_web"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


# ── 任务状态模型 ────────────────────────────────────────────

class JobStatus(BaseModel):
    job_id: str
    status: str  # pending / processing / done / error
    total: int = 0
    current: int = 0
    logs: list = []
    result_filename: str = ""
    error: str = ""


# 内存任务存储
_jobs: dict[str, dict] = {}


# ── 工具函数 ────────────────────────────────────────────────

def _cleanup_job(job_id: str) -> None:
    """清理任务临时文件。"""
    job = _jobs.get(job_id)
    if job and job.get("temp_dir"):
        try:
            shutil.rmtree(job["temp_dir"], ignore_errors=True)
        except Exception:
            pass


def _process_job(job_id: str) -> None:
    """后台处理任务：校验图片 → 生成 PDF → 更新状态。"""
    job = _jobs.get(job_id)
    if not job:
        return
    try:
        total = job["total"]
        job["current"] = 0
        job["status"] = "processing"
        job["logs"].append(("info", f"开始处理 {total} 张图片..."))

        image_paths = []
        # 校验所有图片
        for idx, (filename, temp_path) in enumerate(job["files"]):
            image_paths.append(temp_path)
            try:
                from PIL import Image
                with Image.open(temp_path) as _:
                    pass
            except Exception as e:
                raise ValueError(f"图片读取失败: {filename} — {e}")
            job["current"] = idx + 1
            job["logs"].append(("info", f"已校验: {filename} ({idx+1}/{total})"))

        # 确定输出文件名
        first_stem = Path(job["files"][0][0]).stem
        scale_mode = job.get("scale_mode", "fit")
        layout = job.get("layout", "2x2")
        direction = job.get("direction", "lr")
        title = job.get("title", "")
        show_number = job.get("show_number", True)
        show_page_number = job.get("show_page_number", False)
        output_path = Path(job["temp_dir"]) / f"{first_stem}.pdf"

        job["logs"].append(("info", f"正在生成 PDF (布局: {layout}, 缩放: {scale_mode})..."))
        if job.get("enable_cover"):
            from core.pdf_builder import build_evidence_pdf
            result = build_evidence_pdf(
                image_paths, output_path,
                scale_mode=scale_mode,
                layout=layout,
                direction=direction,
                title=title or first_stem,
                show_number=show_number,
                show_page_number=show_page_number,
                enable_cover=True,
                watermark=job.get("watermark", ""),
                source_files=image_paths,
            )
        else:
            result = build_grid_pdf(
                image_paths, output_path,
                scale_mode=scale_mode,
                layout=layout,
                direction=direction,
                title=title or first_stem,
                show_number=show_number,
                show_page_number=show_page_number,
            )

        job["status"] = "done"
        job["result_filename"] = result.name
        job["current"] = total
        job["logs"].append(("done", f"PDF 生成成功: {result.name}"))

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["logs"].append(("error", f"生成失败: {e}"))
        logger.error("Job %s failed: %s", job_id, e)
    finally:
        # 生成后清理临时图片，保留 PDF
        if job.get("temp_dir"):
            temp_dir = Path(job["temp_dir"])
            for f in temp_dir.iterdir():
                if f.suffix.lower() in IMAGE_EXTENSIONS:
                    try:
                        f.unlink()
                    except OSError:
                        pass


# ── 路由 ────────────────────────────────────────────────────

@router.get("/")
async def index():
    """返回前端页面（带 no-cache 头，防止浏览器缓存旧版本）。"""
    from fastapi.responses import FileResponse
    static_dir = Path(__file__).resolve().parent / "static"
    return FileResponse(
        str(static_dir / "index.html"),
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },
    )


@router.post("/api/pdf/jobs")
async def create_job(
    files: list[UploadFile] = File(...),
    scale_mode: str = Form("fit"),
    layout: str = Form("2x2"),
    direction: str = Form("lr"),
    title: str = Form(""),
    show_number: str = Form("true"),
    show_page_number: str = Form("false"),
):
    """
    创建 PDF 生成任务。
    上传图片 → 返回 job_id → 后台异步处理。
    """
    if not files:
        raise HTTPException(status_code=400, detail="请选择图片/视频")

    if scale_mode not in ("fit", "fill"):
        raise HTTPException(status_code=400, detail="缩放模式必须为 fit 或 fill")
    if layout not in ("1x1", "1x2", "2x2", "2x3"):
        raise HTTPException(status_code=400, detail="布局必须为 1x1/1x2/2x2/2x3")

    # 过滤非图片
    valid_files = []
    for f in files:
        ext = Path(f.filename).suffix.lower()
        if ext in IMAGE_EXTENSIONS:
            valid_files.append(f)

    if not valid_files:
        raise HTTPException(status_code=400, detail="没有有效的图片文件（支持 PNG/JPG/JPEG/WEBP）")

    job_id = str(uuid.uuid4())
    temp_dir = Path(tempfile.mkdtemp(prefix=f"chatScreen2pdf_{job_id}_", dir=str(TEMP_ROOT)))

    # 保存上传的图片
    saved_files = []
    for f in valid_files:
        content = await f.read()
        dest = temp_dir / f.filename
        dest.write_bytes(content)
        saved_files.append((f.filename, dest))

    job = {
        "job_id": job_id,
        "status": "pending",
        "total": len(saved_files),
        "current": 0,
        "logs": [("info", f"已上传 {len(saved_files)} 张图片")],
        "result_filename": "",
        "error": "",
        "files": saved_files,
        "temp_dir": str(temp_dir),
        "scale_mode": scale_mode,
        "layout": layout,
        "direction": direction,
        "title": title,
        "show_number": show_number.lower() == "true",
        "show_page_number": show_page_number.lower() == "true",
        "watermark": "",
        "enable_cover": False,
    }
    _jobs[job_id] = job

    # 后台启动处理
    import threading
    t = threading.Thread(target=_process_job, args=(job_id,), daemon=True)
    t.start()

    return {"job_id": job_id, "total": len(saved_files)}


@router.get("/api/pdf/jobs/{job_id}")
async def get_job_status(job_id: str):
    """查询任务状态。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    return JobStatus(
        job_id=job["job_id"],
        status=job["status"],
        total=job["total"],
        current=job["current"],
        logs=job["logs"],
        result_filename=job.get("result_filename", ""),
        error=job.get("error", ""),
    )


@router.get("/api/pdf/jobs/{job_id}/download")
async def download_pdf(job_id: str):
    """下载生成的 PDF。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] not in ("done", "pdf_done", "pdf_ready"):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=400,
            content={"success": False, "message": "PDF 仍在生成中，请稍后再试"},
        )

    result_name = job.get("result_filename", "")
    temp_dir = Path(job["temp_dir"])
    pdf_path = temp_dir / result_name

    if not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF 文件不存在")

    return FileResponse(
        str(pdf_path),
        media_type="application/pdf",
        filename=result_name,
        headers={"Content-Disposition": f'attachment; filename="{result_name}"'},
    )


# ── Phase 2: 长截图任务 ─────────────────────────────────────

@router.post("/api/long/jobs")
async def create_long_job(
    file: UploadFile = File(...),
    slice_height: int = Form(3000),
    overlap: int = Form(150),
):
    """上传长截图并切片，返回切片信息。"""
    from core.long_image import slice_image, validate_params, IMAGE_EXTENSIONS

    ext = Path(file.filename).suffix.lower()
    if ext not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=400,
                            detail=f"不支持的文件格式: {ext}（支持 PNG/JPG/JPEG/WEBP）")

    try:
        validate_params(slice_height, overlap)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    job_id = str(uuid.uuid4())
    temp_dir = Path(tempfile.mkdtemp(prefix=f"chatScreen2pdf_long_{job_id}_", dir=str(TEMP_ROOT)))

    # 保存原文件
    content = await file.read()
    src_path = temp_dir / file.filename
    src_path.write_bytes(content)

    job = {
        "job_id": job_id,
        "status": "processing",
        "type": "long",
        "total": 0,
        "current": 0,
        "logs": [("info", f"已上传: {file.filename}")],
        "result_filename": "",
        "error": "",
        "src_file": str(src_path),
        "temp_dir": str(temp_dir),
        "slice_height": slice_height,
        "overlap": overlap,
        "slices": [],
        "slice_filenames": [],
    }
    _jobs[job_id] = job

    # 后台切片
    import threading
    t = threading.Thread(target=_process_long_job, args=(job_id,), daemon=True)
    t.start()

    return {"job_id": job_id, "filename": file.filename}


def _process_long_job(job_id: str) -> None:
    """后台切片处理。"""
    from core.long_image import slice_image

    job = _jobs.get(job_id)
    if not job:
        return
    try:
        src_path = Path(job["src_file"])
        output_dir = Path(job["temp_dir"]) / "slices"
        slice_height = job["slice_height"]
        overlap = job["overlap"]

        job["logs"].append(("info", "正在切片..."))
        slices = slice_image(src_path, output_dir, slice_height, overlap)
        job["slices"] = [str(s) for s in slices]
        job["slice_filenames"] = [s.name for s in slices]
        job["total"] = len(slices)
        job["current"] = len(slices)
        job["status"] = "done"
        job["logs"].append(("done", f"切片完成: {len(slices)} 片"))

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["logs"].append(("error", f"切片失败: {e}"))
        logger.error("Long job %s failed: %s", job_id, e)


@router.get("/api/long/jobs/{job_id}")
async def get_long_job_status(job_id: str):
    """查询长截图任务状态。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "total": job["total"],
        "current": job["current"],
        "logs": job["logs"],
        "slices": job.get("slice_filenames", []),
        "error": job.get("error", ""),
    }


@router.post("/api/long/jobs/{job_id}/pdf")
async def create_long_pdf(
    job_id: str,
    layout: str = Form("2x2"),
    direction: str = Form("lr"),
    title: str = Form(""),
    scale_mode: str = Form("fit"),
    show_number: str = Form("true"),
    show_page_number: str = Form("false"),
    watermark: str = Form(""),
    enable_cover: str = Form("false"),
):
    """根据长截图切片生成 PDF。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] != "done":
        raise HTTPException(status_code=400, detail="切片尚未完成")
    if layout not in ("1x1", "1x2", "2x2", "2x3"):
        raise HTTPException(status_code=400, detail="布局无效")

    slices = [Path(p) for p in job["slices"]]
    if not slices:
        raise HTTPException(status_code=400, detail="没有切片可处理")

    # 复用 Phase 1 PDF 生成
    first_stem = Path(job["src_file"]).stem
    pdf_title = title.strip() or first_stem
    output_path = Path(job["temp_dir"]) / f"{first_stem}.pdf"

    job["logs"].append(("info", f"正在生成 PDF ({len(slices)} 片, 布局: {layout})..."))
    job["status"] = "pdf_generating"

    try:
        use_cover = enable_cover.lower() == "true"
        if use_cover:
            from core.pdf_builder import build_evidence_pdf
            result = build_evidence_pdf(
                slices, output_path,
                scale_mode=scale_mode,
                layout=layout,
                direction=direction,
                title=pdf_title,
                show_number=show_number.lower() == "true",
                show_page_number=show_page_number.lower() == "true",
                enable_cover=True,
                watermark=watermark,
                source_files=[Path(job.get("src_file", ""))],
            )
        else:
            result = build_grid_pdf(
                slices, output_path,
                scale_mode=scale_mode,
                layout=layout,
                direction=direction,
                title=pdf_title,
                show_number=show_number.lower() == "true",
                show_page_number=show_page_number.lower() == "true",
            )
        job["status"] = "pdf_done"
        job["result_filename"] = result.name
        job["logs"].append(("done", f"PDF 生成成功: {result.name}"))
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["logs"].append(("error", f"PDF 生成失败: {e}"))

    return {"job_id": job_id, "status": job["status"]}


@router.get("/api/long/jobs/{job_id}/download")
async def download_long_pdf(job_id: str):
    """下载长截图生成的 PDF。"""
    return await download_pdf(job_id)


# ── Phase 4: 视频处理 ───────────────────────────────────────

@router.post("/api/video/draft")
async def create_video_draft(file: UploadFile = File(...)):
    """上传视频草稿（仅保存文件，不处理），用于加载参考帧。"""
    ext = Path(file.filename).suffix.lower()
    if ext != ".mp4":
        raise HTTPException(status_code=400, detail="仅支持 MP4 格式")
    job_id = str(uuid.uuid4())
    temp_dir = Path(tempfile.mkdtemp(prefix=f"chatScreen2pdf_video_{job_id}_", dir=str(TEMP_ROOT)))
    content = await file.read()
    src_path = temp_dir / file.filename
    src_path.write_bytes(content)
    job = {
        "job_id": job_id, "status": "draft", "type": "video",
        "total": 0, "current": 0, "logs": [],
        "result_filename": "", "error": "",
        "src_file": str(src_path), "temp_dir": str(temp_dir),
        "frames": [], "frame_filenames": [], "frame_details": [],
    }
    _jobs[job_id] = job
    return {"job_id": job_id, "filename": file.filename}


@router.post("/api/video/jobs")
async def create_video_job(
    file: UploadFile = File(...),
    interval: float = Form(0.5),
    blur_threshold: float = Form(30.0),
    dedup_threshold: int = Form(10),
    global_dedup: str = Form("false"),
    ocr_region_x: Optional[int] = Form(None),
    ocr_region_y: Optional[int] = Form(None),
    ocr_region_w: Optional[int] = Form(None),
    ocr_region_h: Optional[int] = Form(None),
    exclude_words: str = Form(""),
):
    """上传视频并开始抽帧+筛选+OCR 连续性判断。"""
    ext = Path(file.filename).suffix.lower()
    if ext != ".mp4":
        raise HTTPException(status_code=400, detail="仅支持 MP4 格式")

    # OCR 区域
    ocr_region = None
    if all(v is not None for v in [ocr_region_x, ocr_region_y, ocr_region_w, ocr_region_h]):
        ocr_region = {"x": ocr_region_x, "y": ocr_region_y, "width": ocr_region_w, "height": ocr_region_h}

    # 排除词
    words = []
    if exclude_words and exclude_words.strip():
        for w in exclude_words.replace("\r\n", "\n").split("\n"):
            w = w.strip()
            if w and w not in words:
                words.append(w)

    job_id = str(uuid.uuid4())
    temp_dir = Path(tempfile.mkdtemp(prefix=f"chatScreen2pdf_video_{job_id}_", dir=str(TEMP_ROOT)))

    content = await file.read()
    src_path = temp_dir / file.filename
    src_path.write_bytes(content)

    job = {
        "job_id": job_id,
        "status": "processing",
        "type": "video",
        "total": 0,
        "current": 0,
        "logs": [("info", f"已上传: {file.filename}")],
        "result_filename": "",
        "error": "",
        "src_file": str(src_path),
        "temp_dir": str(temp_dir),
        "interval": interval,
        "blur_threshold": blur_threshold,
        "dedup_threshold": dedup_threshold,
        "global_dedup": global_dedup.lower() == "true",
        "ocr_region": ocr_region,
        "exclude_words": words,
        "frames": [],
        "frame_filenames": [],
        "frame_details": [],  # 每帧的 OCR 分类结果
        "ocr_available": False,
    }
    _jobs[job_id] = job

    import threading
    t = threading.Thread(target=_process_video_job, args=(job_id,), daemon=True)
    t.start()

    return {"job_id": job_id, "filename": file.filename}


def _process_video_job(job_id: str) -> None:
    """后台视频处理。"""
    from core.video_processor import extract_video_frames, filter_frames
    from core.ocr_service import is_ocr_available, recognize_image, classify_frame_by_ocr, validate_ocr_region

    job = _jobs.get(job_id)
    if not job:
        return
    try:
        src_path = Path(job["src_file"])
        frames_dir = Path(job["temp_dir"]) / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)

        job["logs"].append(("info", f"正在抽帧 (间隔={job['interval']}秒)..."))

        # 检查 FFmpeg
        try:
            from core.extractor import check_ffmpeg
            check_ffmpeg()
        except Exception as e:
            raise RuntimeError(f"FFmpeg 不可用: {e}")

        # 1. 抽帧
        frames = extract_video_frames(
            src_path, frames_dir,
            interval=job["interval"],
        )
        job["logs"].append(("info", f"抽帧完成: {len(frames)} 帧"))

        # 2. 检查 OCR
        ocr_avail = is_ocr_available()
        job["ocr_available"] = ocr_avail

        # 校验 OCR 区域
        ocr_region = job.get("ocr_region")
        if ocr_region and frames:
            from PIL import Image
            with Image.open(frames[0]) as img:
                w, h = img.size
            validation = validate_ocr_region(ocr_region, w, h)
            if validation.get("valid") and validation.get("region"):
                job["ocr_region"] = validation["region"]
                if validation.get("warning"):
                    job["logs"].append(("info", f"OCR 区域: {validation['warning']}"))
            else:
                job["ocr_region"] = None
                if validation.get("error"):
                    job["logs"].append(("warning", f"OCR 区域无效: {validation['error']}，使用全图"))

        # 3. 模糊过滤
        job["logs"].append(("info", "正在筛选（模糊过滤）..."))
        kept = filter_frames(
            frames,
            blur_threshold=job["blur_threshold"],
            dedup_threshold=999,  # OCR 阶段再去做重
            global_dedup=False,
        )

        # 4. OCR 连续性判断
        exclude_words = job.get("exclude_words", [])
        frame_details = []
        prev_lines = None

        if ocr_avail:
            job["logs"].append(("info", f"正在进行 OCR 连续性分析 (区域: {ocr_region or '全图'})..."))

        filtered = []
        for idx, fp in enumerate(kept):
            curr_lines = []
            if ocr_avail:
                curr_lines = recognize_image(fp, ocr_region)

            result = classify_frame_by_ocr(
                prev_lines, curr_lines,
                exclude_words=exclude_words,
                ocr_available=ocr_avail,
            )
            result["id"] = fp.name
            result["index"] = idx
            result["preview_url"] = f"/api/files/{job_id}/frames/{fp.name}"
            frame_details.append(result)

            if result["status"] in ("kept", "kept_warning", "image_dedup_only", "ocr_failed"):
                filtered.append(fp)
                if result["status"] in ("kept", "kept_warning"):
                    prev_lines = curr_lines
            elif result["status"] == "skipped_duplicate":
                pass  # 跳过

        # 5. 如果没有 OCR 或全部跳过，降级为图像去重
        if not filtered:
            job["logs"].append(("info", "OCR 筛选后无保留帧，降级为图像去重"))
            filtered = filter_frames(
                kept,
                blur_threshold=job["blur_threshold"],
                dedup_threshold=job["dedup_threshold"],
                global_dedup=job["global_dedup"],
            )
            frame_details = []
            for idx, fp in enumerate(filtered):
                frame_details.append({
                    "id": fp.name,
                    "index": idx,
                    "preview_url": f"/api/files/{job_id}/frames/{fp.name}",
                    "status": "image_dedup_only",
                    "reason": "OCR 降级，使用图像去重保留",
                    "warning": None,
                    "ocr_available": ocr_avail,
                    "ocr_text_count": 0,
                    "ocr_text_preview": [],
                })

        job["frames"] = [str(f) for f in filtered]
        job["frame_filenames"] = [f.name for f in filtered]
        job["frame_details"] = frame_details
        job["total"] = len(filtered)
        job["current"] = len(filtered)
        job["status"] = "done"

        ocr_status = "已启用" if ocr_avail else "未安装"
        job["logs"].append(("done",
            f"视频处理完成: {len(frames)}→{len(filtered)} 帧 (OCR: {ocr_status})"))

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["logs"].append(("error", f"处理失败: {e}"))
        logger.error("Video job %s failed: %s", job_id, e)


@router.get("/api/video/jobs/{job_id}")
async def get_video_job_status(job_id: str):
    """查询视频任务状态。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {
        "job_id": job["job_id"],
        "status": job["status"],
        "total": job["total"],
        "current": job["current"],
        "logs": job["logs"],
        "frames": job.get("frame_filenames", []),
        "frame_details": job.get("frame_details", []),
        "frames_dir": str(Path(job.get("temp_dir", "")) / "frames") if job.get("temp_dir") else "",
        "ocr_available": job.get("ocr_available", False),
        "error": job.get("error", ""),
    }


@router.post("/api/video/reference-frame")
async def create_reference_frame(
    job_id: str = Form(...),
):
    """
    从视频中提取参考帧用于 OCR 区域框选。
    默认取第 1 秒附近的一帧。
    """
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    src_path = Path(job["src_file"])
    if not src_path.exists():
        raise HTTPException(status_code=400, detail="视频文件不存在")

    ref_dir = Path(job["temp_dir"])
    ref_path = ref_dir / "reference.jpg"

    import subprocess
    ffmpeg_path = "ffmpeg"
    try:
        from core.extractor import _find_ffmpeg
        ffmpeg_path = _find_ffmpeg()
    except Exception:
        pass

    # 尝试取第 1 秒的帧
    cmd = [
        ffmpeg_path, "-hide_banner", "-loglevel", "error",
        "-ss", "1", "-i", str(src_path),
        "-frames:v", "1", "-qscale:v", "2", "-y", str(ref_path),
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=30)
    except Exception:
        pass

    # 如果失败，取第一帧
    if not ref_path.exists():
        cmd[4:6] = ["-i", str(src_path)]
        cmd.insert(4, "-ss")
        cmd.insert(5, "0")
        try:
            subprocess.run(cmd, capture_output=True, timeout=30)
        except Exception:
            raise HTTPException(status_code=500, detail="参考帧提取失败")

    if not ref_path.exists():
        raise HTTPException(status_code=500, detail="参考帧提取失败")

    from PIL import Image
    with Image.open(ref_path) as img:
        w, h = img.size

    return {
        "success": True,
        "session_id": job_id,
        "preview_url": f"/api/files/{job_id}/reference.jpg",
        "width": w,
        "height": h,
        "message": "参考帧加载成功",
    }


@router.get("/api/files/{job_id}/frames/{filename}")
async def serve_frame_image(job_id: str, filename: str):
    """提供视频帧图片预览。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404)
    fp = Path(job["temp_dir"]) / "frames" / filename
    if not fp.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(fp), media_type="image/jpeg")


@router.get("/api/files/{job_id}/slices/{filename}")
async def serve_slice_image(job_id: str, filename: str):
    """提供切片图片预览。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404)
    fp = Path(job["temp_dir"]) / "slices" / filename
    if not fp.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(fp), media_type="image/jpeg")


@router.get("/api/files/{job_id}/reference.jpg")
async def serve_reference_frame(job_id: str):
    """提供视频参考帧。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404)
    fp = Path(job["temp_dir"]) / "reference.jpg"
    if not fp.exists():
        raise HTTPException(status_code=404)
    return FileResponse(str(fp), media_type="image/jpeg")


@router.put("/api/video/jobs/{job_id}/frames")
async def update_video_frames(job_id: str, body: dict):
    """更新视频帧顺序（删除/排序后提交）。"""
    filenames = body.get("filenames", [])
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    frames_dir = Path(job["temp_dir"]) / "frames"
    new_frames = []
    new_filenames = []
    for fname in filenames:
        fp = frames_dir / fname
        if fp.exists():
            new_frames.append(str(fp))
            new_filenames.append(fname)
    job["frames"] = new_frames
    job["frame_filenames"] = new_filenames
    job["total"] = len(new_frames)
    job["logs"].append(("info", f"已更新帧顺序: {len(new_filenames)} 帧"))
    return {"total": len(new_filenames)}


@router.put("/api/long/jobs/{job_id}/slices")
async def update_long_slices(job_id: str, body: dict):
    """更新切片顺序。"""
    filenames = body.get("filenames", [])
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    slices_dir = Path(job["temp_dir"]) / "slices"
    new_slices = []
    new_filenames = []
    for fname in filenames:
        fp = slices_dir / fname
        if fp.exists():
            new_slices.append(str(fp))
            new_filenames.append(fname)
    job["slices"] = new_slices
    job["slice_filenames"] = new_filenames
    job["total"] = len(new_filenames)
    job["logs"].append(("info", f"已更新切片顺序: {len(new_filenames)} 片"))
    return {"total": len(new_filenames)}


@router.post("/api/video/jobs/{job_id}/pdf")
async def create_video_pdf(
    job_id: str,
    layout: str = Form("2x2"),
    direction: str = Form("lr"),
    title: str = Form(""),
    scale_mode: str = Form("fit"),
    show_number: str = Form("true"),
    show_page_number: str = Form("false"),
    watermark: str = Form(""),
    enable_cover: str = Form("false"),
):
    """根据视频帧生成 PDF。"""
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] not in ("done", "pdf_done"):
        raise HTTPException(status_code=400, detail="视频处理尚未完成")
    if layout not in ("1x1", "1x2", "2x2", "2x3"):
        raise HTTPException(status_code=400, detail="布局无效")

    frames = [Path(p) for p in job["frames"]]
    if not frames:
        raise HTTPException(status_code=400, detail="没有帧可处理")

    first_stem = Path(job["src_file"]).stem
    pdf_title = title.strip() or first_stem
    output_path = Path(job["temp_dir"]) / f"{first_stem}.pdf"

    job["logs"].append(("info", f"正在生成 PDF ({len(frames)} 帧, 布局: {layout})..."))
    job["status"] = "pdf_generating"

    try:
        use_cover = enable_cover.lower() == "true"
        if use_cover:
            from core.pdf_builder import build_evidence_pdf
            result = build_evidence_pdf(
                frames, output_path,
                scale_mode=scale_mode,
                layout=layout,
                direction=direction,
                title=pdf_title,
                show_number=show_number.lower() == "true",
                show_page_number=show_page_number.lower() == "true",
                enable_cover=True,
                watermark=watermark,
                source_files=[Path(job.get("src_file", ""))],
            )
        else:
            result = build_grid_pdf(
                frames, output_path,
                scale_mode=scale_mode,
                layout=layout,
                direction=direction,
                title=pdf_title,
                show_number=show_number.lower() == "true",
                show_page_number=show_page_number.lower() == "true",
            )
        job["status"] = "pdf_done"
        job["result_filename"] = result.name
        job["logs"].append(("done", f"PDF 生成成功: {result.name}"))
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["logs"].append(("error", f"PDF 生成失败: {e}"))

    return {"job_id": job_id, "status": job["status"]}


@router.get("/api/video/jobs/{job_id}/download")
async def download_video_pdf(job_id: str):
    """下载视频生成的 PDF。"""
    return await download_pdf(job_id)


# 注册路由
app.include_router(router)
