# Soccer Team Abbreviations

This file lists the team abbreviations used by the ESPN API for each supported league.
**Use these abbreviations** in the `favorite_teams` config field in the web UI — the plugin matches teams by their ESPN abbreviation, not their full name.

```json
"favorite_teams": ["LIV", "ARS"]
```

Abbreviations are shown as uppercase 2–4 character codes. If you don't see your team listed or the abbreviation doesn't seem to work, check the plugin's debug logs — the plugin logs `home_abbr` and `away_abbr` for every game it processes.

---

## Premier League (eng.1)

| Club | Abbreviation |
|------|-------------|
| Arsenal | ARS |
| Aston Villa | AVL |
| Bournemouth | BOU |
| Brentford | BRE |
| Brighton & Hove Albion | BHA |
| Chelsea | CHE |
| Crystal Palace | CRY |
| Everton | EVE |
| Fulham | FUL |
| Ipswich Town | IPS |
| Leicester City | LEI |
| Liverpool | LIV |
| Manchester City | MCI |
| Manchester United | MUN |
| Newcastle United | NEW |
| Nottingham Forest | NFO |
| Southampton | SOU |
| Tottenham Hotspur | TOT |
| West Ham United | WHU |
| Wolverhampton Wanderers | WOL |

---

## La Liga (esp.1)

| Club | Abbreviation |
|------|-------------|
| Athletic Club (Bilbao) | ATH |
| Atletico Madrid | ATM |
| Barcelona | BAR |
| Celta Vigo | CEL |
| Espanyol | ESP |
| Getafe | GET |
| Girona | GIR |
| Las Palmas | LPA |
| Leganes | LEG |
| Mallorca | MAL |
| Osasuna | OSA |
| Rayo Vallecano | RAY |
| Real Betis | BET |
| Real Madrid | RM |
| Real Sociedad | RSO |
| Sevilla | SEV |
| Valencia | VAL |
| Valladolid | VLL |
| Villarreal | VIL |

---

## Bundesliga (ger.1)

| Club | Abbreviation |
|------|-------------|
| Augsburg | AUG |
| Bayer Leverkusen | B04 |
| Bayern Munich | BAY |
| Borussia Dortmund | BVB |
| Borussia Monchengladbach | BMG |
| Eintracht Frankfurt | SGE |
| Freiburg | SCF |
| Heidenheim | HDH |
| Hoffenheim | TSG |
| Holstein Kiel | KIE |
| Mainz | MNZ |
| RB Leipzig | RBL |
| St. Pauli | STP |
| Stuttgart | VFB |
| Union Berlin | FCU |
| Werder Bremen | SVW |
| Wolfsburg | WOB |
| Bochum | BOC |

---

## Serie A (ita.1)

| Club | Abbreviation |
|------|-------------|
| AC Milan | MIL |
| AS Roma | ROM |
| Atalanta | ATA |
| Bologna | BOL |
| Cagliari | CAG |
| Como | COM |
| Empoli | EMP |
| Fiorentina | FIO |
| Genoa | GEN |
| Hellas Verona | VER |
| Inter Milan | INT |
| Juventus | JUV |
| Lazio | LAZ |
| Lecce | LEC |
| Monza | MON |
| Napoli | NAP |
| Parma | PAR |
| Torino | TOR |
| Udinese | UDI |
| Venezia | VEN |

---

## Ligue 1 (fra.1)

| Club | Abbreviation |
|------|-------------|
| Angers | ANG |
| Auxerre | AUX |
| Brest | BRE |
| Le Havre | HAV |
| Lens | RCL |
| Lille | LIL |
| Lyon | OL |
| Marseille | OM |
| Monaco | ASM |
| Montpellier | MHSC |
| Nantes | FCN |
| Nice | OGC |
| Paris Saint-Germain | PSG |
| Reims | SDR |
| Rennes | SRFC |
| Saint-Etienne | ASSE |
| Strasbourg | RCSA |
| Toulouse | TFC |

---

## MLS (usa.1)

