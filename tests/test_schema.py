import unittest

from runreckon.schema import validate


class SchemaTests(unittest.TestCase):
    def test_valid_object(self):
        schema = {"type": "object", "required": ["q"],
                  "properties": {"q": {"type": "string", "minLength": 3}}}
        self.assertEqual(validate({"q": "abc"}, schema), [])

    def test_missing_required(self):
        schema = {"type": "object", "required": ["url"]}
        self.assertTrue(validate({}, schema))

    def test_boolean_is_not_an_integer(self):
        # The classic silent-credit trap: True must not satisfy integer.
        self.assertTrue(validate(True, {"type": "integer"}))
        self.assertEqual(validate(True, {"type": "boolean"}), [])

    def test_numeric_string_is_not_a_number(self):
        self.assertTrue(validate("5", {"type": "integer"}))
        self.assertTrue(validate("5", {"type": "number"}))

    def test_integer_satisfies_number(self):
        self.assertEqual(validate(5, {"type": "number"}), [])

    def test_enum_and_range(self):
        schema = {"type": "object", "properties": {
            "table": {"type": "string", "enum": ["users", "orders"]},
            "id": {"type": "integer", "minimum": 1}}}
        self.assertTrue(validate({"table": "secrets", "id": 3}, schema))
        self.assertTrue(validate({"table": "users", "id": 0}, schema))
        self.assertEqual(validate({"table": "users", "id": 3}, schema), [])

    def test_pattern(self):
        schema = {"type": "string", "pattern": "^https?://"}
        self.assertTrue(validate("ftp://x", schema))
        self.assertEqual(validate("https://x", schema), [])

    def test_additional_properties_rejected(self):
        schema = {"type": "object", "properties": {"a": {"type": "integer"}},
                  "additionalProperties": False}
        self.assertTrue(validate({"a": 1, "b": 2}, schema))

    def test_nested_path_in_message(self):
        schema = {"type": "object", "properties": {
            "cfg": {"type": "object", "properties": {
                "n": {"type": "integer"}}}}}
        errors = validate({"cfg": {"n": "x"}}, schema)
        self.assertTrue(any("$.cfg.n" in e for e in errors))

    def test_any_of(self):
        schema = {"anyOf": [{"type": "string"}, {"type": "integer"}]}
        self.assertEqual(validate("x", schema), [])
        self.assertTrue(validate(1.5, schema))


if __name__ == "__main__":
    unittest.main()
