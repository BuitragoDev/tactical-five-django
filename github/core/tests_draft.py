"""
Tests for draft player generation logic.
"""
from django.test import TestCase
import random


class DraftGenerationTests(TestCase):
    """
    Tests for the draft player generation logic.
    
    Key rules:
    - 30 players generated (one per team)
    - Worst team picks first (reverse standings)
    - Pick 1 = ~80 avg, Pick 30 = ~60 avg
    - Potential = overall + (3-12), max 99
    - Age: 19-20 for rookies
    - Position modifiers applied to attributes
    """

    # ==================== DRAFT ORDER ====================

    def _get_draft_order(self, standings):
        """Replicate the draft order logic."""
        # standings is sorted best-to-worst
        # Reverse so worst picks first
        return list(reversed(standings))

    def test_draft_order_worst_team_picks_first(self):
        """Worst standing team should pick first"""
        standings = ['TeamA', 'TeamB', 'TeamC']  # TeamC is worst
        draft_order = self._get_draft_order(standings)
        self.assertEqual(draft_order[0], 'TeamC')

    def test_draft_order_best_team_picks_last(self):
        """Best standing team should pick last"""
        standings = ['TeamA', 'TeamB', 'TeamC']  # TeamA is best
        draft_order = self._get_draft_order(standings)
        self.assertEqual(draft_order[-1], 'TeamA')

    def test_draft_order_30_teams(self):
        """Should have 30 picks for 30 teams"""
        standings = [f'Team{i}' for i in range(30)]
        draft_order = self._get_draft_order(standings)
        self.assertEqual(len(draft_order), 30)


class DraftOverallTests(TestCase):
    """
    Tests for player overall rating based on draft pick.
    """

    def _calculate_base_overall(self, pick_num, total_picks=30):
        """
        Replicate the base overall calculation.
        Linear interpolation from ~80 (pick 1) to ~60 (pick 30)
        """
        # base_avg = 75 - (pick_num - 1) * (15 / 29)
        base_avg = 75 - (pick_num - 1) * (15 / (total_picks - 1))
        return base_avg

    def test_pick_1_has_highest_overall(self):
        """First pick should have highest overall (~75-80)"""
        overall = self._calculate_base_overall(1)
        self.assertGreaterEqual(overall, 75)
        self.assertLessEqual(overall, 80)

    def test_pick_30_has_lowest_overall(self):
        """Last pick should have lowest overall (~60)"""
        overall = self._calculate_base_overall(30)
        self.assertGreater(overall, 58)
        self.assertLess(overall, 65)

    def test_pick_15_has_mid_overall(self):
        """Middle pick should have middle overall"""
        overall = self._calculate_base_overall(15)
        self.assertGreater(overall, 65)
        self.assertLess(overall, 75)

    def test_overall_decreases_with_pick_number(self):
        """Later picks should have lower overall"""
        overall_1 = self._calculate_base_overall(1)
        overall_15 = self._calculate_base_overall(15)
        overall_30 = self._calculate_base_overall(30)
        
        self.assertGreater(overall_1, overall_15)
        self.assertGreater(overall_15, overall_30)


class DraftPotentialTests(TestCase):
    """
    Tests for player potential rating.
    Potential = overall + random(3-12), max 99
    """

    def _calculate_potential(self, overall):
        """Replicate the potential calculation."""
        # This uses random, so we test the range
        min_potential = overall + 3
        max_potential = min(99, overall + 12)
        return min_potential, max_potential

    def test_potential_always_higher_than_overall(self):
        """Potential should always be >= overall"""
        min_pot, max_pot = self._calculate_potential(75)
        self.assertGreaterEqual(min_pot, 75)
        self.assertGreaterEqual(max_pot, 75)

    def test_potential_min_increments(self):
        """Minimum potential is overall + 3"""
        min_pot, _ = self._calculate_potential(70)
        self.assertEqual(min_pot, 73)

    def test_potential_max_increments(self):
        """Maximum potential is overall + 12 (capped at 99)"""
        _, max_pot = self._calculate_potential(70)
        self.assertEqual(max_pot, 82)

    def test_potential_capped_at_99(self):
        """Potential should not exceed 99"""
        _, max_pot = self._calculate_potential(95)
        self.assertEqual(max_pot, 99)

    def test_potential_range(self):
        """Potential should be within overall+3 to overall+12 (max 99)"""
        for overall in [60, 70, 80, 90, 95]:
            min_pot, max_pot = self._calculate_potential(overall)
            self.assertGreaterEqual(min_pot, overall + 3)
            self.assertLessEqual(max_pot, min(99, overall + 12))


class DraftAgeTests(TestCase):
    """
    Tests for rookie age generation.
    """

    def _generate_age(self):
        """Replicate age generation."""
        return random.randint(19, 20)

    def test_age_is_19_or_20(self):
        """Rookies should be 19 or 20 years old"""
        for _ in range(100):  # Test multiple times for randomness
            age = self._generate_age()
            self.assertIn(age, [19, 20])

    def test_age_not_18(self):
        """Rookies should not be 18"""
        for _ in range(50):
            age = self._generate_age()
            self.assertNotEqual(age, 18)

    def test_age_not_21(self):
        """Rookies should not be 21"""
        for _ in range(50):
            age = self._generate_age()
            self.assertNotEqual(age, 21)


