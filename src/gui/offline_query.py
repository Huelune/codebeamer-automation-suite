from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


class OfflineCbqlError(ValueError):
    query_error_kind = "invalid_query"


@dataclass(frozen=True)
class _Token:
    kind: str
    value: str


_TOKEN_PATTERN = re.compile(
    r"(?P<SPACE>\s+)"
    r"|(?P<NOT_LIKE>NOT\s+LIKE\b)"
    r"|(?P<NOT_IN>NOT\s+IN\b)"
    r"|(?P<AND>AND\b)"
    r"|(?P<OR>OR\b)"
    r"|(?P<LIKE>LIKE\b)"
    r"|(?P<IN>IN\b)"
    r"|(?P<LPAREN>\()"
    r"|(?P<RPAREN>\))"
    r"|(?P<COMMA>,)"
    r"|(?P<OP>!=|>=|<=|=|>|<)"
    r"|(?P<STRING>'(?:''|[^'])*')"
    r"|(?P<NUMBER>-?\d+(?:\.\d+)?)"
    r"|(?P<IDENT>[A-Za-z_][A-Za-z0-9_.]*)",
    re.IGNORECASE,
)


def _tokenize(expression: str) -> tuple[_Token, ...]:
    tokens: list[_Token] = []
    position = 0
    while position < len(expression):
        match = _TOKEN_PATTERN.match(expression, position)
        if match is None:
            fragment = expression[position : position + 24]
            raise OfflineCbqlError(
                f"테스트 모드에서 해석할 수 없는 CbQL 구문입니다: {fragment}"
            )
        position = match.end()
        kind = match.lastgroup or ""
        if kind != "SPACE":
            tokens.append(_Token(kind, match.group()))
    return tuple(tokens)


def _decode_string(value: str) -> str:
    return value[1:-1].replace("''", "'")


def _as_comparable_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, dict):
        values: list[Any] = []
        if value.get("id") is not None:
            values.append(value.get("id"))
        if value.get("name") is not None:
            values.append(value.get("name"))
        if value.get("value") is not None:
            values.extend(_as_comparable_values(value.get("value")))
        if value.get("values") is not None:
            values.extend(_as_comparable_values(value.get("values")))
        return values
    if isinstance(value, (list, tuple, set)):
        values: list[Any] = []
        for item in value:
            values.extend(_as_comparable_values(item))
        return values
    return [value]


def _resolve_item_field(item: dict[str, Any], field_name: str) -> Any:
    normalized = field_name.strip()
    aliases = {
        "item.id": "id",
        "summary": "name",
    }
    path = aliases.get(normalized.casefold(), normalized)
    if path.casefold() == "tracker.id":
        tracker = item.get("tracker")
        if isinstance(tracker, dict):
            return tracker.get("id")
        return item.get("trackerId")

    current: Any = item
    for part in path.split("."):
        if not isinstance(current, dict):
            current = None
            break
        matching_key = next(
            (key for key in current if str(key).casefold() == part.casefold()),
            None,
        )
        if matching_key is None:
            current = None
            break
        current = current.get(matching_key)
    if current is not None:
        return current

    for custom_field in item.get("customFields", []):
        if not isinstance(custom_field, dict):
            continue
        if str(custom_field.get("name") or "").casefold() != normalized.casefold():
            continue
        return custom_field.get("values", custom_field.get("value"))
    return None


