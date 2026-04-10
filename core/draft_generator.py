import random
from datetime import date
from .models import Player, Team, Season, Game


FIRST_NAMES = [
    # English (470)
    "James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph",
    "Thomas", "Charles", "Christopher", "Daniel", "Matthew", "Anthony", "Mark",
    "Donald", "Steven", "Paul", "Andrew", "Joshua", "Kenneth", "Kevin", "Brian",
    "George", "Timothy", "Ronald", "Edward", "Jason", "Jeffrey", "Ryan",
    "Jacob", "Gary", "Nicholas", "Eric", "Jonathan", "Stephen", "Larry",
    "Justin", "Scott", "Brandon", "Benjamin", "Samuel", "Raymond", "Gregory",
    "Frank", "Alexander", "Patrick", "Jack", "Dennis", "Jerry", "Tyler",
    "Aaron", "Adam", "Nathan", "Henry", "Zachary", "Douglas", "Peter",
    "Kyle", "Noah", "Ethan", "Jeremy", "Walter", "Christian", "Keith",
    "Roger", "Terry", "Austin", "Sean", "Gerald", "Carl", "Harold", "Dylan",
    "Arthur", "Lawrence", "Jordan", "Jesse", "Bryan", "Billy", "Bruce",
    "Gabriel", "Joe", "Logan", "Albert", "Willie", "Alan", "Wayne",
    "Elijah", "Randy", "Mason", "Vincent", "Liam", "Owen", "Lucas",
    "Isaac", "Hunter", "Caleb", "Connor", "Eli", "Isaiah", "Evan",
    "Chase", "Cameron", "Ian", "Cole", "Adrian", "Carson", "Gavin",
    "Wyatt", "Xavier", "Blake", "Brody", "Colton", "Caden", "Aiden",
    "Brayden", "Landon", "Parker", "Jaxon", "Grayson", "Levi", "Lincoln",
    "Oliver", "Sebastian", "Mateo", "Jackson", "Aidan", "Leon", "Nolan",
    "Dominic", "Hudson", "Cooper", "Tristan", "Jace", "Bryson", "Sawyer",
    "Easton", "Ryder", "Asher", "Declan", "Finn", "Emmett", "Grant",
    "Reid", "Colin", "Miles", "Spencer", "Luke", "Travis", "Tanner",
    "Cody", "Derek", "Dustin", "Bradley", "Mitchell", "Marcus", "Jared",
    "Troy", "Lance", "Garrett", "Seth", "Wesley", "Nathaniel", "Shawn",
    "Corey", "Dillon", "Phillip", "Cory", "Derek", "Glenn", "Rex",
    "Wade", "Joel", "Dale", "Rick", "Clifford", "Stanley", "Vernon",
    "Floyd", "Fredrick", "Hugh", "Gene", "Morris", "Glen", "Clyde",
    "Cecil", "Harvey", "Russell", "Chester", "Roland", "Reginald", "Lonnie",
    "Marvin", "Earl", "Melvin", "Herbert", "Wendell", "Rodney", "Dwayne",
    "Clarence", "Claude", "Alvin", "Eddie", "Jimmy", "Tommy", "Johnny",
    "Bobby", "Ronnie", "Danny", "Ricky", "Timmy", "Donnie", "Kenny",
    "Lenny", "Benny", "Denny", "Penny", "Wally", "Willy", "Billy",
    "Cary", "Barry", "Larry", "Harry", "Garry", "Perry", "Terry",
    "Kerry", "Jerry", "Gerry", "Sherry", "Merle", "Earl", "Karl",
    "Bart", "Burt", "Kurt", "Curt", "Hank", "Clark", "Blake",
    "Drake", "Bryce", "Pierce", "Reece", "Royce", "Lance", "Vance",
    "Chance", "Clint", "Flint", "Trent", "Brent", "Kent", "Dent",
    "Wren", "Glen", "Ben", "Len", "Ken", "Den", "Ren",
    "Tom", "Tim", "Jim", "Kim", "Slim", "Trim", "Brim",
    "Brad", "Chad", "Clad", "Glad", "Mad", "Rad", "Tad",
    "Ted", "Fred", "Ned", "Jed", "Red", "Med", "Wed",
    "Bob", "Rob", "Job", "Mob", "Sob", "Lob", "Cob",
    "Dan", "Fan", "Jan", "Lan", "Man", "Pan", "Ran",
    "Weston", "Preston", "Clayton", "Peyton", "Dayton", "Houston", "Dalton",
    "Colton", "Bolton", "Carlton", "Shelton", "Elton", "Felton", "Melton",
    "Kelton", "Welton", "Belton", "Pelton", "Nelson", "Wilson", "Gibson",
    "Dixon", "Nixon", "Mason", "Jason", "Carson", "Dawson", "Hudson",
    "Madison", "Edison", "Addison", "Harrison", "Morrison", "Henderson", "Anderson",
    "Patterson", "Robertson", "Stevenson", "Williamson", "Richardson", "Thomason", "Jacobson",
    "Michaels", "Roberts", "Williams", "Davis", "Miller", "Moore", "Taylor",
    "Archer", "Fletcher", "Walker", "Turner", "Fisher", "Baker", "Hunter",
    "Potter", "Carter", "Foster", "Porter", "Cooper", "Hooper", "Trooper",
    "Jasper", "Casper", "Harper", "Draper", "Shafer", "Wafer", "Lafer",
    "Rigby", "Kirby", "Selby", "Welby", "Danby", "Hanby", "Canby",
    "Elroy", "Leroy", "Kilroy", "Monroy", "Conroy", "Henroy", "Tenroy",
    "Clifton", "Afton", "Dafton", "Grafton", "Crafton", "Drayton", "Grayton",
    "Sherwood", "Linwood", "Elmwood", "Harwood", "Garwood", "Norwood", "Dorwood",
    "Alden", "Holden", "Golden", "Bolden", "Folden", "Molden", "Tolden",
    "Forrest", "Barrett", "Jarrett", "Garrett", "Everett", "Merritt", "Perritt",
    "Clifford", "Crawford", "Bradford", "Radford", "Sanford", "Hanford", "Canford",
    "Sterling", "Darling", "Carling", "Marling", "Harling", "Farling", "Garling",
    "Weston", "Lawson", "Dawson", "Rawson", "Lawton", "Newton", "Seaton",
    "Winston", "Kinston", "Linton", "Hinton", "Winton", "Minton", "Finton",
    "Shelby", "Kelby", "Welby", "Delby", "Helby", "Felby", "Melby",
    "Rupert", "Hubert", "Gilbert", "Wilbert", "Colbert", "Holbert", "Tolbert",
    "Edmund", "Raymond", "Desmond", "Osmond", "Rosamond", "Beaumont", "Lamont",
    "Geoffrey", "Jeffrey", "Godfrey", "Humphrey", "Aubrey", "Cedric", "Aldric",
    "Leopold", "Rudolph", "Randolph", "Adolph", "Dolph", "Rolph", "Wolph",
    "Luka", "Nikola", "Giannis", "Rui", "Pascal", "Kristaps", "Bogdan",
    "Domantas", "Victor", "Shai", "Deni", "Jusuf",
    "Sekou", "Mamadi", "Killian", "Leandro", "Facundo", "Bennedict",
    "Aleksej", "Vasilije", "Dragan", "Nemanja", "Ognjen", "Boban",
    "Miroslav", "Radoslav", "Slavko", "Zarko",
]

