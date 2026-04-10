from django.shortcuts import render, redirect
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models import Q, Sum, Count, Avg
from django.http import JsonResponse
from datetime import date, timedelta
import json
import random
from .models import Team, Manager, Player, Season, Game, Message, PlayerGameStats, LeagueSettings, TeamSettings, FinanceRecord, GameAttendance, SeasonRecord, FinalsPlayerStats, HistoricalRecord, TeamRecord, SeasonGameRecord, Sponsor, TvChannel
from .schedule_generator import generate_schedule
from .game_simulator import simulate_game, simulate_day, check_injuries


INJURY_TYPES = [
    {'name': 'Esguince leve', 'min_days': 3, 'max_days': 7, 'weight': 40},
    {'name': 'Esguince moderado', 'min_days': 8, 'max_days': 14, 'weight': 25},
    {'name': 'Distensión muscular', 'min_days': 5, 'max_days': 10, 'weight': 30},
    {'name': 'Contusión ósea', 'min_days': 10, 'max_days': 21, 'weight': 15},
    {'name': 'Rotura de ligamentos', 'min_days': 28, 'max_days': 42, 'weight': 5},
    {'name': 'Fractura por estrés', 'min_days': 21, 'max_days': 35, 'weight': 3},
    {'name': 'Rotura de menisco', 'min_days': 35, 'max_days': 56, 'weight': 2},
]


def _update_injuries():
    """Decrease injury days for all injured players."""
    injured = Player.objects.filter(injury_days__gt=0)
    for p in injured:
        p.injury_days -= 1
        if p.injury_days <= 0:
            p.injury_days = 0
            p.injury_type = ''
        p.save()


def _process_renovations(season):
    """Check and complete any finished renovations. Called every day advance."""
    from datetime import date
    for t in Team.objects.filter(arena_renovation_end_day__gt=0):
        if season.current_game_day >= t.arena_renovation_end_day:
            t.apply_renovation(t.arena_renovation_type)
            info = t.get_renovation_info(t.arena_renovation_type)
            # Create finance record for renovation cost
            if t.arena_renovation_cost > 0:
                FinanceRecord.objects.create(
                    team=t,
                    season=season,
                    record_type=FinanceRecord.TYPE_RENOVATION,
                    game_day=season.current_game_day,
                    amount=t.arena_renovation_cost,
                )
            t.budget -= t.arena_renovation_cost
            mgr = Manager.objects.filter(team=t).first()
            if mgr:
                Message.objects.create(
                    manager=mgr,
                    title=f'Remodelación completada: {info["name"]}',
                    body=f'La remodelación "{info["name"]}" ha finalizado. Se han añadido {info["capacity_bonus"]} asientos. Coste total: ${t.arena_renovation_cost:,}.',
                    game_date=date.today(),
                )
            t.arena_renovation_end_day = 0
            t.arena_renovation_type = ''
            t.arena_renovation_cost = 0
            t.save()


def _select_random_contracts():
    """Select 3 random sponsors and 3 random TV channels for the new season."""
    Sponsor.objects.update(is_active=False)
    TvChannel.objects.update(is_active=False)
    
    all_sponsors = list(Sponsor.objects.all())
    all_tv_channels = list(TvChannel.objects.all())
    
    if len(all_sponsors) >= 3:
        selected_sponsors = random.sample(all_sponsors, 3)
        for s in selected_sponsors:
            s.is_active = True
            s.save()
    
    if len(all_tv_channels) >= 3:
        selected_tv = random.sample(all_tv_channels, 3)
        for t in selected_tv:
            t.is_active = True
            t.save()


