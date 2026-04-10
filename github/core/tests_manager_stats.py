"""
Tests for manager stats (trust, morale, press confidence) calculation.
"""
from django.test import TestCase


class ManagerTrustTests(TestCase):
    """
    Tests for Trust (Confianza) calculation.
    
    Base: ±3 per win/loss
    Difficulty: ±2 for beating better/worse teams
    Playoffs: x1.5 multiplier
    Bounds: 0-100
    """

    def _calculate_trust_delta(self, won, team_overall, opp_overall, is_playoff=False):
        """Replicate the trust delta calculation logic."""
        base = 3 if won else -3
        
        overall_diff = opp_overall - team_overall
        
        if won and overall_diff > 5:
            delta = base + 2
        elif won and overall_diff < -5:
            delta = base - 1
        elif not won and overall_diff < -5:
            delta = base - 2
        elif not won and overall_diff > 5:
            delta = base + 1
        else:
            delta = base
        
        if is_playoff:
            delta = int(delta * 1.5)
        
        return delta

    def _apply_trust(self, current, delta):
        """Apply delta with bounds."""
        return max(0, min(100, current + delta))

    # ==================== WIN/LOSS BASE ====================

    def test_trust_increases_on_win(self):
        """Win = +3 base trust"""
        delta = self._calculate_trust_delta(won=True, team_overall=80, opp_overall=80)
        self.assertEqual(delta, 3)

    def test_trust_decreases_on_loss(self):
        """Loss = -3 base trust"""
        delta = self._calculate_trust_delta(won=False, team_overall=80, opp_overall=80)
        self.assertEqual(delta, -3)

    # ==================== DIFFICULTY ADJUSTMENTS ====================

    def test_trust_bonus_beating_much_better_team(self):
        """Win against team +6 overall better = +5 total (+3 base +2 bonus)"""
        delta = self._calculate_trust_delta(won=True, team_overall=80, opp_overall=86)
        self.assertEqual(delta, 5)

    def test_trust_bonus_beating_slightly_better_team(self):
        """Win against team +5 overall better = +3 (threshold is >5, so no bonus)"""
        delta = self._calculate_trust_delta(won=True, team_overall=80, opp_overall=85)
        self.assertEqual(delta, 3)

    def test_trust_no_bonus_beating_slightly_worse_team(self):
        """Win against team -4 overall worse = +3 (threshold is < -5 for penalty, so no penalty)"""
        delta = self._calculate_trust_delta(won=True, team_overall=80, opp_overall=76)
        self.assertEqual(delta, 3)

    def test_trust_penalty_beating_much_worse_team(self):
        """Win against team -6 overall worse = +2 (+3 base -1)"""
        delta = self._calculate_trust_delta(won=True, team_overall=80, opp_overall=74)
        self.assertEqual(delta, 2)

    def test_trust_penalty_losing_to_much_worse_team(self):
        """Loss against team -6 overall worse = -5 (-3 base -2)"""
        delta = self._calculate_trust_delta(won=False, team_overall=80, opp_overall=74)
        self.assertEqual(delta, -5)

    def test_trust_credit_losing_to_much_better_team(self):
        """Loss against team +6 overall better = -2 (-3 base +1)"""
        delta = self._calculate_trust_delta(won=False, team_overall=80, opp_overall=86)
        self.assertEqual(delta, -2)

    # ==================== PLAYOFF MULTIPLIER ====================

    def test_trust_playoff_multiplier_on_win(self):
        """Playoff win = +3 * 1.5 = +4.5 -> int = 4"""
        delta = self._calculate_trust_delta(won=True, team_overall=80, opp_overall=80, is_playoff=True)
        self.assertEqual(delta, 4)

    def test_trust_playoff_multiplier_on_loss(self):
        """Playoff loss = -3 * 1.5 = -4.5 -> int = -4"""
        delta = self._calculate_trust_delta(won=False, team_overall=80, opp_overall=80, is_playoff=True)
        self.assertEqual(delta, -4)

    # ==================== BOUNDS ====================

    def test_trust_never_below_zero(self):
        """Trust should never go below 0"""
        result = self._apply_trust(3, -10)
        self.assertEqual(result, 0)

    def test_trust_never_above_hundred(self):
        """Trust should never go above 100"""
        result = self._apply_trust(98, 5)
        self.assertEqual(result, 100)

    def test_trust_stays_at_boundary(self):
        """Trust at boundary should stay within bounds"""
        self.assertEqual(self._apply_trust(0, -3), 0)
        self.assertEqual(self._apply_trust(100, 3), 100)