LAST_NAMES = [
    # English
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "AJ", "PJ",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
    "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres",
    "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Hall",
    "Rivera", "Campbell", "Mitchell", "Carter", "Roberts", "Gomez", "Phillips",
    "Evans", "Turner", "Diaz", "Parker", "Cruz", "Edwards", "Collins",
    "Reyes", "Stewart", "Morris", "Morales", "Murphy", "Cook", "Rogers",
    "Gutierrez", "Ortiz", "Morgan", "Cooper", "Peterson", "Bailey", "Reed",
    "Kelly", "Howard", "Ramos", "Kim", "Cox", "Ward", "Richardson",
    "Watson", "Brooks", "Chavez", "Wood", "James", "Bennett", "Gray",
    "Mendoza", "Ruiz", "Hughes", "Price", "Alvarez", "Castillo",
    "Sanders", "Patel", "Myers", "Long", "Ross", "Foster", "Jimenez",
    "Powell", "Jenkins", "Perry", "Russell", "Sullivan", "Bell", "Coleman",
    "Butler", "Henderson", "Barnes", "Gonzales", "Fisher", "Vasquez", "Simmons",
    "Romero", "Jordan", "Patterson", "Alexander", "Hamilton", "Graham", "Reynolds",
    "Griffin", "Wallace", "Moreno", "West", "Cole", "Hayes", "Bryant",
    "Herrera", "Gibson", "Ellis", "Tran", "Medina", "Aguilar", "Stevens",
    "Murray", "Ford", "Castro", "Marshall", "Owens", "Harrison", "Fernandez",
    "Mcdonald", "Woods", "Washington", "Kennedy", "Wells", "Vargas", "Henry",
    "Chen", "Freeman", "Webb", "Tucker", "Guzman", "Burns", "Crawford",
    "Olson", "Simpson", "Porter", "Hunter", "Gordon", "Mendez", "Silva",
    "Shaw", "Snyder", "Mason", "Dixon", "Munoz", "Hunt", "Hicks",
    "Holmes", "Palmer", "Wagner", "Black", "Robertson", "Boyd", "Rose",
    "Stone", "Salazar", "Fox", "Warren", "Mills", "Meyer", "Rice",
    "Schmidt", "Garza", "Daniels", "Ferguson", "Nichols", "Stephens", "Soto",
    "Weaver", "Ryan", "Gardner", "Payne", "Grant", "Dunn", "Kelley",
    "Spencer", "Hawkins", "Arnold", "Pierce", "Tran", "Richmond", "Cannon",
    "Fleming", "Obrien", "Harvey", "Lane", "Lawrence", "Patton", "Carr",
    "Hudson", "Chambers", "Byrd", "Bishop", "May", "Brewer", "George",
    "Mckinney", "Reeves", "Klein", "Banks", "Wheeler", "Lowe", "Bowman",
    "Hudson", "Roy", "Holt", "Hawkins", "Duncan", "Aguilar", "Thornton",
    "Wise", "Douglas", "Warner", "Strickland", "Barker", "Cobb", "Gill",
    "Doyle", "Mcgee", "Bates", "Horton", "Walsh", "Obrien", "Burnett",
    "Avila", "Erickson", "Bush", "Dixon", "Pope", "Obrien", "Mccarthy",
    "Drake", "Floyd", "Stein", "Hogan", "Gross", "Duran", "Pratt",
    "Potter", "Walton", "Goodwin", "Burke", "Barber", "Cummings", "Pena",
    "Harrington", "Watts", "Schneider", "Bowen", "Swanson", "Maldonado", "Collier",
    "Conner", "Larsen", "Becker", "Floyd", "Gibbs", "Holland", "Osborne",
    "Pearson", "Mcintosh", "Howe", "Lindsey", "Townsend", "Bowers", "Nolan",
    "Zimmerman", "Rojas", "Mcfarland", "Cannon", "Hubbard", "Mcleod", "Bradshaw",
    "Malone", "Christensen", "Holloway", "Oconnor", "Tillman", "Shelton", "Dodson",
    "Day", "Cooke", "Hoover", "Dean", "Mcgrath", "Griffith", "Carr",
    "Randolph", "Oneill", "Mcallister", "Vance", "Waters", "Frazier", "Saunders",
    "Barnett", "Atkinson", "Trujillo", "Rubin", "Higgins", "Mcpherson", "Cross",
    "Sloan", "Moody", "Walters", "Pace", "Stafford", "Gentry", "Finley",
    "Odom", "Bradford", "Noble", "Hurst", "Acosta", "Frost", "Knapp",
    "Levy", "Mcmahon", "Kent", "Terry", "Ware", "Short", "Savage",
    "Sparks", "Richard", "Delaney", "Gallegos", "Singleton", "Sutton", "Bentley",
    "Blackwell", "Pennington", "Shields", "Mcconnell", "Rollins", "Roach", "Greer",
    "Mcbride", "Clements", "Lester", "Sampson", "Buckley", "Hahn", "Kirby",
    "Barton", "Glover", "Pittman", "Mercer", "Ingram", "Bridges", "Mayer",
    "Yates", "Bright", "Hardy", "Davenport", "Sheppard", "Mcguire", "Cantrell",
    "Delgado", "Escobar", "Lucero", "Pham", "Curry", "Padilla", "Flowers",
    "Mathis", "Galloway", "Hines", "Bass", "Mcclain", "Deleon", "Fuentes",
    "Mcneil", "Mack", "Donaldson", "Dyer", "Ayers", "Norris", "Giles",
    "English", "Sparks", "Pugh", "Allison", "Pennington", "Calhoun", "Byrd",
    # International (30)
    "Petrov", "Volkov", "Novak", "Kovac", "Horvat", "Blazic", "Tomic",
    "Rakic", "Djordjevic", "Stanisic", "Lindqvist", "Bergstrom", "Hanninen", "Makinen",
    "Virtanen", "Korhonen", "Lehtinen", "Nieminen", "Saarinen", "Leinonen",
    "Papadopoulos", "Stavros", "Georgiou", "Nakamura", "Tanaka", "Yamamoto",
    "Okonkwo", "Mensah", "Diallo", "Tremblay",
]

