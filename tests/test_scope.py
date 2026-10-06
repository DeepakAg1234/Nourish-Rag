"""Phase 4 checks: the scope guard refuses in code and does not retrieve."""

import unittest

from src.scope import (
    IN_SCOPE,
    IN_SCOPE_POPULATION_GUIDANCE,
    OUT_OF_SCOPE,
    OUT_OF_SCOPE_MESSAGE,
    classify,
    screen,
)


class _RetrieveSpy:
    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, question: str, document_id: str | None = None) -> list:
        self.calls.append(question)
        return []


class OutOfScopeTests(unittest.TestCase):
    def test_diabetes_diet_refuses_without_retrieval(self):
        self._assert_refused("I have diabetes. What diet should I follow?")

    def test_personal_calorie_target_refuses_without_retrieval(self):
        self._assert_refused("How many calories should I eat to lose 5 kg?")

    def test_weight_target_refuses_without_retrieval(self):
        self._assert_refused("What should I weigh?")

    def test_who_fat_limit_plus_personal_calories_refuses_without_retrieval(self):
        self._assert_refused("Using the WHO fat limit, how many calories should I eat?")

    def test_eatwell_plus_personal_calories_refuses_without_retrieval(self):
        self._assert_refused("According to the Eatwell Guide, how many calories should I eat?")

    def test_calorie_deficit_and_goal_weight_refuse(self):
        self._assert_refused("What calorie deficit should I use?")
        self._assert_refused("What is my goal weight?")

    def test_medication_refuses_without_retrieval(self):
        self._assert_refused("Which medication should I take for high blood sugar?")

    def _assert_refused(self, question: str):
        retrieve = _RetrieveSpy()
        result = screen(question, retrieve)
        self.assertEqual(result["decision"], OUT_OF_SCOPE)
        self.assertEqual(classify(question), OUT_OF_SCOPE)
        self.assertEqual(result["message"], OUT_OF_SCOPE_MESSAGE)
        self.assertIn("qualified professional", result["message"])
        self.assertNotIn("http", result["message"])
        self.assertNotIn("Eatwell", result["message"])
        self.assertNotIn("FoodSafety", result["message"])
        self.assertIsNone(result["chunks"])
        self.assertEqual(retrieve.calls, [])


class InScopeTests(unittest.TestCase):
    def test_fat_share_is_population_guidance_and_may_retrieve(self):
        question = "What share of energy intake does WHO recommend from fat?"
        self._assert_allowed(question, IN_SCOPE_POPULATION_GUIDANCE)

    def test_published_eatwell_calorie_figures_are_population_guidance(self):
        question = "What calorie figures does the Eatwell Guide publish?"
        self._assert_allowed(question, IN_SCOPE_POPULATION_GUIDANCE)

    def test_salt_limit_is_population_guidance(self):
        question = "Is salt under 5 g a day?"
        self._assert_allowed(question, IN_SCOPE_POPULATION_GUIDANCE)

    def test_egg_storage_is_in_scope(self):
        self._assert_allowed("How long can raw eggs stay in the refrigerator?", IN_SCOPE)

    def test_per_food_protein_is_in_scope(self):
        question = "How much protein is in 100 g of chicken?"
        self._assert_allowed(question, IN_SCOPE)
        self.assertNotEqual(classify(question), OUT_OF_SCOPE)

    def test_eatwell_oils_is_in_scope(self):
        self._assert_allowed("What does the Eatwell Guide say about oils?", IN_SCOPE)

    def _assert_allowed(self, question: str, decision: str):
        retrieve = _RetrieveSpy()
        result = screen(question, retrieve)
        self.assertEqual(result["decision"], decision)
        self.assertEqual(classify(question), decision)
        self.assertIsNone(result["message"])
        self.assertEqual(result["chunks"], [])
        self.assertEqual(retrieve.calls, [question])


if __name__ == "__main__":
    unittest.main()
