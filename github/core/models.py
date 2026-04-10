from django.db import models

class LeagueSettings(models.Model):
    """Configuración salarial de la liga (una sola fila activa)."""
    salary_cap        = models.BigIntegerField(default=155_000_000)
    luxury_tax        = models.BigIntegerField(default=189_000_000)
    apron             = models.BigIntegerField(default=199_000_000)
    repeater_apron    = models.BigIntegerField(default=209_000_000)
    mid_level         = models.BigIntegerField(default=14_000_000)
    bi_annual         = models.BigIntegerField(default=5_000_000)
    minimum_salary    = models.BigIntegerField(default=2_000_000)
    is_active         = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'League Settings'
        verbose_name_plural = 'League Settings'

    @classmethod
    def get_active(cls):
        settings = cls.objects.filter(is_active=True).first()
        if not settings:
            settings = cls.objects.create(is_active=True)
        return settings

    def __str__(self):
        return f'Salary Cap: ${self.salary_cap / 1_000_000_000:.1f}B'


class Team(models.Model):

    CONFERENCE_CHOICES = [
        ('East', 'Eastern Conference'),
        ('West', 'Western Conference'),
    ]
    DIVISION_CHOICES = [
        ('Atlantic',  'Atlantic'),
        ('Central',   'Central'),
        ('Southeast', 'Southeast'),
        ('Northwest', 'Northwest'),
        ('Pacific',   'Pacific'),
        ('Southwest', 'Southwest'),
    ]

    # Identidad
    name         = models.CharField(max_length=100)        # "Los Angeles Lakers"
    abbreviation = models.CharField(max_length=5)          # "LAL"
    city         = models.CharField(max_length=100)        # "Los Angeles"
    conference   = models.CharField(max_length=10, choices=CONFERENCE_CHOICES)
    division     = models.CharField(max_length=20, choices=DIVISION_CHOICES)

    # Instalaciones
    arena        = models.CharField(max_length=100)
    capacity     = models.IntegerField()
    owner        = models.CharField(max_length=100)

    # Mejoras del pabellón
    arena_renovation_end_day = models.IntegerField(default=0)
    arena_renovation_type = models.CharField(max_length=50, blank=True, default='')
    arena_renovation_count = models.IntegerField(default=0)
    arena_renovation_cost = models.BigIntegerField(default=0)

    # Atributos de juego (0-99)
    attack       = models.IntegerField(default=70)
    defense      = models.IntegerField(default=70)
    overall      = models.IntegerField(default=70)

    # Recursos
    budget       = models.BigIntegerField(default=100_000_000)   # en dólares
    reputation   = models.IntegerField(default=3)                # 1-5 estrellas
    facilities   = models.IntegerField(default=3)                # 1-5 estrellas

    # Imágenes (rutas relativas a /static/)
    logo         = models.CharField(max_length=200, blank=True)    # "logos/lakers.png"
    jersey_home  = models.CharField(max_length=200, blank=True)    # "jerseys/lakers_home.png"
    jersey_away  = models.CharField(max_length=200, blank=True)    # "jerseys/lakers_away.png"
    arena_image  = models.CharField(max_length=200, blank=True)    # "arenas/lakers.png"

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name

    @property
    def is_under_renovation(self):
        return self.arena_renovation_end_day > 0

    @property
    def renovation_days_left(self):
        if self.arena_renovation_end_day <= 0:
            return 0
        season = Season.get_active()
        if not season:
            return 0
        current_day = season.current_game_day
        return max(0, self.arena_renovation_end_day - current_day)

    @property
    def effective_capacity(self):
        return self.capacity

    @property
    def arena_level(self):
        return self.facilities

    @property
    def arena_tier(self):
        tiers = {
            1: ('Básico', '#8B7355'),
            2: ('Estándar', '#A0A0A0'),
            3: ('Premium', '#4A80F0'),
            4: ('Élite', '#D4A017'),
            5: ('Legendario', '#FFD700'),
        }
        return tiers.get(self.facilities, ('Básico', '#8B7355'))

    RENOVATION_TYPES = {
        'general_seats': {
            'name': 'Ampliar Grada General',
            'icon': '🏟️',
            'desc': 'Aumenta la capacidad de la grada general',
            'capacity_bonus': 3000,
            'cost': 10_000_000,
            'duration_weeks': 3,
        },
        'tribune': {
            'name': 'Ampliar Tribuna',
            'icon': '👑',
            'desc': 'Ampliación de la tribuna principal',
            'capacity_bonus': 2000,
            'cost': 20_000_000,
            'duration_weeks': 5,
        },
        'vip_seats': {
            'name': 'Ampliar Grada VIP',
            'icon': '💎',
            'desc': 'Nuevos palcos y zona VIP premium',
            'capacity_bonus': 1000,
            'cost': 35_000_000,
            'duration_weeks': 8,
        },
    }

    def get_renovation_info(self, upgrade_type):
        return self.RENOVATION_TYPES.get(upgrade_type)

    def get_renovation_cost(self, upgrade_type):
        info = self.get_renovation_info(upgrade_type)
        return info['cost'] if info else 0

    def get_renovation_duration(self, upgrade_type):
        info = self.get_renovation_info(upgrade_type)
        return info['duration_weeks'] * 7 if info else 7

    def get_renovation_capacity_bonus(self, upgrade_type):
        info = self.get_renovation_info(upgrade_type)
        return info['capacity_bonus'] if info else 0

    def apply_renovation(self, upgrade_type):
        """Apply renovation effects: add capacity and potentially increase facilities level."""
        info = self.get_renovation_info(upgrade_type)
        if not info:
            return
        self.capacity += info['capacity_bonus']
        self.arena_renovation_count += 1
        # Increase facilities level every 3 renovations, max 5
        if self.arena_renovation_count >= 3 and self.facilities < 5:
            self.facilities += 1
            self.arena_renovation_count = 0

    def payroll(self):
        """Sum of all player salaries."""
        from django.db.models import Sum
        result = self.players.aggregate(total=Sum('salary'))
        return result['total'] or 0

    def salary_margin(self):
        """Cap space remaining."""
        cap = LeagueSettings.get_active().salary_cap
        return cap - self.payroll()

    def luxury_tax_status(self):
        """Returns tax bracket info."""
        settings = LeagueSettings.get_active()
        payroll = self.payroll()
        if payroll <= settings.salary_cap:
            return {'status': 'under_cap', 'label': 'Bajo el cap', 'color': 'green'}
        elif payroll <= settings.luxury_tax:
            return {'status': 'over_cap', 'label': 'Sobre el cap', 'color': 'blue'}
        elif payroll <= settings.apron:
            return {'status': 'luxury_tax', 'label': 'Impuesto de lujo', 'color': 'gold'}
        elif payroll <= settings.repeater_apron:
            return {'status': 'apron', 'label': 'Primer apron', 'color': 'orange'}
        else:
            return {'status': 'repeater', 'label': 'Repeater apron', 'color': 'red'}


