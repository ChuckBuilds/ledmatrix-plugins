# Soccer Team Abbreviations

This file lists the team abbreviations used by the ESPN API for each supported league.
**Use these abbreviations** in the `favorite_teams` config field in the web UI — the plugin matches teams by their ESPN abbreviation, not their full name.

```json
"favorite_teams": ["LIV", "ARS"]
```

Abbreviations are shown as uppercase 2–4 character codes. If you don't see your team listed or the abbreviation doesn't seem to work, check the plugin's debug logs — the plugin logs `home_abbr` and `away_abbr` for every game it processes.

The tables below are generated from ESPN's live team endpoints, so they are the
codes the plugin actually compares against. **They are not always the code you
would guess:** ESPN uses `MAN` for Manchester United (not `MUN`), `MNC` for
Manchester City (not `MCI`), `RMA` for Real Madrid (not `RM`), and `LYON` /
`OLM` for Lyon and Marseille (not `OL` / `OM`).

### Codes that mean different clubs in different leagues

Favourites are matched by abbreviation across every league you have enabled, so
if two of your enabled leagues share a code you will match both. The one to
watch is `MUN`, which is **Bayern Munich** in the Bundesliga — not Manchester
United.

| Code | Could be |
|------|----------|
| `MUN` | Bayern Munich (Bundesliga) — Manchester United is `MAN` |
| `BRE` | Brentford (Premier League) or Brest (Ligue 1) |
| `MON` | Monza (Serie A) or AS Monaco (Ligue 1) |
| `PAR` | Parma (Serie A) or Paris FC (Ligue 1) |
| `SCP` | SC Paderborn (Bundesliga) or Sporting CP (Liga Portugal) |
| `FCA` | FC Augsburg (Bundesliga) or Arouca (Liga Portugal) |
| `TOR` | Torino (Serie A) or Toronto FC (MLS) |

---

## Premier League (eng.1)

| Club | Abbreviation |
|------|-------------|
| AFC Bournemouth | BOU |
| Arsenal | ARS |
| Aston Villa | AVL |
| Brentford | BRE |
| Brighton & Hove Albion | BHA |
| Chelsea | CHE |
| Coventry City | COV |
| Crystal Palace | CRY |
| Everton | EVE |
| Fulham | FUL |
| Hull City | HUL |
| Ipswich Town | IPS |
| Leeds United | LEE |
| Liverpool | LIV |
| Manchester City | MNC |
| Manchester United | MAN |
| Newcastle United | NEW |
| Nottingham Forest | NFO |
| Sunderland | SUN |
| Tottenham Hotspur | TOT |

---

## La Liga (esp.1)

| Club | Abbreviation |
|------|-------------|
| Alavés | ALA |
| Athletic Club | ATH |
| Atlético Madrid | ATM |
| Barcelona | BAR |
| Celta Vigo | CEL |
| Deportivo La Coruña | DEP |
| Elche | ELC |
| Espanyol | ESP |
| Getafe | GET |
| Levante | LEV |
| Málaga | MCF |
| Osasuna | OSA |
| Racing Santander | RAC |
| Rayo Vallecano | RAY |
| Real Betis | BET |
| Real Madrid | RMA |
| Real Sociedad | RSO |
| Sevilla | SEV |
| Valencia | VAL |
| Villarreal | VIL |

---

## Bundesliga (ger.1)

| Club | Abbreviation |
|------|-------------|
| 1. FC Union Berlin | FCU |
| Bayer Leverkusen | B04 |
| Bayern Munich | MUN |
| Borussia Dortmund | DOR |
| Borussia Mönchengladbach | BMG |
| Eintracht Frankfurt | SGE |
| FC Augsburg | FCA |
| FC Cologne | KOE |
| Hamburg SV | HSV |
| Mainz | M05 |
| RB Leipzig | RBL |
| SC Freiburg | SCF |
| SC Paderborn 07 | SCP |
| Schalke 04 | S04 |
| SV Elversberg | ELV |
| TSG Hoffenheim | TSG |
| VfB Stuttgart | VFB |
| Werder Bremen | SVW |

---

## Serie A (ita.1)

| Club | Abbreviation |
|------|-------------|
| AC Milan | MIL |
| AS Roma | ROMA |
| Atalanta | ATA |
| Bologna | BOL |
| Cagliari | CAG |
| Como | COMO |
| Fiorentina | FIO |
| Frosinone | FRO |
| Genoa | GEN |
| Internazionale | INT |
| Juventus | JUV |
| Lazio | LAZ |
| Lecce | LEC |
| Monza | MON |
| Napoli | NAP |
| Parma | PAR |
| Sassuolo | SAS |
| Torino | TOR |
| Udinese | UDI |
| Venezia | VEN |

---

## Ligue 1 (fra.1)

| Club | Abbreviation |
|------|-------------|
| AJ Auxerre | AUX |
| Angers | ANG |
| AS Monaco | MON |
| Brest | BRE |
| Le Havre AC | HAC |
| Le Mans | MNS |
| Lens | RCL |
| Lille | LILL |
| Lorient | LOR |
| Lyon | LYON |
| Marseille | OLM |
| Nice | NICE |
| Paris FC | PAR |
| Paris Saint-Germain | PSG |
| Stade Rennais | REN |
| Strasbourg | STR |
| Toulouse | TOU |
| Troyes | TRY |

