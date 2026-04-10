import random
from datetime import date, timedelta
from collections import defaultdict
from .models import Team, Game, Season


def _div_pair_games(teams_a, teams_b):
    matchups = []
    n = len(teams_a)
    for i, ta in enumerate(teams_a):
        for j, tb in enumerate(teams_b):
            offset = (j - i) % n
            count = 4 if offset < 3 else 3
            for _ in range(count):
                if random.random() < 0.5:
                    matchups.append((ta.pk, tb.pk))
                else:
                    matchups.append((tb.pk, ta.pk))
    return matchups


def generate_schedule(season):
    teams = list(Team.objects.all())
    team_by_pk = {t.pk: t for t in teams}
    team_pks = [t.pk for t in teams]

    east = sorted([t for t in teams if t.conference == 'East'], key=lambda t: (t.division, t.pk))
    west = sorted([t for t in teams if t.conference == 'West'], key=lambda t: (t.division, t.pk))

    east_divs = {}
    for t in east:
        east_divs.setdefault(t.division, []).append(t)

    west_divs = {}
    for t in west:
        west_divs.setdefault(t.division, []).append(t)

    all_div_groups = [east_divs, west_divs]

    matchups = []

    for div_dict in all_div_groups:
        div_names = sorted(div_dict.keys())
        for i, d1 in enumerate(div_names):
            for j, d2 in enumerate(div_names):
                if i < j:
                    matchups.extend(_div_pair_games(div_dict[d1], div_dict[d2]))

        for d_name, div_teams in div_dict.items():
            for i, t1 in enumerate(div_teams):
                for t2 in div_teams[i + 1:]:
                    for _ in range(4):
                        if random.random() < 0.5:
                            matchups.append((t1.pk, t2.pk))
                        else:
                            matchups.append((t2.pk, t1.pk))

    for t1 in east:
        for t2 in west:
            for _ in range(2):
                if random.random() < 0.5:
                    matchups.append((t1.pk, t2.pk))
                else:
                    matchups.append((t2.pk, t1.pk))

    team_game_count = {}
    for t in teams:
        team_game_count[t.pk] = 0
    for home_pk, away_pk in matchups:
        team_game_count[home_pk] = team_game_count.get(home_pk, 0) + 1
        team_game_count[away_pk] = team_game_count.get(away_pk, 0) + 1

    for pk, count in sorted(team_game_count.items()):
        if count != 82:
            team_name = team_by_pk[pk].name
            raise ValueError(f"{team_name} has {count} games, expected 82")

    season_start = date(season.year_start, 10, 22)
    season_end = date(season.year_end, 4, 15)
    total_days = (season_end - season_start).days + 1
    total_weeks = (total_days + 6) // 7

    random.shuffle(matchups)

    team_day_set = {pk: set() for pk in team_pks}
    day_games_count = defaultdict(int)
    scheduled = []
    scheduled_pairs = set()

    def team_week_count(team_pk, day_idx):
        week = day_idx // 7
        return sum(1 for d in team_day_set[team_pk] if d // 7 == week)

    def has_b2b(team_pk, day_idx):
        return (day_idx - 1 in team_day_set[team_pk] or
                day_idx + 1 in team_day_set[team_pk])

    def find_day(home_pk, away_pk, max_weekly=5):
        best_day = None
        best_score = -1000

        for d in range(total_days):
            if d in team_day_set[home_pk] or d in team_day_set[away_pk]:
                continue

            if day_games_count[d] >= 15:
                continue

            h_week = team_week_count(home_pk, d)
            a_week = team_week_count(away_pk, d)

            if h_week >= max_weekly or a_week >= max_weekly:
                continue

            score = 100

            h_b2b = has_b2b(home_pk, d)
            a_b2b = has_b2b(away_pk, d)
            if h_b2b:
                score -= 50
            if a_b2b:
                score -= 50

            if h_week >= 4 or a_week >= 4:
                score -= 30

            score -= day_games_count[d] * 2

            if score > best_score:
                best_score = score
                best_day = d

        return best_day

    for home_pk, away_pk in matchups:
        day = find_day(home_pk, away_pk)

        if day is not None:
            scheduled.append((day, home_pk, away_pk))
            scheduled_pairs.add((home_pk, away_pk))
            team_day_set[home_pk].add(day)
            team_day_set[away_pk].add(day)
            day_games_count[day] += 1

    unscheduled = [(h, a) for h, a in matchups if (h, a) not in scheduled_pairs]

    for home_pk, away_pk in unscheduled:
        for d in range(total_days):
            if d not in team_day_set[home_pk] and d not in team_day_set[away_pk]:
                scheduled.append((d, home_pk, away_pk))
                scheduled_pairs.add((home_pk, away_pk))
                team_day_set[home_pk].add(d)
                team_day_set[away_pk].add(d)
                day_games_count[d] += 1
                break

    game_dates = [season_start + timedelta(days=d) for d in range(total_days)]

    games_to_create = []
    for day_idx, home_pk, away_pk in scheduled:
        game_date = game_dates[day_idx]
        games_to_create.append(
            Game(
                season=season,
                game_day=day_idx + 1,
                game_date=game_date,
                home_team_id=home_pk,
                away_team_id=away_pk,
                is_played=False,
            )
        )

    Game.objects.bulk_create(games_to_create)

    season.generated = True
    season.save()

    return len(games_to_create)


def _get_standings_for_conference(season, conf):
    """Build standings for a conference from played regular season games."""
    conf_teams = list(Team.objects.filter(conference=conf))
    team_ids = {t.pk for t in conf_teams}
    team_data = {}
    for t in conf_teams:
        team_data[t.pk] = {
            'team_id': t.pk,
            'team': t,
            'wins': 0,
            'losses': 0,
        }

    played_games = Game.objects.filter(season=season, is_played=True, game_type='regular').order_by('game_day', 'pk')
    for g in played_games:
        if g.home_team_id in team_ids:
            if g.home_score > g.away_score:
                team_data[g.home_team_id]['wins'] += 1
            else:
                team_data[g.home_team_id]['losses'] += 1
        if g.away_team_id in team_ids:
            if g.away_score > g.home_score:
                team_data[g.away_team_id]['wins'] += 1
            else:
                team_data[g.away_team_id]['losses'] += 1

    rows = list(team_data.values())
    for s in rows:
        total = s['wins'] + s['losses']
        s['pct'] = s['wins'] / total if total > 0 else 0.0

    rows.sort(key=lambda x: (-x['pct'], x['losses'], -x['wins']))
    for i, s in enumerate(rows, 1):
        s['rank'] = i
    return rows


def generate_playin(season):
    """Generate play-in tournament games after regular season ends.

    7 days gap after last regular season game.
    Format per conference:
    - Game 1: Seed 7 vs Seed 8 (home: seed 7)
    - Game 2: Seed 9 vs Seed 10 (home: seed 9)
    - Game 3 (eliminator): Loser(7v8) vs Winner(9v10) — created dynamically
    """
    last_regular_day = Game.objects.filter(season=season, game_type='regular').order_by('-game_day').values_list('game_day', flat=True).first()
    if not last_regular_day:
        return 0

    playin_start_day = last_regular_day + 7

    # Don't regenerate if play-in games already exist
    existing = Game.objects.filter(season=season, game_type='playin').exists()
    if existing:
        return 0

    last_regular_game = Game.objects.filter(season=season, game_type='regular').order_by('-game_date').first()
    playin_date = last_regular_game.game_date + timedelta(days=7) if last_regular_game else date(season.year_end, 4, 22)

    games_to_create = []

    for conf in ['East', 'West']:
        standings = _get_standings_for_conference(season, conf)
        if len(standings) < 10:
            continue

        seed7 = standings[6]['team']
        seed8 = standings[7]['team']
        seed9 = standings[8]['team']
        seed10 = standings[9]['team']

        games_to_create.append(Game(
            season=season,
            game_day=playin_start_day,
            game_date=playin_date,
            home_team=seed7,
            away_team=seed8,
            is_played=False,
            game_type='playin',
            series_label=f'playin-7-8-{conf.lower()}',
        ))

        games_to_create.append(Game(
            season=season,
            game_day=playin_start_day,
            game_date=playin_date,
            home_team=seed9,
            away_team=seed10,
            is_played=False,
            game_type='playin',
            series_label=f'playin-9-10-{conf.lower()}',
        ))

    created = Game.objects.bulk_create(games_to_create)
    return len(created)


def create_playin_eliminator(season, conf):
    """Create the eliminator game (loser 7v8 vs winner 9v10) for a conference."""
    game_7v8 = Game.objects.filter(season=season, game_type='playin', series_label=f'playin-7-8-{conf}').first()
    game_9v10 = Game.objects.filter(season=season, game_type='playin', series_label=f'playin-9-10-{conf}').first()

    if not game_7v8 or not game_9v10:
        return None
    if not game_7v8.is_played or not game_9v10.is_played:
        return None

    eliminator_exists = Game.objects.filter(season=season, game_type='playin', series_label=f'playin-elim-{conf}').exists()
    if eliminator_exists:
        return None

    loser_7v8 = game_7v8.loser
    winner_9v10 = game_9v10.winner

    if not loser_7v8 or not winner_9v10:
        return None

    eliminator_date = game_7v8.game_date + timedelta(days=2)
    eliminator_day = game_7v8.game_day + 2

    # Use get_or_create to avoid UNIQUE constraint issues with deleted games
    game, created = Game.objects.get_or_create(
        season=season,
        home_team=loser_7v8,
        away_team=winner_9v10,
        game_day=eliminator_day,
        defaults={
            'game_date': eliminator_date,
            'is_played': False,
            'game_type': 'playin',
            'series_label': f'playin-elim-{conf}',
        },
    )
    return game


def _get_playoff_seeds(season):
    """Get the final 8 playoff seeds per conference after play-in."""
    seeds = {}
    for conf in ['East', 'West']:
        standings = _get_standings_for_conference(season, conf)
        top6 = [standings[i]['team'] for i in range(6)]

        game_7v8 = Game.objects.filter(season=season, game_type='playin', series_label=f'playin-7-8-{conf.lower()}').first()
        game_elim = Game.objects.filter(season=season, game_type='playin', series_label=f'playin-elim-{conf.lower()}').first()

        seed7 = game_7v8.winner if game_7v8 and game_7v8.is_played else None
        seed8 = game_elim.winner if game_elim and game_elim.is_played else None

        playoff_teams = top6 + [seed7, seed8]
        seeds[conf] = playoff_teams
    return seeds


def _create_playoff_series_games(season, home_team, away_team, series_label, start_day, start_date):
    """Create up to 7 games for a playoff series (2-2-1-1-1 format).
    Each game is 2 days apart in both game_day and game_date."""
    games = []
    home_games_in_series = [0, 1, 4, 6]

    for game_num in range(7):
        if game_num in home_games_in_series:
            home, away = home_team, away_team
        else:
            home, away = away_team, home_team

        game_day = start_day + game_num * 2
        game_date = start_date + timedelta(days=game_num * 2)

        exists = Game.objects.filter(
            season=season,
            home_team=home,
            away_team=away,
            game_day=game_day,
        ).exists()
        if not exists:
            games.append(Game(
                season=season,
                game_day=game_day,
                game_date=game_date,
                home_team=home,
                away_team=away,
                is_played=False,
                game_type='playoff',
                series_label=series_label,
            ))

    if games:
        return Game.objects.bulk_create(games, ignore_conflicts=True)
    return []


def generate_playoffs(season):
    """Generate the full playoff bracket after play-in ends.

    4 days gap after last play-in game.
    Round 1: All 4 East Game 1s on day N, all 4 West Game 1s on day N+1,
             all 4 East Game 2s on day N+2, all 4 West Game 2s on day N+3, etc.
    Teams play every 2 days.
    Next round starts 4 days after the last possible game 7 of the previous round.
    """
    existing = Game.objects.filter(season=season, game_type='playoff').exists()
    if existing:
        return 0

    seeds = _get_playoff_seeds(season)

    last_playin_game = Game.objects.filter(season=season, game_type='playin').order_by('-game_day').first()
    if not last_playin_game:
        last_regular = Game.objects.filter(season=season, game_type='regular').order_by('-game_day').first()
        base_day = (last_regular.game_day if last_regular else 0) + 11
        base_date = date(season.year_end, 4, 26)
    else:
        base_day = last_playin_game.game_day + 4
        base_date = last_playin_game.game_date + timedelta(days=4)

    all_games = []

    for conf in ['East', 'West']:
        conf_seeds = seeds[conf]
        if len(conf_seeds) < 8 or any(t is None for t in conf_seeds):
            continue

        s1, s2, s3, s4, s5, s6, s7, s8 = conf_seeds

        series_defs = [
            (s1, s8, f'playoff-r1-{conf.lower()}-1v8'),
            (s4, s5, f'playoff-r1-{conf.lower()}-4v5'),
            (s2, s7, f'playoff-r1-{conf.lower()}-2v7'),
            (s3, s6, f'playoff-r1-{conf.lower()}-3v6'),
        ]

        # East starts on base_day, West starts on base_day + 1
        conf_offset = 0 if conf == 'East' else 1
        conf_start_date = base_date + timedelta(days=conf_offset)

        for home, away, label in series_defs:
            games = _create_playoff_series_games(season, home, away, label, base_day + conf_offset, conf_start_date)
            all_games.extend(games)

    Game.objects.bulk_create(all_games, ignore_conflicts=True)
    return len(all_games)


def advance_all_playoff_series(season):
    """Check all playoff series for completed ones and advance winners."""
    all_series = Game.objects.filter(
        season=season, game_type='playoff'
    ).exclude(series_label='').values_list('series_label', flat=True).distinct()

    for series_label in all_series:
        series_games = list(Game.objects.filter(season=season, series_label=series_label).order_by('game_day'))
        played = [g for g in series_games if g.is_played]

        if not played:
            continue

        team_a = played[0].home_team
        team_b = played[0].away_team
        team_a_wins = 0
        team_b_wins = 0
        for g in played:
            if g.home_score > g.away_score:
                if g.home_team_id == team_a.pk:
                    team_a_wins += 1
                else:
                    team_b_wins += 1
            else:
                if g.away_team_id == team_a.pk:
                    team_a_wins += 1
                else:
                    team_b_wins += 1

        if team_a_wins < 4 and team_b_wins < 4:
            continue

        # Series is complete - delete remaining unplayed games
        Game.objects.filter(season=season, series_label=series_label, is_played=False).delete()

        if team_a_wins >= 4:
            winner = team_a
        else:
            winner = team_b

        _advance_winner_to_next_round(season, series_label, winner)

    # After processing all series, check if we need to create next round
    _check_and_create_next_round(season)


def _check_and_create_next_round(season):
    """Check if a round is fully complete and create the next round."""
    r1_labels = [
        'playoff-r1-east-1v8', 'playoff-r1-east-4v5', 'playoff-r1-east-2v7', 'playoff-r1-east-3v6',
        'playoff-r1-west-1v8', 'playoff-r1-west-4v5', 'playoff-r1-west-2v7', 'playoff-r1-west-3v6',
    ]
    r1_done = all(_get_series_winner(season, label) is not None for label in r1_labels)
    if r1_done:
        r2_exists = Game.objects.filter(season=season, series_label__startswith='playoff-r2-').exists()
        if not r2_exists:
            _create_round2_series(season)

    # Check per-conference for conference finals
    for conf in ['East', 'West']:
        conf_lower = conf.lower()
        r2_done = all(
            _get_series_winner(season, f'playoff-r2-{conf_lower}-s{i}') is not None
            for i in [1, 2]
        )
        if r2_done:
            r3_exists = Game.objects.filter(season=season, series_label=f'playoff-r3-{conf_lower}-s1').exists()
            if not r3_exists:
                _create_conference_final(season, conf)

    # Check if both conference finals are done to create NBA Finals
    r3_labels = ['playoff-r3-east-s1', 'playoff-r3-west-s1']
    r3_done = all(_get_series_winner(season, label) is not None for label in r3_labels)
    if r3_done:
        r4_exists = Game.objects.filter(season=season, series_label='playoff-r4-finals').exists()
        if not r4_exists:
            _create_finals_series(season)


def _create_round2_series(season):
    """Create all 4 semifinal series (2 per conference) with proper scheduling."""
    last_played = Game.objects.filter(season=season, game_type='playoff', is_played=True).order_by('-game_day').first()
    base_day = (last_played.game_day if last_played else 0) + 4
    last_date = Game.objects.filter(season=season, game_type='playoff', is_played=True).order_by('-game_date').first()
    base_date = (last_date.game_date if last_date else date(season.year_end, 6, 1)) + timedelta(days=4)

    for conf in ['East', 'West']:
        conf_lower = conf.lower()
        conf_offset = 0 if conf == 'East' else 1

        s1_label = f'playoff-r2-{conf_lower}-s1'
        s2_label = f'playoff-r2-{conf_lower}-s2'

        w1 = _get_series_winner(season, f'playoff-r1-{conf_lower}-1v8')
        w2 = _get_series_winner(season, f'playoff-r1-{conf_lower}-4v5')
        w3 = _get_series_winner(season, f'playoff-r1-{conf_lower}-2v7')
        w4 = _get_series_winner(season, f'playoff-r1-{conf_lower}-3v6')

        if w1 and w2:
            home, away = (w1, w2) if w1.pk < w2.pk else (w2, w1)
            _create_playoff_series_games(season, home, away, s1_label, base_day + conf_offset, base_date + timedelta(days=conf_offset))
        if w3 and w4:
            home, away = (w3, w4) if w3.pk < w4.pk else (w4, w3)
            _create_playoff_series_games(season, home, away, s2_label, base_day + conf_offset, base_date + timedelta(days=conf_offset))


def _create_conference_final(season, conf):
    """Create conference final series for a single conference."""
    conf_lower = conf.lower()
    label = f'playoff-r3-{conf_lower}-s1'

    w1 = _get_series_winner(season, f'playoff-r2-{conf_lower}-s1')
    w2 = _get_series_winner(season, f'playoff-r2-{conf_lower}-s2')
    if not w1 or not w2:
        return

    home, away = (w1, w2) if w1.pk < w2.pk else (w2, w1)

    last_played = Game.objects.filter(season=season, game_type='playoff', is_played=True).order_by('-game_day').first()
    base_day = (last_played.game_day if last_played else 0) + 4
    last_date = Game.objects.filter(season=season, game_type='playoff', is_played=True).order_by('-game_date').first()
    base_date = (last_date.game_date if last_date else date(season.year_end, 6, 1)) + timedelta(days=4)

    _create_playoff_series_games(season, home, away, label, base_day, base_date)


def _create_finals_series(season):
    """Create NBA Finals series."""
    last_played = Game.objects.filter(season=season, game_type='playoff', is_played=True).order_by('-game_day').first()
    base_day = (last_played.game_day if last_played else 0) + 4
    last_date = Game.objects.filter(season=season, game_type='playoff', is_played=True).order_by('-game_date').first()
    base_date = (last_date.game_date if last_date else date(season.year_end, 6, 1)) + timedelta(days=4)

    east_winner = _get_series_winner(season, 'playoff-r3-east-s1')
    west_winner = _get_series_winner(season, 'playoff-r3-west-s1')

    if east_winner and west_winner:
        home, away = (east_winner, west_winner) if east_winner.pk < west_winner.pk else (west_winner, east_winner)
        _create_playoff_series_games(season, home, away, 'playoff-r4-finals', base_day, base_date)


def _advance_winner_to_next_round(season, series_label, winner):
    pass


def _get_series_winner(season, series_label):
    games = list(Game.objects.filter(season=season, series_label=series_label, is_played=True).order_by('game_day'))
    if not games:
        return None

    team_a = games[0].home_team
    team_b = games[0].away_team
    team_a_wins = 0
    team_b_wins = 0
    for g in games:
        if g.home_score > g.away_score:
            if g.home_team_id == team_a.pk:
                team_a_wins += 1
            else:
                team_b_wins += 1
        else:
            if g.away_team_id == team_a.pk:
                team_a_wins += 1
            else:
                team_b_wins += 1

    if team_a_wins >= 4:
        return team_a
    elif team_b_wins >= 4:
        return team_b
    return None