class Manager(models.Model):
    name         = models.CharField(max_length=100)
    team         = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='managers')
    game_mode    = models.CharField(max_length=20, default='manager')
    current_date = models.DateField(null=True, blank=True)
    trust        = models.IntegerField(default=50)
    morale       = models.IntegerField(default=50)
    pressure     = models.IntegerField(default=50)
    created_at   = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.team})"


class SeasonRecord(models.Model):
    """Palmarés de una temporada."""
    season = models.OneToOneField('Season', on_delete=models.CASCADE, related_name='record')
    champion = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, related_name='championships')
    finalist = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, related_name='finalist_appearances')
    finals_result = models.CharField(max_length=10, default='')
    finals_mvp = models.ForeignKey('Player', on_delete=models.SET_NULL, null=True, related_name='finals_mvps')
    season_mvp = models.ForeignKey('Player', on_delete=models.SET_NULL, null=True, related_name='season_mvps')
    season_mvp_rating = models.FloatField(null=True, blank=True)
    season_mvp_games = models.IntegerField(null=True, blank=True)
    rookie_of_year = models.ForeignKey('Player', on_delete=models.SET_NULL, null=True, related_name='rookie_awards')
    rookie_rating = models.FloatField(null=True, blank=True)
    rookie_games = models.IntegerField(null=True, blank=True)
    all_star_pg = models.ForeignKey('Player', on_delete=models.SET_NULL, null=True, related_name='all_star_pg_seasons')
    all_star_sg = models.ForeignKey('Player', on_delete=models.SET_NULL, null=True, related_name='all_star_sg_seasons')
    all_star_sf = models.ForeignKey('Player', on_delete=models.SET_NULL, null=True, related_name='all_star_sf_seasons')
    all_star_pf = models.ForeignKey('Player', on_delete=models.SET_NULL, null=True, related_name='all_star_pf_seasons')
    all_star_c = models.ForeignKey('Player', on_delete=models.SET_NULL, null=True, related_name='all_star_c_seasons')

    class Meta:
        ordering = ['-season__year_start']

    def __str__(self):
        champ = self.champion.name if self.champion else 'N/A'
        return f"{self.season.year_start}-{self.season.year_end}: {champ}"


