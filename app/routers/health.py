from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        db_status = "up"
    except Exception as e:
        db_status = f"down: {e}"
    return {"status": "ok", "service": "aianalytics-service", "db": db_status}


@router.get("/")
def root():
    return {"service": "aianalytics-service", "version": "1.0.0", "port": 8084}
