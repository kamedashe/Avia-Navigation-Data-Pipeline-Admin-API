import os
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.services.task_status import task_statuses
from app.services.safety_check import assert_file_safe

router = APIRouter(prefix="/api/e", tags=["E File"])

@router.get("/")
def get_e_file():
    """Get the latest e file"""
    file_path = "./data/e.csv.gz"
    if os.path.exists(file_path):
        assert_file_safe("e", file_path, task_statuses=task_statuses)
        return FileResponse(path=file_path, filename="e.csv.gz", media_type="application/gzip")
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND, detail="File not found"
    )