def _process_subscription_revenue(team, season):
    """Process subscription revenue on November 1st (game day ~11).
    Only processes for the given team, with randomness based on early season performance."""
    # Check around game day 10-12 (Nov 1 is roughly day 11)
    if not (10 <= season.current_game_day <= 12):
        return
    
    fin_settings, _ = TeamSettings.objects.get_or_create(team=team)
    
    # Check if already recorded for this season
    if FinanceRecord.objects.filter(
        team=team,
        season=season,
        record_type=FinanceRecord.TYPE_SUBSCRIPTION
    ).exists():
        return
    
    # Calculate early season performance (first 3-4 games)
    early_games = Game.objects.filter(
        season=season,
        is_played=True,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day')[:4]
    
    wins = 0
    for g in early_games:
        is_home = g.home_team_id == team.pk
        team_score = g.home_score if is_home else g.away_score
        opp_score = g.away_score if is_home else g.home_score
        if team_score > opp_score:
            wins += 1
    
    # Performance multiplier: +5% per win, baseline 1.0
    performance_mult = 1.0 + (wins * 0.05)
    
    # Randomness factor: 0.85 to 1.15
    random_factor = 0.85 + random.random() * 0.30
    
    # Calculate subscribers
    base_ratio = 0.5
    price_factor = (2000 - fin_settings.subscription_price) / 10000
    num_subscribers = int(team.capacity * (base_ratio + price_factor) * performance_mult * random_factor)
    num_subscribers = max(0, min(team.capacity, num_subscribers))
    sub_amount = num_subscribers * fin_settings.subscription_price
    
    if sub_amount > 0:
        season_start = date(season.year_start, 10, 22)
        game_date = season_start + timedelta(days=season.current_game_day - 1)
        
        FinanceRecord.objects.create(
            team=team,
            season=season,
            record_type=FinanceRecord.TYPE_SUBSCRIPTION,
            game_day=season.current_game_day,
            amount=sub_amount,
        )
        
        mgr = Manager.objects.filter(team=team).first()
        if mgr:
            Message.objects.create(
                manager=mgr,
                title=f'Ingresos por abonos',
                body=f'Se han vendido {num_subscribers:,} abonos esta temporada obteniendo un ingreso total de ${sub_amount:,}.',
                game_day=season.current_game_day,
                game_date=game_date,
            )


def home(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    if team_id and manager_name:
        manager = Manager.objects.filter(name=manager_name).first()
        if manager:
            season = Season.get_active()
            if season and season.generated:
                return redirect('dashboard')
    return render(request, 'core/home.html')


def choose_team(request):
    mode = request.GET.get('mode', 'manager')
    
    if request.method == 'POST':
        team_id      = request.POST.get('team_id')
        manager_name = request.POST.get('manager_name', '').strip()
        if team_id and manager_name:
            request.session['team_id']      = int(team_id)
            request.session['manager_name'] = manager_name
            request.session['game_mode']    = mode

            season = Season.get_active()
            if not season:
                now = timezone.now()
                if now.month >= 10:
                    ys = now.year
                else:
                    ys = now.year - 1
                season = Season.objects.create(
                    year_start=ys,
                    year_end=ys + 1,
                    is_active=True,
                    current_game_day=0,
                    game_mode=mode,
                )
                generate_schedule(season)
            elif not Game.objects.filter(season=season).exists():
                generate_schedule(season)
            elif not season.game_mode:
                season.game_mode = mode
                season.save()

            from datetime import date
            start_date = date(season.year_start, 10, 22)
            manager = Manager.objects.create(
                name=manager_name,
                team_id=int(team_id),
                game_mode=mode,
                current_date=start_date,
            )

            team_obj = Team.objects.get(pk=int(team_id))
            TeamSettings.objects.get_or_create(team=team_obj)
            Message.objects.create(
                manager=manager,
                title=f'Bienvenido a los {team_obj.name}',
                body=f'Hola {manager_name}, bienvenido como nuevo entrenador de los {team_obj.name}. La directiva confía en ti para llevar al equipo lo más alto posible. ¡Buena suerte en esta temporada!',
                game_date=start_date,
            )

            return redirect('dashboard')

    teams = Team.objects.all().order_by('overall')

    east = teams.filter(conference='East')
    west = teams.filter(conference='West')

    if mode == 'promanager':
        teams_list = list(teams)
        worst_5 = teams_list[:5]
        for t in teams_list:
            t.selectable = t in worst_5
    else:
        teams_list = list(teams)
        for t in teams_list:
            t.selectable = True

    # Pre-calculate payroll and cap margin for each team
    from django.db.models import Sum
    for t in teams_list:
        payroll_result = t.players.aggregate(total=Sum('salary'))
        t.team_payroll = payroll_result['total'] or 0
        from .models import LeagueSettings
        cap = LeagueSettings.get_active().salary_cap
        t.team_cap_margin = cap - t.team_payroll

    teams = teams_list

    selected_id = request.POST.get('team_id') or request.GET.get('team_id')
    selected_team = None
    if selected_id:
        try:
            selected_team = Team.objects.get(pk=selected_id)
        except Team.DoesNotExist:
            pass

    title = 'LIGA' 
    subtitle = 'PROMANAGER' if mode == 'promanager' else 'MANAGER'
    
    context = {
        'teams':         teams,
        'east':          east,
        'west':          west,
        'selected_team': selected_team,
        'game_mode':     mode,
        'page_title':    title,
        'page_subtitle': subtitle,
    }
    return render(request, 'core/choose_team.html', context)


def simulate_game(game):
    home = game.home_team
    away = game.away_team

    home_adv = 3
    diff = (home.overall - away.overall) / 10.0
    home_expected = 105 + diff + home_adv + random.gauss(0, 8)
    away_expected = 105 - diff + random.gauss(0, 8)

    game.home_score = max(70, int(round(home_expected)))
    game.away_score = max(70, int(round(away_expected)))
    game.is_played = True
    game.save()


def build_standings_from_games(season, conf):
    conf_teams = list(Team.objects.filter(conference=conf))
    team_ids = {t.pk for t in conf_teams}
    team_data = {}
    for t in conf_teams:
        team_data[t.pk] = {
            'team_id': t.pk,
            'team': t,
            'logo': t.logo,
            'name': t.name,
            'wins': 0,
            'losses': 0,
            'games': [],
        }

    played_games = Game.objects.filter(season=season, is_played=True, game_type='regular').order_by('game_day', 'pk')
    for g in played_games:
        if g.home_team_id in team_ids:
            if g.home_score > g.away_score:
                team_data[g.home_team_id]['wins'] += 1
                team_data[g.home_team_id]['games'].append('W')
            else:
                team_data[g.home_team_id]['losses'] += 1
                team_data[g.home_team_id]['games'].append('L')
        if g.away_team_id in team_ids:
            if g.away_score > g.home_score:
                team_data[g.away_team_id]['wins'] += 1
                team_data[g.away_team_id]['games'].append('W')
            else:
                team_data[g.away_team_id]['losses'] += 1
                team_data[g.away_team_id]['games'].append('L')

    rows = list(team_data.values())
    for s in rows:
        total = s['wins'] + s['losses']
        s['pct'] = s['wins'] / total if total > 0 else 0.0
        s['games_played'] = total
        streak = _calc_streak(s['games'])
        s['streak'] = streak

    rows.sort(key=lambda x: (-x['pct'], x['losses'], -x['wins']))
    for i, s in enumerate(rows, 1):
        s['rank'] = i
        if i <= 6:
            s['zone'] = 'playoff'
        elif i <= 10:
            s['zone'] = 'playin'
        else:
            s['zone'] = 'out'
    return rows


def _calc_streak(games):
    if not games:
        return {'text': '-', 'type': 'none'}

    last = games[-1]
    count = 0
    for g in reversed(games):
        if g == last:
            count += 1
        else:
            break

    if last == 'W':
        return {'text': f'{count}V', 'type': 'win'}
    else:
        return {'text': f'{count}D', 'type': 'loss'}


def dashboard(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    manager = Manager.objects.filter(name=manager_name).first()

    season = Season.get_active()
    if not season:
        return redirect('home')

    players = team.players.filter(is_retired=False).order_by('-overall')

    played_games = Game.objects.filter(season=season, is_played=True)

    team_played = played_games.filter(home_team=team) | played_games.filter(away_team=team)

    last_game = team_played.order_by('-game_day', '-pk').first()
    last_result = None
    if last_game:
        last_result = {
            'home_team_name': last_game.home_team.name,
            'home_team_logo': last_game.home_team.logo,
            'home_score': last_game.home_score,
            'away_team_name': last_game.away_team.name,
            'away_team_logo': last_game.away_team.logo,
            'away_score': last_game.away_score,
            'date': last_game.game_date.strftime('%d/%m/%Y'),
        }

    upcoming = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(home_team=team).order_by('game_day', 'pk') | Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(away_team=team).order_by('game_day', 'pk')

    next_game_obj = upcoming.first()
    next_game = None
    if next_game_obj:
        next_game = {
            'home_team_name': next_game_obj.home_team.name,
            'home_team_logo': next_game_obj.home_team.logo,
            'away_team_name': next_game_obj.away_team.name,
            'away_team_logo': next_game_obj.away_team.logo,
            'date': next_game_obj.game_date.strftime('%d/%m/%Y'),
        }

    games_played_count = team_played.count()

    from .models import PlayerGameStats
    player_stats = PlayerGameStats.objects.filter(
        game__season=season,
        team=team,
        game__is_played=True,
    )

    top_scorer = None
    top_rebounder = None
    top_assister = None
    top_rated = None

    if player_stats.exists():
        from django.db.models import Sum, Avg, Count

        scorer = player_stats.values('player__first_name', 'player__last_name', 'player__position').annotate(
            total_pts=Sum('points'),
            games=Count('game')
        ).order_by('-total_pts').first()

        if scorer:
            top_scorer = {
                'value': round(scorer['total_pts'] / scorer['games'], 1) if scorer['games'] > 0 else scorer['total_pts'],
                'name': f"{scorer['player__first_name']} {scorer['player__last_name']}",
                'games': scorer['games'],
            }

        rebounder = player_stats.values('player__first_name', 'player__last_name', 'player__position').annotate(
            total_reb=Sum('rebounds'),
            games=Count('game')
        ).order_by('-total_reb').first()

        if rebounder:
            top_rebounder = {
                'value': round(rebounder['total_reb'] / rebounder['games'], 1) if rebounder['games'] > 0 else rebounder['total_reb'],
                'name': f"{rebounder['player__first_name']} {rebounder['player__last_name']}",
                'games': rebounder['games'],
            }

        assister = player_stats.values('player__first_name', 'player__last_name', 'player__position').annotate(
            total_ast=Sum('assists'),
            games=Count('game')
        ).order_by('-total_ast').first()

        if assister:
            top_assister = {
                'value': round(assister['total_ast'] / assister['games'], 1) if assister['games'] > 0 else assister['total_ast'],
                'name': f"{assister['player__first_name']} {assister['player__last_name']}",
                'games': assister['games'],
            }

        best_rated = player_stats.values(
            'player__first_name', 'player__last_name', 'player__position', 'player__overall'
        ).annotate(
            avg_rating=Avg('rating'),
            games=Count('game')
        ).order_by('-avg_rating').first()

        if best_rated:
            top_rated = {
                'value': round(best_rated['avg_rating'], 1),
                'name': f"{best_rated['player__first_name']} {best_rated['player__last_name']}",
                'games': best_rated['games'],
            }
    else:
        top_scorer = {'value': 0, 'name': '-', 'games': 0}
        top_rebounder = {'value': 0, 'name': '-', 'games': 0}
        top_assister = {'value': 0, 'name': '-', 'games': 0}
        top_rated = {'value': 0, 'name': '-', 'games': 0}

    standings_east = build_standings_from_games(season, 'East')
    standings_west = build_standings_from_games(season, 'West')

    for s_list in [standings_east, standings_west]:
        for s in s_list:
            s.pop('team', None)

    current_date = None
    if manager and manager.current_date:
        current_date = manager.current_date
    elif season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            from datetime import date
            current_date = date(season.year_start, 10, 22)
    else:
        from datetime import date
        current_date = date(season.year_start, 10, 22)

    total_games = Game.objects.filter(season=season).count()
    played_total = played_games.count()
    season_progress = (played_total / total_games * 100) if total_games > 0 else 0

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    if manager:
        board_trust = manager.trust
        board_morale = manager.morale
        board_pressure = manager.pressure
    else:
        board_trust = 50
        board_morale = 50
        board_pressure = 50

    context = {
        'manager_name': manager_name,
        'team': team,
        'players': players,
        'top_scorer': top_scorer,
        'top_rebounder': top_rebounder,
        'top_assister': top_assister,
        'top_rated': top_rated,
        'last_result': last_result,
        'next_game': next_game,
        'standings_east_json': json.dumps(standings_east),
        'standings_west_json': json.dumps(standings_west),
        'default_conf': team.conference,
        'games_played': games_played_count,
        'board_trust': board_trust,
        'board_morale': board_morale,
        'board_pressure': board_pressure,
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'season_label': f"{season.year_start}-{season.year_end}",
        'season_progress': round(season_progress, 1),
        'current_game_day': season.current_game_day,
        'total_game_days': Game.objects.filter(season=season).values('game_day').distinct().count(),
        'btn_text': btn_text,
        'season_phase': season.phase,
    }
    return render(request, 'core/dashboard.html', context)


def match_day(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    my_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first()

    if not my_game:
        return redirect('dashboard')

    game_day = my_game.game_day

    _update_injuries()

    all_results = simulate_day(season, game_day)

    # Process monthly payroll if on the 1st of the month
    _process_monthly_payroll(team, season, my_game.game_date)

    result = None
    for r in all_results:
        if r['home_team'].pk == team.pk or r['away_team'].pk == team.pk:
            result = r
            break

    if not result:
        my_game.refresh_from_db()
        result = {
            'home_team': my_game.home_team,
            'away_team': my_game.away_team,
            'home_score': my_game.home_score or 0,
            'away_score': my_game.away_score or 0,
            'quarters': [
                {'quarter': 1, 'home_score': my_game.q1_home or 0, 'away_score': my_game.q1_away or 0},
                {'quarter': 2, 'home_score': my_game.q2_home or 0, 'away_score': my_game.q2_away or 0},
                {'quarter': 3, 'home_score': my_game.q3_home or 0, 'away_score': my_game.q3_away or 0},
                {'quarter': 4, 'home_score': my_game.q4_home or 0, 'away_score': my_game.q4_away or 0},
            ],
            'home_stats': [],
            'away_stats': [],
            'home_team_stats': {},
            'away_team_stats': {},
        }

    mvp = None
    if result and result.get('home_stats') and result.get('away_stats'):
        all_players = result['home_stats'] + result['away_stats']
        mvp = max(all_players, key=lambda p: p.get('rating', 0))

    injuries = result.get('injuries', []) if result else []

    from datetime import date
    current_date = my_game.game_date

    manager = Manager.objects.filter(name=manager_name).first()
    if manager:
        my_game.refresh_from_db()
        manager.current_date = my_game.game_date + timedelta(days=1)
        _update_manager_stats(manager, season, game_day)
        manager.save()
        _create_game_result_message(manager, team, my_game)

    season.current_game_day = game_day
    season.save()

    if injuries and manager:
        for inj in injuries:
            if inj['player'].team_id == team.pk:
                Message.objects.create(
                    manager=manager,
                    title=f'Lesión: {inj["player"].full_name}',
                    body=f'{inj["player"].full_name} ha sufrido {inj["type"]}. Estará de baja {inj["days"]} días.',
                    game_date=my_game.game_date,
                )

    # Calculate attendance and ticket revenue if team plays at home
    attendance = None
    ticket_revenue = 0
    if my_game.home_team_id == team.pk:
        fin_settings, _ = TeamSettings.objects.get_or_create(team=team)
        
        # Calculate win percentage
        team_games = Game.objects.filter(
            season=season,
            is_played=True,
        ).filter(
            Q(home_team=team) | Q(away_team=team)
        )
        total_games = team_games.count()
        wins = 0
        for g in team_games:
            is_home = g.home_team_id == team.pk
            team_score = g.home_score if is_home else g.away_score
            opp_score = g.away_score if is_home else g.home_score
            if team_score > opp_score:
                wins += 1
        
        win_pct = wins / total_games if total_games > 0 else 0.5
        
        # Attendance based on win percentage and capacity
        base_attendance = team.capacity * (0.55 + win_pct * 0.40)
        random_factor = 0.92 + random.random() * 0.16
        attendance = int(min(team.capacity, base_attendance * random_factor))
        
        # Calculate revenue
        ticket_revenue = attendance * fin_settings.ticket_price
        
        # Add to budget
        team.budget += ticket_revenue
        team.save()
        
        # Create finance record
        FinanceRecord.objects.create(
            team=team,
            season=season,
            record_type=FinanceRecord.TYPE_TICKET,
            game_day=game_day,
            amount=ticket_revenue,
        )
        
        # Sponsor home game income
        if fin_settings.sponsor and fin_settings.sponsor_years_remaining > 0:
            sponsor_income = fin_settings.sponsor.home_game_income
            team.budget += sponsor_income
            team.save()
            FinanceRecord.objects.create(
                team=team,
                season=season,
                record_type=FinanceRecord.TYPE_SPONSORSHIP,
                game_day=game_day,
                amount=sponsor_income,
            )
        
        # TV home game income
        if fin_settings.tv_channel and fin_settings.tv_years_remaining > 0:
            tv_income = fin_settings.tv_channel.home_game_income
            team.budget += tv_income
            team.save()
            FinanceRecord.objects.create(
                team=team,
                season=season,
                record_type=FinanceRecord.TYPE_TV,
                game_day=game_day,
                amount=tv_income,
            )

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y'),
        'game_day': game_day,
        'result': result,
        'mvp': mvp,
        'attendance': attendance,
        'ticket_revenue': ticket_revenue,
        'injuries': injuries,
        'season_phase': season.phase,
    }
    return render(request, 'core/match_day.html', context)


def game_results(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    game_day = season.current_game_day
    day_games = Game.objects.filter(season=season, game_day=game_day, is_played=True)

    results = []
    all_player_stats = []
    for g in day_games:
        home_stats = list(g.player_stats.filter(team=g.home_team).order_by('-rating'))
        away_stats = list(g.player_stats.filter(team=g.away_team).order_by('-rating'))
        
        home_team_stats = {
            'fgm': sum(s.fgm for s in home_stats),
            'fga': sum(s.fga for s in home_stats),
            'fg3m': sum(s.fg3m for s in home_stats),
            'fg3a': sum(s.fg3a for s in home_stats),
            'ftm': sum(s.ftm for s in home_stats),
            'fta': sum(s.fta for s in home_stats),
            'oreb': sum(s.oreb for s in home_stats),
            'dreb': sum(s.dreb for s in home_stats),
            'reb': sum(s.rebounds for s in home_stats),
            'assists': sum(s.assists for s in home_stats),
            'steals': sum(s.steals for s in home_stats),
            'blocks': sum(s.blocks for s in home_stats),
            'turnovers': sum(s.turnovers for s in home_stats),
            'pf': sum(s.pf for s in home_stats),
            'points': g.home_score,
        }
        away_team_stats = {
            'fgm': sum(s.fgm for s in away_stats),
            'fga': sum(s.fga for s in away_stats),
            'fg3m': sum(s.fg3m for s in away_stats),
            'fg3a': sum(s.fg3a for s in away_stats),
            'ftm': sum(s.ftm for s in away_stats),
            'fta': sum(s.fta for s in away_stats),
            'oreb': sum(s.oreb for s in away_stats),
            'dreb': sum(s.dreb for s in away_stats),
            'reb': sum(s.rebounds for s in away_stats),
            'assists': sum(s.assists for s in away_stats),
            'steals': sum(s.steals for s in away_stats),
            'blocks': sum(s.blocks for s in away_stats),
            'turnovers': sum(s.turnovers for s in away_stats),
            'pf': sum(s.pf for s in away_stats),
            'points': g.away_score,
        }
        
        results.append({
            'game': g,
            'home_stats': home_stats,
            'away_stats': away_stats,
            'home_team_stats': home_team_stats,
            'away_team_stats': away_team_stats,
        })
        all_player_stats.extend(home_stats)
        all_player_stats.extend(away_stats)

    mvp = max(all_player_stats, key=lambda p: p.rating) if all_player_stats else None

    top_scorers = sorted(all_player_stats, key=lambda p: p.points, reverse=True)[:3]
    top_rebounders = sorted(all_player_stats, key=lambda p: p.rebounds, reverse=True)[:3]
    top_assisters = sorted(all_player_stats, key=lambda p: p.assists, reverse=True)[:3]

    from datetime import date
    current_date = date(season.year_start, 10, 22)
    if day_games.exists():
        current_date = day_games.first().game_date

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y'),
        'game_day': game_day,
        'results': results,
        'mvp': mvp,
        'top_scorers': top_scorers,
        'top_rebounders': top_rebounders,
        'top_assisters': top_assisters,
        'season_phase': season.phase,
    }
    return render(request, 'core/game_results.html', context)


def roster(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    players = list(team.players.filter(is_retired=False).order_by('-overall'))
    player_count = len(players)
    for p in players:
        p.height_m = round(p.height_cm / 100, 2)

    # Get player season stats
    from django.db.models import Sum, Avg, Count
    player_game_stats = PlayerGameStats.objects.filter(
        team=team,
        game__season=season,
        game__is_played=True,
    ).values('player_id').annotate(
        games=Count('game'),
        total_points=Sum('points'),
        total_rebounds=Sum('rebounds'),
        total_assists=Sum('assists'),
        avg_pts=Avg('points'),
        avg_reb=Avg('rebounds'),
        avg_ast=Avg('assists'),
    )
    
    stats_map = {s['player_id']: s for s in player_game_stats}
    for p in players:
        ps = stats_map.get(p.pk, {})
        p.season_games = ps.get('games', 0)
        p.season_pts = round(ps.get('avg_pts', 0), 1) if ps.get('avg_pts') else 0
        p.season_reb = round(ps.get('avg_reb', 0), 1) if ps.get('avg_reb') else 0
        p.season_ast = round(ps.get('avg_ast', 0), 1) if ps.get('avg_ast') else 0

    # Group by position
    positions = ['PG', 'SG', 'SF', 'PF', 'C']
    pos_labels = {'PG': 'Base', 'SG': 'Escolta', 'SF': 'Alero', 'PF': 'Ala-Pivot', 'C': 'Pivot'}
    roster_by_pos = {}
    for pos in positions:
        roster_by_pos[pos] = [p for p in players if p.position == pos]

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    current_date = None
    if manager := Manager.objects.filter(name=manager_name).first():
        current_date = manager.current_date
    elif season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            current_date = date(season.year_start, 10, 22)
    else:
        current_date = date(season.year_start, 10, 22)

    contract_result = request.session.pop('contract_result', None)
    trade_success = request.session.pop('trade_success', None)
    trade_rejected = request.session.pop('trade_rejected', None)

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'positions': positions,
        'pos_labels': pos_labels,
        'roster_by_pos': roster_by_pos,
        'player_count': player_count,
        'contract_result': contract_result,
        'trade_success': trade_success,
        'trade_rejected': trade_rejected,
        'season_phase': season.phase,
    }
    return render(request, 'core/roster.html', context)


def player_stats(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    stat_type = request.GET.get('stat', 'points')
    time_filter = request.GET.get('time', 'season')
    display_mode = request.GET.get('mode', 'totals')
    valid_stats = ['points', 'rebounds', 'assists', 'steals', 'blocks', 'fg_pct', 'fg3_pct', 'ft_pct', 'rating', 'turnovers', 'minutes', 'double_double', 'triple_double']
    if stat_type not in valid_stats:
        stat_type = 'points'

    # Season stats
    season_stats = PlayerGameStats.objects.filter(
        game__season=season,
        game__is_played=True,
    ).values(
        'player', 'player__first_name', 'player__last_name', 'player__position',
        'player__overall', 'player__team', 'player__team__name', 'player__team__abbreviation',
        'player__team__logo',
    ).annotate(
        games=Count('id'),
        total_points=Sum('points'),
        total_rebounds=Sum('rebounds'),
        total_assists=Sum('assists'),
        total_steals=Sum('steals'),
        total_blocks=Sum('blocks'),
        total_turnovers=Sum('turnovers'),
        total_fgm=Sum('fgm'),
        total_fga=Sum('fga'),
        total_fg3m=Sum('fg3m'),
        total_fg3a=Sum('fg3a'),
        total_ftm=Sum('ftm'),
        total_fta=Sum('fta'),
        total_oreb=Sum('oreb'),
        total_dreb=Sum('dreb'),
        total_minutes=Sum('minutes'),
        total_rating=Sum('rating'),
        total_double_double=Sum('double_double'),
        total_triple_double=Sum('triple_double'),
    ).order_by()

    if time_filter == 'historical':
        # Get historical stats
        from .models import HistoricalPlayerStats
        hist_stats = HistoricalPlayerStats.objects.all().values(
            'first_name', 'last_name', 'position', 'overall',
            'team_name', 'team_abbreviation', 'team_logo',
            'games', 'total_points', 'total_rebounds', 'total_assists',
            'total_steals', 'total_blocks', 'total_turnovers',
            'total_fgm', 'total_fga', 'total_fg3m', 'total_fg3a',
            'total_ftm', 'total_fta', 'total_double_doubles', 'total_triple_doubles',
        )

        # Build a dict of historical stats keyed by (first_name, last_name)
        hist_dict = {}
        for h in hist_stats:
            key = (h['first_name'].lower(), h['last_name'].lower())
            hist_dict[key] = h

        # Merge: for active players, add season stats to historical
        all_stats = []
        merged_players = set()

        for s in season_stats:
            key = (s['player__first_name'].lower(), s['player__last_name'].lower())
            s['name'] = f"{s['player__first_name']} {s['player__last_name']}"
            s['player__team__name'] = s['player__team__name']
            s['player__team__abbreviation'] = s['player__team__abbreviation']
            s['player__team__logo'] = s['player__team__logo']

            if key in hist_dict:
                h = hist_dict[key]
                s['games'] += h['games']
                s['total_points'] += h['total_points']
                s['total_rebounds'] += h['total_rebounds']
                s['total_assists'] += h['total_assists']
                s['total_steals'] += h['total_steals']
                s['total_blocks'] += h['total_blocks']
                s['total_fgm'] += h['total_fgm']
                s['total_fga'] += h['total_fga']
                s['total_fg3m'] += h['total_fg3m']
                s['total_fg3a'] += h['total_fg3a']
                s['total_ftm'] += h['total_ftm']
                s['total_fta'] += h['total_fta']
                s['total_oreb'] += h.get('total_oreb', 0)
                s['total_dreb'] += h.get('total_dreb', 0)
                s['total_minutes'] += h['games'] * 36
                s['total_rating'] += h.get('total_rating', 0)
                s['total_double_double'] = s.get('total_double_double', 0) + h.get('total_double_doubles', 0)
                s['total_triple_double'] = s.get('total_triple_double', 0) + h.get('total_triple_doubles', 0)
                # Use historical team info if no current team
                if not s['player__team__logo']:
                    s['player__team__name'] = h['team_name']
                    s['player__team__abbreviation'] = h['team_abbreviation']
                    s['player__team__logo'] = h['team_logo']
                merged_players.add(key)

            all_stats.append(s)

        # Add historical-only players not in current season
        for key, h in hist_dict.items():
            if key not in merged_players:
                all_stats.append({
                    'player': None,
                    'player__first_name': h['first_name'],
                    'player__last_name': h['last_name'],
                    'player__position': h['position'],
                    'player__overall': h['overall'],
                    'player__team': None,
                    'player__team__name': h['team_name'],
                    'player__team__abbreviation': h['team_abbreviation'],
                    'player__team__logo': h['team_logo'],
                    'games': h['games'],
                    'total_points': h['total_points'],
                    'total_rebounds': h['total_rebounds'],
                    'total_assists': h['total_assists'],
                    'total_steals': h['total_steals'],
                    'total_blocks': h['total_blocks'],
                    'total_turnovers': h.get('total_turnovers', 0),
                    'total_fgm': h['total_fgm'],
                    'total_fga': h['total_fga'],
                    'total_fg3m': h['total_fg3m'],
                    'total_fg3a': h['total_fg3a'],
                    'total_ftm': h['total_ftm'],
                    'total_fta': h['total_fta'],
                    'total_oreb': h.get('total_oreb', 0),
                    'total_dreb': h.get('total_dreb', 0),
                    'total_minutes': h['games'] * 36,
                    'total_rating': h.get('total_rating', 0),
                    'total_double_double': h.get('total_double_doubles', 0),
                    'total_triple_double': h.get('total_triple_doubles', 0),
                    'name': f"{h['first_name']} {h['last_name']}",
                })
    else:
        # Season only
        all_stats = list(season_stats)
        for s in all_stats:
            s['name'] = f"{s['player__first_name']} {s['player__last_name']}"

    # Calculate averages and percentages
    for s in all_stats:
        g = s['games']
        s['ppg'] = round(s['total_points'] / g, 1) if g > 0 else 0
        s['rpg'] = round(s['total_rebounds'] / g, 1) if g > 0 else 0
        s['apg'] = round(s['total_assists'] / g, 1) if g > 0 else 0
        s['spg'] = round(s['total_steals'] / g, 1) if g > 0 else 0
        s['bpg'] = round(s['total_blocks'] / g, 1) if g > 0 else 0
        s['topg'] = round(s['total_turnovers'] / g, 1) if g > 0 else 0
        s['mpg'] = round(s['total_minutes'] / g, 1) if g > 0 else 0
        s['fg_pct'] = round(s['total_fgm'] / s['total_fga'] * 100, 1) if s['total_fga'] > 0 else 0
        s['fg3_pct'] = round(s['total_fg3m'] / s['total_fg3a'] * 100, 1) if s['total_fg3a'] > 0 else 0
        s['ft_pct'] = round(s['total_ftm'] / s['total_fta'] * 100, 1) if s['total_fta'] > 0 else 0
        s['rpg_avg'] = round(s['total_rating'] / g, 1) if g > 0 else 0

    # Sort by selected stat
    sort_map = {
        'points': 'ppg', 'rebounds': 'rpg', 'assists': 'apg',
        'steals': 'spg', 'blocks': 'bpg', 'fg_pct': 'fg_pct',
        'fg3_pct': 'fg3_pct', 'ft_pct': 'ft_pct', 'rating': 'rpg_avg',
        'turnovers': 'topg', 'minutes': 'mpg',
        'double_double': 'total_double_double', 'triple_double': 'total_triple_double',
    }
    sort_key = sort_map[stat_type]
    if display_mode == 'totals' and stat_type not in ('fg_pct', 'fg3_pct', 'ft_pct'):
        sort_key = {
            'points': 'total_points', 'rebounds': 'total_rebounds', 'assists': 'total_assists',
            'steals': 'total_steals', 'blocks': 'total_blocks', 'rating': 'total_rating',
            'turnovers': 'total_turnovers', 'minutes': 'total_minutes',
            'double_double': 'total_double_double', 'triple_double': 'total_triple_double',
        }.get(stat_type, sort_key)
    all_stats = sorted(all_stats, key=lambda x: x.get(sort_key, 0), reverse=True)
    all_stats = all_stats[:100]

    # League leaders
    stat_labels = {
        'points': 'Puntos', 'rebounds': 'Rebotes', 'assists': 'Asistencias',
        'steals': 'Robos', 'blocks': 'Tapones', 'fg_pct': '% TC',
        'fg3_pct': '% 3P', 'ft_pct': '% TL', 'rating': 'Valoración',
        'turnovers': 'Pérdidas', 'minutes': 'Minutos',
        'double_double': 'Dobles-Dobles', 'triple_double': 'Triples-Dobles',
    }
    mode_labels = {'totals': 'Totales', 'averages': 'Promedios'}

    # Get next/prev day info for header
    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season, is_played=False,
    ).filter(Q(home_team=team) | Q(away_team=team)).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    current_date = None
    if manager := Manager.objects.filter(name=manager_name).first():
        current_date = manager.current_date
    elif season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            current_date = date(season.year_start, 10, 22)
    else:
        current_date = date(season.year_start, 10, 22)

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'stat_type': stat_type,
        'time_filter': time_filter,
        'display_mode': display_mode,
        'stat_labels': stat_labels,
        'mode_labels': mode_labels,
        'all_stats': all_stats,
        'season_phase': season.phase,
    }
    return render(request, 'core/player_stats.html', context)


def arena(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    renovations = []
    for key in team.RENOVATION_TYPES:
        info = team.get_renovation_info(key)
        cost = team.get_renovation_cost(key)
        duration_weeks = team.get_renovation_info(key)['duration_weeks']
        capacity_bonus = team.get_renovation_capacity_bonus(key)
        renovations.append({
            'type': key,
            'name': info['name'],
            'icon': info['icon'],
            'desc': info['desc'],
            'cost': cost,
            'duration_weeks': duration_weeks,
            'capacity_bonus': capacity_bonus,
            'can_afford': team.budget >= cost,
        })

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season, is_played=False,
    ).filter(Q(home_team=team) | Q(away_team=team)).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    current_date = None
    if manager := Manager.objects.filter(name=manager_name).first():
        current_date = manager.current_date
    elif season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            current_date = date(season.year_start, 10, 22)
    else:
        current_date = date(season.year_start, 10, 22)

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'renovations': renovations,
        'season_phase': season.phase,
    }
    return render(request, 'core/arena.html', context)


@require_POST
def arena_renovate(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    renovation_type = request.POST.get('type', '')
    valid_types = list(Team.RENOVATION_TYPES.keys())
    if renovation_type not in valid_types:
        return redirect('arena')

    if team.is_under_renovation:
        return redirect('arena')

    cost = team.get_renovation_cost(renovation_type)
    if team.budget < cost:
        return redirect('arena')

    info = team.get_renovation_info(renovation_type)
    duration_days = info['duration_weeks'] * 7

    # Store renovation info based on game day, DON'T deduct cost yet
    team.arena_renovation_end_day = season.current_game_day + duration_days
    team.arena_renovation_type = renovation_type
    team.arena_renovation_cost = cost
    team.save()

    Message.objects.create(
        manager=Manager.objects.filter(name=manager_name).first(),
        title=f'Remodelación del pabellón iniciada',
        body=f'Ha comenzado la remodelación: {info["name"]}. Coste: ${cost:,}. Duración: {info["duration_weeks"]} semanas. El coste se descontará al finalizar.',
        game_date=date.today(),
    )

    return redirect('arena')


def trade(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    other_teams = Team.objects.exclude(pk=team_id).order_by('name')
    selected_team_id = request.GET.get('team')
    selected_team = None
    my_players = team.players.filter(is_retired=False).order_by('-overall')
    other_players = []
    fa_players = []

    salary_cap = LeagueSettings.get_active().salary_cap
    my_payroll = team.players.aggregate(total=Sum('salary'))['total'] or 0
    my_salary_margin = salary_cap - my_payroll
    other_payroll = 0
    other_salary_margin = 0

    if selected_team_id == 'fa':
        selected_team = 'fa'
    elif selected_team_id:
        try:
            selected_team = Team.objects.get(pk=selected_team_id)
            other_players = list(selected_team.players.filter(is_retired=False).order_by('-overall'))
            other_payroll = selected_team.players.aggregate(total=Sum('salary'))['total'] or 0
            other_salary_margin = salary_cap - other_payroll
        except Team.DoesNotExist:
            selected_team = None

    is_fa = selected_team == 'fa'

    fa_players = list(Player.objects.filter(team__isnull=True, is_retired=False).order_by('-overall'))

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season, is_played=False,
    ).filter(Q(home_team=team) | Q(away_team=team)).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    current_date = None
    if manager := Manager.objects.filter(name=manager_name).first():
        current_date = manager.current_date
    elif season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            current_date = date(season.year_start, 10, 22)
    else:
        current_date = date(season.year_start, 10, 22)

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'other_teams': other_teams,
        'selected_team': selected_team,
        'my_players': my_players,
        'other_players': other_players,
        'fa_players': fa_players,
        'is_fa': is_fa,
        'my_salary_margin': my_salary_margin,
        'other_salary_margin': other_salary_margin,
        'my_payroll': my_payroll,
        'other_payroll': other_payroll,
        'salary_cap': salary_cap,
        'roster_count': team.players.count(),
        'season_phase': season.phase,
    }
    return render(request, 'core/trade.html', context)


def trade_check(request):
    """AJAX endpoint to check if a trade offer is valid and likely to be accepted."""
    team_id = request.session.get('team_id')
    if not team_id:
        return JsonResponse({'status': 'error', 'errors': ['No autenticado']})

    try:
        my_team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return JsonResponse({'status': 'error', 'errors': ['Equipo no encontrado']})

    other_team_id = request.GET.get('team')
    try:
        other_team = Team.objects.get(pk=other_team_id)
    except (Team.DoesNotExist, ValueError):
        return JsonResponse({'status': 'error', 'errors': ['Equipo no válido']})

    my_player_ids = request.GET.getlist('my_player_ids', [])
    other_player_ids = request.GET.getlist('other_player_ids', [])

    my_players = list(Player.objects.filter(id__in=my_player_ids, team=my_team))
    other_players = list(Player.objects.filter(id__in=other_player_ids, team=other_team))

    if not my_players and not other_players:
        return JsonResponse({'status': 'empty'})

    my_salary_out = sum(p.salary for p in my_players)
    other_salary_out = sum(p.salary for p in other_players)

    salary_cap = 155_000_000
    first_apron = 195_900_000
    second_apron = 207_800_000

    from django.db.models import Sum
    other_current_payroll = other_team.players.aggregate(total=Sum('salary'))['total'] or 0
    other_payroll_after = other_current_payroll - other_salary_out + my_salary_out

    errors = []

    # Min 10, max 15 players
    my_after = my_team.players.count() - len(my_players) + len(other_players)
    other_after = other_team.players.count() - len(other_players) + len(my_players)
    if my_after < 10:
        errors.append(f'Tu equipo tendría solo {my_after} jugadores (mínimo 10)')
    if my_after > 15:
        errors.append(f'Tu equipo tendría {my_after} jugadores (máximo 15)')
    if other_after < 10:
        errors.append(f'{other_team.name} tendría solo {other_after} jugadores (mínimo 10)')
    if other_after > 15:
        errors.append(f'{other_team.name} tendría {other_after} jugadores (máximo 15)')

    # Salary matching
    if other_payroll_after > second_apron:
        if len(my_players) > 1:
            errors.append(f'{other_team.name} está en el segundo apron. No pueden agregar salarios.')
        if other_salary_out < my_salary_out:
            errors.append(f'{other_team.name} está en el segundo apron. Solo pueden recibir salario igual o menor.')
    elif other_payroll_after > first_apron:
        max_receive = other_salary_out * 1.10
        if my_salary_out > max_receive + 250_000:
            errors.append(f'{other_team.name} está en el primer apron. Solo pueden recibir hasta el 110% del salario enviado.')
    else:
        if other_salary_out < 7_500_000:
            max_receive = other_salary_out * 2.0 + 250_000
        elif other_salary_out < 29_000_000:
            max_receive = other_salary_out + 7_500_000
        else:
            max_receive = other_salary_out * 1.25 + 250_000
        if my_salary_out > max_receive + 250_000:
            errors.append(f'{other_team.name} no puede recibir más de ${max_receive/1_000_000:.1f}M.')

    if errors:
        return JsonResponse({'status': 'invalid', 'errors': errors})

    # Check if AI would accept
    accept_score = 0
    other_best_ovr = max((p.overall for p in other_players), default=0)
    my_best_ovr = max((p.overall for p in my_players), default=0)
    other_avg_ovr = (sum(p.overall for p in other_players) / len(other_players)) if other_players else 0
    my_avg_ovr = (sum(p.overall for p in my_players) / len(my_players)) if my_players else 0
    my_total_ovr = sum(p.overall for p in my_players)
    other_total_ovr = sum(p.overall for p in other_players)

    if other_best_ovr >= 90:
        if my_best_ovr >= 90:
            accept_score += 40 + (my_best_ovr - other_best_ovr) * 3
        elif my_best_ovr >= 85:
            accept_score += 15 + (my_best_ovr - other_best_ovr) * 2
        else:
            accept_score -= 50
    elif other_best_ovr >= 85:
        if my_best_ovr >= 85:
            accept_score += 30 + (my_best_ovr - other_best_ovr) * 2
        elif my_best_ovr >= 80:
            accept_score += 10
        else:
            accept_score -= 30
    elif other_best_ovr >= 80:
        if my_best_ovr >= 80:
            accept_score += 20
        elif my_best_ovr >= 75:
            accept_score += 5
        else:
            accept_score -= 15
    else:
        if my_avg_ovr >= other_avg_ovr:
            accept_score += 10
        else:
            accept_score -= 10

    accept_score += min(20, max(-20, my_total_ovr - other_total_ovr))

    if other_current_payroll > second_apron:
        if my_salary_out > other_salary_out:
            accept_score += 30
        else:
            accept_score -= 20
    elif other_current_payroll > first_apron:
        if my_salary_out > other_salary_out:
            accept_score += 20
        else:
            accept_score -= 10
    elif other_current_payroll > 189_000_000:
        if my_salary_out > other_salary_out:
            accept_score += 15
        elif my_salary_out < other_salary_out:
            accept_score -= 5
    else:
        if my_salary_out > other_salary_out:
            accept_score += 5
        elif my_salary_out < other_salary_out:
            accept_score -= 5

    if other_after <= 12:
        accept_score += 15
    elif other_after <= 14:
        accept_score += 5

    if my_players and other_players:
        my_avg_age = sum(p.age for p in my_players) / len(my_players)
        other_avg_age = sum(p.age for p in other_players) / len(other_players)
        if my_avg_age < other_avg_age - 3:
            accept_score += 10
        elif my_avg_age > other_avg_age + 3:
            accept_score -= 5

    accept_score = max(0, min(100, accept_score))

    threshold = 50
    if other_current_payroll > second_apron:
        threshold = 40
    elif other_current_payroll > first_apron:
        threshold = 45

    would_accept = accept_score >= threshold

    return JsonResponse({
        'status': 'valid',
        'would_accept': would_accept,
        'accept_score': accept_score,
        'threshold': threshold,
    })


@require_POST
def fa_offer(request):
    """Sign a free agent player."""
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    player_id = request.POST.get('player_id')
    try:
        player = Player.objects.get(pk=player_id, team__isnull=True)
    except Player.DoesNotExist:
        return redirect('/trade/?team=fa')

    # Check roster limit (max 15)
    if team.players.count() >= 15:
        return redirect('/trade/?team=fa')

    # Calculate contract: salary = last_salary + 2M, years based on age
    new_salary = player.salary + 2_000_000
    if player.age > 35:
        years = 1
    elif player.age > 32:
        years = 2
    elif player.age > 28:
        years = 3
    elif player.age > 25:
        years = 4
    else:
        years = 5

    # Sign the player
    player.team = team
    player.salary = new_salary
    player.contract_years = years
    player.save()

    manager = Manager.objects.filter(name=manager_name).first()
    if manager:
        Message.objects.create(
            manager=manager,
            title=f'Fichaje: {player.full_name}',
            body=f'{player.full_name} ha firmado con tu equipo. Contrato: ${new_salary:,}/año durante {years} año{"s" if years > 1 else ""}.',
            game_day=Season.get_active().current_game_day if Season.get_active() else 0,
        )

    return redirect('/trade/?team=fa')


@require_POST
def trade_submit(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        my_team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    other_team_id = request.POST.get('other_team_id')
    try:
        other_team = Team.objects.get(pk=other_team_id)
    except (Team.DoesNotExist, ValueError):
        return redirect('trade')

    my_player_ids = request.POST.getlist('my_player_ids', [])
    other_player_ids = request.POST.getlist('other_player_ids', [])

    my_players = list(Player.objects.filter(id__in=my_player_ids, team=my_team))
    other_players = list(Player.objects.filter(id__in=other_player_ids, team=other_team))

    my_salary_out = sum(p.salary for p in my_players)
    other_salary_out = sum(p.salary for p in other_players)

    # NBA 2025-26 apron thresholds
    salary_cap = 155_000_000
    luxury_tax = 189_000_000
    first_apron = 195_900_000
    second_apron = 207_800_000

    from django.db.models import Sum
    my_payroll = (my_team.players.aggregate(total=Sum('salary'))['total'] or 0) - my_salary_out + other_salary_out
    other_payroll = (other_team.players.aggregate(total=Sum('salary'))['total'] or 0) - other_salary_out + my_salary_out

    # ---- NBA RULES VALIDATION ----
    errors = []

    # Rule 1: Each team must have at least 10 players, max 15 after trade
    my_after = my_team.players.count() - len(my_players) + len(other_players)
    other_after = other_team.players.count() - len(other_players) + len(my_players)
    if my_after < 10:
        errors.append(f'Tu equipo tendría solo {my_after} jugadores (mínimo 10)')
    if my_after > 15:
        errors.append(f'Tu equipo tendría {my_after} jugadores (máximo 15)')
    if other_after < 10:
        errors.append(f'{other_team.name} tendría solo {other_after} jugadores (mínimo 10)')
    if other_after > 15:
        errors.append(f'{other_team.name} tendría {other_after} jugadores (máximo 15)')

    # Rule 2: At least one player must be involved
    if not my_players and not other_players:
        errors.append('Debes incluir al menos un jugador en la oferta')

    # Rule 3: NBA salary matching rules based on other team's payroll
    if other_payroll > second_apron:
        # Second apron: can only receive <= what they send (100% rule)
        # Cannot aggregate salaries
        if len(my_players) > 1:
            errors.append(f'{other_team.name} está en el segundo apron ($207.8M). No pueden agregar salarios de múltiples jugadores.')
        if other_salary_out < my_salary_out:
            errors.append(f'{other_team.name} está en el segundo apron. Solo pueden recibir salario igual o menor al que envían.')
    elif other_payroll > first_apron:
        # First apron: can receive up to 110% of what they send
        max_receive = other_salary_out * 1.10
        if my_salary_out > max_receive + 250_000:
            errors.append(f'{other_team.name} está en el primer apron ($195.9M). Solo pueden recibir hasta el 110% del salario enviado.')
    else:
        # Below aprons: standard rules
        if other_salary_out < 7_500_000:
            max_receive = other_salary_out * 2.0 + 250_000
        elif other_salary_out < 29_000_000:
            max_receive = other_salary_out + 7_500_000
        else:
            max_receive = other_salary_out * 1.25 + 250_000
        
        if my_salary_out > max_receive + 250_000:
            errors.append(f'{other_team.name} no puede recibir más de ${max_receive/1_000_000:.1f}M según las reglas de emparejamiento salarial.')

    if errors:
        manager = Manager.objects.filter(name=manager_name).first()
        if manager:
            Message.objects.create(
                manager=manager,
                title=f'Traspaso rechazado: reglas NBA',
                body=f'La oferta no cumple las reglas de la liga: {"; ".join(errors)}',
                game_date=date.today(),
            )
        return redirect('trade')

    # ---- AI DECISION LOGIC ----
    accept_score = 0  # Start neutral, not 50

    # 1. Player quality comparison (MOST IMPORTANT)
    other_best_ovr = max((p.overall for p in other_players), default=0)
    other_worst_ovr = min((p.overall for p in other_players), default=0)
    my_best_ovr = max((p.overall for p in my_players), default=0)
    my_worst_ovr = min((p.overall for p in my_players), default=0)

    other_avg_ovr = (sum(p.overall for p in other_players) / len(other_players)) if other_players else 0
    my_avg_ovr = (sum(p.overall for p in my_players) / len(my_players)) if my_players else 0

    # If they're giving up a star (90+), they need a star back
    if other_best_ovr >= 90:
        if my_best_ovr >= 90:
            accept_score += 40  # Star for star = good deal
            accept_score += (my_best_ovr - other_best_ovr) * 3
        elif my_best_ovr >= 85:
            accept_score += 15  # Good player but not star
            accept_score += (my_best_ovr - other_best_ovr) * 2
        else:
            accept_score -= 50  # Star for role player = terrible
    elif other_best_ovr >= 85:
        if my_best_ovr >= 85:
            accept_score += 30
            accept_score += (my_best_ovr - other_best_ovr) * 2
        elif my_best_ovr >= 80:
            accept_score += 10
        else:
            accept_score -= 30
    elif other_best_ovr >= 80:
        if my_best_ovr >= 80:
            accept_score += 20
        elif my_best_ovr >= 75:
            accept_score += 5
        else:
            accept_score -= 15
    else:
        # Role players, less critical
        if my_avg_ovr >= other_avg_ovr:
            accept_score += 10
        else:
            accept_score -= 10

    # 2. Total OVR value comparison
    other_total_ovr = sum(p.overall for p in other_players)
    my_total_ovr = sum(p.overall for p in my_players)
    ovr_diff = my_total_ovr - other_total_ovr
    accept_score += min(20, max(-20, ovr_diff))

    # 3. Financial situation of other team
    other_current_payroll = other_team.players.aggregate(total=Sum('salary'))['total'] or 0
    other_salary_margin = salary_cap - other_current_payroll

    # If they're deep in luxury tax / apron, they WANT to shed salary
    if other_current_payroll > second_apron:
        # Desperate to reduce payroll
        if my_salary_out > other_salary_out:
            accept_score += 30  # They save money!
        else:
            accept_score -= 20  # They take on more money (bad)
    elif other_current_payroll > first_apron:
        if my_salary_out > other_salary_out:
            accept_score += 20
        else:
            accept_score -= 10
    elif other_current_payroll > luxury_tax:
        if my_salary_out > other_salary_out:
            accept_score += 15
        elif my_salary_out < other_salary_out:
            accept_score -= 5
    else:
        # Under tax, less financial pressure
        if my_salary_out > other_salary_out:
            accept_score += 5
        elif my_salary_out < other_salary_out:
            accept_score -= 5

    # 4. Team needs
    if other_after <= 12:
        accept_score += 15  # They need players badly
    elif other_after <= 14:
        accept_score += 5

    # 5. Age factor - younger players more valuable
    if my_players and other_players:
        my_avg_age = sum(p.age for p in my_players) / len(my_players)
        other_avg_age = sum(p.age for p in other_players) / len(other_players)
        if my_avg_age < other_avg_age - 3:
            accept_score += 10  # Younger talent incoming
        elif my_avg_age > other_avg_age + 3:
            accept_score -= 5

    # 6. Contract length
    if my_players and other_players:
        my_avg_years = sum(p.contract_years for p in my_players) / len(my_players)
        other_avg_years = sum(p.contract_years for p in other_players) / len(other_players)
        if my_avg_years > other_avg_years:
            accept_score += 5  # More years of control

    # 7. Randomness (small)
    accept_score += random.randint(-5, 5)

    # Clamp
    accept_score = max(0, min(100, accept_score))

    # Decision threshold varies by situation
    threshold = 50
    if other_current_payroll > second_apron:
        threshold = 40  # More willing to trade
    elif other_current_payroll > first_apron:
        threshold = 45

    accepted = accept_score >= threshold

    if accepted:
        # Execute trade
        for p in my_players:
            p.team = other_team
            p.save()
        for p in other_players:
            p.team = my_team
            p.save()

        manager = Manager.objects.filter(name=manager_name).first()
        if manager:
            my_names = ', '.join(p.full_name for p in my_players)
            other_names = ', '.join(p.full_name for p in other_players)
            Message.objects.create(
                manager=manager,
                title=f'Traspaso aceptado: {other_team.name}',
                body=f'El traspaso ha sido aceptado. Envías: {my_names}. Recibes: {other_names}.',
                game_date=date.today(),
            )

        # Store trade result in session for success overlay
        request.session['trade_success'] = {
            'my_names': my_names,
            'other_names': other_names,
            'other_team': other_team.name,
        }
    else:
        manager = Manager.objects.filter(name=manager_name).first()
        if manager:
            Message.objects.create(
                manager=manager,
                title=f'Traspaso rechazado: {other_team.name}',
                body=f'{other_team.name} ha rechazado tu oferta de traspaso.',
                game_date=date.today(),
            )
        request.session['trade_rejected'] = {
            'other_team': other_team.name,
        }

    return redirect('roster')


def dismiss_player(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    player_id = request.POST.get('player_id')
    try:
        player = Player.objects.get(pk=player_id, team=team)
    except Player.DoesNotExist:
        return redirect('roster')

    # Calculate penalty: 50% of annual salary × remaining years
    penalty = int(player.salary * player.contract_years * 0.5)

    # Deduct from budget
    team.budget = max(0, team.budget - penalty)
    team.save()

    # Remove player from team (player stays in DB without team)
    player.team = None
    player.save()

    # Create finance record for dismissal
    season = Season.get_active()
    if season:
        FinanceRecord.objects.create(
            team=team,
            season=season,
            record_type=FinanceRecord.TYPE_DISMISSAL,
            game_day=season.current_game_day,
            amount=penalty,
        )

    # Create message from player
    manager = Manager.objects.filter(name=manager_name).first()
    if manager:
        Message.objects.create(
            manager=manager,
            title=f'{player.full_name} despedido',
            body=f'{player.full_name} no está contento con el despido. Ha expresado su descontento públicamente. Coste de la indemnización: ${penalty:,}.',
            game_day=season.current_game_day if season else 0,
        )

    return redirect('roster')


def finances(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    fin_settings, _ = TeamSettings.objects.get_or_create(team=team)

    # Handle price updates
    if request.method == 'POST':
        new_ticket = request.POST.get('ticket_price')
        new_subscription = request.POST.get('subscription_price')
        if new_ticket:
            fin_settings.ticket_price = int(new_ticket)
        if new_subscription:
            fin_settings.subscription_price = int(new_subscription)
        fin_settings.save()
        return redirect('finances')

    # Get all finance records for this team/season
    all_records = FinanceRecord.objects.filter(team=team, season=season)
    
    # Totals by type
    total_ticket = all_records.filter(record_type=FinanceRecord.TYPE_TICKET).aggregate(Sum('amount'))['amount__sum'] or 0
    total_subscription = all_records.filter(record_type=FinanceRecord.TYPE_SUBSCRIPTION).aggregate(Sum('amount'))['amount__sum'] or 0
    total_sponsorship = all_records.filter(record_type=FinanceRecord.TYPE_SPONSORSHIP).aggregate(Sum('amount'))['amount__sum'] or 0
    total_tv = all_records.filter(record_type=FinanceRecord.TYPE_TV).aggregate(Sum('amount'))['amount__sum'] or 0
    total_renovation = all_records.filter(record_type=FinanceRecord.TYPE_RENOVATION).aggregate(Sum('amount'))['amount__sum'] or 0
    total_dismissal = all_records.filter(record_type=FinanceRecord.TYPE_DISMISSAL).aggregate(Sum('amount'))['amount__sum'] or 0
    total_salaries = all_records.filter(record_type=FinanceRecord.TYPE_SALARIES).aggregate(Sum('amount'))['amount__sum'] or 0
    total_salaries_fmt = f'${total_salaries:,}'

    total_revenue = total_ticket + total_subscription + total_sponsorship + total_tv
    total_expenses = total_renovation + total_dismissal + total_salaries
    net_balance = total_revenue - total_expenses

    # Monthly data for chart - use actual calendar month boundaries
    month_names_es = ['Octubre', 'Noviembre', 'Diciembre', 'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio']
    month_ranges = [
        (1, 9),     # October
        (10, 39),   # November
        (40, 69),   # December
        (70, 99),   # January
        (100, 127), # February
        (128, 157), # March
        (158, 187), # April
        (188, 217), # May
        (218, 247), # June
        (248, 277), # July
    ]
    months_data = []
    for i, (month_start, month_end) in enumerate(month_ranges):
        month_income = all_records.filter(
            game_day__gte=month_start,
            game_day__lte=month_end,
            record_type__lte=FinanceRecord.TYPE_TV
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        month_expenses = all_records.filter(
            game_day__gte=month_start,
            game_day__lte=month_end,
            record_type__gte=FinanceRecord.TYPE_RENOVATION
        ).aggregate(Sum('amount'))['amount__sum'] or 0
        
        months_data.append({
            'name': month_names_es[i],
            'income': month_income,
            'expenses': month_expenses,
            'balance': month_income - month_expenses,
        })

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season, is_played=False,
    ).filter(Q(home_team=team) | Q(away_team=team)).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    current_date = None
    if manager := Manager.objects.filter(name=manager_name).first():
        current_date = manager.current_date
    elif season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            current_date = date(season.year_start, 10, 22)
    else:
        current_date = date(season.year_start, 10, 22)

    payroll = team.players.aggregate(total=Sum('salary'))['total'] or 0
    monthly_payroll = payroll // 12
    max_balance = max((abs(m['balance']) for m in months_data), default=1)
    if max_balance == 0:
        max_balance = 1

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'payroll': payroll,
        'monthly_payroll': monthly_payroll,
        'total_revenue': total_revenue,
        'total_expenses': total_expenses,
        'net_balance': net_balance,
        'ticket_price': fin_settings.ticket_price,
        'subscription_price': fin_settings.subscription_price,
        'total_ticket': total_ticket,
        'total_subscription': total_subscription,
        'total_sponsorship': total_sponsorship,
        'total_tv': total_tv,
        'total_renovation': total_renovation,
        'total_dismissal': total_dismissal,
        'total_salaries': total_salaries_fmt,
        'months_data': months_data,
        'chart_max_value': max_balance,
        'ticket_prices': [20, 30, 40, 50, 60, 70, 80, 90, 100, 120, 150, 180, 200, 250, 300],
        'subscription_prices': [200, 300, 400, 500, 600, 700, 800, 1000, 1200, 1500, 2000, 2500, 3000, 4000, 5000],
        'season_phase': season.phase,
    }
    return render(request, 'core/finances.html', context)


def sponsors(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')
    
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')
    
    manager = Manager.objects.filter(name=manager_name).first()
    season = Season.get_active()
    fin_settings = TeamSettings.objects.get(team=team)
    
    current_date = manager.current_date if manager else date.today()
    can_hire = current_date.month == 10 and fin_settings.sponsor is None
    
    if request.method == 'POST' and can_hire:
        sponsor_id = request.POST.get('sponsor_id')
        sponsor = Sponsor.objects.get(pk=sponsor_id)
        
        fin_settings.sponsor = sponsor
        fin_settings.sponsor_years_remaining = sponsor.contract_years
        fin_settings.save()
        
        Message.objects.create(
            manager=manager,
            title=f'Nuevo patrocinador: {sponsor.name}',
            body=f'Has contratado a {sponsor.name}. Recibirás ${sponsor.initial_income:,} iniciales y ${sponsor.home_game_income:,} por partido en casa durante {sponsor.contract_years} año{"s" if sponsor.contract_years > 1 else ""}.',
            game_date=current_date,
        )
        
        FinanceRecord.objects.create(
            team=team,
            season=season,
            record_type=FinanceRecord.TYPE_SPONSORSHIP,
            game_day=max(1, season.current_game_day if season else 0),
            amount=sponsor.initial_income,
        )
        
        team.budget += sponsor.initial_income
        team.save()
        
        return redirect('sponsors')
    
    payroll = team.payroll()
    salary_margin = team.salary_margin()
    season_label = f"{season.year_start}-{season.year_end}" if season else "N/A"
    
    if season.phase == 'playoffs':
        btn_text = 'VER PLAYOFFS'
    elif season.phase == 'finished':
        btn_text = 'FINALIZADO'
    else:
        next_day = season.current_game_day + 1
        if Game.objects.filter(season=season, game_day=next_day, home_team=team).exists() or Game.objects.filter(season=season, game_day=next_day, away_team=team).exists():
            btn_text = 'DÍA DE PARTIDO'
        else:
            btn_text = 'AVANZAR DÍA'
    
    context = {
        'team': team,
        'manager_name': manager_name,
        'season_label': season_label,
        'current_date': current_date.strftime('%d/%m/%Y'),
        'btn_text': btn_text,
        'payroll': payroll,
        'sponsors': Sponsor.objects.filter(is_active=True),
        'current_sponsor': fin_settings.sponsor,
        'can_hire': can_hire,
    }
    return render(request, 'core/sponsors.html', context)


def television(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')
    
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')
    
    manager = Manager.objects.filter(name=manager_name).first()
    season = Season.get_active()
    fin_settings = TeamSettings.objects.get(team=team)
    
    current_date = manager.current_date if manager else date.today()
    can_hire = current_date.month == 10 and fin_settings.tv_channel is None
    
    if request.method == 'POST' and can_hire:
        tv_id = request.POST.get('tv_id')
        tv = TvChannel.objects.get(pk=tv_id)
        
        fin_settings.tv_channel = tv
        fin_settings.tv_years_remaining = tv.contract_years
        fin_settings.save()
        
        Message.objects.create(
            manager=manager,
            title=f'Nuevo contrato de TV: {tv.name}',
            body=f'Has firmado con {tv.name}. Recibirás ${tv.initial_income:,} iniciales y ${tv.home_game_income:,} por partido en casa durante {tv.contract_years} año{"s" if tv.contract_years > 1 else ""}.',
            game_date=current_date,
        )
        
        FinanceRecord.objects.create(
            team=team,
            season=season,
            record_type=FinanceRecord.TYPE_TV,
            game_day=max(1, season.current_game_day if season else 0),
            amount=tv.initial_income,
        )
        
        team.budget += tv.initial_income
        team.save()
        
        return redirect('television')
    
    payroll = team.payroll()
    salary_margin = team.salary_margin()
    season_label = f"{season.year_start}-{season.year_end}" if season else "N/A"
    
    if season.phase == 'playoffs':
        btn_text = 'VER PLAYOFFS'
    elif season.phase == 'finished':
        btn_text = 'FINALIZADO'
    else:
        next_day = season.current_game_day + 1
        if Game.objects.filter(season=season, game_day=next_day, home_team=team).exists() or Game.objects.filter(season=season, game_day=next_day, away_team=team).exists():
            btn_text = 'DÍA DE PARTIDO'
        else:
            btn_text = 'AVANZAR DÍA'
    
    context = {
        'team': team,
        'manager_name': manager_name,
        'season_label': season_label,
        'current_date': current_date.strftime('%d/%m/%Y'),
        'btn_text': btn_text,
        'payroll': payroll,
        'tv_channels': TvChannel.objects.filter(is_active=True),
        'current_tv': fin_settings.tv_channel,
        'can_hire': can_hire,
    }
    return render(request, 'core/television.html', context)


@require_POST
def contract_offer(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    player_id = request.POST.get('player_id')
    salary = int(request.POST.get('salary', 0))
    years = int(request.POST.get('years', 0))

    if not player_id or salary < 2_000_000 or salary > 60_000_000 or years < 1 or years > 5:
        return redirect('roster')

    try:
        player = Player.objects.get(pk=player_id, team=team)
    except Player.DoesNotExist:
        return redirect('roster')

    # Calculate acceptance probability
    current_salary = player.salary
    salary_increase = (salary - current_salary) / current_salary if current_salary > 0 else 0
    
    # Base acceptance rate
    accept_score = 50
    
    # Salary factor: big increase = more likely to accept
    if salary_increase >= 0.3:
        accept_score += 25
    elif salary_increase >= 0.1:
        accept_score += 15
    elif salary_increase >= 0:
        accept_score += 5
    else:
        accept_score -= abs(salary_increase) * 50
    
    # Age factor: older players more likely to accept
    if player.age >= 32:
        accept_score += 10
    elif player.age >= 28:
        accept_score += 5
    elif player.age <= 23:
        accept_score -= 5
    
    # Overall/quality factor: better players demand more
    if player.overall >= 85:
        accept_score -= 5
    elif player.overall >= 75:
        accept_score += 0
    else:
        accept_score += 5
    
    # Importance in team (minutes played this season)
    from .models import PlayerGameStats
    games_played = PlayerGameStats.objects.filter(
        player=player,
        game__season=Season.get_active(),
        game__is_played=True
    ).count()
    
    if games_played >= 50:
        accept_score += 10  # Key player, values security
    elif games_played >= 30:
        accept_score += 5
    elif games_played >= 10:
        accept_score += 0
    else:
        accept_score -= 10  # Bench player, less leverage
    
    # Years factor: longer contracts are more attractive
    if years >= 4:
        accept_score += 10
    elif years >= 3:
        accept_score += 5
    elif years >= 2:
        accept_score += 0
    else:
        accept_score -= 5
    
    # Cap probability
    accept_score = max(10, min(95, accept_score))
    
    accepted = random.randint(1, 100) <= accept_score
    
    player_name = player.full_name
    salary_m = f"${salary / 1_000_000:.0f}M"
    years_text = f"{years} año{'s' if years > 1 else ''}"
    
    if accepted:
        player.salary = salary
        player.contract_years = years
        player.save()
        
        Message.objects.create(
            manager=Manager.objects.filter(name=manager_name).first(),
            title=f'Contrato renovado: {player_name}',
            body=f'{player_name} ha aceptado la oferta de renovación. Nuevo contrato: {salary_m}/año durante {years_text}.',
        )
        request.session['contract_result'] = {
            'accepted': True,
            'player': player_name,
            'salary': salary_m,
            'years': years_text,
        }
    else:
        Message.objects.create(
            manager=Manager.objects.filter(name=manager_name).first(),
            title=f'Oferta rechazada: {player_name}',
            body=f'{player_name} ha rechazado la oferta de {salary_m}/año durante {years_text}.',
        )
        request.session['contract_result'] = {
            'accepted': False,
            'player': player_name,
            'salary': salary_m,
            'years': years_text,
        }
    
    return redirect('roster')


def results(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    selected_date_str = request.GET.get('date')
    if selected_date_str:
        try:
            parts = selected_date_str.split('-')
            selected_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            selected_date = date(season.year_start, 10, 22)
    else:
        # Use the date of the last game played by the user's team
        last_team_game = Game.objects.filter(
            season=season,
            is_played=True,
        ).filter(
            Q(home_team=team) | Q(away_team=team)
        ).order_by('-game_day').first()
        
        if last_team_game:
            selected_date = last_team_game.game_date
        elif season.current_game_day > 0:
            last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
            if last_played:
                selected_date = last_played.game_date
            else:
                selected_date = date(season.year_start, 10, 22)
        else:
            selected_date = date(season.year_start, 10, 22)

    season_start = date(season.year_start, 10, 22)
    season_end = date(season.year_end, 4, 15)
    total_days = (season_end - season_start).days + 1

    day_idx = (selected_date - season_start).days
    day_idx = max(0, min(day_idx, total_days - 1))

    prev_date = selected_date - timedelta(days=1) if day_idx > 0 else None
    next_date = selected_date + timedelta(days=1) if day_idx < total_days - 1 else None

    day_games = Game.objects.filter(season=season, game_day=day_idx + 1).order_by('pk')

    current_date = None
    if manager := Manager.objects.filter(name=manager_name).first():
        current_date = manager.current_date
    elif season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            current_date = date(season.year_start, 10, 22)
    else:
        current_date = date(season.year_start, 10, 22)

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'selected_date': selected_date,
        'selected_date_str': selected_date.strftime('%d/%m/%Y'),
        'prev_date': prev_date.strftime('%Y-%m-%d') if prev_date else None,
        'next_date': next_date.strftime('%Y-%m-%d') if next_date else None,
        'day_games': day_games,
        'season_phase': season.phase,
    }

    # Calendar picker data - pass as JSON for client-side rendering
    month_names_es = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                      'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

    cal_season_start = date(season.year_start, 10, 22)
    cal_season_end = date(season.year_end, 4, 15)

    calendar_months = []
    cur = cal_season_start.replace(day=1)
    while cur <= cal_season_end:
        year = cur.year
        month = cur.month
        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)

        weekday_offset = (first_day.weekday() + 1) % 7
        total_cells = weekday_offset + last_day.day
        total_rows = (total_cells + 6) // 7
        total_grid = total_rows * 7

        days = []
        for i in range(total_grid):
            if i < weekday_offset or (i - weekday_offset) >= last_day.day:
                days.append(None)
            else:
                day_num = i - weekday_offset + 1
                d = date(year, month, day_num)
                days.append({
                    'day': day_num,
                    'date_str': d.strftime('%Y-%m-%d'),
                    'is_selected': d == selected_date,
                })

        calendar_months.append({
            'year': year,
            'month': month,
            'month_name': month_names_es[month - 1],
            'days': days,
        })

        if month == 12:
            cur = date(year + 1, 1, 1)
        else:
            cur = date(year, month + 1, 1)

    context['calendar_months_json'] = json.dumps(calendar_months)
    context['selected_date_str_full'] = selected_date.strftime('%Y-%m-%d')

    return render(request, 'core/results.html', context)


def standings(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    selected_conf = request.GET.get('conf', 'all')
    standings_east = build_standings_from_games(season, 'East')
    standings_west = build_standings_from_games(season, 'West')

    if selected_conf == 'East':
        display_standings = standings_east
        if display_standings:
            first = display_standings[0]
            for s in display_standings:
                s['gb'] = round((first['wins'] - s['wins'] + s['losses'] - first['losses']) / 2, 1)
    elif selected_conf == 'West':
        display_standings = standings_west
        if display_standings:
            first = display_standings[0]
            for s in display_standings:
                s['gb'] = round((first['wins'] - s['wins'] + s['losses'] - first['losses']) / 2, 1)
    else:
        display_standings = sorted(standings_east + standings_west, key=lambda x: (-x['pct'], x['losses'], -x['wins']))
        east_count = 0
        west_count = 0
        for s in display_standings:
            if s['team'].conference == 'East':
                east_count += 1
                if east_count <= 6:
                    s['zone'] = 'playoff'
                elif east_count <= 10:
                    s['zone'] = 'playin'
                else:
                    s['zone'] = 'out'
            else:
                west_count += 1
                if west_count <= 6:
                    s['zone'] = 'playoff'
                elif west_count <= 10:
                    s['zone'] = 'playin'
                else:
                    s['zone'] = 'out'
        for i, s in enumerate(display_standings, 1):
            s['rank'] = i
        if display_standings:
            first = display_standings[0]
            for s in display_standings:
                s['gb'] = round((first['wins'] - s['wins'] + s['losses'] - first['losses']) / 2, 1)
        else:
            for s in display_standings:
                s['gb'] = 0

    current_date = None
    if manager := Manager.objects.filter(name=manager_name).first():
        current_date = manager.current_date
    elif season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            from datetime import date
            current_date = date(season.year_start, 10, 22)
    else:
        from datetime import date
        current_date = date(season.year_start, 10, 22)

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'standings': display_standings,
        'selected_conf': selected_conf,
        'season_phase': season.phase,
    }
    return render(request, 'core/standings.html', context)


def records(request):
    """Display team records with filters: My Team, Season, Historical."""
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')
    
    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')
    
    season = Season.get_active()
    if not season:
        return redirect('home')
    
    filter_type = request.GET.get('filter', 'team')
    
    STAT_ORDER = ['points', 'rebounds', 'assists', 'steals', 'blocks', 'fgm', 'fg3m', 'ftm', 'turnovers']
    STAT_LABELS = {
        'points': 'Puntos',
        'rebounds': 'Rebotes',
        'assists': 'Asistencias',
        'steals': 'Robos',
        'blocks': 'Tapones',
        'fgm': 'Tiros de Campo',
        'fg3m': 'Triples',
        'ftm': 'Tiros Libres',
        'turnovers': 'Pérdidas',
    }
    
    records_data = []
    
    if filter_type == 'team':
        # TeamRecord: best all-time for user's team
        team_records = TeamRecord.objects.filter(team=team)
        records_by_stat = {r.stat_type: r for r in team_records}
        for stat in STAT_ORDER:
            if stat in records_by_stat:
                r = records_by_stat[stat]
                records_data.append({
                    'stat': STAT_LABELS.get(r.stat_type, r.stat_type),
                    'stat_type': r.stat_type,
                    'player': r.player_name,
                    'value': r.value,
                    'date': r.game_date.strftime('%d/%m/%Y') if r.game_date else '',
                })
    elif filter_type == 'season':
        # SeasonGameRecord: best of current season for all teams
        all_team_ids = [t.pk for t in Team.objects.all()]
        season_records = SeasonGameRecord.objects.filter(
            season=season, team_id__in=all_team_ids
        ).order_by('-value')
        seen_stats = set()
        for r in season_records:
            if r.stat_type not in seen_stats:
                records_data.append({
                    'stat': STAT_LABELS.get(r.stat_type, r.stat_type),
                    'stat_type': r.stat_type,
                    'player': r.player_name,
                    'value': r.value,
                    'date': r.game_date.strftime('%d/%m/%Y') if r.game_date else '',
                    'team': r.team.name,
                })
                seen_stats.add(r.stat_type)
    else:
        # HistoricalRecord: NBA all-time best
        historical_records = HistoricalRecord.objects.all()
        records_by_stat = {r.stat_type: r for r in historical_records}
        for stat in STAT_ORDER:
            if stat in records_by_stat:
                r = records_by_stat[stat]
                # Get full team name from abbreviation
                team_obj = Team.objects.filter(abbreviation=r.team_abbreviation).first()
                team_name = team_obj.name if team_obj else r.team_abbreviation
                records_data.append({
                    'stat': STAT_LABELS.get(r.stat_type, r.stat_type),
                    'stat_type': r.stat_type,
                    'player': r.player_name,
                    'value': r.value,
                    'date': r.game_date.strftime('%d/%m/%Y') if r.game_date else '',
                    'team': team_name,
                })
    
    current_date = None
    if manager := Manager.objects.filter(name=manager_name).first():
        current_date = manager.current_date
    elif season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            from datetime import date
            current_date = date(season.year_start, 10, 22)
    else:
        from datetime import date
        current_date = date(season.year_start, 10, 22)
    
    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)
    
    next_unplayed_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first()
    
    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'
    
    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'records': records_data,
        'filter_type': filter_type,
        'season_phase': season.phase,
    }
    return render(request, 'core/records.html', context)


def messages_view(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    manager = Manager.objects.filter(name=manager_name).first()
    season = Season.get_active()

    messages = Message.objects.filter(manager=manager) if manager else []

    current_date = None
    if manager and manager.current_date:
        current_date = manager.current_date
    elif season and season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            from datetime import date
            current_date = date(season.year_start, 10, 22)
    else:
        from datetime import date
        current_date = date(season.year_start, 10, 22) if season else ''

    next_day = season.current_game_day + 1 if season else 0
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False) if season else []
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team) if season else []

    next_unplayed_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first() if season else None

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}" if season else '',
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'messages': messages,
        'btn_text': btn_text,
        'season_phase': season.phase if season else 'regular',
    }
    return render(request, 'core/messages.html', context)


