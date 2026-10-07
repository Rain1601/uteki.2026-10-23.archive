"""Strict JSON object parsing; pure offline checks with no model requests."""
import unittest

from uteki.agents.runtime.strict_json import StrictJSONError, parse_json_object


class StrictJSONTests(unittest.TestCase):
    def assert_rejected(self, text, code):
        with self.assertRaises(StrictJSONError) as caught:
            parse_json_object(text)
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), f'JSON output rejected: {code}')
        self.assertNotIn('SECRET_KEY', str(caught.exception))
        self.assertNotIn('PRIVATE_VALUE', str(caught.exception))

    def test_accepts_objects_with_whitespace_nested_types_and_literal_nan_text(self):
        source = ' \n\t{"name":"NaN","中文":"原文","nested":{"values":[null,true,false,0,-7,1.5,1e308,{"x":1}]},"separate":{"x":2}}\r\n'
        original = source[:]
        parsed = parse_json_object(source)
        self.assertIs(type(parsed), dict)
        self.assertEqual(parsed, {
            'name': 'NaN', '中文': '原文',
            'nested': {'values': [None, True, False, 0, -7, 1.5, 1e308, {'x': 1}]},
            'separate': {'x': 2},
        })
        self.assertEqual(parse_json_object('{}'), {})
        parsed['nested']['values'].append('new value')
        self.assertEqual(source, original)

    def test_rejects_duplicate_keys_at_every_depth_after_escape_decoding(self):
        cases = (
            '{"SECRET_KEY":1,"SECRET_KEY":2}',
            '{"outer":{"SECRET_KEY":null,"SECRET_KEY":"PRIVATE_VALUE"}}',
            '{"outer":[0,{"deeper":[{"SECRET_KEY":true,"SECRET_KEY":false}]}]}',
            r'{"SECRET_KEY":1,"\u0053ECRET_KEY":2}',
            r'{"outer":{"x":1,"\u0078":2}}',
        )
        for source in cases:
            with self.subTest(source=source):
                self.assert_rejected(source, 'duplicate_key')

    def test_rejects_non_finite_numbers_in_objects_arrays_and_root(self):
        for token in ('NaN', 'Infinity', '-Infinity', '1e999', '-1e999'):
            for source in (token, '{"SECRET_KEY":' + token + '}',
                           '{"outer":[{"values":[0,' + token + ']}]}'):
                with self.subTest(token=token, source=source):
                    self.assert_rejected(source, 'non_finite_number')

    def test_rejects_malformed_json_wrappers_prefaces_and_multiple_objects(self):
        cases = (
            '', ' \n\t', '{"SECRET_KEY":"PRIVATE_VALUE",}',
            '{"SECRET_KEY":"PRIVATE_VALUE"',
            '```json\n{"SECRET_KEY":"PRIVATE_VALUE"}\n```',
            '<result>{"SECRET_KEY":"PRIVATE_VALUE"}</result>',
            'The answer is {"SECRET_KEY":"PRIVATE_VALUE"}',
            '{"SECRET_KEY":"PRIVATE_VALUE"} trailing prose',
            '{}{}', '{} \n {"SECRET_KEY":"PRIVATE_VALUE"}',
        )
        for source in cases:
            with self.subTest(source=source):
                self.assert_rejected(source, 'invalid_json')

    def test_rejects_valid_json_roots_that_are_not_objects(self):
        for source in ('[]', '[{"SECRET_KEY":"PRIVATE_VALUE"}]', 'null', '0', '-12',
                       '1.25', 'true', 'false', '"PRIVATE_VALUE"'):
            with self.subTest(source=source):
                self.assert_rejected(source, 'root_not_object')


if __name__ == '__main__':
    unittest.main()
