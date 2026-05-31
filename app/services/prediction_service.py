from sqlmodel import Session, select, func
from app.db.models import Job, JobStatus
from app.config import settings
from app.schemas.schemas import PredictionResponse
from app.services.connection_manager import connection_manager


LOW_PAPER_THRESHOLD_PCT = 15.0


def get_prediction(session: Session) -> PredictionResponse:
    result = session.exec(
        select(func.sum(Job.estimated_paper_cm)).where(
            Job.status == JobStatus.SUCCESS
        )
    ).first()

    used_cm: float = float(result or 0.0)
    initial_cm = settings.paper_roll_initial_meters * 100
    remaining_cm = max(0.0, initial_cm - used_cm)
    remaining_pct = round(remaining_cm / initial_cm * 100, 1) if initial_cm > 0 else 0.0

    avg_cm = settings.avg_paper_per_print_cm
    prints_left = int(remaining_cm / avg_cm) if avg_cm > 0 else 0

    if remaining_pct <= 0:
        message = "Paper roll is empty. Please replace immediately."
    elif remaining_pct < LOW_PAPER_THRESHOLD_PCT:
        message = f"Low paper warning: ~{prints_left} prints remaining. Replace soon."
    elif prints_left < 50:
        message = f"Paper running low: approximately {prints_left} prints left."
    else:
        message = f"Paper OK. Approximately {prints_left} prints remaining ({remaining_pct}%)."

    if connection_manager.is_connected():
        live_cm, live_pct = connection_manager.get_paper_info()
        if live_cm >= 0:
            remaining_cm = live_cm
            remaining_pct = live_pct
            prints_left = int(live_cm / avg_cm) if avg_cm > 0 else 0

    return PredictionResponse(
        paper_remaining_cm=round(remaining_cm, 1),
        paper_remaining_pct=remaining_pct,
        estimated_prints_left=prints_left,
        roll_eta_message=message,
        low_paper_warning=remaining_pct < LOW_PAPER_THRESHOLD_PCT,
    )
