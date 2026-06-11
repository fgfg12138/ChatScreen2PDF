import sys
import subprocess
import pytest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.extractor import check_ffmpeg, extract_frames, _find_ffmpeg, FFmpegNotInstalledError, FrameExtractionError


def _create_test_video(output_path, duration=2):
    ffmpeg = _find_ffmpeg()
    subprocess.run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=" + str(duration) + ":r=10",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output_path),
    ], check=True, capture_output=True)
    return output_path


def test_check_ffmpeg():
    version = check_ffmpeg()
    assert "ffmpeg" in version.lower()


def test_extract_frames_returns_images(tmp_path):
    video = _create_test_video(tmp_path / "test.mp4", duration=2)
    frames = extract_frames(video, fps=1.0, temp_dir=tmp_path / "tmp")
    assert len(frames) >= 2
    for f in frames:
        assert f.exists() and f.suffix == ".jpg" and f.stat().st_size > 0


def test_extract_frames_higher_fps(tmp_path):
    video = _create_test_video(tmp_path / "test.mp4", duration=2)
    f1 = extract_frames(video, fps=1.0, temp_dir=tmp_path / "t1")
    f2 = extract_frames(video, fps=2.0, temp_dir=tmp_path / "t2")
    assert len(f2) > len(f1)


def test_extract_frames_file_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        extract_frames(Path("/no/such/video.mp4"), fps=1.0, temp_dir=tmp_path / "t")


def test_extract_frames_corrupted_video(tmp_path):
    bad = tmp_path / "bad.mp4"
    bad.write_bytes(b"not a video")
    with pytest.raises(FrameExtractionError):
        extract_frames(bad, fps=1.0, temp_dir=tmp_path / "t")


def test_extract_frames_sorted_output(tmp_path):
    video = _create_test_video(tmp_path / "test.mp4", duration=3)
    frames = extract_frames(video, fps=1.0, temp_dir=tmp_path / "t")
    assert frames == sorted(frames)


def test_extract_frames_with_crop_ratio(tmp_path):
    video = _create_test_video(tmp_path / "test.mp4", duration=2)
    frames = extract_frames(video, fps=1.0, temp_dir=tmp_path / "t",
                            crop_ratio=(0.1, 0.0, 0.9, 1.0))
    assert len(frames) >= 2


def test_extract_frames_with_crop_pixels(tmp_path):
    video = _create_test_video(tmp_path / "test.mp4", duration=2)
    frames = extract_frames(video, fps=1.0, temp_dir=tmp_path / "t",
                            crop_pixels=(0, 10, 300, 200))
    assert len(frames) >= 2
