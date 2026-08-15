"""
Regulated Data and PII Redactor.
Performs pattern-based and structured field masking for financial data,
credentials, tokens, SSNs, account numbers, and personal identifiers.
"""
import re
from typing import Any, Dict, List, Union

# Regex patterns for sensitive financial and authentication data
SSN_REGEX = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
CARD_PAN_REGEX = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")
BEARER_TOKEN_REGEX = re.compile(r"\b(Bearer\s+)[a-zA-Z0-9_\-\.]{15,}\b", re.IGNORECASE)
GENERIC_SECRET_REGEX = re.compile(r"(api[_-]?key|password|secret|token|auth)\s*[:=]\s*['\"]?([a-zA-Z0-9_\-\.]{8,})['\"]?", re.IGNORECASE)
ACCOUNT_NUMBER_REGEX = re.compile(r"\b009\d{5}-\d{2}\b")


class PIIRedactor:
    """Masks sensitive financial data before persistence or logging."""

    @staticmethod
    def mask_ssn(ssn: str) -> str:
        if len(ssn) >= 4:
            return f"***-**-{ssn[-4:]}"
        return "***-**-****"

    @staticmethod
    def mask_card_pan(pan: str) -> str:
        clean = re.sub(r"[\s-]", "", pan)
        if len(clean) >= 4:
            return f"****-****-****-{clean[-4:]}"
        return "****-****-****-****"

    @staticmethod
    def mask_account_number(acc: str) -> str:
        if len(acc) >= 4:
            return f"*****{acc[-4:]}"
        return "********"

    @classmethod
    def redact_text(cls, text: str) -> str:
        if not text or not isinstance(text, str):
            return text

        # Redact SSN
        text = SSN_REGEX.sub(lambda m: cls.mask_ssn(m.group(0)), text)
        # Redact Credit Cards
        text = CARD_PAN_REGEX.sub(lambda m: cls.mask_card_pan(m.group(0)), text)
        # Redact Bearer Tokens
        text = BEARER_TOKEN_REGEX.sub(r"\1[REDACTED_TOKEN]", text)
        # Redact Generic Secrets
        text = GENERIC_SECRET_REGEX.sub(r"\1=[REDACTED_SECRET]", text)
        return text

    @classmethod
    def redact_structured_data(cls, data: Union[Dict[str, Any], List[Any], str, Any]) -> Any:
        """Recursively redact dictionaries, lists, and primitives."""
        if isinstance(data, dict):
            redacted = {}
            for k, v in data.items():
                if isinstance(v, (dict, list)):
                    redacted[k] = cls.redact_structured_data(v)
                else:
                    lower_k = k.lower()
                    if any(sec in lower_k for sec in ["password", "secret", "token", "api_key", "credential"]):
                        redacted[k] = "[REDACTED_SECRET]"
                    elif "ssn" in lower_k and isinstance(v, str):
                        redacted[k] = cls.mask_ssn(v)
                    elif "card" in lower_k and isinstance(v, str):
                        redacted[k] = cls.mask_card_pan(v)
                    else:
                        redacted[k] = cls.redact_structured_data(v)
            return redacted
        elif isinstance(data, list):
            return [cls.redact_structured_data(item) for item in data]
        elif isinstance(data, str):
            return cls.redact_text(data)
        return data
