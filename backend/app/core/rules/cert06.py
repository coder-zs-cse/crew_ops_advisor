"""RULE-CERT-06 -- All certifications must be valid on the duty date.

Four cert types per crew member: licence, medical_class1, recurrent_training,
dangerous_goods. The reference implementation checks ``valid_to >= duty_date``
only; we check the same for the legality verdict (so exclusion reasons match)
but surface ``valid_from`` in the arithmetic trace, and flag a not-yet-valid
certificate separately so it is not silently ignored.
"""

from __future__ import annotations

from datetime import date

from ..models import ArithmeticStep, PairingDay, RuleVerdict
from .base import CoverContext

RULE_ID = "RULE-CERT-06"


def certs_valid_on(world, crew_id: str, on: date) -> tuple[bool, list[str]]:
    """Returns (ok, expired_cert_types) using the reference ``valid_to`` test."""
    expired = [
        cert.cert_type
        for cert in world.certs(crew_id).values()
        if cert.valid_to < on
    ]
    return (not expired), expired


class CertificationRule:
    rule_id = RULE_ID

    def evaluate_day(self, ctx: CoverContext, day: PairingDay, index: int) -> RuleVerdict:
        certs = ctx.world.certs(ctx.crew_id)
        d = day.date
        expired = sorted(c.cert_type for c in certs.values() if c.valid_to < d)
        not_yet = sorted(c.cert_type for c in certs.values() if c.valid_from > d)

        steps = [
            ArithmeticStep(
                cert.cert_type,
                f"valid {cert.valid_from.isoformat()} .. {cert.valid_to.isoformat()}",
                "EXPIRED" if cert.valid_to < d else ("NOT YET VALID" if cert.valid_from > d else "valid"),
            )
            for cert in sorted(certs.values(), key=lambda c: c.cert_type)
        ]

        if expired:
            message = f"RULE-CERT-06: certification invalid on {d}"
            verdict = "breach"
        elif not_yet:
            message = f"RULE-CERT-06: {', '.join(not_yet)} not yet effective on {d} (advisory)"
            verdict = "advisory"
        else:
            message = f"all certifications valid on {d}"
            verdict = "pass"

        return RuleVerdict(
            rule_id=RULE_ID,
            verdict=verdict,
            message=message,
            subject_crew_id=ctx.crew_id,
            subject_date=d,
            arithmetic=tuple(steps),
        )


def days_to_expiry(world, crew_id: str, as_of: date) -> list[dict]:
    out = []
    for cert in sorted(world.certs(crew_id).values(), key=lambda c: c.valid_to):
        out.append(
            {
                "crew_id": crew_id,
                "cert_type": cert.cert_type,
                "valid_from": cert.valid_from.isoformat(),
                "valid_to": cert.valid_to.isoformat(),
                "days_remaining": (cert.valid_to - as_of).days,
                "expired": cert.valid_to < as_of,
            }
        )
    return out
