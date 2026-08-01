"""
test_web.py — Web 接口测试（Phase 0-B）。
使用 httpx 测试 FastAPI 路由。
"""

import sys
import io
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PIL import Image
import pikepdf
from httpx import AsyncClient, ASGITransport

from web.routes import app, _jobs


@pytest.fixture
def test_image_png():
    """生成一张测试 PNG 图片数据。"""
    img = Image.new("RGB", (400, 300), (100, 150, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue(), "test_img.png"


@pytest.fixture
def test_image_jpg():
    """生成一张测试 JPG 图片数据。"""
    img = Image.new("RGB", (200, 200), (50, 100, 150))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue(), "test_photo.jpg"


@pytest.mark.asyncio
async def test_index_returns_html(test_image_png):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "Framescreen2PDF" in resp.text
    assert "图片转 PDF/Word" in resp.text


@pytest.mark.asyncio
async def test_health_includes_edition_features():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app_name"] == "Framescreen2PDF"
    assert data["version"] == "1.0.0"
    assert data["edition"] in ("full", "lite")
    assert data["features"]["bundled_ffmpeg"] is False
    assert "video_image_zip" in data["features"]
    assert data["features"]["default_watermark"] == "Framescreen2PDF"


@pytest.mark.asyncio
async def test_ocr_status_endpoint_is_lightweight():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/ocr/status")
    assert resp.status_code == 200
    data = resp.json()
    assert set(["installed", "paddleocr", "paddle", "message"]).issubset(data.keys())
    assert isinstance(data["installed"], bool)


@pytest.mark.asyncio
async def test_create_job_no_files():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pdf/jobs")
    # FastAPI 自动校验缺少的 files 参数，返回 422
    assert resp.status_code in (400, 422)
    data = resp.json()
    assert "detail" in data


@pytest.mark.asyncio
async def test_create_job_with_png(test_image_png):
    data_bytes, filename = test_image_png
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/pdf/jobs",
            files={"files": (filename, data_bytes, "image/png")},
            data={"scale_mode": "fit", "layout": "2x2", "show_number": "true", "show_page_number": "false"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert data["total"] == 1


@pytest.mark.asyncio
async def test_create_job_multiple_images(test_image_png, test_image_jpg):
    png_data, png_name = test_image_png
    jpg_data, jpg_name = test_image_jpg
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/pdf/jobs",
            files=[
                ("files", (png_name, png_data, "image/png")),
                ("files", (jpg_name, jpg_data, "image/jpeg")),
            ],
            data={"scale_mode": "fill", "layout": "1x2", "direction": "tb", "title": "测试文件"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 2


@pytest.mark.asyncio
async def test_create_and_check_job(test_image_png):
    """创建任务并查询状态直至完成。"""
    data_bytes, filename = test_image_png
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 创建
        resp = await client.post(
            "/api/pdf/jobs",
            files={"files": (filename, data_bytes, "image/png")},
            data={"scale_mode": "fit"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        # 轮询直到完成
        import time
        for _ in range(30):
            resp = await client.get(f"/api/pdf/jobs/{job_id}")
            assert resp.status_code == 200
            data = resp.json()
            if data["status"] == "done":
                break
            time.sleep(0.2)

        assert data["status"] == "done", f"Job failed: {data.get('error', 'unknown')}"
        assert data["total"] == 1
        assert data["result_filename"] != ""


@pytest.mark.asyncio
async def test_download_pdf(test_image_png):
    """生成 PDF 后下载。"""
    data_bytes, filename = test_image_png
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 创建
        resp = await client.post(
            "/api/pdf/jobs",
            files={"files": (filename, data_bytes, "image/png")},
            data={"scale_mode": "fit"},
        )
        job_id = resp.json()["job_id"]

        # 等完成
        import time
        for _ in range(30):
            resp = await client.get(f"/api/pdf/jobs/{job_id}")
            if resp.json()["status"] == "done":
                break
            time.sleep(0.2)

        # 下载
        resp = await client.get(f"/api/pdf/jobs/{job_id}/download")
        assert resp.status_code == 200
        assert resp.headers.get("content-type") == "application/pdf"
        assert len(resp.content) > 100  # 至少 100 字节


@pytest.mark.asyncio
async def test_watermark_pdf_does_not_add_cover_page(test_image_png):
    data_bytes, filename = test_image_png
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/pdf/jobs",
            files={"files": (filename, data_bytes, "image/png")},
            data={"scale_mode": "fit", "enable_watermark": "true", "watermark": "Framescreen2PDF"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        import time
        for _ in range(30):
            resp = await client.get(f"/api/pdf/jobs/{job_id}")
            if resp.json()["status"] == "done":
                break
            time.sleep(0.2)

        resp = await client.get(f"/api/pdf/jobs/{job_id}/download")
        assert resp.status_code == 200
        with pikepdf.open(io.BytesIO(resp.content)) as pdf:
            assert len(pdf.pages) == 1


@pytest.mark.asyncio
async def test_create_and_download_word(test_image_png):
    """生成 Word 后下载。"""
    data_bytes, filename = test_image_png
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/pdf/jobs",
            files={"files": (filename, data_bytes, "image/png")},
            data={"scale_mode": "fit", "show_number": "true"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        import time
        for _ in range(30):
            resp = await client.get(f"/api/pdf/jobs/{job_id}")
            if resp.json()["status"] == "done":
                break
            time.sleep(0.2)

        resp = await client.post(
            f"/api/pdf/jobs/{job_id}/word",
            data={"title": "截图文件", "show_number": "true"},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "word_done"

        resp = await client.get(f"/api/pdf/jobs/{job_id}/word/download")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert len(resp.content) > 1000


@pytest.mark.asyncio
async def test_create_and_download_long_word():
    img = Image.new("RGB", (360, 1400), (180, 190, 210))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/long/jobs",
            files={"file": ("long_chat.png", buf.getvalue(), "image/png")},
            data={"slice_height": "600", "overlap": "80"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        import time
        for _ in range(30):
            resp = await client.get(f"/api/long/jobs/{job_id}")
            data = resp.json()
            if data["status"] == "done":
                break
            time.sleep(0.2)
        assert data["status"] == "done"

        resp = await client.post(f"/api/long/jobs/{job_id}/word", data={"show_number": "true"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "word_done"

        resp = await client.get(f"/api/long/jobs/{job_id}/word/download")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )
        assert len(resp.content) > 1000


@pytest.mark.asyncio
async def test_download_pdf_with_chinese_filename():
    img = Image.new("RGB", (320, 240), (120, 130, 140))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/pdf/jobs",
            files={"files": ("聊天截图001.png", buf.getvalue(), "image/png")},
            data={"scale_mode": "fit"},
        )
        assert resp.status_code == 200
        job_id = resp.json()["job_id"]

        import time
        for _ in range(30):
            resp = await client.get(f"/api/pdf/jobs/{job_id}")
            if resp.json()["status"] == "done":
                break
            time.sleep(0.2)

        resp = await client.get(f"/api/pdf/jobs/{job_id}/download")
        assert resp.status_code == 200
        content_disposition = resp.headers.get("content-disposition", "")
        assert "filename*=" in content_disposition
        assert "%E8%81%8A%E5%A4%A9%E6%88%AA%E5%9B%BE001.pdf" in content_disposition


@pytest.mark.asyncio
async def test_frontend_video_flow_has_progress_dedup_toggle_and_next_video():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/")
    assert resp.status_code == 200
    html = resp.text
    assert 'id="enableDedup"' in html
    assert "dedup_enabled" in html
    assert "softProgress" in html
    assert "选择下一个视频" in html
    assert "当前 PDF 已生成但还没有确认下载" in html
    assert "PDFD=false" in html
    assert 'id="btnGenerateWord"' in html
    assert 'id="longBtnGenerateWord"' in html
    assert 'id="videoBtnGenerateWord"' in html
    assert 'id="enableWatermark"' in html
    assert "watermarkValue" in html
    assert "word/download" in html
    assert "正在生成 Word 0%" in html
    assert "Word 生成完成 100%" in html
    assert "videoSection.style.display = 'none'" in html
    assert "长截图转 PDF/Word" in html
    assert 'id="enableOcrAssist"' in html
    assert "OCR辅助筛选" in html
    assert 'id="videoBtnImagesZip"' in html
    assert "images-zip" in html
    assert 'id="videoBatchDownloadLink"' in html
    assert 'id="videoBatchWordDownloadLink"' in html
    assert 'id="videoBatchImagesDownloadLink"' in html
    assert "runBatchJobs" in html
    assert "batchFiles" in html
    assert 'multiple style="display:none"' in html
    assert "/api/video/batch/download" in html
    assert "word_done" in html
    assert "images_done" in html
    assert "正在生成 Word [" in html
    assert "正在打包图片 [" in html
    assert "建议只框选主要内容区域" not in html
    assert "微信&#10;文件传输助手" not in html
    assert "OCR 未安装，使用图像对比筛选" not in html
    assert "图像去重未开启，保留模糊过滤后的帧" not in html


@pytest.mark.asyncio
async def test_video_images_zip_uses_current_frame_order(tmp_path):
    frames_dir = tmp_path / "frames"
    frames_dir.mkdir()
    first = frames_dir / "b.jpg"
    second = frames_dir / "a.jpg"
    Image.new("RGB", (80, 80), (200, 20, 20)).save(first, format="JPEG")
    Image.new("RGB", (80, 80), (20, 200, 20)).save(second, format="JPEG")

    job_id = "zip-order-test"
    _jobs[job_id] = {
        "job_id": job_id,
        "status": "done",
        "type": "video",
        "total": 2,
        "current": 2,
        "logs": [],
        "src_file": str(tmp_path / "户外视频.mp4"),
        "temp_dir": str(tmp_path),
        "frames": [str(first), str(second)],
        "frame_filenames": [first.name, second.name],
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.put(
            f"/api/video/jobs/{job_id}/frames",
            json={"filenames": [second.name, first.name]},
        )
        assert resp.status_code == 200
        resp = await client.post(f"/api/video/jobs/{job_id}/images-zip")
        assert resp.status_code == 200
        assert resp.json()["status"] == "images_zip_done"
        resp = await client.get(f"/api/video/jobs/{job_id}/images-zip/download")
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("application/zip")

    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert zf.namelist() == ["户外视频01.jpg", "户外视频02.jpg"]


@pytest.mark.asyncio
async def test_video_batch_download_zips_generated_pdfs(tmp_path):
    first_pdf = tmp_path / "first.pdf"
    second_pdf = tmp_path / "second.pdf"
    first_pdf.write_bytes(b"%PDF-1.4\nfirst")
    second_pdf.write_bytes(b"%PDF-1.4\nsecond")
    _jobs["batch-a"] = {
        "job_id": "batch-a",
        "status": "pdf_done",
        "temp_dir": str(tmp_path),
        "result_filename": first_pdf.name,
    }
    _jobs["batch-b"] = {
        "job_id": "batch-b",
        "status": "pdf_done",
        "temp_dir": str(tmp_path),
        "result_filename": second_pdf.name,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/video/batch/download",
            json={"kind": "pdf", "job_ids": ["batch-a", "batch-b"]},
        )
    assert resp.status_code == 200
    assert resp.headers.get("content-type", "").startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        assert zf.namelist() == ["first.pdf", "second.pdf"]


@pytest.mark.asyncio
async def test_video_batch_download_zips_word_and_images(tmp_path):
    word_file = tmp_path / "sample.docx"
    images_zip = tmp_path / "sample_图片.zip"
    word_file.write_bytes(b"word")
    images_zip.write_bytes(b"zip")
    _jobs["batch-extra"] = {
        "job_id": "batch-extra",
        "status": "pdf_done",
        "temp_dir": str(tmp_path),
        "word_result_filename": word_file.name,
        "images_zip_filename": images_zip.name,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        word_resp = await client.post(
            "/api/video/batch/download",
            json={"kind": "word", "job_ids": ["batch-extra"]},
        )
        images_resp = await client.post(
            "/api/video/batch/download",
            json={"kind": "images", "job_ids": ["batch-extra"]},
        )
    assert word_resp.status_code == 200
    assert images_resp.status_code == 200
    with zipfile.ZipFile(io.BytesIO(word_resp.content)) as zf:
        assert zf.namelist() == ["sample.docx"]
    with zipfile.ZipFile(io.BytesIO(images_resp.content)) as zf:
        assert zf.namelist() == ["sample_图片.zip"]


@pytest.mark.asyncio
async def test_job_not_found():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/pdf/jobs/nonexistent")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_invalid_layout(test_image_png):
    data_bytes, filename = test_image_png
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/pdf/jobs",
            files={"files": (filename, data_bytes, "image/png")},
            data={"layout": "5x5"},
        )
    assert resp.status_code == 400


# ── 任务历史：持久化与恢复 ─────────────────────────────────

@pytest.mark.asyncio
async def test_list_jobs_endpoint_returns_downloadable_summary(tmp_path):
    """任务历史接口应返回已生成文件的可下载摘要。"""
    temp_dir = tmp_path / "jobdir"
    temp_dir.mkdir()
    pdf = temp_dir / "out.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    word = temp_dir / "out.docx"
    word.write_bytes(b"word")
    _jobs["list-a"] = {
        "job_id": "list-a",
        "status": "pdf_done",
        "type": "video",
        "created_at": "2026-07-01 10:00:00",
        "temp_dir": str(temp_dir),
        "result_filename": pdf.name,
        "word_result_filename": word.name,
        "src_file": str(tmp_path / "户外视频.mp4"),
        "total": 3,
        "current": 3,
        "error": "",
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/jobs")
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    summary = next(j for j in jobs if j["job_id"] == "list-a")
    assert summary["type"] == "video"
    assert summary["name"] == "户外视频.mp4"
    assert summary["has_pdf"] is True
    assert summary["has_word"] is True
    assert summary["has_images_zip"] is False


@pytest.mark.asyncio
async def test_job_persisted_and_restored_after_restart(tmp_path, monkeypatch):
    """任务应落盘，且清空内存后可从磁盘恢复。"""
    import json as _json
    import web.routes as routes
    jobs_dir = tmp_path / "jobs"
    monkeypatch.setattr(routes, "JOBS_DIR", jobs_dir)
    monkeypatch.setattr(routes, "_persist_enabled", True)

    temp_dir = tmp_path / "jobdir"
    temp_dir.mkdir()
    pdf = temp_dir / "result.pdf"
    pdf.write_bytes(b"%PDF-1.4 test")
    job = {
        "job_id": "persist-1",
        "status": "done",
        "type": "image",
        "total": 1,
        "current": 1,
        "logs": [],
        "result_filename": pdf.name,
        "error": "",
        "files": [("a.png", str(temp_dir / "a.png"))],
        "temp_dir": str(temp_dir),
    }
    routes._register_job("persist-1", job)
    assert (jobs_dir / "persist-1.json").exists()

    # 模拟程序重启：清空内存任务表后重新加载
    routes._jobs.clear()
    routes._load_jobs()
    assert "persist-1" in routes._jobs
    restored = routes._jobs["persist-1"]
    assert restored["status"] == "done"
    assert restored["created_at"]
    assert restored["files"][0] == ["a.png", str(temp_dir / "a.png")]


@pytest.mark.asyncio
async def test_interrupted_job_recovered_when_pdf_exists(tmp_path, monkeypatch):
    """处理中的任务重启后若 PDF 已生成，应恢复为可下载状态。"""
    import json as _json
    import web.routes as routes
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(routes, "JOBS_DIR", jobs_dir)

    temp_dir = tmp_path / "jobdir"
    temp_dir.mkdir()
    pdf = temp_dir / "out.pdf"
    pdf.write_bytes(b"%PDF-1.4 x")
    job = {
        "job_id": "int-1",
        "status": "processing",
        "type": "video",
        "total": 5,
        "current": 3,
        "logs": [],
        "result_filename": pdf.name,
        "error": "",
        "temp_dir": str(temp_dir),
        "src_file": str(tmp_path / "v.mp4"),
        "frames": [],
        "frame_filenames": [],
    }
    (jobs_dir / "int-1.json").write_text(_json.dumps(job, ensure_ascii=False), encoding="utf-8")
    routes._load_jobs()
    assert routes._jobs["int-1"]["status"] == "pdf_done"


@pytest.mark.asyncio
async def test_interrupted_job_without_result_marked_interrupted(tmp_path, monkeypatch):
    """处理中的任务重启后没有结果文件，应标记为已中断。"""
    import json as _json
    import web.routes as routes
    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    monkeypatch.setattr(routes, "JOBS_DIR", jobs_dir)

    temp_dir = tmp_path / "jobdir"
    temp_dir.mkdir()
    job = {
        "job_id": "int-2",
        "status": "processing",
        "type": "video",
        "total": 5,
        "current": 3,
        "logs": [],
        "result_filename": "",
        "error": "",
        "temp_dir": str(temp_dir),
        "src_file": str(tmp_path / "v.mp4"),
    }
    (jobs_dir / "int-2.json").write_text(_json.dumps(job, ensure_ascii=False), encoding="utf-8")
    routes._load_jobs()
    assert routes._jobs["int-2"]["status"] == "interrupted"