def delete_message(request, message_id):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    manager = Manager.objects.filter(name=manager_name).first()
    if manager:
        Message.objects.filter(id=message_id, manager=manager).delete()

    return redirect('messages')


def _create_game_result_message(manager, team, game):
    """Create a post-game result message."""
    is_home = game.home_team_id == team.pk
    team_score = game.home_score if is_home else game.away_score
    opp_score = game.away_score if is_home else game.home_score
    opp_name = game.away_team.name if is_home else game.home_team.name
    venue = "casa" if is_home else "fuera"

    if team_score > opp_score:
        title = f"¡Victoria contra {opp_name}!"
        body = f"Los {team.name} han ganado a los {opp_name} por {team_score}-{opp_score} jugando {venue}. ¡Gran trabajo del equipo!"
    else:
        title = f"Derrota contra {opp_name}"
        body = f"Los {team.name} han perdido contra los {opp_name} por {team_score}-{opp_score} jugando {venue}."

    Message.objects.create(
        manager=manager,
        title=title,
        body=body,
        game_day=game.game_day,
        game_date=game.game_date,
    )


@require_POST
def simulate_others(request):
    """Simula partidos de otros equipos (cuando el usuario no tiene juego)."""
    season = Season.get_active()
    if not season:
        return redirect('home')

    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        team = None

    _update_injuries()
    _process_renovations(season)

    next_day = season.current_game_day + 1
    day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)

    if day_games.exists():
        simulate_day(season, next_day)

    season.current_game_day = next_day
    season.save()

    all_played_on_day = Game.objects.filter(
        season=season,
        game_day=next_day,
        is_played=True,
    )

    return redirect('game_results')


