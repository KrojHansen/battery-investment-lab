
# ==========================================
# BATTERY INVESTMENT LAB
# BATTERIKONFIGURATION
# ==========================================


# ==========================================
# BATTERIETS TEKNISKE SPECIFIKATIONER
# ==========================================

# Maksimal lade- og afladeeffekt
BATTERY_POWER_MW = 10.0

# Batteriets energikapacitet
BATTERY_CAPACITY_MWH = 20.0

# Samlet virkningsgrad ved opladning og afladning
ROUNDTRIP_EFFICIENCY = 0.90

# Længden af hvert prisinterval i timer
INTERVAL_HOURS = 0.25

# Batteriets energiniveau ved periodens start
START_SOC_MWH = 0.0

# Batteriets energiniveau ved periodens afslutning
END_SOC_MWH = 0.0


# ==========================================
# ØKONOMISKE FORUDSÆTNINGER
# ==========================================

# Referencepris for batteripakken
# NREL-benchmark for 2-timers batterisystem
# Oprindeligt opgjort i 2022 USD
BATTERY_PACK_COST_USD_PER_KWH = 215.0

# Dollarkurs fra 28. oktober 2026
USD_TO_DKK = 6.7135

# Forventet beregningshorisont
BATTERY_LIFETIME_YEARS = 15

# Reference for antal fulde cyklusser pr. dag
FULL_CYCLES_PER_DAY = 1.0

# Antal dage pr. år i referenceberegningen
DAYS_PER_YEAR = 365


# ==========================================
# BEREGNING AF BATTERISLITAGE
# ==========================================

# Batteriets samlede referenceværdi
BATTERY_PACK_COST_DKK = (
    BATTERY_CAPACITY_MWH
    * 1000
    * BATTERY_PACK_COST_USD_PER_KWH
    * USD_TO_DKK
)

# Forventet antal fulde cyklusser
LIFETIME_FULL_CYCLES = (
    BATTERY_LIFETIME_YEARS
    * DAYS_PER_YEAR
    * FULL_CYCLES_PER_DAY
)

# Afladningsvirkningsgrad
DISCHARGE_EFFICIENCY = ROUNDTRIP_EFFICIENCY ** 0.5

# Forventet samlet energileverance
LIFETIME_DISCHARGED_MWH = (
    BATTERY_CAPACITY_MWH
    * LIFETIME_FULL_CYCLES
    * DISCHARGE_EFFICIENCY
)

# Slitageomkostning pr. afladet MWh
DEGRADATION_COST_DKK_PER_MWH = (
    BATTERY_PACK_COST_DKK
    / LIFETIME_DISCHARGED_MWH
)


# ==========================================
# FILER
# ==========================================

# Historisk prisfil
PRICE_FILE = "dk1_month.csv"

# Fil til den optimerede handelsstrategi
OUTPUT_FILE = "optimized_month.csv"


# ==========================================
# TEST AF KONFIGURATION
# ==========================================

if __name__ == "__main__":

    print("\nBATTERIKONFIGURATION")

    print("Batterieffekt:", BATTERY_POWER_MW, "MW")

    print("Batterikapacitet:", BATTERY_CAPACITY_MWH, "MWh")

    print(
        "Virkningsgrad:",
        ROUNDTRIP_EFFICIENCY * 100,
        "%"
    )

    print("\nØKONOMISKE FORUDSÆTNINGER")

    print(
        "Referenceværdi af batteripakke:",
        round(BATTERY_PACK_COST_DKK, 2),
        "kr."
    )

    print(
        "Forventet antal fulde cyklusser:",
        round(LIFETIME_FULL_CYCLES, 0)
    )

    print(
        "Forventet samlet afladet energi:",
        round(LIFETIME_DISCHARGED_MWH, 2),
        "MWh"
    )

    print(
        "Beregnet slidtageomkostning:",
        round(DEGRADATION_COST_DKK_PER_MWH, 2),
        "kr./MWh"
    )
