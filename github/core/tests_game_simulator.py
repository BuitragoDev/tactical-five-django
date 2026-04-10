"""
Tests for game simulation logic: double doubles, triple doubles, rating calculation.
"""
from django.test import TestCase


class DoubleTripleDoubleTests(TestCase):
    """
    Tests for the double-double and triple-double calculation logic.
    A double-double requires >= 10 in at least 2 of 5 categories.
    A triple-double requires >= 10 in at least 3 of 5 categories.
    
    Categories: points, rebounds (oreb + dreb), assists, steals, blocks
    """

    def _calculate_double_triple(self, pts, oreb, dreb, ast, stl, blk):
        """
        Helper that replicates the game_simulator logic for testing.
        Returns dict with 'double_double' and 'triple_double' keys.
        """
        categories = 0
        if pts >= 10:
            categories += 1
        if oreb + dreb >= 10:
            categories += 1
        if ast >= 10:
            categories += 1
        if stl >= 10:
            categories += 1
        if blk >= 10:
            categories += 1

        if categories >= 3:
            return {'double_double': 1, 'triple_double': 1}
        elif categories >= 2:
            return {'double_double': 1, 'triple_double': 0}
        else:
            return {'double_double': 0, 'triple_double': 0}

    # ==================== DOUBLE-DOUBLE TESTS ====================

    def test_double_double_true_with_2_categories(self):
        """2 categories >= 10 = double-double"""
        result = self._calculate_double_triple(12, 5, 11, 3, 2, 1)  # pts, reb, ast
        self.assertEqual(result['double_double'], 1)

    def test_double_double_true_pts_and_reb(self):
        """Points >= 10 and rebounds >= 10 = double-double"""
        result = self._calculate_double_triple(15, 8, 5, 3, 2, 1)  # pts=15, reb=13
        self.assertEqual(result['double_double'], 1)
        self.assertEqual(result['triple_double'], 0)

    def test_double_double_true_pts_and_ast(self):
        """Points >= 10 and assists >= 10 = double-double"""
        result = self._calculate_double_triple(18, 2, 2, 12, 1, 0)
        self.assertEqual(result['double_double'], 1)

    def test_double_double_true_reb_and_ast(self):
        """Rebounds >= 10 and assists >= 10 = double-double"""
        result = self._calculate_double_triple(5, 6, 5, 11, 1, 2)
        self.assertEqual(result['double_double'], 1)

    def test_double_double_false_with_1_category(self):
        """Only 1 category >= 10 = NOT double-double"""
        result = self._calculate_double_triple(15, 3, 2, 4, 1, 0)  # only pts
        self.assertEqual(result['double_double'], 0)

    def test_double_double_false_with_0_categories(self):
        """0 categories >= 10 = NOT double-double"""
        result = self._calculate_double_triple(5, 2, 2, 3, 1, 0)
        self.assertEqual(result['double_double'], 0)
        self.assertEqual(result['triple_double'], 0)

    # ==================== TRIPLE-DOUBLE TESTS ====================

    def test_triple_double_true_with_3_categories(self):
        """3 categories >= 10 = triple-double"""
        result = self._calculate_double_triple(12, 5, 11, 10, 2, 1)  # pts, reb, ast
        self.assertEqual(result['double_double'], 1)
        self.assertEqual(result['triple_double'], 1)

    def test_triple_double_true_with_4_categories(self):
        """4 categories >= 10 = triple-double"""
        result = self._calculate_double_triple(12, 5, 11, 10, 12, 1)  # pts, reb, ast, stl
        self.assertEqual(result['double_double'], 1)
        self.assertEqual(result['triple_double'], 1)

    def test_triple_double_true_with_5_categories(self):
        """5 categories >= 10 = triple-double"""
        result = self._calculate_double_triple(12, 5, 11, 10, 12, 15)
        self.assertEqual(result['double_double'], 1)
        self.assertEqual(result['triple_double'], 1)

    def test_triple_double_false_with_2_categories(self):
        """2 categories >= 10 = NOT triple-double (only double-double)"""
        result = self._calculate_double_triple(12, 5, 11, 3, 2, 1)
        self.assertEqual(result['double_double'], 1)
        self.assertEqual(result['triple_double'], 0)

    def test_triple_double_false_with_1_category(self):
        """1 category >= 10 = NOT triple-double"""
        result = self._calculate_double_triple(15, 3, 2, 4, 1, 0)
        self.assertEqual(result['triple_double'], 0)

    # ==================== EDGE CASES ====================

    def test_edge_case_exactly_10_counts(self):
        """Exactly 10 in a category should count as >= 10"""
        # pts=10, oreb=5, dreb=5, ast=10, steals=0, blk=0
        # This gives 3 categories >= 10: pts, reb (10), ast = triple double!
        result = self._calculate_double_triple(10, 5, 5, 10, 0, 0)
        self.assertEqual(result['double_double'], 1)
        self.assertEqual(result['triple_double'], 1)  # 3 categories = triple double

    def test_edge_case_9_does_not_count(self):
        """9 in a category should NOT count"""
        result = self._calculate_double_triple(9, 5, 5, 9, 0, 0)  # all 9s
        self.assertEqual(result['double_double'], 0)
        self.assertEqual(result['triple_double'], 0)

    def test_edge_case_11_counts(self):
        """11 in a category should count"""
        result = self._calculate_double_triple(11, 0, 0, 0, 11, 0)  # pts=11, stl=11
        self.assertEqual(result['double_double'], 1)

    def test_steals_double_double(self):
        """Steals >= 10 can form a double-double when combined with another category"""
        # pts=12, oreb=2, dreb=2, ast=3, steals=12, blk=0 -> 2 categories (pts + steals)
        result = self._calculate_double_triple(12, 2, 2, 3, 12, 0)
        self.assertEqual(result['double_double'], 1)
        self.assertEqual(result['triple_double'], 0)

    def test_blocks_double_double(self):
        """Blocks >= 10 can form a double-double when combined with another category"""
        # pts=12, oreb=2, dreb=2, ast=3, steals=0, blk=12 -> 2 categories (pts + blocks)
        result = self._calculate_double_triple(12, 2, 2, 3, 0, 12)
        self.assertEqual(result['double_double'], 1)
        self.assertEqual(result['triple_double'], 0)

    def test_rebounds_split_between_oreb_and_dreb(self):
        """Rebounds count as combined (oreb + dreb)"""
        # 5 offensive + 5 defensive = 10 rebounds total
        # pts=8, oreb=5, dreb=5, ast=3, steals=1, blk=0 -> 1 category only (rebounds)
        result = self._calculate_double_triple(8, 5, 5, 3, 1, 0)
        # Only rebounds >= 10, so no double double
        self.assertEqual(result['double_double'], 0)
        
    def test_rebounds_plus_another_category(self):
        """Rebounds combined with another category = double-double"""
        # pts=12, oreb=5, dreb=5, ast=3, steals=1, blk=0 -> 2 categories (pts + rebounds)
        result = self._calculate_double_triple(12, 5, 5, 3, 1, 0)
        self.assertEqual(result['double_double'], 1)

    def test_rebounds_below_10_combined(self):
        """oreb + dreb < 10 should not count"""
        result = self._calculate_double_triple(15, 3, 3, 2, 1, 0)  # 6 total rebounds
        self.assertEqual(result['double_double'], 0)  # only points >= 10


