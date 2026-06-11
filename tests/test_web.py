"""
test_web.py — Web 接口测试（Phase 0-B）。
使用 httpx 测试 FastAPI 路由。
"""

import sys
import io
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PIL import Image
from httpx import AsyncClient, ASGITransport

from web.routes import app


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
    assert "截图生成 PDF" in resp.text


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
            data={"scale_mode": "fill", "layout": "1x2", "direction": "tb", "title": "测试证据"},
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