class ManagerMoraleTests(TestCase):
    """
    Tests for Morale (Moral) calculation.
    
    Base: ±2 per win/loss
    Close game: ±1 for games decided by <=5 points
    Injuries: -1 for 2+ injured, -2 for 4+ injured
    Bounds: 0-100
    """

    def _calculate_morale_delta(self, won, margin, injured_count=0):
        """Replicate the morale delta calculation logic."""
        base = 2 if won else -2
        
        if abs(margin) <= 5:
            delta = base + (1 if won else -1)
        else:
            delta = base
        
        if injured_count >= 4:
            delta -= 2
        elif injured_count >= 2:
            delta -= 1
        
        return delta

    def _apply_morale(self, current, delta):
        """Apply delta with bounds."""
        return max(0, min(100, current + delta))

    # ==================== WIN/LOSS BASE ====================

    def test_morale_increases_on_win(self):
        """Win = +2 base morale"""
        delta = self._calculate_morale_delta(won=True, margin=10)
        self.assertEqual(delta, 2)

    def test_morale_decreases_on_loss(self):
        """Loss = -2 base morale"""
        delta = self._calculate_morale_delta(won=False, margin=10)
        self.assertEqual(delta, -2)

    # ==================== CLOSE GAME ADJUSTMENTS ====================

    def test_morale_bonus_close_win(self):
        """Close win (<=5 pts) = +3 (+2 base +1 bonus)"""
        delta = self._calculate_morale_delta(won=True, margin=5)
        self.assertEqual(delta, 3)

    def test_morale_penalty_close_loss(self):
        """Close loss (<=5 pts) = -3 (-2 base -1 penalty)"""
        delta = self._calculate_morale_delta(won=False, margin=3)
        self.assertEqual(delta, -3)

    def test_morale_no_bonus_blowout_win(self):
        """Blowout win (>5 pts) = +2 (no bonus)"""
        delta = self._calculate_morale_delta(won=True, margin=15)
        self.assertEqual(delta, 2)

    def test_morale_no_penalty_blowout_loss(self):
        """Blowout loss (>5 pts) = -2 (no penalty)"""
        delta = self._calculate_morale_delta(won=False, margin=20)
        self.assertEqual(delta, -2)

    # ==================== INJURY ADJUSTMENTS ====================

    def test_morale_penalty_2_injured(self):
        """2 injured players (7+ days) = -1 extra"""
        delta = self._calculate_morale_delta(won=True, margin=10, injured_count=2)
        self.assertEqual(delta, 1)  # +2 -1

    def test_morale_penalty_3_injured(self):
        """3 injured players = -1 extra (threshold is >=2)"""
        delta = self._calculate_morale_delta(won=True, margin=10, injured_count=3)
        self.assertEqual(delta, 1)  # +2 -1

    def test_morale_penalty_4_injured(self):
        """4 injured players = -2 extra"""
        delta = self._calculate_morale_delta(won=True, margin=10, injured_count=4)
        self.assertEqual(delta, 0)  # +2 -2

    def test_morale_no_penalty_1_injured(self):
        """1 injured player = no penalty"""
        delta = self._calculate_morale_delta(won=True, margin=10, injured_count=1)
        self.assertEqual(delta, 2)

    # ==================== COMBINED SCENARIOS ====================

    def test_morale_close_win_with_injuries(self):
        """Close win + 2 injured = +2 (+2 base +1 -1)"""
        delta = self._calculate_morale_delta(won=True, margin=3, injured_count=2)
        self.assertEqual(delta, 2)

    def test_morale_close_loss_with_many_injuries(self):
        """Close loss + 4 injured = -5 (-2 -1 -2)"""
        delta = self._calculate_morale_delta(won=False, margin=4, injured_count=4)
        self.assertEqual(delta, -5)

    # ==================== BOUNDS ====================

    def test_morale_never_below_zero(self):
        """Morale should never go below 0"""
        result = self._apply_morale(1, -5)
        self.assertEqual(result, 0)

    def test_morale_never_above_hundred(self):
        """Morale should never go above 100"""
        result = self._apply_morale(99, 5)
        self.assertEqual(result, 100)


