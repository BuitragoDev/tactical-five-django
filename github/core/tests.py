"""
Tests for Django models.
"""
from django.test import TestCase
from django.db import IntegrityError
from core.models import (
    Team, Player, Game, Season, Manager, 
    PlayerGameStats, LeagueSettings, TeamSettings,
    FinanceRecord, Message, SeasonRecord, FinalsPlayerStats,
    HistoricalPlayerStats
)


class TeamModelTests(TestCase):
    """Tests for Team model."""

    def test_team_creation(self):
        """Team can be created with required fields."""
        team = Team.objects.create(
            name="Test Team",
            abbreviation="TST",
            city="Test City",
            conference="East",
            division="Atlantic",
            arena="Test Arena",
            capacity=18000,
            owner="Test Owner",
            attack=80,
            defense=80,
            overall=80
        )
        self.assertEqual(team.name, "Test Team")
        self.assertEqual(team.abbreviation, "TST")
        self.assertEqual(team.conference, "East")

    def test_team_str_representation(self):
        """Team __str__ should return name."""
        team = Team.objects.create(
            name="Lakers",
            abbreviation="LAL",
            city="Los Angeles",
            conference="West",
            division="Pacific",
            arena="Staples Center",
            capacity=19000,
            owner="Jeanie Buss"
        )
        self.assertEqual(str(team), "Lakers")

    def test_team_arena_renovation_default(self):
        """Team should have default renovation values."""
        team = Team.objects.create(
            name="Test Team",
            abbreviation="TST",
            city="Test",
            conference="East",
            division="Atlantic",
            arena="Arena",
            capacity=18000,
            owner="Owner"
        )
        self.assertFalse(team.is_under_renovation)
        self.assertEqual(team.renovation_days_left, 0)

    def test_conference_choices(self):
        """Team conference should be East or West."""
        team_east = Team.objects.create(
            name="East Team", abbreviation="EAT", city="City",
            conference="East", division="Atlantic", arena="Arena",
            capacity=18000, owner="Owner"
        )
        team_west = Team.objects.create(
            name="West Team", abbreviation="WST", city="City",
            conference="West", division="Pacific", arena="Arena",
            capacity=18000, owner="Owner"
        )
        self.assertEqual(team_east.conference, "East")
        self.assertEqual(team_west.conference, "West")


class PlayerModelTests(TestCase):
    """Tests for Player model."""

    def setUp(self):
        """Create a team for player tests."""
        self.team = Team.objects.create(
            name="Test Team",
            abbreviation="TST",
            city="Test",
            conference="East",
            division="Atlantic",
            arena="Arena",
            capacity=18000,
            owner="Owner"
        )

    def test_player_creation(self):
        """Player can be created with required fields."""
        player = Player.objects.create(
            team=self.team,
            first_name="Test",
            last_name="Player",
            position="PG",
            age=25,
            nationality="USA",
            height_cm=190,
            weight_kg=85,
            overall=80,
            potential=90
        )
        self.assertEqual(player.first_name, "Test")
        self.assertEqual(player.last_name, "Player")
        self.assertEqual(player.position, "PG")

    def test_player_full_name(self):
        """Player should have full_name property."""
        player = Player.objects.create(
            first_name="LeBron",
            last_name="James",
            position="SF",
            age=38,
            height_cm=206,
            weight_kg=113,
            overall=88
        )
        self.assertEqual(player.full_name, "LeBron James")

    def test_player_str_representation(self):
        """Player __str__ should include name and position."""
        player = Player.objects.create(
            first_name="Stephen",
            last_name="Curry",
            position="PG",
            age=35,
            height_cm=188,
            weight_kg=84,
            overall=90
        )
        self.assertIn("Stephen", str(player))
        self.assertIn("Curry", str(player))

    def test_player_default_values(self):
        """Player should have sensible defaults."""
        player = Player.objects.create(
            first_name="Test",
            last_name="Player",
            position="PG",
            age=25,
            height_cm=190,
            weight_kg=85
        )
        self.assertEqual(player.overall, 70)
        self.assertEqual(player.potential, 70)
        self.assertEqual(player.injury_days, 0)
        self.assertFalse(player.is_rookie)
        self.assertFalse(player.is_retired)

    def test_player_position_choices(self):
        """Player position should be valid."""
        for position in ['PG', 'SG', 'SF', 'PF', 'C']:
            player = Player.objects.create(
                first_name="Test",
                last_name=f"Player{position}",
                position=position,
                age=25,
                height_cm=190,
                weight_kg=85
            )
            self.assertEqual(player.position, position)