POSITIONS = ['PG', 'SG', 'SF', 'PF', 'C']

# Position-based attribute modifiers (relative to base)
# Each position has strengths in certain attributes
POSITION_MODIFIERS = {
    'PG': {'speed': 8, 'passing': 8, 'ball_handling': 8, 'iq': 5, 'three_point': 3,
           'shooting': 2, 'defense': 0, 'athleticism': 2, 'rebounding': -5, 'blocks': -5, 'steals': 3},
    'SG': {'speed': 5, 'shooting': 8, 'three_point': 8, 'ball_handling': 5, 'athleticism': 3,
           'passing': 2, 'defense': 2, 'iq': 2, 'rebounding': -3, 'blocks': -4, 'steals': 2},
    'SF': {'speed': 4, 'shooting': 5, 'three_point': 5, 'defense': 5, 'athleticism': 5,
           'ball_handling': 3, 'passing': 3, 'iq': 3, 'rebounding': 0, 'blocks': -2, 'steals': 2},
    'PF': {'defense': 6, 'rebounding': 7, 'athleticism': 5, 'blocks': 4, 'shooting': 2,
           'speed': 0, 'passing': 0, 'iq': 2, 'ball_handling': -2, 'three_point': 0, 'steals': 0},
    'C':  {'rebounding': 10, 'blocks': 10, 'defense': 7, 'athleticism': 3, 'shooting': -3,
           'speed': -5, 'passing': -5, 'iq': 0, 'ball_handling': -5, 'three_point': -8, 'steals': -3},
}

