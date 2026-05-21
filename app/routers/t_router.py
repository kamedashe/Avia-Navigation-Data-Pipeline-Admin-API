import os
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.services.task_status import task_statuses
from app.services.safety_check import assert_file_safe

router = APIRouter(prefix="/api/t", tags=["T File"])


@router.get("/")
def get_t_file():
    """Get the latest t file"""
    file_path = "./data/tfr.csv.gz"
    if os.path.exists(file_path):
        assert_file_safe("t", file_path, task_statuses=task_statuses)
        return FileResponse(path=file_path, filename="tfr.csv.gz", media_type="application/gzip")
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
    )
