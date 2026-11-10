import unittest
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


ROOT = Path(__file__).resolve().parents[1]


class AppSmokeTests(unittest.TestCase):
    def assert_healthy(self, app):
        self.assertFalse(list(app.exception), [item.value for item in app.exception])
        self.assertFalse(list(app.error), [item.value for item in app.error])
        self.assertGreater(len(app.metric), 0)

    @patch(
        "modules.analysis_service.analyze_market",
        side_effect=AssertionError("The app must render from saved snapshots"),
    )
    def test_main_sections_and_reload_use_saved_snapshots(self, analyze_market):
        app = AppTest.from_file(ROOT / "app.py", default_timeout=30).run()
        self.assert_healthy(app)
        self.assertEqual(len(app.radio[0].options), 5)

        for option in list(app.radio[0].options):
            with self.subTest(section=option):
                app.radio[0].set_value(option).run()
                self.assert_healthy(app)

        app.button[0].click().run()
        self.assert_healthy(app)
        analyze_market.assert_not_called()

    def test_portfolio_analysis_page_renders(self):
        app = AppTest.from_file(ROOT / "app.py", default_timeout=30).run()
        self.assert_healthy(app)
        pages = list((ROOT / "pages").glob("2_*.py"))
        self.assertEqual(len(pages), 1)

        app.switch_page(pages[0].relative_to(ROOT).as_posix()).run()
        self.assert_healthy(app)
        self.assertGreater(len(app.dataframe), 0)


if __name__ == "__main__":
    unittest.main()
