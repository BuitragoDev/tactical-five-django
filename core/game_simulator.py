import random
from .models import PlayerGameStats, HistoricalRecord, TeamRecord, SeasonGameRecord


def simulate_day(season, game_day):
    """Simulate all games for a given game day. Returns list of result dicts."""
    from .models import Game
    games = Game.objects.filter(season=season, game_day=game_day, is_played=False)
    results = []
    for game in games:
        result = simulate_game(game)
        if result:
            results.append(result)
    return results


def simulate_game(game):
    """Simulate a single game. Returns result dict and saves everything to DB."""
    home = game.home_team
    away = game.away_team

    home_players = list(home.players.filter(injury_days=0).order_by('-overall'))
    away_players = list(away.players.filter(injury_days=0).order_by('-overall'))

    if not home_players or not away_players:
        home_score = random.randint(105, 125)
        away_score = random.randint(100, 120)
        q_scores = _distribute_quarters(home_score, away_score)
        game.home_score = home_score
        game.away_score = away_score
        game.is_played = True
        game.q1_home, game.q1_away = q_scores[0]
        game.q2_home, game.q2_away = q_scores[1]
        game.q3_home, game.q3_away = q_scores[2]
        game.q4_home, game.q4_away = q_scores[3]
        game.save()
        return _build_result(home, away, home_score, away_score, q_scores, [], [])

    home_ps = [_init_ps(p) for p in home_players]
    away_ps = [_init_ps(p) for p in away_players]

    home_r = home.overall
    away_r = away.overall

    pace = 98 + (home_r + away_r - 140) * 0.06 + random.uniform(-2, 2)
    pace = max(92, min(104, pace))

    quarters = []
    home_total = 0
    away_total = 0

    for q in range(4):
        h_pts, a_pts = _sim_quarter(q + 1, home_r, away_r, home_ps, away_ps, pace)
        home_total += h_pts
        away_total += a_pts
        quarters.append((h_pts, a_pts))

    for ps in home_ps:
        ps['minutes'] = round(ps['minutes'])
    for ps in away_ps:
        ps['minutes'] = round(ps['minutes'])

    for ps in home_ps + away_ps:
        ps['rating'] = (ps['points'] + ps['oreb'] + ps['dreb'] + ps['assists'] +
                        ps['steals'] + ps['blocks'] -
                        (ps['fga'] - ps['fgm']) - (ps['fta'] - ps['ftm']) -
                        ps['turnovers'] - ps['pf'])
        
        categories = 0
        if ps['points'] >= 10: categories += 1
        if ps['oreb'] + ps['dreb'] >= 10: categories += 1
        if ps['assists'] >= 10: categories += 1
        if ps['steals'] >= 10: categories += 1
        if ps['blocks'] >= 10: categories += 1
        
        if categories >= 3:
            ps['triple_double'] = 1
            ps['double_double'] = 0
        elif categories >= 2:
            ps['double_double'] = 1
            ps['triple_double'] = 0
        else:
            ps['double_double'] = 0
            ps['triple_double'] = 0

    # Simulate overtime if tied (basketball never ends in a tie)
    ot_periods = []
    ot_count = 0
    while home_total == away_total and ot_count < 5:
        ot_count += 1
        h_ot, a_ot = _sim_overtime(home_r, away_r, home_ps, away_ps)
        home_total += h_ot
        away_total += a_ot
        ot_periods.append((h_ot, a_ot))

    game.home_score = home_total
    game.away_score = away_total
    game.is_played = True
    game.q1_home, game.q1_away = quarters[0]
    game.q2_home, game.q2_away = quarters[1]
    game.q3_home, game.q3_away = quarters[2]
    game.q4_home, game.q4_away = quarters[3]
    game.save()

    if game.game_type == 'regular':
        _save_player_stats(game, home_ps, home)
        _save_player_stats(game, away_ps, away)
    elif game.game_type == 'playoff' and game.series_label == 'playoff-r4-finals':
        _save_finals_stats(game, home_ps, home)
        _save_finals_stats(game, away_ps, away)

    home_injuries = check_injuries(home_ps, game.game_day)
    away_injuries = check_injuries(away_ps, game.game_day)

    result = _build_result(home, away, home_total, away_total, quarters, home_ps, away_ps, ot_periods)
    result['injuries'] = home_injuries + away_injuries

    return result


