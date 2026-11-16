import unittest

from runreckon.trace import TraceFormatError, parse_trace


class TraceParsingTests(unittest.TestCase):
    def test_minimal_trace(self):
        trace = parse_trace(
            '{"type": "call", "step": 1, "tool": "a", "args": {}}\n'
            '{"type": "result", "step": 1, "ok": true, "output": 1}\n'
            '{"type": "final", "answer": "done", "state": {}}\n')
        self.assertEqual(len(trace.calls), 1)
        self.assertEqual(trace.final.answer, "done")

    def test_malformed_json_names_the_line(self):
        with self.assertRaises(TraceFormatError) as ctx:
            parse_trace('{"type": "call", "step": 1, "tool": "a", "args": {}}\n'
                        'not json\n')
        self.assertEqual(ctx.exception.line, 2)

    def test_missing_result_is_synthesised_as_failure_not_credited(self):
        trace = parse_trace(
            '{"type": "call", "step": 1, "tool": "a", "args": {}}\n'
            '{"type": "final", "answer": "done", "state": {}}\n')
        result = trace.result_for(trace.calls[0])
        self.assertFalse(result.ok)
        self.assertTrue(result.synthesised)
        self.assertEqual(result.error, "no result recorded")

    def test_orphan_result_is_a_format_error(self):
        with self.assertRaises(TraceFormatError):
            parse_trace('{"type": "result", "step": 9, "ok": true}\n')

    def test_two_finals_are_a_format_error(self):
        with self.assertRaises(TraceFormatError):
            parse_trace('{"type": "final", "answer": "a"}\n'
                        '{"type": "final", "answer": "b"}\n')

    def test_calls_after_final_are_counted(self):
        trace = parse_trace(
            '{"type": "call", "step": 1, "tool": "a", "args": {}}\n'
            '{"type": "result", "step": 1, "ok": true}\n'
            '{"type": "final", "answer": "done"}\n'
            '{"type": "call", "step": 2, "tool": "a", "args": {}}\n'
            '{"type": "result", "step": 2, "ok": true}\n')
        self.assertEqual(trace.calls_after_final, 1)

    def test_unknown_events_are_counted_not_fatal(self):
        trace = parse_trace('{"type": "telemetry", "x": 1}\n'
                            '{"type": "final", "answer": "done"}\n')
        self.assertEqual(trace.unknown_events, 1)

    def test_call_with_non_object_args_is_a_format_error(self):
        with self.assertRaises(TraceFormatError):
            parse_trace('{"type": "call", "step": 1, "tool": "a", "args": [1]}\n')


if __name__ == "__main__":
    unittest.main()
