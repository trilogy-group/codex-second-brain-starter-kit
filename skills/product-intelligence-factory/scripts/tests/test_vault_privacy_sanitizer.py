from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parents[1]
MODULE_PATH = TOOLS_DIR / "sanitize_vault_privacy.py"


def load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class VaultPrivacySanitizerTests(unittest.TestCase):
    def test_sanitize_markdown_redacts_emails_private_ips_credentials_and_person_names(self) -> None:
        module = load_module(MODULE_PATH, "sanitize_vault_privacy_under_test")
        text = "\n".join(
            [
                "- Contact support@example.com or alice@customer.example",
                "- Use https://gitlab+deploy-token-20:secret@gitlab.example.com/repo.git",
                "- Internal host 10.241.126.160 should stay private",
                "## Priyanka Bhotika",
            ]
        )

        sanitized = module.sanitize_markdown_text(text, {"Priyanka Bhotika"})

        self.assertNotIn("support@example.com", sanitized)
        self.assertNotIn("alice@customer.example", sanitized)
        self.assertNotIn("gitlab+deploy-token-20:secret@", sanitized)
        self.assertNotIn("10.241.126.160", sanitized)
        self.assertNotIn("Priyanka Bhotika", sanitized)
        self.assertIn("[REDACTED_EMAIL]", sanitized)
        self.assertIn("[REDACTED_CREDENTIALS]@", sanitized)
        self.assertIn("[REDACTED_PRIVATE_IP]", sanitized)
        self.assertIn("[REDACTED_PERSON]", sanitized)

    def test_detect_likely_person_names_uses_author_context(self) -> None:
        module = load_module(MODULE_PATH, "sanitize_vault_privacy_detection_test")
        with tempfile.TemporaryDirectory() as tmp_dir:
            vault = Path(tmp_dir)
            (vault / "a.md").write_text(
                "\n".join(
                    [
                        "# Sample",
                        "## Comments",
                        "- Priyanka Bhotika",
                        "## Priyanka Bhotika",
                    ]
                )
            )
            (vault / "b.md").write_text(
                "\n".join(
                    [
                        "# Sample",
                        "## Full Article Content",
                        "- Platform Core",
                    ]
                )
            )

            names = module.detect_likely_person_names(sorted(vault.rglob("*.md")))

        self.assertIn("Priyanka Bhotika", names)
        self.assertNotIn("Platform Core", names)
        self.assertNotIn("Full Article Content", names)


if __name__ == "__main__":
    unittest.main()