def _sim_overtime(home_r, away_r, home_ps, away_ps):
    """Simulate a 5-minute overtime period."""
    home_pts = 0
    away_pts = 0

    # Overtime has ~12 possessions per team (half of a quarter)
    total_possessions = 24

    home_mins = [0.0] * len(home_ps)
    away_mins = [0.0] * len(away_ps)

    # Start with top 5 players
    home_on = set(range(min(5, len(home_ps))))
    away_on = set(range(min(5, len(away_ps))))

    home_max = len(home_ps)
    away_max = len(away_ps)

    # Fewer substitutions in OT
    sub_schedule = [2.5]
    sub_idx = 0
    mins_per_poss = 5.0 / total_possessions

    for p_idx in range(total_possessions):
        elapsed = p_idx * mins_per_poss

        if sub_idx < len(sub_schedule) and elapsed >= sub_schedule[sub_idx]:
            home_on, away_on = _do_sub(home_on, away_on, home_max, away_max)
            sub_idx += 1

        for i in home_on:
            home_mins[i] += mins_per_poss
        for i in away_on:
            away_mins[i] += mins_per_poss

        is_home = random.random() < 0.5
        if is_home:
            home_pts += _run_poss(
                [home_ps[i] for i in home_on],
                [away_ps[i] for i in away_on],
                home_r, away_r
            )
        else:
            away_pts += _run_poss(
                [away_ps[i] for i in away_on],
                [home_ps[i] for i in home_on],
                away_r, home_r
            )

    for i in range(len(home_ps)):
        home_ps[i]['minutes'] += home_mins[i]
    for i in range(len(away_ps)):
        away_ps[i]['minutes'] += away_mins[i]

    return home_pts, away_pts


def _build_result(home, away, home_score, away_score, quarters, home_ps, away_ps, ot_periods=None):
    q_list = [
        {'quarter': i + 1, 'home_score': quarters[i][0], 'away_score': quarters[i][1]}
        for i in range(4)
    ]
    if ot_periods:
        for i, (h, a) in enumerate(ot_periods):
            q_list.append({'quarter': f'OT{i+1}', 'home_score': h, 'away_score': a})
    return {
        'home_team': home,
        'away_team': away,
        'home_score': home_score,
        'away_score': away_score,
        'quarters': q_list,
        'home_stats': home_ps,
        'away_stats': away_ps,
        'home_team_stats': _team_stats(home_ps),
        'away_team_stats': _team_stats(away_ps),
    }


def _distribute_quarters(home_total, away_total):
    h = _partition(home_total, 4, 22, 40)
    a = _partition(away_total, 4, 22, 40)
    return list(zip(h, a))