class Season(models.Model):
    PHASE_CHOICES = [
        ('regular', 'Regular Season'),
        ('playin', 'Play-In'),
        ('playoffs', 'Playoffs'),
        ('finished', 'Temporada Finalizada'),
    ]

    year_start       = models.IntegerField()
    year_end         = models.IntegerField()
    is_active        = models.BooleanField(default=False)
    current_game_day = models.IntegerField(default=0)
    generated        = models.BooleanField(default=False)
    last_payroll_month = models.IntegerField(null=True, blank=True)
    game_mode        = models.CharField(max_length=20, default='manager')
    phase            = models.CharField(max_length=10, choices=PHASE_CHOICES, default='regular')

    class Meta:
        ordering = ['-year_start']

    def __str__(self):
        return f"Temporada {self.year_start}-{self.year_end}"

    @classmethod
    def get_active(cls):
        return cls.objects.filter(is_active=True).first()


class Game(models.Model):
    GAME_TYPE_CHOICES = [
        ('regular', 'Regular Season'),
        ('playin', 'Play-In'),
        ('playoff', 'Playoffs'),
    ]

    season      = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='games')
    game_day    = models.IntegerField()
    game_date   = models.DateField()
    home_team   = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='home_games')
    away_team   = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='away_games')
    home_score  = models.IntegerField(null=True, blank=True)
    away_score  = models.IntegerField(null=True, blank=True)
    is_played   = models.BooleanField(default=False)
    game_type   = models.CharField(max_length=10, choices=GAME_TYPE_CHOICES, default='regular')
    series_label = models.CharField(max_length=30, blank=True, default='')

    q1_home     = models.IntegerField(null=True, blank=True)
    q1_away     = models.IntegerField(null=True, blank=True)
    q2_home     = models.IntegerField(null=True, blank=True)
    q2_away     = models.IntegerField(null=True, blank=True)
    q3_home     = models.IntegerField(null=True, blank=True)
    q3_away     = models.IntegerField(null=True, blank=True)
    q4_home     = models.IntegerField(null=True, blank=True)
    q4_away     = models.IntegerField(null=True, blank=True)

    class Meta:
        ordering = ['season', 'game_day', 'pk']
        unique_together = ['season', 'home_team', 'away_team', 'game_day']

    def __str__(self):
        type_label = dict(self.GAME_TYPE_CHOICES).get(self.game_type, '')
        return f"[{type_label}] Day {self.game_day}: {self.away_team} @ {self.home_team}"

    @property
    def winner(self):
        if not self.is_played:
            return None
        if self.home_score >= self.away_score:
            return self.home_team
        return self.away_team

    @property
    def loser(self):
        if not self.is_played:
            return None
        if self.home_score >= self.away_score:
            return self.away_team
        return self.home_team


class Player(models.Model):

    POSITION_CHOICES = [
        ('PG', 'Point Guard'),
        ('SG', 'Shooting Guard'),
        ('SF', 'Small Forward'),
        ('PF', 'Power Forward'),
        ('C',  'Center'),
    ]

    team         = models.ForeignKey(Team, on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name='players')
    first_name   = models.CharField(max_length=100)
    last_name    = models.CharField(max_length=100)
    position     = models.CharField(max_length=2, choices=POSITION_CHOICES)
    age          = models.IntegerField()
    nationality  = models.CharField(max_length=100, default='USA')

    # Atributos físicos
    height_cm    = models.IntegerField()
    weight_kg    = models.IntegerField()

    # Atributos de juego (0-99)
    overall      = models.IntegerField(default=70)
    potential    = models.IntegerField(default=70)
    speed        = models.IntegerField(default=70)
    shooting     = models.IntegerField(default=70)
    three_point  = models.IntegerField(default=70)
    passing      = models.IntegerField(default=70)
    ball_handling= models.IntegerField(default=70)
    defense      = models.IntegerField(default=70)
    rebounding   = models.IntegerField(default=70)
    athleticism  = models.IntegerField(default=70)
    iq           = models.IntegerField(default=70)
    steals       = models.IntegerField(default=70)
    blocks       = models.IntegerField(default=70)

    # Lesiones
    injury_days  = models.IntegerField(default=0)
    injury_type  = models.CharField(max_length=50, blank=True, default='')

    # Contrato
    salary       = models.IntegerField(default=5_000_000)   # dólares/año
    contract_years = models.IntegerField(default=2)

    # Rookie
    is_rookie    = models.BooleanField(default=False)

    # Retired
    is_retired   = models.BooleanField(default=False)

    class Meta:
        ordering = ['-overall']

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.position})"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"