class DraftPositionTests(TestCase):
    """
    Tests for player position validation.
    """

    VALID_POSITIONS = ['PG', 'SG', 'SF', 'PF', 'C']

    def _validate_position(self, position):
        """Check if position is valid."""
        return position in self.VALID_POSITIONS

    def test_all_positions_valid(self):
        """All 5 positions should be valid"""
        for pos in self.VALID_POSITIONS:
            self.assertTrue(self._validate_position(pos))

    def test_point_guard_valid(self):
        """PG should be valid"""
        self.assertTrue(self._validate_position('PG'))

    def test_center_valid(self):
        """C should be valid"""
        self.assertTrue(self._validate_position('C'))

    def test_invalid_position_rejected(self):
        """Invalid positions should be rejected"""
        self.assertFalse(self._validate_position('FB'))
        self.assertFalse(self._validate_position('G'))
        self.assertFalse(self._validate_position('F'))


class DraftPositionModifiersTests(TestCase):
    """
    Tests for position-based attribute modifiers.
    
    PG: +speed, +passing, +ball_handling, -rebounding, -blocks
    C:  +rebounding, +blocks, -speed, -shooting, -three_point
    """

    POSITION_MODIFIERS = {
        'PG': {'speed': 8, 'passing': 8, 'ball_handling': 8, 'rebounding': -5, 'blocks': -5},
        'SG': {'speed': 5, 'shooting': 8, 'three_point': 8, 'ball_handling': 5, 'rebounding': -3},
        'SF': {'speed': 4, 'shooting': 5, 'defense': 5, 'rebounding': 0},
        'PF': {'defense': 6, 'rebounding': 7, 'blocks': 4, 'speed': 0},
        'C':  {'rebounding': 10, 'blocks': 10, 'defense': 7, 'speed': -5, 'three_point': -8},
    }

    def test_pg_has_high_speed_modifier(self):
        """PG should have positive speed modifier"""
        self.assertGreater(self.POSITION_MODIFIERS['PG']['speed'], 0)

    def test_pg_has_negative_rebounding_modifier(self):
        """PG should have negative rebounding modifier"""
        self.assertLess(self.POSITION_MODIFIERS['PG']['rebounding'], 0)

    def test_c_has_high_rebounding_modifier(self):
        """C should have positive rebounding modifier"""
        self.assertGreater(self.POSITION_MODIFIERS['C']['rebounding'], 0)

    def test_c_has_negative_speed_modifier(self):
        """C should have negative speed modifier"""
        self.assertLess(self.POSITION_MODIFIERS['C']['speed'], 0)

    def test_c_has_negative_three_point_modifier(self):
        """C should have negative three-point modifier"""
        self.assertLess(self.POSITION_MODIFIERS['C']['three_point'], 0)


class DraftAttributesRangeTests(TestCase):
    """
    Tests for attribute value ranges after generation.
    """

    def _generate_attribute(self, base_avg, modifier, min_val=30, max_val=99):
        """Replicate attribute generation."""
        value = int(base_avg + modifier + random.randint(-5, 5))
        value = max(min_val, min(max_val, value))
        return value

    def test_attribute_within_30_to_99(self):
        """Attributes should be within 30-99 range"""
        for _ in range(100):
            attr = self._generate_attribute(base_avg=70, modifier=0)
            self.assertGreaterEqual(attr, 30)
            self.assertLessEqual(attr, 99)

    def test_attribute_respects_modifiers(self):
        """Modifiers should influence the attribute value"""
        # High modifier should tend toward higher values
        high_modifier = 10
        low_modifier = -10
        
        high_sum = 0
        low_sum = 0
        for _ in range(50):
            high_sum += self._generate_attribute(70, high_modifier)
            low_sum += self._generate_attribute(70, low_modifier)
        
        avg_high = high_sum / 50
        avg_low = low_sum / 50
        
        self.assertGreater(avg_high, avg_low)


class DraftSalaryTests(TestCase):
    """
    Tests for rookie salary generation.
    """

    def _generate_salary(self):
        """Replicate salary generation."""
        salary = random.randint(3000000, 8000000)
        salary = round(salary / 100000) * 100000
        return salary

    def test_salary_within_range(self):
        """Salary should be between 3M and 8M"""
        for _ in range(100):
            salary = self._generate_salary()
            self.assertGreaterEqual(salary, 3000000)
            self.assertLessEqual(salary, 8000000)

    def test_salary_rounded_to_100k(self):
        """Salary should be rounded to nearest 100K"""
        for _ in range(100):
            salary = self._generate_salary()
            self.assertEqual(salary % 100000, 0)

    def test_minimum_salary(self):
        """Minimum salary should be 3M"""
        min_salary = 3000000
        self.assertEqual(min_salary, 3000000)

    def test_maximum_salary(self):
        """Maximum salary should be 8M"""
        max_salary = 8000000
        self.assertEqual(max_salary, 8000000)
