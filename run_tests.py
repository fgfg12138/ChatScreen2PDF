"""
run_tests.py - Lightweight test runner.
Usage: python run_tests.py

健壮模式：单个测试模块 import 失败不影响其他模块运行。
"""
import sys, tempfile, importlib, inspect, types, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


class _Raises:
    def __init__(self, exc_type):
        self.exc_type = exc_type
    def __enter__(self): return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            raise AssertionError("Expected " + str(self.exc_type))
        if not issubclass(exc_type, self.exc_type):
            raise AssertionError("Expected " + str(self.exc_type) + " got " + str(exc_type))
        return True


pytest_mod = types.ModuleType("pytest")
pytest_mod.raises = staticmethod(lambda e: _Raises(e))
sys.modules["pytest"] = pytest_mod

test_modules = [
    "tests.test_scanner",
    "tests.test_cleanup",
    "tests.test_extractor",
    "tests.test_dedup",
    "tests.test_pdf_builder",
    "tests.test_version",
    "tests.test_release",
    "tests.test_crop",
    "tests.test_long_image",
    "tests.test_video_processor",
    "tests.test_ocr_service",
]

total_passed = total_failed = total_import_failed = 0
for module_name in test_modules:
    # Try to import the module; if it fails, record and continue
    try:
        mod = importlib.import_module(module_name)
    except Exception as e:
        print("FAILED  " + module_name + " (import error): " + str(e))
        traceback.print_exc()
        total_import_failed += 1
        continue

    test_funcs = [getattr(mod, n) for n in sorted(dir(mod)) if n.startswith("test_")]
    for fn in test_funcs:
        sig = inspect.signature(fn)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tp = Path(tmp)
                if list(sig.parameters)[0:1] == ["tmp_path"]:
                    fn(tp)
                else:
                    fn()
            print("PASSED  " + fn.__name__)
            total_passed += 1
        except Exception as e:
            print("FAILED  " + fn.__name__ + ": " + str(e))
            total_failed += 1

summary_parts = ["%d passed" % total_passed, "%d failed" % total_failed]
if total_import_failed:
    summary_parts.append("%d module(s) failed to import" % total_import_failed)
print("\n" + ", ".join(summary_parts))
sys.exit(1 if total_failed or total_import_failed else 0)