class GameModelTests(TestCase):
    """Tests for Game model."""

    def setUp(self):
        """Create teams and season for game tests."""
        self.home_team = Team.objects.create(
            name="Home Team", abbreviation="HOM", city="Home",
            conference="East", division="Atlantic", arena="Arena",
            capacity=18000, owner="Owner"
        )
        self.away_team = Team.objects.create(
            name="Away Team", abbreviation="AWY", city="Away",
            conference="West", division="Pacific", arena="Arena",
            capacity=18000, owner="Owner"
        )
        self.season = Season.objects.create(
            year_start=2025,
            year_end=2026,
            is_active=True
        )

    def test_game_creation(self):
        """Game can be created with teams."""
        from datetime import date
        game = Game.objects.create(
            home_team=self.home_team,
            away_team=self.away_team,
            season=self.season,
            game_day=1,
            game_date=date(2025, 10, 22)
        )
        self.assertEqual(game.home_team, self.home_team)
        self.assertEqual(game.away_team, self.away_team)
        self.assertFalse(game.is_played)

    def test_game_winner_property(self):
        """Game winner should return correct team when played."""
        from datetime import date
        game = Game.objects.create(
            home_team=self.home_team,
            away_team=self.away_team,
            season=self.season,
            game_day=1,
            game_date=date(2025, 10, 22),
            home_score=110,
            away_score=100,
            is_played=True
        )
        self.assertEqual(game.winner, self.home_team)
        self.assertEqual(game.loser, self.away_team)

    def test_game_winner_property_not_played(self):
        """Game winner should be None when not played."""
        from datetime import date
        game = Game.objects.create(
            home_team=self.home_team,
            away_team=self.away_team,
            season=self.season,
            game_day=1,
            game_date=date(2025, 10, 22)
        )
        self.assertIsNone(game.winner)
        self.assertIsNone(game.loser)

    def test_game_str_representation(self):
        """Game __str__ should include teams and day."""
        from datetime import date
        game = Game.objects.create(
            home_team=self.home_team,
            away_team=self.away_team,
            season=self.season,
            game_day=10,
            game_date=date(2025, 10, 22)
        )
        self.assertIn("Home Team", str(game))
        self.assertIn("Away Team", str(game))
        self.assertIn("10", str(game))


class SeasonModelTests(TestCase):
    """Tests for Season model."""

    def test_season_creation(self):
        """Season can be created with years."""
        season = Season.objects.create(
            year_start=2025,
            year_end=2026
        )
        self.assertEqual(season.year_start, 2025)
        self.assertEqual(season.year_end, 2026)

    def test_get_active_season(self):
        """get_active should return active season."""
        Season.objects.filter(is_active=True).update(is_active=False)
        season = Season.objects.create(
            year_start=2025,
            year_end=2026,
            is_active=True
        )
        active = Season.get_active()
        self.assertEqual(active, season)


class ManagerModelTests(TestCase):
    """Tests for Manager model."""

    def setUp(self):
        """Create a team for manager tests."""
        self.team = Team.objects.create(
            name="Test Team", abbreviation="TST", city="Test",
            conference="East", division="Atlantic", arena="Arena",
            capacity=18000, owner="Owner"
        )

    def test_manager_creation(self):
        """Manager can be created with name and team."""
        manager = Manager.objects.create(
            name="Test Manager",
            team=self.team
        )
        self.assertEqual(manager.name, "Test Manager")
        self.assertEqual(manager.team, self.team)

    def test_manager_default_stats(self):
        """Manager should have default stat values."""
        manager = Manager.objects.create(
            name="Test Manager",
            team=self.team
        )
        self.assertEqual(manager.trust, 50)
        self.assertEqual(manager.morale, 50)
        self.assertEqual(manager.pressure, 50)

    def test_manager_stats_bounds(self):
        """Manager stats should be within bounds."""
        manager = Manager.objects.create(
            name="Test Manager",
            team=self.team,
            trust=50,
            morale=50,
            pressure=50
        )
        # Test that values are stored correctly
        self.assertGreaterEqual(manager.trust, 0)
        self.assertLessEqual(manager.trust, 100)


class LeagueSettingsModelTests(TestCase):
    """Tests for LeagueSettings model."""

    def test_get_active_creates_if_not_exists(self):
        """get_active should create settings if none exist."""
        LeagueSettings.objects.all().delete()
        settings = LeagueSettings.get_active()
        self.assertIsNotNone(settings)
        self.assertTrue(settings.is_active)

    def test_league_settings_defaults(self):
        """LeagueSettings should have default values."""
        LeagueSettings.objects.all().delete()
        settings = LeagueSettings.objects.create(is_active=True)
        self.assertEqual(settings.salary_cap, 155_000_000)
        self.assertEqual(settings.luxury_tax, 189_000_000)