@require_POST
def advance_day(request):
    season = Season.get_active()
    if not season:
        return redirect('home')

    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        team = None

    _update_injuries()
    _process_renovations(season)

    if team and season.phase == 'regular':
        _process_subscription_revenue(team, season)

    # Simulate games for the current day
    next_day = season.current_game_day + 1
    day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)

    if day_games.exists():
        simulate_day(season, next_day)
    else:
        max_day = Game.objects.filter(season=season).order_by('-game_day').values_list('game_day', flat=True).first()
        if max_day and next_day <= max_day:
            simulate_day(season, next_day)

    season.current_game_day = next_day
    season.save()

    # Process monthly payroll only during regular season
    if season.phase == 'regular' and team:
        manager = Manager.objects.filter(name=manager_name).first() if manager_name else None
        current_date = manager.current_date if manager else None
        if current_date:
            _process_monthly_payroll(team, season, current_date)

    # ── Phase transition: Regular → Play-In ──
    if season.phase == 'regular':
        remaining_regular = Game.objects.filter(season=season, game_type='regular', is_played=False).exists()
        if not remaining_regular:
            from .schedule_generator import generate_playin
            generate_playin(season)
            season.phase = 'playin'
            season.save()
            # Simulate play-in games if they land on the current day
            playin_today = Game.objects.filter(season=season, game_day=next_day, game_type='playin', is_played=False)
            if playin_today.exists():
                simulate_day(season, next_day)

    # ── Phase: Play-In ──
    if season.phase == 'playin':
        from .schedule_generator import create_playin_eliminator
        for conf in ['east', 'west']:
            create_playin_eliminator(season, conf)

        # Simulate eliminator games if they land on the current day
        elim_today = Game.objects.filter(season=season, game_day=next_day, game_type='playin', is_played=False)
        if elim_today.exists():
            simulate_day(season, next_day)

        remaining_playin = Game.objects.filter(season=season, game_type='playin', is_played=False).exists()
        if not remaining_playin and season.phase != 'playoffs':
            from .schedule_generator import generate_playoffs
            generate_playoffs(season)
            season.phase = 'playoffs'
            season.save()

    # ── Phase: Playoffs ──
    if season.phase == 'playoffs':
        from .schedule_generator import advance_all_playoff_series
        advance_all_playoff_series(season)

        # After advancing, check if new series games were created for the current day
        new_games_today = Game.objects.filter(season=season, game_day=next_day, game_type='playoff', is_played=False)
        if new_games_today.exists():
            simulate_day(season, next_day)

        remaining_playoff = Game.objects.filter(season=season, game_type='playoff', is_played=False).exists()
        if not remaining_playoff:
            season.phase = 'finished'
            season.save()
            _save_season_record(season)
            if manager_name:
                manager = Manager.objects.filter(name=manager_name).first()
                if manager:
                    _check_dismissal(manager, season, request)

    # ── Phase: Finished → Season Summary after 3 days ──
    if season.phase == 'finished':
        if manager_name:
            manager = Manager.objects.filter(name=manager_name).first()
            if manager:
                _check_dismissal(manager, season, request)
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played and next_day >= last_played.game_day + 3:
            if request.session.get('is_dismissed') and not request.session.get('dismissal_acknowledged'):
                return redirect('dismissal')
            return redirect('season_summary')

    # ── Manager date update ──
    if manager_name:
        manager = Manager.objects.filter(name=manager_name).first()
        if manager:
            # Advance date by 1 day, not jump to next game
            if manager.current_date:
                manager.current_date += timedelta(days=1)
            else:
                from datetime import date
                manager.current_date = date(season.year_start, 10, 22)
            _update_manager_stats(manager, season, next_day)
            manager.save()

    # ── Check what happened today ──
    all_played_on_day = Game.objects.filter(
        season=season,
        game_day=next_day,
        is_played=True,
    )
    my_game_on_day = all_played_on_day.filter(
        Q(home_team=team) | Q(away_team=team)
    ).first() if team else None

    if my_game_on_day:
        if my_game_on_day.home_team_id == team.pk and my_game_on_day.game_type == 'regular':
            fin_settings, _ = TeamSettings.objects.get_or_create(team=team)

            team_games_played = Game.objects.filter(
                season=season,
                is_played=True,
                game_type='regular',
            ).filter(
                Q(home_team=team) | Q(away_team=team)
            )
            total_games = team_games_played.count()
            wins = 0
            for g in team_games_played:
                is_home = g.home_team_id == team.pk
                team_score = g.home_score if is_home else g.away_score
                opp_score = g.away_score if is_home else g.home_score
                if team_score > opp_score:
                    wins += 1

            win_pct = wins / total_games if total_games > 0 else 0.5
            base_attendance = team.capacity * (0.55 + win_pct * 0.40)
            random_factor = 0.92 + random.random() * 0.16
            attendance = int(min(team.capacity, base_attendance * random_factor))
            ticket_revenue = attendance * fin_settings.ticket_price

            team.budget += ticket_revenue
            team.save()

            FinanceRecord.objects.create(
                team=team,
                season=season,
                record_type=FinanceRecord.TYPE_TICKET,
                game_day=next_day,
                amount=ticket_revenue,
            )

        if manager_name:
            manager = Manager.objects.filter(name=manager_name).first()
            if manager:
                _create_game_result_message(manager, team, my_game_on_day)

    # If any games were played today, go to game_results
    if all_played_on_day.exists():
        return redirect('game_results')

    return redirect('dashboard')