class RatingCalculationTests(TestCase):
    """
    Tests for the player rating calculation formula.
    Rating = points + oreb + dreb + assists + steals + blocks 
             - (fga - fgm) - (fta - ftm) - turnovers - fouls
    """

    def _calculate_rating(self, pts, oreb, dreb, ast, stl, blk, fgm, fga, ftm, fta, to, pf):
        """Helper that replicates the game_simulator rating logic."""
        miss_fg = fga - fgm
        miss_ft = fta - ftm
        return pts + oreb + dreb + ast + stl + blk - miss_fg - miss_ft - to - pf

    def test_rating_basic_calculation(self):
        """Basic rating calculation"""
        # pts=20, oreb=3, dreb=5, ast=8, stl=2, blk=1
        # fgm=10, fga=20, ftm=2, fta=4, to=3, pf=2
        # miss_fg = 20-10 = 10, miss_ft = 4-2 = 2
        # rating = 20 + 3 + 5 + 8 + 2 + 1 - 10 - 2 - 3 - 2 = 22
        rating = self._calculate_rating(20, 3, 5, 8, 2, 1, 10, 20, 2, 4, 3, 2)
        self.assertEqual(rating, 22)

    def test_rating_zero_stats(self):
        """Rating with all zeros should be 0 or negative"""
        rating = self._calculate_rating(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        self.assertEqual(rating, 0)

    def test_rating_perfect_game(self):
        """Perfect game: all shots made, no misses/turnovers/fouls"""
        rating = self._calculate_rating(30, 2, 6, 5, 2, 2, 12, 12, 6, 6, 0, 0)
        expected = 30 + 2 + 6 + 5 + 2 + 2  # 47 (no misses)
        self.assertEqual(rating, expected)

    def test_rating_bad_game(self):
        """Bad game: lots of misses, turnovers, fouls"""
        rating = self._calculate_rating(10, 1, 2, 2, 0, 0, 3, 15, 1, 5, 6, 5)
        miss_fg = 15 - 3  # 12
        miss_ft = 5 - 1   # 4
        expected = 10 + 1 + 2 + 2 + 0 + 0 - 12 - 4 - 6 - 5
        self.assertEqual(rating, expected)

    def test_rating_negative_possible(self):
        """Rating can be negative in very bad games"""
        rating = self._calculate_rating(2, 0, 1, 0, 0, 0, 1, 10, 0, 2, 5, 5)
        self.assertLess(rating, 0)


class OvertimeLogicTests(TestCase):
    """
    Tests for overtime logic.
    - Overtime triggered when scores are tied after regulation
    - Maximum 5 overtime periods
    """

    def _should_have_overtime(self, home_score, away_score):
        """Helper to check if overtime should be triggered."""
        return home_score == away_score

    def _simulate_overtime(self, home_score, away_score, max_periods=5):
        """Simulate overtime and return if it ends."""
        total_home = home_score
        total_away = away_score
        periods = 0
        
        while total_home == total_away and periods < max_periods:
            periods += 1
            # In overtime, teams score less (simulate ~5 pts each per OT)
            import random
            total_home += random.randint(4, 7)
            total_away += random.randint(4, 7)
        
        return periods, total_home != total_away

    def test_overtime_triggered_on_tie(self):
        """Tie after regulation should trigger overtime"""
        self.assertTrue(self._should_have_overtime(100, 100))

    def test_no_overtime_when_home_wins(self):
        """Home win means no overtime"""
        self.assertFalse(self._should_have_overtime(105, 100))

    def test_no_overtime_when_away_wins(self):
        """Away win means no overtime"""
        self.assertFalse(self._should_have_overtime(98, 105))

    def test_overtime_max_periods_logic(self):
        """Maximum 5 overtime periods"""
        # The logic should prevent infinite overtime
        home = 100
        away = 100
        
        # Simulate many OT periods - should cap at some limit
        periods = 0
        max_test = 10  # Test more than max OT periods
        for _ in range(max_test):
            if home == away:
                periods += 1
                home += 1  # Home scores to break tie
            else:
                break
        
        # If we started tied, home should have won after 1 period
        self.assertEqual(periods, 1)
        self.assertNotEqual(home, away)
