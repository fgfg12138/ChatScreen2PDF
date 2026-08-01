"""
web/routes.py — FastAPI 路由：图片上传、PDF 生成、状态查询、下载。
"""

import json
import logging
import os
import shutil
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import FastAPI, APIRouter, File, Form, UploadFile, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app_config import APP_EDITION as CONFIG_EDITION, APP_NAME, APP_VERSION
from core.pdf_builder import build_grid_pdf

logger = logging.getLogger(__name__)

APP_EDITION = os.environ.get("FRAMESCREEN2PDF_EDITION", CONFIG_EDITION).strip().lower()
if APP_EDITION not in ("full", "lite"):
    APP_EDITION = "full"
IS_LITE = APP_EDITION == "lite"
ENABLE_WORD = not IS_LITE
ENABLE_VIDEO_IMAGE_ZIP = not IS_LITE
DEFAULT_WATERMARK = APP_NAME

# FastAPI 应用
app = FastAPI(title=APP_NAME, version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

router = APIRouter()

# 支持的图片扩展名
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


# ── 健康检查 + 版本信息 ──────────────────────────────────

@router.get("/api/health")
async def health_check():
    """健康检查接口，前端依赖此接口确认后端可用。"""
    return {
        "success": True,
        "version": APP_VERSION,
        "app_name": APP_NAME,
        "edition": APP_EDITION,
        "features": {
            "word": ENABLE_WORD,
            "watermark_optional": not IS_LITE,
            "watermark_forced": IS_LITE,
            "default_watermark": DEFAULT_WATERMARK,
            "bundled_ffmpeg": False,
            "video_image_zip": ENABLE_VIDEO_IMAGE_ZIP,
        },
        "message": f"{APP_NAME} backend OK",
        "routes": {
            "pdf_jobs": True,
            "long_jobs": True,
            "video_draft": True,
            "video_jobs": True,
            "video_pdf": True,
        },
    }


@router.post("/api/shutdown")
async def shutdown_app():
    """Close the local desktop service after responding to the browser."""
    def _exit_later():
        time.sleep(0.3)
        os._exit(0)

    threading.Thread(target=_exit_later, daemon=True).start()
    return {"success": True, "message": "Framescreen2PDF is shutting down"}


from fastapi.responses import Response


@router.get("/api/ocr/status")
async def ocr_status():
    """Lightweight OCR component detection for the optional UI toggle."""
    from core.ocr_service import get_ocr_status
    return get_ocr_status()


@router.get("/favicon.ico")
async def favicon():
    """返回空 favicon，避免 404 干扰。"""
    return Response(status_code=204)

# 临时文件根目录
TEMP_ROOT = Path(tempfile.gettempdir()) / "chatScreen2pdf_web"
TEMP_ROOT.mkdir(parents=True, exist_ok=True)


# ── 任务持久化（浏览器关闭/程序重启后可恢复下载） ──────────────

JOBS_DIR = TEMP_ROOT / "jobs"
_persist_enabled = False
_jobs_lock = threading.Lock()
JOB_RETENTION_SECONDS = 7 * 24 * 3600


def _register_job(job_id: str, job: dict) -> None:
    """写入内存任务表并持久化快照。"""
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    job.setdefault("created_at", now)
    job["updated_at"] = now
    _jobs[job_id] = job
    _save_job(job_id)


def _json_default(obj):
    """JSON 序列化兜底：Path 对象转为字符串。"""
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _save_job(job_id: str) -> None:
    """将单个任务快照写入磁盘（原子替换）。"""
    if not _persist_enabled:
        return
    job = _jobs.get(job_id)
    if not job:
        return
    try:
        job["updated_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        JOBS_DIR.mkdir(parents=True, exist_ok=True)
        tmp_path = JOBS_DIR / f"{job_id}.json.tmp"
        tmp_path.write_text(
            json.dumps(job, ensure_ascii=False, indent=1, default=_json_default),
            encoding="utf-8",
        )
        tmp_path.replace(JOBS_DIR / f"{job_id}.json")
    except Exception:
        logger.exception("Failed to persist job %s", job_id)


def _save_all_jobs() -> None:
    """快照全部任务（后台循环调用）。"""
    if not _persist_enabled:
        return
    with _jobs_lock:
        items = list(_jobs.items())
    for job_id, _ in items:
        _save_job(job_id)


def _load_jobs() -> None:
    """启动时恢复历史任务；处理中断的任务按结果文件决定恢复状态。"""
    if not JOBS_DIR.exists():
        return
    now_ts = time.time()
    for jf in sorted(JOBS_DIR.glob("*.json")):
        try:
            job = json.loads(jf.read_text(encoding="utf-8"))
        except Exception:
            jf.unlink(missing_ok=True)
            continue
        job_id = job.get("job_id")
        if not job_id:
            continue
        temp_dir = Path(job.get("temp_dir", "")) if job.get("temp_dir") else None
        # 过期任务清理（仅清理程序自己的临时目录）
        if temp_dir and temp_dir.is_relative_to(TEMP_ROOT):
            try:
                if now_ts - temp_dir.stat().st_mtime > JOB_RETENTION_SECONDS:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    jf.unlink(missing_ok=True)
                    continue
            except OSError:
                pass
        # 中断恢复：进程重启后不再有后台线程，处理中的任务按已有结果恢复
        if job.get("status") in ("pending", "processing", "pdf_generating"):
            result_name = job.get("result_filename", "")
            result_path = (temp_dir / result_name) if (temp_dir and result_name) else None
            if result_path and result_path.exists():
                job["status"] = "pdf_done"
                job.setdefault("logs", []).append(("info", "检测到已生成的 PDF，已恢复为可下载状态"))
            else:
                job["status"] = "interrupted"
                job["error"] = "程序中断，任务未完成"
                job.setdefault("logs", []).append(("error", "程序中断，任务未完成"))
        _jobs[job_id] = job


def _persist_loop() -> None:
    """后台周期持久化，兜底保存中间状态。"""
    while True:
        time.sleep(5)
        try:
            _save_all_jobs()
        except Exception:
            logger.exception("Job persist loop error")


def init_job_persistence() -> None:
    """加载历史任务并启动持久化循环（由 web_app 启动时调用）。"""
    global _persist_enabled
    _persist_enabled = True
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    _load_jobs()
    threading.Thread(target=_persist_loop, daemon=True).start()


# ── 任务状态模型 ────────────────────────────────────────────

class JobStatus(BaseModel):
    job_id: str
    status: str  # pending / processing / done / error
    total: int = 0
    current: int = 0
    logs: list = []
    result_filename: str = ""
    error: str = ""


class BatchDownloadRequest(BaseModel):
    job_ids: list[str]
    kind: str = "pdf"


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


def _download_file_response(file_path: Path, result_name: str, media_type: str) -> FileResponse:
    """Return a download response that supports Chinese filenames."""
    fallback = "".join(
        ch if ch.isascii() and ch not in {'"', "\\", "\r", "\n"} else "_"
        for ch in result_name
    ).strip("._ ")
    if not fallback:
        fallback = APP_NAME
    encoded = quote(result_name)
    return FileResponse(
        str(file_path),
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{encoded}'
            )
        },
    )