class PlayerGameStatsModelTests(TestCase):
    """Tests for PlayerGameStats model."""

    def setUp(self):
        """Create team, player, season, and game for stats tests."""
        self.team = Team.objects.create(
            name="Test Team", abbreviation="TST", city="Test",
            conference="East", division="Atlantic", arena="Arena",
            capacity=18000, owner="Owner"
        )
        self.player = Player.objects.create(
            team=self.team,
            first_name="Test",
            last_name="Player",
            position="PG",
            age=25,
            height_cm=190,
            weight_kg=85,
            overall=80
        )
        self.season = Season.objects.create(
            year_start=2025,
            year_end=2026,
            is_active=True
        )
        from datetime import date
        self.game = Game.objects.create(
            home_team=self.team,
            away_team=Team.objects.create(
                name="Opp", abbreviation="OPP", city="Opp",
                conference="West", division="Pacific", arena="Arena",
                capacity=18000, owner="Owner"
            ),
            season=self.season,
            game_day=1,
            game_date=date(2025, 10, 22)
        )

    def test_player_game_stats_creation(self):
        """PlayerGameStats can be created."""
        stats = PlayerGameStats.objects.create(
            game=self.game,
            player=self.player,
            team=self.team,
            points=20,
            rebounds=5,
            assists=8,
            steals=2,
            blocks=1,
            minutes=30
        )
        self.assertEqual(stats.points, 20)
        self.assertEqual(stats.player, self.player)

    def test_double_double_default(self):
        """double_double should default to 0."""
        stats = PlayerGameStats.objects.create(
            game=self.game,
            player=self.player,
            team=self.team,
            points=20,
            rebounds=5
        )
        self.assertEqual(stats.double_double, 0)

    def test_triple_double_default(self):
        """triple_double should default to 0."""
        stats = PlayerGameStats.objects.create(
            game=self.game,
            player=self.player,
            team=self.team,
            points=20,
            rebounds=5
        )
        self.assertEqual(stats.triple_double, 0)


class TeamSettingsModelTests(TestCase):
    """Tests for TeamSettings model."""

    def setUp(self):
        self.team = Team.objects.create(
            name="Test Team", abbreviation="TST", city="Test",
            conference="East", division="Atlantic", arena="Arena",
            capacity=18000, owner="Owner"
        )

    def test_team_settings_creation(self):
        """TeamSettings can be created."""
        settings = TeamSettings.objects.create(
            team=self.team,
            ticket_price=100
        )
        self.assertEqual(settings.team, self.team)

    def test_team_settings_get_or_create(self):
        """get_or_create should work."""
        settings, created = TeamSettings.objects.get_or_create(team=self.team)
        self.assertTrue(created)
        
        settings2, created2 = TeamSettings.objects.get_or_create(team=self.team)
        self.assertFalse(created2)
        self.assertEqual(settings.pk, settings2.pk)


class FinanceRecordModelTests(TestCase):
    """Tests for FinanceRecord model."""

    def setUp(self):
        self.team = Team.objects.create(
            name="Test Team", abbreviation="TST", city="Test",
            conference="East", division="Atlantic", arena="Arena",
            capacity=18000, owner="Owner"
        )
        self.season = Season.objects.create(
            year_start=2025,
            year_end=2026,
            is_active=True
        )

    def test_finance_record_creation(self):
        """FinanceRecord can be created."""
        record = FinanceRecord.objects.create(
            team=self.team,
            season=self.season,
            record_type=FinanceRecord.TYPE_TICKET,
            amount=1000000,
            game_day=1
        )
        self.assertEqual(record.amount, 1000000)
        self.assertEqual(record.record_type, FinanceRecord.TYPE_TICKET)


class MessageModelTests(TestCase):
    """Tests for Message model."""

    def setUp(self):
        self.team = Team.objects.create(
            name="Test Team", abbreviation="TST", city="Test",
            conference="East", division="Atlantic", arena="Arena",
            capacity=18000, owner="Owner"
        )
        self.manager = Manager.objects.create(
            name="Test Manager",
            team=self.team
        )

    def test_message_creation(self):
        """Message can be created."""
        message = Message.objects.create(
            manager=self.manager,
            title="Test Message",
            body="This is a test message."
        )
        self.assertEqual(message.title, "Test Message")
        self.assertFalse(message.is_read)