class Message(models.Model):
    manager     = models.ForeignKey(Manager, on_delete=models.CASCADE, related_name='messages')
    title       = models.CharField(max_length=200)
    body        = models.TextField()
    game_day    = models.IntegerField(default=0)
    game_date   = models.DateField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    is_read     = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.manager.name}"


class HistoricalPlayerStats(models.Model):
    """Estadísticas históricas de carrera de jugadores (retirados y activos)."""
    first_name     = models.CharField(max_length=100)
    last_name      = models.CharField(max_length=100)
    position       = models.CharField(max_length=2)
    overall        = models.IntegerField(default=70)
    team_name      = models.CharField(max_length=100, default='')
    team_abbreviation = models.CharField(max_length=5, default='')
    team_logo      = models.CharField(max_length=200, default='', blank=True)

    games          = models.IntegerField(default=0)
    total_points   = models.IntegerField(default=0)
    total_rebounds = models.IntegerField(default=0)
    total_assists  = models.IntegerField(default=0)
    total_steals   = models.IntegerField(default=0)
    total_blocks   = models.IntegerField(default=0)
    total_turnovers= models.IntegerField(default=0)
    total_fgm      = models.IntegerField(default=0)
    total_fga      = models.IntegerField(default=0)
    total_fg3m     = models.IntegerField(default=0)
    total_fg3a     = models.IntegerField(default=0)
    total_ftm      = models.IntegerField(default=0)
    total_fta      = models.IntegerField(default=0)
    total_double_doubles = models.IntegerField(default=0)
    total_triple_doubles = models.IntegerField(default=0)

    class Meta:
        ordering = ['-total_points']
        unique_together = ['first_name', 'last_name']

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    @property
    def ppg(self):
        return round(self.total_points / self.games, 1) if self.games > 0 else 0

    @property
    def rpg(self):
        return round(self.total_rebounds / self.games, 1) if self.games > 0 else 0

    @property
    def apg(self):
        return round(self.total_assists / self.games, 1) if self.games > 0 else 0

    @property
    def spg(self):
        return round(self.total_steals / self.games, 1) if self.games > 0 else 0

    @property
    def bpg(self):
        return round(self.total_blocks / self.games, 1) if self.games > 0 else 0

    @property
    def fg_pct(self):
        return round(self.total_fgm / self.total_fga * 100, 1) if self.total_fga > 0 else 0

    @property
    def fg3_pct(self):
        return round(self.total_fg3m / self.total_fg3a * 100, 1) if self.total_fg3a > 0 else 0

    @property
    def ft_pct(self):
        return round(self.total_ftm / self.total_fta * 100, 1) if self.total_fta > 0 else 0

    def __str__(self):
        return f"{self.full_name} - {self.total_points} pts"


class PlayerGameStats(models.Model):
    game        = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='player_stats')
    player      = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='game_stats')
    team        = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='player_game_stats')

    minutes     = models.FloatField(default=0.0)
    points      = models.IntegerField(default=0)
    fgm         = models.IntegerField(default=0)
    fga         = models.IntegerField(default=0)
    fg3m        = models.IntegerField(default=0)
    fg3a        = models.IntegerField(default=0)
    ftm         = models.IntegerField(default=0)
    fta         = models.IntegerField(default=0)
    oreb        = models.IntegerField(default=0)
    dreb        = models.IntegerField(default=0)
    rebounds    = models.IntegerField(default=0)
    assists     = models.IntegerField(default=0)
    steals      = models.IntegerField(default=0)
    blocks      = models.IntegerField(default=0)
    turnovers   = models.IntegerField(default=0)
    pf          = models.IntegerField(default=0)
    rating      = models.IntegerField(default=0)
    double_double = models.IntegerField(default=0)
    triple_double  = models.IntegerField(default=0)

    class Meta:
        ordering = ['-points']
        unique_together = ['game', 'player']

    def __str__(self):
        return f"{self.player} - {self.points}pts en {self.minutes:.1f}min"