def _download_pdf_response(pdf_path: Path, result_name: str) -> FileResponse:
    return _download_file_response(pdf_path, result_name, "application/pdf")


def _download_docx_response(docx_path: Path, result_name: str) -> FileResponse:
    return _download_file_response(
        docx_path,
        result_name,
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


def _download_zip_response(zip_path: Path, result_name: str) -> FileResponse:
    return _download_file_response(zip_path, result_name, "application/zip")


def _unique_zip_name(used: set[str], filename: str) -> str:
    """Return a stable unique filename inside a zip archive."""
    candidate = filename
    stem = Path(filename).stem
    suffix = Path(filename).suffix
    idx = 1
    while candidate in used:
        candidate = f"{stem}_{idx}{suffix}"
        idx += 1
    used.add(candidate)
    return candidate


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
        watermark = job.get("watermark", "")
        output_path = Path(job["temp_dir"]) / f"{first_stem}.pdf"

        job["logs"].append(("info", f"正在生成 PDF (布局: {layout}, 缩放: {scale_mode})..."))
        if job.get("enable_cover") or watermark:
            from core.pdf_builder import build_evidence_pdf
            result = build_evidence_pdf(
                image_paths, output_path,
                scale_mode=scale_mode,
                layout=layout,
                direction=direction,
                title=title or first_stem,
                show_number=show_number,
                show_page_number=show_page_number,
                enable_cover=bool(job.get("enable_cover")),
                watermark=watermark,
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
        # 保留临时图片，后续可继续导出 Word；同时持久化任务状态。
        _save_job(job_id)


def _download_word(job_id: str) -> FileResponse:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")

    result_name = job.get("word_result_filename", "")
    if not result_name:
        raise HTTPException(status_code=400, detail="Word 尚未生成")

    docx_path = Path(job["temp_dir"]) / result_name
    if not docx_path.exists():
        raise HTTPException(status_code=404, detail=f"Word 文件不存在: {result_name}")

    return _download_docx_response(docx_path, result_name)


# ── 任务历史 ────────────────────────────────────────────────

def _job_display_name(job: dict) -> str:
    """返回任务显示名（首个文件或视频文件名）。"""
    src_file = job.get("src_file", "")
    if src_file:
        return Path(src_file).name
    files = job.get("files") or []
    if files:
        first = files[0]
        if isinstance(first, (list, tuple)) and first:
            return Path(str(first[0])).name
        return Path(str(first)).name
    return str(job.get("job_id", ""))


def _job_summary(job: dict) -> dict:
    """生成任务历史列表的摘要信息。"""
    temp_dir = Path(job["temp_dir"]) if job.get("temp_dir") else None

    def _file_exists(name: str) -> bool:
        return bool(name) and temp_dir is not None and (temp_dir / name).exists()

    return {
        "job_id": job.get("job_id", ""),
        "type": job.get("type", "image"),
        "status": job.get("status", ""),
        "name": _job_display_name(job),
        "created_at": job.get("created_at", ""),
        "updated_at": job.get("updated_at", ""),
        "total": job.get("total", 0),
        "current": job.get("current", 0),
        "result_filename": job.get("result_filename", ""),
        "word_result_filename": job.get("word_result_filename", ""),
        "images_zip_filename": job.get("images_zip_filename", ""),
        "error": job.get("error", ""),
        "has_pdf": _file_exists(job.get("result_filename", "")),
        "has_word": _file_exists(job.get("word_result_filename", "")),
        "has_images_zip": _file_exists(job.get("images_zip_filename", "")),
    }


@router.get("/api/jobs")
async def list_jobs():
    """返回全部历史任务（页面刷新/重开后用于恢复下载列表）。"""
    jobs = [_job_summary(job) for job in _jobs.values()]
    jobs.sort(key=lambda j: j.get("created_at") or "", reverse=True)
    return {"jobs": jobs}


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
    watermark: str = Form(""),
    enable_watermark: str = Form("false"),
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

    pdf_watermark = DEFAULT_WATERMARK if IS_LITE else (watermark.strip() if enable_watermark.lower() == "true" else "")

    job = {
        "job_id": job_id,
        "status": "pending",
        "type": "image",
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
        "watermark": pdf_watermark,
        "enable_cover": False,
    }
    _register_job(job_id, job)

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
        raise HTTPException(status_code=404, detail=f"PDF 文件不存在: {result_name}")

    return _download_pdf_response(pdf_path, result_name)


@router.post("/api/pdf/jobs/{job_id}/word")
async def create_image_word(
    job_id: str,
    title: str = Form(""),
    show_number: str = Form("true"),
):
    """根据普通截图生成 Word 文档。"""
    if not ENABLE_WORD:
        raise HTTPException(status_code=404, detail="当前版本不包含 Word 导出功能")
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] not in ("done", "pdf_done", "pdf_ready"):
        raise HTTPException(status_code=400, detail="图片处理尚未完成")

    image_paths = [Path(p) for _, p in job.get("files", [])]
    image_paths = [p for p in image_paths if p.exists()]
    if not image_paths:
        raise HTTPException(status_code=400, detail="没有图片可处理")

    first_stem = Path(job["files"][0][0]).stem
    output_path = Path(job["temp_dir"]) / f"{first_stem}.docx"
    doc_title = title.strip() or job.get("title") or first_stem

    try:
        from core.word_builder import build_image_docx
        result = build_image_docx(
            image_paths,
            output_path,
            title=doc_title,
            show_number=show_number.lower() == "true",
        )
        job["word_result_filename"] = result.name
        job["logs"].append(("done", f"Word 生成成功: {result.name}"))
        _save_job(job_id)
        return {"job_id": job_id, "status": "word_done", "result_filename": result.name}
    except Exception as e:
        job["error"] = str(e)
        job["logs"].append(("error", f"Word 生成失败: {e}"))
        _save_job(job_id)
        raise HTTPException(status_code=500, detail=f"Word 生成失败: {e}")


@router.get("/api/pdf/jobs/{job_id}/word/download")
async def download_image_word(job_id: str):
    """下载普通截图生成的 Word。"""
    if not ENABLE_WORD:
        raise HTTPException(status_code=404, detail="当前版本不包含 Word 导出功能")
    return _download_word(job_id)


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
    _register_job(job_id, job)

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
        _save_job(job_id)

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["logs"].append(("error", f"切片失败: {e}"))
        logger.error("Long job %s failed: %s", job_id, e)
        _save_job(job_id)


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
        pdf_watermark = DEFAULT_WATERMARK if IS_LITE else watermark.strip()
        if use_cover or pdf_watermark:
            from core.pdf_builder import build_evidence_pdf
            result = build_evidence_pdf(
                slices, output_path,
                scale_mode=scale_mode,
                layout=layout,
                direction=direction,
                title=pdf_title,
                show_number=show_number.lower() == "true",
                show_page_number=show_page_number.lower() == "true",
                enable_cover=False,
                watermark=pdf_watermark,
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
        _save_job(job_id)
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["logs"].append(("error", f"PDF 生成失败: {e}"))
        _save_job(job_id)

    return {"job_id": job_id, "status": job["status"]}


@router.get("/api/long/jobs/{job_id}/download")
async def download_long_pdf(job_id: str):
    """下载长截图生成的 PDF。"""
    return await download_pdf(job_id)


@router.post("/api/long/jobs/{job_id}/word")
async def create_long_word(
    job_id: str,
    title: str = Form(""),
    show_number: str = Form("true"),
):
    """根据长截图切片生成 Word 文档。"""
    if not ENABLE_WORD:
        raise HTTPException(status_code=404, detail="当前版本不包含 Word 导出功能")
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] not in ("done", "pdf_done"):
        raise HTTPException(status_code=400, detail="切片尚未完成")

    slices = [Path(p) for p in job.get("slices", [])]
    slices = [p for p in slices if p.exists()]
    if not slices:
        raise HTTPException(status_code=400, detail="没有切片可处理")

    first_stem = Path(job["src_file"]).stem
    output_path = Path(job["temp_dir"]) / f"{first_stem}.docx"
    doc_title = title.strip() or first_stem

    try:
        from core.word_builder import build_image_docx
        result = build_image_docx(
            slices,
            output_path,
            title=doc_title,
            show_number=show_number.lower() == "true",
        )
        job["word_result_filename"] = result.name
        job["logs"].append(("done", f"Word 生成成功: {result.name}"))
        _save_job(job_id)
        return {"job_id": job_id, "status": "word_done", "result_filename": result.name}
    except Exception as e:
        job["error"] = str(e)
        job["logs"].append(("error", f"Word 生成失败: {e}"))
        _save_job(job_id)
        raise HTTPException(status_code=500, detail=f"Word 生成失败: {e}")


@router.get("/api/long/jobs/{job_id}/word/download")
async def download_long_word(job_id: str):
    """下载长截图生成的 Word。"""
    if not ENABLE_WORD:
        raise HTTPException(status_code=404, detail="当前版本不包含 Word 导出功能")
    return _download_word(job_id)


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
    _register_job(job_id, job)
    return {"job_id": job_id, "filename": file.filename}


@router.post("/api/video/jobs")
async def create_video_job(
    file: UploadFile = File(...),
    interval: float = Form(0.5),
    blur_threshold: float = Form(10.0),
    dedup_threshold: int = Form(10),
    dedup_enabled: str = Form("false"),
    global_dedup: str = Form("false"),
    enable_ocr: str = Form("false"),
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
        "dedup_enabled": dedup_enabled.lower() == "true",
        "global_dedup": global_dedup.lower() == "true",
        "enable_ocr": enable_ocr.lower() == "true",
        "ocr_region": ocr_region,
        "exclude_words": words,
        "frames": [],
        "frame_filenames": [],
        "frame_details": [],  # 每帧的 OCR 分类结果
        "ocr_available": False,
    }
    _register_job(job_id, job)

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
        raw_region = job.get("ocr_region")
        crop_pixels = None
        if raw_region:
            crop_pixels = (
                int(raw_region["x"]),
                int(raw_region["y"]),
                int(raw_region["width"]),
                int(raw_region["height"]),
            )
        frames = extract_video_frames(
            src_path, frames_dir,
            interval=job["interval"],
            crop_pixels=crop_pixels,
        )
        job["logs"].append(("info", f"抽帧完成: {len(frames)} 帧"))

        # 2. OCR 仅在用户主动勾选时检测和启用
        ocr_requested = bool(job.get("enable_ocr"))
        ocr_avail = is_ocr_available() if ocr_requested else False
        job["ocr_available"] = ocr_avail

        # 校验 OCR 区域
        ocr_region = job.get("ocr_region")
        if crop_pixels:
            job["logs"].append(("info", f"已按框选区域裁剪输出帧: {crop_pixels}"))
            job["ocr_region"] = None
            ocr_region = None
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
            dedup_threshold=job["dedup_threshold"],
            global_dedup=False,
            dedup_enabled=False,
        )

        # 4. OCR 连续性判断
        exclude_words = job.get("exclude_words", [])
        frame_details = []
        prev_lines = None

        # 只有当用户勾选、OCR 可用且有明确区域时才启用 OCR 去重
        ocr_active = ocr_requested and ocr_avail and bool(crop_pixels or job.get("ocr_region"))
        if ocr_active:
            job["logs"].append(("info", f"正在进行 OCR 连续性分析 (区域: {job.get('ocr_region')})..."))

        filtered = []
        for idx, fp in enumerate(kept):
            curr_lines = []
            if ocr_active:
                curr_lines = recognize_image(fp, ocr_region)

            result = classify_frame_by_ocr(
                prev_lines, curr_lines,
                exclude_words=exclude_words,
                ocr_available=ocr_active,
            )
            result["id"] = fp.name
            result["index"] = idx
            result["preview_url"] = f"/api/files/{job_id}/frames/{fp.name}"
            result["ocr_available"] = ocr_active
            frame_details.append(result)

            if result["status"] in ("kept", "kept_warning", "image_dedup_only", "ocr_failed"):
                filtered.append(fp)
                if result["status"] in ("kept", "kept_warning"):
                    prev_lines = curr_lines
            elif result["status"] == "skipped_duplicate":
                pass  # 跳过
            elif result["status"] == "skipped_duplicate":
                pass  # 跳过

        if not ocr_active:
            if job.get("dedup_enabled"):
                filtered = filter_frames(
                    kept,
                    blur_threshold=0,
                    dedup_threshold=job["dedup_threshold"],
                    global_dedup=job["global_dedup"],
                    dedup_enabled=True,
                )
            else:
                filtered = kept
            detail_reason = ""
            frame_details = []
            for idx, fp in enumerate(filtered):
                frame_details.append({
                    "id": fp.name,
                    "index": idx,
                    "preview_url": f"/api/files/{job_id}/frames/{fp.name}",
                    "status": "kept",
                    "reason": detail_reason,
                    "warning": None,
                    "ocr_available": ocr_active,
                    "ocr_text_count": 0,
                    "ocr_text_preview": [],
                })

        # 5. 如果没有 OCR 或全部跳过，降级为图像去重
        if not filtered and job.get("dedup_enabled"):
            if ocr_active:
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
                    "reason": "OCR 降级，使用图像去重保留" if ocr_active else "",
                    "warning": None,
                    "ocr_available": ocr_active,
                    "ocr_text_count": 0,
                    "ocr_text_preview": [],
                })

        if not filtered:
            job["logs"].append(("warning", "未保留任何帧，已回退为模糊过滤后的全部帧"))
            filtered = kept
            frame_details = []
            for idx, fp in enumerate(filtered):
                frame_details.append({
                    "id": fp.name,
                    "index": idx,
                    "preview_url": f"/api/files/{job_id}/frames/{fp.name}",
                    "status": "kept",
                    "reason": "",
                    "warning": None,
                    "ocr_available": ocr_active,
                    "ocr_text_count": 0,
                    "ocr_text_preview": [],
                })

        job["frames"] = [str(f) for f in filtered]
        job["frame_filenames"] = [f.name for f in filtered]
        job["frame_details"] = frame_details
        job["total"] = len(filtered)
        job["current"] = len(filtered)
        job["status"] = "done"

        job["logs"].append(("done", f"视频处理完成: {len(frames)}→{len(filtered)} 帧"))
        _save_job(job_id)

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["logs"].append(("error", f"处理失败: {e}"))
        logger.error("Video job %s failed: %s", job_id, e)
        _save_job(job_id)


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
    _save_job(job_id)
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
    _save_job(job_id)
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
        pdf_watermark = DEFAULT_WATERMARK if IS_LITE else watermark.strip()
        if use_cover or pdf_watermark:
            from core.pdf_builder import build_evidence_pdf
            result = build_evidence_pdf(
                frames, output_path,
                scale_mode=scale_mode,
                layout=layout,
                direction=direction,
                title=pdf_title,
                show_number=show_number.lower() == "true",
                show_page_number=show_page_number.lower() == "true",
                enable_cover=False,
                watermark=pdf_watermark,
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
        _save_job(job_id)
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["logs"].append(("error", f"PDF 生成失败: {e}"))
        _save_job(job_id)

    return {"job_id": job_id, "status": job["status"]}


@router.get("/api/video/jobs/{job_id}/download")
async def download_video_pdf(job_id: str):
    """下载视频生成的 PDF。"""
    return await download_pdf(job_id)


@router.post("/api/video/batch/download")
async def download_video_batch(body: BatchDownloadRequest):
    """将多个已生成的视频结果打包下载。默认打包 PDF。"""
    kind = (body.kind or "pdf").lower().strip()
    if kind not in ("pdf", "word", "images"):
        raise HTTPException(status_code=400, detail="批量下载类型无效")
    if kind == "word" and not ENABLE_WORD:
        raise HTTPException(status_code=404, detail="当前版本不包含 Word 导出功能")
    if kind == "images" and not ENABLE_VIDEO_IMAGE_ZIP:
        raise HTTPException(status_code=404, detail="当前版本不包含视频转图片功能")

    files: list[tuple[Path, str]] = []
    for job_id in body.job_ids:
        job = _jobs.get(job_id)
        if not job:
            continue
        temp_dir = Path(job.get("temp_dir", ""))
        if kind == "pdf":
            result_name = job.get("result_filename", "")
        elif kind == "word":
            result_name = job.get("word_result_filename", "")
        else:
            result_name = job.get("images_zip_filename", "")
        if not result_name:
            continue
        fp = temp_dir / result_name
        if fp.exists():
            files.append((fp, result_name))

    if not files:
        raise HTTPException(status_code=400, detail="没有可打包的文件")

    suffix = {"pdf": "PDF", "word": "Word", "images": "图片"}[kind]
    zip_name = f"批量视频转换_{suffix}.zip"
    zip_path = TEMP_ROOT / f"framescreen2pdf_batch_{uuid.uuid4().hex}.zip"
    used: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for fp, result_name in files:
            zf.write(fp, _unique_zip_name(used, result_name))

    return _download_zip_response(zip_path, zip_name)


@router.post("/api/video/jobs/{job_id}/word")
async def create_video_word(
    job_id: str,
    title: str = Form(""),
    show_number: str = Form("true"),
):
    """根据视频帧生成 Word 文档。"""
    if not ENABLE_WORD:
        raise HTTPException(status_code=404, detail="当前版本不包含 Word 导出功能")
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] not in ("done", "pdf_done"):
        raise HTTPException(status_code=400, detail="视频处理尚未完成")

    frames = [Path(p) for p in job.get("frames", [])]
    frames = [p for p in frames if p.exists()]
    if not frames:
        raise HTTPException(status_code=400, detail="没有帧可处理")

    first_stem = Path(job["src_file"]).stem
    output_path = Path(job["temp_dir"]) / f"{first_stem}.docx"
    doc_title = title.strip() or first_stem

    try:
        from core.word_builder import build_image_docx
        result = build_image_docx(
            frames,
            output_path,
            title=doc_title,
            show_number=show_number.lower() == "true",
        )
        job["word_result_filename"] = result.name
        job["logs"].append(("done", f"Word 生成成功: {result.name}"))
        _save_job(job_id)
        return {"job_id": job_id, "status": "word_done", "result_filename": result.name}
    except Exception as e:
        job["error"] = str(e)
        job["logs"].append(("error", f"Word 生成失败: {e}"))
        _save_job(job_id)
        raise HTTPException(status_code=500, detail=f"Word 生成失败: {e}")