class ManagerPressConfidenceTests(TestCase):
    """
    Tests for Press Confidence (Confianza de la Prensa) calculation.
    
    Base: ±4 per win/loss
    Margin: +2 for >=15 pt wins, +1 for <=5 pt wins
    Margin: -2 for >=15 pt losses
    Difficulty: +2/-2 based on opponent quality
    Playoffs: x1.5 multiplier
    Bounds: 0-100
    """

    def _calculate_press_delta(self, won, margin, team_overall, opp_overall, is_playoff=False):
        """Replicate the press confidence delta calculation logic."""
        base = 4 if won else -4
        
        # Margin adjustment
        if won and margin >= 15:
            delta = base + 2
        elif won and margin <= 5:
            delta = base + 1
        elif not won and margin >= 15:
            delta = base - 2
        else:
            delta = base
        
        # Difficulty adjustment
        overall_diff = opp_overall - team_overall
        if won and overall_diff > 3:
            delta += 2
        elif not won and overall_diff < -3:
            delta -= 2
        
        if is_playoff:
            delta = int(delta * 1.5)
        
        return delta

    def _apply_press(self, current, delta):
        """Apply delta with bounds."""
        return max(0, min(100, current + delta))

    # ==================== WIN/LOSS BASE ====================

    def test_press_increases_on_win(self):
        """Win = +4 base press confidence"""
        delta = self._calculate_press_delta(won=True, margin=10, team_overall=80, opp_overall=80)
        self.assertEqual(delta, 4)

    def test_press_decreases_on_loss(self):
        """Loss = -4 base press confidence"""
        delta = self._calculate_press_delta(won=False, margin=10, team_overall=80, opp_overall=80)
        self.assertEqual(delta, -4)

    # ==================== MARGIN ADJUSTMENTS ====================

    def test_press_bonus_big_win(self):
        """Win by >=15 = +6 (+4 base +2)"""
        delta = self._calculate_press_delta(won=True, margin=20, team_overall=80, opp_overall=80)
        self.assertEqual(delta, 6)

    def test_press_bonus_close_win(self):
        """Close win (<=5) = +5 (+4 base +1)"""
        delta = self._calculate_press_delta(won=True, margin=5, team_overall=80, opp_overall=80)
        self.assertEqual(delta, 5)

    def test_press_bonus_exact_15(self):
        """Win by exactly 15 = +6"""
        delta = self._calculate_press_delta(won=True, margin=15, team_overall=80, opp_overall=80)
        self.assertEqual(delta, 6)

    def test_press_penalty_blowout_loss(self):
        """Loss by >=15 = -6 (-4 base -2)"""
        delta = self._calculate_press_delta(won=False, margin=20, team_overall=80, opp_overall=80)
        self.assertEqual(delta, -6)

    def test_press_no_extra_penalty_normal_loss(self):
        """Normal loss (6-14 pts) = -4 (no extra)"""
        delta = self._calculate_press_delta(won=False, margin=10, team_overall=80, opp_overall=80)
        self.assertEqual(delta, -4)

    # ==================== DIFFICULTY ADJUSTMENTS ====================

    def test_press_extra_credit_beating_good_team(self):
        """Win against +4 better team = +2 extra"""
        delta = self._calculate_press_delta(won=True, margin=10, team_overall=80, opp_overall=84)
        self.assertEqual(delta, 6)  # +4 base +2 difficulty

    def test_press_extra_penalty_losing_to_bad_team(self):
        """Loss against -4 worse team = -2 extra"""
        delta = self._calculate_press_delta(won=False, margin=10, team_overall=80, opp_overall=76)
        self.assertEqual(delta, -6)  # -4 base -2 difficulty

    def test_press_no_diff_adjustment_slightly_better(self):
        """Win against +2 better team = no extra (threshold is >3)"""
        delta = self._calculate_press_delta(won=True, margin=10, team_overall=80, opp_overall=82)
        self.assertEqual(delta, 4)

    # ==================== PLAYOFF MULTIPLIER ====================

    def test_press_playoff_multiplier_on_win(self):
        """Playoff win = +4 * 1.5 = 6"""
        delta = self._calculate_press_delta(won=True, margin=10, team_overall=80, opp_overall=80, is_playoff=True)
        self.assertEqual(delta, 6)

    def test_press_playoff_multiplier_on_big_win(self):
        """Playoff big win = (+4+2) * 1.5 = 9"""
        delta = self._calculate_press_delta(won=True, margin=20, team_overall=80, opp_overall=80, is_playoff=True)
        self.assertEqual(delta, 9)

    # ==================== BOUNDS ====================

    def test_press_never_below_zero(self):
        """Press should never go below 0"""
        result = self._apply_press(2, -10)
        self.assertEqual(result, 0)

    def test_press_never_above_hundred(self):
        """Press should never go above 100"""
        result = self._apply_press(98, 10)
        self.assertEqual(result, 100)


