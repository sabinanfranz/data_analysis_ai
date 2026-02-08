import importlib
import unittest

from fastapi import FastAPI


class UvicornEntrypointCompatTest(unittest.TestCase):
    def test_compat_module_is_importable(self) -> None:
        module = importlib.import_module("app.main")
        self.assertTrue(hasattr(module, "app"))

    def test_compat_app_is_fastapi_instance(self) -> None:
        from app.main import app as compat_app

        self.assertIsInstance(compat_app, FastAPI)

    def test_compat_and_official_app_are_same_object(self) -> None:
        from app.main import app as compat_app
        from dashboard.server.main import app as official_app

        self.assertIs(compat_app, official_app)


if __name__ == "__main__":
    unittest.main()