@router.get("/api/video/jobs/{job_id}/word/download")
async def download_video_word(job_id: str):
    """下载视频生成的 Word。"""
    if not ENABLE_WORD:
        raise HTTPException(status_code=404, detail="当前版本不包含 Word 导出功能")
    return _download_word(job_id)


@router.post("/api/video/jobs/{job_id}/images-zip")
async def create_video_images_zip(job_id: str):
    """将当前保留并排序后的帧打包为图片 ZIP。Full 功能。"""
    if not ENABLE_VIDEO_IMAGE_ZIP:
        raise HTTPException(status_code=404, detail="当前版本不包含视频转图片功能")
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] not in ("done", "pdf_done"):
        raise HTTPException(status_code=400, detail="视频处理尚未完成")

    frames = [Path(p) for p in job.get("frames", [])]
    frames = [p for p in frames if p.exists()]
    if not frames:
        raise HTTPException(status_code=400, detail="没有帧可导出")

    first_stem = Path(job["src_file"]).stem
    safe_stem = "".join(ch if ch not in '<>:"/\\|?*\r\n' else "_" for ch in first_stem).strip("._ ")
    if not safe_stem:
        safe_stem = "frames"
    pad = max(2, len(str(len(frames))))
    zip_name = f"{safe_stem}_图片.zip"
    zip_path = Path(job["temp_dir"]) / zip_name

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for idx, frame in enumerate(frames, start=1):
            ext = frame.suffix.lower() or ".jpg"
            zf.write(frame, arcname=f"{safe_stem}{idx:0{pad}d}{ext}")

    job["images_zip_filename"] = zip_name
    job["logs"].append(("done", f"图片 ZIP 生成成功: {zip_name}"))
    _save_job(job_id)
    return {"job_id": job_id, "status": "images_zip_done", "result_filename": zip_name}


@router.get("/api/video/jobs/{job_id}/images-zip/download")
async def download_video_images_zip(job_id: str):
    """下载当前保留帧图片 ZIP。"""
    if not ENABLE_VIDEO_IMAGE_ZIP:
        raise HTTPException(status_code=404, detail="当前版本不包含视频转图片功能")
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    result_name = job.get("images_zip_filename", "")
    if not result_name:
        raise HTTPException(status_code=400, detail="图片 ZIP 尚未生成")
    zip_path = Path(job["temp_dir"]) / result_name
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail=f"图片 ZIP 不存在: {result_name}")
    return _download_zip_response(zip_path, result_name)


# 注册路由
if not ENABLE_WORD:
    router.routes[:] = [
        route for route in router.routes
        if "/word" not in getattr(route, "path", "").lower()
    ]
if not ENABLE_VIDEO_IMAGE_ZIP:
    router.routes[:] = [
        route for route in router.routes
        if "images-zip" not in getattr(route, "path", "").lower()
    ]

app.include_router(router)
