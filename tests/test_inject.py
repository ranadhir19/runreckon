import unittest

from runreckon import inject
from runreckon.selftest import BASES, _score_all


class PlantTests(unittest.TestCase):
    def test_every_plant_drops_its_dimension_on_every_base(self):
        for name, build in BASES.items():
            trace, spec = build()
            base_scores = _score_all(trace, spec)
            for defect, (plant, dimension) in inject.PLANTS.items():
                mutant = plant(trace, spec)
                self.assertIsNotNone(mutant, f"{defect} inapplicable on {name}")
                mutant_scores = _score_all(mutant, spec)
                self.assertLess(mutant_scores[dimension], base_scores[dimension],
                                f"{defect} not caught on {name}")

    def test_clean_bases_score_perfectly(self):
        for name, build in BASES.items():
            trace, spec = build()
            for dim, score in _score_all(trace, spec).items():
                self.assertEqual(score, 1.0, f"{name}/{dim} = {score}")

    def test_plants_are_deterministic(self):
        trace, spec = BASES["research-brief"]()
        for plant, _dim in inject.PLANTS.values():
            first = inject.trace_to_jsonl(plant(trace, spec))
            second = inject.trace_to_jsonl(plant(trace, spec))
            self.assertEqual(first, second)

    def test_policy_plant_needs_a_rule(self):
        trace, _spec = BASES["research-brief"]()
        self.assertIsNone(inject.plant_policy_breach(trace, {}))

    def test_plant_does_not_mutate_the_original(self):
        trace, spec = BASES["research-brief"]()
        before = inject.trace_to_jsonl(trace)
        inject.plant_loop_waste(trace, spec)
        self.assertEqual(inject.trace_to_jsonl(trace), before)


if __name__ == "__main__":
    unittest.main()