def _partition(total, n, lo, hi):
    result = []
    remaining = total
    for i in range(n - 1):
        low = max(lo, remaining - hi * (n - 1 - i))
        high = min(hi, remaining - lo * (n - 1 - i))
        if low > high:
            low = max(lo, remaining // (n - i))
            high = low + 1
        val = random.randint(low, high)
        result.append(val)
        remaining -= val
    result.append(max(lo, remaining))
    return result


def _save_player_stats(game, player_stats, team):
    PlayerGameStats.objects.filter(game=game, team=team).delete()
    for ps in player_stats:
        PlayerGameStats.objects.create(
            game=game,
            player=ps['player'],
            team=team,
            minutes=ps['minutes'],
            points=ps['points'],
            fgm=ps['fgm'],
            fga=ps['fga'],
            fg3m=ps['fg3m'],
            fg3a=ps['fg3a'],
            ftm=ps['ftm'],
            fta=ps['fta'],
            oreb=ps['oreb'],
            dreb=ps['dreb'],
            rebounds=ps['oreb'] + ps['dreb'],
            assists=ps['assists'],
            steals=ps['steals'],
            blocks=ps['blocks'],
            turnovers=ps['turnovers'],
            pf=ps['pf'],
            rating=ps['rating'],
            double_double=ps.get('double_double', 0),
            triple_double=ps.get('triple_double', 0),
        )
    
    _check_and_update_records(game, player_stats, team)


def _check_and_update_records(game, player_stats, team):
    """Check and update all 3 record types after a game. Optimized with bulk fetch."""
    STAT_FIELDS = ['points', 'rebounds', 'assists', 'steals', 'blocks', 'fgm', 'fg3m', 'ftm', 'turnovers']
    
    existing_hist = {r.stat_type: r for r in HistoricalRecord.objects.all()}
    existing_team = {r.stat_type: r for r in TeamRecord.objects.filter(team=team)}
    existing_season = {r.stat_type: r for r in SeasonGameRecord.objects.filter(team=team, season=game.season)}
    
    hist_to_update = []
    hist_to_create = []
    team_to_update = []
    team_to_create = []
    season_to_update = []
    season_to_create = []
    
    for ps in player_stats:
        player_name = ps['player'].full_name
        game_date = game.game_date
        
        for stat in STAT_FIELDS:
            if stat == 'rebounds':
                value = ps.get('oreb', 0) + ps.get('dreb', 0)
            else:
                value = ps.get(stat, 0)
            
            if value <= 0:
                continue
            
            if value > existing_hist.get(stat, type('obj', (), {'value': 0})()).value:
                existing = existing_hist.get(stat)
                if existing:
                    existing.player_name = player_name
                    existing.value = value
                    existing.game_date = game_date
                    existing.team_abbreviation = team.abbreviation
                    hist_to_update.append(existing)
                else:
                    hist_to_create.append(HistoricalRecord(
                        stat_type=stat,
                        player_name=player_name,
                        value=value,
                        game_date=game_date,
                        team_abbreviation=team.abbreviation,
                    ))
            
            if value > existing_team.get(stat, type('obj', (), {'value': 0})()).value:
                existing = existing_team.get(stat)
                if existing:
                    existing.player_name = player_name
                    existing.value = value
                    existing.game_date = game_date
                    team_to_update.append(existing)
                else:
                    team_to_create.append(TeamRecord(
                        team=team,
                        stat_type=stat,
                        player_name=player_name,
                        value=value,
                        game_date=game_date,
                    ))
            
            if value > existing_season.get(stat, type('obj', (), {'value': 0})()).value:
                existing = existing_season.get(stat)
                if existing:
                    existing.player_name = player_name
                    existing.value = value
                    existing.game_date = game_date
                    season_to_update.append(existing)
                else:
                    season_to_create.append(SeasonGameRecord(
                        team=team,
                        season=game.season,
                        stat_type=stat,
                        player_name=player_name,
                        value=value,
                        game_date=game_date,
                    ))
    
    if hist_to_update:
        HistoricalRecord.objects.bulk_update(hist_to_update, ['player_name', 'value', 'game_date', 'team_abbreviation'])
    if hist_to_create:
        HistoricalRecord.objects.bulk_create(hist_to_create, ignore_conflicts=True)
    
    if team_to_update:
        TeamRecord.objects.bulk_update(team_to_update, ['player_name', 'value', 'game_date'])
    if team_to_create:
        TeamRecord.objects.bulk_create(team_to_create, ignore_conflicts=True)
    
    if season_to_update:
        SeasonGameRecord.objects.bulk_update(season_to_update, ['player_name', 'value', 'game_date'])
    if season_to_create:
        SeasonGameRecord.objects.bulk_create(season_to_create, ignore_conflicts=True)


def _save_finals_stats(game, player_stats, team):
    from .models import FinalsPlayerStats
    FinalsPlayerStats.objects.filter(game=game, team=team).delete()
    for ps in player_stats:
        FinalsPlayerStats.objects.create(
            game=game,
            player=ps['player'],
            team=team,
            minutes=ps['minutes'],
            points=ps['points'],
            fgm=ps['fgm'],
            fga=ps['fga'],
            fg3m=ps['fg3m'],
            fg3a=ps['fg3a'],
            ftm=ps['ftm'],
            fta=ps['fta'],
            oreb=ps['oreb'],
            dreb=ps['dreb'],
            rebounds=ps['oreb'] + ps['dreb'],
            assists=ps['assists'],
            steals=ps['steals'],
            blocks=ps['blocks'],
            turnovers=ps['turnovers'],
            pf=ps['pf'],
            rating=ps['rating'],
            double_double=ps.get('double_double', 0),
            triple_double=ps.get('triple_double', 0),
        )


def _init_ps(player):
    return {
        'player': player,
        'name': player.full_name,
        'position': player.position,
        'overall': player.overall,
        'shooting': player.shooting,
        'three_point': player.three_point,
        'passing': player.passing,
        'rebounding': player.rebounding,
        'defense': player.defense,
        'steals_attr': player.steals,
        'blocks_attr': player.blocks,
        'minutes': 0.0,
        'fgm': 0, 'fga': 0,
        'fg3m': 0, 'fg3a': 0,
        'ftm': 0, 'fta': 0,
        'oreb': 0, 'dreb': 0,
        'assists': 0,
        'steals': 0,
        'blocks': 0,
        'turnovers': 0,
        'pf': 0,
        'points': 0,
        'rating': 0,
    }


def _sim_quarter(q_num, home_r, away_r, home_ps, away_ps, pace):
    home_pts = 0
    away_pts = 0

    team_possessions = int(pace / 4 * random.uniform(0.96, 1.04))
    team_possessions = max(22, min(28, team_possessions))
    total_possessions = team_possessions * 2

    home_mins = [0.0] * len(home_ps)
    away_mins = [0.0] * len(away_ps)

    home_on = set(range(min(5, len(home_ps))))
    away_on = set(range(min(5, len(away_ps))))

    home_max = len(home_ps)
    away_max = len(away_ps)

    sub_schedule = _sub_schedule(q_num)
    sub_idx = 0
    mins_per_poss = 12.0 / total_possessions

    for p_idx in range(total_possessions):
        elapsed = p_idx * mins_per_poss

        if sub_idx < len(sub_schedule) and elapsed >= sub_schedule[sub_idx]:
            home_on, away_on = _do_sub(home_on, away_on, home_max, away_max)
            sub_idx += 1

        for i in home_on:
            home_mins[i] += mins_per_poss
        for i in away_on:
            away_mins[i] += mins_per_poss

        is_home = random.random() < 0.5
        if is_home:
            home_pts += _run_poss(
                [home_ps[i] for i in home_on],
                [away_ps[i] for i in away_on],
                home_r, away_r
            )
        else:
            away_pts += _run_poss(
                [away_ps[i] for i in away_on],
                [home_ps[i] for i in home_on],
                away_r, home_r
            )

    for i in range(len(home_ps)):
        home_ps[i]['minutes'] += home_mins[i]
    for i in range(len(away_ps)):
        away_ps[i]['minutes'] += away_mins[i]

    return home_pts, away_pts


def _sim_overtime(home_r, away_r, home_ps, away_ps):
    """Simulate a 5-minute overtime period."""
    home_pts = 0
    away_pts = 0

    # Overtime has ~12 possessions per team (half of a quarter)
    total_possessions = 24

    home_mins = [0.0] * len(home_ps)
    away_mins = [0.0] * len(away_ps)

    # Start with top 5 players
    home_on = set(range(min(5, len(home_ps))))
    away_on = set(range(min(5, len(away_ps))))

    home_max = len(home_ps)
    away_max = len(away_ps)

    # Fewer substitutions in OT
    sub_schedule = [2.5]
    sub_idx = 0
    mins_per_poss = 5.0 / total_possessions

    for p_idx in range(total_possessions):
        elapsed = p_idx * mins_per_poss

        if sub_idx < len(sub_schedule) and elapsed >= sub_schedule[sub_idx]:
            home_on, away_on = _do_sub(home_on, away_on, home_max, away_max)
            sub_idx += 1

        for i in home_on:
            home_mins[i] += mins_per_poss
        for i in away_on:
            away_mins[i] += mins_per_poss

        is_home = random.random() < 0.5
        if is_home:
            home_pts += _run_poss(
                [home_ps[i] for i in home_on],
                [away_ps[i] for i in away_on],
                home_r, away_r
            )
        else:
            away_pts += _run_poss(
                [away_ps[i] for i in away_on],
                [home_ps[i] for i in home_on],
                away_r, home_r
            )

    for i in range(len(home_ps)):
        home_ps[i]['minutes'] += home_mins[i]
    for i in range(len(away_ps)):
        away_ps[i]['minutes'] += away_mins[i]

    return home_pts, away_pts


def _sub_schedule(q_num):
    if q_num == 1:
        return [4.0, 8.0]
    elif q_num == 2:
        return [2.0, 5.0, 8.0, 10.5]
    elif q_num == 3:
        return [4.0, 8.0]
    else:
        return [2.0, 5.0, 8.0, 10.5]


def _do_sub(home_on, away_on, home_max, away_max):
    return _sub_one(home_on, home_max), _sub_one(away_on, away_max)


def _sub_one(on_court, max_players):
    n = 2 if random.random() < 0.5 else 3
    n = min(n, len(on_court))
    if n == 0:
        return on_court
    out = random.sample(list(on_court), n)
    new = on_court - set(out)
    bench = [i for i in range(max_players) if i not in on_court]
    random.shuffle(bench)
    for i in bench[:n]:
        new.add(i)
    return new


def _run_poss(off, def_c, off_r, def_r):
    """Run one possession. Returns points scored (0-3)."""
    to_pct = 0.07 + (def_r - off_r) * 0.0003
    if random.random() < to_pct:
        _do_to(off, def_c)
        return 0

    shooter = _pick(off)
    if not shooter:
        return 0

    shot = _shot_type(shooter)
    defender = max(def_c, key=lambda p: p['defense']) if def_c else None
    di = (defender['defense'] - 70) * 0.002 if defender else 0

    if shot == '3':
        base_pct = 0.35 + (shooter['three_point'] - 70) * 0.005
        pct = max(0.30, min(0.50, base_pct - di))
        shooter['fg3a'] += 1
        shooter['fga'] += 1
        if random.random() < pct:
            shooter['fg3m'] += 1
            shooter['fgm'] += 1
            shooter['points'] += 3
            _ast(off, shooter)
            return 3
        return _miss_handler(def_c, off, shooter, is_three=True)

    base_pct = 0.52 + (shooter['shooting'] - 70) * 0.005
    pct = max(0.45, min(0.72, base_pct - di * 0.4))
    shooter['fga'] += 1
    if random.random() < pct:
        shooter['fgm'] += 1
        shooter['points'] += 2
        _ast(off, shooter)
        if random.random() < 0.06:
            _foul(def_c)
            shooter['fta'] += 1
            if random.random() < 0.78:
                shooter['ftm'] += 1
                shooter['points'] += 1
                return 3
        return 2

    return _miss_handler(def_c, off, shooter, is_three=False)


def _miss_handler(def_c, off, shooter, is_three):
    """Handle what happens after a missed shot: block, foul or rebound. Returns FT points."""
    # Check for block
    for defender in def_c:
        block_chance = (defender['blocks_attr'] - 50) / 500
        block_chance = max(0, min(0.15, block_chance))
        if random.random() < block_chance:
            defender['blocks'] += 1
            return 0

    foul_chance = 0.18 if is_three else 0.14
    if random.random() < foul_chance:
        _foul(def_c)
        n_shots = 3 if is_three else 2
        if random.random() < 0.10 and not is_three:
            n_shots = 3
        ft_pct = 0.78 + (shooter['overall'] - 70) * 0.002
        made = 0
        for _ in range(n_shots):
            shooter['fta'] += 1
            if random.random() < ft_pct:
                shooter['ftm'] += 1
                shooter['points'] += 1
                made += 1
        return made
    else:
        _reb(def_c, off)
        return 0


def _pick(court):
    """Pick a shooter based on overall rating. Stars (92+) get more opportunities."""
    if not court:
        return None
    w = [p['overall'] ** 1.7 if p['overall'] >= 92 else p['overall'] ** 1.5 for p in court]
    t = sum(w)
    if t == 0:
        return random.choice(court)
    r = random.random() * t
    c = 0
    for p in court:
        weight = p['overall'] ** 1.7 if p['overall'] >= 92 else p['overall'] ** 1.5
        c += weight
        if r <= c:
            return p
    return court[-1]


def _shot_type(shooter):
    """Choose shot type based on position and player's three_point ability."""
    pos = shooter['position']
    r = random.random()
    base_3pt = {
        'PG': 0.36,
        'SG': 0.42,
        'SF': 0.35,
        'PF': 0.30,
        'C': 0.14,
    }.get(pos, 0.30)
    adjusted_3pt = base_3pt + (shooter['three_point'] - 75) * 0.002
    adjusted_3pt = max(0.10, min(0.55, adjusted_3pt))
    return '3' if r < adjusted_3pt else '2'


def _ast(court, scorer):
    """Assist based on passing attribute. Uses passing^5 for extreme differentiation."""
    if random.random() < 0.75:
        others = [p for p in court if p is not scorer]
        if others:
            w = [max(1, p['passing']) ** 5 for p in others]
            t = sum(w)
            if t > 0:
                r = random.random() * t
                c = 0
                for p in others:
                    c += max(1, p['passing']) ** 5
                    if r <= c:
                        p['assists'] += 1
                        return


def _reb(def_c, off_c):
    """Rebound based on rebounding attribute. Uses reb^3 for strong differentiation."""
    dw = sum(p['rebounding'] ** 3 for p in def_c)
    ow = sum(p['rebounding'] ** 2.5 for p in off_c)
    t = dw + ow
    if t == 0:
        return

    if random.random() * t < dw:
        if def_c:
            w = [p['rebounding'] ** 3 for p in def_c]
            s = sum(w)
            if s > 0:
                r = random.random() * s
                c = 0
                for p in def_c:
                    c += p['rebounding'] ** 3
                    if r <= c:
                        p['dreb'] += 1
                        return
    else:
        if off_c:
            w = [p['rebounding'] ** 3 for p in off_c]
            s = sum(w)
            if s > 0:
                r = random.random() * s
                c = 0
                for p in off_c:
                    c += p['rebounding'] ** 3
                    if r <= c:
                        p['oreb'] += 1
                        return


def _do_to(off, def_c):
    """Turnover and steal based on steals attribute."""
    h = [p for p in off if p['position'] in ('PG', 'SG', 'SF')]
    if not h:
        h = off
    if h:
        random.choice(h)['turnovers'] += 1
    if def_c:
        w = [p['steals_attr'] ** 3 for p in def_c]
        t = sum(w)
        if t > 0:
            r = random.random() * t
            c = 0
            for p in def_c:
                c += p['steals_attr'] ** 3
                if r <= c:
                    p['steals'] += 1
                    return
        max(def_c, key=lambda p: p['steals_attr'])['steals'] += 1


def _foul(court):
    b = [p for p in court if p['position'] in ('C', 'PF')]
    if not b:
        b = court
    if b:
        random.choice(b)['pf'] += 1


def _team_stats(ps):
    ts = {
        'fgm': 0, 'fga': 0, 'fg3m': 0, 'fg3a': 0,
        'ftm': 0, 'fta': 0, 'points': 0,
        'oreb': 0, 'dreb': 0, 'reb': 0,
        'assists': 0, 'steals': 0, 'blocks': 0,
        'turnovers': 0, 'pf': 0,
    }
    for p in ps:
        ts['fgm'] += p['fgm']
        ts['fga'] += p['fga']
        ts['fg3m'] += p['fg3m']
        ts['fg3a'] += p['fg3a']
        ts['ftm'] += p['ftm']
        ts['fta'] += p['fta']
        ts['oreb'] += p['oreb']
        ts['dreb'] += p['dreb']
        ts['assists'] += p['assists']
        ts['steals'] += p['steals']
        ts['blocks'] += p['blocks']
        ts['turnovers'] += p['turnovers']
        ts['pf'] += p['pf']
    ts['reb'] = ts['oreb'] + ts['dreb']
    ts['points'] = ts['fg3m'] * 3 + (ts['fgm'] - ts['fg3m']) * 2 + ts['ftm']
    return ts


INJURY_TYPES = [
    {'name': 'Esguince leve', 'min_days': 3, 'max_days': 7, 'weight': 40},
    {'name': 'Distensión muscular', 'min_days': 5, 'max_days': 10, 'weight': 30},
    {'name': 'Esguince moderado', 'min_days': 8, 'max_days': 14, 'weight': 25},
    {'name': 'Contusión ósea', 'min_days': 10, 'max_days': 21, 'weight': 15},
    {'name': 'Fractura por estrés', 'min_days': 21, 'max_days': 35, 'weight': 5},
    {'name': 'Rotura de ligamentos', 'min_days': 28, 'max_days': 42, 'weight': 3},
    {'name': 'Rotura de menisco', 'min_days': 35, 'max_days': 56, 'weight': 2},
]


def check_injuries(players_list, game_day):
    """Check for injuries among players. Returns list of injured players."""
    injured = []
    for ps in players_list:
        player = ps['player']
        if player.injury_days > 0:
            continue
        injury_chance = 0.008
        if random.random() < injury_chance:
            injury = _pick_injury()
            player.injury_type = injury['name']
            player.injury_days = random.randint(injury['min_days'], injury['max_days'])
            player.save()
            injured.append({
                'player': player,
                'type': injury['name'],
                'days': player.injury_days,
            })
    return injured


def _pick_injury():
    """Pick an injury type based on weighted probability."""
    total = sum(i['weight'] for i in INJURY_TYPES)
    r = random.random() * total
    cumulative = 0
    for injury in INJURY_TYPES:
        cumulative += injury['weight']
        if r <= cumulative:
            return injury
    return INJURY_TYPES[0]
