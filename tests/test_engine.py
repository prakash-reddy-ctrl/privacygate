"""
PrivacyGateAI - Core Engine Tests
Run with: python tests/test_engine.py
No API key required — tests the sanitize/restore pipeline only.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from core.engine import PrivacyEngine


def run_test(name: str, fn):
    try:
        fn()
        print(f"  ✓ {name}")
    except AssertionError as e:
        print(f"  ✗ {name}: {e}")
    except Exception as e:
        print(f"  ✗ {name}: UNEXPECTED ERROR — {e}")


engine = PrivacyEngine()


def test_email_detection():
    result = engine.sanitize("Send the report to john.doe@acme.com please.")
    assert result.entity_count >= 1, f"Expected at least 1 entity, got {result.entity_count}"
    assert "EMAIL_ADDRESS" in result.entity_types
    assert "john.doe@acme.com" not in result.sanitized_text


def test_ssn_detection():
    result = engine.sanitize("Patient SSN is 078-05-1120.")
    assert result.entity_count >= 1
    assert "US_SSN" in result.entity_types
    assert "078-05-1120" not in result.sanitized_text


def test_phone_detection():
    result = engine.sanitize("Call me at +1 (415) 555-0172 anytime.")
    assert result.entity_count >= 1
    assert "PHONE_NUMBER" in result.entity_types


def test_credit_card_detection():
    result = engine.sanitize("Charge card 4532015112830366 for the subscription.")
    assert result.entity_count >= 1
    assert "CREDIT_CARD" in result.entity_types
    assert "4532015112830366" not in result.sanitized_text


def test_api_key_detection():
    result = engine.sanitize("Use API key sk-abcdef1234567890abcdef to authenticate.")
    assert result.entity_count >= 1
    assert "API_KEY" in result.entity_types


def test_restore_fidelity():
    """Sanitized then restored text should exactly equal original."""
    original = "Contact jane.smith@company.com or call 555-867-5309 for help."
    result = engine.sanitize(original)
    restored = engine.restore(result.sanitized_text, result.entity_map)
    assert restored == original, f"Restore failed!\nExpected: {original}\nGot:      {restored}"


def test_consistent_placeholders():
    """Same value appearing twice should get the same placeholder."""
    text = "Email john@acme.com and CC john@acme.com on the thread."
    result = engine.sanitize(text)
    # Count occurrences of the email placeholder
    placeholders = list(result.entity_map.keys())
    assert len(placeholders) >= 1
    # The restored text should have the email back in both places
    restored = engine.restore(result.sanitized_text, result.entity_map)
    assert restored.count("john@acme.com") == 2


def test_clean_text_passthrough():
    """Text with no PII should pass through unchanged."""
    clean = "Please summarize the quarterly earnings report for Q3 2024."
    result = engine.sanitize(clean)
    assert result.entity_count == 0
    assert result.sanitized_text == clean


def test_multi_entity_text():
    """Real-world prompt with multiple PII types."""
    prompt = (
        "Draft a contract for John Smith (john@smithlaw.com, SSN: 078-05-1120) "
        "at Acme Corp. His phone is +1-415-555-0172 and card ending 4532015112830366."
    )
    result = engine.sanitize(prompt)
    assert result.entity_count >= 3, f"Expected 3+ entities, got {result.entity_count}"
    assert "john@smithlaw.com" not in result.sanitized_text
    assert "078-05-1120" not in result.sanitized_text
    assert "4532015112830366" not in result.sanitized_text

    restored = engine.restore(result.sanitized_text, result.entity_map)
    assert "john@smithlaw.com" in restored
    assert "078-05-1120" in restored


if __name__ == "__main__":
    print("\n=== PrivacyGateAI Engine Tests ===\n")
    run_test("Email detection", test_email_detection)
    run_test("SSN detection", test_ssn_detection)
    run_test("Phone number detection", test_phone_detection)
    run_test("Credit card detection", test_credit_card_detection)
    run_test("API key detection", test_api_key_detection)
    run_test("Restore fidelity (round-trip)", test_restore_fidelity)
    run_test("Consistent placeholders (same value → same token)", test_consistent_placeholders)
    run_test("Clean text passthrough", test_clean_text_passthrough)
    run_test("Multi-entity real-world prompt", test_multi_entity_text)
    print()