def _process_monthly_payroll(team, season, current_date):
    """Deduct 1/12th of player's salary from team budget on the 1st of each month. Only for the specified team."""
    from django.db.models import Sum
    
    # Check if today is the 1st of the month
    if current_date.day != 1:
        return
    
    # Check if this month's salary has already been processed
    if season.last_payroll_month == current_date.month:
        return
    
    season.last_payroll_month = current_date.month
    season.save()
    
    # Deduct payroll only for this team
    payroll = team.players.aggregate(total=Sum('salary'))['total'] or 0
    monthly_payroll = payroll // 12
    team.budget = max(0, team.budget - monthly_payroll)
    team.save(update_fields=['budget'])
    
    # Create finance record for salaries
    if monthly_payroll > 0:
        FinanceRecord.objects.create(
            team=team,
            season=season,
            record_type=FinanceRecord.TYPE_SALARIES,
            game_day=season.current_game_day,
            amount=monthly_payroll,
        )


def _update_manager_stats(manager, season, game_day):
    """
    Update manager trust, morale and pressure based on the result of the last game.
    Each stat has different behavior:
    - Trust: Based on win/loss and opponent difficulty
    - Morale: Based on win/loss, close games, and injuries
    - Press Confidence: Based on win/loss, margin, and opponent quality
    """
    from .models import Game, Player
    
    team = manager.team
    
    # Find the game for this day
    game = Game.objects.filter(
        season=season,
        game_day=game_day,
        is_played=True,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).first()
    
    if not game:
        return  # No game for this team today, don't update
    
    # Get game info
    is_home = game.home_team_id == team.pk
    team_score = game.home_score if is_home else game.away_score
    opp_score = game.away_score if is_home else game.home_score
    opponent = game.away_team if is_home else game.home_team
    
    won = team_score > opp_score
    margin = team_score - opp_score
    is_playoff = game.game_type == 'playoff'
    
    # === TRUST (Confianza - Directiva) ===
    # Base: ±3 per win/loss
    # Difficulty adjustment: ±2 if opponent is better/worse than expected
    trust_delta = 3 if won else -3
    
    # Adjust for difficulty (opponent overall vs team overall)
    overall_diff = opponent.overall - team.overall
    if won and overall_diff > 5:
        trust_delta += 2  # Bonus for beating a better team
    elif won and overall_diff < -5:
        trust_delta -= 1  # Minor penalty for beating a worse team
    elif not won and overall_diff < -5:
        trust_delta -= 2  # Penalty for losing to a worse team
    elif not won and overall_diff > 5:
        trust_delta += 1  # Partial credit for losing to a better team
    
    # Playoff bonus/penalty is higher
    if is_playoff:
        trust_delta = int(trust_delta * 1.5)
    
    manager.trust = max(0, min(100, manager.trust + trust_delta))
    
    # === MORALE (Moral del equipo) ===
    # Base: ±2 per win/loss
    # Close game bonus: ±1 for close games (≤5 points)
    # Injury penalty: -1 if key players injured
    morale_delta = 2 if won else -2
    
    # Close game adjustment
    if abs(margin) <= 5:
        morale_delta += 1 if won else -1
    
    # Injury check (players out with 7+ days)
    injured_count = Player.objects.filter(
        team=team,
        injury_days__gte=7
    ).count()
    if injured_count >= 2:
        morale_delta -= 1
    elif injured_count >= 4:
        morale_delta -= 2
    
    manager.morale = max(0, min(100, manager.morale + morale_delta))
    
    # === PRESS CONFIDENCE (Confianza de la Prensa) ===
    # Base: ±4 per win/loss
    # Margin bonus: +2 for big wins (≥15), +1 for close wins
    # Difficulty: ±2 based on opponent quality
    press_delta = 4 if won else -4
    
    # Margin adjustment
    if won and margin >= 15:
        press_delta += 2  # Big win bonus
    elif won and margin <= 5:
        press_delta += 1  # Close win
    elif not won and margin >= 15:
        press_delta -= 2  # Bad loss (blown out)
    
    # Difficulty adjustment
    if won and overall_diff > 3:
        press_delta += 2  # More credit for beating good teams
    elif not won and overall_diff < -3:
        press_delta -= 2  # Worse for losing to bad teams
    
    # Playoff has more impact
    if is_playoff:
        press_delta = int(press_delta * 1.5)
    
    manager.pressure = max(0, min(100, manager.pressure + press_delta))


