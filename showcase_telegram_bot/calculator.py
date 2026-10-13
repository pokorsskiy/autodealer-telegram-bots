"""Предварительный расчёт стоимости ввоза автомобиля для физического лица."""

from dataclasses import dataclass

AGE_UNDER_3 = "under_3"
AGE_3_TO_5 = "3_to_5"
AGE_OVER_5 = "over_5"

AGE_LABELS = {
    AGE_UNDER_3: "до 3 лет",
    AGE_3_TO_5: "от 3 до 5 лет",
    AGE_OVER_5: "старше 5 лет",
}

# Параметры расчёта держим рядом с формулой, а не в .env: числа одинаковые
# во всех трёх решениях, и разъезжаться им нельзя. Настройку через админку
# сделаем вместе с подстановкой актуальных курсов.
# Демонстрационные значения.
EUR_RUB_RATE = 100.0
DELIVERY_AND_EXPENSES_RUB = 450_000


# Утилизационный сбор для физического лица при ввозе для личного пользования.
# Демонстрационные ставки: перед рабочим запуском сверить с действующими.
RECYCLING_FEE_UNDER_3_RUB = 3_400
RECYCLING_FEE_OVER_3_RUB = 5_200


def recycling_fee_rub(age: str) -> int:
    """Утильсбор зависит только от возраста автомобиля."""
    return RECYCLING_FEE_UNDER_3_RUB if age == AGE_UNDER_3 else RECYCLING_FEE_OVER_3_RUB


@dataclass(frozen=True)
class Calculation:
    car_price_eur: float
    duty_eur: float
    car_price_rub: int
    duty_rub: int
    recycling_rub: int
    delivery_rub: int
    other_costs_rub: int
    total_rub: int


def _rate_by_engine(engine_cc: int, brackets: tuple[tuple[int, float], ...]) -> float:
    for upper_bound, rate in brackets:
        if engine_cc <= upper_bound:
            return rate
    return brackets[-1][1]


def calculate_duty_eur(car_price_eur: float, age: str, engine_cc: int) -> float:
    """Возвращает единую таможенную ставку в евро по решению ЕЭК №107."""
    if age == AGE_UNDER_3:
        price_brackets = (
            (8_500, 0.54, 2.5),
            (16_700, 0.48, 3.5),
            (42_300, 0.48, 5.5),
            (84_500, 0.48, 7.5),
            (169_000, 0.48, 15.0),
            (float("inf"), 0.48, 20.0),
        )
        for upper_bound, percent, minimum_per_cc in price_brackets:
            if car_price_eur <= upper_bound:
                return max(car_price_eur * percent, engine_cc * minimum_per_cc)

    if age == AGE_3_TO_5:
        rate = _rate_by_engine(
            engine_cc,
            (
                (1_000, 1.5),
                (1_500, 1.7),
                (1_800, 2.5),
                (2_300, 2.7),
                (3_000, 3.0),
                (10_000, 3.6),
            ),
        )
        return engine_cc * rate

    if age == AGE_OVER_5:
        rate = _rate_by_engine(
            engine_cc,
            (
                (1_000, 3.0),
                (1_500, 3.2),
                (1_800, 3.5),
                (2_300, 4.8),
                (3_000, 5.0),
                (10_000, 5.7),
            ),
        )
        return engine_cc * rate

    raise ValueError("Неизвестная возрастная категория автомобиля")


def calculate_total(
    car_price_eur: float,
    age: str,
    engine_cc: int,
    eur_rub_rate: float,
    delivery_rub: int,
    other_costs_rub: int,
) -> Calculation:
    duty_eur = calculate_duty_eur(car_price_eur, age, engine_cc)
    car_price_rub = round(car_price_eur * eur_rub_rate)
    duty_rub = round(duty_eur * eur_rub_rate)
    recycling_rub = recycling_fee_rub(age)
    return Calculation(
        car_price_eur=car_price_eur,
        duty_eur=duty_eur,
        car_price_rub=car_price_rub,
        duty_rub=duty_rub,
        recycling_rub=recycling_rub,
        delivery_rub=delivery_rub,
        other_costs_rub=other_costs_rub,
        total_rub=(
            car_price_rub + duty_rub + recycling_rub + delivery_rub + other_costs_rub
        ),
    )


def calculate_total_from_rub(
    car_price_rub: int,
    age: str,
    engine_cc: int,
    eur_rub_rate: float,
    delivery_rub: int,
    other_costs_rub: int,
) -> Calculation:
    """Рассчитывает итог при вводе стоимости автомобиля в рублях."""
    if eur_rub_rate <= 0:
        raise ValueError("Курс евро должен быть больше нуля")

    return calculate_total(
        car_price_eur=car_price_rub / eur_rub_rate,
        age=age,
        engine_cc=engine_cc,
        eur_rub_rate=eur_rub_rate,
        delivery_rub=delivery_rub,
        other_costs_rub=other_costs_rub,
    )


def calculate_from_budget(
    budget_rub: int,
    age: str,
    engine_cc: int,
    eur_rub_rate: float,
    delivery_rub: int,
    other_costs_rub: int,
    price_step_rub: int = 10_000,
) -> Calculation | None:
    """Подбирает стоимость автомобиля, при которой итог влезает в бюджет.

    Пошлина зависит от цены автомобиля, поэтому вычесть расходы напрямую
    нельзя: ищем подбором наибольшую цену, при которой итог не превышает
    бюджет. Возвращает None, если бюджета не хватает даже на привоз.
    """
    if budget_rub <= 0:
        return None

    low, high = 0, budget_rub
    best: Calculation | None = None
    while low <= high:
        middle = (low + high) // 2
        calculation = calculate_total_from_rub(
            car_price_rub=middle,
            age=age,
            engine_cc=engine_cc,
            eur_rub_rate=eur_rub_rate,
            delivery_rub=delivery_rub,
            other_costs_rub=other_costs_rub,
        )
        if calculation.total_rub <= budget_rub:
            best = calculation
            low = middle + 1
        else:
            high = middle - 1

    if best is None or best.car_price_rub < price_step_rub:
        return None

    # Округляем вниз: округление вверх вывело бы итог за бюджет.
    rounded_price = best.car_price_rub // price_step_rub * price_step_rub
    return calculate_total_from_rub(
        car_price_rub=rounded_price,
        age=age,
        engine_cc=engine_cc,
        eur_rub_rate=eur_rub_rate,
        delivery_rub=delivery_rub,
        other_costs_rub=other_costs_rub,
    )