def _numbers(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except Exception:
        return None


def _equals(left: Any, right: Any) -> bool:
    left_number = _numbers(left)
    right_number = _numbers(right)
    if left_number is not None and right_number is not None:
        return left_number == right_number
    return str(left).casefold() == str(right).casefold()


def _like(left: Any, pattern: str) -> bool:
    regex_parts: list[str] = []
    for character in str(pattern):
        if character == "%":
            regex_parts.append(".*")
        elif character == "_":
            regex_parts.append(".")
        else:
            regex_parts.append(re.escape(character))
    return re.fullmatch("".join(regex_parts), str(left), re.IGNORECASE | re.DOTALL) is not None


def _compare_scalar(left: Any, operator: str, right: Any) -> bool:
    if operator == "=":
        return _equals(left, right)
    if operator == "!=":
        return not _equals(left, right)
    if operator in {"LIKE", "NOT LIKE"}:
        matches = _like(left, str(right))
        return not matches if operator == "NOT LIKE" else matches

    left_number = _numbers(left)
    right_number = _numbers(right)
    if left_number is not None and right_number is not None:
        comparable_left: Any = left_number
        comparable_right: Any = right_number
    else:
        comparable_left = str(left).casefold()
        comparable_right = str(right).casefold()
    if operator == ">":
        return comparable_left > comparable_right
    if operator == ">=":
        return comparable_left >= comparable_right
    if operator == "<":
        return comparable_left < comparable_right
    if operator == "<=":
        return comparable_left <= comparable_right
    raise OfflineCbqlError(f"지원하지 않는 CbQL 연산자입니다: {operator}")


class _Parser:
    def __init__(self, tokens: tuple[_Token, ...]) -> None:
        self.tokens = tokens
        self.index = 0

    def _peek(self, *kinds: str) -> bool:
        return self.index < len(self.tokens) and self.tokens[self.index].kind in kinds

    def _take(self, *kinds: str) -> _Token:
        if not self._peek(*kinds):
            expected = ", ".join(kinds)
            actual = self.tokens[self.index].value if self.index < len(self.tokens) else "끝"
            raise OfflineCbqlError(
                f"CbQL 구문이 올바르지 않습니다. 예상: {expected}, 현재: {actual}"
            )
        token = self.tokens[self.index]
        self.index += 1
        return token

    def parse(self):
        if not self.tokens:
            return lambda item: True
        evaluator = self._parse_or()
        if self.index != len(self.tokens):
            raise OfflineCbqlError(
                f"CbQL 끝에서 해석하지 못한 값이 있습니다: {self.tokens[self.index].value}"
            )
        return evaluator

    def _parse_or(self):
        evaluators = [self._parse_and()]
        while self._peek("OR"):
            self._take("OR")
            evaluators.append(self._parse_and())
        return lambda item: any(evaluator(item) for evaluator in evaluators)

    def _parse_and(self):
        evaluators = [self._parse_factor()]
        while self._peek("AND"):
            self._take("AND")
            evaluators.append(self._parse_factor())
        return lambda item: all(evaluator(item) for evaluator in evaluators)

    def _parse_factor(self):
        if self._peek("LPAREN"):
            self._take("LPAREN")
            evaluator = self._parse_or()
            self._take("RPAREN")
            return evaluator
        return self._parse_comparison()

    def _parse_value(self) -> Any:
        token = self._take("STRING", "NUMBER", "IDENT")
        if token.kind == "STRING":
            return _decode_string(token.value)
        if token.kind == "NUMBER":
            return float(token.value) if "." in token.value else int(token.value)
        if token.value.upper() == "TRUE":
            return True
        if token.value.upper() == "FALSE":
            return False
        return token.value

    def _parse_comparison(self):
        field_token = self._take("IDENT", "STRING")
        field_name = (
            _decode_string(field_token.value)
            if field_token.kind == "STRING"
            else field_token.value
        )
        operator_token = self._take("OP", "LIKE", "NOT_LIKE", "IN", "NOT_IN")
        operator = re.sub(r"\s+", " ", operator_token.value.upper())
        if operator in {"IN", "NOT IN"}:
            self._take("LPAREN")
            expected_values = [self._parse_value()]
            while self._peek("COMMA"):
                self._take("COMMA")
                expected_values.append(self._parse_value())
            self._take("RPAREN")

            def _evaluate_in(item):
                values = _as_comparable_values(_resolve_item_field(item, field_name))
                found = any(
                    _equals(value, expected)
                    for value in values
                    for expected in expected_values
                )
                return not found if operator == "NOT IN" else found

            return _evaluate_in

        expected = self._parse_value()

        def _evaluate(item):
            values = _as_comparable_values(_resolve_item_field(item, field_name))
            if operator in {"!=", "NOT LIKE"}:
                return bool(values) and all(
                    _compare_scalar(value, operator, expected) for value in values
                )
            return any(_compare_scalar(value, operator, expected) for value in values)

        return _evaluate


def build_offline_cbql_predicate(expression: str):
    return _Parser(_tokenize(str(expression or "").strip())).parse()


__all__ = [
    "OfflineCbqlError",
    "build_offline_cbql_predicate",
]