def _check_dismissal(manager, season, request):
    """Check if manager should be dismissed based on trust, morale or press confidence."""
    dismissed = False
    reason = None

    if manager.trust <= 5:
        dismissed = True
        reason = 'La directiva ha perdido la confianza en tu trabajo.'
    elif manager.morale <= 5:
        dismissed = True
        reason = 'La moral del equipo está en mínimos. Los jugadores ya no creen en ti.'
    elif manager.pressure <= 5:
        dismissed = True
        reason = 'La prensa ha perdido la confianza en ti. Las críticas son constantes.'

    if dismissed:
        request.session['is_dismissed'] = True
        request.session['dismissal_reason'] = reason
        request.session['dismissal_trust'] = manager.trust
        request.session['dismissal_morale'] = manager.morale
        request.session['dismissal_pressure'] = manager.pressure

    return dismissed


def dismissal(request):
    if not request.session.get('is_dismissed'):
        return redirect('home')
    
    context = {
        'dismissal_reason': request.session.get('dismissal_reason', 'La directiva ha decidido prescindir de tus servicios.'),
        'dismissal_trust': request.session.get('dismissal_trust', 0),
        'dismissal_morale': request.session.get('dismissal_morale', 0),
        'dismissal_pressure': request.session.get('dismissal_pressure', 0),
        'game_mode': request.session.get('game_mode', 'manager'),
    }
    return render(request, 'core/dismissal.html', context)


@require_POST
def dismissal_acknowledge(request):
    request.session['dismissal_acknowledged'] = True
    return JsonResponse({'success': True})


def dismissal_choose_team(request):
    if not request.session.get('is_dismissed'):
        return redirect('home')
    
    game_mode = request.session.get('game_mode', 'promanager')
    
    teams = Team.objects.all().order_by('overall')
    worst_5 = list(teams[:5])
    
    for t in teams:
        t.selectable = t in worst_5
    
    from django.db.models import Sum
    for t in teams:
        payroll_result = t.players.aggregate(total=Sum('salary'))
        t.team_payroll = payroll_result['total'] or 0
        from .models import LeagueSettings
        cap = LeagueSettings.get_active().salary_cap
        t.team_cap_margin = cap - t.team_payroll
    
    east = teams.filter(conference='East')
    west = teams.filter(conference='West')
    
    selected_id = request.POST.get('team_id') or request.session.get('dismissal_team_id')
    
    context = {
        'teams': teams,
        'east': east,
        'west': west,
        'game_mode': game_mode,
        'page_title': 'ELIGE EQUIPO',
        'page_subtitle': 'PROMANAGER - NUEVA CARRERA',
        'is_dismissal': True,
        'selected_team_id': selected_id,
    }
    return render(request, 'core/choose_team.html', context)


@require_POST
def dismissal_select_team(request):
    team_id = request.POST.get('team_id')
    if team_id:
        request.session['dismissal_team_id'] = int(team_id)
    return JsonResponse({'success': True})


@require_POST
def dismissal_start_new(request):
    team_id = request.session.get('dismissal_team_id')
    if not team_id:
        return redirect('dismissal_choose_team')
    
    team = Team.objects.get(pk=team_id)
    
    season = Season.get_active()
    if not season:
        return redirect('home')
    
    request.session['is_dismissed'] = False
    request.session['dismissal_reason'] = None
    request.session['dismissal_trust'] = None
    request.session['dismissal_morale'] = None
    request.session['dismissal_pressure'] = None
    request.session['dismissal_team_id'] = None
    
    request.session['team_id'] = team_id
    request.session['game_mode'] = 'promanager'
    
    Manager.objects.filter(name=request.session.get('manager_name')).delete()
    
    manager_name = request.session.get('manager_name', '')
    start_date = date(season.year_start, 10, 22)
    manager = Manager.objects.create(
        name=manager_name,
        team=team,
        game_mode='promanager',
        current_date=start_date,
        trust=50,
        morale=50,
        pressure=50,
    )
    
    return redirect('dashboard')


def calendar(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')
    
    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    from datetime import date, timedelta
    selected_date_str = request.GET.get('date')
    user_selected_day = bool(selected_date_str)
    if selected_date_str:
        try:
            parts = selected_date_str.split('-')
            selected_date = date(int(parts[0]), int(parts[1]), int(parts[2]))
        except (ValueError, IndexError):
            selected_date = date(season.year_start, 10, 1)
            user_selected_day = False
    else:
        manager = Manager.objects.filter(name=manager_name).first()
        if manager and manager.current_date:
            selected_date = manager.current_date
        elif season.current_game_day > 0:
            last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
            if last_played:
                selected_date = last_played.game_date
            else:
                selected_date = date(season.year_start, 10, 22)
        else:
            selected_date = date(season.year_start, 10, 22)

    year = selected_date.year
    month = selected_date.month

    import calendar as cal_mod
    cal_obj = cal_mod.Calendar(firstweekday=6)
    month_days = cal_obj.monthdayscalendar(year, month)
    month_name = cal_mod.month_name[month]

    dates_by_day = {}
    for week in month_days:
        for day in week:
            if day > 0:
                d = date(year, month, day)
                dates_by_day[day] = d.strftime('%Y-%m-%d')

    team_games = Game.objects.filter(
        season=season,
    ).filter(home_team=team).order_by('game_date') | Game.objects.filter(
        season=season,
    ).filter(away_team=team).order_by('game_date')

    games_by_date = {}
    games_by_date_flags = {}
    for g in team_games:
        key = g.game_date.strftime('%Y-%m-%d')
        if key not in games_by_date:
            games_by_date[key] = []
        games_by_date[key].append(g)
        if g.home_team_id == team.pk:
            games_by_date_flags[key] = g.away_team.logo
        else:
            games_by_date_flags[key] = g.home_team.logo

    all_games = Game.objects.filter(season=season).order_by('game_date')
    games_by_date_all = {}
    for g in all_games:
        key = g.game_date.strftime('%Y-%m-%d')
        if key not in games_by_date_all:
            games_by_date_all[key] = []
        games_by_date_all[key].append(g)

    selected_date_str_full = selected_date.strftime('%Y-%m-%d')
    selected_games = games_by_date.get(selected_date_str_full, [])
    selected_games_all = games_by_date_all.get(selected_date_str_full, [])

    prev_month = selected_date.replace(day=1)
    if prev_month.month == 1:
        prev_month = prev_month.replace(year=prev_month.year - 1, month=12)
    else:
        prev_month = prev_month.replace(month=prev_month.month - 1)

    next_month = selected_date.replace(day=1)
    if next_month.month == 12:
        next_month = next_month.replace(year=next_month.year + 1, month=1)
    else:
        next_month = next_month.replace(month=next_month.month + 1)

    month_names_es = {
        1: 'Enero', 2: 'Febrero', 3: 'Marzo', 4: 'Abril',
        5: 'Mayo', 6: 'Junio', 7: 'Julio', 8: 'Agosto',
        9: 'Septiembre', 10: 'Octubre', 11: 'Noviembre', 12: 'Diciembre',
    }
    day_names_es = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb']

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_game_day': season.current_game_day,
        'total_game_days': Game.objects.filter(season=season).values('game_day').distinct().count(),
        'current_date': selected_date.strftime('%d/%m/%Y'),
        'year': year,
        'month': month,
        'month_name': month_names_es[month],
        'day_names': day_names_es,
        'month_days': month_days,
        'dates_by_day': dates_by_day,
        'games_by_date': games_by_date,
        'games_by_date_flags': games_by_date_flags,
        'games_by_date_json': json.dumps(games_by_date_flags),
        'selected_date': selected_date_str_full,
        'selected_games': selected_games,
        'selected_games_all': selected_games_all,
        'prev_month_url': f"?date={prev_month.strftime('%Y-%m-01')}",
        'next_month_url': f"?date={next_month.strftime('%Y-%m-01')}",
        'btn_text': btn_text,
        'season_phase': season.phase,
    }
    return render(request, 'core/calendar.html', context)


@require_POST
def reset_game(request):
    from django.core.management import call_command

    # Borrar todo en orden de dependencias
    Message.objects.all().delete()
    PlayerGameStats.objects.all().delete()
    GameAttendance.objects.all().delete()
    FinanceRecord.objects.all().delete()
    TeamSettings.objects.all().delete()
    Game.objects.all().delete()
    Season.objects.all().delete()
    Manager.objects.all().delete()
    Player.objects.all().delete()
    Team.objects.all().delete()

    request.session.flush()

    # Repoblar la base de datos
    call_command('poblar_db')

    return redirect('home')