class FinanceRecord(models.Model):
    """Registro financiero individual (ingreso o gasto)."""
    TYPE_TICKET = 1
    TYPE_SUBSCRIPTION = 2
    TYPE_SPONSORSHIP = 3
    TYPE_TV = 4
    TYPE_RENOVATION = 5
    TYPE_DISMISSAL = 6
    TYPE_SALARIES = 7

    TYPE_CHOICES = [
        (TYPE_TICKET, 'Taquilla'),
        (TYPE_SUBSCRIPTION, 'Abonos'),
        (TYPE_SPONSORSHIP, 'Patrocinios'),
        (TYPE_TV, 'Televisión'),
        (TYPE_RENOVATION, 'Remodelación'),
        (TYPE_DISMISSAL, 'Despido'),
        (TYPE_SALARIES, 'Sueldos'),
    ]

    team          = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='finance_records')
    season        = models.ForeignKey(Season, on_delete=models.CASCADE, related_name='finance_records')
    record_type   = models.IntegerField(choices=TYPE_CHOICES)
    game_day      = models.IntegerField(default=0)
    amount        = models.BigIntegerField(default=0)

    class Meta:
        ordering = ['season', 'game_day', 'record_type']

    @property
    def is_income(self):
        return self.record_type <= self.TYPE_TV

    @property
    def is_expense(self):
        return self.record_type >= self.TYPE_RENOVATION

    @property
    def type_label(self):
        return dict(self.TYPE_CHOICES).get(self.record_type, '')

    def __str__(self):
        sign = '+' if self.is_income else '-'
        return f"{self.team} {sign}${self.amount:,} ({self.type_label})"


class GameAttendance(models.Model):
    """Asistencia a un partido."""
    game        = models.OneToOneField(Game, on_delete=models.CASCADE, related_name='attendance')
    attendance  = models.IntegerField(default=0)
    ticket_price = models.IntegerField(default=0)
    revenue     = models.BigIntegerField(default=0)

    def __str__(self):
        return f"{self.game} - {self.attendance} asistentes"


class Sponsor(models.Model):
    """Patrocinadores disponibles para los equipos."""
    name = models.CharField(max_length=100)
    logo = models.CharField(max_length=100)
    initial_income = models.IntegerField()
    home_game_income = models.IntegerField()
    contract_years = models.IntegerField(default=1)
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TvChannel(models.Model):
    """Cadenas de televisión disponibles para los equipos."""
    name = models.CharField(max_length=100)
    logo = models.CharField(max_length=100)
    initial_income = models.IntegerField()
    home_game_income = models.IntegerField()
    contract_years = models.IntegerField(default=1)
    is_active = models.BooleanField(default=False)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class TeamSettings(models.Model):
    """Configuración financiera del equipo."""
    team            = models.OneToOneField(Team, on_delete=models.CASCADE, related_name='fin_settings')
    ticket_price    = models.IntegerField(default=50)
    subscription_price = models.IntegerField(default=2000)
    sponsor = models.ForeignKey(Sponsor, on_delete=models.SET_NULL, null=True, blank=True)
    sponsor_years_remaining = models.IntegerField(default=0)
    tv_channel = models.ForeignKey(TvChannel, on_delete=models.SET_NULL, null=True, blank=True)
    tv_years_remaining = models.IntegerField(default=0)

    def __str__(self):
        return f"Configuración de {self.team.name}"