| Club | Abbreviation |
|------|-------------|
| Atlanta United | ATL |
| Austin FC | ATX |
| Charlotte FC | CLT |
| Chicago Fire | CHI |
| FC Cincinnati | CIN |
| Colorado Rapids | COL |
| Columbus Crew | CLB |
| D.C. United | DC |
| FC Dallas | DAL |
| Houston Dynamo | HOU |
| Inter Miami | MIA |
| LA Galaxy | LA |
| Los Angeles FC | LAFC |
| Minnesota United | MIN |
| CF Montréal | MTL |
| Nashville SC | NSH |
| New England Revolution | NE |
| New York City FC | NYC |
| New York Red Bulls | RBNY |
| Orlando City | ORL |
| Philadelphia Union | PHI |
| Portland Timbers | POR |
| Real Salt Lake | RSL |
| San Diego FC | SD |
| San Jose Earthquakes | SJ |
| Seattle Sounders | SEA |
| Sporting Kansas City | SKC |
| St. Louis City SC | STL |
| Toronto FC | TOR |
| Vancouver Whitecaps | VAN |

---

## Liga Portugal (por.1)

| Club | Abbreviation |
|------|-------------|
| Arouca | ARO |
| Benfica | SLB |
| Boavista | BOA |
| Braga | SCB |
| Casa Pia | CPA |
| Estoril | EST |
| Famalicao | FAM |
| Farense | FAR |
| Gil Vicente | GIL |
| Moreirense | MOR |
| Nacional | NAC |
| Porto | FCP |
| Rio Ave | RAV |
| Sporting CP | SCP |
| Vitoria SC (Guimaraes) | VIT |

---

## UEFA Champions League (uefa.champions)

Teams change each season. Use the club's abbreviation from its domestic league table above. For example, Real Madrid is `RM`, Liverpool is `LIV`.

---

## UEFA Europa League (uefa.europa)

Same as Champions League — use the club's domestic abbreviation from the tables above.

---

## FIFA World Cup 2026 (fifa.world)

> **⚠️ Verify abbreviations via debug logs.** ESPN's internal abbreviations for national teams are not always the same as FIFA country codes. Enable debug logging and check the `home_abbr`/`away_abbr` values logged for each game to confirm the exact codes the ESPN feed uses before setting `favorite_teams`.

The table below lists high-confidence ESPN abbreviations based on prior international tournament data. Entries marked with `*` should be treated as approximate until confirmed from the live feed.

| Country | Abbreviation |
|---------|-------------|
| Argentina | ARG |
| Australia | AUS |
| Belgium | BEL |
| Brazil | BRA |
| Cameroon | CMR |
| Canada | CAN |
| Chile | CHI |
| Colombia | COL |
| Costa Rica | CRC |
| Croatia | CRO |
| Czech Republic | CZE |
| Ecuador | ECU |
| Egypt | EGY |
| England | ENG |
| France | FRA |
| Germany | GER |
| Ghana | GHA |
| Hungary | HUN |
| Iran | IRN |
| Japan | JPN |
| Mali | MLI * |
| Mexico | MEX |
| Morocco | MAR |
| Netherlands | NED |
| New Zealand | NZL |
| Nigeria | NGA |
| Panama | PAN |
| Paraguay | PAR |
| Portugal | POR |
| Saudi Arabia | KSA |
| Senegal | SEN |
| Serbia | SRB |
| Slovakia | SVK |
| South Korea | KOR |
| Spain | ESP |
| Switzerland | SUI |
| Tunisia | TUN |
| United States | USA |
| Uruguay | URU |

To find your team's abbreviation: enable the plugin, set `debug` log level, then look for lines like `Extracted: USA@MEX` in the logs — those are the exact codes ESPN returns.

---

## Tips

- **Abbreviations are case-sensitive** — use uppercase as shown (e.g. `"LIV"` not `"liv"`)
- **Season rosters change** — promoted/relegated teams join or leave; if a team isn't listed here, check the debug logs for the abbreviation the API returns
- **Custom leagues** — for any ESPN-supported league not listed here (e.g., `mex.1`, `arg.1`), run the plugin with debug logging and look for `home_abbr`/`away_abbr` log lines to find the correct codes