def bracket(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')

    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    if season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            from datetime import date
            current_date = date(season.year_start, 10, 22)
    else:
        from datetime import date
        current_date = date(season.year_start, 10, 22)

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'season_phase': season.phase,
        'conferences': ['East', 'West'],
    }

    if season.phase == 'regular':
        return render(request, 'core/bracket.html', context)

    from .schedule_generator import _get_standings_for_conference

    bracket_data = {}

    if season.phase in ('playin', 'playoffs', 'finished'):
        playin_games = Game.objects.filter(season=season, game_type='playin').order_by('game_day')
        playin_by_label = {}
        for g in playin_games:
            if g.series_label not in playin_by_label:
                playin_by_label[g.series_label] = []
            playin_by_label[g.series_label].append(g)

        context['playin_games'] = playin_games
        context['playin_by_label'] = playin_by_label

    if season.phase in ('playoffs', 'finished'):
        playoff_games = Game.objects.filter(season=season, game_type='playoff').order_by('series_label', 'game_day')
        playoff_by_series = {}
        for g in playoff_games:
            if g.series_label not in playoff_by_series:
                playoff_by_series[g.series_label] = []
            playoff_by_series[g.series_label].append(g)

        context['playoff_games'] = playoff_games
        context['playoff_by_series'] = playoff_by_series
        context['finals_exist'] = 'playoff-r4-finals' in playoff_by_series

        round_labels = {
            'playoff-r1': 'Primera Ronda',
            'playoff-r2': 'Semifinales de Conferencia',
            'playoff-r3': 'Finales de Conferencia',
            'playoff-r4': 'Finales NBA',
        }
        context['round_labels'] = round_labels

        playoff_series_keys = {
            'east_r2_s1': 'playoff-r2-east-s1',
            'east_r2_s2': 'playoff-r2-east-s2',
            'west_r2_s1': 'playoff-r2-west-s1',
            'west_r2_s2': 'playoff-r2-west-s2',
            'east_r3_s1': 'playoff-r3-east-s1',
            'west_r3_s1': 'playoff-r3-west-s1',
        }
        for key, label in playoff_series_keys.items():
            context[key] = label in playoff_by_series

        # Build series matchup info: {series_label: {'top': Team, 'bottom': Team, 'top_wins': N, 'bottom_wins': N}}
        # "top" and "bottom" are determined by the series label (e.g., "1v8" → seed 1 is top, seed 8 is bottom)
        series_matchups = {}
        for label, games in playoff_by_series.items():
            if not games:
                continue
            # Extract team IDs from label: e.g., "playoff-r1-east-1v8"
            parts = label.split('-')
            matchup_part = parts[-1]  # "1v8", "4v5", "2v7", "3v6", "s1", "s2", "finals"
            first_game = games[0]

            # Use the two teams from the first game
            team_a = first_game.home_team
            team_b = first_game.away_team

            # Count wins per team across ALL games in the series
            team_a_wins = 0
            team_b_wins = 0
            for g in games:
                if g.is_played:
                    if g.home_score > g.away_score:
                        winner_id = g.home_team_id
                    else:
                        winner_id = g.away_team_id
                    if winner_id == team_a.pk:
                        team_a_wins += 1
                    elif winner_id == team_b.pk:
                        team_b_wins += 1

            series_matchups[label] = {
                'top': team_a,
                'bottom': team_b,
                'top_wins': team_a_wins,
                'bottom_wins': team_b_wins,
            }
        context['series_matchups'] = series_matchups

    return render(request, 'core/bracket.html', context)


def season_summary(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')

    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    if season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            from datetime import date
            current_date = date(season.year_start, 10, 22)
    else:
        from datetime import date
        current_date = date(season.year_start, 10, 22)

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    # Finals info
    finals_games = Game.objects.filter(season=season, game_type='playoff', series_label='playoff-r4-finals', is_played=True).order_by('game_day')

    champion = None
    finalist = None
    finals_result = None
    if finals_games.exists():
        first_game = finals_games[0]
        team1_wins = 0
        team2_wins = 0
        for g in finals_games:
            if g.home_score > g.away_score:
                winner_id = g.home_team_id
            else:
                winner_id = g.away_team_id
            if winner_id == first_game.home_team_id:
                team1_wins += 1
            else:
                team2_wins += 1
        if team1_wins >= 4:
            champion = first_game.home_team
            finalist = first_game.away_team
            finals_result = f"{team1_wins} - {team2_wins}"
        else:
            champion = first_game.away_team
            finalist = first_game.home_team
            finals_result = f"{team2_wins} - {team1_wins}"

    # Finals MVP: best player from the CHAMPION team only
    from django.db.models import Avg, Count
    from .models import FinalsPlayerStats
    finals_mvp = None
    if finals_games.exists() and champion:
        finals_mvp = (
            FinalsPlayerStats.objects
            .filter(game__in=finals_games, team=champion)
            .values('player', 'player__first_name', 'player__last_name', 'player__team__name')
            .annotate(
                avg_rating=Avg('rating'),
                games_played=Count('id'),
                avg_pts=Avg('points'),
                avg_reb=Avg('rebounds'),
                avg_ast=Avg('assists'),
            )
            .filter(games_played__gte=2)
            .order_by('-avg_rating')
            .first()
        )

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'season_phase': season.phase,
        'champion': champion,
        'finalist': finalist,
        'finals_result': finals_result,
        'finals_mvp': finals_mvp,
    }
    return render(request, 'core/season_summary.html', context)


def player_awards(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')

    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    if season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            from datetime import date
            current_date = date(season.year_start, 10, 22)
    else:
        from datetime import date
        current_date = date(season.year_start, 10, 22)

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)

    next_unplayed_game = Game.objects.filter(
        season=season,
        is_played=False,
    ).filter(
        Q(home_team=team) | Q(away_team=team)
    ).order_by('game_day').first()

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    from django.db.models import Avg, Count

    # MVP: best avg rating with 65+ games played
    mvp = (
        PlayerGameStats.objects
        .filter(game__season=season, game__game_type='regular')
        .values('player', 'player__first_name', 'player__last_name', 'player__position', 'player__team__name', 'player__is_rookie')
        .annotate(avg_rating=Avg('rating'), games_played=Count('id'), avg_pts=Avg('points'), avg_reb=Avg('rebounds'), avg_ast=Avg('assists'))
        .filter(games_played__gte=65)
        .order_by('-avg_rating')
        .first()
    )

    # Rookie of the Year: best avg rating with 65+ games and is_rookie=True
    rookie_of_year = (
        PlayerGameStats.objects
        .filter(game__season=season, game__game_type='regular', player__is_rookie=True)
        .values('player', 'player__first_name', 'player__last_name', 'player__position', 'player__team__name')
        .annotate(avg_rating=Avg('rating'), games_played=Count('id'), avg_pts=Avg('points'), avg_reb=Avg('rebounds'), avg_ast=Avg('assists'))
        .filter(games_played__gte=65)
        .order_by('-avg_rating')
        .first()
    )

    # Best All-Rookie team (top 5 rookies by avg rating, 65+ games)
    all_rookie = list(
        PlayerGameStats.objects
        .filter(game__season=season, game__game_type='regular', player__is_rookie=True)
        .values('player', 'player__first_name', 'player__last_name', 'player__position', 'player__team__name')
        .annotate(avg_rating=Avg('rating'), games_played=Count('id'), avg_pts=Avg('points'), avg_reb=Avg('rebounds'), avg_ast=Avg('assists'))
        .filter(games_played__gte=65)
        .order_by('-avg_rating')[:5]
    )

    # Best All-Star team: best avg rating per position (PG, SG, SF, PF, C), 65+ games
    positions = ['PG', 'SG', 'SF', 'PF', 'C']
    all_star = []
    for pos in positions:
        best = (
            PlayerGameStats.objects
            .filter(game__season=season, game__game_type='regular', player__position=pos)
            .values('player', 'player__first_name', 'player__last_name', 'player__position', 'player__team__name')
            .annotate(avg_rating=Avg('rating'), games_played=Count('id'), avg_pts=Avg('points'), avg_reb=Avg('rebounds'), avg_ast=Avg('assists'))
            .filter(games_played__gte=65)
            .order_by('-avg_rating')
            .first()
        )
        if best:
            all_star.append(best)

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'season_phase': season.phase,
        'mvp': mvp,
        'rookie_of_year': rookie_of_year,
        'all_star': all_star,
        'all_rookie': all_rookie,
    }
    return render(request, 'core/player_awards.html', context)


def _save_season_record(season):
    """Save palmarés record when a season finishes."""
    if SeasonRecord.objects.filter(season=season).exists():
        return

    finals_games = Game.objects.filter(season=season, game_type='playoff', series_label='playoff-r4-finals', is_played=True).order_by('game_day')
    champion = None
    finalist = None
    finals_result = ''
    if finals_games.exists():
        first_game = finals_games[0]
        team1_wins = 0
        team2_wins = 0
        for g in finals_games:
            if g.home_score > g.away_score:
                winner_id = g.home_team_id
            else:
                winner_id = g.away_team_id
            if winner_id == first_game.home_team_id:
                team1_wins += 1
            else:
                team2_wins += 1
        if team1_wins >= 4:
            champion = first_game.home_team
            finalist = first_game.away_team
            finals_result = f"{team1_wins}-{team2_wins}"
        else:
            champion = first_game.away_team
            finalist = first_game.home_team
            finals_result = f"{team2_wins}-{team1_wins}"

    # Finals MVP (best player from the CHAMPION team only)
    finals_mvp = None
    if finals_games.exists() and champion:
        finals_mvp = (
            FinalsPlayerStats.objects
            .filter(game__in=finals_games, team=champion)
            .values('player')
            .annotate(avg_rating=Avg('rating'), games_played=Count('id'))
            .filter(games_played__gte=2)
            .order_by('-avg_rating')
            .first()
        )
        if finals_mvp:
            finals_mvp = Player.objects.get(pk=finals_mvp['player'])

    # Season MVP
    mvp = (
        PlayerGameStats.objects
        .filter(game__season=season, game__game_type='regular')
        .values('player')
        .annotate(avg_rating=Avg('rating'), games_played=Count('id'))
        .filter(games_played__gte=65)
        .order_by('-avg_rating')
        .first()
    )
    season_mvp = None
    season_mvp_rating = None
    season_mvp_games = None
    if mvp:
        season_mvp = Player.objects.get(pk=mvp['player'])
        season_mvp_rating = mvp['avg_rating']
        season_mvp_games = mvp['games_played']

    # Rookie of the Year
    roy = (
        PlayerGameStats.objects
        .filter(game__season=season, game__game_type='regular', player__is_rookie=True)
        .values('player')
        .annotate(avg_rating=Avg('rating'), games_played=Count('id'))
        .filter(games_played__gte=65)
        .order_by('-avg_rating')
        .first()
    )
    rookie_of_year = None
    rookie_rating = None
    rookie_games = None
    if roy:
        rookie_of_year = Player.objects.get(pk=roy['player'])
        rookie_rating = roy['avg_rating']
        rookie_games = roy['games_played']

    # Best players by position (All-Star team)
    positions = ['PG', 'SG', 'SF', 'PF', 'C']
    all_star_players = {}
    for pos in positions:
        best = (
            PlayerGameStats.objects
            .filter(game__season=season, game__game_type='regular', player__position=pos)
            .values('player')
            .annotate(avg_rating=Avg('rating'), games_played=Count('id'))
            .filter(games_played__gte=65)
            .order_by('-avg_rating')
            .first()
        )
        if best:
            all_star_players[pos] = Player.objects.get(pk=best['player'])

    SeasonRecord.objects.create(
        season=season,
        champion=champion,
        finalist=finalist,
        finals_result=finals_result,
        finals_mvp=finals_mvp,
        season_mvp=season_mvp,
        season_mvp_rating=season_mvp_rating,
        season_mvp_games=season_mvp_games,
        rookie_of_year=rookie_of_year,
        rookie_rating=rookie_rating,
        rookie_games=rookie_games,
        all_star_pg=all_star_players.get('PG'),
        all_star_sg=all_star_players.get('SG'),
        all_star_sf=all_star_players.get('SF'),
        all_star_pf=all_star_players.get('PF'),
        all_star_c=all_star_players.get('C'),
    )


def palmares(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')

    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    if season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            current_date = date(season.year_start, 10, 22)
    else:
        current_date = date(season.year_start, 10, 22)

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)
    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    next_unplayed_game = Game.objects.filter(
        season=season, is_played=False,
    ).filter(Q(home_team=team) | Q(away_team=team)).order_by('game_day').first()

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    # Team palmares
    records = SeasonRecord.objects.select_related('season', 'champion', 'finalist', 'finals_mvp').order_by('-season__year_start')

    # Team championship counts
    team_champs = Team.objects.annotate(
        num_championships=Count('championships')
    ).filter(num_championships__gt=0).order_by('-num_championships')

    # Player palmares
    player_mvps = Player.objects.annotate(
        mvp_count=Count('season_mvps')
    ).filter(mvp_count__gt=0).order_by('-mvp_count')

    # All-Star appearances
    all_star_appearances = Player.objects.annotate(
        all_star_count=(
            Count('all_star_pg_seasons', distinct=True) +
            Count('all_star_sg_seasons', distinct=True) +
            Count('all_star_sf_seasons', distinct=True) +
            Count('all_star_pf_seasons', distinct=True) +
            Count('all_star_c_seasons', distinct=True)
        )
    ).filter(all_star_count__gt=0).order_by('-all_star_count')

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'season_phase': season.phase,
        'records': records,
        'team_champs': team_champs,
        'player_mvps': player_mvps,
        'all_star_appearances': all_star_appearances,
    }
    return render(request, 'core/palmares.html', context)


def end_season(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')

    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    if season.current_game_day > 0:
        last_played = Game.objects.filter(season=season, is_played=True).order_by('-game_day').first()
        if last_played:
            current_date = last_played.game_date
        else:
            current_date = date(season.year_start, 10, 22)
    else:
        current_date = date(season.year_start, 10, 22)

    next_day = season.current_game_day + 1
    next_day_games = Game.objects.filter(season=season, game_day=next_day, is_played=False)

    next_unplayed_game = Game.objects.filter(
        season=season, is_played=False,
    ).filter(Q(home_team=team) | Q(away_team=team)).order_by('game_day').first()

    next_day_my_games = next_day_games.filter(home_team=team) | next_day_games.filter(away_team=team)

    if next_day_my_games.exists():
        btn_text = 'DÍA DE PARTIDO'
    elif next_day_games.exists():
        btn_text = 'SIMULAR PARTIDOS'
    else:
        btn_text = 'AVANZAR'

    # Retiring players (40+ years old, not already retired)
    retiring = Player.objects.filter(age__gte=40, is_retired=False).order_by('-age')

    # Players with 1 year left on contract (only those with a team)
    expiring = Player.objects.filter(contract_years=1, team__isnull=False, age__lt=40).select_related('team').order_by('team_id', 'age')

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y') if current_date else '',
        'btn_text': btn_text,
        'season_phase': season.phase,
        'retiring': retiring,
        'expiring': expiring,
        'draft_year': season.year_end,
    }
    return render(request, 'core/end_season.html', context)


@require_POST
def end_season_draft(request):
    season = Season.get_active()
    if not season:
        return JsonResponse({'error': 'No active season'}, status=400)

    from .draft_generator import generate_draft_players
    draft_picks = generate_draft_players(season)

    data = []
    for pick in draft_picks:
        p = pick['player']
        data.append({
            'pick': pick['pick'],
            'team_name': pick['team'].name,
            'team_abbreviation': pick['team'].abbreviation,
            'team_logo': pick['team'].logo,
            'player_id': p.pk,
            'name': f'{p.first_name} {p.last_name}',
            'position': p.position,
            'age': p.age,
            'height': p.height_cm,
            'weight': p.weight_kg,
            'nationality': p.nationality,
            'overall': p.overall,
            'potential': p.potential,
            'speed': p.speed,
            'shooting': p.shooting,
            'three_point': p.three_point,
            'passing': p.passing,
            'ball_handling': p.ball_handling,
            'defense': p.defense,
            'rebounding': p.rebounding,
            'athleticism': p.athleticism,
            'iq': p.iq,
            'steals': p.steals,
            'blocks': p.blocks,
        })

    return JsonResponse(data, safe=False)


@require_POST
def end_season_renew(request, player_id):
    player = Player.objects.get(pk=player_id)

    age = player.age
    if age <= 25:
        years = 5
    elif age <= 28:
        years = 4
    elif age <= 32:
        years = 3
    elif age < 40:
        years = 2
    else:
        years = 1

    new_salary = int(player.salary * 1.05)
    new_salary = round(new_salary / 100000) * 100000
    if new_salary < player.salary:
        new_salary = player.salary

    player.contract_years = years
    player.salary = new_salary
    player.save()

    return redirect('end_season')