class FinalsPlayerStats(models.Model):
    """Estadísticas de jugadores en las Finales NBA."""
    game        = models.ForeignKey(Game, on_delete=models.CASCADE, related_name='finals_stats')
    player      = models.ForeignKey(Player, on_delete=models.CASCADE, related_name='finals_stats')
    team        = models.ForeignKey(Team, on_delete=models.CASCADE, related_name='finals_stats')

    minutes     = models.FloatField(default=0.0)
    points      = models.IntegerField(default=0)
    fgm         = models.IntegerField(default=0)
    fga         = models.IntegerField(default=0)
    fg3m        = models.IntegerField(default=0)
    fg3a        = models.IntegerField(default=0)
    ftm         = models.IntegerField(default=0)
    fta         = models.IntegerField(default=0)
    oreb        = models.IntegerField(default=0)
    dreb        = models.IntegerField(default=0)
    rebounds    = models.IntegerField(default=0)
    assists     = models.IntegerField(default=0)
    steals      = models.IntegerField(default=0)
    blocks      = models.IntegerField(default=0)
    turnovers   = models.IntegerField(default=0)
    pf          = models.IntegerField(default=0)
    rating      = models.IntegerField(default=0)
    double_double = models.IntegerField(default=0)
    triple_double  = models.IntegerField(default=0)

    class Meta:
        ordering = ['-points']
        unique_together = ['game', 'player']

    def __str__(self):
        return f"{self.player} - {self.points}pts en {self.minutes:.1f}min (Finals)"


class HistoricalRecord(models.Model):
    """NBA all-time single-game records."""
    
    STAT_TYPE_CHOICES = [
        ('points', 'Puntos'),
        ('rebounds', 'Rebotes'),
        ('assists', 'Asistencias'),
        ('steals', 'Robos'),
        ('blocks', 'Tapones'),
        ('fgm', 'Tiros de Campo'),
        ('fg3m', 'Triples'),
        ('ftm', 'Tiros Libres'),
        ('turnovers', 'Pérdidas'),
    ]
    
    stat_type = models.CharField(max_length=20, choices=STAT_TYPE_CHOICES, unique=True)
    player_name = models.CharField(max_length=200)
    value = models.IntegerField()
    game_date = models.DateField()
    team_abbreviation = models.CharField(max_length=3)
    
    class Meta:
        ordering = ['stat_type']
    
    def __str__(self):
        return f"HIST: {self.get_stat_type_display()}: {self.value} by {self.player_name}"


class TeamRecord(models.Model):
    """Best single-game records for each team (all-time)."""
    
    STAT_TYPE_CHOICES = [
        ('points', 'Puntos'),
        ('rebounds', 'Rebotes'),
        ('assists', 'Asistencias'),
        ('steals', 'Robos'),
        ('blocks', 'Tapones'),
        ('fgm', 'Tiros de Campo'),
        ('fg3m', 'Triples'),
        ('ftm', 'Tiros Libres'),
        ('turnovers', 'Pérdidas'),
    ]
    
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='team_records')
    stat_type = models.CharField(max_length=20, choices=STAT_TYPE_CHOICES)
    player_name = models.CharField(max_length=200)
    value = models.IntegerField()
    game_date = models.DateField()
    
    class Meta:
        ordering = ['stat_type']
        unique_together = ['team', 'stat_type']
    
    def __str__(self):
        return f"{self.team.abbreviation}: {self.get_stat_type_display()}: {self.value} by {self.player_name}"


class SeasonGameRecord(models.Model):
    """Best single-game records for each team in the current season."""
    
    STAT_TYPE_CHOICES = [
        ('points', 'Puntos'),
        ('rebounds', 'Rebotes'),
        ('assists', 'Asistencias'),
        ('steals', 'Robos'),
        ('blocks', 'Tapones'),
        ('fgm', 'Tiros de Campo'),
        ('fg3m', 'Triples'),
        ('ftm', 'Tiros Libres'),
        ('turnovers', 'Pérdidas'),
    ]
    
    team = models.ForeignKey('Team', on_delete=models.CASCADE, related_name='season_game_records')
    season = models.ForeignKey('Season', on_delete=models.CASCADE, related_name='season_game_records')
    stat_type = models.CharField(max_length=20, choices=STAT_TYPE_CHOICES)
    player_name = models.CharField(max_length=200)
    value = models.IntegerField()
    game_date = models.DateField()
    
    class Meta:
        ordering = ['stat_type']
        unique_together = ['team', 'season', 'stat_type']
    
    def __str__(self):
        return f"{self.team.abbreviation} S{self.season.year_start}: {self.get_stat_type_display()}: {self.value} by {self.player_name}"