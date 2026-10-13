"""Money helpers shared by calculators and generated documents."""
from decimal import Decimal, ROUND_HALF_UP

def included_vat(gross, rate) -> Decimal:
    gross, rate = Decimal(str(gross)), Decimal(str(rate))
    if not gross.is_finite() or not rate.is_finite() or gross < 0 or not 0 <= rate <= 100:
        raise ValueError("Invalid price or VAT rate")
    return (gross * rate / (Decimal(100) + rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