# Height and weight ranges by position (cm, kg)
POSITION_BODY = {
    'PG': (183, 193, 77, 90),
    'SG': (188, 198, 82, 95),
    'SF': (196, 206, 90, 105),
    'PF': (201, 211, 100, 115),
    'C':  (208, 218, 108, 125),
}


def generate_draft_players(season):
    """Generate 30 draft players assigned to teams in reverse standings order."""
    # Reset is_rookie for ALL existing players
    Player.objects.all().update(is_rookie=False)

    # Get final standings from regular season
    standings = _get_final_standings(season)
    if len(standings) < 30:
        return []

    # Reverse order: worst team picks first
    draft_order = list(reversed(standings))[:30]

    draft_picks = []
    for pick_num, team in enumerate(draft_order, 1):
        # Pick 1 = best (~80 avg), Pick 30 = worst (~60 avg)
        # Linear interpolation
        base_avg = 75 - (pick_num - 1) * (15 / 29)  # 80 down to 60

        position = random.choice(POSITIONS)
        modifiers = POSITION_MODIFIERS[position]
        height_min, height_max, weight_min, weight_max = POSITION_BODY[position]

        height = random.randint(height_min, height_max)
        weight = random.randint(weight_min, weight_max)
        age = random.randint(19, 20)

        # Generate attributes around base_avg with position modifiers
        attrs = {}
        for attr in ['speed', 'shooting', 'three_point', 'passing', 'ball_handling',
                      'defense', 'rebounding', 'athleticism', 'iq', 'steals', 'blocks']:
            mod = modifiers.get(attr, 0)
            value = int(base_avg + mod + random.randint(-5, 5))
            value = max(30, min(99, value))
            attrs[attr] = value

        # Overall is average of all attributes
        overall = int(sum(attrs.values()) / len(attrs))
        potential = min(99, overall + random.randint(3, 12))

        # Nationality
        if random.random() < 0.9:
            nationality = "USA"
        else:
            intl = [
                "GER", "BRA", "GMB", "TGO", "AUS", "PNG", "AUT", "BAH", "NGA", "BEL",
                "MLI", "BIH", "CMR", "CAN", "HTI", "CHN", "CRO", "SLO", "ESP", "FIN",
                "FRA", "BEN", "MTQ", "CIV", "GUI", "MAR", "COD", "SEN", "GEO", "GRE",
                "ISR", "ITA", "JAM", "JPN", "LAT", "LTU", "MNE", "TUR", "NZL", "NED",
                "POR", "GNB", "GBR", "POL", "CZE", "DOM", "RUS", "LCA", "SRB", "SWE",
                "SSD", "UGA", "SUI", "ANG", "UKR",
            ]
            nationality = random.choice(intl)

        first_name = random.choice(FIRST_NAMES)
        last_name = random.choice(LAST_NAMES)

        salary = random.randint(3000000, 8000000)
        salary = round(salary / 100000) * 100000

        player = Player(
            team=team,
            first_name=first_name,
            last_name=last_name,
            position=position,
            age=age,
            nationality=nationality,
            height_cm=height,
            weight_kg=weight,
            overall=overall,
            potential=potential,
            speed=attrs['speed'],
            shooting=attrs['shooting'],
            three_point=attrs['three_point'],
            passing=attrs['passing'],
            ball_handling=attrs['ball_handling'],
            defense=attrs['defense'],
            rebounding=attrs['rebounding'],
            athleticism=attrs['athleticism'],
            iq=attrs['iq'],
            steals=attrs['steals'],
            blocks=attrs['blocks'],
            injury_days=0,
            injury_type='',
            salary=salary,
            contract_years=4,
            is_rookie=True,
        )
        player.save()

        draft_picks.append({
            'pick': pick_num,
            'player': player,
            'team': team,
        })

    return draft_picks


def _get_final_standings(season):
    """Get final standings sorted by win percentage (worst first for draft)."""
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

    # Sort by win percentage (best first), then by losses
    rows.sort(key=lambda x: (-x['pct'], x['losses'], -x['wins']))
    return [r['team'] for r in rows]