---

## MLS (usa.1)

| Club | Abbreviation |
|------|-------------|
| Atlanta United FC | ATL |
| Austin FC | ATX |
| CF Montréal | MTL |
| Charlotte FC | CLT |
| Chicago Fire FC | CHI |
| Colorado Rapids | COL |
| Columbus Crew | CLB |
| D.C. United | DC |
| FC Cincinnati | CIN |
| FC Dallas | DAL |
| Houston Dynamo FC | HOU |
| Inter Miami CF | MIA |
| LA Galaxy | LA |
| LAFC | LAFC |
| Minnesota United FC | MIN |
| Nashville SC | NSH |
| New England Revolution | NE |
| New York City FC | NYC |
| Orlando City SC | ORL |
| Philadelphia Union | PHI |
| Portland Timbers | POR |
| Real Salt Lake | RSL |
| Red Bull New York | RBNY |
| San Diego FC | SD |
| San Jose Earthquakes | SJ |
| Seattle Sounders FC | SEA |
| Sporting Kansas City | SKC |
| St. Louis CITY SC | STL |
| Toronto FC | TOR |
| Vancouver Whitecaps | VAN |

---

## Liga Portugal (por.1)

| Club | Abbreviation |
|------|-------------|
| Académico de Viseu | AVF |
| Alverca | ALV |
| Arouca | FCA |
| Benfica | SLB |
| Braga | SCB |
| C.D. Nacional | CDN |
| Casa Pia | CPAC |
| Estoril | EPF |
| Estrela | EST |
| FC Famalicao | FCF |
| FC Porto | FCP |
| Gil Vicente | GVFC |
| Maritimo | MAR |
| Moreirense | MFC |
| Rio Ave | RAFC |
| Santa Clara | CDSC |
| Sporting CP | SCP |
| Vitória de Guimaraes | VSC |

---

## UEFA Champions League (uefa.champions)

Teams change each season. Use the club's abbreviation from its domestic league table above. For example, Real Madrid is `RMA`, Liverpool is `LIV`.

---

## UEFA Europa League (uefa.europa)

Same as Champions League — use the club's domestic abbreviation from the tables above.

---

## FIFA World Cup 2026 (fifa.world)

National-team flags are **bundled with the plugin** and seeded into a dedicated
`soccer_logos/national/` directory on startup. This keeps them isolated from club
logos that share an abbreviation — without it, Espanyol's `ESP` crest would
shadow Spain's flag, Portland Timbers' `POR` would shadow Portugal, and Colorado
Rapids' `COL` would shadow Colombia. Every country below renders its real flag
out of the box; no per-game download is required.

The abbreviations below are confirmed from ESPN's live `fifa.world` feed and are
the exact codes to use in `favorite_teams`.

| Country | Abbreviation |
|---------|-------------|
| Algeria | ALG |
| Argentina | ARG |
| Australia | AUS |
| Austria | AUT |
| Belgium | BEL |
| Bosnia-Herzegovina | BIH |
| Brazil | BRA |
| Canada | CAN |
| Cape Verde | CPV |
| Colombia | COL |
| Congo DR | COD |
| Croatia | CRO |
| Curaçao | CUW |
| Czechia | CZE |
| Ecuador | ECU |
| Egypt | EGY |
| England | ENG |
| France | FRA |
| Germany | GER |
| Ghana | GHA |
| Haiti | HAI |
| Iran | IRN |
| Iraq | IRQ |
| Ivory Coast | CIV |
| Japan | JPN |
| Jordan | JOR |
| Mexico | MEX |
| Morocco | MAR |
| Netherlands | NED |
| New Zealand | NZL |
| Norway | NOR |
| Panama | PAN |
| Paraguay | PAR |
| Portugal | POR |
| Qatar | QAT |
| Saudi Arabia | KSA |
| Scotland | SCO |
| Senegal | SEN |
| South Africa | RSA |
| South Korea | KOR |
| Spain | ESP |
| Sweden | SWE |
| Switzerland | SUI |
| Tunisia | TUN |
| Türkiye | TUR |
| United States | USA |
| Uruguay | URU |
| Uzbekistan | UZB |

If a team isn't listed (e.g. a late playoff qualifier), the plugin still
downloads its flag on demand from ESPN into the same `national/` directory.

---

## Tips

- **Abbreviations are case-sensitive** — use uppercase as shown (e.g. `"LIV"` not `"liv"`)
- **Season rosters change** — promoted/relegated teams join or leave; if a team isn't listed here, check the debug logs for the abbreviation the API returns
- **Custom leagues** — for any ESPN-supported league not listed here (e.g., `mex.1`, `arg.1`), run the plugin with debug logging and look for `home_abbr`/`away_abbr` log lines to find the correct codes
- **Nothing showing up?** The plugin now tells you which it is at startup. An
  unrecognised code logs a warning naming the closest match; a code that is
  valid but has no fixtures yet logs the date the season starts. Check the logs
  before assuming the code is wrong — between seasons an empty screen is normal
- **Re-checking a code yourself** — ESPN's team list for a league is at
  `https://site.api.espn.com/apis/site/v2/sports/soccer/<league>/teams`, e.g.
  `.../soccer/eng.1/teams`