@require_POST
def end_season_renew_all(request):
    players = Player.objects.filter(contract_years=1, team__isnull=False, age__lt=40)
    for player in players:
        age = player.age
        if age <= 25:
            years = 5
        elif age <= 28:
            years = 4
        elif age <= 32:
            years = 3
        elif age < 40:
            years = 2
        else:
            years = 1
        
        new_salary = int(player.salary * 1.05)
        new_salary = round(new_salary / 100000) * 100000
        if new_salary < player.salary:
            new_salary = player.salary
        
        player.contract_years = years
        player.salary = new_salary
        player.save()
    
    return redirect('end_season')


def _build_standings_for_draft(season):
    """Get final standings sorted by win percentage (best first)."""
    teams = list(Team.objects.all())
    team_ids = {t.pk for t in teams}
    team_data = {}
    for t in teams:
        team_data[t.pk] = {'team_id': t.pk, 'team': t, 'wins': 0, 'losses': 0}

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
    return [r['team'] for r in rows]


def next_season(request):
    team_id = request.session.get('team_id')
    manager_name = request.session.get('manager_name')

    if not team_id or not manager_name:
        return redirect('home')

    try:
        team = Team.objects.get(pk=team_id)
    except Team.DoesNotExist:
        return redirect('home')

    season = Season.get_active()
    if not season:
        return redirect('home')

    current_date = date(season.year_end, 4, 15)
    manager = Manager.objects.filter(name=manager_name).first()

    game_mode = season.game_mode
    is_dismissed = request.session.get('is_dismissed', False)

    if game_mode == 'manager':
        available_teams = [team]
    else:
        standings = _build_standings_for_draft(season)
        bottom_10 = standings[-10:] if len(standings) >= 10 else standings
        
        if is_dismissed:
            bottom_10 = [t for t in bottom_10 if t.pk != team.pk]
            random_teams = random.sample(bottom_10, min(3, len(bottom_10)))
            available_teams = random_teams
        else:
            bottom_10 = [t for t in bottom_10 if t.pk != team.pk]
            random_teams = random.sample(bottom_10, min(3, len(bottom_10)))
            available_teams = [team] + random_teams

    selected_team_id = request.session.get('next_season_team_id')

    context = {
        'manager_name': manager_name,
        'team': team,
        'season_label': f"{season.year_start}-{season.year_end}",
        'current_date': current_date.strftime('%d/%m/%Y'),
        'btn_text': 'INICIAR NUEVA TEMPORADA',
        'season_phase': 'finished',
        'available_teams': available_teams,
        'selected_team_id': selected_team_id,
        'game_mode': game_mode,
        'is_dismissed': is_dismissed,
    }
    return render(request, 'core/next_season.html', context)


@require_POST
def next_season_select(request, team_id):
    request.session['next_season_team_id'] = team_id
    return JsonResponse({'success': True})


@require_POST
def next_season_start(request):
    manager_name = request.session.get('manager_name')
    new_team_id = request.session.get('next_season_team_id')

    if not manager_name or not new_team_id:
        return redirect('next_season')

    try:
        new_team = Team.objects.get(pk=new_team_id)
    except Team.DoesNotExist:
        return redirect('next_season')

    # 0. Aggregate PlayerGameStats into HistoricalPlayerStats before clearing
    from .models import HistoricalPlayerStats
    season_stats = (
        PlayerGameStats.objects
        .values('player', 'player__first_name', 'player__last_name', 'player__position', 'player__overall')
        .annotate(
            games=Count('id'),
            total_points=Sum('points'),
            total_rebounds=Sum('rebounds'),
            total_assists=Sum('assists'),
            total_steals=Sum('steals'),
            total_blocks=Sum('blocks'),
            total_turnovers=Sum('turnovers'),
            total_fgm=Sum('fgm'),
            total_fga=Sum('fga'),
            total_fg3m=Sum('fg3m'),
            total_fg3a=Sum('fg3a'),
            total_ftm=Sum('ftm'),
            total_fta=Sum('fta'),
            total_double_double=Sum('double_double'),
            total_triple_double=Sum('triple_double'),
        )
    )

    for stat in season_stats:
        player_id = stat['player']
        try:
            player = Player.objects.get(pk=player_id)
            team_name = player.team.name if player.team else ''
            team_abbr = player.team.abbreviation if player.team else ''
            team_logo = player.team.logo if player.team else ''
        except Player.DoesNotExist:
            team_name = ''
            team_abbr = ''
            team_logo = ''

        hist, created = HistoricalPlayerStats.objects.get_or_create(
            first_name=stat['player__first_name'],
            last_name=stat['player__last_name'],
            defaults={
                'position': stat['player__position'],
                'overall': stat['player__overall'],
                'team_name': team_name,
                'team_abbreviation': team_abbr,
                'team_logo': team_logo,
                'games': stat['games'],
                'total_points': stat['total_points'] or 0,
                'total_rebounds': stat['total_rebounds'] or 0,
                'total_assists': stat['total_assists'] or 0,
                'total_steals': stat['total_steals'] or 0,
                'total_blocks': stat['total_blocks'] or 0,
                'total_turnovers': stat['total_turnovers'] or 0,
                'total_fgm': stat['total_fgm'] or 0,
                'total_fga': stat['total_fga'] or 0,
                'total_fg3m': stat['total_fg3m'] or 0,
                'total_fg3a': stat['total_fg3a'] or 0,
                'total_ftm': stat['total_ftm'] or 0,
                'total_fta': stat['total_fta'] or 0,
                'total_double_doubles': stat['total_double_double'] or 0,
                'total_triple_doubles': stat['total_triple_double'] or 0,
            }
        )
        if not created:
            hist.games += stat['games']
            hist.total_points += stat['total_points'] or 0
            hist.total_rebounds += stat['total_rebounds'] or 0
            hist.total_assists += stat['total_assists'] or 0
            hist.total_steals += stat['total_steals'] or 0
            hist.total_blocks += stat['total_blocks'] or 0
            hist.total_turnovers += stat['total_turnovers'] or 0
            hist.total_fgm += stat['total_fgm'] or 0
            hist.total_fga += stat['total_fga'] or 0
            hist.total_fg3m += stat['total_fg3m'] or 0
            hist.total_fg3a += stat['total_fg3a'] or 0
            hist.total_ftm += stat['total_ftm'] or 0
            hist.total_fta += stat['total_fta'] or 0
            hist.total_double_doubles += stat['total_double_double'] or 0
            hist.total_triple_doubles += stat['total_triple_double'] or 0
            hist.overall = stat['player__overall']
            hist.team_name = team_name
            hist.team_abbreviation = team_abbr
            hist.team_logo = team_logo
            hist.save()

    # 1. Retire players (40+)
    Player.objects.filter(age__gte=40).update(is_retired=True)

    # 2-4. Age, attributes, contracts
    all_players = Player.objects.all()
    for p in all_players:
        p.age += 1

        if p.age < 32:
            p.overall = min(p.overall + 2, p.potential)
            p.speed = min(99, p.speed + 2)
            p.shooting = min(99, p.shooting + 2)
            p.three_point = min(99, p.three_point + 2)
            p.passing = min(99, p.passing + 2)
            p.ball_handling = min(99, p.ball_handling + 2)
            p.defense = min(99, p.defense + 2)
            p.rebounding = min(99, p.rebounding + 2)
            p.athleticism = min(99, p.athleticism + 2)
            p.iq = min(99, p.iq + 2)
            p.steals = min(99, p.steals + 2)
            p.blocks = min(99, p.blocks + 2)
        else:
            p.overall = max(0, p.overall - 2)
            p.speed = max(0, p.speed - 2)
            p.shooting = max(0, p.shooting - 2)
            p.three_point = max(0, p.three_point - 2)
            p.passing = max(0, p.passing - 2)
            p.ball_handling = max(0, p.ball_handling - 2)
            p.defense = max(0, p.defense - 2)
            p.rebounding = max(0, p.rebounding - 2)
            p.athleticism = max(0, p.athleticism - 2)
            p.iq = max(0, p.iq - 2)
            p.steals = max(0, p.steals - 2)
            p.blocks = max(0, p.blocks - 2)

        p.contract_years -= 1
        if p.contract_years <= 0:
            p.contract_years = 0
            p.team = None
        p.save()

    # Decrement sponsor and TV contract years
    for ts in TeamSettings.objects.all():
        if ts.sponsor and ts.sponsor_years_remaining > 0:
            ts.sponsor_years_remaining -= 1
            if ts.sponsor_years_remaining <= 0:
                ts.sponsor = None
                ts.sponsor_years_remaining = 0
        if ts.tv_channel and ts.tv_years_remaining > 0:
            ts.tv_years_remaining -= 1
            if ts.tv_years_remaining <= 0:
                ts.tv_channel = None
                ts.tv_years_remaining = 0
        ts.save()

    # Clear tables
    PlayerGameStats.objects.all().delete()
    FinalsPlayerStats.objects.all().delete()
    FinanceRecord.objects.all().delete()
    GameAttendance.objects.all().delete()
    Message.objects.all().delete()
    Game.objects.all().delete()

    # Fill rosters to 12 players for all teams except the user's team
    teams = Team.objects.all()
    for t in teams:
        if t.pk == new_team_id:
            continue
        roster_count = t.players.count()
        if roster_count >= 12:
            continue

        # Count players by position
        pos_counts = {}
        for pos in ['PG', 'SG', 'SF', 'PF', 'C']:
            pos_counts[pos] = t.players.filter(position=pos).count()

        # Get available free agents sorted by overall (best first)
        free_agents = list(Player.objects.filter(team__isnull=True, is_retired=False).order_by('-overall'))

        need = 12 - roster_count
        signed = 0

        # Prioritize positions with fewest players
        for _ in range(need):
            if not free_agents:
                break

            # Find the position with fewest players
            min_pos = min(pos_counts, key=pos_counts.get)

            # Find best free agent for that position
            signed_player = None
            for fa in free_agents:
                if fa.position == min_pos:
                    signed_player = fa
                    break

            # If no player for that position, take best available
            if not signed_player and free_agents:
                signed_player = free_agents[0]

            if signed_player:
                signed_player.team = t
                signed_player.contract_years = max(1, 4 - signed_player.age // 10)
                signed_player.save()
                free_agents.remove(signed_player)
                pos_counts[signed_player.position] += 1
                signed += 1

    # Deactivate old season
    old_season = Season.get_active()
    if old_season:
        old_season.is_active = False
        old_season.save()

    # Create new season
    new_year_start = old_season.year_start + 1 if old_season else 2026
    new_season = Season.objects.create(
        year_start=new_year_start,
        year_end=new_year_start + 1,
        is_active=True,
        current_game_day=0,
        game_mode=old_season.game_mode if old_season else 'manager',
        phase='regular',
    )

    # Generate new schedule
    from .schedule_generator import generate_schedule
    generate_schedule(new_season)

    # Select random sponsors and TV channels for the new season
    _select_random_contracts()

    # Increase salary cap and luxury tax by 5%
    ls = LeagueSettings.get_active()
    if ls:
        ls.salary_cap = int(ls.salary_cap * 1.05)
        ls.luxury_tax = int(ls.luxury_tax * 1.05)
        ls.apron = int(ls.apron * 1.05)
        ls.repeater_apron = int(ls.repeater_apron * 1.05)
        ls.mid_level = int(ls.mid_level * 1.05)
        ls.bi_annual = int(ls.bi_annual * 1.05)
        ls.minimum_salary = int(ls.minimum_salary * 1.05)
        ls.save()

    # Update manager
    manager = Manager.objects.filter(name=manager_name).first()
    if manager:
        manager.current_date = date(new_year_start, 10, 22)
        manager.team = new_team
        if request.session.get('is_dismissed'):
            manager.trust = 50
            manager.morale = 50
            manager.pressure = 50
        manager.save()

    # Update session
    request.session['team_id'] = new_team_id
    request.session.pop('next_season_team_id', None)
    request.session.pop('is_dismissed', None)
    request.session.pop('dismissal_reason', None)
    request.session.pop('dismissal_trust', None)
    request.session.pop('dismissal_morale', None)
    request.session.pop('dismissal_pressure', None)

    return redirect('dashboard')


def editor(request):
    teams = Team.objects.all().order_by('name')
    return render(request, 'core/editor.html', {
        'teams': teams,
    })


@require_POST
def editor_update_team(request, team_id):
    team = Team.objects.get(pk=team_id)

    team.name = request.POST.get('name', team.name)
    team.abbreviation = request.POST.get('abbreviation', team.abbreviation)
    team.city = request.POST.get('city', team.city)
    team.conference = request.POST.get('conference', team.conference)
    team.division = request.POST.get('division', team.division)
    team.arena = request.POST.get('arena', team.arena)
    team.capacity = int(request.POST.get('capacity', team.capacity))
    team.owner = request.POST.get('owner', team.owner)
    team.attack = int(request.POST.get('attack', team.attack))
    team.defense = int(request.POST.get('defense', team.defense))
    team.overall = int(request.POST.get('overall', team.overall))
    team.budget = int(request.POST.get('budget', team.budget))
    team.reputation = int(request.POST.get('reputation', team.reputation))
    team.facilities = int(request.POST.get('facilities', team.facilities))
    team.logo = request.POST.get('logo', team.logo)
    team.jersey_home = request.POST.get('jersey_home', team.jersey_home)
    team.jersey_away = request.POST.get('jersey_away', team.jersey_away)
    team.arena_image = request.POST.get('arena_image', team.arena_image)
    team.save()

    return redirect(f"{request.META.get('HTTP_REFERER', '/editor/')}")


@require_POST
def editor_update_player(request, player_id):
    player = Player.objects.get(pk=player_id)

    player.first_name = request.POST.get('first_name', player.first_name)
    player.last_name = request.POST.get('last_name', player.last_name)
    player.position = request.POST.get('position', player.position)
    player.age = int(request.POST.get('age', player.age))
    player.nationality = request.POST.get('nationality', player.nationality)
    player.height_cm = int(request.POST.get('height_cm', player.height_cm))
    player.weight_kg = int(request.POST.get('weight_kg', player.weight_kg))
    player.overall = int(request.POST.get('overall', player.overall))
    player.potential = int(request.POST.get('potential', player.potential))
    player.speed = int(request.POST.get('speed', player.speed))
    player.shooting = int(request.POST.get('shooting', player.shooting))
    player.three_point = int(request.POST.get('three_point', player.three_point))
    player.passing = int(request.POST.get('passing', player.passing))
    player.ball_handling = int(request.POST.get('ball_handling', player.ball_handling))
    player.defense = int(request.POST.get('defense', player.defense))
    player.rebounding = int(request.POST.get('rebounding', player.rebounding))
    player.athleticism = int(request.POST.get('athleticism', player.athleticism))
    player.iq = int(request.POST.get('iq', player.iq))
    player.steals = int(request.POST.get('steals', player.steals))
    player.blocks = int(request.POST.get('blocks', player.blocks))
    player.injury_days = int(request.POST.get('injury_days', player.injury_days))
    player.injury_type = request.POST.get('injury_type', player.injury_type)
    player.salary = int(request.POST.get('salary', player.salary))
    player.contract_years = int(request.POST.get('contract_years', player.contract_years))

    team_id = request.POST.get('team')
    if team_id == '':
        player.team = None
    else:
        player.team = Team.objects.get(pk=team_id)

    player.save()

    return redirect(f"{request.META.get('HTTP_REFERER', '/editor/')}")


def api_players_by_team(request, team_id):
    players = Player.objects.filter(team_id=team_id).order_by('-overall')
    data = []
    for p in players:
        data.append({
            'id': p.pk,
            'first_name': p.first_name,
            'last_name': p.last_name,
            'position': p.position,
            'age': p.age,
            'nationality': p.nationality,
            'height_cm': p.height_cm,
            'weight_kg': p.weight_kg,
            'overall': p.overall,
            'potential': p.potential,
            'speed': p.speed,
            'shooting': p.shooting,
            'three_point': p.three_point,
            'passing': p.passing,
            'ball_handling': p.ball_handling,
            'defense': p.defense,
            'rebounding': p.rebounding,
            'athleticism': p.athleticism,
            'iq': p.iq,
            'steals': p.steals,
            'blocks': p.blocks,
            'injury_days': p.injury_days,
            'injury_type': p.injury_type,
            'salary': p.salary,
            'contract_years': p.contract_years,
            'team': p.team_id,
        })
    return JsonResponse(data, safe=False)