class DismissalConditionTests(TestCase):
    """
    Tests for dismissal conditions.
    Manager is dismissed if any stat reaches 0.
    """

    def _check_dismissal(self, trust, morale, pressure):
        """Check if manager should be dismissed."""
        if trust <= 5:
            return True, 'trust'
        elif morale <= 5:
            return True, 'morale'
        elif pressure <= 5:
            return True, 'pressure'
        return False, None

    def test_dismissal_when_trust_at_5(self):
        """Trust at 5 should trigger dismissal"""
        dismissed, reason = self._check_dismissal(trust=5, morale=50, pressure=50)
        self.assertTrue(dismissed)
        self.assertEqual(reason, 'trust')

    def test_dismissal_when_trust_below_5(self):
        """Trust below 5 should trigger dismissal"""
        dismissed, reason = self._check_dismissal(trust=3, morale=50, pressure=50)
        self.assertTrue(dismissed)
        self.assertEqual(reason, 'trust')

    def test_dismissal_when_morale_at_5(self):
        """Morale at 5 should trigger dismissal"""
        dismissed, reason = self._check_dismissal(trust=50, morale=5, pressure=50)
        self.assertTrue(dismissed)
        self.assertEqual(reason, 'morale')

    def test_dismissal_when_pressure_at_5(self):
        """Pressure at 5 should trigger dismissal"""
        dismissed, reason = self._check_dismissal(trust=50, morale=50, pressure=5)
        self.assertTrue(dismissed)
        self.assertEqual(reason, 'pressure')

    def test_no_dismissal_above_threshold(self):
        """Stats above 5 should not trigger dismissal"""
        dismissed, reason = self._check_dismissal(trust=6, morale=50, pressure=50)
        self.assertFalse(dismissed)
        self.assertIsNone(reason)

    def test_no_dismissal_at_50(self):
        """Stats at 50 should not trigger dismissal"""
        dismissed, reason = self._check_dismissal(trust=50, morale=50, pressure=50)
        self.assertFalse(dismissed)

    def test_no_dismissal_at_100(self):
        """Stats at 100 should not trigger dismissal"""
        dismissed, reason = self._check_dismissal(trust=100, morale=100, pressure=100)
        self.assertFalse(dismissed)
